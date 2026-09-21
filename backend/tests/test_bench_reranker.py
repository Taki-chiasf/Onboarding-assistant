from scripts.bench_reranker import QUERIES, load_passages


def test_load_passages_returns_non_empty() -> None:
    passages = load_passages()
    assert len(passages) > 40
    assert all(passage.strip() for passage in passages)


def test_queries_are_defined() -> None:
    assert len(QUERIES) >= 5
    assert all(query.strip() for query in QUERIES)
