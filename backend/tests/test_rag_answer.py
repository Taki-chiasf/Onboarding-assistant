from collections.abc import AsyncIterator, Sequence
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.auth.principal import Principal
from app.llm.models import ModelConfig
from app.llm.provider import MistralProvider
from app.rag import answer as answer_mod
from app.rag.answer import RagAnswerer
from app.rag.retrieval import RetrievedChunk, Retriever


def _principal() -> Principal:
    return Principal(sub="alex", email="alex@example.com", dept="Engineering", role="employee")


def _models() -> ModelConfig:
    return ModelConfig(
        provider="mistral",
        models={"grounding": "mistral-large-2512", "embed": "mistral-embed"},
    )


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        id="chunk-1",
        source_uri="file:docs/a.md",
        section_anchor="A",
        content="16 weeks of leave",
        source_type="policy",
        similarity=0.9,
        score=0.5,
    )


class _FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.source_types: Sequence[str] | None = None

    async def retrieve(
        self,
        query: str,
        *,
        dept: str,
        role: str,
        source_types: Sequence[str] | None = None,
        **_: object,
    ) -> list[RetrievedChunk]:
        self.source_types = source_types
        return self._chunks


class _FakeProvider:
    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.stream_calls = 0

    def effective_model(self, model: str) -> str:
        return model

    async def stream(self, model: str, messages: list[object]) -> AsyncIterator[str]:
        self.stream_calls += 1
        for token in self._tokens:
            yield token


class _FakeSession:
    def __init__(self, added: list[Any]) -> None:
        self.added = added
        self.committed = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed += 1

    async def execute(self, statement: object) -> None:
        return None

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _patch_session_factory(monkeypatch: pytest.MonkeyPatch, added: list[Any]) -> None:
    def factory() -> _FakeSession:
        return _FakeSession(added)

    monkeypatch.setattr(answer_mod, "async_sessionmaker", lambda engine, expire_on_commit: factory)


def _answerer(
    provider: _FakeProvider, chunks: list[RetrievedChunk]
) -> tuple[RagAnswerer, _FakeRetriever]:
    retriever = _FakeRetriever(chunks)
    answerer = RagAnswerer(
        MagicMock(),
        cast(MistralProvider, provider),
        _models(),
        cast(Retriever, retriever),
    )
    return answerer, retriever


async def test_stream_cite_or_die_without_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    provider = _FakeProvider([])
    answerer, _ = _answerer(provider, [])

    events = [e async for e in answerer.stream("hello", _principal())]

    assert [e["event"] for e in events] == ["sources", "token", "done"]
    assert events[1]["data"]["text"] == "I don't know"
    done = events[2]["data"]
    assert done["answer"] == "I don't know"
    assert done["tokens_in"] == 0
    assert provider.stream_calls == 0


async def test_stream_grounds_and_streams_with_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    provider = _FakeProvider(["16 ", "weeks"])
    answerer, _ = _answerer(provider, [_chunk()])

    events = [e async for e in answerer.stream("how much leave?", _principal())]

    assert [e["event"] for e in events] == ["sources", "token", "token", "done"]
    assert events[0]["data"]["sources"][0]["id"] == "chunk-1"
    assert events[1]["data"]["text"] == "16 "
    assert events[2]["data"]["text"] == "weeks"
    done = events[3]["data"]
    assert done["answer"] == "16 weeks"
    assert done["prompt_version"] == "grounding.v1"
    assert done["tokens_out"] > 0

    assistant = [obj for obj in added if getattr(obj, "role", None) == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == "16 weeks"
    assert assistant[0].detail == {
        "sources": [
            {
                "id": "chunk-1",
                "source_uri": "file:docs/a.md",
                "section_anchor": "A",
                "score": 0.5,
            }
        ]
    }


async def test_stream_passes_source_type_restriction(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    answerer, retriever = _answerer(_FakeProvider(["ok"]), [_chunk()])

    _ = [e async for e in answerer.stream("deploy", _principal(), source_types=("engineering",))]

    assert retriever.source_types == ("engineering",)
