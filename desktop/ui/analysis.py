from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..assets import list_image_assets
from ..models import AnalysisReport, FeedNote, normalize_feed
from ..pipeline import hydrate_notes
from .report_render import report_to_html, report_to_markdown


class AnalysisMixin:
    """竞品分析与批量草稿创作。"""

    def import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入小红书 JSON", str(Path.cwd()), "JSON 文件 (*.json)"
        )
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
        # 导入没有网络往返，批次当场开、当场结；source 只记文件名，
        # 免得把本机目录结构写进审计记录。
        run_id = self.store.start_collection_run(self.current_task_id, "JSON 导入", Path(path).name)
        self.current_notes = notes
        self.store.save_notes(self.current_task_id, notes, run_id=run_id)
        self.store.update_task(self.current_task_id, status="ready", progress=100)
        self.workspace.save_samples(self.current_task_id, topic, notes)
        self.store.finish_collection_run(
            run_id, status="success", requested=len(notes), fetched=len(notes)
        )
        self._export_collection_log(self.current_task_id)
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
        task_id = self._create_or_reuse_task(topic, self._workflow_task_type("竞品分析"))
        # 分析开始前会把缺正文的样本逐篇补详情，这也是一次真实取数，同样留痕。
        self._begin_collection_run(task_id, "详情补全", f"{len(notes)} 篇样本")
        self.store.update_task(task_id, status="running", progress=15, error="")
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

    def _on_analysis_result(self, result: tuple[list[FeedNote], AnalysisReport, list[str]]) -> None:
        notes, report, skipped = result
        if skipped:
            report.add_finding(
                f"有 {len(skipped)} 篇样本详情未能访问，报告基于其余 {len(notes)} 篇生成。"
            )
        self.current_notes = [
            next((item for item in notes if item.note_id == old.note_id), old)
            for old in self.current_notes
        ]
        self.current_report = report
        self.set_creator_reference_notes([note.note_id for note in notes])
        if hasattr(self, "creator_source_summary"):
            self.creator_source_summary.setText(f"创作依据：已分析 {len(notes)} 篇参考样本")
        if self.current_task_id:
            self.store.save_notes(self.current_task_id, notes, run_id=self._active_run_id)
            self.store.save_report(self.current_task_id, report)
            self.store.update_task(self.current_task_id, status="done", progress=100)
            self.workspace.save_samples(
                self.current_task_id, self.search_input.text().strip() or "内容分析", notes
            )
            self.workspace.save_report(
                self.current_task_id,
                self.search_input.text().strip() or "内容分析",
                report,
                notes,
            )
            self._sync_comment_table()
            # 请求数是选中的样本数（含被跳过的），失败数是详情取不到的篇数。
            self._finish_collection_run(
                "success",
                requested=len(notes) + len(skipped),
                fetched=len(notes),
                failed=len(skipped),
            )
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
            self.creator_asset_summary.setText(
                f"已读取 {len(self.creator_asset_paths)} 张图片：{self.creator_asset_paths[0].name}"
            )
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
        self.creator_batch_selector.addItems(
            [f"方案 {index + 1}" for index in range(len(self.creator_drafts))]
        )
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
        self.creator_tags.setText(
            "、".join(map(str, tags)) if isinstance(tags, list) else str(tags)
        )

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
        tags = [
            tag.strip().lstrip("#")
            for tag in self.draft_tags.text().replace(",", "、").split("、")
            if tag.strip()
        ]
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
            [
                {
                    "title": self.draft_title.text().strip(),
                    "content": self.draft_content.toPlainText().strip(),
                    "tags": tags,
                }
            ],
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
        path, _ = QFileDialog.getSaveFileName(
            self, "导出分析报告", "xhs-analysis.md", "Markdown 文件 (*.md)"
        )
        if not path:
            return
        topic = self.search_input.text().strip() or "小红书内容"
        try:
            Path(path).write_text(report_to_markdown(topic, self.current_report), encoding="utf-8")
        except OSError as exc:
            self._show_error(f"导出失败：{exc}")
            return
        self.show_status(f"报告已导出：{path}")
