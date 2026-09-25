import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any, Protocol, TypeVar

from mistralai.client import Mistral
from mistralai.client.models import (
    AssistantMessage,
    DocumentURLChunk,
    File,
    JSONSchema,
    OCRResponse,
    ResponseFormat,
    SystemMessage,
    TextChunk,
    UserMessage,
)
from pydantic import BaseModel

from app.core.config import get_settings
from app.llm.resolver import ModelResolver, is_model_unavailable, is_transient_throttle

logger = logging.getLogger(__name__)

JsonSchema = dict[str, Any]

T = TypeVar("T")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatProvider(Protocol):
    def effective_model(self, model: str) -> str:
        """Return the model that served, or will serve, the given configured id."""
        ...

    async def chat(self, model: str, messages: Sequence[ChatMessage]) -> str: ...

    def stream(self, model: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]: ...

    async def chat_structured(
        self, model: str, messages: Sequence[ChatMessage], schema: JsonSchema
    ) -> str: ...


def _to_sdk_message(message: ChatMessage) -> AssistantMessage | SystemMessage | UserMessage:
    if message.role == "system":
        return SystemMessage(content=message.content)
    if message.role == "assistant":
        return AssistantMessage(content=message.content)
    return UserMessage(content=message.content)


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(chunk.text for chunk in content if isinstance(chunk, TextChunk))
    return ""


class MistralProvider:
    def __init__(self, client: Mistral, resolver: ModelResolver | None = None) -> None:
        self._client = client
        self._resolver = resolver

    @classmethod
    def from_api_key(cls, api_key: str, resolver: ModelResolver | None = None) -> "MistralProvider":
        return cls(Mistral(api_key=api_key), resolver)

    def effective_model(self, model: str) -> str:
        """Return the model currently serving a configured id.

        Callers record this rather than the configured id so cost and eval
        attribution reflect the model that actually answered.
        """
        if self._resolver is None:
            return model
        chain = self._resolver.chain(model)
        return chain[0] if chain else model

    async def _attempt(self, call: Callable[[], Awaitable[T]], model: str) -> T:
        """Call once, waiting out a real per-minute ceiling before giving up."""
        settings = get_settings()
        attempts = max(1, settings.llm_max_attempts)
        for attempt in range(attempts):
            try:
                return await call()
            except Exception as error:
                if attempt == attempts - 1 or not is_transient_throttle(error):
                    raise
                delay = min(
                    settings.llm_retry_max_delay_s,
                    settings.llm_retry_base_delay_s * (2**attempt),
                )
                logger.warning(
                    "throttled by %s, retrying %s in %.1fs (%d/%d)",
                    model,
                    model,
                    delay,
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")

    async def _with_fallback(self, model: str, call: Callable[[str], Awaitable[T]]) -> T:
        """Run a model call, stepping to a stand-in if the tier rejects the model."""
        if self._resolver is None:
            return await self._attempt(lambda: call(model), model)
        last: Exception | None = None
        for candidate in self._resolver.chain(model):
            async def attempt(bound: str = candidate) -> T:
                return await call(bound)

            try:
                return await self._attempt(attempt, candidate)
            except Exception as error:
                if not is_model_unavailable(error):
                    raise
                last = error
                self._resolver.demote(model, candidate)
        raise last if last is not None else RuntimeError(f"no available model for: {model}")

    async def _stream_with_fallback(
        self, model: str, call: Callable[[str], AsyncIterator[str]]
    ) -> AsyncIterator[str]:
        """Stream a call, stepping to a stand-in only before any output starts.

        Once a chunk has been handed to the caller the stream is committed, so a
        later failure is raised instead of being restarted on another model.
        """
        if self._resolver is None:
            async for chunk in call(model):
                yield chunk
            return
        last: Exception | None = None
        for candidate in self._resolver.chain(model):
            emitted = False
            settings = get_settings()
            attempts = max(1, settings.llm_max_attempts)
            for attempt in range(attempts):
                try:
                    async for chunk in call(candidate):
                        emitted = True
                        yield chunk
                    return
                except Exception as error:
                    retryable = not emitted and is_transient_throttle(error)
                    if not retryable:
                        if emitted or not is_model_unavailable(error):
                            raise
                        last = error
                        self._resolver.demote(model, candidate)
                        break
                    if attempt == attempts - 1:
                        raise
                    delay = min(
                        settings.llm_retry_max_delay_s,
                        settings.llm_retry_base_delay_s * (2**attempt),
                    )
                    logger.warning(
                        "throttled by %s, retrying in %.1fs (%d/%d)",
                        candidate,
                        delay,
                        attempt + 1,
                        attempts,
                    )
                    await asyncio.sleep(delay)
        raise last if last is not None else RuntimeError(f"no available model for: {model}")

    async def chat(self, model: str, messages: Sequence[ChatMessage]) -> str:
        async def call(candidate: str) -> str:
            sdk_messages = [_to_sdk_message(message) for message in messages]
            response = await self._client.chat.complete_async(
                model=candidate, messages=sdk_messages
            )
            message = response.choices[0].message
            return _extract_text(message.content if message else None)

        return await self._with_fallback(model, call)

    async def stream(self, model: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        async def call(candidate: str) -> AsyncIterator[str]:
            sdk_messages = [_to_sdk_message(message) for message in messages]
            stream = await self._client.chat.stream_async(model=candidate, messages=sdk_messages)
            async for event in stream:
                delta = event.data.choices[0].delta
                text = _extract_text(delta.content if delta else None)
                if text:
                    yield text

        async for chunk in self._stream_with_fallback(model, call):
            yield chunk

    async def chat_structured(
        self, model: str, messages: Sequence[ChatMessage], schema: JsonSchema
    ) -> str:
        async def call(candidate: str) -> str:
            sdk_messages = [_to_sdk_message(message) for message in messages]
            response = await self._client.chat.complete_async(
                model=candidate,
                messages=sdk_messages,
                response_format=ResponseFormat(
                    type="json_schema",
                    json_schema=JSONSchema(
                        name="structured_output", schema_definition=schema, strict=True
                    ),
                ),
            )
            message = response.choices[0].message
            return _extract_text(message.content if message else None)

        return await self._with_fallback(model, call)

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        async def call(candidate: str) -> list[list[float]]:
            response = await self._client.embeddings.create_async(
                model=candidate, inputs=list(texts)
            )
            ordered = sorted(response.data, key=lambda item: item.index or 0)
            embeddings: list[list[float]] = []
            for item in ordered:
                if item.embedding is not None:
                    embeddings.append(item.embedding)
            return embeddings

        return await self._with_fallback(model, call)

    async def ocr_pdf(self, model: str, file_name: str, content: bytes) -> OCRResponse:
        uploaded = await self._client.files.upload_async(
            file=File(file_name=file_name, content=content, content_type="application/pdf"),
            purpose="ocr",
        )
        signed = await self._client.files.get_signed_url_async(file_id=uploaded.id)

        async def call(candidate: str) -> OCRResponse:
            return await self._client.ocr.process_async(
                model=candidate,
                document=DocumentURLChunk(document_url=signed.url),
            )

        return await self._with_fallback(model, call)
