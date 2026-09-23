"""Text-to-SQL answer path: build, execute, summarize, stream.

The streaming surface mirrors the RAG orchestrator so the router can dispatch to
either path uniformly. Events: ``sql`` (query text + row metrics), ``token``*
(summary tokens), ``done`` (final answer + provenance). The summary is grounded
in the returned rows; an empty result set yields deterministic copy instead of a
model call.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth.principal import Principal
from app.core.redact import redact_pii
from app.llm.models import ModelConfig
from app.llm.pricing import compute_cost, estimate_tokens
from app.llm.provider import ChatMessage, ChatProvider
from app.models import Conversation, Message
from app.prompts.loader import load_prompt, prompt_version
from app.rag.cost import record_cost
from app.text_to_sql.builder import SqlBuilder
from app.text_to_sql.executor import SqlExecutor, SqlResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

SQL_SUMMARIZE_PROMPT = "sql_summarize"
NO_MATCHING_RECORDS = "No matching records."


@dataclass(frozen=True)
class SqlEvent:
    sql: str
    row_count: int
    truncated: bool
    latency_ms: int


def format_row_packet(result: SqlResult, limit: int = 50) -> str:
    """Render query rows as a compact markdown table for the summary step."""
    header = "| " + " | ".join(result.columns) + " |"
    divider = "|" + "|".join("---" for _ in result.columns) + "|"
    lines = [header, divider]
    for row in result.rows[:limit]:
        cells = ["" if value is None else str(value) for value in row]
        lines.append("| " + " | ".join(cells) + " |")
    if result.truncated:
        lines.append("(result set truncated by the row cap)")
    return "\n".join(lines)


def build_summary_messages(query: str, result: SqlResult) -> tuple[list[ChatMessage], str]:
    prompt = load_prompt(SQL_SUMMARIZE_PROMPT)
    user_content = prompt.user.format(
        query=query, rows=len(result.rows), table=format_row_packet(result)
    )
    messages = [
        ChatMessage(role="system", content=prompt.system),
        ChatMessage(role="user", content=user_content),
    ]
    return messages, prompt_version(SQL_SUMMARIZE_PROMPT)


class SqlAnswerer:
    def __init__(
        self,
        engine: AsyncEngine,
        provider: ChatProvider,
        models: ModelConfig,
        executor: SqlExecutor,
    ) -> None:
        self._engine = engine
        self._provider = provider
        self._models = models
        self._executor = executor
        self._builder = SqlBuilder(provider, models.models["sql_builder"])
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def stream(
        self,
        query: str,
        principal: Principal,
        conversation_id: uuid.UUID | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        trace_id = uuid.uuid4().hex
        started = perf_counter()
        logger.info(
            "sql query from %s: %s", principal.email, redact_pii(query, allow=[principal.email])
        )

        with tracer.start_as_current_span("sql_answer") as span:
            span.set_attribute("user.dept", principal.dept)
            span.set_attribute("user.role", principal.role)

            conv_id = await self._record_user_message(query, principal, trace_id, conversation_id)

            with tracer.start_as_current_span("sql_generate"):
                built = await self._builder.build(query)
            span.set_attribute("sql.prompt_version", built.prompt_version)

            with tracer.start_as_current_span("sql_execute"):
                result = await self._executor.execute(
                    built.sql,
                    dept=principal.dept,
                    role=principal.role,
                    principal=principal.email,
                    trace_id=trace_id,
                )

            yield {
                "event": "sql",
                "data": asdict(
                    SqlEvent(
                        sql=built.sql,
                        row_count=len(result.rows),
                        truncated=result.truncated,
                        latency_ms=result.latency_ms,
                    )
                ),
            }

            summary_model = self._models.models["grounding"]
            summary_tokens_in = 0

            if not result.rows:
                answer = NO_MATCHING_RECORDS
                version = prompt_version(SQL_SUMMARIZE_PROMPT)
                yield {"event": "token", "data": {"text": answer}}
            else:
                messages, version = build_summary_messages(query, result)
                summary_tokens_in = estimate_tokens("".join(m.content for m in messages))
                parts: list[str] = []
                with tracer.start_as_current_span("sql_summarize"):
                    async for token in self._provider.stream(summary_model, messages):
                        parts.append(token)
                        yield {"event": "token", "data": {"text": token}}
                answer = "".join(parts)

            latency_ms = int((perf_counter() - started) * 1000)
            tokens_out = estimate_tokens(answer)
            sql_tokens_out = estimate_tokens(built.sql)
            builder_cost = compute_cost(
                self._models.models["sql_builder"], built.tokens_in, sql_tokens_out
            )
            summary_cost = compute_cost(summary_model, summary_tokens_in, tokens_out)
            cost = builder_cost + summary_cost

            message_id = await self._record_answer(
                conv_id,
                principal,
                answer,
                summary_model,
                version,
                trace_id,
                latency_ms,
                cost,
                built.tokens_in,
                sql_tokens_out,
                builder_cost,
                summary_tokens_in,
                tokens_out,
                summary_cost,
            )

            span.set_attribute("answer.row_count", len(result.rows))
            yield {
                "event": "done",
                "data": {
                    "conversation_id": str(conv_id),
                    "message_id": str(message_id),
                    "answer": answer,
                    "sql": built.sql,
                    "row_count": len(result.rows),
                    "truncated": result.truncated,
                    "sql_latency_ms": result.latency_ms,
                    "trace_id": trace_id,
                    "model": summary_model,
                    "sql_model": self._models.models["sql_builder"],
                    "prompt_version": version,
                    "sql_prompt_version": built.prompt_version,
                    "latency_ms": latency_ms,
                    "tokens_in": summary_tokens_in,
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
        principal: Principal,
        answer: str,
        model: str,
        version: str,
        trace_id: str,
        latency_ms: int,
        cost: Decimal,
        sql_tokens_in: int,
        sql_tokens_out: int,
        builder_cost: Decimal,
        tokens_in: int,
        tokens_out: int,
        summary_cost: Decimal,
    ) -> uuid.UUID:
        message_id = uuid.uuid4()
        async with self._session_factory() as session:
            session.add(
                Message(
                    id=message_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                    trace_id=trace_id,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    prompt_version=version,
                    model_version=model,
                )
            )
            await record_cost(
                session,
                user_id=principal.sub,
                model=self._models.models["sql_builder"],
                tokens_in=sql_tokens_in,
                tokens_out=sql_tokens_out,
                cost_usd=builder_cost,
            )
            if tokens_in or tokens_out:
                await record_cost(
                    session,
                    user_id=principal.sub,
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=summary_cost,
                )
            await session.commit()
        return message_id
