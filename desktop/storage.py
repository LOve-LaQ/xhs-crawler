from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import AnalysisReport, FeedNote


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """幂等补列：SQLite 不支持 ADD COLUMN IF NOT EXISTS。"""
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


class LocalStore:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            data_root = Path(os.environ.get("APPDATA", Path.home())) / "XHS Insight"
            path = data_root / "workspace.db"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        # timeout 是拿不到锁时的等待上限：后台线程（QThreadPool）写入的同时主线程可能
        # 正在刷新任务列表，默认的 rollback journal 下写事务会阻塞读，超时即报
        # database is locked，因此这里既放宽等待，也切到读写互不阻塞的 WAL。
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        # WAL 是写入库文件的持久设置，设一次即长期生效；synchronous 则是每连接设置。
        # 代价是库旁边会多出 -wal / -shm 两个文件：备份或拷贝时必须一起带走，
        # 只复制 .db 会丢掉尚未 checkpoint 的最新数据。
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        # 外键默认关闭，不显式打开则下面所有 ON DELETE CASCADE 都是装饰。
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    progress INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notes (
                    task_id TEXT NOT NULL,
                    note_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    collected_at TEXT NOT NULL DEFAULT '',
                    last_seen_at TEXT NOT NULL DEFAULT '',
                    run_id TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (task_id, note_id),
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS reports (
                    task_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS comment_opportunities (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    note_id TEXT NOT NULL,
                    note_title TEXT NOT NULL,
                    xsec_token TEXT NOT NULL DEFAULT '',
                    comment_id TEXT NOT NULL,
                    commenter_name TEXT NOT NULL DEFAULT '',
                    comment_content TEXT NOT NULL,
                    ai_reply TEXT NOT NULL DEFAULT '',
                    qa_matches TEXT NOT NULL DEFAULT '',
                    score INTEGER NOT NULL DEFAULT 0,
                    score_breakdown TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT '未评论',
                    created_at TEXT NOT NULL,
                    commented_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(task_id, comment_id),
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS qa_entries (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    keywords TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collection_runs (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT '',
                    requested INTEGER NOT NULL DEFAULT 0,
                    fetched INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                -- 采集日志是唯一会持续增长的表，两条索引分别服务「按任务查历史」
                -- 与「全局按时间倒序巡察」；其余表的主键 / UNIQUE 已覆盖各自查询路径。
                CREATE INDEX IF NOT EXISTS idx_collection_runs_task
                    ON collection_runs(task_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_collection_runs_started
                    ON collection_runs(started_at DESC);
                -- 任务列表是唯一没有索引支撑的高频排序查询（updated_at DESC LIMIT）。
                CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);
                """
            )
            # 老库缺列时补齐；新库由上面的建表语句直接建全，这里不会命中。
            _ensure_column(
                connection, "comment_opportunities", "score", "INTEGER NOT NULL DEFAULT 0"
            )
            _ensure_column(
                connection, "comment_opportunities", "score_breakdown", "TEXT NOT NULL DEFAULT '{}'"
            )
            _ensure_column(connection, "notes", "collected_at", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "notes", "last_seen_at", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "notes", "run_id", "TEXT NOT NULL DEFAULT ''")
            # 老数据无法还原真实采集时刻，用所属任务的创建时间回填：既是可解释的下界，
            # 也保证「什么时候采集的」这一列不会留空。
            connection.execute(
                "UPDATE notes SET collected_at = COALESCE(NULLIF(collected_at, ''), "
                "(SELECT created_at FROM tasks WHERE tasks.id = notes.task_id), '') "
                "WHERE collected_at = ''"
            )
            connection.execute(
                "UPDATE notes SET last_seen_at = collected_at WHERE last_seen_at = ''"
            )

    def create_task(self, topic: str, task_type: str) -> str:
        task_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tasks(id, topic, task_type, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, topic.strip(), task_type, now, now),
            )
        return task_id

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        error: str | None = None,
    ) -> None:
        updates: list[str] = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if progress is not None:
            updates.append("progress = ?")
            values.append(max(0, min(100, progress)))
        if error is not None:
            updates.append("error = ?")
            values.append(error)
        values.append(task_id)
        with self._connect() as connection:
            connection.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", values)

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"任务不存在: {task_id}")
        return dict(row)

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    # --- 采集审计：回答「这份数据是什么时候、以什么方式采到的」 -----------------

    def start_collection_run(self, task_id: str, action: str, source: str = "") -> str:
        """登记一次采集动作，返回 run_id 供收尾时回填结果。"""
        run_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO collection_runs(id, task_id, action, source, status, started_at)
                VALUES (?, ?, ?, ?, 'running', ?)
                """,
                (run_id, task_id, action, source.strip(), _now()),
            )
        return run_id

    def finish_collection_run(
        self,
        run_id: str,
        *,
        status: str,
        requested: int = 0,
        fetched: int = 0,
        failed: int = 0,
        message: str = "",
    ) -> None:
        """收尾一次采集，status 取 success / failed / cancelled。"""
        if not run_id:
            return
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE collection_runs
                SET status = ?, finished_at = ?, requested = ?, fetched = ?, failed = ?,
                    message = ?
                WHERE id = ?
                """,
                (
                    status,
                    _now(),
                    max(0, int(requested)),
                    max(0, int(fetched)),
                    max(0, int(failed)),
                    message,
                    run_id,
                ),
            )

    def list_collection_runs(
        self, task_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """采集日志，按开始时间倒序；不传 task_id 即全局巡察视图。"""
        limited = max(1, int(limit))
        with self._connect() as connection:
            if task_id:
                rows = connection.execute(
                    "SELECT * FROM collection_runs WHERE task_id = ? "
                    "ORDER BY started_at DESC, rowid DESC LIMIT ?",
                    (task_id, limited),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM collection_runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
                    (limited,),
                ).fetchall()
        return [dict(row) for row in rows]

    def collection_summary(self, task_id: str) -> dict[str, Any]:
        """任务的采集概览：批次次数、成败、条数、时间跨度。"""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS runs,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS succeeded,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_runs,
                       SUM(fetched) AS fetched,
                       SUM(failed) AS failed_items,
                       MIN(started_at) AS first_started_at,
                       MAX(COALESCE(NULLIF(finished_at, ''), started_at)) AS last_activity_at
                FROM collection_runs WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        return {
            "runs": int(row["runs"] or 0),
            "succeeded": int(row["succeeded"] or 0),
            "failed_runs": int(row["failed_runs"] or 0),
            "fetched": int(row["fetched"] or 0),
            "failed_items": int(row["failed_items"] or 0),
            "first_started_at": row["first_started_at"] or "",
            "last_activity_at": row["last_activity_at"] or "",
        }

    def list_note_timeline(self, task_id: str) -> list[dict[str, Any]]:
        """逐条笔记的采集时间线：首次采到、最近一次见到、来自哪个批次。"""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT note_id, title, collected_at, last_seen_at, run_id FROM notes "
                "WHERE task_id = ? ORDER BY collected_at, rowid",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_notes(self, task_id: str, notes: list[FeedNote], *, run_id: str = "") -> None:
        """写入笔记。

        collected_at 只在首次入库时落定，后续重复采集只推进 last_seen_at 与 run_id，
        否则「这条笔记第一次是什么时候采到的」会被下一次采集覆盖掉，审计就失真了。
        """
        now = _now()
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO notes(
                    task_id, note_id, title, payload, collected_at, last_seen_at, run_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, note_id) DO UPDATE SET
                    title = excluded.title,
                    payload = excluded.payload,
                    last_seen_at = excluded.last_seen_at,
                    run_id = excluded.run_id
                """,
                [
                    (
                        task_id,
                        note.note_id,
                        note.title,
                        json.dumps(note.to_dict(), ensure_ascii=False),
                        now,
                        now,
                        run_id,
                    )
                    for note in notes
                ],
            )

    def load_notes(self, task_id: str) -> list[FeedNote]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM notes WHERE task_id = ? ORDER BY rowid", (task_id,)
            ).fetchall()
        return [FeedNote(**json.loads(row["payload"])) for row in rows]

    def save_report(self, task_id: str, report: AnalysisReport) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO reports(task_id, payload, created_at) VALUES (?, ?, ?)",
                (task_id, json.dumps(report.raw or report.__dict__, ensure_ascii=False), _now()),
            )

    def load_report(self, task_id: str) -> AnalysisReport | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM reports WHERE task_id = ?", (task_id,)
            ).fetchone()
        return AnalysisReport.from_dict(json.loads(row["payload"])) if row else None

    def save_draft(self, task_id: str, title: str, content: str, tags: list[str]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO drafts(task_id, title, content, tags, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, title, content, json.dumps(tags, ensure_ascii=False), _now()),
            )

    def load_draft(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT title, content, tags, updated_at FROM drafts WHERE task_id = ?", (task_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "title": row["title"],
            "content": row["content"],
            "tags": json.loads(row["tags"]),
            "updated_at": row["updated_at"],
        }

    def save_comment_opportunities(self, task_id: str, items: list[dict[str, Any]]) -> None:
        now = _now()
        with self._connect() as connection:
            for item in items:
                comment_id = str(item.get("comment_id") or item.get("commentId") or "")
                if not comment_id:
                    continue
                existing = connection.execute(
                    "SELECT id, status, commented_at FROM comment_opportunities "
                    "WHERE task_id = ? AND comment_id = ?",
                    (task_id, comment_id),
                ).fetchone()
                values = (
                    existing["id"] if existing else uuid.uuid4().hex,
                    task_id,
                    str(item.get("note_id", "")),
                    str(item.get("note_title", "")),
                    str(item.get("xsec_token", "")),
                    comment_id,
                    str(item.get("commenter_name", "")),
                    str(item.get("comment_content", "")),
                    str(item.get("ai_reply") or item.get("reply") or ""),
                    str(item.get("qa_matches") or item.get("qaMatches") or ""),
                    max(0, min(100, int(item.get("score", 0) or 0))),
                    json.dumps(
                        item.get("score_breakdown") or item.get("scoreFactors") or {},
                        ensure_ascii=False,
                    ),
                    str(item.get("status") or (existing["status"] if existing else "未评论")),
                    now,
                    existing["commented_at"] if existing else "",
                )
                connection.execute(
                    """
                    INSERT OR REPLACE INTO comment_opportunities(
                        id, task_id, note_id, note_title, xsec_token, comment_id, commenter_name,
                        comment_content, ai_reply, qa_matches, score, score_breakdown, status,
                        created_at, commented_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )

    def list_comment_opportunities(self, task_id: str, query: str = "") -> list[dict[str, Any]]:
        like = f"%{query.strip()}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM comment_opportunities
                WHERE task_id = ? AND (? = '' OR note_title LIKE ? OR commenter_name LIKE ?
                    OR comment_content LIKE ? OR ai_reply LIKE ? OR qa_matches LIKE ?)
                ORDER BY CASE status WHEN '未评论' THEN 0 ELSE 1 END, created_at DESC
                """,
                (task_id, query.strip(), like, like, like, like, like),
            ).fetchall()
        opportunities = []
        for row in rows:
            item = dict(row)
            try:
                item["score_breakdown"] = json.loads(item.get("score_breakdown") or "{}")
            except (TypeError, json.JSONDecodeError):
                item["score_breakdown"] = {}
            opportunities.append(item)
        return opportunities

    def comment_opportunity_stats(self, task_id: str) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = '已评论' THEN 1 ELSE 0 END) AS commented
                FROM comment_opportunities WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        total = int(row["total"] or 0)
        commented = int(row["commented"] or 0)
        return {"total": total, "commented": commented, "pending": total - commented}

    def mark_comment_opportunity_commented(self, opportunity_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE comment_opportunities SET status = '已评论', commented_at = ? WHERE id = ?",
                (_now(), opportunity_id),
            )

    def update_comment_opportunity_reply(self, opportunity_id: str, reply: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE comment_opportunities SET ai_reply = ? WHERE id = ?",
                (reply, opportunity_id),
            )

    def update_comment_opportunity_ai(
        self,
        opportunity_id: str,
        *,
        reply: str,
        qa_matches: str,
        score: int,
        score_breakdown: dict[str, Any],
        status: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE comment_opportunities
                SET ai_reply = ?, qa_matches = ?, score = ?, score_breakdown = ?, status = ?
                WHERE id = ?
                """,
                (
                    reply,
                    qa_matches,
                    max(0, min(100, int(score))),
                    json.dumps(score_breakdown, ensure_ascii=False),
                    status,
                    opportunity_id,
                ),
            )

    def save_qa_entry(self, question: str, answer: str, keywords: str = "") -> str:
        entry_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO qa_entries(id, question, answer, keywords, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry_id, question.strip(), answer.strip(), keywords.strip(), _now()),
            )
        return entry_id

    def list_qa_entries(self, query: str = "") -> list[dict[str, Any]]:
        like = f"%{query.strip()}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM qa_entries
                WHERE ? = '' OR question LIKE ? OR answer LIKE ? OR keywords LIKE ?
                ORDER BY updated_at DESC
                """,
                (query.strip(), like, like, like),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_qa_entry(self, entry_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM qa_entries WHERE id = ?", (entry_id,))
        return cursor.rowcount > 0
