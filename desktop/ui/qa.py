from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from .formatting import table_item


class QaLibraryMixin:
    """Q&A 资料库的维护与导出。"""

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

    def refresh_qa_entries(self) -> None:
        if not hasattr(self, "qa_table"):
            return
        entries = self.store.list_qa_entries(self.qa_search.text())
        self.qa_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            self.qa_table.setItem(row, 0, table_item(entry["question"]))
            self.qa_table.setItem(row, 1, table_item(entry["answer"]))
            self.qa_table.setItem(row, 2, table_item(entry["keywords"]))
            self.qa_table.setItem(row, 3, table_item(entry["updated_at"].replace("T", " ")[:16]))
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
