from collections.abc import AsyncIterator, Sequence
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.auth.principal import Principal
from app.core.moderation import ScreenResult
from app.llm.fake import FakeProvider
from app.llm.provider import ModerationVerdict
from app.rag.answer import RagAnswerer
from app.router import dispatcher as dispatcher_mod
from app.router.dispatcher import REFUSAL, ChatDispatcher, pinned_decision
from app.router.router import IntentRouter
from app.router.schema import (
    ClarifyOption,
    ClarifyPrompt,
    Intent,
    RouteDecision,
    Surface,
)
from app.text_to_sql.answer import SqlAnswerer


def _principal() -> Principal:
    return Principal(sub="alex", email="alex@example.com", dept="Engineering", role="employee")


def _decision(intent: Intent, *, clarify: ClarifyPrompt | None = None) -> RouteDecision:
    return RouteDecision(
        intent=intent,
        confidence=0.9,
        surfaces=[],
        entities=[],
        rationale="test",
        source="router",
        clarify=clarify,
    )


class _FakeRouter:
    def __init__(self, decision: RouteDecision) -> None:
        self._decision = decision
        self.prompt_version = "router.v1"
        self.calls = 0

    async def decide(self, query: str) -> RouteDecision:
        self.calls += 1
        return self._decision


class _FakeRag:
    def __init__(self) -> None:
        self.source_types: Sequence[str] | None = None
        self.route: dict[str, Any] | None = None
        self.calls = 0

    async def stream(
        self,
        query: str,
        principal: Principal,
        conversation_id: object = None,
        *,
        source_types: Sequence[str] | None = None,
        route: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        self.source_types = source_types
        self.route = route
        yield {"event": "sources", "data": {"conversation_id": "c1", "sources": []}}
        yield {"event": "token", "data": {"text": "doc answer"}}
        yield {"event": "done", "data": {"answer": "doc answer"}}


class _FakeSql:
    def __init__(self) -> None:
        self.calls = 0
        self.route: dict[str, Any] | None = None

    async def stream(
        self,
        query: str,
        principal: Principal,
        conversation_id: object = None,
        *,
        route: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls += 1
        self.route = route
        yield {"event": "sql", "data": {"sql": "SELECT 1"}}
        yield {"event": "done", "data": {"answer": "sql answer"}}


class _FakeSession:
    def __init__(self, added: list[Any]) -> None:
        self.added = added

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _patch_session_factory(monkeypatch: pytest.MonkeyPatch, added: list[Any]) -> None:
    def factory() -> _FakeSession:
        return _FakeSession(added)

    monkeypatch.setattr(
        dispatcher_mod, "async_sessionmaker", lambda engine, expire_on_commit: factory
    )


def _dispatcher(router: _FakeRouter, rag: _FakeRag, sql: _FakeSql) -> ChatDispatcher:
    return ChatDispatcher(
        MagicMock(),
        cast(IntentRouter, router),
        cast(RagAnswerer, rag),
        cast(SqlAnswerer, sql),
    )


async def test_dispatches_rag_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    rag, sql = _FakeRag(), _FakeSql()
    dispatcher = _dispatcher(_FakeRouter(_decision(Intent.RAG_DOCS)), rag, sql)

    events = [e async for e in dispatcher.stream("policy?", _principal())]

    assert rag.calls == 1
    assert rag.source_types is None
    assert rag.route == {
        "intent": "rag-docs",
        "route_source": "router",
        "router_confidence": 0.9,
        "router_prompt_version": "router.v1",
    }
    assert sql.calls == 0
    assert events[-1]["data"]["intent"] == "rag-docs"


async def test_dispatches_rag_code_with_source_types(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    rag, sql = _FakeRag(), _FakeSql()
    dispatcher = _dispatcher(_FakeRouter(_decision(Intent.RAG_CODE)), rag, sql)

    _ = [e async for e in dispatcher.stream("where is auth?", _principal())]

    assert rag.calls == 1
    assert rag.source_types == ("engineering", "runbook")


async def test_dispatches_text_to_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    rag, sql = _FakeRag(), _FakeSql()
    dispatcher = _dispatcher(_FakeRouter(_decision(Intent.TEXT_TO_SQL)), rag, sql)

    events = [e async for e in dispatcher.stream("how many projects?", _principal())]

    assert sql.calls == 1
    assert rag.calls == 0
    assert sql.route is not None
    assert sql.route["intent"] == "text-to-sql"
    assert events[0]["event"] == "sql"


async def test_out_of_scope_refuses_without_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    rag, sql = _FakeRag(), _FakeSql()
    dispatcher = _dispatcher(_FakeRouter(_decision(Intent.OUT_OF_SCOPE)), rag, sql)

    events = [e async for e in dispatcher.stream("weather?", _principal())]

    assert rag.calls == 0
    assert sql.calls == 0
    assert events[0]["data"]["text"] == REFUSAL
    assert events[-1]["data"]["answer"] == REFUSAL
    roles = [obj.role for obj in added if hasattr(obj, "role")]
    assert roles.count("user") == 1
    assert roles.count("assistant") == 1
    assistant = [obj for obj in added if getattr(obj, "role", None) == "assistant"][0]
    assert assistant.detail == {
        "route": {
            "intent": "out-of-scope",
            "route_source": "router",
            "router_confidence": 0.9,
            "router_prompt_version": "router.v1",
        }
    }


async def test_ambiguous_emits_clarify(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    clarify = ClarifyPrompt(
        kind="surface",
        question="Docs or live data?",
        options=[
            ClarifyOption(surface=Surface.RAG_DOCS, label="Company documents"),
            ClarifyOption(surface=Surface.TEXT_TO_SQL, label="Live org data"),
        ],
    )
    rag, sql = _FakeRag(), _FakeSql()
    dispatcher = _dispatcher(_FakeRouter(_decision(Intent.AMBIGUOUS, clarify=clarify)), rag, sql)

    events = [e async for e in dispatcher.stream("tell me about the team", _principal())]

    assert [e["event"] for e in events] == ["clarify", "token", "done"]
    assert rag.calls == 0
    assert sql.calls == 0
    assert events[0]["data"]["options"][0]["surface"] == "rag-docs"
    assert events[-1]["data"]["clarify"]["question"] == "Docs or live data?"
    assistant = [obj for obj in added if getattr(obj, "role", None) == "assistant"][0]
    assert assistant.detail is not None
    assert assistant.detail["route"]["intent"] == "ambiguous"


async def test_pinned_surface_skips_router(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    rag, sql = _FakeRag(), _FakeSql()
    router = _FakeRouter(_decision(Intent.OUT_OF_SCOPE))
    dispatcher = _dispatcher(router, rag, sql)

    events = [
        e
        async for e in dispatcher.stream(
            "how many projects?", _principal(), surface=Surface.TEXT_TO_SQL
        )
    ]

    assert router.calls == 0
    assert sql.calls == 1
    assert events[-1]["data"]["route_source"] == "pinned"


def test_pinned_decision_maps_surface_to_intent() -> None:
    assert pinned_decision(Surface.RAG_DOCS).intent == Intent.RAG_DOCS
    assert pinned_decision(Surface.RAG_CODE).intent == Intent.RAG_CODE
    assert pinned_decision(Surface.TEXT_TO_SQL).intent == Intent.TEXT_TO_SQL


async def test_screens_user_input_and_records_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    recorded: list[tuple[str, str, ScreenResult]] = []
    monkeypatch.setattr(
        dispatcher_mod,
        "record_screen",
        lambda result, *, where, subject: recorded.append((where, subject, result)),
    )
    rag, sql = _FakeRag(), _FakeSql()
    provider = FakeProvider(
        moderate_fn=lambda text: ModerationVerdict(flagged=True, categories=("pii",))
    )
    dispatcher = ChatDispatcher(
        MagicMock(),
        cast(IntentRouter, _FakeRouter(_decision(Intent.RAG_DOCS))),
        cast(RagAnswerer, rag),
        cast(SqlAnswerer, sql),
        moderation=(provider, "mistral-moderation-2603"),
    )

    _ = [e async for e in dispatcher.stream("policy?", _principal())]

    assert rag.calls == 1
    assert len(recorded) == 1
    where, subject, result = recorded[0]
    assert where == "prompt"
    assert subject == "alex"
    assert result.flagged is True


async def test_no_screen_without_moderation_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []
    _patch_session_factory(monkeypatch, added)
    recorded: list[object] = []
    monkeypatch.setattr(
        dispatcher_mod, "record_screen", lambda result, *, where, subject: recorded.append(result)
    )
    rag, sql = _FakeRag(), _FakeSql()
    dispatcher = _dispatcher(_FakeRouter(_decision(Intent.RAG_DOCS)), rag, sql)

    _ = [e async for e in dispatcher.stream("policy?", _principal())]

    assert recorded == []
