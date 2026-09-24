"""Intent router service.

One structured-output call classifies a question into the five intents, then the
deterministic guardrails turn that verdict into a final routing decision. A
verdict that fails to parse is never guessed at: it falls back to document
retrieval, which is the safe default surface.
"""

from __future__ import annotations

import logging

from app.llm.provider import ChatMessage, ChatProvider
from app.prompts.loader import load_prompt, prompt_version
from app.router.guardrails import resolve_verdict
from app.router.schema import Intent, RouteDecision, RouterVerdict, Surface, verdict_json_schema

logger = logging.getLogger(__name__)

ROUTER_PROMPT = "router"


class IntentRouter:
    def __init__(self, provider: ChatProvider, model: str) -> None:
        self._provider = provider
        self._model = model
        self.prompt_version = prompt_version(ROUTER_PROMPT)

    async def decide(self, query: str) -> RouteDecision:
        prompt = load_prompt(ROUTER_PROMPT)
        messages = [
            ChatMessage(role="system", content=prompt.system),
            ChatMessage(role="user", content=prompt.user.format(query=query)),
        ]
        try:
            raw = await self._provider.chat_structured(self._model, messages, verdict_json_schema())
            verdict = RouterVerdict.model_validate_json(raw)
        except ValueError:
            logger.warning("router verdict failed to parse; falling back to document retrieval")
            return _parse_fallback()
        return resolve_verdict(query, verdict)


def _parse_fallback() -> RouteDecision:
    return RouteDecision(
        intent=Intent.RAG_DOCS,
        confidence=0.0,
        surfaces=[Surface.RAG_DOCS],
        entities=[],
        rationale="router output could not be parsed",
        source="parse_fallback",
    )
