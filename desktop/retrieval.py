from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

# 英文 / 数字按词切，中文连续段单独取出再切 2-gram。
# 刻意不引入 jieba 之类的分词器：桌面端要多一个依赖和一份词典，
# 而评论这种短查询用 2-gram 已经够用。
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")


def tokenize(text: Any) -> list[str]:
    """切词：英文 / 数字按词，中文按 2-gram，单字保留原样。"""
    tokens: list[str] = []
    for chunk in _TOKEN_PATTERN.findall(str(text).lower()):
        if chunk.isascii() or len(chunk) == 1:
            tokens.append(chunk)
            continue
        tokens.extend(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return tokens


class Bm25Index:
    """最小 BM25 实现，用于在本地问答库里做关键词召回。

    注意 BM25 的分数量纲不可跨语料比较，因此这里只承诺「排序」不承诺「阈值」——
    与热度分的处理原则一致：top-k 负责预算，是否命中用「有无词元交集」判断。
    """

    def __init__(self, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._tokens = [tokenize(document) for document in documents]
        self._lengths = [len(tokens) for tokens in self._tokens]
        self._total = len(self._tokens)
        self._average_length = (sum(self._lengths) / self._total) if self._total else 0.0
        self._frequencies = [Counter(tokens) for tokens in self._tokens]
        document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            document_frequency.update(set(tokens))
        self._document_frequency = document_frequency

    def _idf(self, term: str) -> float:
        frequency = self._document_frequency.get(term, 0)
        if frequency == 0 or self._total == 0:
            return 0.0
        return math.log(1 + (self._total - frequency + 0.5) / (frequency + 0.5))

    def score(self, query: str, index: int) -> float:
        if index < 0 or index >= self._total:
            return 0.0
        terms = tokenize(query)
        if not terms:
            return 0.0
        length = self._lengths[index] or 1
        frequencies = self._frequencies[index]
        total = 0.0
        for term in set(terms):
            term_frequency = frequencies.get(term, 0)
            if not term_frequency:
                continue
            denominator = term_frequency + self.k1 * (
                1 - self.b + self.b * length / (self._average_length or 1)
            )
            total += self._idf(term) * term_frequency * (self.k1 + 1) / denominator
        return total

    def search(self, query: str, top_k: int = 3) -> list[tuple[int, float]]:
        """返回 [(文档下标, 分数)]，只保留真正命中过词元的文档并按分降序。"""
        if top_k <= 0 or not self._total:
            return []
        scored = [(index, self.score(query, index)) for index in range(self._total)]
        hits = [(index, value) for index, value in scored if value > 0]
        hits.sort(key=lambda item: (-item[1], item[0]))
        return hits[:top_k]


def _qa_document(entry: dict[str, Any]) -> str:
    """把一条问答拼成检索文档。

    keywords 是人工维护的强信号，重复一次以提升它在 BM25 里的权重。
    """
    keywords = str(entry.get("keywords", ""))
    return " ".join(
        [
            str(entry.get("question", "")),
            keywords,
            keywords,
            str(entry.get("answer", "")),
        ]
    )


class QaRetriever:
    """问答库召回器：索引只建一次，供整批评论复用。"""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._entries = entries
        self._index = Bm25Index([_qa_document(entry) for entry in entries]) if entries else None

    def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if self._index is None:
            return []
        return [self._entries[position] for position, _ in self._index.search(query, top_k)]
