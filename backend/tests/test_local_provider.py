import json

import httpx

from app.llm.local import LocalProvider
from app.llm.provider import ChatMessage


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="hello")]


def _provider(handler: httpx.MockTransport) -> LocalProvider:
    client = httpx.AsyncClient(base_url="http://ollama", transport=handler)
    return LocalProvider("http://ollama", client=client)


async def test_chat_returns_message_content() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hi there"}})

    provider = _provider(httpx.MockTransport(handler))
    text = await provider.chat("ministral-3:8b", _messages())

    assert text == "hi there"
    assert captured["model"] == "ministral-3:8b"
    assert captured["stream"] is False
    await provider.aclose()


async def test_chat_structured_passes_json_schema() -> None:
    captured: dict[str, object] = {}
    schema = {"type": "object", "properties": {"intent": {"type": "string"}}}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"intent": "rag-docs"}'}})

    provider = _provider(httpx.MockTransport(handler))
    text = await provider.chat_structured("ministral-3:8b", _messages(), schema)

    assert text == '{"intent": "rag-docs"}'
    assert captured["format"] == schema
    await provider.aclose()


async def test_stream_parses_ndjson_tokens() -> None:
    lines = "\n".join(
        [
            json.dumps({"message": {"content": "Hel"}}),
            json.dumps({"message": {"content": "lo"}}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=lines.encode())

    provider = _provider(httpx.MockTransport(handler))
    tokens: list[str] = []
    async for token in provider.stream("ministral-3:8b", _messages()):
        tokens.append(token)

    assert "".join(tokens) == "Hello"
    await provider.aclose()
