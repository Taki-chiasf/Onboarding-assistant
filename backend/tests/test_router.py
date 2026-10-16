from typing import Any, cast

from app.llm.fake import FakeProvider
from app.llm.provider import ChatMessage, ChatProvider
from app.router.router import IntentRouter
from app.router.schema import Intent


def _provider(payload: str) -> FakeProvider:
    return FakeProvider(structured={"fake-router": payload})


async def test_decide_parses_verdict_and_applies_guardrails() -> None:
    provider = _provider(
        '{"intent": "text-to-sql", "confidence": 0.92, "surfaces": ["text-to-sql"]}'
    )
    router = IntentRouter(provider, "fake-router")

    decision = await router.decide("How many projects are active?")

    assert decision.intent == Intent.TEXT_TO_SQL
    assert decision.source == "router"
    assert router.prompt_version == "router.v1"


async def test_decide_falls_back_to_docs_on_parse_failure() -> None:
    router = IntentRouter(_provider("not json at all"), "fake-router")

    decision = await router.decide("How many projects are active?")

    assert decision.intent == Intent.RAG_DOCS
    assert decision.source == "parse_fallback"


async def test_decide_falls_back_to_docs_on_invalid_verdict() -> None:
    router = IntentRouter(_provider('{"intent": "unknown", "confidence": 2.0}'), "fake-router")

    decision = await router.decide("anything")

    assert decision.intent == Intent.RAG_DOCS
    assert decision.source == "parse_fallback"


class _ExplodingProvider:
    async def chat_structured(
        self, model: str, messages: list[ChatMessage], schema: dict[str, Any]
    ) -> str:
        raise RuntimeError("model unreachable")

    def effective_model(self, model: str) -> str:
        return model


async def test_decide_falls_back_to_docs_when_router_model_unreachable() -> None:
    router = IntentRouter(cast(ChatProvider, _ExplodingProvider()), "fake-router")

    decision = await router.decide("Where is the onboarding checklist?")

    assert decision.intent == Intent.RAG_DOCS
    assert decision.source == "provider_fallback"


async def test_router_model_failure_still_honors_the_keyword_bridge() -> None:
    router = IntentRouter(cast(ChatProvider, _ExplodingProvider()), "fake-router")

    decision = await router.decide("How many projects are active?")

    assert decision.intent == Intent.TEXT_TO_SQL
    assert decision.source == "provider_fallback"
