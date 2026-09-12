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


class LocalStore:
    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            data_root = Path(os.environ.get("APPDATA", Path.home())) / "XHS Insight"
            path = data_root / "workspace.db"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
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
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(comment_opportunities)").fetchall()
            }
            if "score" not in columns:
                connection.execute(
                    "ALTER TABLE comment_opportunities ADD COLUMN score INTEGER NOT NULL DEFAULT 0"
                )
            if "score_breakdown" not in columns:
                connection.execute(
                    "ALTER TABLE comment_opportunities ADD COLUMN score_breakdown "
                    "TEXT NOT NULL DEFAULT '{}'"
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

    def save_notes(self, task_id: str, notes: list[FeedNote]) -> None:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO notes(task_id, note_id, title, payload)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        task_id,
                        note.note_id,
                        note.title,
                        json.dumps(note.to_dict(), ensure_ascii=False),
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
