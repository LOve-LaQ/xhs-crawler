import json
import zipfile

from desktop.models import AnalysisReport, FeedNote
from desktop.workspace import WorkspaceArchive, write_xlsx


def test_write_xlsx_creates_an_excel_package(tmp_path) -> None:
    path = tmp_path / "table.xlsx"
    write_xlsx(path, "数据", ["名称", "数量"], [["样本", 3]])

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert "xl/workbook.xml" in names
        assert "xl/worksheets/sheet1.xml" in names
        assert "样本" in archive.read("xl/worksheets/sheet1.xml").decode("utf-8")


def test_workspace_archive_writes_task_artifacts(tmp_path) -> None:
    archive = WorkspaceArchive()
    archive.set_root(tmp_path / "workspace")
    note = FeedNote(note_id="n1", title="标题", body="正文")

    archive.save_samples("task-1", "通勤效率", [note])
    archive.save_report(
        "task-1",
        "通勤效率",
        AnalysisReport(
            summary="综合结论",
            key_findings=["关键发现内容"],
            title_formulas=["标题公式内容"],
            evidence=[{"noteId": "n1", "analysis": "标题的利益点明确"}],
        ),
        [note],
    )
    archive.save_drafts(
        "task-1",
        "通勤效率",
        [{"title": "草稿标题", "content": "正文", "tags": ["标签"]}],
    )

    sample_json = next((tmp_path / "workspace" / "samples").glob("*/notes.json"))
    report_json = next((tmp_path / "workspace" / "reports").glob("*/report.json"))
    draft_json = next((tmp_path / "workspace" / "drafts").glob("*/drafts.json"))
    assert json.loads(sample_json.read_text(encoding="utf-8"))[0]["title"] == "标题"
    assert json.loads(report_json.read_text(encoding="utf-8"))["evidence"][0]["noteId"] == "n1"
    assert json.loads(draft_json.read_text(encoding="utf-8"))[0]["title"] == "草稿标题"
    assert list((tmp_path / "workspace" / "samples").glob("*/notes.xlsx"))
    assert list((tmp_path / "workspace" / "reports").glob("*/report.xlsx"))
    assert list((tmp_path / "workspace" / "drafts").glob("*/drafts.xlsx"))
    report_xlsx = next((tmp_path / "workspace" / "reports").glob("*/report.xlsx"))
    with zipfile.ZipFile(report_xlsx) as archive_file:
        report_sheet = archive_file.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "样本ID" in report_sheet
    assert "分析结论" in report_sheet
    assert "综合结论" in report_sheet
    assert "关键发现内容" in report_sheet
    assert "标题公式内容" in report_sheet


def test_workspace_finds_existing_folder_for_task_type(tmp_path) -> None:
    archive = WorkspaceArchive()
    archive.set_root(tmp_path / "workspace")
    note = FeedNote(note_id="n1", title="标题")
    archive.save_samples("task-1", "通勤效率", [note])
    archive.save_report("task-1", "通勤效率", AnalysisReport(summary="结论"), [note])

    folder = archive.find_task_folder("task-1", "通勤效率", "竞品分析")

    assert folder is not None
    assert folder.parent.name == "reports"


def test_workspace_exports_qa_library_to_excel(tmp_path) -> None:
    archive = WorkspaceArchive()
    archive.set_root(tmp_path / "workspace")
    archive.save_qa_entries(
        [{"question": "尺寸多大", "answer": "20cm", "keywords": "尺寸", "updated_at": "2026-08-15"}]
    )

    qa_xlsx = tmp_path / "workspace" / "qa" / "qa_library.xlsx"
    assert qa_xlsx.exists()
    with zipfile.ZipFile(qa_xlsx) as archive_file:
        sheet = archive_file.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "标准答案" in sheet
    assert "20cm" in sheet


def test_workspace_exports_comment_table_without_session_secrets(tmp_path) -> None:
    archive = WorkspaceArchive()
    archive.set_root(tmp_path / "workspace")
    archive.save_comment_table(
        "task-1",
        "通勤效率",
        [
            {
                "note_id": "n1",
                "note_title": "帖子标题",
                "commenter_name": "用户A",
                "comment_content": "求链接",
                "ai_reply": "可以私信了解",
                "qa_matches": "尺寸说明",
                "score": 92,
                "status": "未评论",
                "xsec_token": "secret-token",
            }
        ],
    )

    comment_xlsx = tmp_path / "workspace" / "reports" / "通勤效率_task-1" / "评论表.xlsx"
    assert comment_xlsx.exists()
    with zipfile.ZipFile(comment_xlsx) as archive_file:
        sheet = archive_file.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "原评论" in sheet
    assert "AI 回复建议" in sheet
    assert "求链接" in sheet
    assert "可以私信了解" in sheet
    assert "secret-token" not in sheet


def test_workspace_exports_comment_table_to_collection_task_folder(tmp_path) -> None:
    archive = WorkspaceArchive()
    archive.set_root(tmp_path / "workspace")

    archive.save_comment_table(
        "task-2",
        "采集主题",
        [{"note_title": "帖子", "comment_content": "求", "ai_reply": "可以了解"}],
        task_type="内容采集",
    )

    assert (tmp_path / "workspace" / "samples" / "采集主题_task-2" / "评论表.xlsx").exists()
