from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from app.api.chat import get_chat_orchestrator


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
