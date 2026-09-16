from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


def _first(mapping: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def _user_name(user: dict[str, Any]) -> str:
    return str(_first(user, "nickname", "nickName", "nick_name", default="未知用户"))


@dataclass
class FeedNote:
    note_id: str
    title: str
    body: str = ""
    note_type: str = ""
    author: str = ""
    liked_count: str = ""
    collected_count: str = ""
    comment_count: str = ""
    tags: list[str] = field(default_factory=list)
    cover_url: str = ""
    xsec_token: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def interaction_score(self) -> int:
        def as_number(value: str) -> float:
            value = str(value).strip().lower().replace(",", "")
            if not value:
                return 0
            multiplier = 1000 if value.endswith("k") else 10000 if value.endswith("w") else 1
            value = value.rstrip("kw")
            try:
                return float(value) * multiplier
            except ValueError:
                return 0

        return round(
            as_number(self.liked_count)
            + as_number(self.collected_count) * 1.4
            + as_number(self.comment_count) * 1.8
        )

    def to_dict(self, include_secret: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        if not include_secret:
            data.pop("xsec_token", None)
        return data


@dataclass
class AnalysisReport:
    summary: str = ""
    key_findings: list[str] = field(default_factory=list)
    title_formulas: list[str] = field(default_factory=list)
    content_structure: dict[str, Any] = field(default_factory=dict)
    tag_strategy: dict[str, Any] = field(default_factory=dict)
    cover_style_analysis: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisReport:
        return cls(
            summary=str(data.get("summary", "")),
            key_findings=_as_string_list(data.get("keyFindings", data.get("key_findings", []))),
            title_formulas=_as_string_list(
                data.get("titleFormulas", data.get("title_formulas", []))
            ),
            content_structure=_as_dict(data.get("contentStructure", data.get("content_structure"))),
            tag_strategy=_as_dict(data.get("tagStrategy", data.get("tag_strategy"))),
            cover_style_analysis=_as_dict(
                data.get("coverStyleAnalysis", data.get("cover_style_analysis"))
            ),
            recommendations=_as_string_list(data.get("recommendations", [])),
            evidence=data.get("evidence", []) if isinstance(data.get("evidence", []), list) else [],
            raw=data,
        )

    def add_finding(self, text: str) -> None:
        """追写一条结论，并同步写回 raw。

        save_report 持久化的就是 raw，只改 key_findings 会在落库后丢失；
        两处同写才能保证「报告已归档」时这条口径仍在。
        """
        if not text:
            return
        self.key_findings.append(text)
        findings = self.raw.setdefault("keyFindings", [])
        if isinstance(findings, list):
            findings.append(text)


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_feed(data: dict[str, Any]) -> FeedNote:
    """Normalize CLI search results and detail responses into one local shape."""
    note = data.get("note") if isinstance(data.get("note"), dict) else data
    note_card = note.get("noteCard") if isinstance(note.get("noteCard"), dict) else note
    user = note.get("user") or note_card.get("user") or {}
    interact = note.get("interactInfo") or note_card.get("interactInfo") or {}
    cover = note.get("cover") or note_card.get("cover") or {}
    if isinstance(cover, str):
        cover_url = cover
    else:
        cover_url = str(_first(cover, "url", "urlDefault", "url_default", default=""))

    return FeedNote(
        note_id=str(_first(note, "noteId", "note_id", "id", default="")),
        title=str(
            _first(
                note,
                "title",
                "displayTitle",
                "display_title",
                default="未命名笔记",
            )
        ),
        body=str(_first(note, "body", "desc", "description", default="")),
        note_type=str(_first(note, "type", "noteType", "note_type", default="")),
        author=_user_name(user),
        liked_count=str(_first(interact, "likedCount", "liked_count", default="")),
        collected_count=str(_first(interact, "collectedCount", "collected_count", default="")),
        comment_count=str(_first(interact, "commentCount", "comment_count", default="")),
        tags=[str(item) for item in _first(note, "tags", default=[]) if item],
        cover_url=cover_url,
        xsec_token=str(_first(data, "xsecToken", "xsec_token", default="")),
        raw=data,
    )


_SENSITIVE_KEYS = {
    "a1",
    "authorization",
    "cookie",
    "cookies",
    "password",
    "session",
    "user_id",
    "userid",
    "web_session",
    "websession",
    "xs",
    "xsec_token",
    "xsectoken",
}


def sanitize_for_ai(value: Any) -> Any:
    """Remove browser credentials and account identifiers before model calls."""
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized = re.sub(r"[-\s]", "_", str(key).strip().lower())
            if normalized in _SENSITIVE_KEYS:
                continue
            safe[str(key)] = sanitize_for_ai(item)
        return safe
    if isinstance(value, list):
        return [sanitize_for_ai(item) for item in value]
    return value
