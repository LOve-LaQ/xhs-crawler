from __future__ import annotations

import html
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .ai_service import AnalysisService, DeepSeekClient, DeepSeekConfig
from .assets import list_image_assets
from .config import AppSettings
from .models import AnalysisReport, FeedNote, normalize_feed
from .pipeline import hydrate_notes
from .storage import LocalStore
from .workspace import WorkspaceArchive
from .xhs_adapter import XhsCliAdapter


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as exc:  # Qt worker boundary must forward errors to the UI.
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class DragSplitterHandle(QSplitterHandle):
    """A splitter handle that updates pane sizes directly while dragging."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._drag_origin = None
        self._initial_sizes: list[int] = []
        self.setCursor(
            Qt.CursorShape.SizeVerCursor
            if orientation == Qt.Orientation.Vertical
            else Qt.CursorShape.SizeHorCursor
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag_origin = event.globalPosition().toPoint()
        self._initial_sizes = self.splitter().sizes()
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if self._drag_origin is None or len(self._initial_sizes) != 2:
            super().mouseMoveEvent(event)
            return
        current = event.globalPosition().toPoint()
        delta = (
            current.y() - self._drag_origin.y()
            if self.orientation() == Qt.Orientation.Vertical
            else current.x() - self._drag_origin.x()
        )
        total = sum(self._initial_sizes)
        first = max(1, min(self._initial_sizes[0] + delta, total - 1))
        self.splitter().setSizes([first, total - first])
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if self._drag_origin is not None:
            self.releaseMouse()
            self._drag_origin = None
            self._initial_sizes = []
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DragSplitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:  # noqa: N802 - Qt override name
        return DragSplitterHandle(self.orientation(), self)


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "<p class='muted'>暂无内容</p>"
    return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def _table_item(text: Any) -> QTableWidgetItem:
    value = "" if text is None else str(text)
    item = QTableWidgetItem(value)
    if len(value) > 18 or "\n" in value:
        item.setToolTip(value)
    return item


def _comment_score(response: dict[str, Any]) -> tuple[int, dict[str, int]]:
    raw_factors = response.get("scoreFactors") or response.get("score_breakdown") or {}
    factors = {}
    if isinstance(raw_factors, dict):
        for key in ("intent", "relevance", "evidence", "naturalness", "conversion"):
            try:
                factors[key] = max(0, min(100, int(raw_factors.get(key, 0) or 0)))
            except (TypeError, ValueError):
                factors[key] = 0
    score = sum(factors.values())
    if not score:
        try:
            score = max(0, min(100, int(response.get("score", 0) or 0)))
        except (TypeError, ValueError):
            score = 0
    return score, factors


def _score_color(score: int) -> QColor:
    if score >= 85:
        return QColor("#e4f5ea")
    if score >= 70:
        return QColor("#fff1cf")
    if score >= 50:
        return QColor("#ffead7")
    return QColor("#fde2e2")


def report_to_html(report: AnalysisReport, notes: list[FeedNote] | None = None) -> str:
    structure = report.content_structure or {}
    tags = report.tag_strategy or {}
    cover = report.cover_style_analysis or {}
    evidence = {
        str(item.get("noteId", "")): str(item.get("analysis") or item.get("claim") or "")
        for item in report.evidence
        if isinstance(item, dict)
    }
    sample_rows = "".join(
        "<tr>"
        f"<td>{html.escape(note.note_id)}</td>"
        f"<td>{html.escape(note.title)}</td>"
        f"<td>{html.escape(report.summary or '暂无综合结论')}</td>"
        f"<td>{html.escape(evidence.get(note.note_id) or report.summary or '暂无单篇分析')}</td>"
        "</tr>"
        for note in (notes or [])
    )
    sample_table = (
        "<h3>样本分析明细</h3>"
        "<table class='sample-table'><thead><tr><th>样本ID</th><th>样本标题</th><th>分析结论</th>"
        f"<th>单篇分析结果</th></tr></thead><tbody>{sample_rows or '<tr><td colspan=4>暂无样本明细</td></tr>'}</tbody></table>"
    )
    return f"""
    <style>
      body {{ font-family: 'Microsoft YaHei', sans-serif; color:#17212b; line-height:1.65; font-size:13px; }}
      h2 {{ font-size:17px; margin: 4px 0 9px; }}
      h3 {{ font-size:13px; margin:18px 0 6px; color:#d84c43; }}
      p {{ margin: 5px 0; }}
      ul {{ margin: 4px 0 0; padding-left: 20px; }}
      li {{ margin: 4px 0; }}
      .muted {{ color:#88939c; }}
      .quote {{ padding:10px 12px; border-left:3px solid #f45d52; background:#fff5f3; }}
      .tag {{ display:inline-block; padding:3px 7px; margin:3px 4px 0 0; border-radius:5px; background:#ecf8f5; color:#217d6c; }}
      .sample-table {{ width:100%; border-collapse:collapse; margin-top:7px; }}
      .sample-table th, .sample-table td {{ border:1px solid #e2e8ea; padding:7px; text-align:left; vertical-align:top; }}
      .sample-table th {{ color:#54616d; background:#f7f9f9; font-weight:700; }}
    </style>
    <h2>分析结论</h2>
    <p class='quote'>{html.escape(report.summary or '暂无摘要')}</p>
    <h3>关键发现</h3>{_bullet_list(report.key_findings)}
    <h3>标题公式</h3>{_bullet_list(report.title_formulas)}
    <h3>内容结构</h3>
    <p><b>开头：</b>{html.escape('、'.join(map(str, structure.get('openingHooks', []))) or '暂无')}</p>
    <p><b>正文：</b>{html.escape(str(structure.get('bodyPattern', '暂无')))}</p>
    <p><b>结尾：</b>{html.escape('、'.join(map(str, structure.get('endingHooks', []))) or '暂无')}</p>
    <h3>标签策略</h3>
    <div>{''.join(f"<span class='tag'>#{html.escape(str(tag))}</span>" for tag in tags.get('commonTags', [])) or '<span class=muted>暂无</span>'}</div>
    <h3>封面风格</h3>{_bullet_list([str(x) for x in cover.get('commonStyles', [])])}
    <h3>下一步建议</h3>{_bullet_list(report.recommendations)}
    {sample_table}
    """


def report_to_markdown(topic: str, report: AnalysisReport) -> str:
    structure = report.content_structure or {}
    tags = report.tag_strategy or {}
    lines = [f"# {topic} · 小红书内容分析报告", "", "## 分析结论", report.summary or "暂无", ""]
    for heading, items in (
        ("关键发现", report.key_findings),
        ("标题公式", report.title_formulas),
        ("下一步建议", report.recommendations),
    ):
        lines.extend([f"## {heading}", *[f"- {item}" for item in items], ""])
    lines.extend(
        [
            "## 内容结构",
            f"- 开头：{'、'.join(map(str, structure.get('openingHooks', [])))}",
            f"- 正文：{structure.get('bodyPattern', '')}",
            f"- 结尾：{'、'.join(map(str, structure.get('endingHooks', [])))}",
            "",
            "## 标签策略",
            f"- 常用标签：{'、'.join(map(str, tags.get('commonTags', [])))}",
            "",
        ]
    )
    return "\n".join(lines)


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("工作区设置")
        self.setMinimumWidth(480)
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.base_url = QLineEdit(settings.deepseek_base_url)
        self.api_key = QLineEdit(settings.deepseek_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.model = QLineEdit(settings.deepseek_model)
        self.bridge_url = QLineEdit(settings.bridge_url)
        form.addRow("DeepSeek 地址", self.base_url)
        form.addRow("API Key", self.api_key)
        form.addRow("模型", self.model)
        form.addRow("Bridge 地址", self.bridge_url)
        layout.addLayout(form)
        hint = QLabel("API Key 仅保存在本机配置目录，不会写入分析内容。")
        hint.setObjectName("mutedLabel")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        self.settings.deepseek_base_url = self.base_url.text().strip()
        self.settings.deepseek_api_key = self.api_key.text().strip()
        self.settings.deepseek_model = self.model.text().strip() or "deepseek-chat"
        self.settings.bridge_url = self.bridge_url.text().strip() or "ws://localhost:9333"
        self.settings.save()
        super().accept()


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        store: LocalStore | None = None,
        settings: AppSettings | None = None,
        adapter: XhsCliAdapter | None = None,
        analysis_service: AnalysisService | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("XHS Insight")
        self.setMinimumSize(1180, 760)
        self.resize(1440, 900)
        self.store = store or LocalStore()
        self.settings = settings or AppSettings.load()
        self.workspace = WorkspaceArchive(self.settings.workspace_dir or None)
        if self.workspace.enabled:
            self.workspace.set_root(self.settings.workspace_dir)
        self.adapter = adapter or XhsCliAdapter(bridge_url=self.settings.bridge_url)
        self.analysis_service = analysis_service or self._make_analysis_service()
        self.thread_pool = QThreadPool.globalInstance()
        self.current_task_id: str | None = None
        self.current_notes: list[FeedNote] = []
        self.current_report: AnalysisReport | None = None
        self.creator_reference_note_ids: set[str] = set()
        self.active_workflow = "竞品分析"
        self._active_workers = 0
        self._worker_refs: set[Worker] = set()
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}
        self._build_ui()
        self._load_tasks()
        self.refresh_qa_entries()
        QTimer.singleShot(100, self.refresh_connection_status)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._wait_for_workers)

    def _make_analysis_service(self) -> AnalysisService:
        return AnalysisService(
            DeepSeekClient(
                DeepSeekConfig(
                    base_url=self.settings.deepseek_base_url,
                    api_key=self.settings.deepseek_api_key,
                    model=self.settings.deepseek_model,
                )
            )
        )

    def _icon(self, standard_pixmap: QStyle.StandardPixmap):
        return self.style().standardIcon(standard_pixmap)

    def _build_ui(self) -> None:
        self.setStyleSheet(APP_STYLE)
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._build_sidebar())
        root_layout.addWidget(self._build_main_area(), 1)
        self.setCentralWidget(root)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(15, 23, 15, 16)
        layout.setSpacing(5)

        brand = QLabel("◉  XHS Insight\n    CONTENT INTELLIGENCE")
        brand.setObjectName("brandLabel")
        layout.addWidget(brand)
        work_label = QLabel("工作空间")
        work_label.setObjectName("sidebarLabel")
        layout.addWidget(work_label)

        for label, icon in (
            ("工作台", QStyle.StandardPixmap.SP_DesktopIcon),
            ("运营工作流", QStyle.StandardPixmap.SP_DialogHelpButton),
            ("内容采集", QStyle.StandardPixmap.SP_FileDialogContentsView),
            ("分析任务", QStyle.StandardPixmap.SP_DialogApplyButton),
            ("报告中心", QStyle.StandardPixmap.SP_FileDialogDetailedView),
            ("内容创作", QStyle.StandardPixmap.SP_FileDialogNewFolder),
        ):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setProperty("active", label == "工作台")
            button.setIcon(self._icon(icon))
            button.clicked.connect(
                lambda checked=False, text=label: self.navigate_to(text)
            )
            self.nav_buttons[label] = button
            layout.addWidget(button)

        system_label = QLabel("系统")
        system_label.setObjectName("sidebarLabel")
        layout.addSpacing(20)
        layout.addWidget(system_label)
        for label, icon in (
            ("执行日志", QStyle.StandardPixmap.SP_FileDialogInfoView),
            ("设置", QStyle.StandardPixmap.SP_FileDialogDetailedView),
        ):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setIcon(self._icon(icon))
            if label == "设置":
                button.clicked.connect(self.open_settings)
            else:
                button.setProperty("active", False)
                button.clicked.connect(lambda: self.navigate_to("执行日志"))
            self.nav_buttons[label] = button
            layout.addWidget(button)
        layout.addStretch(1)

        connection = QFrame()
        connection.setObjectName("connectionCard")
        connection_layout = QVBoxLayout(connection)
        connection_layout.setContentsMargins(12, 12, 12, 12)
        connection_layout.setSpacing(7)
        connection_layout.addWidget(QLabel("连接状态", objectName="connectionTitle"))
        self.bridge_status_label = QLabel("Chrome / Bridge   检查中")
        self.api_status_label = QLabel("DeepSeek API   未配置")
        self.bridge_status_label.setObjectName("connectionStatus")
        self.api_status_label.setObjectName("connectionStatus")
        connection_layout.addWidget(self.bridge_status_label)
        connection_layout.addWidget(self.api_status_label)
        layout.addWidget(connection)
        footer = QLabel("本地工作区 · v0.1")
        footer.setObjectName("sidebarFooter")
        layout.addWidget(footer)
        return sidebar

    def _build_main_area(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 24, 30, 30)
        layout.setSpacing(16)

        top = QHBoxLayout()
        title_box = QVBoxLayout()
        eyebrow = QLabel("内容脉搏  /  本地工作台")
        eyebrow.setObjectName("eyebrow")
        self.page_title = QLabel("先看清楚，再开始创作。")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("从真实的小红书内容里，找到下一篇值得写的东西。")
        self.page_subtitle.setObjectName("subtitle")
        title_box.addWidget(eyebrow)
        title_box.addWidget(self.page_title)
        title_box.addWidget(self.page_subtitle)
        top.addLayout(title_box, 1)
        settings_button = QPushButton("工作区设置")
        settings_button.setIcon(self._icon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        settings_button.clicked.connect(self.open_settings)
        top.addWidget(settings_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)

        self.page_stack = QStackedWidget()
        self.dashboard_page = self._build_dashboard_page()
        self.workflow_page = self._build_workflow_page()
        self.collection_page = self._build_collection_page()
        self.analysis_tasks_page = self._build_analysis_tasks_page()
        self.report_page = self._build_report_page()
        self.creator_page = self._build_creator_page()
        self.logs_page = self._build_logs_page()
        for name, page in (
            ("工作台", self.dashboard_page),
            ("运营工作流", self.workflow_page),
            ("内容采集", self.collection_page),
            ("分析任务", self.analysis_tasks_page),
            ("报告中心", self.report_page),
            ("内容创作", self.creator_page),
            ("执行日志", self.logs_page),
        ):
            self.page_indices[name] = self.page_stack.addWidget(page)
        layout.addWidget(self.page_stack, 1)
        self.statusBar().showMessage("就绪 · 可搜索主题或导入 CLI JSON")
        return container

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.dashboard_vertical_splitter = DragSplitter(Qt.Orientation.Vertical)
        self.dashboard_vertical_splitter.setObjectName("dashboardVerticalSplitter")
        self.dashboard_vertical_splitter.setChildrenCollapsible(False)
        self.dashboard_vertical_splitter.setHandleWidth(12)

        workbench = QWidget()
        workbench_layout = QVBoxLayout(workbench)
        workbench_layout.setContentsMargins(0, 0, 0, 0)
        workbench_layout.setSpacing(16)
        workbench_layout.addWidget(self._build_workspace_bar())
        workbench_layout.addWidget(self._build_pulse())
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_research_panel())
        splitter.addWidget(self._build_analysis_panel())
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        workbench_layout.addWidget(splitter, 1)

        task_panel = self._build_runtime_panel()
        self.dashboard_vertical_splitter.addWidget(workbench)
        self.dashboard_vertical_splitter.addWidget(task_panel)
        workbench.setMinimumHeight(0)
        task_panel.setMinimumHeight(0)
        workbench.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        task_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.dashboard_vertical_splitter.handle(1).setCursor(Qt.CursorShape.SizeVerCursor)
        self.dashboard_vertical_splitter.setStretchFactor(0, 5)
        self.dashboard_vertical_splitter.setStretchFactor(1, 2)
        self.dashboard_vertical_splitter.setSizes([650, 180])
        layout.addWidget(self.dashboard_vertical_splitter, 1)
        return page

    def _build_workspace_bar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("workspaceBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        label = QLabel("本地工作区")
        label.setObjectName("sectionLabel")
        layout.addWidget(label)
        self.workspace_path = QLineEdit()
        self.workspace_path.setReadOnly(True)
        self.workspace_path.setPlaceholderText("选择一个文件夹，任务会自动归档样本、报告、草稿和 Excel")
        if self.workspace.enabled:
            self.workspace_path.setText(str(self.workspace.root))
        layout.addWidget(self.workspace_path, 1)
        choose = QPushButton("选择文件夹")
        choose.clicked.connect(self.choose_workspace_folder)
        layout.addWidget(choose)
        return frame

    def choose_workspace_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择本地工作区文件夹", str(Path.cwd()))
        if not folder:
            return
        self.workspace.set_root(folder)
        self.settings.workspace_dir = folder
        self.settings.save()
        self.workspace_path.setText(folder)
        self.show_status("工作区已设置：后续任务会自动归档到该文件夹")

    def _page_frame(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 20)
        panel_layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("panelTitle")
        hint = QLabel(subtitle)
        hint.setObjectName("panelSubtitle")
        panel_layout.addWidget(heading)
        panel_layout.addWidget(hint)
        layout.addWidget(panel, 1)
        return panel, panel_layout

    def _build_collection_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 20)
        panel_layout.setSpacing(12)
        heading = QLabel("内容采集")
        heading.setObjectName("panelTitle")
        hint = QLabel(
            "搜索目标帖子，以其他店铺运营视角筛选评论，先补充公开经验，再按需承接私信，并生成待人工确认的回复建议。系统不会自动发布评论。"
        )
        hint.setObjectName("panelSubtitle")
        panel_layout.addWidget(heading)
        panel_layout.addWidget(hint)
        controls = QHBoxLayout()
        self.collection_topic = QLineEdit()
        self.collection_topic.setPlaceholderText("输入搜索主题")
        self.collection_topic.returnPressed.connect(self.collect_from_collection_page)
        controls.addWidget(self.collection_topic, 1)
        collect = QPushButton("开始采集")
        collect.setObjectName("primaryButton")
        collect.setIcon(self._icon(QStyle.StandardPixmap.SP_BrowserReload))
        collect.clicked.connect(self.collect_from_collection_page)
        controls.addWidget(collect)
        import_button = QPushButton("导入 JSON")
        import_button.clicked.connect(self.import_json)
        controls.addWidget(import_button)
        panel_layout.addLayout(controls)
        self.collection_splitter = DragSplitter(Qt.Orientation.Vertical)
        self.collection_splitter.setObjectName("collectionVerticalSplitter")
        self.collection_splitter.setHandleWidth(8)
        self.collection_splitter.setChildrenCollapsible(False)

        notes_section = QFrame()
        notes_section.setMinimumHeight(180)
        notes_layout = QVBoxLayout(notes_section)
        notes_layout.setContentsMargins(0, 4, 0, 0)
        notes_layout.setSpacing(8)
        notes_header = QHBoxLayout()
        notes_header.addWidget(QLabel("目标帖子", objectName="sectionLabel"))
        self.collection_notes_hint = QLabel("搜索后可打开帖子或采集最多 20 条评论")
        self.collection_notes_hint.setObjectName("mutedLabel")
        notes_header.addWidget(self.collection_notes_hint)
        notes_header.addStretch(1)
        notes_layout.addLayout(notes_header)
        self.collection_notes_table = QTableWidget(0, 6)
        self.collection_notes_table.setHorizontalHeaderLabels(
            ["标题", "作者", "互动", "打开帖子", "采集评论", "评论数"]
        )
        self.collection_notes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.collection_notes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.collection_notes_table.setAlternatingRowColors(True)
        self.collection_notes_table.setWordWrap(False)
        self.collection_notes_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.collection_notes_table.verticalHeader().setVisible(False)
        self.collection_notes_table.verticalHeader().setDefaultSectionSize(36)
        self.collection_notes_table.verticalHeader().setMinimumSectionSize(36)
        notes_table_header = self.collection_notes_table.horizontalHeader()
        notes_table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.collection_notes_table.setColumnWidth(0, 360)
        notes_table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        notes_table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column, width in ((3, 112), (4, 124), (5, 78)):
            notes_table_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.collection_notes_table.setColumnWidth(column, width)
        notes_layout.addWidget(self.collection_notes_table, 1)
        self.collection_splitter.addWidget(notes_section)

        self.collection_outreach_splitter = DragSplitter(Qt.Orientation.Vertical)
        self.collection_outreach_splitter.setObjectName("collectionOutreachSplitter")
        self.collection_outreach_splitter.setHandleWidth(8)
        self.collection_outreach_splitter.setChildrenCollapsible(False)

        comment_section = QFrame()
        comment_section.setMinimumHeight(180)
        comment_layout = QVBoxLayout(comment_section)
        comment_layout.setContentsMargins(0, 4, 0, 0)
        comment_layout.setSpacing(8)
        outreach_header = QHBoxLayout()
        outreach_header.addWidget(QLabel("评论机会", objectName="sectionLabel"))
        self.comment_total_label = QLabel("总评论 0")
        self.comment_pending_label = QLabel("待评论 0")
        self.comment_commented_label = QLabel("已评论 0")
        for label in (self.comment_total_label, self.comment_pending_label, self.comment_commented_label):
            label.setObjectName("metricChip")
            outreach_header.addWidget(label)
        self.comment_score_guide_button = QPushButton("评分标准")
        self.comment_score_guide_button.setToolTip("查看评论适配评分的计算因子和人工复核标准")
        self.comment_score_guide_button.clicked.connect(self.show_comment_score_guide)
        outreach_header.addWidget(self.comment_score_guide_button)
        self.generate_comment_button = QPushButton("AI 筛选建议")
        self.generate_comment_button.setObjectName("primaryButton")
        self.generate_comment_button.setToolTip("对已保存的原始评论单独生成筛选结果和回复建议")
        self.generate_comment_button.clicked.connect(self.generate_comment_suggestions)
        outreach_header.addWidget(self.generate_comment_button)
        self.comment_ai_status_label = QLabel("等待 AI 筛选", objectName="mutedLabel")
        self.comment_ai_status_label.setToolTip("AI 筛选只处理已保存的原始评论，不影响评论采集数据")
        outreach_header.addWidget(self.comment_ai_status_label)
        self.qa_toggle_button = QPushButton("收起问答库")
        self.qa_toggle_button.setToolTip("收起问答库，让评论机会区域获得更多空间")
        self.qa_toggle_button.clicked.connect(self.toggle_qa_section)
        outreach_header.addWidget(self.qa_toggle_button)
        outreach_header.addStretch(1)
        self.comment_search = QLineEdit()
        self.comment_search.setPlaceholderText("搜索帖子、用户、评论或建议")
        self.comment_search.setClearButtonEnabled(True)
        self.comment_search.textChanged.connect(self.refresh_comment_opportunities)
        outreach_header.addWidget(self.comment_search, 1)
        comment_layout.addLayout(outreach_header)

        product_row = QHBoxLayout()
        self.collection_product_info = QLineEdit()
        self.collection_product_info.setPlaceholderText(
            "填写本店产品信息，AI 将以第三方运营视角生成真实、克制的经验补充，明确需求时再承接私信"
        )
        product_row.addWidget(self.collection_product_info, 1)
        product_row.addWidget(QLabel("每帖评论", objectName="mutedLabel"))
        self.collection_comment_limit = QSpinBox()
        self.collection_comment_limit.setRange(1, 100)
        self.collection_comment_limit.setValue(20)
        self.collection_comment_limit.setSuffix(" 条")
        product_row.addWidget(self.collection_comment_limit)
        comment_layout.addLayout(product_row)

        self.comment_opportunity_table = QTableWidget(0, 8)
        self.comment_opportunity_table.setHorizontalHeaderLabels(
            ["评分", "帖子", "用户", "原评论", "AI 回复建议", "问答依据", "状态", "操作"]
        )
        self.comment_opportunity_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.comment_opportunity_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.comment_opportunity_table.setAlternatingRowColors(True)
        self.comment_opportunity_table.setWordWrap(False)
        self.comment_opportunity_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.comment_opportunity_table.verticalHeader().setVisible(False)
        self.comment_opportunity_table.verticalHeader().setDefaultSectionSize(36)
        self.comment_opportunity_table.verticalHeader().setMinimumSectionSize(36)
        comment_header = self.comment_opportunity_table.horizontalHeader()
        for column, width in ((0, 64), (1, 130), (2, 88), (3, 190), (4, 220), (5, 120), (6, 75), (7, 320)):
            comment_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.comment_opportunity_table.setColumnWidth(column, width)
        comment_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for column in (1, 3, 4, 5):
            comment_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        comment_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.comment_opportunity_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        comment_layout.addWidget(self.comment_opportunity_table, 1)
        self.collection_outreach_splitter.addWidget(comment_section)

        qa_section = QFrame()
        self.qa_section = qa_section
        qa_section.setMinimumHeight(120)
        qa_layout = QVBoxLayout(qa_section)
        qa_layout.setContentsMargins(0, 4, 0, 0)
        qa_layout.setSpacing(8)
        qa_header = QHBoxLayout()
        qa_header.addWidget(QLabel("Q&A 问答对库", objectName="sectionLabel"))
        qa_header.addStretch(1)
        self.qa_search = QLineEdit()
        self.qa_search.setPlaceholderText("搜索问答库")
        self.qa_search.setClearButtonEnabled(True)
        self.qa_search.textChanged.connect(self.refresh_qa_entries)
        qa_header.addWidget(self.qa_search)
        export_qa = QPushButton("导出 Excel")
        export_qa.clicked.connect(self.export_qa_library)
        qa_header.addWidget(export_qa)
        qa_layout.addLayout(qa_header)
        qa_form = QHBoxLayout()
        self.qa_question_input = QLineEdit()
        self.qa_question_input.setPlaceholderText("问题")
        self.qa_answer_input = QLineEdit()
        self.qa_answer_input.setPlaceholderText("标准答案")
        self.qa_keywords_input = QLineEdit()
        self.qa_keywords_input.setPlaceholderText("关键词（逗号分隔）")
        add_qa = QPushButton("添加问答")
        add_qa.setObjectName("primaryButton")
        add_qa.clicked.connect(self.add_qa_entry)
        qa_form.addWidget(self.qa_question_input, 1)
        qa_form.addWidget(self.qa_answer_input, 2)
        qa_form.addWidget(self.qa_keywords_input, 1)
        qa_form.addWidget(add_qa)
        qa_layout.addLayout(qa_form)
        self.qa_table = QTableWidget(0, 5)
        self.qa_table.setHorizontalHeaderLabels(["问题", "标准答案", "关键词", "更新时间", "操作"])
        self.qa_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.qa_table.setAlternatingRowColors(True)
        self.qa_table.setWordWrap(False)
        self.qa_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.qa_table.verticalHeader().setVisible(False)
        qa_table_header = self.qa_table.horizontalHeader()
        qa_table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        qa_table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        qa_table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        qa_table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        qa_table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.qa_table.setColumnWidth(4, 72)
        self.qa_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        qa_layout.addWidget(self.qa_table, 1)
        self.collection_outreach_splitter.addWidget(qa_section)
        self.collection_outreach_splitter.setStretchFactor(0, 3)
        self.collection_outreach_splitter.setStretchFactor(1, 2)
        self.collection_outreach_splitter.setSizes([380, 220])
        self._qa_expanded_sizes = [380, 220]
        self.collection_splitter.addWidget(self.collection_outreach_splitter)
        self.collection_splitter.setStretchFactor(0, 1)
        self.collection_splitter.setStretchFactor(1, 2)
        self.collection_splitter.setSizes([300, 540])
        panel_layout.addWidget(self.collection_splitter, 1)
        layout.addWidget(panel, 1)
        return page

    def _build_workflow_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 20)
        panel_layout.setSpacing(12)

        heading = QLabel("运营工作流")
        heading.setObjectName("panelTitle")
        panel_layout.addWidget(heading)
        hint = QLabel("按目标选择一条运营链路，系统会带入对应的搜索和分析策略。")
        hint.setObjectName("panelSubtitle")
        panel_layout.addWidget(hint)

        controls = QHBoxLayout()
        self.workflow_keyword_input = QLineEdit()
        self.workflow_keyword_input.setPlaceholderText("输入关键词或主题，例如：通勤效率")
        self.workflow_keyword_input.returnPressed.connect(
            lambda: self.start_workflow(self.active_workflow)
        )
        controls.addWidget(self.workflow_keyword_input, 1)
        panel_layout.addLayout(controls)

        self.workflow_buttons: dict[str, QPushButton] = {}
        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        workflows = (
            (
                "竞品分析",
                "拆解竞品爆款，输出标题、封面、正文、标签和互动数据对比。",
                "按点赞搜索 · 取 3-5 篇详情",
            ),
            (
                "热点追踪",
                "对比近期趋势和历史爆款，给出热度排名与可执行选题。",
                "按最新搜索 · 关注时效变化",
            ),
            (
                "内容创作",
                "研究参考笔记，生成可编辑的标题、正文和标签草稿。",
                "先分析结构 · 再生成草稿",
            ),
            (
                "互动管理",
                "筛选适合互动的目标笔记，生成评论建议后由你确认执行。",
                "中等互动筛选 · 人工确认发送",
            ),
        )
        for index, (name, description, route) in enumerate(workflows):
            card = QFrame()
            card.setObjectName("workflowCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 15, 16, 15)
            card_layout.setSpacing(7)
            title = QLabel(name)
            title.setObjectName("workflowTitle")
            body = QLabel(description)
            body.setObjectName("workflowDescription")
            body.setWordWrap(True)
            route_label = QLabel(route)
            route_label.setObjectName("workflowRoute")
            action = QPushButton("开始")
            action.setObjectName("primaryButton" if index == 0 else "workflowAction")
            action.clicked.connect(lambda checked=False, value=name: self.start_workflow(value))
            card_layout.addWidget(title)
            card_layout.addWidget(body, 1)
            card_layout.addWidget(route_label)
            card_layout.addWidget(action, 0, Qt.AlignmentFlag.AlignLeft)
            self.workflow_buttons[name] = action
            cards.addWidget(card, index // 2, index % 2)
        panel_layout.addLayout(cards)
        layout.addWidget(panel, 1)
        return page

    def _build_analysis_tasks_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 20)
        heading_row = QHBoxLayout()
        heading = QLabel("分析任务")
        heading.setObjectName("panelTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        refresh = QPushButton("刷新任务")
        refresh.clicked.connect(self._load_tasks)
        heading_row.addWidget(refresh)
        panel_layout.addLayout(heading_row)
        hint = QLabel("查看采集、分析和草稿任务的状态；失败任务会保留错误原因。")
        hint.setObjectName("panelSubtitle")
        panel_layout.addWidget(hint)
        self.analysis_task_table = QTableWidget(0, 6)
        self.analysis_task_table.setHorizontalHeaderLabels(
            ["任务名称", "类型", "状态", "进度", "更新时间", "文件夹"]
        )
        self.analysis_task_table.setObjectName("taskTable")
        self.analysis_task_table.verticalHeader().setVisible(False)
        self.analysis_task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.analysis_task_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 5):
            self.analysis_task_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.analysis_task_table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        panel_layout.addWidget(self.analysis_task_table, 1)
        layout.addWidget(panel, 1)
        return page

    def _build_report_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 20)
        heading_row = QHBoxLayout()
        heading = QLabel("报告中心")
        heading.setObjectName("panelTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.copy_report_center_button = self._copy_button(
            "分析报告", lambda: self.report_center_view.toPlainText()
        )
        heading_row.addWidget(self.copy_report_center_button)
        export = QPushButton("导出当前报告")
        export.clicked.connect(self.export_report)
        heading_row.addWidget(export)
        panel_layout.addLayout(heading_row)
        hint = QLabel("分析完成后，报告会在这里保留，并可导出为 Markdown。")
        hint.setObjectName("panelSubtitle")
        panel_layout.addWidget(hint)
        self.report_center_view = QTextBrowser()
        self.report_center_view.setHtml(
            "<p class='muted'>还没有报告。先从内容采集或工作台选择样本并运行分析。</p>"
        )
        panel_layout.addWidget(self.report_center_view, 1)
        layout.addWidget(panel, 1)
        return page

    def _build_creator_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 20)
        heading = QLabel("内容创作")
        heading.setObjectName("panelTitle")
        panel_layout.addWidget(heading)
        hint = QLabel("基于已选样本的分析结果，结合产品资料批量生成草稿。")
        hint.setObjectName("panelSubtitle")
        panel_layout.addWidget(hint)
        product_label = QLabel("产品信息")
        product_label.setObjectName("sectionLabel")
        panel_layout.addWidget(product_label)
        self.creator_product_info = QTextEdit()
        self.creator_product_info.setPlaceholderText("填写产品卖点、规格、价格、适用人群和不能虚构的信息")
        self.creator_product_info.setMaximumHeight(82)
        panel_layout.addWidget(self.creator_product_info)
        asset_row = QHBoxLayout()
        self.creator_asset_path = QLineEdit()
        self.creator_asset_path.setReadOnly(True)
        self.creator_asset_path.setPlaceholderText("选择包含产品图片的本地文件夹")
        self.creator_asset_paths: list[Path] = []
        asset_row.addWidget(self.creator_asset_path, 1)
        choose_assets = QPushButton("选择图片文件夹")
        choose_assets.clicked.connect(self.choose_creator_assets)
        asset_row.addWidget(choose_assets)
        panel_layout.addLayout(asset_row)
        self.creator_asset_summary = QLabel("尚未选择图片素材")
        self.creator_asset_summary.setObjectName("mutedLabel")
        panel_layout.addWidget(self.creator_asset_summary)
        self.creator_source_summary = QLabel("尚未完成样本分析")
        self.creator_source_summary.setObjectName("mutedLabel")
        panel_layout.addWidget(self.creator_source_summary)
        reference_row = QHBoxLayout()
        self.creator_reference_summary = QLabel("尚未选择参考样本")
        self.creator_reference_summary.setObjectName("mutedLabel")
        reference_row.addWidget(self.creator_reference_summary, 1)
        self.creator_reference_button = QPushButton("选择参考样本")
        self.creator_reference_button.clicked.connect(self.choose_creator_references)
        reference_row.addWidget(self.creator_reference_button)
        panel_layout.addLayout(reference_row)
        batch_row = QHBoxLayout()
        batch_row.addWidget(QLabel("生成数量"))
        self.creator_batch_count = QSpinBox()
        self.creator_batch_count.setRange(1, 50)
        self.creator_batch_count.setValue(20)
        self.creator_batch_count.setSuffix(" 组")
        batch_row.addWidget(self.creator_batch_count)
        batch_row.addStretch(1)
        panel_layout.addLayout(batch_row)
        self.creator_title = QLineEdit()
        self.creator_title.setPlaceholderText("标题")
        self.creator_content = QTextEdit()
        self.creator_content.setPlaceholderText("正文")
        self.creator_tags = QLineEdit()
        self.creator_tags.setPlaceholderText("标签，用逗号分隔")
        self.creator_batch_selector = QComboBox()
        self.creator_batch_selector.setPlaceholderText("生成后选择一组草稿")
        self.creator_batch_selector.currentIndexChanged.connect(self._select_creator_draft)
        panel_layout.addWidget(self.creator_batch_selector)
        creator_title_row = QHBoxLayout()
        creator_title_row.addWidget(self.creator_title, 1)
        creator_title_row.addWidget(self._copy_button("标题", self.creator_title.text))
        creator_content_row = QHBoxLayout()
        creator_content_row.addWidget(self.creator_content, 1)
        creator_content_row.addWidget(
            self._copy_button("正文", self.creator_content.toPlainText),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        creator_tags_row = QHBoxLayout()
        creator_tags_row.addWidget(self.creator_tags, 1)
        creator_tags_row.addWidget(self._copy_button("标签", self.creator_tags.text))
        panel_layout.addLayout(creator_title_row)
        panel_layout.addLayout(creator_content_row, 1)
        panel_layout.addLayout(creator_tags_row)
        buttons = QHBoxLayout()
        self.creator_generate_button = QPushButton("批量生成草稿")
        self.creator_generate_button.setObjectName("primaryButton")
        self.creator_generate_button.clicked.connect(self.generate_product_drafts)
        save = QPushButton("保存草稿")
        save.clicked.connect(self.save_creator_draft)
        copy_all = self._copy_button("草稿全文", self._creator_draft_text)
        buttons.addWidget(self.creator_generate_button)
        buttons.addWidget(save)
        buttons.addWidget(copy_all)
        panel_layout.addLayout(buttons)
        layout.addWidget(panel, 1)
        return page

    def _build_logs_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(20, 18, 20, 20)
        heading_row = QHBoxLayout()
        heading = QLabel("执行日志")
        heading.setObjectName("panelTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        clear = QPushButton("清空日志")
        clear.clicked.connect(lambda: self.log_view.clear())
        heading_row.addWidget(clear)
        panel_layout.addLayout(heading_row)
        self.log_view = QTextBrowser()
        self.log_view.setPlaceholderText("任务运行记录会显示在这里")
        panel_layout.addWidget(self.log_view, 1)
        layout.addWidget(panel, 1)
        return page

    def _build_pulse(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("pulseFrame")
        grid = QGridLayout(frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        intro = self._metric_card("当前研究主题", "等待输入", "搜索后会显示在这里", accent=True)
        self.topic_metric = intro.findChild(QLabel, "metricValue")
        grid.addWidget(intro, 0, 0)
        grid.addWidget(self._metric_card("样本笔记", "0", "等待采集"), 0, 1)
        grid.addWidget(self._metric_card("平均互动", "—", "选择样本后计算"), 0, 2)
        self.progress_metric = self._metric_card("分析进度", "0%", "尚未运行分析")
        grid.addWidget(self.progress_metric, 0, 3)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        return frame

    def _metric_card(self, label: str, value: str, note: str, *, accent: bool = False) -> QFrame:
        card = QFrame()
        card.setObjectName("metricAccent" if accent else "metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 13)
        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        value_widget = QLabel(value)
        value_widget.setObjectName("metricValue")
        note_widget = QLabel(note)
        note_widget.setObjectName("metricNote")
        layout.addWidget(label_widget)
        layout.addWidget(value_widget)
        layout.addWidget(note_widget)
        return card

    def _build_research_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 17, 18, 16)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        heading_text = QVBoxLayout()
        title = QLabel("⌕  选题研究")
        title.setObjectName("panelTitle")
        subtitle = QLabel("搜索内容、导入结果，并挑选需要分析的样本")
        subtitle.setObjectName("panelSubtitle")
        heading_text.addWidget(title)
        heading_text.addWidget(subtitle)
        heading.addLayout(heading_text, 1)
        self.import_button = QPushButton("导入 JSON")
        self.import_button.clicked.connect(self.import_json)
        heading.addWidget(self.import_button)
        layout.addLayout(heading)

        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索主题，例如：通勤效率")
        self.search_input.returnPressed.connect(self.collect_notes)
        search_row.addWidget(self.search_input, 1)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["最多点赞", "最新", "最多评论", "最多收藏"])
        search_row.addWidget(self.sort_combo)
        self.collect_button = QPushButton("开始采集")
        self.collect_button.setObjectName("primaryButton")
        self.collect_button.setIcon(self._icon(QStyle.StandardPixmap.SP_BrowserReload))
        self.collect_button.clicked.connect(self.collect_notes)
        search_row.addWidget(self.collect_button)
        layout.addLayout(search_row)

        selection_row = QHBoxLayout()
        selection_row.setSpacing(8)
        selection_label = QLabel("样本选择")
        selection_label.setObjectName("mutedLabel")
        selection_row.addWidget(selection_label)
        selection_row.addStretch(1)
        self.select_all_button = QPushButton("全选")
        self.select_all_button.clicked.connect(self.select_all_notes)
        selection_row.addWidget(self.select_all_button)
        self.clear_all_button = QPushButton("取消全选")
        self.clear_all_button.clicked.connect(self.clear_all_notes)
        selection_row.addWidget(self.clear_all_button)
        layout.addLayout(selection_row)

        self.note_table = QTableWidget(0, 6)
        self.note_table.setHorizontalHeaderLabels(["选择", "标题", "作者", "点赞", "收藏", "评论"])
        self.note_table.setObjectName("noteTable")
        self.note_table.setAlternatingRowColors(True)
        self.note_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.note_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.note_table.verticalHeader().setVisible(False)
        header = self.note_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for column in (3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.note_table, 1)
        self.note_hint = QLabel("尚无样本。可以搜索主题，或导入 search-feeds 生成的 JSON。")
        self.note_hint.setObjectName("mutedLabel")
        layout.addWidget(self.note_hint)
        return panel

    def _build_analysis_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 17, 18, 16)
        layout.setSpacing(10)
        heading = QHBoxLayout()
        text = QVBoxLayout()
        title = QLabel("✦  分析快照")
        title.setObjectName("panelTitle")
        subtitle = QLabel("基于当前选中的样本")
        subtitle.setObjectName("panelSubtitle")
        text.addWidget(title)
        text.addWidget(subtitle)
        heading.addLayout(text, 1)
        self.analyze_button = QPushButton("分析选中内容")
        self.analyze_button.setObjectName("primaryButton")
        self.analyze_button.clicked.connect(self.analyze_selected)
        heading.addWidget(self.analyze_button)
        self.copy_report_button = self._copy_button(
            "分析报告", lambda: self.report_view.toPlainText()
        )
        self.copy_report_button.setText("复制报告")
        heading.addWidget(self.copy_report_button)
        layout.addLayout(heading)

        self.analysis_vertical_splitter = DragSplitter(Qt.Orientation.Vertical)
        self.analysis_vertical_splitter.setObjectName("analysisVerticalSplitter")
        self.analysis_vertical_splitter.setChildrenCollapsible(False)
        self.analysis_vertical_splitter.setHandleWidth(12)

        report_section = QWidget()
        report_layout = QVBoxLayout(report_section)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setSpacing(8)
        self.analysis_progress = QProgressBar()
        self.analysis_progress.setRange(0, 100)
        self.analysis_progress.setValue(0)
        self.analysis_progress.setTextVisible(False)
        report_layout.addWidget(self.analysis_progress)
        self.report_view = QTextBrowser()
        self.report_view.setMinimumHeight(0)
        self.report_view.setOpenExternalLinks(False)
        self.report_view.setHtml("<p class='muted'>选择样本后运行分析，报告会出现在这里。</p>")
        report_layout.addWidget(self.report_view, 1)
        self.analysis_vertical_splitter.addWidget(report_section)

        draft_section = QWidget()
        draft_layout = QVBoxLayout(draft_section)
        draft_layout.setContentsMargins(0, 0, 0, 0)
        draft_layout.setSpacing(8)
        draft_label = QLabel("草稿编辑")
        draft_label.setObjectName("sectionLabel")
        draft_layout.addWidget(draft_label)
        self.draft_title = QLineEdit()
        self.draft_title.setPlaceholderText("标题")
        title_row = QHBoxLayout()
        title_row.addWidget(self.draft_title, 1)
        title_row.addWidget(self._copy_button("标题", self.draft_title.text))
        self.draft_content = QTextEdit()
        self.draft_content.setPlaceholderText("生成草稿后可以在这里继续编辑")
        self.draft_content.setMinimumHeight(0)
        content_row = QHBoxLayout()
        content_row.addWidget(self.draft_content, 1)
        content_row.addWidget(
            self._copy_button("正文", self.draft_content.toPlainText),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        self.draft_tags = QLineEdit()
        self.draft_tags.setPlaceholderText("标签，用逗号分隔")
        tags_row = QHBoxLayout()
        tags_row.addWidget(self.draft_tags, 1)
        tags_row.addWidget(self._copy_button("标签", self.draft_tags.text))
        draft_layout.addLayout(title_row)
        draft_layout.addLayout(content_row, 1)
        draft_layout.addLayout(tags_row)
        draft_buttons = QHBoxLayout()
        self.generate_button = QPushButton("根据报告生成草稿")
        self.generate_button.clicked.connect(self.generate_draft)
        self.save_draft_button = QPushButton("保存草稿")
        self.save_draft_button.clicked.connect(self.save_draft)
        self.export_button = QPushButton("导出报告")
        self.export_button.clicked.connect(self.export_report)
        copy_all = self._copy_button("草稿全文", self._draft_text)
        draft_buttons.addWidget(self.generate_button)
        draft_buttons.addWidget(self.save_draft_button)
        draft_buttons.addWidget(copy_all)
        draft_buttons.addWidget(self.export_button)
        draft_layout.addLayout(draft_buttons)
        self.analysis_vertical_splitter.addWidget(draft_section)
        report_section.setMinimumHeight(0)
        draft_section.setMinimumHeight(0)
        report_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        draft_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored)
        self.analysis_vertical_splitter.handle(1).setCursor(Qt.CursorShape.SizeVerCursor)
        self.analysis_vertical_splitter.setStretchFactor(0, 3)
        self.analysis_vertical_splitter.setStretchFactor(1, 2)
        self.analysis_vertical_splitter.setSizes([300, 250])
        layout.addWidget(self.analysis_vertical_splitter, 1)
        return panel

    def _build_runtime_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 13, 18, 12)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel("◷  运行日志")
        title.setObjectName("panelTitle")
        hint = QLabel("当前任务的执行步骤、进度和状态")
        hint.setObjectName("panelSubtitle")
        heading.addWidget(title)
        heading.addSpacing(10)
        heading.addWidget(hint)
        heading.addStretch(1)
        self.runtime_state_label = QLabel("待命")
        self.runtime_state_label.setObjectName("runtimeState")
        heading.addWidget(self.runtime_state_label)
        clear = QPushButton("清空")
        clear.clicked.connect(self._clear_dashboard_logs)
        heading.addWidget(clear)
        layout.addLayout(heading)
        progress_row = QHBoxLayout()
        self.runtime_progress = QProgressBar()
        self.runtime_progress.setRange(0, 100)
        self.runtime_progress.setValue(0)
        self.runtime_progress.setTextVisible(False)
        progress_row.addWidget(self.runtime_progress, 1)
        self.runtime_progress_label = QLabel("0%")
        self.runtime_progress_label.setObjectName("runtimeProgress")
        progress_row.addWidget(self.runtime_progress_label)
        layout.addLayout(progress_row)
        self.dashboard_log_view = QTextBrowser()
        self.dashboard_log_view.setObjectName("dashboardLogView")
        self.dashboard_log_view.setHtml("<p class='muted'>等待任务开始。搜索、分析和草稿生成步骤会记录在这里。</p>")
        self.dashboard_log_view.setMinimumHeight(0)
        self.dashboard_log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.dashboard_log_view, 1)
        return panel

    def _clear_dashboard_logs(self) -> None:
        self.dashboard_log_view.setHtml("<p class='muted'>等待任务开始。搜索、分析和草稿生成步骤会记录在这里。</p>")

    def navigate_to(self, page_name: str) -> None:
        """Switch the visible workbench section and keep the sidebar state in sync."""
        index = self.page_indices.get(page_name)
        if index is None:
            return
        self.page_stack.setCurrentIndex(index)
        titles = {
            "工作台": ("先看清楚，再开始创作。", "从真实的小红书内容里，找到下一篇值得写的东西。"),
            "运营工作流": ("选择一条运营链路。", "从搜索、分析到创作和互动，每一步都保留在本地工作区。"),
            "内容采集": ("把样本采回来。", "搜索或导入内容，然后挑选需要分析的笔记。"),
            "分析任务": ("任务都在这里。", "查看采集、分析和草稿任务的执行状态。"),
            "报告中心": ("把规律留下来。", "查看分析结论，并导出可复用的内容策略。"),
            "内容创作": ("从结论写成草稿。", "把分析结果转成可以继续编辑的标题、正文和标签。"),
            "执行日志": ("每一步都有记录。", "查看采集、分析和保存动作的本地运行记录。"),
        }
        title, subtitle = titles[page_name]
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        for name, button in self.nav_buttons.items():
            is_active = name == page_name
            button.setProperty("active", is_active)
            button.style().unpolish(button)
            button.style().polish(button)
        self.show_status(f"已打开「{page_name}」")

        if page_name == "内容采集":
            self.collection_topic.setFocus()
        elif page_name == "内容创作":
            self.creator_title.setFocus()
        elif page_name == "分析任务":
            self._load_tasks()

    def start_workflow(self, workflow: str) -> None:
        workflow_settings = {
            "竞品分析": {"sort": "最多点赞", "task_type": "竞品分析"},
            "热点追踪": {"sort": "最新", "task_type": "热点追踪"},
            "内容创作": {"sort": "最多点赞", "task_type": "内容创作"},
            "互动管理": {"sort": "最新", "task_type": "互动管理"},
        }
        settings = workflow_settings.get(workflow)
        if settings is None:
            return
        keyword = self.workflow_keyword_input.text().strip()
        if not keyword:
            self._show_error("请先输入关键词或主题")
            self.navigate_to("运营工作流")
            self.workflow_keyword_input.setFocus()
            return
        self.active_workflow = workflow
        self.search_input.setText(keyword)
        self.collection_topic.setText(keyword)
        self.sort_combo.setCurrentText(settings["sort"])
        self.navigate_to("工作台")
        self.show_status(f"已进入「{workflow}」：{keyword} · {settings['sort']} ")

    def _workflow_task_type(self, fallback: str) -> str:
        return {
            "竞品分析": "竞品分析",
            "热点追踪": "热点追踪",
            "内容创作": "内容创作",
            "互动管理": "互动管理",
        }.get(self.active_workflow, fallback)

    def _copy_button(self, label: str, source: Callable[[], str]) -> QPushButton:
        button = QPushButton("复制")
        button.setObjectName("copyButton")
        button.setToolTip(f"复制{label}")
        button.clicked.connect(lambda checked=False, target=button: self._copy_from_button(target, source, label))
        return button

    def _copy_from_button(
        self, button: QPushButton, source: Callable[[], str], label: str
    ) -> None:
        content = source()
        if not content.strip():
            self.copy_text(content, label)
            return
        self.copy_text(content, label)
        button.setProperty("copyDefaultText", button.text())
        button.setText("已复制")
        button.setToolTip(f"已复制{label}")
        QTimer.singleShot(
            1800,
            lambda target=button, name=label: self._restore_copy_button(target, name),
        )

    def _restore_copy_button(self, button: QPushButton, label: str) -> None:
        if button is not None and not button.isDown():
            button.setText(str(button.property("copyDefaultText") or "复制"))
            button.setToolTip(f"复制{label}")

    def copy_text(self, text: str, label: str) -> None:
        content = text.strip()
        if not content:
            self.show_status(f"没有可复制的{label}")
            return
        QApplication.clipboard().setText(content)
        self.show_status(f"已复制{label}")

    def _draft_text(self) -> str:
        return "\n".join(
            value
            for value in (
                self.draft_title.text().strip(),
                self.draft_content.toPlainText().strip(),
                self.draft_tags.text().strip(),
            )
            if value
        )

    def _creator_draft_text(self) -> str:
        return "\n".join(
            value
            for value in (
                self.creator_title.text().strip(),
                self.creator_content.toPlainText().strip(),
                self.creator_tags.text().strip(),
            )
            if value
        )

    def show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
        timestamp = datetime.now().strftime("%H:%M:%S")
        if hasattr(self, "dashboard_log_view"):
            self.dashboard_log_view.append(f"<b>{timestamp}</b> &nbsp; {html.escape(message)}")
        if hasattr(self, "log_view"):
            self.log_view.append(f"[{timestamp}] {html.escape(message)}")

    def set_runtime_status(self, label: str, progress: int) -> None:
        if not hasattr(self, "runtime_state_label"):
            return
        value = max(0, min(100, progress))
        self.runtime_state_label.setText(label)
        self.runtime_progress.setValue(value)
        self.runtime_progress_label.setText(f"{value}%")

    def _set_busy(self, busy: bool, button: QPushButton | None = None) -> None:
        if button is not None:
            button.setEnabled(not busy)
        self._active_workers += 1 if busy else -1
        if self._active_workers < 0:
            self._active_workers = 0

    def _run_worker(
        self,
        function: Callable[..., Any],
        *,
        on_result: Callable[[Any], None],
        on_error: Callable[[str], None] | None = None,
        button: QPushButton | None = None,
        **kwargs: Any,
    ) -> None:
        worker = Worker(function, **kwargs)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error or self._show_error)
        self._worker_refs.add(worker)
        worker.signals.finished.connect(
            lambda worker=worker: self._release_worker(worker, button)
        )
        self._set_busy(True, button)
        self.thread_pool.start(worker)

    def _release_worker(self, worker: Worker, button: QPushButton | None) -> None:
        self._worker_refs.discard(worker)
        self._set_busy(False, button)

    def _wait_for_workers(self) -> None:
        self.thread_pool.waitForDone(3000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        self._wait_for_workers()
        super().closeEvent(event)

    def _show_error(self, message: str) -> None:
        self.show_status(f"操作失败：{message}")
        QMessageBox.critical(self, "操作失败", message)

    def _load_tasks(self) -> None:
        tasks = self.store.list_tasks()
        if hasattr(self, "analysis_task_table"):
            self._fill_task_table(self.analysis_task_table, tasks)

    def _fill_task_table(self, table: QTableWidget, tasks: list[dict[str, Any]]) -> None:
        table.clearContents()
        table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            table.setItem(row, 0, QTableWidgetItem(task["topic"]))
            table.setItem(row, 1, QTableWidgetItem(task["task_type"]))
            table.setItem(row, 2, QTableWidgetItem(task["status"]))
            table.setItem(row, 3, QTableWidgetItem(f"{task['progress']}%"))
            table.setItem(row, 4, QTableWidgetItem(task["updated_at"].replace("T", " ")[:16]))
            if table.columnCount() > 5:
                action = QPushButton("打开")
                action.clicked.connect(
                    lambda checked=False, value=task: self.open_task_folder(value)
                )
                table.setCellWidget(row, 5, action)

    def open_task_folder(self, task: dict[str, Any]) -> None:
        self._sync_comment_table_for_task(task)
        folder = self.workspace.find_task_folder(
            task["id"], task["topic"], task["task_type"]
        )
        if folder is None:
            QMessageBox.information(
                self,
                "文件夹不存在",
                "没有找到该任务对应的本地文件夹。请确认已选择工作区，且任务已生成归档文件。",
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self._show_error(f"无法打开文件夹：{folder}")
            return
        self.show_status(f"已打开任务文件夹：{folder}")

    def _create_or_reuse_task(self, topic: str, task_type: str) -> str:
        if self.current_task_id:
            try:
                current = self.store.get_task(self.current_task_id)
                if current["topic"] == topic:
                    return self.current_task_id
            except KeyError:
                pass
        self.current_task_id = self.store.create_task(topic, task_type)
        return self.current_task_id

    def collect_notes(self) -> None:
        topic = self.search_input.text().strip()
        if not topic:
            self._show_error("请先输入搜索主题")
            return
        task_type = self._workflow_task_type("内容采集")
        task_id = self._create_or_reuse_task(topic, task_type)
        self.store.update_task(task_id, status="running", progress=10, error="")
        self.collect_button.setText("采集中...")
        self.set_runtime_status("采集中", 10)
        self.show_status("正在通过现有自动化脚本搜索内容；需要 Chrome 扩展保持连接")
        self._run_worker(
            self.adapter.search_feeds,
            keyword=topic,
            sort_by=self.sort_combo.currentText(),
            on_result=self._on_search_result,
            on_error=self._on_task_error,
            button=self.collect_button,
        )

    def collect_from_collection_page(self) -> None:
        topic = self.collection_topic.text().strip()
        if not topic:
            self._show_error("请先输入搜索主题")
            return
        self.search_input.setText(topic)
        self.navigate_to("工作台")
        self.collect_notes()

    def _on_search_result(self, notes: list[FeedNote]) -> None:
        self.current_notes = notes
        if self.current_task_id:
            self.store.save_notes(self.current_task_id, notes)
            self.store.update_task(self.current_task_id, status="ready", progress=100)
            self.workspace.save_samples(
                self.current_task_id,
                self.search_input.text().strip() or "内容采集",
                notes,
            )
        self.populate_notes(notes)
        self.populate_collection_notes(notes)
        self.set_runtime_status("采集完成", 100)
        self.collect_button.setText("开始采集")
        self.show_status(f"已采集 {len(notes)} 篇笔记")
        self._load_tasks()

    def _on_task_error(self, message: str) -> None:
        if self.current_task_id:
            self.store.update_task(self.current_task_id, status="error", error=message)
        self.collect_button.setText("开始采集")
        self.analyze_button.setText("分析选中内容")
        self.set_runtime_status("执行失败", 0)
        self._show_error(message)
        self._load_tasks()

    def populate_notes(self, notes: list[FeedNote]) -> None:
        self.note_table.setRowCount(len(notes))
        for row, note in enumerate(notes):
            checked = QTableWidgetItem()
            checked.setCheckState(Qt.CheckState.Checked)
            checked.setData(Qt.ItemDataRole.UserRole, note.note_id)
            self.note_table.setItem(row, 0, checked)
            self.note_table.setItem(row, 1, QTableWidgetItem(note.title))
            self.note_table.setItem(row, 2, QTableWidgetItem(note.author))
            self.note_table.setItem(row, 3, QTableWidgetItem(note.liked_count))
            self.note_table.setItem(row, 4, QTableWidgetItem(note.collected_count))
            self.note_table.setItem(row, 5, QTableWidgetItem(note.comment_count))
        self.note_hint.setText(f"已加载 {len(notes)} 篇样本 · 勾选需要分析的内容")
        if notes:
            self.topic_metric.setText(self.search_input.text().strip() or "已导入内容")
            if hasattr(self, "collection_topic"):
                self.collection_topic.setText(self.search_input.text().strip())

    def populate_collection_notes(self, notes: list[FeedNote]) -> None:
        if not hasattr(self, "collection_notes_table"):
            return
        table = self.collection_notes_table
        table.setRowCount(len(notes))
        for row, note in enumerate(notes):
            title = _table_item(note.title)
            title.setData(Qt.ItemDataRole.UserRole, note.note_id)
            table.setItem(row, 0, title)
            table.setItem(row, 1, _table_item(note.author))
            table.setItem(
                row,
                2,
                _table_item(
                    f"赞 {note.liked_count or '-'}  藏 {note.collected_count or '-'}"
                ),
            )
            open_post = QPushButton("打开帖子")
            open_post.setObjectName("tableActionButton")
            open_post.setMinimumWidth(104)
            open_post.setFixedHeight(28)
            open_post.clicked.connect(lambda checked=False, item=note: self.open_note_post(item))
            table.setCellWidget(row, 3, open_post)
            collect_comments = QPushButton("采集评论")
            collect_comments.setObjectName("primaryButton")
            collect_comments.setProperty("tableAction", True)
            collect_comments.setMinimumWidth(116)
            collect_comments.setFixedHeight(28)
            collect_comments.clicked.connect(
                lambda checked=False, item=note, button=collect_comments: self.collect_note_comments(item, button)
            )
            table.setCellWidget(row, 4, collect_comments)
            table.setItem(row, 5, _table_item(note.comment_count or "-"))
        self.collection_notes_hint.setText(
            f"已加载 {len(notes)} 篇帖子，可采集每帖最多 {self.collection_comment_limit.value()} 条评论"
            if notes
            else "搜索后可打开帖子或采集最多 20 条评论"
        )

    @staticmethod
    def _note_url(note_id: str, xsec_token: str = "", comment_id: str = "") -> QUrl:
        query = urlencode({"xsec_token": xsec_token, "xsec_source": "pc_feed"}) if xsec_token else ""
        fragment = f"#comment-{quote(comment_id)}" if comment_id else ""
        return QUrl(f"https://www.xiaohongshu.com/explore/{quote(note_id)}?{query}{fragment}")

    def open_note_post(self, note: FeedNote) -> None:
        if not note.note_id:
            self._show_error("该帖子缺少笔记 ID，无法定位")
            return
        if not QDesktopServices.openUrl(self._note_url(note.note_id, note.xsec_token)):
            self._show_error("无法打开小红书帖子")

    @staticmethod
    def _detail_comments(note: FeedNote) -> list[dict[str, Any]]:
        raw_comments = note.raw.get("comments", []) if isinstance(note.raw, dict) else []
        if isinstance(raw_comments, dict):
            raw_comments = raw_comments.get("list", [])
        return [item for item in raw_comments if isinstance(item, dict)]

    def collect_note_comments(self, note: FeedNote, button: QPushButton) -> None:
        if not self.current_task_id:
            self._show_error("请先搜索或导入帖子，再采集评论")
            return
        button.setText("采集中...")
        button.setEnabled(False)
        self.show_status(f"正在加载《{note.title}》的评论")
        self.set_runtime_status("正在加载评论", 25)
        self._run_worker(
            self._collect_raw_comments,
            note=note,
            limit=self.collection_comment_limit.value(),
            on_result=lambda result, original=note: self._on_comments_collected(result, original),
            on_error=self._on_task_error,
            button=button,
        )

    def _collect_raw_comments(
        self, note: FeedNote, limit: int
    ) -> tuple[FeedNote, list[dict[str, Any]], int]:
        detail = self.adapter.get_feed_detail(
            note, load_all_comments=True, max_comment_items=max(1, limit)
        )
        comments = self._detail_comments(detail)
        opportunities = []
        for comment in comments:
            user = comment.get("user", {}) if isinstance(comment.get("user"), dict) else {}
            opportunities.append(
                {
                    "note_id": detail.note_id,
                    "note_title": detail.title,
                    "xsec_token": note.xsec_token,
                    "comment_id": str(comment.get("id", "")),
                    "commenter_name": str(user.get("nickname", "未知用户")),
                    "comment_content": str(comment.get("content", "")),
                    "ai_reply": "",
                    "qa_matches": "",
                    "score": 0,
                    "score_breakdown": {},
                    "status": "待筛选",
                }
            )
        return detail, opportunities, len(comments)

    def _on_comments_collected(
        self, result: tuple[FeedNote, list[dict[str, Any]], int], original: FeedNote
    ) -> None:
        detail, opportunities, comment_count = result
        self.current_notes = [detail if item.note_id == detail.note_id else item for item in self.current_notes]
        if self.current_task_id:
            self.store.save_notes(self.current_task_id, self.current_notes)
            self.store.save_comment_opportunities(self.current_task_id, opportunities)
            self._sync_comment_table()
        self.populate_collection_notes(self.current_notes)
        self.refresh_comment_opportunities()
        self.set_runtime_status("评论已保存", 60)
        if not comment_count:
            self.show_status(f"《{original.title}》没有可读取的评论")
        else:
            self.show_status(f"《{original.title}》已保存 {comment_count} 条原始评论，可点击“AI 筛选建议”")

    def generate_comment_suggestions(self) -> None:
        if not self.current_task_id:
            self.comment_ai_status_label.setText("请先采集并保存评论")
            self._show_error("请先搜索或导入帖子，再采集评论")
            return
        product_info = self.collection_product_info.text().strip()
        if not product_info:
            self.comment_ai_status_label.setText("请先填写产品信息")
            self._show_error("请先填写产品信息，再生成评论回复建议")
            return
        items = self.store.list_comment_opportunities(self.current_task_id)
        if not items:
            self.comment_ai_status_label.setText("暂无已保存评论")
            self._show_error("请先点击帖子列表中的“采集评论”保存原始评论")
            return
        self.generate_comment_button.setEnabled(False)
        self.generate_comment_button.setText("AI 筛选中...")
        self.comment_ai_status_label.setText(f"正在分析 {len(items)} 条已保存评论")
        self.show_status("正在对已保存评论进行 AI 筛选")
        self.set_runtime_status("正在 AI 筛选", 70)
        self._run_worker(
            self._generate_comment_suggestions,
            items=items,
            product_info=product_info,
            notes=self.current_notes,
            qa_entries=self.store.list_qa_entries(),
            on_result=self._on_comment_suggestions_generated,
            on_error=self._on_comment_suggestions_error,
            button=self.generate_comment_button,
        )

    def _generate_comment_suggestions(
        self,
        items: list[dict[str, Any]],
        product_info: str,
        notes: list[FeedNote],
        qa_entries: list[dict[str, Any]],
    ) -> int:
        service = self._make_analysis_service()
        notes_by_id = {note.note_id: note for note in notes}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            grouped.setdefault(str(item.get("note_id", "")), []).append(item)
        updated = 0
        for note_id, note_items in grouped.items():
            note = notes_by_id.get(note_id)
            if note is None:
                continue
            comments = [
                {
                    "id": item.get("comment_id", ""),
                    "content": item.get("comment_content", ""),
                    "user": {"nickname": item.get("commenter_name", "")},
                }
                for item in note_items
            ]
            suggested = service.generate_comment_replies(product_info, note, comments, qa_entries)
            replies = {
                str(response.get("commentId", "")): response
                for response in suggested
                if isinstance(response, dict) and response.get("commentId")
            }
            for item in note_items:
                response = replies.get(str(item.get("comment_id", "")))
                if response:
                    qa_matches = response.get("qaMatches", [])
                    score, factors = _comment_score(response)
                    self.store.update_comment_opportunity_ai(
                        item["id"],
                        reply=str(response.get("reply", "")),
                        qa_matches=(
                            "、".join(map(str, qa_matches))
                            if isinstance(qa_matches, list)
                            else str(qa_matches)
                        ),
                        score=score,
                        score_breakdown=factors,
                        status="未评论",
                    )
                else:
                    self.store.update_comment_opportunity_ai(
                        item["id"],
                        reply="",
                        qa_matches="",
                        score=0,
                        score_breakdown={},
                        status="不建议",
                    )
                updated += 1
        return updated

    def _on_comment_suggestions_generated(self, count: int) -> None:
        self._sync_comment_table()
        self.refresh_comment_opportunities()
        self.generate_comment_button.setText("AI 筛选建议")
        self.comment_ai_status_label.setText(f"已完成 {count} 条，可继续人工编辑")
        self.set_runtime_status("AI 筛选完成", 100)
        self.show_status(f"AI 筛选完成，已处理 {count} 条评论；请人工确认后复制发布")

    def _on_comment_suggestions_error(self, message: str) -> None:
        self._sync_comment_table()
        self.generate_comment_button.setText("AI 筛选建议")
        self.comment_ai_status_label.setText("AI 筛选失败，原始评论已保留")
        self.set_runtime_status("AI 筛选失败", 60)
        self.show_status(f"AI 筛选失败，原始评论已保留：{message}")

    def refresh_comment_opportunities(self) -> None:
        if not hasattr(self, "comment_opportunity_table"):
            return
        items = (
            self.store.list_comment_opportunities(
                self.current_task_id, self.comment_search.text()
            )
            if self.current_task_id
            else []
        )
        table = self.comment_opportunity_table
        table.setRowCount(len(items))
        for row, item in enumerate(items):
            score = max(0, min(100, int(item.get("score", 0) or 0)))
            score_item = _table_item(score)
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            score_item.setBackground(_score_color(score))
            breakdown = item.get("score_breakdown") or {}
            score_item.setToolTip(
                "评分明细\n"
                + "\n".join(
                    f"{label}：{breakdown.get(key, 0)}"
                    for key, label in (
                        ("intent", "需求明确度 / 25"),
                        ("relevance", "回复匹配度 / 25"),
                        ("evidence", "事实依据 / 20"),
                        ("naturalness", "自然度 / 15"),
                        ("conversion", "自然承接 / 15"),
                    )
                )
            )
            score_item.setData(Qt.ItemDataRole.UserRole, item["id"])
            table.setItem(row, 0, score_item)
            for column, key in enumerate(
                ("note_title", "commenter_name", "comment_content", "qa_matches", "status")
            ):
                cell = _table_item(item.get(key, ""))
                cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                target_column = column + 1 if column < 3 else column + 2
                table.setItem(row, target_column, cell)
            reply_cell = QWidget()
            reply_layout = QHBoxLayout(reply_cell)
            reply_layout.setContentsMargins(4, 3, 4, 3)
            reply_layout.setSpacing(0)
            reply_editor = QLineEdit(str(item.get("ai_reply", "")))
            reply_editor.setObjectName("commentReplyEditor")
            reply_editor.setToolTip(str(item.get("ai_reply", "")))
            reply_editor.setClearButtonEnabled(True)
            reply_editor.setCursorPosition(0)
            reply_editor.setMinimumWidth(0)
            reply_editor.setFixedHeight(28)
            reply_editor.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            reply_layout.addWidget(reply_editor)
            reply_editor.editingFinished.connect(
                lambda editor=reply_editor, opportunity_id=item["id"]: self.save_comment_reply(
                    opportunity_id, editor
                )
            )
            table.setCellWidget(row, 4, reply_cell)
            actions = QWidget()
            action_layout = QHBoxLayout(actions)
            action_layout.setContentsMargins(4, 3, 4, 3)
            action_layout.setSpacing(4)
            actions.setMinimumHeight(34)
            copy_button = QPushButton("复制")
            copy_button.setObjectName("tableActionButton")
            copy_button.setMinimumWidth(60)
            copy_button.setFixedHeight(28)
            copy_button.clicked.connect(
                lambda checked=False, button=copy_button, editor=reply_editor: self._copy_from_button(
                    button, editor.text, "评论建议"
                )
            )
            comment_button = QPushButton("评论")
            comment_button.setObjectName("tableActionButton")
            comment_button.setMinimumWidth(60)
            comment_button.setFixedHeight(28)
            comment_button.clicked.connect(
                lambda checked=False, record=item, target_row=row: self.open_comment_location(record, target_row)
            )
            marked = QPushButton("标记已评论")
            marked.setObjectName("tableActionButton")
            marked.setMinimumWidth(112)
            marked.setFixedHeight(28)
            marked.setEnabled(item.get("status") != "已评论")
            marked.clicked.connect(
                lambda checked=False, opportunity_id=item["id"]: self.mark_comment_commented(opportunity_id)
            )
            action_layout.addWidget(copy_button)
            action_layout.addWidget(comment_button)
            action_layout.addWidget(marked)
            table.setCellWidget(row, 7, actions)
        stats = self.store.comment_opportunity_stats(self.current_task_id) if self.current_task_id else {"total": 0, "pending": 0, "commented": 0}
        self.comment_total_label.setText(f"总评论 {stats['total']}")
        self.comment_pending_label.setText(f"待评论 {stats['pending']}")
        self.comment_commented_label.setText(f"已评论 {stats['commented']}")

    def open_comment_location(self, record: dict[str, Any], row: int) -> None:
        self.comment_opportunity_table.selectRow(row)
        note = FeedNote(
            note_id=str(record.get("note_id", "")),
            title=str(record.get("note_title", "")),
            xsec_token=str(record.get("xsec_token", "")),
        )
        self.set_runtime_status("正在定位评论", 45)
        self._run_worker(
            self.adapter.locate_comment,
            note=note,
            comment_id=str(record.get("comment_id", "")),
            on_result=lambda result: self._on_comment_location_result(result),
            on_error=lambda message, record=record: self._fallback_comment_location(record, message),
        )

    def _on_comment_location_result(self, _result: Any) -> None:
        self.set_runtime_status("评论已定位", 100)
        self.show_status("已打开并高亮目标评论；请手动粘贴回复，发布后再标记为已评论")

    def _fallback_comment_location(self, record: dict[str, Any], message: str) -> None:
        url = self._note_url(
            str(record.get("note_id", "")),
            str(record.get("xsec_token", "")),
            str(record.get("comment_id", "")),
        )
        if not QDesktopServices.openUrl(url):
            self._show_error("无法打开小红书帖子")
            return
        self.set_runtime_status("已打开帖子", 100)
        self.show_status(f"自动高亮失败，已打开评论锚点；请手动找到评论后粘贴回复（{message}）")

    def save_comment_reply(self, opportunity_id: str, editor: QLineEdit) -> None:
        reply = editor.text().strip()
        editor.setToolTip(reply)
        self.store.update_comment_opportunity_reply(opportunity_id, reply)
        self._sync_comment_table()

    def mark_comment_commented(self, opportunity_id: str) -> None:
        self.store.mark_comment_opportunity_commented(opportunity_id)
        self._sync_comment_table()
        self.refresh_comment_opportunities()
        self.show_status("评论状态已标记为已评论")

    def _sync_comment_table(self) -> None:
        if not self.current_task_id or not self.workspace.enabled:
            return
        try:
            task = self.store.get_task(self.current_task_id)
        except KeyError:
            return
        self._sync_comment_table_for_task(task)

    def _sync_comment_table_for_task(self, task: dict[str, Any]) -> None:
        if not self.workspace.enabled:
            return
        task_id = str(task.get("id") or "")
        if not task_id:
            return
        self.workspace.save_comment_table(
            task_id,
            str(task.get("topic") or "内容分析"),
            self.store.list_comment_opportunities(task_id),
            str(task.get("task_type") or "竞品分析"),
        )

    def add_qa_entry(self) -> None:
        question = self.qa_question_input.text().strip()
        answer = self.qa_answer_input.text().strip()
        if not question or not answer:
            self._show_error("请填写问题和标准答案")
            return
        self.store.save_qa_entry(question, answer, self.qa_keywords_input.text())
        self.qa_question_input.clear()
        self.qa_answer_input.clear()
        self.qa_keywords_input.clear()
        self.export_qa_library()
        self.refresh_qa_entries()
        self.show_status("问答已保存到本地问答库")

    def toggle_qa_section(self) -> None:
        if self.qa_section.isHidden():
            self.qa_section.setVisible(True)
            self.qa_toggle_button.setText("收起问答库")
            self.qa_toggle_button.setToolTip("收起问答库，让评论机会区域获得更多空间")
            total = max(1, sum(self.collection_outreach_splitter.sizes()))
            expanded = getattr(self, "_qa_expanded_sizes", [int(total * 0.65), int(total * 0.35)])
            qa_size = max(120, min(expanded[1], total - 120))
            self.collection_outreach_splitter.setSizes([total - qa_size, qa_size])
            self.show_status("问答库已展开")
            return
        sizes = self.collection_outreach_splitter.sizes()
        if len(sizes) == 2:
            self._qa_expanded_sizes = sizes
        self.qa_section.setVisible(False)
        self.qa_toggle_button.setText("展开问答库")
        self.qa_toggle_button.setToolTip("展开问答库")
        self.collection_outreach_splitter.setSizes([max(1, sum(sizes)), 0])
        self.show_status("问答库已收起，评论机会区域已展开")

    def delete_qa_entry(self, entry_id: str) -> None:
        if self.store.delete_qa_entry(entry_id):
            if self.workspace.enabled:
                self.workspace.save_qa_entries(self.store.list_qa_entries())
            self.refresh_qa_entries()
            self.show_status("问答已从本地问答库删除")

    def show_comment_score_guide(self) -> None:
        existing = getattr(self, "comment_score_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("评论评分标准")
        dialog.setMinimumSize(680, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        guide = QTextBrowser()
        guide.setOpenExternalLinks(False)
        guide.setHtml(
            """
            <style>
              body { font-family: 'Microsoft YaHei', sans-serif; color: #17212b; font-size: 13px; line-height: 1.6; }
              h2 { font-size: 17px; margin: 0 0 8px; }
              h3 { font-size: 14px; margin: 16px 0 6px; color: #d84c43; }
              p { margin: 5px 0; }
              table { width: 100%; border-collapse: collapse; margin-top: 6px; }
              th, td { border: 1px solid #e2e8ea; padding: 8px 9px; text-align: left; }
              th { background: #f4f7f8; color: #54616d; }
              .muted { color: #6e7a81; }
              .good { color: #217d6c; font-weight: 700; }
              .warn { color: #a66b00; font-weight: 700; }
              .bad { color: #c94d48; font-weight: 700; }
            </style>
            <h2>评论适配评分（满分 100）</h2>
            <p>评分用于判断一条评论是否值得由第三方店铺运营人工回复。分数由 AI 根据评论、帖子、产品资料和 Q&amp;A 事实库生成，并在本地保存评分明细。</p>
            <table>
              <tr><th>评分因子</th><th>满分</th><th>判断标准</th></tr>
              <tr><td>需求明确度</td><td>25</td><td>用户是否表达了具体问题、需求或购买意向。</td></tr>
              <tr><td>回复匹配度</td><td>25</td><td>建议是否直接回应原评论，而不是泛泛宣传。</td></tr>
              <tr><td>产品事实依据</td><td>20</td><td>是否有产品资料或 Q&amp;A 事实支持，是否避免虚构。</td></tr>
              <tr><td>真诚自然度</td><td>15</td><td>语气是否克制、像真人交流，不贬低原博主或竞品。</td></tr>
              <tr><td>自然承接与获客潜力</td><td>15</td><td>是否在提供公开价值后，按用户明确需求自然承接后续交流；不以主动私信为必选项。</td></tr>
            </table>
            <h3>分数区间</h3>
            <p><span class="good">85–100：高匹配</span>，优先人工确认；<span class="warn">70–84：可用</span>，建议人工润色；<span class="warn">50–69：需优化</span>，谨慎使用；<span class="bad">0–49：不建议</span>，通常不应回复。</p>
            <h3>角色与合规边界</h3>
            <p class="muted">本工具代表其他店铺/品牌的运营视角，不是当前帖子博主客服。系统只生成建议，不会自动发布评论；发布前必须由人工核对产品事实、语气和平台规则。</p>
            """
        )
        layout.addWidget(guide, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        self.comment_score_dialog = dialog
        dialog.open()

    def refresh_qa_entries(self) -> None:
        if not hasattr(self, "qa_table"):
            return
        entries = self.store.list_qa_entries(self.qa_search.text())
        self.qa_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.qa_table.setItem(row, 0, _table_item(entry["question"]))
            self.qa_table.setItem(row, 1, _table_item(entry["answer"]))
            self.qa_table.setItem(row, 2, _table_item(entry["keywords"]))
            self.qa_table.setItem(row, 3, _table_item(entry["updated_at"].replace("T", " ")[:16]))
            delete_button = QPushButton("删除")
            delete_button.setObjectName("tableActionButton")
            delete_button.setFixedHeight(28)
            delete_button.setToolTip("从本地问答库删除这条问答")
            delete_button.clicked.connect(
                lambda checked=False, entry_id=entry["id"]: self.delete_qa_entry(entry_id)
            )
            self.qa_table.setCellWidget(row, 4, delete_button)

    def export_qa_library(self) -> None:
        if not self.workspace.enabled:
            self._show_error("请先在工作台选择本地工作区文件夹")
            return
        self.workspace.save_qa_entries(self.store.list_qa_entries())
        self.show_status("问答库已导出到 qa/qa_library.xlsx")

    def import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入小红书 JSON", str(Path.cwd()), "JSON 文件 (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            raw_notes = payload.get("feeds", payload) if isinstance(payload, dict) else payload
            if isinstance(raw_notes, dict):
                raw_notes = [raw_notes]
            notes = [normalize_feed(item) for item in raw_notes if isinstance(item, dict)]
            if not notes:
                raise ValueError("JSON 中没有可识别的 feeds 数据")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._show_error(f"导入失败：{exc}")
            return
        topic = self.search_input.text().strip() or "导入内容分析"
        if hasattr(self, "collection_topic"):
            self.collection_topic.setText(topic)
        self.current_task_id = self.store.create_task(topic, "内容导入")
        self.current_notes = notes
        self.store.save_notes(self.current_task_id, notes)
        self.store.update_task(self.current_task_id, status="ready", progress=100)
        self.workspace.save_samples(self.current_task_id, topic, notes)
        self.populate_notes(notes)
        self.populate_collection_notes(notes)
        self._load_tasks()
        self.show_status(f"已导入 {len(notes)} 篇笔记")

    def selected_notes(self) -> list[FeedNote]:
        selected_ids = {
            self.note_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(self.note_table.rowCount())
            if self.note_table.item(row, 0)
            and self.note_table.item(row, 0).checkState() == Qt.CheckState.Checked
        }
        return [note for note in self.current_notes if note.note_id in selected_ids]

    def select_all_notes(self) -> None:
        for row in range(self.note_table.rowCount()):
            item = self.note_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def clear_all_notes(self) -> None:
        for row in range(self.note_table.rowCount()):
            item = self.note_table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def analyze_selected(self) -> None:
        notes = self.selected_notes()
        if not notes:
            self._show_error("请先选择至少一篇笔记")
            return
        topic = self.search_input.text().strip() or "小红书内容分析"
        self._create_or_reuse_task(topic, self._workflow_task_type("竞品分析"))
        self.store.update_task(self.current_task_id or "", status="running", progress=15, error="")
        self.analyze_button.setText("分析中...")
        self.set_runtime_status("分析中", 15)
        self.analysis_progress.setValue(15)
        self.analysis_service = self._make_analysis_service()
        self._run_worker(
            self._analyze_notes,
            notes=notes,
            topic=topic,
            on_result=self._on_analysis_result,
            on_error=self._on_task_error,
            button=self.analyze_button,
        )

    def _analyze_notes(
        self, notes: list[FeedNote], topic: str
    ) -> tuple[list[FeedNote], AnalysisReport, list[str]]:
        enriched, skipped = hydrate_notes(notes, self.adapter.get_feed_detail)
        report = self.analysis_service.analyze(topic, enriched)
        return enriched, report, skipped

    def _on_analysis_result(
        self, result: tuple[list[FeedNote], AnalysisReport, list[str]]
    ) -> None:
        notes, report, skipped = result
        if skipped:
            report.key_findings.append(
                f"有 {len(skipped)} 篇样本详情未能访问，报告基于其余 {len(notes)} 篇生成。"
            )
        self.current_notes = [next((item for item in notes if item.note_id == old.note_id), old) for old in self.current_notes]
        self.current_report = report
        self.set_creator_reference_notes([note.note_id for note in notes])
        if hasattr(self, "creator_source_summary"):
            self.creator_source_summary.setText(f"创作依据：已分析 {len(notes)} 篇参考样本")
        if self.current_task_id:
            self.store.save_notes(self.current_task_id, notes)
            self.store.save_report(self.current_task_id, report)
            self.store.update_task(self.current_task_id, status="done", progress=100)
            self.workspace.save_samples(self.current_task_id, self.search_input.text().strip() or "内容分析", notes)
            self.workspace.save_report(
                self.current_task_id,
                self.search_input.text().strip() or "内容分析",
                report,
                notes,
            )
            self._sync_comment_table()
        self.analysis_progress.setValue(100)
        self.set_runtime_status("分析完成", 100)
        self.report_view.setHtml(report_to_html(report, notes))
        self.report_center_view.setHtml(report_to_html(report, notes))
        self.analyze_button.setText("分析选中内容")
        self.progress_metric.findChild(QLabel, "metricValue").setText("100%")
        status = "分析完成，报告已保存到本地"
        if skipped:
            status += f"；已跳过 {len(skipped)} 篇不可访问笔记"
        self.show_status(status)
        self._load_tasks()

    def generate_draft(self) -> None:
        if self.current_report is None:
            self._show_error("请先完成一次内容分析")
            return
        topic = self.search_input.text().strip() or "小红书内容"
        self.analysis_service = self._make_analysis_service()
        self.generate_button.setEnabled(False)
        self.set_runtime_status("生成草稿中", 25)
        self._run_worker(
            self.analysis_service.generate_draft,
            topic=topic,
            report=self.current_report,
            on_result=self._on_draft_result,
            on_error=self._on_draft_error,
            button=self.generate_button,
        )

    def choose_creator_assets(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择产品图片文件夹", str(Path.cwd()))
        if not folder:
            return
        self.creator_asset_paths = list_image_assets(folder)
        self.creator_asset_path.setText(folder)
        if self.creator_asset_paths:
            self.creator_asset_summary.setText(f"已读取 {len(self.creator_asset_paths)} 张图片：{self.creator_asset_paths[0].name}")
            if len(self.creator_asset_paths) > 1:
                self.creator_asset_summary.setText(
                    f"已读取 {len(self.creator_asset_paths)} 张图片：{self.creator_asset_paths[0].name} 等"
                )
        else:
            self.creator_asset_summary.setText("文件夹中没有支持的图片（JPG、PNG、WEBP、BMP、GIF）")

    def creator_reference_notes(self) -> list[FeedNote]:
        return [
            note for note in self.current_notes if note.note_id in self.creator_reference_note_ids
        ]

    def set_creator_reference_notes(self, note_ids: list[str]) -> None:
        valid_ids = {note.note_id for note in self.current_notes}
        self.creator_reference_note_ids = set(note_ids) & valid_ids
        if hasattr(self, "creator_reference_summary"):
            count = len(self.creator_reference_note_ids)
            self.creator_reference_summary.setText(
                f"已选择 {count} 篇样本作为本次创作参考" if count else "尚未选择参考样本"
            )

    def choose_creator_references(self) -> None:
        if not self.current_notes:
            self._show_error("请先采集并分析样本，再选择创作参考")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("选择创作参考样本")
        dialog.setMinimumSize(760, 460)
        layout = QVBoxLayout(dialog)
        hint = QLabel("仅会将勾选样本的内容结构和互动规律用于本次草稿生成。")
        hint.setObjectName("panelSubtitle")
        layout.addWidget(hint)
        actions = QHBoxLayout()
        select_all = QPushButton("全选")
        clear_all = QPushButton("取消全选")
        actions.addWidget(select_all)
        actions.addWidget(clear_all)
        actions.addStretch(1)
        layout.addLayout(actions)
        table = QTableWidget(len(self.current_notes), 5)
        table.setHorizontalHeaderLabels(["选择", "标题", "作者", "点赞", "收藏"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for row, note in enumerate(self.current_notes):
            item = QTableWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, note.note_id)
            item.setCheckState(
                Qt.CheckState.Checked
                if note.note_id in self.creator_reference_note_ids
                else Qt.CheckState.Unchecked
            )
            table.setItem(row, 0, item)
            table.setItem(row, 1, QTableWidgetItem(note.title))
            table.setItem(row, 2, QTableWidgetItem(note.author))
            table.setItem(row, 3, QTableWidgetItem(note.liked_count))
            table.setItem(row, 4, QTableWidgetItem(note.collected_count))
        select_all.clicked.connect(
            lambda: [
                table.item(row, 0).setCheckState(Qt.CheckState.Checked)
                for row in range(table.rowCount())
            ]
        )
        clear_all.clicked.connect(
            lambda: [
                table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
                for row in range(table.rowCount())
            ]
        )
        layout.addWidget(table, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_creator_reference_notes(
                [
                    table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                    for row in range(table.rowCount())
                    if table.item(row, 0).checkState() == Qt.CheckState.Checked
                ]
            )

    def generate_product_drafts(self) -> None:
        if self.current_report is None:
            self._show_error("请先完成竞品分析，再生成商品草稿")
            return
        product_info = self.creator_product_info.toPlainText().strip()
        if not product_info:
            self._show_error("请先填写产品信息")
            return
        if not self.creator_asset_paths:
            self._show_error("请先选择产品图片文件夹")
            return
        reference_notes = self.creator_reference_notes()
        if not reference_notes:
            self._show_error("请先选择至少一篇创作参考样本")
            return
        topic = self.search_input.text().strip() or "小红书商品内容"
        self.analysis_service = self._make_analysis_service()
        self.creator_generate_button.setEnabled(False)
        self.creator_generate_button.setText("批量生成中...")
        self.creator_generate_button.setToolTip("正在生成草稿，请稍候")
        self.show_status(f"正在生成 {self.creator_batch_count.value()} 组商品草稿")
        self.set_runtime_status("生成商品草稿中", 25)
        self._run_worker(
            self.analysis_service.generate_product_drafts,
            topic=topic,
            report=self.current_report,
            product_info=product_info,
            asset_names=[item.name for item in self.creator_asset_paths],
            reference_notes=reference_notes,
            count=self.creator_batch_count.value(),
            on_result=self._on_product_drafts_result,
            on_error=self._on_draft_error,
            button=self.creator_generate_button,
        )

    def _on_product_drafts_result(self, payload: dict[str, Any]) -> None:
        self.creator_generate_button.setText("批量生成草稿")
        self.creator_generate_button.setToolTip("根据分析结果批量生成商品草稿")
        drafts = payload.get("drafts", [])
        if not isinstance(drafts, list):
            self._show_error("模型返回的草稿格式不正确")
            return
        self.creator_drafts = [item for item in drafts if isinstance(item, dict)]
        if self.current_task_id:
            topic = self.search_input.text().strip() or "小红书商品内容"
            self.workspace.save_drafts(self.current_task_id, topic, self.creator_drafts)
            self.workspace.copy_assets(self.current_task_id, topic, self.creator_asset_paths)
        self.creator_batch_selector.clear()
        self.creator_batch_selector.addItems([f"方案 {index + 1}" for index in range(len(self.creator_drafts))])
        if self.creator_drafts:
            self._select_creator_draft(0)
            self.set_runtime_status("草稿已生成", 100)
            self.show_status(f"已生成 {len(self.creator_drafts)} 组商品草稿，可以逐组编辑")
        else:
            self._show_error("模型没有返回可用草稿")

    def _select_creator_draft(self, index: int) -> None:
        if not hasattr(self, "creator_drafts") or index < 0 or index >= len(self.creator_drafts):
            return
        draft = self.creator_drafts[index]
        self.creator_title.setText(str(draft.get("title", "")))
        self.creator_content.setPlainText(str(draft.get("content", "")))
        tags = draft.get("tags", [])
        self.creator_tags.setText("、".join(map(str, tags)) if isinstance(tags, list) else str(tags))

    def _on_draft_result(self, draft: dict[str, Any]) -> None:
        title = str(draft.get("title", ""))
        content = str(draft.get("content", ""))
        tags = draft.get("tags", [])
        tag_text = "、".join(map(str, tags)) if isinstance(tags, list) else str(tags)
        self.draft_title.setText(title)
        self.draft_content.setPlainText(content)
        self.draft_tags.setText(tag_text)
        self.creator_title.setText(title)
        self.creator_content.setPlainText(content)
        self.creator_tags.setText(tag_text)
        self.set_runtime_status("草稿已生成", 100)
        self.show_status("草稿已生成，可以继续编辑")

    def _on_draft_error(self, message: str) -> None:
        if hasattr(self, "creator_generate_button"):
            self.creator_generate_button.setText("批量生成草稿")
            self.creator_generate_button.setToolTip("根据分析结果批量生成商品草稿")
        self.set_runtime_status("生成失败", 0)
        self._show_error(message)

    def save_draft(self) -> None:
        if not self.current_task_id:
            self._show_error("请先采集或导入内容")
            return
        tags = [tag.strip().lstrip("#") for tag in self.draft_tags.text().replace(",", "、").split("、") if tag.strip()]
        self.store.save_draft(
            self.current_task_id,
            self.draft_title.text().strip(),
            self.draft_content.toPlainText().strip(),
            tags,
        )
        topic = self.search_input.text().strip() or "小红书内容"
        self.workspace.save_drafts(
            self.current_task_id,
            topic,
            [{
                "title": self.draft_title.text().strip(),
                "content": self.draft_content.toPlainText().strip(),
                "tags": tags,
            }],
        )
        self.show_status("草稿已保存到本地")

    def save_creator_draft(self) -> None:
        self.draft_title.setText(self.creator_title.text())
        self.draft_content.setPlainText(self.creator_content.toPlainText())
        self.draft_tags.setText(self.creator_tags.text())
        self.save_draft()

    def export_report(self) -> None:
        if self.current_report is None:
            self._show_error("当前还没有可导出的报告")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出分析报告", "xhs-analysis.md", "Markdown 文件 (*.md)")
        if not path:
            return
        topic = self.search_input.text().strip() or "小红书内容"
        try:
            Path(path).write_text(report_to_markdown(topic, self.current_report), encoding="utf-8")
        except OSError as exc:
            self._show_error(f"导出失败：{exc}")
            return
        self.show_status(f"报告已导出：{path}")

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.analysis_service = self._make_analysis_service()
            self.api_status_label.setText(
                f"DeepSeek API   {'已配置' if self.settings.deepseek_api_key else '未配置'}"
            )
            self.show_status("设置已保存")

    def refresh_connection_status(self) -> None:
        self._run_worker(
            self.adapter.bridge_status,
            on_result=self._on_connection_status,
            on_error=lambda message: self._on_connection_status({"server": False, "extension": False}),
        )

    def _on_connection_status(self, status: dict[str, bool]) -> None:
        bridge = "在线" if status.get("server") else "未启动"
        extension = "扩展已连接" if status.get("extension") else "扩展未连接"
        self.bridge_status_label.setText(f"Chrome / Bridge   {bridge} · {extension}")
        self.api_status_label.setText(
            f"DeepSeek API   {'已配置' if self.settings.deepseek_api_key else '未配置'}"
        )


APP_STYLE = """
QMainWindow, QWidget { background:#f4f7f8; color:#17212b; font-family:'Microsoft YaHei','Noto Sans SC',sans-serif; font-size:12px; }
QLabel { background:transparent; }
#sidebar { background:#17212b; color:#f3f7f8; }
#brandLabel { color:#ffffff; font-weight:800; font-size:15px; line-height:1.5; padding:3px 10px 20px; }
#sidebarLabel { color:#74818b; font-size:10px; letter-spacing:1px; padding:5px 10px; }
#navButton { text-align:left; border:0; border-left:3px solid transparent; border-radius:8px; padding:10px 12px; color:#aebac2; background:transparent; font-weight:600; }
#navButton:hover { color:#ffffff; background:#25333d; }
#navButton[active="true"] { color:#ffffff; background:#293641; border-left-color:#f45d52; }
#connectionCard { border:1px solid #364651; border-radius:10px; background:#202d37; }
#connectionTitle { color:#cbd6db; font-weight:700; }
#connectionStatus { color:#8e9ba4; font-size:10px; padding:2px 0; }
#sidebarFooter { color:#778590; border-top:1px solid #2d3a44; padding-top:12px; font-size:10px; }
#eyebrow { color:#d84c43; font-weight:800; letter-spacing:1px; }
#pageTitle { color:#17212b; font-size:28px; font-weight:800; letter-spacing:-1px; padding-top:2px; }
#subtitle { color:#54616d; font-size:12px; }
QPushButton { min-height:31px; border:1px solid #d5dfe2; border-radius:7px; padding:0 11px; color:#17212b; background:#ffffff; font-weight:700; }
QPushButton:hover { border-color:#aebdc2; background:#fbfcfc; }
QPushButton#tableActionButton, QPushButton[tableAction="true"] { min-height:28px; padding:0 8px; }
#primaryButton { border:1px solid #f45d52; color:#ffffff; background:#f45d52; }
#primaryButton:hover { background:#d84c43; }
#copyButton { min-width:48px; min-height:29px; color:#54616d; background:#fbfcfc; }
#copyButton:hover { border-color:#f45d52; color:#d84c43; background:#fff7f6; }
#pulseFrame { border:1px solid #17212b; border-radius:12px; background:#17212b; min-height:104px; }
#metricCard, #metricAccent { border:0; border-left:1px solid #31404a; border-radius:0; background:#17212b; }
#metricAccent { border-left:0; border-radius:11px 0 0 11px; background:#f45d52; }
#metricLabel { color:#94a2aa; font-size:10px; }
#metricAccent #metricLabel, #metricAccent #metricValue, #metricAccent #metricNote { color:#ffffff; }
#metricValue { color:#ffffff; font-size:24px; font-weight:800; padding-top:6px; }
#metricNote { color:#87959e; font-size:10px; }
#workspaceBar { border:1px solid #dfe6e9; border-radius:9px; background:#ffffff; }
#panel { border:1px solid #dfe6e9; border-radius:12px; background:#ffffff; }
#panelTitle { color:#17212b; font-size:14px; font-weight:800; }
#panelSubtitle, #mutedLabel { color:#88939c; font-size:10px; }
#runtimeState { color:#d84c43; background:#fff1ef; border-radius:5px; padding:4px 8px; font-size:10px; font-weight:800; }
#runtimeProgress { color:#54616d; font-weight:800; min-width:32px; }
#dashboardLogView { border:1px solid #e7edef; border-radius:7px; background:#fbfcfc; color:#54616d; padding:5px 8px; }
#workflowCard { border:1px solid #dfe6e9; border-radius:9px; background:#fbfcfc; }
#workflowCard:hover { border-color:#f3aaa3; background:#fffaf9; }
#workflowTitle { color:#17212b; font-size:14px; font-weight:800; }
#workflowDescription { color:#54616d; font-size:11px; }
#workflowRoute { color:#d84c43; font-size:10px; font-weight:700; }
#workflowAction { min-height:28px; }
#sectionLabel { color:#54616d; font-size:11px; font-weight:800; padding-top:4px; }
#metricChip { color:#54616d; background:#f1f5f5; border-radius:5px; padding:4px 7px; font-size:10px; font-weight:700; }
QLineEdit, QComboBox, QTextEdit, QTextBrowser { border:1px solid #d6e0e3; border-radius:7px; background:#fbfcfc; padding:7px 9px; selection-background-color:#f7c2bc; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QTextBrowser:focus { border:1px solid #f45d52; }
#commentReplyEditor { min-height:22px; max-height:28px; padding:0 7px; }
QTableWidget { border:1px solid #e6ecee; border-radius:7px; background:#ffffff; gridline-color:#edf1f2; alternate-background-color:#fbfcfc; }
QHeaderView::section { border:0; border-bottom:1px solid #edf1f2; padding:8px 7px; color:#88939c; background:#ffffff; font-size:10px; font-weight:700; }
QTableWidget::item { padding:5px; color:#54616d; }
QTableWidget::item:selected { color:#17212b; background:#fff1ef; }
QProgressBar { border:0; border-radius:4px; background:#edf2f2; height:6px; text-align:center; }
QProgressBar::chunk { border-radius:4px; background:#f45d52; }
QSplitter#analysisVerticalSplitter::handle:vertical { height:12px; background:#cbd6da; border-top:2px solid #f4f7f8; border-bottom:2px solid #f4f7f8; }
QSplitter#analysisVerticalSplitter::handle:vertical:hover { background:#f45d52; }
QSplitter#dashboardVerticalSplitter::handle:vertical { height:12px; background:#cbd6da; border-top:2px solid #f4f7f8; border-bottom:2px solid #f4f7f8; }
QSplitter#dashboardVerticalSplitter::handle:vertical:hover { background:#f45d52; }
QSplitter#collectionVerticalSplitter::handle:vertical, QSplitter#collectionOutreachSplitter::handle:vertical { height:8px; background:#edf2f2; border-top:1px solid #ffffff; border-bottom:1px solid #ffffff; }
QSplitter#collectionVerticalSplitter::handle:vertical:hover, QSplitter#collectionOutreachSplitter::handle:vertical:hover { background:#cbd6da; }
QSplitter::handle:vertical { height:10px; background:#dce5e7; border-top:2px solid #ffffff; border-bottom:2px solid #ffffff; }
QSplitter::handle:vertical:hover { background:#f45d52; }
QTabWidget::pane { border:0; }
QStatusBar { color:#6e7a81; background:#eaf0f1; border-top:1px solid #dfe6e9; }
QDialog { background:#f4f7f8; }
"""


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("XHS Insight")
    app.setFont(QFont("Microsoft YaHei", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
