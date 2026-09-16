from desktop.models import FeedNote, normalize_feed, sanitize_for_ai


def test_normalize_cli_feed_to_note() -> None:
    note = normalize_feed(
        {
            "id": "note-1",
            "xsecToken": "secret-token",
            "displayTitle": "通勤路上适合听的播客",
            "type": "图文",
            "user": {"userId": "user-1", "nickname": "城市耳朵"},
            "interactInfo": {
                "likedCount": "7.2k",
                "collectedCount": "1.4k",
                "commentCount": "181",
            },
        }
    )

    assert note == FeedNote(
        note_id="note-1",
        title="通勤路上适合听的播客",
        note_type="图文",
        author="城市耳朵",
        liked_count="7.2k",
        collected_count="1.4k",
        comment_count="181",
        xsec_token="secret-token",
    )


def test_sanitize_for_ai_removes_credentials_recursively() -> None:
    safe = sanitize_for_ai(
        {
            "note": {"title": "测试", "xsecToken": "token", "userId": "user"},
            "cookies": {"web_session": "session", "a1": "a1-value"},
            "body": "正常内容",
        }
    )

    assert safe == {"note": {"title": "测试"}, "body": "正常内容"}
