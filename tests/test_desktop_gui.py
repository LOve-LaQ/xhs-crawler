import json
import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QTableWidget,
    QTextBrowser,
)

from desktop import ui
from desktop.config import AppSettings
from desktop.main import MainWindow
from desktop.models import AnalysisReport, FeedNote
from desktop.storage import LocalStore


def test_main_window_exposes_workbench_actions(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))

    assert window.windowTitle() == "XHS Insight"
    assert window.search_input.placeholderText() == "搜索主题，例如：通勤效率"
    assert window.collect_button.text() == "开始采集"
    assert window.analyze_button.text() == "分析选中内容"
    assert window.analysis_vertical_splitter.orientation() == Qt.Orientation.Vertical
    assert window.dashboard_vertical_splitter.orientation() == Qt.Orientation.Vertical
    assert window.analysis_task_table.columnCount() == 7
    assert window.analysis_task_table.horizontalHeaderItem(5).text() == "文件夹"
    assert window.analysis_task_table.horizontalHeaderItem(6).text() == "采集日志"
    window.analysis_vertical_splitter.setSizes([260, 420])
    assert window.analysis_vertical_splitter.sizes()[0] > 0
    assert window.analysis_vertical_splitter.sizes()[1] > 0
    original_sizes = window.analysis_vertical_splitter.sizes()
    window.analysis_vertical_splitter.setSizes([120, 560])
    app.processEvents()
    resized_sizes = window.analysis_vertical_splitter.sizes()
    assert resized_sizes[0] != original_sizes[0]
    assert resized_sizes[1] != original_sizes[1]
    assert window.analysis_vertical_splitter.handleWidth() >= 8
    assert window.dashboard_log_view.toPlainText().startswith("等待任务开始")
    window.show_status("正在获取样本")
    assert "正在获取样本" in window.dashboard_log_view.toPlainText()
    window.copy_text("可复制内容", "测试文本")
    assert QApplication.clipboard().text() == "可复制内容"
    assert window.copy_report_button.text() == "复制报告"
    handle = window.analysis_vertical_splitter.handle(1)
    before_drag = window.analysis_vertical_splitter.sizes()
    center = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
    QTest.mouseMove(handle, QPoint(center.x(), center.y() + 30), 50)
    QTest.mouseRelease(
        handle,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(center.x(), center.y() + 30),
    )
    assert window.analysis_vertical_splitter.sizes() != before_drag
    window.dashboard_vertical_splitter.setSizes([620, 150])
    assert all(size > 0 for size in window.dashboard_vertical_splitter.sizes())

    window.navigate_to("报告中心")
    assert window.page_stack.currentWidget() is window.report_page
    assert window.nav_buttons["报告中心"].property("active") is True

    window.navigate_to("内容创作")
    assert window.page_stack.currentWidget() is window.creator_page

    window.navigate_to("执行日志")
    assert window.page_stack.currentWidget() is window.logs_page

    window.close()
    app.processEvents()


def test_copy_button_confirms_success_on_the_clicked_button(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    button = window._copy_button("标题", lambda: "可复制标题")

    button.click()

    assert QApplication.clipboard().text() == "可复制标题"
    assert button.text() == "已复制"
    assert "已复制标题" in button.toolTip()

    window.close()
    app.processEvents()


def test_batch_draft_generation_immediately_enters_loading_state(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    window.current_report = AnalysisReport(summary="分析结论")
    window.current_notes = [FeedNote(note_id="n1", title="参考帖子")]
    window.set_creator_reference_notes(["n1"])
    window.creator_product_info.setPlainText("收纳产品")
    window.creator_asset_paths = [tmp_path / "product.png"]
    captured = {}

    def fake_run_worker(function, **kwargs):
        captured["function"] = function
        captured["kwargs"] = kwargs

    window._run_worker = fake_run_worker
    window.generate_product_drafts()

    assert not window.creator_generate_button.isEnabled()
    assert window.creator_generate_button.text() == "批量生成中..."
    assert window.runtime_state_label.text() == "生成商品草稿中"
    assert captured["function"] == window.analysis_service.generate_product_drafts

    window.close()
    app.processEvents()


def test_operations_workflow_entry_points_set_search_strategy(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))

    assert "运营工作流" in window.nav_buttons
    assert window.workflow_page is not None
    assert set(window.workflow_buttons) == {"竞品分析", "热点追踪", "内容创作", "互动管理"}

    window.workflow_keyword_input.setText("通勤效率")
    window.start_workflow("热点追踪")

    assert window.active_workflow == "热点追踪"
    assert window.search_input.text() == "通勤效率"
    assert window.sort_combo.currentText() == "最新"
    assert window.page_stack.currentWidget() is window.dashboard_page

    window.close()
    app.processEvents()


def test_creator_exposes_product_assets_and_batch_controls(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))

    assert window.creator_product_info.placeholderText().startswith("填写产品卖点")
    assert window.creator_asset_path.isReadOnly()
    assert window.creator_batch_count.value() == 20
    window.creator_batch_count.setValue(7)
    assert window.creator_batch_count.value() == 7
    assert window.creator_batch_selector.count() == 0

    window.close()
    app.processEvents()


def test_creator_can_keep_its_own_reference_sample_selection(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    window.current_notes = [
        FeedNote(note_id="note-1", title="样本一", author="作者一"),
        FeedNote(note_id="note-2", title="样本二", author="作者二"),
    ]

    window.set_creator_reference_notes(["note-2"])

    assert window.creator_reference_note_ids == {"note-2"}
    assert [note.note_id for note in window.creator_reference_notes()] == ["note-2"]
    assert "已选择 1 篇" in window.creator_reference_summary.text()

    window.close()
    app.processEvents()


def test_note_selection_shortcuts_update_every_row(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    notes = [
        FeedNote(note_id="note-1", title="样本一", author="作者一"),
        FeedNote(note_id="note-2", title="样本二", author="作者二"),
        FeedNote(note_id="note-3", title="样本三", author="作者三"),
    ]
    window.populate_notes(notes)

    assert window.select_all_button.text() == "全选"
    assert window.clear_all_button.text() == "取消全选"

    window.clear_all_notes()
    assert all(
        window.note_table.item(row, 0).checkState() == Qt.CheckState.Unchecked
        for row in range(window.note_table.rowCount())
    )

    window.select_all_notes()
    assert all(
        window.note_table.item(row, 0).checkState() == Qt.CheckState.Checked
        for row in range(window.note_table.rowCount())
    )

    window.close()
    app.processEvents()


def test_collection_page_exposes_comment_outreach_and_qa_controls(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))

    assert window.collection_notes_table.columnCount() == 6
    assert window.comment_opportunity_table.columnCount() == 8
    assert window.collection_splitter.count() == 2
    assert window.collection_outreach_splitter.count() == 2
    assert window.collection_outreach_splitter.handleWidth() >= 8
    assert window.qa_table.maximumHeight() == 16777215
    assert window.collection_comment_limit.value() == 20
    assert window.comment_search.placeholderText() == "搜索帖子、用户、评论或建议"
    assert window.comment_score_guide_button.text() == "评分标准"
    assert window.generate_comment_button.text() == "AI 筛选建议"
    assert window.qa_question_input.placeholderText() == "问题"
    assert window.qa_answer_input.placeholderText() == "标准答案"
    assert window.qa_table.columnCount() == 5
    assert window.qa_toggle_button.text() == "收起问答库"

    window.close()
    app.processEvents()


def test_ai_comment_filter_shows_immediate_running_state(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    task_id = window.store.create_task("收纳", "内容采集")
    window.current_task_id = task_id
    window.current_notes = [FeedNote(note_id="n1", title="帖子")]
    window.store.save_comment_opportunities(
        task_id,
        [
            {
                "note_id": "n1",
                "note_title": "帖子",
                "comment_id": "c1",
                "commenter_name": "用户",
                "comment_content": "求",
            }
        ],
    )
    window.collection_product_info.setText("收纳用品")
    captured = {}

    def fake_run_worker(function, **kwargs):
        captured["function"] = function
        captured["kwargs"] = kwargs

    window._run_worker = fake_run_worker
    window.generate_comment_suggestions()

    assert window.generate_comment_button.text() == "AI 筛选中..."
    assert window.comment_ai_status_label.text().startswith("正在分析")
    assert "1 条" in window.comment_ai_status_label.text()
    assert captured["function"] == window._generate_comment_suggestions

    window.close()
    app.processEvents()


def test_qa_library_can_collapse_and_delete_rows(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    window.store.save_qa_entry("如何使用", "标准答案", "使用")
    window.refresh_qa_entries()

    assert window.qa_table.columnCount() == 5
    assert not window.qa_section.isAncestorOf(window.qa_toggle_button)
    delete_button = window.qa_table.cellWidget(0, 4)
    assert delete_button is not None
    delete_button.click()
    assert window.store.list_qa_entries() == []

    assert not window.qa_section.isHidden()
    window.qa_toggle_button.click()
    assert window.qa_section.isHidden()
    assert window.qa_toggle_button.text() == "展开问答库"
    window.qa_toggle_button.click()
    assert not window.qa_section.isHidden()
    assert window.qa_toggle_button.text() == "收起问答库"

    window.close()
    app.processEvents()


def test_comment_table_syncs_into_the_analysis_task_folder(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    window.workspace.set_root(tmp_path / "workspace")
    task_id = window.store.create_task("收纳", "竞品分析")
    window.current_task_id = task_id
    window.store.save_comment_opportunities(
        task_id,
        [
            {
                "note_id": "n1",
                "note_title": "收纳帖子",
                "comment_id": "c1",
                "commenter_name": "用户",
                "comment_content": "求链接",
                "ai_reply": "可以私信了解",
                "score": 90,
                "status": "未评论",
            }
        ],
    )

    window._sync_comment_table()

    path = tmp_path / "workspace" / "reports" / f"收纳_{task_id[:8]}" / "评论表.xlsx"
    assert path.exists()
    with zipfile.ZipFile(path) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "可以私信了解" in sheet

    window.close()
    app.processEvents()


def test_existing_task_comment_table_is_backfilled_before_opening_folder(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    window.workspace.set_root(tmp_path / "workspace")
    task_id = window.store.create_task("采集主题", "内容采集")
    window.store.save_comment_opportunities(
        task_id,
        [
            {
                "note_id": "n1",
                "note_title": "帖子",
                "comment_id": "c1",
                "commenter_name": "用户",
                "comment_content": "求",
                "ai_reply": "可以了解",
            }
        ],
    )

    window._sync_comment_table_for_task(window.store.get_task(task_id))

    path = tmp_path / "workspace" / "samples" / f"采集主题_{task_id[:8]}" / "评论表.xlsx"
    assert path.exists()

    window.close()
    app.processEvents()


def test_comment_score_guide_opens_with_public_scoring_standard(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))

    window.comment_score_guide_button.click()
    app.processEvents()

    dialog = window.comment_score_dialog
    assert dialog.isVisible()
    assert dialog.windowTitle() == "评论评分标准"
    text = dialog.findChild(QTextBrowser).toHtml()
    assert "需求明确度" in text
    assert "自然承接与获客潜力" in text
    assert "人工确认" in text

    dialog.close()
    window.close()
    app.processEvents()


def test_collection_tables_ellipsize_long_text_with_hover_tooltips(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    long_title = "这是一个非常长的帖子标题，用于验证表格不会把标题区域无限撑开"
    window.populate_collection_notes(
        [FeedNote(note_id="n1", title=long_title, author="作者", liked_count="1")]
    )
    title_item = window.collection_notes_table.item(0, 0)

    assert title_item.toolTip() == long_title
    assert window.collection_notes_table.wordWrap() is False
    assert window.collection_notes_table.textElideMode() == Qt.TextElideMode.ElideRight
    assert window.collection_notes_table.cellWidget(0, 3).minimumWidth() >= 104
    assert window.collection_notes_table.cellWidget(0, 4).minimumWidth() >= 116

    task_id = window.store.create_task("收纳", "内容采集")
    window.current_task_id = task_id
    window.store.save_comment_opportunities(
        task_id,
        [
            {
                "note_id": "n1",
                "note_title": long_title,
                "comment_id": "c1",
                "commenter_name": "用户",
                "comment_content": "这是一段很长的原评论内容，用于悬停查看完整文本",
                "ai_reply": "这是一段很长的 AI 回复建议，用于悬停查看完整文本",
                "qa_matches": "尺寸说明",
            }
        ],
    )
    window.refresh_comment_opportunities()
    assert window.comment_opportunity_table.item(0, 1).toolTip() == long_title
    reply_cell = window.comment_opportunity_table.cellWidget(0, 4)
    reply_editor = reply_cell.findChild(QLineEdit)
    assert isinstance(reply_editor, QLineEdit)
    assert reply_editor.text().startswith("这是一段很长的 AI")
    assert reply_editor.cursorPosition() == 0
    assert reply_editor.maximumHeight() <= 30
    assert reply_editor.minimumWidth() == 0
    reply_editor.setText("手动修改后的回复建议")
    reply_editor.editingFinished.emit()
    assert window.store.list_comment_opportunities(task_id)[0]["ai_reply"] == "手动修改后的回复建议"
    actions = window.comment_opportunity_table.cellWidget(0, 7)
    assert actions.layout().itemAt(2).widget().minimumWidth() >= 112

    window.store.save_qa_entry("如何使用", "这是一段很长的标准答案，用于悬停查看完整内容", "使用")
    window.refresh_qa_entries()
    assert window.qa_table.item(0, 1).toolTip().startswith("这是一段很长的标准答案")

    window.close()
    app.processEvents()


def test_comment_score_is_displayed_with_range_color_and_row_height(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))
    task_id = window.store.create_task("收纳", "内容采集")
    window.current_task_id = task_id
    window.store.save_comment_opportunities(
        task_id,
        [
            {
                "note_id": "n1",
                "note_title": "帖子",
                "comment_id": "c1",
                "commenter_name": "用户",
                "comment_content": "想了解尺寸",
                "ai_reply": "可以私信了解",
                "qa_matches": "尺寸",
                "score": 92,
                "score_breakdown": {
                    "intent": 24,
                    "relevance": 24,
                    "evidence": 18,
                    "naturalness": 14,
                    "conversion": 12,
                },
            }
        ],
    )
    window.refresh_comment_opportunities()

    score = window.comment_opportunity_table.item(0, 0)
    assert score.text() == "92"
    assert score.toolTip().startswith("评分明细")
    assert window.comment_opportunity_table.verticalHeader().defaultSectionSize() >= 34
    assert window.comment_opportunity_table.cellWidget(0, 7) is not None

    window.close()
    app.processEvents()


def test_collection_table_columns_use_available_width_naturally(tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "gui.db"))

    notes_header = window.collection_notes_table.horizontalHeader()
    comment_header = window.comment_opportunity_table.horizontalHeader()

    assert notes_header.sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch
    assert all(
        comment_header.sectionResizeMode(column) == QHeaderView.ResizeMode.Stretch
        for column in (1, 3, 4, 5)
    )
    assert notes_header.sectionResizeMode(3) == QHeaderView.ResizeMode.Fixed
    assert notes_header.sectionResizeMode(4) == QHeaderView.ResizeMode.Fixed
    assert comment_header.sectionResizeMode(7) == QHeaderView.ResizeMode.Fixed
    assert window.collection_notes_table.columnWidth(3) >= 104
    assert window.collection_notes_table.columnWidth(4) >= 104
    assert window.comment_opportunity_table.columnWidth(7) >= 300

    window.close()
    app.processEvents()


def _ui_mixin_classes() -> list[type]:
    classes = []
    for module in (
        ui.builder,
        ui.interaction,
        ui.collection,
        ui.comments,
        ui.qa,
        ui.analysis,
        ui.settings_ops,
    ):
        for attr in dir(module):
            candidate = getattr(module, attr)
            if isinstance(candidate, type) and attr.endswith("Mixin"):
                classes.append(candidate)
    return classes


def test_main_window_wires_every_ui_mixin(tmp_path) -> None:
    """main.py 拆分为 ui/ 下的 Mixin 后，页面方法必须仍全部挂在 MainWindow 上。"""
    app = QApplication.instance() or QApplication([])
    window = MainWindow(store=LocalStore(tmp_path / "mixins.db"))

    mixins = _ui_mixin_classes()
    assert mixins

    expected: set[str] = set()
    for mixin in mixins:
        expected |= {name for name in vars(mixin) if not name.startswith("__")}
    assert not [name for name in sorted(expected) if not hasattr(window, name)]

    # QMainWindow 必须排在所有 Mixin 之后，否则 closeEvent 中的 super() 会落到错误的类
    mro = type(window).__mro__
    qmainwindow_index = mro.index(QMainWindow)
    assert all(mro.index(mixin) < qmainwindow_index for mixin in mixins)

    window.close()
    app.processEvents()


def test_task_table_exposes_collection_audit_dialog(tmp_path) -> None:
    """任务表要能点开采集日志，且日志里看得出「什么时候采的、采到多少」。"""
    app = QApplication.instance() or QApplication([])
    store = LocalStore(tmp_path / "audit.db")
    window = MainWindow(store=store)

    task_id = store.create_task("通勤效率", "内容采集")
    run_id = store.start_collection_run(task_id, "关键词搜索", "通勤效率")
    store.save_notes(task_id, [FeedNote(note_id="n1", title="标题")], run_id=run_id)
    store.finish_collection_run(
        run_id, status="success", requested=2, fetched=1, failed=1, message="1 篇详情不可访问"
    )
    window._load_tasks()

    audit_button = window.analysis_task_table.cellWidget(0, 6)
    assert audit_button is not None
    assert audit_button.text() == "采集日志"

    dialog = window._build_collection_log_dialog(store.get_task(task_id))
    overview = dialog.findChild(QLabel)
    assert overview is not None
    assert "1 次取数" in overview.text()
    assert "首次采集" in overview.text()

    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "关键词搜索"
    assert table.item(0, 5).text() == "1 / 2"
    assert table.item(0, 6).text() == "1 篇详情不可访问"

    window.close()
    app.processEvents()


def test_collection_writes_audit_log_into_workspace(tmp_path) -> None:
    """点一次采集，工作区 logs/ 里就该留下这次取数的完整回路。"""
    app = QApplication.instance() or QApplication([])
    store = LocalStore(tmp_path / "gui.db")
    workspace_dir = tmp_path / "workspace"
    window = MainWindow(store=store, settings=AppSettings(workspace_dir=str(workspace_dir)))

    class StubAdapter:
        def search_feeds(self, keyword: str, sort_by: str = "") -> list[FeedNote]:
            return [
                FeedNote(note_id="n1", title="标题"),
                FeedNote(note_id="n2", title="另一篇"),
            ]

    window.adapter = StubAdapter()

    def run_inline(function, *, on_result, on_error=None, button=None, **kwargs):
        # 把 worker 拉回当前线程同步跑，让断言直接看到落盘结果
        try:
            result = function(**kwargs)
        except Exception as exc:  # 与 _run_worker 的失败路径保持一致
            if on_error:
                on_error(str(exc))
            return
        on_result(result)

    window._run_worker = run_inline
    window.search_input.setText("通勤效率")
    window.collect_notes()

    log_json = next((workspace_dir / "logs").glob("*/collection_log.json"))
    payload = json.loads(log_json.read_text(encoding="utf-8"))
    assert payload["topic"] == "通勤效率"
    assert payload["runs"][0]["action"] == "关键词搜索"
    assert payload["runs"][0]["status"] == "success"
    assert payload["runs"][0]["fetched"] == 2
    assert [item["note_id"] for item in payload["notes"]] == ["n1", "n2"]
    assert payload["notes"][0]["collected_at"] == payload["notes"][0]["last_seen_at"]
    # 条目能追回它来自哪一批：这就是「什么时候采的」的回路
    assert payload["notes"][0]["run_id"] == payload["runs"][0]["id"]
    assert (log_json.parent / "collection_log.xlsx").exists()

    window.close()
    app.processEvents()
