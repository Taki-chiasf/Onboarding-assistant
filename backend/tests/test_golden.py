import uuid

from app.eval.golden import (
    INTENT_RAG_DOCS,
    build_golden_set,
    corpus_documents,
    recall_at_k,
)
from app.rag import chunk_id


def test_golden_set_has_at_least_fifty_cases() -> None:
    cases = build_golden_set()
    assert len(cases) >= 50


def test_golden_cases_have_expected_sources() -> None:
    cases = build_golden_set()
    for case in cases:
        assert case.expected_source_ids
        assert case.expected_intent == INTENT_RAG_DOCS
        for source_id in case.expected_source_ids:
            uuid.UUID(source_id)


def test_golden_set_covers_all_domains() -> None:
    cases = build_golden_set()
    domains = {case.tags[1] for case in cases}
    assert {"policy", "handbook", "runbook", "engineering"} <= domains


def test_golden_set_is_deterministic() -> None:
    first = build_golden_set()
    second = build_golden_set()
    assert [(c.prompt, c.expected_source_ids) for c in first] == [
        (c.prompt, c.expected_source_ids) for c in second
    ]


def test_expected_ids_match_chunk_ids() -> None:
    cases = {c.prompt: c for c in build_golden_set()}
    case = cases["How many weeks of paid parental leave do employees get?"]
    source_uri = "file:policies/parental-leave.md"
    assert case.expected_source_ids
    valid = {str(chunk_id(source_uri, index)) for index in range(0, 10)}
    assert set(case.expected_source_ids) <= valid


def test_corpus_documents_has_all_markdown() -> None:
    documents = corpus_documents()
    assert len(documents) == 44
    assert all(content.strip() for content in documents.values())


def test_recall_at_k() -> None:
    expected = ["a", "b"]
    assert recall_at_k(expected, ["a", "c"], k=5)
    assert recall_at_k(expected, ["x", "y", "b"], k=3)
    assert not recall_at_k(expected, ["x", "y"], k=5)
    assert recall_at_k(expected, ["x", "a"], k=2)
    assert not recall_at_k(expected, ["x", "a"], k=1)
