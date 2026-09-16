from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QPushButton, QTableWidget, QTableWidgetItem

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
