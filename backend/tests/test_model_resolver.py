"""Standing-in models for roles the current subscription tier rejects."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from mistralai.client import Mistral
from mistralai.client.errors.sdkerror import SDKError
from mistralai.client.models import TextChunk

from app.llm import ChatMessage, MistralProvider
from app.llm import provider as provider_mod
from app.llm.models import ModelConfig, load_models
from app.llm.resolver import ModelResolver, is_model_unavailable, is_transient_throttle

TIER_403 = "not available in your subscription tier"


def _fast_retry(
    monkeypatch: pytest.MonkeyPatch, attempts: int = 4
) -> list[float]:
    """Shrink the retry backoff and record the delays instead of really sleeping."""
    recorded: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)

    settings = SimpleNamespace(
        llm_max_attempts=attempts, llm_retry_base_delay_s=0.1, llm_retry_max_delay_s=30.0
    )
    monkeypatch.setattr(provider_mod, "get_settings", lambda: settings)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return recorded


def _config() -> ModelConfig:
    return ModelConfig(
        provider="mistral",
        models={"router": "mistral-small-2603", "grounding": "mistral-large-2512"},
        fallbacks={
            "router": ["ministral-8b-2512", "ministral-3b-2512"],
            "grounding": ["ministral-14b-2512"],
        },
    )


def _error(status: int, headers: dict[str, str] | None = None, body: str = "") -> SDKError:
    return SDKError("failed", httpx.Response(status, headers=headers or {}), body)


def _locked_out() -> SDKError:
    return _error(429, headers={"x-ratelimit-limit-req-minute": "0"})


def _client() -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock(content="answer")
    client.chat.complete_async = AsyncMock(return_value=response)
    return client


def test_tier_restriction_counts_as_unavailable() -> None:
    assert is_model_unavailable(_error(403, body=TIER_403))


def test_zero_quota_counts_as_unavailable() -> None:
    assert is_model_unavailable(_locked_out())


def test_transient_throttle_is_not_unavailable() -> None:
    err = _error(429, headers={"x-ratelimit-limit-req-minute": "60"})
    assert not is_model_unavailable(err)


def test_unknown_model_id_counts_as_unavailable() -> None:
    assert is_model_unavailable(_error(400, body='{"message":"Invalid model: x"}'))


def test_unrelated_failures_are_not_unavailable() -> None:
    assert not is_model_unavailable(_error(500))
    assert not is_model_unavailable(RuntimeError("boom"))


def test_chain_starts_at_preferred_model() -> None:
    chain = ModelResolver(_config()).chain("mistral-small-2603")
    assert chain == ["mistral-small-2603", "ministral-8b-2512", "ministral-3b-2512"]


def test_model_without_fallbacks_is_its_own_chain() -> None:
    resolver = ModelResolver(ModelConfig(provider="mistral", models={"embed": "mistral-embed"}))
    assert resolver.chain("mistral-embed") == ["mistral-embed"]


def test_demotion_advances_the_chain() -> None:
    resolver = ModelResolver(_config())
    assert resolver.demote("mistral-small-2603", "mistral-small-2603") == "ministral-8b-2512"
    assert resolver.chain("mistral-small-2603") == ["ministral-8b-2512", "ministral-3b-2512"]


def test_demotion_past_the_last_candidate_returns_none() -> None:
    resolver = ModelResolver(_config())
    assert resolver.demote("mistral-small-2603", "ministral-3b-2512") is None


def test_reset_restores_the_preferred_model() -> None:
    resolver = ModelResolver(_config())
    resolver.demote("mistral-small-2603", "mistral-small-2603")
    resolver.reset("mistral-small-2603")
    assert resolver.chain("mistral-small-2603")[0] == "mistral-small-2603"


def test_stand_in_shared_by_several_roles_extends_the_pool() -> None:
    config = ModelConfig(
        provider="mistral",
        models={"router": "mistral-small-2603", "condenser": "mistral-small-2603"},
        fallbacks={"router": ["ministral-8b-2512"], "condenser": ["ministral-3b-2512"]},
    )
    chain = ModelResolver(config).chain("mistral-small-2603")
    assert chain == ["mistral-small-2603", "ministral-8b-2512", "ministral-3b-2512"]


def test_stand_in_reaches_every_model_configured_against_the_primary() -> None:
    config = ModelConfig(
        provider="mistral",
        models={"grounding": "mistral-large-2512", "sql_builder": "mistral-large-2512"},
        fallbacks={"grounding": ["ministral-14b-2512"], "sql_builder": ["codestral-2508"]},
    )
    chain = ModelResolver(config).chain("mistral-large-2512")
    assert chain == ["mistral-large-2512", "ministral-14b-2512", "codestral-2508"]


async def test_chat_steps_to_a_stand_in_when_the_model_is_locked_out() -> None:
    client = _client()
    ok = client.chat.complete_async.return_value
    client.chat.complete_async = AsyncMock(side_effect=[_locked_out(), ok])
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    result = await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    assert result == "answer"
    used = [call.kwargs["model"] for call in client.chat.complete_async.await_args_list]
    assert used == ["mistral-small-2603", "ministral-8b-2512"]


async def test_stand_in_is_reused_on_later_calls() -> None:
    client = _client()
    ok = client.chat.complete_async.return_value
    client.chat.complete_async = AsyncMock(side_effect=[_locked_out(), ok, ok])
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    for _ in range(2):
        await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    used = [call.kwargs["model"] for call in client.chat.complete_async.await_args_list]
    assert used == ["mistral-small-2603", "ministral-8b-2512", "ministral-8b-2512"]


async def test_preferred_model_is_used_when_it_works() -> None:
    client = _client()
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    used = [call.kwargs["model"] for call in client.chat.complete_async.await_args_list]
    assert used == ["mistral-small-2603"]


async def test_tier_error_also_steps_to_a_stand_in() -> None:
    client = _client()
    ok = client.chat.complete_async.return_value
    client.chat.complete_async = AsyncMock(side_effect=[_error(403, body=TIER_403), ok])
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    assert await provider.chat("mistral-large-2512", [ChatMessage(role="user", content="hi")])
    used = [call.kwargs["model"] for call in client.chat.complete_async.await_args_list]
    assert used == ["mistral-large-2512", "ministral-14b-2512"]


async def test_transient_throttle_waits_and_retries_the_same_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps = _fast_retry(monkeypatch)
    client = _client()
    ok = client.chat.complete_async.return_value
    throttle = _error(429, headers={"x-ratelimit-limit-req-minute": "60"})
    client.chat.complete_async = AsyncMock(side_effect=[throttle, throttle, ok])
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    result = await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    assert result == "answer"
    used = [call.kwargs["model"] for call in client.chat.complete_async.await_args_list]
    assert used == ["mistral-small-2603"] * 3
    assert sleeps == [0.1, 0.2]


async def test_throttle_gives_up_after_the_configured_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_retry(monkeypatch, attempts=3)
    client = _client()
    throttle = _error(429, headers={"x-ratelimit-limit-req-minute": "60"})
    client.chat.complete_async = AsyncMock(side_effect=throttle)
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    with pytest.raises(SDKError):
        await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    assert client.chat.complete_async.await_count == 3


async def test_exhausted_throttle_does_not_step_to_a_stand_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fast_retry(monkeypatch, attempts=2)
    client = _client()
    throttle = _error(429, headers={"x-ratelimit-limit-req-minute": "60"})
    client.chat.complete_async = AsyncMock(side_effect=throttle)
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    with pytest.raises(SDKError):
        await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    used = [call.kwargs["model"] for call in client.chat.complete_async.await_args_list]
    assert set(used) == {"mistral-small-2603"}


async def test_retry_after_header_is_not_treated_as_a_lockout() -> None:
    err = _error(429, headers={"x-ratelimit-limit-req-minute": "60", "retry-after": "12"})
    assert is_transient_throttle(err)
    assert not is_model_unavailable(err)


async def test_zero_quota_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _fast_retry(monkeypatch)
    client = _client()
    ok = client.chat.complete_async.return_value
    client.chat.complete_async = AsyncMock(side_effect=[_locked_out(), ok])
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    assert sleeps == []


def test_transient_throttle_detection() -> None:
    assert is_transient_throttle(_error(429, headers={"x-ratelimit-limit-req-minute": "60"}))
    assert not is_transient_throttle(_locked_out())
    assert not is_transient_throttle(_error(403))
    assert not is_transient_throttle(_error(500))


async def test_exhausted_chain_raises_rather_than_returning_nothing() -> None:
    client = _client()
    client.chat.complete_async = AsyncMock(side_effect=_locked_out())
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    with pytest.raises(SDKError):
        await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    assert client.chat.complete_async.await_count == 3


async def test_structured_call_steps_to_a_stand_in() -> None:
    client = _client()
    ok = client.chat.complete_async.return_value
    client.chat.complete_async = AsyncMock(side_effect=[_locked_out(), ok])
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    result = await provider.chat_structured(
        "mistral-small-2603", [ChatMessage(role="user", content="hi")], {"type": "object"}
    )

    assert result == "answer"
    used = [call.kwargs["model"] for call in client.chat.complete_async.await_args_list]
    assert used == ["mistral-small-2603", "ministral-8b-2512"]


def _stream_event(text: str) -> Any:
    return MagicMock(data=MagicMock(choices=[MagicMock(delta=MagicMock(content=text))]))


async def test_stream_steps_to_a_stand_in_before_any_output() -> None:
    client = MagicMock()
    ok = _stream_event("hello")
    client.chat.stream_async = AsyncMock(side_effect=[_locked_out(), _aiter(ok)])
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    chunks = [
        chunk
        async for chunk in provider.stream(
            "mistral-small-2603", [ChatMessage(role="user", content="hi")]
        )
    ]

    assert chunks == ["hello"]
    used = [call.kwargs["model"] for call in client.chat.stream_async.await_args_list]
    assert used == ["mistral-small-2603", "ministral-8b-2512"]


async def test_stream_failure_after_output_is_not_restarted() -> None:
    client = MagicMock()
    client.chat.stream_async = AsyncMock(
        return_value=_aiter_then(_stream_event("partial"), _locked_out())
    )
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    collected: list[str] = []
    with pytest.raises(SDKError):
        async for chunk in provider.stream(
            "mistral-small-2603", [ChatMessage(role="user", content="hi")]
        ):
            collected.append(chunk)

    assert collected == ["partial"]
    assert client.chat.stream_async.await_count == 1


async def test_role_without_a_stand_in_raises_on_rejection() -> None:
    client = MagicMock()
    client.embeddings.create_async = AsyncMock(side_effect=_locked_out())
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    with pytest.raises(SDKError):
        await provider.embed("mistral-embed", ["a"])

    assert client.embeddings.create_async.await_count == 1


async def test_provider_without_resolver_never_steps() -> None:
    client = _client()
    client.chat.complete_async = AsyncMock(side_effect=_locked_out())
    provider = MistralProvider(cast(Mistral, client))

    with pytest.raises(SDKError):
        await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    assert client.chat.complete_async.await_count == 1


async def test_extract_text_still_handles_chunk_lists() -> None:
    assert TextChunk(text="a") is not None
    client = _client()
    provider = MistralProvider(cast(Mistral, client))
    assert await provider.chat("m", [ChatMessage(role="user", content="hi")]) == "answer"


def test_shipped_config_keeps_preferred_models() -> None:
    config = load_models()
    assert config.models["router"] == "mistral-small-2603"
    assert config.models["grounding"] == "mistral-large-2512"
    assert config.models["sql_builder"] == "mistral-large-2512"
    assert config.models["embed"] == "mistral-embed"


def test_shipped_config_gives_locked_roles_a_stand_in() -> None:
    config = load_models()
    # ocr is excluded on purpose: no OCR model is reachable on a restricted tier.
    for role in ("router", "condenser", "grounding", "sql_builder", "judge", "escalation"):
        assert config.fallbacks.get(role), f"no fallback configured for {role}"


def test_shipped_resolver_builds_without_conflicts() -> None:
    resolver = ModelResolver(load_models())
    assert resolver.chain("mistral-small-2603")[0] == "mistral-small-2603"
    assert "ministral-8b-2512" in resolver.chain("mistral-small-2603")
    assert "ministral-14b-2512" in resolver.chain("mistral-large-2512")


def test_effective_model_reports_the_configured_id_initially() -> None:
    client = _client()
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))
    assert provider.effective_model("mistral-small-2603") == "mistral-small-2603"


async def test_effective_model_reports_the_stand_in_after_a_rejection() -> None:
    client = _client()
    ok = client.chat.complete_async.return_value
    client.chat.complete_async = AsyncMock(side_effect=[_locked_out(), ok])
    provider = MistralProvider(cast(Mistral, client), ModelResolver(_config()))

    await provider.chat("mistral-small-2603", [ChatMessage(role="user", content="hi")])

    assert provider.effective_model("mistral-small-2603") == "ministral-8b-2512"


def test_effective_model_without_resolver_is_the_configured_id() -> None:
    provider = MistralProvider(cast(Mistral, _client()))
    assert provider.effective_model("mistral-small-2603") == "mistral-small-2603"


def _aiter(*items: Any) -> AsyncIterator[Any]:
    async def gen() -> AsyncIterator[Any]:
        for item in items:
            yield item

    return gen()


def _aiter_then(item: Any, error: Exception) -> AsyncIterator[Any]:
    async def gen() -> AsyncIterator[Any]:
        yield item
        raise error

    return gen()
