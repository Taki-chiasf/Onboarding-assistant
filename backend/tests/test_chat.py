import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.api import chat as chat_mod
from app.api.chat import get_chat_orchestrator
from app.core.config import get_settings
from app.main import create_app
from app.models import Conversation, Message


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.surfaces: list[str | None] = []

    async def stream(
        self,
        query: str,
        principal: object,
        conversation_id: object = None,
        *,
        surface: object = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self.surfaces.append(surface if isinstance(surface, str) else None)
        yield {"event": "sources", "data": {"conversation_id": "c1", "sources": []}}
        yield {"event": "token", "data": {"text": "I don't know"}}
        yield {"event": "done", "data": {"answer": "I don't know"}}


async def test_chat_streams_sse(app: FastAPI, client: AsyncClient) -> None:
    fake = _FakeOrchestrator()
    app.dependency_overrides[get_chat_orchestrator] = lambda: fake
    try:
        resp = await client.post("/api/chat", json={"query": "how much leave?"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: sources" in resp.text
    assert "event: token" in resp.text
    assert "event: done" in resp.text
    assert fake.surfaces == [None]


async def test_chat_forwards_pinned_surface(app: FastAPI, client: AsyncClient) -> None:
    fake = _FakeOrchestrator()
    app.dependency_overrides[get_chat_orchestrator] = lambda: fake
    try:
        resp = await client.post(
            "/api/chat", json={"query": "how much leave?", "surface": "rag-docs"}
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert fake.surfaces == ["rag-docs"]


class _FailingOrchestrator:
    async def stream(
        self,
        query: str,
        principal: object,
        conversation_id: object = None,
        *,
        surface: object = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "sources", "data": {"conversation_id": "c1", "sources": []}}
        raise RuntimeError("router exploded")


async def test_chat_emits_error_event_on_stream_failure(app: FastAPI, client: AsyncClient) -> None:
    app.dependency_overrides[get_chat_orchestrator] = lambda: _FailingOrchestrator()
    try:
        resp = await client.post("/api/chat", json={"query": "boom"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "Please try again" in resp.text


class _StubMessage:
    def __init__(self, detail: dict[str, Any] | None) -> None:
        self.id = uuid.uuid4()
        self.role = "assistant"
        self.content = "16 weeks"
        self.cost_usd = None
        self.model_version = "mistral-large-2512"
        self.prompt_version = "grounding.v1"
        self.trace_id = "trace-abc"
        self.detail = detail


class _StubFeedback:
    def __init__(self, message_id: uuid.UUID, rating: str, correction: str | None) -> None:
        self.message_id = message_id
        self.rating = rating
        self.correction = correction


class _StubScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _StubResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _StubScalars:
        return _StubScalars(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _StubSession:
    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)

    async def execute(self, statement: object) -> _StubResult:
        return _StubResult([self._results.pop(0)])

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


async def test_messages_endpoint_returns_evidence(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assistant evidence (sources, sql), the caller's feedback state, and the
    trace id must survive a reload so the panel and the rating render again
    from history."""
    app.state.engine = None
    detail = {"sources": [{"id": "chunk-1", "source_uri": "file:docs/a.md"}]}
    message = _StubMessage(detail)
    feedback = _StubFeedback(message.id, "down", "missing the policy citation")
    monkeypatch.setattr(
        chat_mod,
        "async_sessionmaker",
        lambda engine, expire_on_commit=False: (
            lambda: _StubSession([uuid.uuid4(), message, feedback])
        ),
    )

    resp = await client.get(f"/api/conversations/{uuid.uuid4()}/messages")

    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["detail"] == detail
    assert row["trace_id"] == "trace-abc"
    assert row["feedback"] == {
        "rating": "down",
        "correction": "missing the policy citation",
    }


async def test_messages_endpoint_hides_other_users_conversation(
    app: FastAPI, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conversation the caller does not own must not be readable."""
    app.state.engine = None
    monkeypatch.setattr(
        chat_mod,
        "async_sessionmaker",
        lambda engine, expire_on_commit=False: lambda: _StubSession([None]),
    )

    resp = await client.get(f"/api/conversations/{uuid.uuid4()}/messages")

    assert resp.status_code == 404


_LIVE_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture
async def live_engine() -> AsyncIterator[AsyncEngine]:
    if not _LIVE_DB_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    engine = create_async_engine(_LIVE_DB_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def live_stack(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    monkeypatch.setenv("MOCK_OIDC", "1")
    monkeypatch.setenv("DEV_PRINCIPAL_SUB", "convo-regression-user")
    monkeypatch.setenv("DEV_PRINCIPAL_EMAIL", "convo@example.com")
    monkeypatch.setenv("DEV_PRINCIPAL_DEPT", "Engineering")
    monkeypatch.setenv("DEV_PRINCIPAL_ROLE", "employee")
    monkeypatch.setenv("DATABASE_URL", _LIVE_DB_URL)
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    application = create_app()
    application.state.engine = live_engine
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield application, c
    get_settings.cache_clear()


async def test_conversation_list_and_history_use_orm_session(
    live_stack: tuple[FastAPI, AsyncClient],
) -> None:
    """Regression: these endpoints must run their ORM selects through an
    ORM session, not a Core connection, or row access fails with 500s."""
    application, client = live_stack
    factory = async_sessionmaker(application.state.engine, expire_on_commit=False)
    convo_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    answer_id = uuid.uuid4()
    detail = {"sources": [{"id": "chunk-1", "source_uri": "file:docs/a.md"}]}
    async with factory() as session:
        session.add(Conversation(id=convo_id, user_id="convo-regression-user", title="Regression"))
        session.add(Message(id=msg_id, conversation_id=convo_id, role="user", content="hello"))
        session.add(
            Message(
                id=answer_id,
                conversation_id=convo_id,
                role="assistant",
                content="hi",
                trace_id="trace-live",
                detail=detail,
            )
        )
        await session.commit()
    try:
        listed = await client.get("/api/conversations")
        assert listed.status_code == 200
        assert any(item["id"] == str(convo_id) for item in listed.json())

        history = await client.get(f"/api/conversations/{convo_id}/messages")
        assert history.status_code == 200
        assert [m["content"] for m in history.json()] == ["hello", "hi"]
        assert history.json()[1]["detail"] == detail
        assert history.json()[1]["trace_id"] == "trace-live"
        assert history.json()[1]["feedback"] is None
    finally:
        async with factory() as session:
            await session.execute(delete(Message).where(Message.id.in_([msg_id, answer_id])))
            await session.execute(delete(Conversation).where(Conversation.id == convo_id))
            await session.commit()
