"""Deterministic in-process provider for keyless runs.

Implements the same chat/stream/embed surface as the hosted provider so the
full answer pipeline can run without a real model in local development and CI.
Responses are canned per model (or computed by an injected callable), and
embeddings are derived from a hash of the input so they stay stable across
runs.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable, Mapping, Sequence

from app.llm.provider import ChatMessage, JsonSchema, ModerationVerdict

ChatFn = Callable[[str, Sequence[ChatMessage]], str]
ModerateFn = Callable[[str], ModerationVerdict]


class FakeProvider:
    def __init__(
        self,
        responses: Mapping[str, str] | None = None,
        *,
        chat_fn: ChatFn | None = None,
        structured: Mapping[str, str] | None = None,
        moderate_fn: ModerateFn | None = None,
        default: str = "",
    ) -> None:
        self._responses = dict(responses or {})
        self._structured = dict(structured or {})
        self._chat_fn = chat_fn
        self._moderate_fn = moderate_fn
        self._default = default

    def _chat(self, model: str, messages: Sequence[ChatMessage]) -> str:
        if self._chat_fn is not None:
            return self._chat_fn(model, messages)
        return self._responses.get(model, self._default)

    def _structured_chat(self, model: str, messages: Sequence[ChatMessage]) -> str:
        if model in self._structured:
            return self._structured[model]
        return self._chat(model, messages)

    def effective_model(self, model: str) -> str:
        return model

    async def chat(self, model: str, messages: Sequence[ChatMessage]) -> str:
        return self._chat(model, messages)

    async def chat_structured(
        self, model: str, messages: Sequence[ChatMessage], schema: JsonSchema
    ) -> str:
        return self._structured_chat(model, messages)

    async def stream(self, model: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        for token in self._tokenize(self._chat(model, messages)):
            yield token

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    async def moderate(self, model: str, texts: Sequence[str]) -> list[ModerationVerdict]:
        if self._moderate_fn is None:
            return [ModerationVerdict(flagged=False) for _ in texts]
        return [self._moderate_fn(text) for text in texts]

    @staticmethod
    def _tokenize(text: str, chunk: int = 4) -> list[str]:
        if not text:
            return []
        return [text[i : i + chunk] for i in range(0, len(text), chunk)]

    @staticmethod
    def _embed_one(text: str, dim: int = 1024) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector = [0.0] * dim
        for i in range(min(dim, len(digest))):
            vector[i] = (digest[i] / 255.0) * 2.0 - 1.0
        return vector
