from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..models import FeedNote
from .formatting import comment_score, score_color, table_item


class CommentsMixin:
    """评论运营：AI 回复建议、评分、定位与状态流转。"""

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
        self.current_notes = [
            detail if item.note_id == detail.note_id else item for item in self.current_notes
        ]
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
            self.show_status(
                f"《{original.title}》已保存 {comment_count} 条原始评论，可点击“AI 筛选建议”"
            )

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
                    score, factors = comment_score(response)
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
            self.store.list_comment_opportunities(self.current_task_id, self.comment_search.text())
            if self.current_task_id
            else []
        )
        table = self.comment_opportunity_table
        table.setRowCount(len(items))
        for row, item in enumerate(items):
            score = max(0, min(100, int(item.get("score", 0) or 0)))
            score_item = table_item(score)
            score_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            score_item.setBackground(score_color(score))
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
                cell = table_item(item.get(key, ""))
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
            reply_editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
                lambda checked=False, button=copy_button, editor=reply_editor: (
                    self._copy_from_button(button, editor.text, "评论建议")
                )
            )
            comment_button = QPushButton("评论")
            comment_button.setObjectName("tableActionButton")
            comment_button.setMinimumWidth(60)
            comment_button.setFixedHeight(28)
            comment_button.clicked.connect(
                lambda checked=False, record=item, target_row=row: self.open_comment_location(
                    record, target_row
                )
            )
            marked = QPushButton("标记已评论")
            marked.setObjectName("tableActionButton")
            marked.setMinimumWidth(112)
            marked.setFixedHeight(28)
            marked.setEnabled(item.get("status") != "已评论")
            marked.clicked.connect(
                lambda checked=False, opportunity_id=item["id"]: self.mark_comment_commented(
                    opportunity_id
                )
            )
            action_layout.addWidget(copy_button)
            action_layout.addWidget(comment_button)
            action_layout.addWidget(marked)
            table.setCellWidget(row, 7, actions)
        stats = (
            self.store.comment_opportunity_stats(self.current_task_id)
            if self.current_task_id
            else {"total": 0, "pending": 0, "commented": 0}
        )
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
            on_error=lambda message, record=record: self._fallback_comment_location(
                record, message
            ),
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
