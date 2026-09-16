from desktop.retrieval import Bm25Index, QaRetriever, tokenize

QA_LIBRARY = [
    {"question": "发货时间", "answer": "48 小时内发出", "keywords": "物流,发货"},
    {"question": "尺寸", "answer": "20cm x 10cm", "keywords": "尺寸,大小"},
]


def test_tokenize_splits_english_words_and_chinese_bigrams() -> None:
    assert tokenize("通勤 bag2") == ["通勤", "bag2"]


def test_tokenize_keeps_single_chinese_character() -> None:
    assert tokenize("蹲") == ["蹲"]


def test_tokenize_returns_empty_for_blank_text() -> None:
    assert tokenize("   ") == []


def test_qa_retriever_ranks_keyword_match_first() -> None:
    retriever = QaRetriever(QA_LIBRARY)

    hits = retriever.search("这个尺寸多大", top_k=1)

    assert hits[0]["answer"] == "20cm x 10cm"


def test_qa_retriever_drops_entries_without_token_overlap() -> None:
    retriever = QaRetriever(QA_LIBRARY)

    assert retriever.search("完全无关的另一个话题") == []


def test_qa_retriever_respects_top_k() -> None:
    library = [
        {"question": f"尺寸问题{index}", "answer": f"{index}cm", "keywords": "尺寸"}
        for index in range(5)
    ]

    assert len(QaRetriever(library).search("尺寸", top_k=2)) == 2


def test_qa_retriever_handles_empty_library() -> None:
    assert QaRetriever([]).search("尺寸") == []


def test_bm25_index_reports_no_hits_for_unrelated_query() -> None:
    index = Bm25Index(["尺寸 大小", "物流 发货"])

    assert index.search("苹果", top_k=2) == []


def test_bm25_index_prefers_shorter_document_for_same_term_hit() -> None:
    # 同样命中「尺寸」，短文档的归一化权重应高于被大量无关词稀释的长文档
    index = Bm25Index(["尺寸", "尺寸 " + "无关词 ".join(f"d{position}" for position in range(40))])

    hits = index.search("尺寸", top_k=2)

    assert [position for position, _ in hits] == [0, 1]
