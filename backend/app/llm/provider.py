from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from mistralai.client import Mistral
from mistralai.client.models import (
    AssistantMessage,
    DocumentURLChunk,
    File,
    OCRResponse,
    SystemMessage,
    TextChunk,
    UserMessage,
)
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatProvider(Protocol):
    async def chat(self, model: str, messages: Sequence[ChatMessage]) -> str: ...

    def stream(self, model: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]: ...


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
    def __init__(self, client: Mistral) -> None:
        self._client = client

    @classmethod
    def from_api_key(cls, api_key: str) -> "MistralProvider":
        return cls(Mistral(api_key=api_key))

    async def chat(self, model: str, messages: Sequence[ChatMessage]) -> str:
        sdk_messages = [_to_sdk_message(message) for message in messages]
        response = await self._client.chat.complete_async(model=model, messages=sdk_messages)
        message = response.choices[0].message
        return _extract_text(message.content if message else None)

    async def stream(self, model: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        sdk_messages = [_to_sdk_message(message) for message in messages]
        stream = await self._client.chat.stream_async(model=model, messages=sdk_messages)
        async for event in stream:
            delta = event.data.choices[0].delta
            text = _extract_text(delta.content if delta else None)
            if text:
                yield text

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        response = await self._client.embeddings.create_async(model=model, inputs=list(texts))
        ordered = sorted(response.data, key=lambda item: item.index or 0)
        embeddings: list[list[float]] = []
        for item in ordered:
            if item.embedding is not None:
                embeddings.append(item.embedding)
        return embeddings

    async def ocr_pdf(self, model: str, file_name: str, content: bytes) -> OCRResponse:
        uploaded = await self._client.files.upload_async(
            file=File(file_name=file_name, content=content, content_type="application/pdf"),
            purpose="ocr",
        )
        signed = await self._client.files.get_signed_url_async(file_id=uploaded.id)
        return await self._client.ocr.process_async(
            model=model,
            document=DocumentURLChunk(document_url=signed.url),
        )
