from __future__ import annotations

import html
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from .widgets import Worker


class InteractionMixin:
    """交互基础设施：导航、状态栏、Worker 调度与剪贴板。"""

    def navigate_to(self, page_name: str) -> None:
        """Switch the visible workbench section and keep the sidebar state in sync."""
        index = self.page_indices.get(page_name)
        if index is None:
            return
        self.page_stack.setCurrentIndex(index)
        titles = {
            "工作台": ("先看清楚，再开始创作。", "从真实的小红书内容里，找到下一篇值得写的东西。"),
            "运营工作流": (
                "选择一条运营链路。",
                "从搜索、分析到创作和互动，每一步都保留在本地工作区。",
            ),
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
        button.clicked.connect(
            lambda checked=False, target=button: self._copy_from_button(target, source, label)
        )
        return button

    def _copy_from_button(self, button: QPushButton, source: Callable[[], str], label: str) -> None:
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
        worker.signals.finished.connect(lambda worker=worker: self._release_worker(worker, button))
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
