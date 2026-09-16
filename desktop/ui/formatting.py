from __future__ import annotations

import html
from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidgetItem


def bullet_list(items: list[str]) -> str:
    if not items:
        return "<p class='muted'>暂无内容</p>"
    return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def table_item(text: Any) -> QTableWidgetItem:
    value = "" if text is None else str(text)
    item = QTableWidgetItem(value)
    if len(value) > 18 or "\n" in value:
        item.setToolTip(value)
    return item


def comment_score(response: dict[str, Any]) -> tuple[int, dict[str, int]]:
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


def score_color(score: int) -> QColor:
    if score >= 85:
        return QColor("#e4f5ea")
    if score >= 70:
        return QColor("#fff1cf")
    if score >= 50:
        return QColor("#ffead7")
    return QColor("#fde2e2")
