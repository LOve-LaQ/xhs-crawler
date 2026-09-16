from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import AnalysisReport, FeedNote, sanitize_for_ai
from .retrieval import QaRetriever


class AIServiceError(RuntimeError):
    pass


# --- 分析样本预算（Tier 0）----------------------------------------------------
# 上下文窗口是硬资源，所以用固定的「条数 + 单篇字数」上限控制预算。
# interaction_score 是未校准的热度加权和：它只适合排序，不适合当成概率分布做
# top-p / 百分位截断 —— 同一条 p 在不同关键词下选出的样本数会剧烈漂移，
# 同一主题两次分析也会拿到不同样本，报告既不可控也不可复现。
# 因此让 top-N 负责「不超窗」，绝对下限 floor 负责「不掺水」，两者职责分离。
MAX_ANALYSIS_SAMPLES = 20
MAX_ANALYSIS_BODY_CHARS = 1200
MIN_ANALYSIS_INTERACTION = 500
MAP_REDUCE_CHUNK_SIZE = 20
COMMENT_QA_TOP_K = 3

_ANALYSIS_SCHEMA: dict[str, Any] = {
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

_DIGEST_SCHEMA: dict[str, Any] = {
    "batchSummary": "本批样本的共性",
    "patterns": ["可复用的标题 / 结构 / 标签规律"],
    "notableNotes": [{"noteId": "来源笔记 ID", "title": "样本标题", "why": "值得单独记录的原因"}],
}


def truncate_body(payload: dict[str, Any]) -> dict[str, Any]:
    """截断单篇正文，避免少数长文吃掉整批预算。"""
    body = str(payload.get("body", ""))
    if len(body) > MAX_ANALYSIS_BODY_CHARS:
        payload["body"] = f"{body[:MAX_ANALYSIS_BODY_CHARS]}…（正文已截断）"
    return payload


def analysis_payload(note: dict[str, Any] | FeedNote) -> dict[str, Any]:
    """把样本整理成送模型的形态：去敏感字段 + 截断正文。"""
    data = note.to_dict(include_secret=False) if isinstance(note, FeedNote) else note
    payload = sanitize_for_ai(data)
    return truncate_body(payload if isinstance(payload, dict) else {})


def select_analysis_samples(
    notes: list[FeedNote],
    *,
    limit: int = MAX_ANALYSIS_SAMPLES,
    min_interaction: int = MIN_ANALYSIS_INTERACTION,
) -> tuple[list[FeedNote], str]:
    """按互动热度取 top-N，并丢掉低于质量下限的样本。

    top-N 控制上下文预算，floor 控制样本质量；若全部低于下限则保底回退热度最高的一篇，
    避免质量闸门把分析变成「无输入」。返回 (入选样本, 口径说明)，口径会写进报告用于留档自证。
    """
    if not notes:
        return [], ""
    ranked = sorted(notes, key=lambda item: item.interaction_score, reverse=True)
    qualified = [item for item in ranked if item.interaction_score >= min_interaction]
    if not qualified:
        return (
            ranked[:1],
            f"样本口径：{len(notes)} 篇候选热度均低于 {min_interaction}，已回退热度最高的 1 篇",
        )
    selected = qualified[: max(1, limit)]
    parts = [f"样本口径：按互动热度取前 {len(selected)} 篇（共 {len(notes)} 篇候选）"]
    if len(qualified) > len(selected):
        parts.append(f"其余 {len(qualified) - len(selected)} 篇超出单批上限 {limit} 未纳入")
    if len(ranked) > len(qualified):
        parts.append(f"{len(ranked) - len(qualified)} 篇因热度低于 {min_interaction} 被过滤")
    return selected, "；".join(parts)


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
        serializable = [analysis_payload(note) for note in notes]
        return (
            "你是小红书内容策略分析师。请只根据提供的样本分析，不要编造数据。\n"
            f"研究主题：{topic}\n"
            "请用简体中文返回严格 JSON，不要 Markdown 代码块。\n"
            "evidence 必须覆盖每篇样本，每篇样本写一条独立分析结果。\n"
            f"输出结构：{json.dumps(_ANALYSIS_SCHEMA, ensure_ascii=False)}\n"
            f"样本数据：{json.dumps(serializable, ensure_ascii=False)}"
        )

    def _require_client(self) -> DeepSeekClient:
        if self.client is None:
            raise AIServiceError("尚未配置 DeepSeek 客户端")
        return self.client

    def analyze(
        self,
        topic: str,
        notes: list[FeedNote],
        *,
        map_reduce: bool = False,
    ) -> AnalysisReport:
        """默认只把 top-N 样本送进单次调用，保证上下文预算可控且结果可复现。

        map_reduce=True 时改为「先分批归纳、再汇总」：代价是调用次数按批数增长，
        收益是不丢尾部样本——因此默认关闭，只在候选远多于单批上限时显式开启。
        """
        self._require_client()
        selected, scope_note = select_analysis_samples(notes)
        if not selected:
            raise AIServiceError("没有可分析的样本")
        if map_reduce and len(notes) > len(selected):
            return self._analyze_map_reduce(topic, notes)
        report = self._analyze_single_pass(topic, selected)
        if scope_note:
            report.add_finding(scope_note)
        return report

    def _analyze_single_pass(self, topic: str, notes: list[FeedNote]) -> AnalysisReport:
        content = self._require_client().complete(
            [
                {"role": "system", "content": "你输出可靠、简洁、可执行的结构化分析。"},
                {"role": "user", "content": self.build_prompt(topic, notes)},
            ]
        )
        return AnalysisReport.from_dict(parse_json_response(content))

    def _digest_chunk(self, topic: str, chunk: list[FeedNote]) -> dict[str, Any]:
        samples = json.dumps([analysis_payload(note) for note in chunk], ensure_ascii=False)
        prompt = (
            "你是小红书内容策略分析师。请只根据本批样本做归纳，不要编造数据。\n"
            f"研究主题：{topic}\n"
            "只返回严格 JSON，不要 Markdown 代码块。\n"
            f"输出结构：{json.dumps(_DIGEST_SCHEMA, ensure_ascii=False)}\n"
            f"本批样本：{samples}"
        )
        return parse_json_response(
            self._require_client().complete([{"role": "user", "content": prompt}])
        )

    def _analyze_map_reduce(self, topic: str, notes: list[FeedNote]) -> AnalysisReport:
        ranked = sorted(notes, key=lambda item: item.interaction_score, reverse=True)
        chunks = [
            ranked[index : index + MAP_REDUCE_CHUNK_SIZE]
            for index in range(0, len(ranked), MAP_REDUCE_CHUNK_SIZE)
        ]
        digests = [self._digest_chunk(topic, chunk) for chunk in chunks]
        prompt = (
            "你是小红书内容策略分析师。下面是分批归纳出的要点，请汇总为一份完整报告。\n"
            "只依据这些要点，不要编造数据。\n"
            f"研究主题：{topic}\n"
            "请用简体中文返回严格 JSON，不要 Markdown 代码块。\n"
            f"输出结构：{json.dumps(_ANALYSIS_SCHEMA, ensure_ascii=False)}\n"
            f"分批要点：{json.dumps(digests, ensure_ascii=False)}"
        )
        content = self._require_client().complete(
            [
                {"role": "system", "content": "你输出可靠、简洁、可执行的结构化分析。"},
                {"role": "user", "content": prompt},
            ]
        )
        report = AnalysisReport.from_dict(parse_json_response(content))
        report.add_finding(
            f"样本口径：{len(ranked)} 篇候选按每批 {MAP_REDUCE_CHUNK_SIZE} 篇分 "
            f"{len(chunks)} 批归纳后汇总，未丢弃尾部样本"
        )
        return report

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

    def _match_qa_for_comments(
        self,
        comments: list[dict[str, Any]],
        qa_entries: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """为每条评论召回 top-k 问答，替代「整个问答库 × 全部评论」的交叉匹配。

        全量 dump 时每条评论都要与问答库整体比对，注意力被稀释且容易配错；
        按 top-k 召回后总预算 = 评论数 × k，条数可控、可预测。
        """
        retriever = QaRetriever(qa_entries)
        matches: list[list[dict[str, Any]]] = []
        for comment in comments:
            content = str(comment.get("content", "")) if isinstance(comment, dict) else ""
            matches.append(
                [
                    {
                        "question": str(entry.get("question", ""))[:160],
                        "answer": str(entry.get("answer", ""))[:500],
                        "keywords": str(entry.get("keywords", ""))[:160],
                    }
                    for entry in retriever.search(content, COMMENT_QA_TOP_K)
                ]
            )
        return matches

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
        qa_matches = self._match_qa_for_comments(compact_comments, qa_entries)
        for comment, matches in zip(compact_comments, qa_matches, strict=True):
            comment["candidateQa"] = matches
        note_json = json.dumps(note_payload, ensure_ascii=False)
        comments_json = json.dumps(sanitize_for_ai(compact_comments), ensure_ascii=False)
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
            "每条评论的 candidateQa 字段是该评论从本地问答库召回的相关条目，可能为空数组；"
            "没有匹配时不要强行引用问答库。\n"
            "Q&A 问答库是事实优先依据。仅输出建议，必须由人工确认并手动发布，禁止暗示自动评论。\n"
            "请为每条建议按以下 100 分制打分，scoreFactors 必须是整数且总和为 100："
            "intent 评论需求明确度 25 分，relevance 回复与评论匹配度 25 分，"
            "evidence 产品事实依据 20 分，naturalness 真诚自然度 15 分，"
            "conversion 自然承接与获客潜力 15 分（不以是否引导私信为唯一加分项）。"
            "分数越高越适合人工发布。\n"
            f"产品信息：{product_info}\n"
            f"笔记：{note_json}\n"
            f"评论：{comments_json}\n"
            "只返回严格 JSON，不要 Markdown 代码块。\n"
            f"输出结构：{json.dumps(schema, ensure_ascii=False)}"
        )
        payload = parse_json_response(self.client.complete([{"role": "user", "content": prompt}]))
        replies = payload.get("replies", [])
        return replies if isinstance(replies, list) else []
