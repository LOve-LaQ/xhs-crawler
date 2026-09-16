from desktop.ai_service import (
    AnalysisService,
    DeepSeekClient,
    DeepSeekConfig,
    parse_json_response,
    select_analysis_samples,
    truncate_body,
)
from desktop.models import AnalysisReport, FeedNote
from desktop.ui.report_render import report_to_html


def test_parse_json_response_accepts_markdown_fenced_json() -> None:
    result = parse_json_response('```json\n{"summary":"ok","keyFindings":[]}\n```')

    assert result == {"summary": "ok", "keyFindings": []}


def test_analysis_prompt_does_not_include_xsec_token() -> None:
    service = AnalysisService(client=None)
    prompt = service.build_prompt(
        "通勤效率",
        [
            {
                "note_id": "n1",
                "title": "标题",
                "body": "正文",
                "xsec_token": "must-not-leak",
            }
        ],
    )

    assert "must-not-leak" not in prompt
    assert "标题" in prompt
    assert "每篇样本" in prompt


def test_deepseek_client_builds_openai_compatible_request() -> None:
    captured = {}

    def fake_request(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return b'{"choices":[{"message":{"content":"{\\"summary\\":\\"ok\\"}"}}]}'

    client = DeepSeekClient(
        DeepSeekConfig(
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
            model="deepseek-chat",
            max_retries=0,
        ),
        request_fn=fake_request,
    )

    result = client.complete([{"role": "user", "content": "hello"}])

    assert result == '{"summary":"ok"}'
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert '"model": "deepseek-chat"' in captured["body"]
    assert '"response_format": {"type": "json_object"}' in captured["body"]


def test_product_draft_prompt_combines_report_samples_and_product_info() -> None:
    captured = {}

    class FakeClient:
        def complete(self, messages, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return '{"drafts": [{"title": "标题", "content": "正文", "tags": []}]}'

    service = AnalysisService(client=FakeClient())
    service.generate_product_drafts(
        "通勤效率",
        AnalysisReport(summary="强调省时和真实体验"),
        "产品卖点：轻便、可折叠；价格：99元",
        ["product-01.jpg"],
        reference_notes=[FeedNote(note_id="n1", title="爆款标题", body="爆款正文结构")],
        count=20,
    )

    assert "爆款标题" in captured["prompt"]
    assert "爆款正文结构" in captured["prompt"]
    assert "产品卖点：轻便、可折叠" in captured["prompt"]


def test_comment_reply_prompt_uses_product_qa_and_manual_review_constraint() -> None:
    captured = {}

    class FakeClient:
        def complete(self, messages, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return (
                '{"replies":[{"commentId":"c1","reply":"可以试试",'
                '"qaMatches":["尺寸"],"reason":"咨询尺寸",'
                '"scoreFactors":{"intent":24,"relevance":23,"evidence":20,'
                '"naturalness":14,"conversion":13}}]}'
            )

    service = AnalysisService(client=FakeClient())
    replies = service.generate_comment_replies(
        "收纳盒，适合桌面",
        FeedNote(note_id="n1", title="收纳好物"),
        [{"id": "c1", "content": "尺寸多大？", "user": {"nickname": "小红"}}],
        [{"question": "尺寸", "answer": "20cm", "keywords": "尺寸"}],
    )

    assert replies[0]["commentId"] == "c1"
    assert "收纳盒，适合桌面" in captured["prompt"]
    assert "20cm" in captured["prompt"]
    assert "人工确认" in captured["prompt"]
    assert "其他店铺" in captured["prompt"]
    assert "引导用户私信" in captured["prompt"]
    assert "我之前用过一家" in captured["prompt"]
    assert "之前有朋友推荐过一个" in captured["prompt"]
    assert "公共价值优先" in captured["prompt"]
    assert "不要每条都引导私信" in captured["prompt"]
    assert "真实体验" in captured["prompt"]
    assert "补充判断方法" in captured["prompt"]
    assert "扩大话题范围" in captured["prompt"]
    assert "1" in captured["prompt"]
    assert "求" in captured["prompt"]
    assert "短评论" in captured["prompt"]
    assert "scoreFactors" in captured["prompt"]
    assert sum(replies[0]["scoreFactors"].values()) == 94


def test_comment_reply_prompt_clips_large_comment_and_qa_payloads() -> None:
    captured = {}

    class FakeClient:
        def complete(self, messages, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return '{"replies": []}'

    service = AnalysisService(client=FakeClient())
    service.generate_comment_replies(
        "产品信息",
        FeedNote(note_id="n1", title="帖子"),
        # 评论需与问答库有词元交集才会被召回，这里用「尺寸」制造命中
        [{"id": "c1", "content": "尺寸" * 120 + "后" * 240, "user": {"nickname": "用户"}}],
        [{"question": "尺寸问题", "answer": "答" * 500 + "尾" * 100, "keywords": "尺寸"}],
    )

    assert "尺寸" * 120 in captured["prompt"]
    assert "后" * 20 not in captured["prompt"]
    assert "答" * 500 in captured["prompt"]
    assert "尾" * 20 not in captured["prompt"]


def test_comment_reply_prompt_attaches_retrieved_qa_candidates_per_comment() -> None:
    captured = {}

    class FakeClient:
        def complete(self, messages, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return '{"replies": []}'

    service = AnalysisService(client=FakeClient())
    service.generate_comment_replies(
        "产品信息",
        FeedNote(note_id="n1", title="帖子"),
        [
            {"id": "c1", "content": "尺寸多大", "user": {"nickname": "甲"}},
            {"id": "c2", "content": "什么时候发货", "user": {"nickname": "乙"}},
        ],
        [
            {"question": "尺寸", "answer": "尺寸答案", "keywords": "尺寸"},
            {"question": "发货", "answer": "发货答案", "keywords": "物流,发货"},
        ],
    )

    # 每条评论各挂一个候选，而不是把整个问答库 dump 进去
    assert captured["prompt"].count('"candidateQa"') == 2
    assert "尺寸答案" in captured["prompt"]
    assert "发货答案" in captured["prompt"]


def test_report_html_includes_selected_sample_analysis_table() -> None:
    report = AnalysisReport(evidence=[{"noteId": "n1", "analysis": "封面利益点明确"}])
    html = report_to_html(report, [FeedNote(note_id="n1", title="样本标题")])

    assert "样本分析明细" in html
    assert "样本ID" in html
    assert "样本标题" in html
    assert "分析结论" in html
    assert "封面利益点明确" in html


def _make_note(note_id: str, liked: str, body: str = "正文") -> FeedNote:
    return FeedNote(note_id=note_id, title=f"标题{note_id}", body=body, liked_count=liked)


def test_select_analysis_samples_keeps_top_n_by_interaction() -> None:
    notes = [_make_note(f"n{index}", str(10_000 - index * 100)) for index in range(25)]

    selected, scope = select_analysis_samples(notes, limit=20)

    assert len(selected) == 20
    assert selected[0].note_id == "n0"
    assert "样本口径" in scope
    assert "取前 20 篇" in scope


def test_select_analysis_samples_drops_notes_below_interaction_floor() -> None:
    notes = [_make_note("hot", "5000"), _make_note("cold", "100")]

    selected, scope = select_analysis_samples(notes, min_interaction=500)

    assert [note.note_id for note in selected] == ["hot"]
    assert "被过滤" in scope


def test_select_analysis_samples_falls_back_when_all_below_floor() -> None:
    notes = [_make_note("a", "10"), _make_note("b", "80")]

    selected, scope = select_analysis_samples(notes, min_interaction=500)

    assert [note.note_id for note in selected] == ["b"]
    assert "回退" in scope


def test_select_analysis_samples_returns_empty_for_no_notes() -> None:
    assert select_analysis_samples([]) == ([], "")


def test_truncate_body_clips_long_text_and_keeps_short_text() -> None:
    short = truncate_body({"body": "短正文"})
    clipped = truncate_body({"body": "长" * 2000})

    assert short["body"] == "短正文"
    assert clipped["body"].startswith("长" * 100)
    assert len(clipped["body"]) < 2000
    assert "已截断" in clipped["body"]


def test_analysis_prompt_truncates_oversized_sample_body() -> None:
    service = AnalysisService(client=None)

    prompt = service.build_prompt("主题", [_make_note("n1", "1000", body="正" * 3000)])

    assert "正" * 1200 in prompt
    assert "正" * 2000 not in prompt


def test_analyze_records_sample_scope_in_report_and_raw() -> None:
    class FakeClient:
        def complete(self, messages, **kwargs):
            return '{"summary": "ok", "keyFindings": ["原有结论"]}'

    service = AnalysisService(client=FakeClient())
    report = service.analyze("主题", [_make_note(f"n{index}", "1000") for index in range(3)])

    assert report.key_findings[0] == "原有结论"
    assert any("样本口径" in item for item in report.key_findings)
    # 口径必须同时写回 raw，否则 save_report 落库后会丢
    assert any("样本口径" in item for item in report.raw["keyFindings"])


def test_analyze_map_reduce_digests_each_chunk_then_aggregates() -> None:
    prompts = []

    class FakeClient:
        def complete(self, messages, **kwargs):
            prompts.append(messages[-1]["content"])
            if "本批样本" in messages[-1]["content"]:
                return '{"batchSummary": "本批共性", "patterns": [], "notableNotes": []}'
            return '{"summary": "汇总结论", "keyFindings": []}'

    service = AnalysisService(client=FakeClient())
    notes = [_make_note(f"n{index}", "1000") for index in range(45)]

    report = service.analyze("主题", notes, map_reduce=True)

    assert len([prompt for prompt in prompts if "本批样本" in prompt]) == 3
    assert report.summary == "汇总结论"
    assert "未丢弃尾部样本" in report.key_findings[-1]


def test_analyze_map_reduce_is_skipped_when_samples_fit_one_batch() -> None:
    prompts = []

    class FakeClient:
        def complete(self, messages, **kwargs):
            prompts.append(messages[-1]["content"])
            return '{"summary": "ok"}'

    service = AnalysisService(client=FakeClient())

    service.analyze("主题", [_make_note("n1", "1000")], map_reduce=True)

    assert len(prompts) == 1
    assert "本批样本" not in prompts[0]
