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
