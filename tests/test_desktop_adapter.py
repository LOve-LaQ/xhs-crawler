import sys

from desktop.models import FeedNote
from desktop.pipeline import hydrate_notes
from desktop.xhs_adapter import XhsCliAdapter, build_cli_command


def test_build_search_command_uses_repository_cli() -> None:
    command = build_cli_command(
        "search-feeds",
        "--keyword",
        "通勤效率",
        "--sort-by",
        "最多点赞",
    )

    assert command[:2] == [sys.executable, "scripts/cli.py"]
    assert command[2:] == ["search-feeds", "--keyword", "通勤效率", "--sort-by", "最多点赞"]


def test_one_unavailable_note_does_not_abort_batch() -> None:
    good = FeedNote(note_id="good", title="可访问", xsec_token="token")
    bad = FeedNote(note_id="bad", title="未命名笔记", xsec_token="token")

    def fetch_detail(note: FeedNote) -> FeedNote:
        if note.note_id == "bad":
            raise RuntimeError("笔记被风控拦截")
        note.body = "详情正文"
        return note

    enriched, skipped = hydrate_notes([good, bad], fetch_detail)

    assert [note.note_id for note in enriched] == ["good"]
    assert skipped == ["未命名笔记: 笔记被风控拦截"]


def test_detail_command_limits_collected_comments() -> None:
    adapter = XhsCliAdapter()
    captured: list[str] = []
    adapter.run_json = lambda *args, **kwargs: (
        captured.extend(args) or {"noteId": "n1", "title": "标题"}
    )  # type: ignore[method-assign]

    adapter.get_feed_detail(
        FeedNote(note_id="n1", title="标题", xsec_token="token"),
        load_all_comments=True,
        max_comment_items=20,
    )

    assert "--load-all-comments" in captured
    assert captured[captured.index("--max-comment-items") + 1] == "20"


def test_locate_comment_command_uses_comment_id_without_publish_action() -> None:
    adapter = XhsCliAdapter()
    captured: list[str] = []
    adapter.run_json = lambda *args: captured.extend(args) or {"success": True}  # type: ignore[method-assign]

    adapter.locate_comment(
        FeedNote(note_id="n1", title="标题", xsec_token="token"),
        comment_id="c1",
    )

    assert captured[:5] == [
        "locate-comment",
        "--feed-id",
        "n1",
        "--xsec-token",
        "token",
    ]
    assert captured[-2:] == ["--comment-id", "c1"]
    assert "post-comment" not in captured
    assert "reply-comment" not in captured
