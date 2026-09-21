from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from mistralai.client import Mistral
from mistralai.client.models import OCRResponse, TextChunk

from app.llm import ChatMessage, MistralProvider, load_models
from app.llm.provider import _extract_text, _to_sdk_message


def test_models_pin_dated_ids() -> None:
    config = load_models()
    for model_id in config.models.values():
        assert not model_id.endswith("-latest")
    assert config.models["grounding"] == "mistral-large-2512"
    assert config.models["router"] == "mistral-small-2603"
    assert config.models["ocr"] == "mistral-ocr-4-0"
    assert config.models["rag_code"] == "codestral-2508"


def test_extract_text_from_string() -> None:
    assert _extract_text("hello") == "hello"


def test_extract_text_from_chunks() -> None:
    assert _extract_text([TextChunk(text="a"), TextChunk(text="b")]) == "ab"


def test_extract_text_from_none() -> None:
    assert _extract_text(None) == ""


def test_to_sdk_message_maps_roles() -> None:
    system = _to_sdk_message(ChatMessage(role="system", content="s"))
    user = _to_sdk_message(ChatMessage(role="user", content="u"))
    assistant = _to_sdk_message(ChatMessage(role="assistant", content="a"))
    assert _extract_text(system.content) == "s"
    assert _extract_text(user.content) == "u"
    assert _extract_text(assistant.content) == "a"


def test_from_api_key_constructs_client() -> None:
    provider = MistralProvider.from_api_key("test-key")
    assert provider is not None


async def test_chat_returns_text() -> None:
    client = MagicMock()
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))])
    client.chat.complete_async = AsyncMock(return_value=response)

    provider = MistralProvider(cast(Mistral, client))
    result = await provider.chat("model", [ChatMessage(role="user", content="hi")])

    assert result == "answer"
    client.chat.complete_async.assert_awaited_once()


async def test_stream_yields_deltas() -> None:
    client = MagicMock()
    event1 = SimpleNamespace(
        data=SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hel"))])
    )
    event2 = SimpleNamespace(
        data=SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"))])
    )

    async def fake_stream() -> AsyncIterator[object]:
        yield event1
        yield event2

    client.chat.stream_async = AsyncMock(return_value=fake_stream())

    provider = MistralProvider(cast(Mistral, client))
    chunks = [
        chunk async for chunk in provider.stream("model", [ChatMessage(role="user", content="hi")])
    ]

    assert chunks == ["hel", "lo"]


async def test_embed_orders_results_by_index() -> None:
    client = MagicMock()
    response = SimpleNamespace(
        data=[
            SimpleNamespace(index=1, embedding=[1.0, 2.0]),
            SimpleNamespace(index=0, embedding=[0.1, 0.2]),
        ]
    )
    client.embeddings.create_async = AsyncMock(return_value=response)

    provider = MistralProvider(cast(Mistral, client))
    result = await provider.embed("mistral-embed", ["a", "b"])

    assert result == [[0.1, 0.2], [1.0, 2.0]]
    client.embeddings.create_async.assert_awaited_once()


async def test_embed_skips_missing_embeddings() -> None:
    client = MagicMock()
    response = SimpleNamespace(
        data=[
            SimpleNamespace(index=0, embedding=None),
            SimpleNamespace(index=1, embedding=[3.0]),
        ]
    )
    client.embeddings.create_async = AsyncMock(return_value=response)

    provider = MistralProvider(cast(Mistral, client))
    result = await provider.embed("mistral-embed", ["a", "b"])

    assert result == [[3.0]]


async def test_ocr_pdf_uploads_and_processes() -> None:
    client = MagicMock()
    ocr_result = cast(OCRResponse, SimpleNamespace(pages=[]))
    client.files.upload_async = AsyncMock(return_value=SimpleNamespace(id="file-1"))
    client.files.get_signed_url_async = AsyncMock(
        return_value=SimpleNamespace(url="https://signed.example")
    )
    client.ocr.process_async = AsyncMock(return_value=ocr_result)

    provider = MistralProvider(cast(Mistral, client))
    result = await provider.ocr_pdf("mistral-ocr-4-0", "doc.pdf", b"%PDF")

    assert result is ocr_result
    upload_call = client.files.upload_async.await_args
    assert upload_call.kwargs["purpose"] == "ocr"
    process_call = client.ocr.process_async.await_args
    assert process_call.kwargs["model"] == "mistral-ocr-4-0"
    assert process_call.kwargs["document"].document_url == "https://signed.example"
