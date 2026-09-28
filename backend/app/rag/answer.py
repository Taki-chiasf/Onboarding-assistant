"""Document answer path: retrieve, ground, stream, and record.

Streams ``sources`` once, then ``token`` per model token, then ``done`` with the
final answer and provenance. The streaming shape is shared with the SQL path so
the dispatcher can forward either one to the client unchanged. A ``source_types``
restriction narrows retrieval to a subset of the corpus (used for
code-oriented questions).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict
from decimal import Decimal
from time import perf_counter
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth.principal import Principal
from app.core.fallback import is_dont_know
from app.core.otel import current_trace_id
from app.core.redact import redact_pii
from app.history import record_user_message, seal_message
from app.llm.models import ModelConfig
from app.llm.pricing import compute_cost, estimate_tokens
from app.llm.provider import ChatProvider
from app.models import Message
from app.prompts.loader import prompt_version
from app.rag.cost import record_cost
from app.rag.grounding import CITE_OR_DIE, Source, build_grounding_messages, to_sources
from app.rag.retrieval import Retriever

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

GROUNDING_PROMPT = "grounding"


class RagAnswerer:
    def __init__(
        self,
        engine: AsyncEngine,
        provider: ChatProvider,
        models: ModelConfig,
        retriever: Retriever,
    ) -> None:
        self._engine = engine
        self._provider = provider
        self._models = models
        self._retriever = retriever
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def stream(
        self,
        query: str,
        principal: Principal,
        conversation_id: uuid.UUID | None = None,
        *,
        source_types: Sequence[str] | None = None,
        model_role: str = "grounding",
        route: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        started = perf_counter()
        logger.info(
            "chat query from %s: %s", principal.email, redact_pii(query, allow=[principal.email])
        )

        with tracer.start_as_current_span("chat") as span:
            trace_id = current_trace_id() or uuid.uuid4().hex
            span.set_attribute("user.dept", principal.dept)
            span.set_attribute("user.role", principal.role)
            span.set_attribute("answer.model_role", model_role)
            if source_types is not None:
                span.set_attribute("retrieve.source_types", list(source_types))

            conv_id = await self._record_user_message(query, principal, trace_id, conversation_id)

            with tracer.start_as_current_span("retrieve"):
                chunks = await self._retriever.retrieve(
                    query, dept=principal.dept, role=principal.role, source_types=source_types
                )

            sources = to_sources(chunks)
            yield {
                "event": "sources",
                "data": {
                    "conversation_id": str(conv_id),
                    "sources": [asdict(s) for s in sources],
                },
            }

            answer_model = self._models.models[model_role]

            if not chunks:
                answer = CITE_OR_DIE
                version = prompt_version(GROUNDING_PROMPT)
                tokens_in = 0
                yield {"event": "token", "data": {"text": answer}}
            else:
                messages, version = build_grounding_messages(query, chunks)
                tokens_in = estimate_tokens("".join(m.content for m in messages))
                parts: list[str] = []
                with tracer.start_as_current_span("ground"):
                    async for token in self._provider.stream(answer_model, messages):
                        parts.append(token)
                        yield {"event": "token", "data": {"text": token}}
                answer = "".join(parts)

            latency_ms = int((perf_counter() - started) * 1000)
            tokens_out = estimate_tokens(answer)
            served_model = self._provider.effective_model(answer_model)
            cost: Decimal = (
                compute_cost(served_model, tokens_in, tokens_out) if chunks else Decimal("0")
            )
            message_id = await self._record_answer(
                conv_id,
                principal,
                answer,
                served_model,
                version,
                trace_id,
                latency_ms,
                tokens_in,
                tokens_out,
                cost,
                sources,
                route,
            )

            span.set_attribute("answer.cited_sources", len(chunks))
            yield {
                "event": "done",
                "data": {
                    "conversation_id": str(conv_id),
                    "message_id": str(message_id),
                    "answer": answer,
                    "sources": [asdict(s) for s in sources],
                    "trace_id": trace_id,
                    "model": served_model,
                    "prompt_version": version,
                    "latency_ms": latency_ms,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_usd": str(cost),
                },
            }

    async def _record_user_message(
        self,
        query: str,
        principal: Principal,
        trace_id: str,
        conversation_id: uuid.UUID | None,
    ) -> uuid.UUID:
        async with self._session_factory() as session:
            return await record_user_message(
                session,
                user_id=principal.sub,
                query=query,
                trace_id=trace_id,
                conversation_id=conversation_id,
            )

    async def _record_answer(
        self,
        conversation_id: uuid.UUID,
        principal: Principal,
        answer: str,
        model: str,
        version: str,
        trace_id: str,
        latency_ms: int,
        tokens_in: int,
        tokens_out: int,
        cost: Decimal,
        sources: list[Source],
        route: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        message_id = uuid.uuid4()
        detail: dict[str, Any] = {"sources": [asdict(source) for source in sources]}
        if is_dont_know(answer):
            detail["fallback"] = True
        if route is not None:
            detail["route"] = route
        async with self._session_factory() as session:
            stored = await seal_message(
                session, conversation_id=conversation_id, message_id=message_id, text=answer
            )
            session.add(
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=stored,
                    trace_id=trace_id,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    prompt_version=version,
                    model_version=model,
                    detail=detail,
                )
            )
            if tokens_in or tokens_out:
                await record_cost(
                    session,
                    user_id=principal.sub,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost,
                )
            await session.commit()
        return message_id
