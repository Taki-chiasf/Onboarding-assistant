"""Top-level chat dispatch.

Runs the intent router once (unless the client pinned a surface), then forwards
to the document or SQL answer path unchanged. Refusals and clarifications are
resolved here without a grounded model call, and persisted so they survive a
conversation reload.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth.principal import Principal
from app.core.moderation import record_screen, screen
from app.core.otel import current_trace_id
from app.llm.provider import ChatProvider
from app.models import Conversation, Message
from app.rag.answer import RagAnswerer
from app.router.router import IntentRouter
from app.router.schema import (
    ClarifyPrompt,
    Intent,
    RouteDecision,
    Surface,
)
from app.text_to_sql.answer import SqlAnswerer

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

REFUSAL = (
    "I can only help with onboarding and company questions. "
    "Try asking about policies, teams, projects, assets, or where to find a document."
)

RAG_CODE_SOURCE_TYPES: tuple[str, ...] = ("code",)
RAG_CODE_MODEL_ROLE = "rag_code"

SURFACE_INTENT: dict[Surface, Intent] = {
    Surface.RAG_DOCS: Intent.RAG_DOCS,
    Surface.RAG_CODE: Intent.RAG_CODE,
    Surface.TEXT_TO_SQL: Intent.TEXT_TO_SQL,
}


def pinned_decision(surface: Surface) -> RouteDecision:
    intent = SURFACE_INTENT[surface]
    return RouteDecision(
        intent=intent,
        confidence=1.0,
        surfaces=[surface],
        entities=[],
        rationale="surface chosen by the user",
        source="pinned",
    )


class ChatDispatcher:
    def __init__(
        self,
        engine: AsyncEngine,
        router: IntentRouter,
        rag: RagAnswerer,
        sql: SqlAnswerer,
        *,
        moderation: tuple[ChatProvider, str] | None = None,
    ) -> None:
        self._router = router
        self._rag = rag
        self._sql = sql
        self._moderation = moderation
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def stream(
        self,
        query: str,
        principal: Principal,
        conversation_id: uuid.UUID | None = None,
        *,
        surface: Surface | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        started = perf_counter()

        with tracer.start_as_current_span("dispatch") as span:
            trace_id = current_trace_id() or uuid.uuid4().hex
            span.set_attribute("user.dept", principal.dept)
            span.set_attribute("user.role", principal.role)

            if self._moderation is not None:
                provider, moderation_model = self._moderation
                result = await screen(provider, moderation_model, query)
                record_screen(result, where="prompt", subject=principal.sub)

            decision = pinned_decision(surface) if surface else await self._router.decide(query)
            span.set_attribute("route.intent", decision.intent.value)
            span.set_attribute("route.confidence", decision.confidence)
            span.set_attribute("route.source", decision.source)
            span.set_attribute("route.rationale", decision.rationale)

            if decision.intent == Intent.OUT_OF_SCOPE:
                async for event in self._resolve_locally(
                    query, principal, conversation_id, trace_id, decision, started
                ):
                    yield event
                return

            if decision.intent == Intent.AMBIGUOUS:
                async for event in self._clarify(
                    query, principal, conversation_id, trace_id, decision, started
                ):
                    yield event
                return

            async for event in self._route(
                decision, query, principal, conversation_id, self._route_metadata(decision)
            ):
                if event["event"] == "done" and isinstance(event["data"], dict):
                    event["data"].update(self._route_metadata(decision))
                yield event

    def _route(
        self,
        decision: RouteDecision,
        query: str,
        principal: Principal,
        conversation_id: uuid.UUID | None,
        route: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        if decision.intent == Intent.TEXT_TO_SQL:
            return self._sql.stream(query, principal, conversation_id, route=route)
        if decision.intent == Intent.RAG_CODE:
            return self._rag.stream(
                query,
                principal,
                conversation_id,
                source_types=RAG_CODE_SOURCE_TYPES,
                model_role=RAG_CODE_MODEL_ROLE,
                route=route,
            )
        return self._rag.stream(query, principal, conversation_id, route=route)

    def _route_metadata(self, decision: RouteDecision) -> dict[str, Any]:
        return {
            "intent": decision.intent.value,
            "route_source": decision.source,
            "router_confidence": decision.confidence,
            "router_prompt_version": self._router.prompt_version,
        }

    async def _resolve_locally(
        self,
        query: str,
        principal: Principal,
        conversation_id: uuid.UUID | None,
        trace_id: str,
        decision: RouteDecision,
        started: float,
    ) -> AsyncIterator[dict[str, Any]]:
        conv_id = await self._record_user_message(query, principal, trace_id, conversation_id)
        message_id = await self._record_answer(
            conv_id, REFUSAL, detail={"route": self._route_metadata(decision)}
        )
        yield {"event": "token", "data": {"text": REFUSAL}}
        done = {
            "conversation_id": str(conv_id),
            "message_id": str(message_id),
            "answer": REFUSAL,
            "trace_id": trace_id,
            "latency_ms": int((perf_counter() - started) * 1000),
            **self._route_metadata(decision),
        }
        yield {"event": "done", "data": done}

    async def _clarify(
        self,
        query: str,
        principal: Principal,
        conversation_id: uuid.UUID | None,
        trace_id: str,
        decision: RouteDecision,
        started: float,
    ) -> AsyncIterator[dict[str, Any]]:
        prompt = decision.clarify
        if prompt is None:
            prompt = ClarifyPrompt(
                kind="surface", question="Which surface do you mean?", options=[]
            )
        conv_id = await self._record_user_message(query, principal, trace_id, conversation_id)
        message_id = await self._record_answer(
            conv_id, prompt.question, detail={"route": self._route_metadata(decision)}
        )
        clarify = {
            "conversation_id": str(conv_id),
            "kind": prompt.kind,
            "question": prompt.question,
            "options": [
                {"surface": option.surface.value, "label": option.label}
                for option in prompt.options
            ],
        }
        yield {"event": "clarify", "data": clarify}
        yield {"event": "token", "data": {"text": prompt.question}}
        done = {
            "conversation_id": str(conv_id),
            "message_id": str(message_id),
            "answer": prompt.question,
            "clarify": clarify,
            "trace_id": trace_id,
            "latency_ms": int((perf_counter() - started) * 1000),
            **self._route_metadata(decision),
        }
        yield {"event": "done", "data": done}

    async def _record_user_message(
        self,
        query: str,
        principal: Principal,
        trace_id: str,
        conversation_id: uuid.UUID | None,
    ) -> uuid.UUID:
        conv_id = conversation_id or uuid.uuid4()
        async with self._session_factory() as session:
            if conversation_id is None:
                session.add(Conversation(id=conv_id, user_id=principal.sub, title=query[:255]))
            session.add(
                Message(
                    id=uuid.uuid4(),
                    conversation_id=conv_id,
                    role="user",
                    content=query,
                    trace_id=trace_id,
                )
            )
            await session.commit()
        return conv_id

    async def _record_answer(
        self,
        conversation_id: uuid.UUID,
        answer: str,
        detail: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        message_id = uuid.uuid4()
        async with self._session_factory() as session:
            session.add(
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                    detail=detail,
                )
            )
            await session.commit()
        return message_id
