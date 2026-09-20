from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from mistralai.client import Mistral
from mistralai.client.models import AssistantMessage, SystemMessage, TextChunk, UserMessage
from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatProvider(Protocol):
    def chat(self, model: str, messages: Sequence[ChatMessage]) -> str: ...

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
