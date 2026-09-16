from desktop.ai_service import AnalysisService, DeepSeekClient, DeepSeekConfig, parse_json_response
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
        [{"id": "c1", "content": "前" * 240 + "后" * 240, "user": {"nickname": "用户"}}],
        [{"question": "问题", "answer": "答" * 500 + "尾" * 100, "keywords": "关键词"}],
    )

    assert "前" * 240 in captured["prompt"]
    assert "后" * 20 not in captured["prompt"]
    assert "答" * 500 in captured["prompt"]
    assert "尾" * 20 not in captured["prompt"]


def test_report_html_includes_selected_sample_analysis_table() -> None:
    report = AnalysisReport(evidence=[{"noteId": "n1", "analysis": "封面利益点明确"}])
    html = report_to_html(report, [FeedNote(note_id="n1", title="样本标题")])

    assert "样本分析明细" in html
    assert "样本ID" in html
    assert "样本标题" in html
    assert "分析结论" in html
    assert "封面利益点明确" in html
