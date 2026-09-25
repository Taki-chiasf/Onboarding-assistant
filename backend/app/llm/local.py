"""Local open-weights provider backed by an Ollama server.

Used in development so the intent router can run on a small local model
(Ministral 3 8B on an 8 GB GPU) without a hosted API key. Structured output is
requested through Ollama's JSON-schema ``format`` field; the caller still
re-validates the parsed verdict.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.llm.provider import ChatMessage, JsonSchema

DEFAULT_TIMEOUT = 120.0


def _to_wire(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _content(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


class LocalProvider:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _payload(
        self,
        model: str,
        messages: Sequence[ChatMessage],
        *,
        stream: bool,
        schema: JsonSchema | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": _to_wire(messages),
            "stream": stream,
            "options": {"temperature": 0},
        }
        if schema is not None:
            payload["format"] = schema
        return payload

    def effective_model(self, model: str) -> str:
        return model

    async def chat(self, model: str, messages: Sequence[ChatMessage]) -> str:
        response = await self._client.post(
            "/api/chat", json=self._payload(model, messages, stream=False)
        )
        response.raise_for_status()
        return _content(response.json())

    async def chat_structured(
        self, model: str, messages: Sequence[ChatMessage], schema: JsonSchema
    ) -> str:
        response = await self._client.post(
            "/api/chat", json=self._payload(model, messages, stream=False, schema=schema)
        )
        response.raise_for_status()
        return _content(response.json())

    async def stream(self, model: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        async with self._client.stream(
            "POST", "/api/chat", json=self._payload(model, messages, stream=True)
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                text = _content(json.loads(line))
                if text:
                    yield text
