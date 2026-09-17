import sqlite3

from desktop.models import AnalysisReport, FeedNote
from desktop.storage import LocalStore


def test_local_store_persists_task_notes_report_and_draft(tmp_path) -> None:
    store = LocalStore(tmp_path / "workspace.db")
    task_id = store.create_task("通勤效率", "竞品分析")
    note = FeedNote(note_id="note-1", title="标题", author="作者")

    store.save_notes(task_id, [note])
    store.save_report(
        task_id,
        AnalysisReport(
            summary="摘要",
            key_findings=["结论"],
            title_formulas=["场景 + 收益"],
            recommendations=["具体化收益"],
            raw={"summary": "摘要"},
        ),
    )
    store.save_draft(task_id, "下班后多出一小时", "正文内容", ["通勤效率"])

    assert store.get_task(task_id)["topic"] == "通勤效率"
    assert store.load_notes(task_id)[0].title == "标题"
    assert store.load_report(task_id).summary == "摘要"
    assert store.load_draft(task_id)["title"] == "下班后多出一小时"


def test_local_store_tracks_comment_opportunities_and_qa_entries(tmp_path) -> None:
    store = LocalStore(tmp_path / "workspace.db")
    task_id = store.create_task("收纳盒", "内容采集")
    store.save_comment_opportunities(
        task_id,
        [
            {
                "note_id": "n1",
                "note_title": "收纳好物",
                "xsec_token": "token",
                "comment_id": "c1",
                "commenter_name": "小红",
                "comment_content": "小户型能放吗？",
                "ai_reply": "可以的，尺寸适合桌面收纳。",
                "qa_matches": "尺寸说明",
                "score": 86,
                "score_breakdown": {
                    "intent": 22,
                    "relevance": 23,
                    "evidence": 18,
                    "naturalness": 12,
                    "conversion": 11,
                },
            }
        ],
    )
    store.save_qa_entry("尺寸多大", "长 20cm", "尺寸,大小")

    opportunities = store.list_comment_opportunities(task_id, "户型")
    assert opportunities[0]["status"] == "未评论"
    assert opportunities[0]["score"] == 86
    assert opportunities[0]["score_breakdown"]["intent"] == 22
    store.update_comment_opportunity_reply(opportunities[0]["id"], "手动修改后的回复")
    assert store.list_comment_opportunities(task_id)[0]["ai_reply"] == "手动修改后的回复"
    assert store.comment_opportunity_stats(task_id) == {"total": 1, "commented": 0, "pending": 1}
    store.mark_comment_opportunity_commented(opportunities[0]["id"])
    assert store.comment_opportunity_stats(task_id)["commented"] == 1
    assert store.list_qa_entries("尺寸")[0]["answer"] == "长 20cm"


def test_local_store_deletes_qa_entry(tmp_path) -> None:
    store = LocalStore(tmp_path / "workspace.db")
    entry_id = store.save_qa_entry("问题", "答案", "关键词")

    assert store.delete_qa_entry(entry_id) is True
    assert store.list_qa_entries() == []
    assert store.delete_qa_entry(entry_id) is False


def test_local_store_records_collection_run_and_note_timeline(tmp_path) -> None:
    store = LocalStore(tmp_path / "workspace.db")
    task_id = store.create_task("通勤效率", "内容采集")

    run_id = store.start_collection_run(task_id, "关键词搜索", "通勤效率")
    assert store.list_collection_runs(task_id)[0]["status"] == "running"

    store.save_notes(task_id, [FeedNote(note_id="n1", title="标题")], run_id=run_id)
    store.finish_collection_run(
        run_id, status="success", requested=2, fetched=1, failed=1, message="1 篇详情不可访问"
    )

    run = store.list_collection_runs(task_id)[0]
    assert (run["action"], run["source"], run["status"]) == ("关键词搜索", "通勤效率", "success")
    assert run["started_at"] and run["finished_at"]
    assert (run["requested"], run["fetched"], run["failed"]) == (2, 1, 1)
    assert run["message"] == "1 篇详情不可访问"

    row = store.list_note_timeline(task_id)[0]
    assert row["run_id"] == run_id
    assert row["collected_at"] == row["last_seen_at"]

    summary = store.collection_summary(task_id)
    assert summary["runs"] == 1
    assert summary["succeeded"] == 1
    assert summary["fetched"] == 1
    assert summary["failed_items"] == 1
    assert summary["first_started_at"] == run["started_at"]
    assert summary["last_activity_at"] == run["finished_at"]


def test_local_store_keeps_first_collected_at_on_recollect(tmp_path) -> None:
    store = LocalStore(tmp_path / "workspace.db")
    task_id = store.create_task("通勤效率", "内容采集")

    first_run = store.start_collection_run(task_id, "关键词搜索", "通勤效率")
    store.save_notes(task_id, [FeedNote(note_id="n1", title="第一次标题")], run_id=first_run)
    first_collected_at = store.list_note_timeline(task_id)[0]["collected_at"]

    second_run = store.start_collection_run(task_id, "关键词搜索", "通勤效率")
    store.save_notes(task_id, [FeedNote(note_id="n1", title="第二次标题")], run_id=second_run)

    row = store.list_note_timeline(task_id)[0]
    assert row["title"] == "第二次标题"
    assert row["collected_at"] == first_collected_at
    assert row["run_id"] == second_run
    assert store.load_notes(task_id)[0].title == "第二次标题"
    assert store.collection_summary(task_id)["runs"] == 2


def test_local_store_uses_wal_and_migrates_legacy_db(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ready',
            progress INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE notes (
            task_id TEXT NOT NULL,
            note_id TEXT NOT NULL,
            title TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (task_id, note_id),
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        """
    )
    legacy.execute(
        "INSERT INTO tasks(id, topic, task_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("t1", "老任务", "内容采集", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    legacy.execute(
        "INSERT INTO notes(task_id, note_id, title, payload) VALUES (?, ?, ?, ?)",
        ("t1", "n1", "老笔记", '{"note_id": "n1", "title": "老笔记"}'),
    )
    legacy.commit()
    legacy.close()

    store = LocalStore(path)

    # 老库被补齐：缺失的时间列按任务创建时间回填，不留下无法解释的空值
    row = store.list_note_timeline("t1")[0]
    assert row["collected_at"] == "2026-01-01T00:00:00+00:00"
    assert row["last_seen_at"] == row["collected_at"]
    assert row["run_id"] == ""
    assert store.list_collection_runs("t1") == []
    assert store.collection_summary("t1")["runs"] == 0
    assert store.load_notes("t1")[0].title == "老笔记"

    # WAL 是写进库文件的持久设置，换一条连接也能读到
    probe = sqlite3.connect(path)
    assert probe.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    probe.close()

    # foreign_keys 确实在 store 自己的连接上生效，否则 ON DELETE CASCADE 只是装饰
    with store._connect() as connection:
        connection.execute("DELETE FROM tasks WHERE id = ?", ("t1",))
    assert store.load_notes("t1") == []

    LocalStore(path)  # 重复打开不报错：补列与建索引都是幂等的
