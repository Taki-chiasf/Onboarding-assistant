"""Chat and conversation endpoints."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.auth.mock_oidc import get_principal
from app.auth.principal import Principal
from app.core.budget import BudgetDecision, daily_usage, evaluate, record_runaway
from app.core.config import get_settings
from app.llm.client import get_provider, get_router_provider
from app.llm.models import ModelConfig, load_models
from app.models import Conversation, Feedback, Message
from app.rag.answer import RagAnswerer
from app.rag.retrieval import Retriever
from app.router.dispatcher import ChatDispatcher
from app.router.router import IntentRouter
from app.router.schema import Surface
from app.text_to_sql.answer import SqlAnswerer
from app.text_to_sql.executor import SqlExecutor

router = APIRouter(prefix="/api", tags=["chat"])

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    query: str
    conversation_id: uuid.UUID | None = None
    surface: Surface | None = None


def _router_model(models: ModelConfig) -> str:
    if get_settings().llm_provider == "ollama":
        return models.models["router_local"]
    return models.models["router"]


def _build_orchestrator(engine: AsyncEngine) -> ChatDispatcher:
    settings = get_settings()
    provider = get_provider()
    models = load_models()

    async def embed(texts: list[str]) -> list[list[float]]:
        return await provider.embed(models.models["embed"], texts)

    retriever = Retriever(engine, embed)
    rag = RagAnswerer(engine, provider, models, retriever)
    executor = SqlExecutor(
        engine,
        readonly_role=settings.sql_readonly_role,
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        max_rows=settings.sql_max_rows,
    )
    sql = SqlAnswerer(engine, provider, models, executor)
    intent_router = IntentRouter(get_router_provider(), _router_model(models))
    moderation = (provider, models.models["moderation"]) if settings.moderation_enabled else None
    return ChatDispatcher(engine, intent_router, rag, sql, moderation=moderation)


def get_chat_orchestrator(request: Request) -> ChatDispatcher:
    return _build_orchestrator(request.app.state.engine)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
OrchestratorDep = Annotated[ChatDispatcher, Depends(get_chat_orchestrator)]


async def enforce_budget(request: Request, principal: PrincipalDep) -> BudgetDecision:
    """Read today's ledger for the caller and decide whether the turn may run.

    Resolved before the stream starts so an over-budget request never reaches a
    model. Without a database (local unit runs) the cap cannot be evaluated, so
    the turn is allowed.
    """
    settings = get_settings()
    engine: AsyncEngine | None = getattr(request.app.state, "engine", None)
    if engine is None or settings.daily_token_budget <= 0:
        return BudgetDecision(allowed=True, tokens_used=0, cost_usd=Decimal("0"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        usage = await daily_usage(session, user_id=principal.sub, day=datetime.now(UTC).date())
    decision = evaluate(
        usage,
        token_budget=settings.daily_token_budget,
        cost_alert_usd=settings.daily_cost_alert_usd,
    )
    if decision.runaway:
        record_runaway(principal.sub, decision)
    return decision


BudgetDep = Annotated[BudgetDecision, Depends(enforce_budget)]


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    principal: PrincipalDep,
    orchestrator: OrchestratorDep,
    budget: BudgetDep,
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        if not budget.allowed:
            yield _sse("limit", {"message": budget.message})
            return
        try:
            async for event in orchestrator.stream(
                payload.query, principal, payload.conversation_id, surface=payload.surface
            ):
                yield _sse(str(event["event"]), event["data"])
        except Exception:
            # The response has already started by the time a router, builder, or
            # executor failure surfaces, so the status code cannot change. Send a
            # terminal error event instead of dropping the connection, which
            # otherwise looks identical to an empty answer to the client.
            logger.exception("chat stream failed")
            yield _sse(
                "error",
                {"message": "Something went wrong handling that request. Please try again."},
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/conversations")
async def list_conversations(request: Request, principal: PrincipalDep) -> list[dict[str, object]]:
    factory = async_sessionmaker(request.app.state.engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.user_id == principal.sub)
            .order_by(Conversation.created_at.desc())
        )
        rows = result.scalars().all()
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: uuid.UUID, request: Request, principal: PrincipalDep
) -> list[dict[str, object]]:
    factory = async_sessionmaker(request.app.state.engine, expire_on_commit=False)
    async with factory() as session:
        owned = await session.execute(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.user_id == principal.sub,
            )
        )
        if owned.scalar_one_or_none() is None:
            # Do not distinguish "not yours" from "does not exist".
            raise HTTPException(status_code=404, detail="conversation not found")
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        rows = result.scalars().all()
        feedback_by_message: dict[uuid.UUID, Feedback] = {}
        if rows:
            feedback_rows = (
                (
                    await session.execute(
                        select(Feedback).where(
                            Feedback.message_id.in_([row.id for row in rows]),
                            Feedback.source == "real",
                        )
                    )
                )
                .scalars()
                .all()
            )
            for feedback in feedback_rows:
                feedback_by_message.setdefault(feedback.message_id, feedback)
    return [
        {
            "id": str(row.id),
            "role": row.role,
            "content": row.content,
            "trace_id": row.trace_id,
            "detail": row.detail,
            "feedback": (
                {
                    "rating": feedback_by_message[row.id].rating,
                    "correction": feedback_by_message[row.id].correction,
                }
                if row.id in feedback_by_message
                else None
            ),
            "cost_usd": str(row.cost_usd) if row.cost_usd is not None else None,
            "model_version": row.model_version,
            "prompt_version": row.prompt_version,
        }
        for row in rows
    ]
