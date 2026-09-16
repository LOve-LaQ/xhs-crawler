from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import AnalysisReport, FeedNote, sanitize_for_ai


class AIServiceError(RuntimeError):
    pass


def parse_json_response(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIServiceError(f"模型返回的内容不是有效 JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise AIServiceError("模型返回的 JSON 顶层必须是对象")
    return payload


@dataclass
class DeepSeekConfig:
    base_url: str
    api_key: str
    model: str = "deepseek-chat"
    temperature: float = 0.35
    timeout: int = 120
    max_retries: int = 2


class DeepSeekClient:
    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        request_fn: Callable[[urllib.request.Request, int], bytes] | None = None,
    ) -> None:
        self.config = config
        self._request_fn = request_fn or self._request

    @staticmethod
    def _request(request: urllib.request.Request, timeout: int) -> bytes:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = True) -> str:
        if not self.config.api_key:
            raise AIServiceError("尚未配置 DeepSeek API Key，请在设置中填写")
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                payload = json.loads(self._request_fn(request, self.config.timeout).decode("utf-8"))
                content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not content:
                    raise AIServiceError("DeepSeek 返回了空内容")
                return str(content)
            except (
                AIServiceError,
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(0.6 * (2**attempt))
        raise AIServiceError(f"DeepSeek 调用失败: {last_error}") from last_error


class AnalysisService:
    def __init__(self, client: DeepSeekClient | None) -> None:
        self.client = client

    def build_prompt(self, topic: str, notes: list[dict[str, Any] | FeedNote]) -> str:
        serializable = []
        for note in notes:
            data = note.to_dict(include_secret=False) if isinstance(note, FeedNote) else note
            serializable.append(sanitize_for_ai(data))
        schema = {
            "summary": "一句话总结",
            "keyFindings": ["可验证的内容共性"],
            "titleFormulas": ["标题公式"],
            "contentStructure": {
                "openingHooks": ["开头方式"],
                "bodyPattern": "正文结构",
                "endingHooks": ["结尾方式"],
            },
            "tagStrategy": {"commonTags": ["标签"], "suggestions": ["标签建议"]},
            "coverStyleAnalysis": {"commonStyles": ["封面风格"]},
            "recommendations": ["下一步建议"],
            "evidence": [
                {
                    "noteId": "来源笔记 ID",
                    "title": "样本标题",
                    "analysis": "这篇样本的标题、结构、互动点分析",
                }
            ],
        }
        return (
            "你是小红书内容策略分析师。请只根据提供的样本分析，不要编造数据。\n"
            f"研究主题：{topic}\n"
            "请用简体中文返回严格 JSON，不要 Markdown 代码块。\n"
            "evidence 必须覆盖每篇样本，每篇样本写一条独立分析结果。\n"
            f"输出结构：{json.dumps(schema, ensure_ascii=False)}\n"
            f"样本数据：{json.dumps(serializable, ensure_ascii=False)}"
        )

    def analyze(self, topic: str, notes: list[FeedNote]) -> AnalysisReport:
        if self.client is None:
            raise AIServiceError("尚未配置 DeepSeek 客户端")
        prompt = self.build_prompt(topic, notes)
        content = self.client.complete(
            [
                {"role": "system", "content": "你输出可靠、简洁、可执行的结构化分析。"},
                {"role": "user", "content": prompt},
            ]
        )
        return AnalysisReport.from_dict(parse_json_response(content))

    def generate_draft(self, topic: str, report: AnalysisReport) -> dict[str, Any]:
        if self.client is None:
            raise AIServiceError("尚未配置 DeepSeek 客户端")
        report_json = json.dumps(sanitize_for_ai(report.raw or report.__dict__), ensure_ascii=False)
        prompt = (
            "请根据以下小红书分析报告生成一条原创图文草稿。\n"
            f"主题：{topic}\n"
            f"报告：{report_json}\n"
            '只返回 JSON：{"title":"20字以内标题","content":"正文","tags":["标签1","标签2"]}'
        )
        return parse_json_response(self.client.complete([{"role": "user", "content": prompt}]))

    def generate_product_drafts(
        self,
        topic: str,
        report: AnalysisReport,
        product_info: str,
        asset_names: list[str],
        reference_notes: list[FeedNote] | None = None,
        count: int = 3,
    ) -> dict[str, Any]:
        if self.client is None:
            raise AIServiceError("尚未配置 DeepSeek 客户端")
        report_json = json.dumps(sanitize_for_ai(report.raw or report.__dict__), ensure_ascii=False)
        samples_json = json.dumps(
            [
                sanitize_for_ai(note.to_dict(include_secret=False))
                for note in (reference_notes or [])
            ],
            ensure_ascii=False,
        )
        schema = {
            "drafts": [
                {
                    "title": "20字以内标题",
                    "content": "正文",
                    "tags": ["标签1", "标签2"],
                    "cover_suggestion": "从素材中选择的配图建议",
                }
            ]
        }
        prompt = (
            "你是小红书商品内容策划。请参考竞品分析报告，但不要抄袭竞品原文，生成多组可直接编辑的原创图文草稿。\n"
            f"主题：{topic}\n产品信息：{product_info}\n"
            f"本地图片素材文件名：{json.dumps(asset_names, ensure_ascii=False)}\n"
            f"需要生成数量：{max(1, min(count, 50))}\n"
            f"竞品分析报告：{report_json}\n"
            f"参与分析的参考样本：{samples_json}\n"
            "请提炼参考样本的标题结构、内容节奏、互动触发点和标签规律，"
            "再结合产品信息重新创作，禁止照抄参考样本。\n"
            "标题必须控制在20字以内，正文不得虚构产品信息；"
            "只返回严格 JSON，不要 Markdown 代码块。\n"
            f"输出结构：{json.dumps(schema, ensure_ascii=False)}"
        )
        return parse_json_response(self.client.complete([{"role": "user", "content": prompt}]))

    def generate_comment_replies(
        self,
        product_info: str,
        note: FeedNote,
        comments: list[dict[str, Any]],
        qa_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.client is None:
            raise AIServiceError("尚未配置 DeepSeek 客户端")
        schema = {
            "replies": [
                {
                    "commentId": "评论 ID",
                    "reply": "建议回复",
                    "qaMatches": ["匹配问答"],
                    "reason": "适合回复的原因",
                    "scoreFactors": {
                        "intent": 0,
                        "relevance": 0,
                        "evidence": 0,
                        "naturalness": 0,
                        "conversion": 0,
                    },
                }
            ]
        }
        note_payload = sanitize_for_ai(note.to_dict(include_secret=False))
        if isinstance(note_payload, dict):
            note_payload["body"] = str(note_payload.get("body", ""))[:1800]
        compact_comments = []
        for comment in comments:
            user = comment.get("user", {}) if isinstance(comment, dict) else {}
            compact_comments.append(
                {
                    "id": str(comment.get("id", "")),
                    "content": str(comment.get("content", ""))[:240],
                    "user": {
                        "nickname": str(user.get("nickname", ""))[:60]
                        if isinstance(user, dict)
                        else ""
                    },
                }
            )
        compact_qa = [
            {
                "question": str(entry.get("question", ""))[:160],
                "answer": str(entry.get("answer", ""))[:500],
                "keywords": str(entry.get("keywords", ""))[:160],
            }
            for entry in qa_entries
        ]
        note_json = json.dumps(note_payload, ensure_ascii=False)
        comments_json = json.dumps(sanitize_for_ai(compact_comments), ensure_ascii=False)
        qa_json = json.dumps(sanitize_for_ai(compact_qa), ensure_ascii=False)
        prompt = (
            "你是一名经验丰富的小红书评论区运营，代表与当前帖子无关的其他店铺/品牌，不是帖子博主或博主客服。\n"
            "公共价值优先：先让原评论者和围观读者获得真实、有用的补充，再考虑是否需要继续交流；不要把每条回复都写成截流话术。\n"
            "你的目标是识别真实需求、扩大话题范围和覆盖的使用场景，在不打扰原帖讨论的前提下建立可信度。\n"
            "不得冒充博主客服，不得贬低原博主或竞品，不得诱导违规，不得硬广刷屏。\n"
            "回复必须像真实用户交流：自然、克制、有停顿感和具体场景，不要像客服、广告或统一模板；不可虚构产品能力、价格、库存或使用体验。\n"
            "优先从真实体验展开，例如使用过程、适用边界、前后差异、容易踩坑的地方和什么人可能不适合；"
            "也可以补充判断方法、选择思路、注意事项或相关场景，让回复不局限于直接介绍产品。\n"
            "表达优先采用普通用户分享经验的口吻，而不是客服话术：在产品资料或真实上下文有依据时，"
            "可以用‘我之前用过一家……’、‘之前有朋友推荐过一个……’这类自然引子；没有依据时不要编造亲身经历，"
            "改用中性、可验证的说法。不同评论应有不同长度和句式，不要每条都使用‘先认可+产品优势+私信邀请’的结构。\n"
            "不要每条都引导私信：普通分享、吐槽、泛泛提问或尚未表达购买意向的评论，只提供公开可读的经验和方法，"
            "不要主动出现‘私信我、店铺、购买、链接、加我’等营销词；只有用户明确求链接、求资料、问价格或问怎么买时，"
            "才可以在已经提供有用信息之后，用一句轻量的继续交流邀请承接需求。引导用户私信不是必选项，也不是回复质量的唯一标准。\n"
            "不要因为评论很短就过滤高意向用户：‘1’、‘求’、‘球’、‘蹲’、‘想要’、‘同求’、‘求链接’等短评论，"
            "在结合帖子主题后通常表示想要资料、购买信息或继续沟通，应作为潜在获客机会保留并给出简短自然的私信引导。"
            "这类短评论的需求明确度可以依据上下文评分，不要机械地按字数扣低分。\n"
            "Q&A 问答库是事实优先依据。仅输出建议，必须由人工确认并手动发布，禁止暗示自动评论。\n"
            "请为每条建议按以下 100 分制打分，scoreFactors 必须是整数且总和为 100："
            "intent 评论需求明确度 25 分，relevance 回复与评论匹配度 25 分，"
            "evidence 产品事实依据 20 分，naturalness 真诚自然度 15 分，"
            "conversion 自然承接与获客潜力 15 分（不以是否引导私信为唯一加分项）。"
            "分数越高越适合人工发布。\n"
            f"产品信息：{product_info}\n"
            f"笔记：{note_json}\n"
            f"评论：{comments_json}\n"
            f"Q&A 问答库：{qa_json}\n"
            "只返回严格 JSON，不要 Markdown 代码块。\n"
            f"输出结构：{json.dumps(schema, ensure_ascii=False)}"
        )
        payload = parse_json_response(self.client.complete([{"role": "user", "content": prompt}]))
        replies = payload.get("replies", [])
        return replies if isinstance(replies, list) else []
