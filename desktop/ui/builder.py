from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .style import APP_STYLE
from .widgets import DragSplitter


class UiBuilderMixin:
    """UI 构建：侧边栏、各页面与面板装配。"""

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
            button.clicked.connect(lambda checked=False, text=label: self.navigate_to(text))
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
        self.api_status_label = QLabel(self._api_status_text())
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
        self.workspace_path.setPlaceholderText(
            "选择一个文件夹，任务会自动归档样本、报告、草稿和 Excel"
        )
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
        self.collection_notes_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
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
        for label in (
            self.comment_total_label,
            self.comment_pending_label,
            self.comment_commented_label,
        ):
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
        self.comment_opportunity_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.comment_opportunity_table.setAlternatingRowColors(True)
        self.comment_opportunity_table.setWordWrap(False)
        self.comment_opportunity_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.comment_opportunity_table.verticalHeader().setVisible(False)
        self.comment_opportunity_table.verticalHeader().setDefaultSectionSize(36)
        self.comment_opportunity_table.verticalHeader().setMinimumSectionSize(36)
        comment_header = self.comment_opportunity_table.horizontalHeader()
        for column, width in (
            (0, 64),
            (1, 130),
            (2, 88),
            (3, 190),
            (4, 220),
            (5, 120),
            (6, 75),
            (7, 320),
        ):
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
        hint = QLabel(
            "查看采集、分析和草稿任务的状态；失败任务会保留错误原因，采集日志可逐批回溯取数时间。"
        )
        hint.setObjectName("panelSubtitle")
        panel_layout.addWidget(hint)
        self.analysis_task_table = QTableWidget(0, 7)
        self.analysis_task_table.setHorizontalHeaderLabels(
            ["任务名称", "类型", "状态", "进度", "更新时间", "文件夹", "采集日志"]
        )
        self.analysis_task_table.setObjectName("taskTable")
        self.analysis_task_table.verticalHeader().setVisible(False)
        self.analysis_task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.analysis_task_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 7):
            self.analysis_task_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
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
        self.creator_product_info.setPlaceholderText(
            "填写产品卖点、规格、价格、适用人群和不能虚构的信息"
        )
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
        self.dashboard_log_view.setHtml(
            "<p class='muted'>等待任务开始。搜索、分析和草稿生成步骤会记录在这里。</p>"
        )
        self.dashboard_log_view.setMinimumHeight(0)
        self.dashboard_log_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.dashboard_log_view, 1)
        return panel

    def _clear_dashboard_logs(self) -> None:
        self.dashboard_log_view.setHtml(
            "<p class='muted'>等待任务开始。搜索、分析和草稿生成步骤会记录在这里。</p>"
        )
