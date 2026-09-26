from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from mistralai.client import Mistral

from app.eval.golden import GoldenCase, build_golden_set
from app.eval.rag_eval import (
    RetrievalCaseResult,
    RetrievalEvalSummary,
    judge_answer,
    run_answer_eval,
    run_retrieval_eval,
)
from app.llm.models import ModelConfig
from app.llm.provider import ChatMessage, ChatProvider, MistralProvider
from app.rag.retrieval import RetrievedChunk, Retriever


def _chunk(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        source_uri="file:docs/a.md",
        section_anchor="A",
        content="body",
        source_type="policy",
        similarity=0.9,
        score=0.5,
    )


def _cases() -> list[GoldenCase]:
    return build_golden_set()[:3]


class _FakeRetriever:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def retrieve(
        self, query: str, *, dept: str, role: str, top_k: int = 5
    ) -> list[RetrievedChunk]:
        return [_chunk(chunk_id) for chunk_id in self._ids]


async def test_retrieval_eval_counts_hits() -> None:
    cases = _cases()
    retriever = _FakeRetriever(cases[0].expected_source_ids)
    summary = await run_retrieval_eval(cast(Retriever, retriever), cases)

    assert summary.total == 3
    assert summary.recall_at_5 > 0.0
    assert summary.hits >= 1
    assert summary.results[0].hit is True


async def test_retrieval_eval_all_miss() -> None:
    cases = _cases()
    retriever = _FakeRetriever([])
    summary = await run_retrieval_eval(cast(Retriever, retriever), cases)

    assert summary.hits == 0
    assert summary.recall_at_5 == 0.0
    assert all(not result.hit for result in summary.results)


async def test_judge_answer_pass() -> None:
    client = MagicMock()
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="pass"))]
    )
    client.chat.complete_async = AsyncMock(return_value=response)
    provider = MistralProvider(cast(Mistral, client))

    assert await judge_answer(provider, "judge-model", "q", "a", "context") is True


async def test_judge_answer_fail() -> None:
    client = MagicMock()
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="fail"))]
    )
    client.chat.complete_async = AsyncMock(return_value=response)
    provider = MistralProvider(cast(Mistral, client))

    assert await judge_answer(provider, "judge-model", "q", "a", "context") is False


def test_summary_dataclasses_are_frozen() -> None:
    result = RetrievalCaseResult(prompt="p", expected=["a"], retrieved=["b"], hit=False)
    summary = RetrievalEvalSummary(recall_at_5=0.5, total=2, hits=1, results=[result])
    assert summary.recall_at_5 == 0.5


class _FakeAnswerProvider:
    def effective_model(self, model: str) -> str:
        return model

    async def stream(
        self, model: str, messages: Sequence[ChatMessage]
    ) -> AsyncIterator[str]:
        yield "grounded "
        yield "answer"

    async def chat(self, model: str, messages: Sequence[ChatMessage]) -> str:
        return "pass"


async def test_answer_eval_collects_latency_cost_and_verdicts() -> None:
    models = ModelConfig(
        provider="mistral",
        models={"grounding": "g-model", "judge": "j-model", "embed": "e-model"},
    )
    retriever = _FakeRetriever(["c1", "c2"])
    summary = await run_answer_eval(
        cast(Retriever, retriever),
        cast(ChatProvider, _FakeAnswerProvider()),
        models,
        _cases(),
    )

    assert len(summary.results) == 3
    assert all(result.answer == "grounded answer" for result in summary.results)
    assert all(result.judged_correct for result in summary.results)
    assert all(result.first_token_s <= result.latency_s for result in summary.results)
    assert len(summary.judge_verdicts) == 3
    assert summary.answers == ["grounded answer"] * 3
