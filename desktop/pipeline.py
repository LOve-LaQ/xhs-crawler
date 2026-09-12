from __future__ import annotations

from collections.abc import Callable

from .models import FeedNote


def hydrate_notes(
    notes: list[FeedNote],
    fetch_detail: Callable[[FeedNote], FeedNote],
) -> tuple[list[FeedNote], list[str]]:
    """Fetch details without letting one unavailable note abort a batch."""
    enriched: list[FeedNote] = []
    skipped: list[str] = []
    for note in notes:
        if note.body or not note.xsec_token:
            enriched.append(note)
            continue
        try:
            enriched.append(fetch_detail(note))
        except Exception as exc:  # A single XHS 404/risk block should not abort the batch.
            skipped.append(f"{note.title or note.note_id}: {exc}")
            if note.title.strip() and note.title.strip() != "未命名笔记":
                enriched.append(note)
    if not enriched:
        reason = skipped[0] if skipped else "没有可分析的内容"
        raise RuntimeError(f"所选笔记都无法获取详情，首个原因：{reason}")
    return enriched, skipped
