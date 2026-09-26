from collections.abc import Sequence

from app.llm.fake import FakeProvider
from app.llm.provider import ChatMessage, ModerationVerdict


async def test_chat_returns_canned_response_by_model() -> None:
    provider = FakeProvider(responses={"a": "one", "b": "two"}, default="fallback")

    assert await provider.chat("a", []) == "one"
    assert await provider.chat("b", []) == "two"
    assert await provider.chat("missing", []) == "fallback"


async def test_chat_fn_takes_precedence() -> None:
    def chat_fn(model: str, messages: Sequence[ChatMessage]) -> str:
        return f"{model}:{len(messages)}"

    provider = FakeProvider(responses={"a": "canned"}, chat_fn=chat_fn)
    assert await provider.chat("a", [ChatMessage(role="user", content="hi")]) == "a:1"


async def test_stream_tokenizes_canned_response() -> None:
    provider = FakeProvider(responses={"m": "hello world"})
    tokens = [token async for token in provider.stream("m", [])]
    assert "".join(tokens) == "hello world"
    assert tokens == ["hell", "o wo", "rld"]


async def test_stream_empty_response_yields_nothing() -> None:
    provider = FakeProvider(responses={"m": ""})
    tokens = [token async for token in provider.stream("m", [])]
    assert tokens == []


async def test_embed_is_deterministic_and_distinct() -> None:
    provider = FakeProvider()
    first = await provider.embed("embed", ["alpha", "beta"])
    second = await provider.embed("embed", ["alpha", "beta"])

    assert len(first) == 2
    assert len(first[0]) == 1024
    assert first == second
    assert first[0] != first[1]


async def test_moderate_defaults_to_not_flagged() -> None:
    verdicts = await FakeProvider().moderate("m", ["a", "b"])
    assert len(verdicts) == 2
    assert all(not verdict.flagged for verdict in verdicts)


async def test_moderate_fn_marks_each_text() -> None:
    provider = FakeProvider(
        moderate_fn=lambda text: ModerationVerdict(
            flagged=text == "bad", categories=("pii",) if text == "bad" else ()
        )
    )
    verdicts = await provider.moderate("m", ["bad", "good"])
    assert verdicts[0].flagged
    assert verdicts[0].categories == ("pii",)
    assert not verdicts[1].flagged
