from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..models import FeedNote
from .formatting import table_item


class CollectionMixin:
    """内容采集：任务管理、关键词搜索与笔记评论拉取。"""

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
            if table.columnCount() > 6:
                audit = QPushButton("采集日志")
                audit.clicked.connect(
                    lambda checked=False, value=task: self.open_collection_log(value)
                )
                table.setCellWidget(row, 6, audit)

    @staticmethod
    def _readable_time(value: str) -> str:
        """把 ISO 时间戳裁成能直接读的形态，与任务表的更新时间口径一致。"""
        return value.replace("T", " ")[:19] if value else "—"

    def open_collection_log(self, task: dict[str, Any]) -> None:
        """摊开某个任务的采集审计。"""
        self._build_collection_log_dialog(task).exec()

    def _build_collection_log_dialog(self, task: dict[str, Any]) -> QDialog:
        """构建采集审计视图：什么时候、以什么方式、采到多少、漏了多少。

        与 open_collection_log 拆开，是为了让测试能直接检查内容，
        而不必让模态对话框的 exec() 阻塞住测试进程。
        """
        task_id = task["id"]
        runs = self.store.list_collection_runs(task_id)
        summary = self.store.collection_summary(task_id)
        timeline = self.store.list_note_timeline(task_id)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"采集日志 · {task['topic']}")
        dialog.resize(980, 540)
        layout = QVBoxLayout(dialog)

        if timeline:
            notes_line = (
                f"笔记 {len(timeline)} 篇：最早 "
                f"{self._readable_time(timeline[0]['collected_at'])} 采到，最近 "
                f"{self._readable_time(max(item['last_seen_at'] for item in timeline))} 见到"
            )
        else:
            notes_line = "暂无笔记入库记录"
        overview = QLabel(
            f"共 {summary['runs']} 次取数（成功 {summary['succeeded']} / 失败 "
            f"{summary['failed_runs']}）；累计入库 {summary['fetched']} 条，"
            f"取数失败 {summary['failed_items']} 条\n"
            f"首次采集 {self._readable_time(summary['first_started_at'])}；"
            f"最近活动 {self._readable_time(summary['last_activity_at'])}\n{notes_line}"
        )
        overview.setWordWrap(True)
        layout.addWidget(overview)

        table = QTableWidget(len(runs), 7)
        table.setHorizontalHeaderLabels(
            ["采集方式", "来源", "状态", "开始时间", "结束时间", "成功 / 请求", "说明"]
        )
        table.setObjectName("taskTable")
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row, run in enumerate(runs):
            table.setItem(row, 0, table_item(run["action"]))
            table.setItem(row, 1, table_item(run["source"]))
            table.setItem(row, 2, table_item(run["status"]))
            table.setItem(row, 3, table_item(self._readable_time(run["started_at"])))
            table.setItem(row, 4, table_item(self._readable_time(run["finished_at"])))
            table.setItem(row, 5, table_item(f"{run['fetched']} / {run['requested']}"))
            table.setItem(row, 6, table_item(run["message"]))
        header = table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table, 1)

        buttons = QDialogButtonBox()
        export_button = buttons.addButton("导出到工作区", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton("关闭", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.rejected.connect(dialog.reject)

        def export() -> None:
            if not self.workspace.enabled:
                QMessageBox.information(
                    dialog, "未设置工作区", "请先在设置里选择工作区目录，再导出采集日志。"
                )
                return
            self._export_collection_log(task_id)
            self.show_status(f"采集日志已导出到「{task['topic']}」的 logs 文件夹")

        export_button.clicked.connect(export)
        layout.addWidget(buttons)
        return dialog

    def open_task_folder(self, task: dict[str, Any]) -> None:
        self._sync_comment_table_for_task(task)
        folder = self.workspace.find_task_folder(task["id"], task["topic"], task["task_type"])
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

    def _begin_collection_run(self, task_id: str, action: str, source: str = "") -> None:
        """开启一条采集批次，失败时统一由 _on_task_error 收尾。"""
        self._active_run_id = self.store.start_collection_run(task_id, action, source)

    def _finish_collection_run(
        self,
        status: str,
        *,
        requested: int = 0,
        fetched: int = 0,
        failed: int = 0,
        message: str = "",
    ) -> None:
        """收尾当前批次，并立刻把日志刷到工作区，避免库里与归档两份记录分叉。"""
        run_id = getattr(self, "_active_run_id", "")
        if not run_id:
            return
        self.store.finish_collection_run(
            run_id,
            status=status,
            requested=requested,
            fetched=fetched,
            failed=failed,
            message=message,
        )
        self._active_run_id = ""
        self._export_collection_log()

    def _export_collection_log(self, task_id: str = "") -> None:
        """把采集审计落到工作区 logs/；未启用工作区时静默跳过。"""
        target = task_id or self.current_task_id
        if not target or not self.workspace.enabled:
            return
        try:
            task = self.store.get_task(target)
        except KeyError:  # 任务已被清理，用不着为它留日志
            return
        self.workspace.save_collection_log(
            target,
            task["topic"],
            self.store.list_collection_runs(target),
            self.store.list_note_timeline(target),
        )

    def collect_notes(self) -> None:
        topic = self.search_input.text().strip()
        if not topic:
            self._show_error("请先输入搜索主题")
            return
        task_type = self._workflow_task_type("内容采集")
        task_id = self._create_or_reuse_task(topic, task_type)
        self._begin_collection_run(task_id, "关键词搜索", topic)
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
            self.store.save_notes(self.current_task_id, notes, run_id=self._active_run_id)
            self.store.update_task(self.current_task_id, status="ready", progress=100)
            self.workspace.save_samples(
                self.current_task_id,
                self.search_input.text().strip() or "内容采集",
                notes,
            )
            # 搜索接口返回多少就是多少，中间没有重试层，故请求数与实际条数一致。
            self._finish_collection_run("success", requested=len(notes), fetched=len(notes))
        self.populate_notes(notes)
        self.populate_collection_notes(notes)
        self.set_runtime_status("采集完成", 100)
        self.collect_button.setText("开始采集")
        self.show_status(f"已采集 {len(notes)} 篇笔记")
        self._load_tasks()

    def _on_task_error(self, message: str) -> None:
        if self.current_task_id:
            self.store.update_task(self.current_task_id, status="error", error=message)
        # 采集 / 分析 / 评论的 worker 共用这个失败回调，收尾当前进行中的那条批次即可。
        self._finish_collection_run("failed", message=message)
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
            title = table_item(note.title)
            title.setData(Qt.ItemDataRole.UserRole, note.note_id)
            table.setItem(row, 0, title)
            table.setItem(row, 1, table_item(note.author))
            table.setItem(
                row,
                2,
                table_item(f"赞 {note.liked_count or '-'}  藏 {note.collected_count or '-'}"),
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
                lambda checked=False, item=note, button=collect_comments: (
                    self.collect_note_comments(item, button)
                )
            )
            table.setCellWidget(row, 4, collect_comments)
            table.setItem(row, 5, table_item(note.comment_count or "-"))
        self.collection_notes_hint.setText(
            f"已加载 {len(notes)} 篇帖子，可采集每帖最多 {self.collection_comment_limit.value()} 条评论"
            if notes
            else "搜索后可打开帖子或采集最多 20 条评论"
        )

    @staticmethod
    def _note_url(note_id: str, xsec_token: str = "", comment_id: str = "") -> QUrl:
        query = (
            urlencode({"xsec_token": xsec_token, "xsec_source": "pc_feed"}) if xsec_token else ""
        )
        fragment = f"#comment-{quote(comment_id)}" if comment_id else ""
        return QUrl(f"https://www.xiaohongshu.com/explore/{quote(note_id)}?{query}{fragment}")

    def open_note_post(self, note: FeedNote) -> None:
        if not note.note_id:
            self._show_error("该帖子缺少笔记 ID，无法定位")
            return
        if not QDesktopServices.openUrl(self._note_url(note.note_id, note.xsec_token)):
            self._show_error("无法打开小红书帖子")
