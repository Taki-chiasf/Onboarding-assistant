"""Admin-only endpoints.

The cost dashboard aggregates the same ledger the budget guard reads, scoped to
callers whose principal carries the admin role. The eval review queue lists the
candidate cases filed by feedback so an admin can promote or reject them.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.mock_oidc import get_principal
from app.auth.principal import Principal
from app.core.budget import cost_window
from app.core.deps import SettingsDep
from app.models import EvalCase, Feedback, Message
from app.router.schema import Intent

router = APIRouter(prefix="/api/admin", tags=["admin"])

MAX_WINDOW_DAYS = 90
MAX_REVIEW_CASES = 200


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not configured",
        )
    return async_sessionmaker(engine, expire_on_commit=False)


def require_admin(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return principal


AdminDep = Annotated[Principal, Depends(require_admin)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


class DayCost(BaseModel):
    day: str
    tokens: int
    cost_usd: str


class UserCost(BaseModel):
    user_id: str
    tokens: int
    cost_usd: str


class ModelCost(BaseModel):
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: str


class CostSummary(BaseModel):
    window_days: int
    daily_token_budget: int
    daily_cost_alert_usd: float
    days: list[DayCost]
    users: list[UserCost]
    models: list[ModelCost]


@router.get("/cost", response_model=CostSummary)
async def cost_summary(
    _admin: AdminDep,
    factory: SessionFactoryDep,
    settings: SettingsDep,
    days: int = 1,
) -> CostSummary:
    window = max(1, min(days, MAX_WINDOW_DAYS))
    until = datetime.now(UTC).date()
    since = until - timedelta(days=window - 1)
    async with factory() as session:
        data = await cost_window(session, since=since, until=until)
    return CostSummary(
        window_days=window,
        daily_token_budget=settings.daily_token_budget,
        daily_cost_alert_usd=settings.daily_cost_alert_usd,
        days=[
            DayCost(day=row.day.isoformat(), tokens=row.tokens, cost_usd=str(row.cost_usd))
            for row in data.days
        ],
        users=[
            UserCost(user_id=row.user_id, tokens=row.tokens, cost_usd=str(row.cost_usd))
            for row in data.users
        ],
        models=[
            ModelCost(
                model=row.model,
                tokens_in=row.tokens_in,
                tokens_out=row.tokens_out,
                cost_usd=str(row.cost_usd),
            )
            for row in data.models
        ],
    )


class ReviewCase(BaseModel):
    id: str
    prompt: str
    status: str
    source: str | None
    tags: list[str] | None
    created_at: str
    expected_intent: str | None
    expected_source_ids: list[str] | None
    expected_sql_pattern: str | None
    expected_rows_predicate: str | None
    message_id: str | None
    trace_id: str | None
    rating: str | None
    correction: str | None
    detail: dict[str, Any] | None


class ReviewQueue(BaseModel):
    cases: list[ReviewCase]


class PromoteRequest(BaseModel):
    expected_intent: Intent | None = None
    expected_source_ids: list[str] | None = None
    expected_sql_pattern: str | None = None
    expected_rows_predicate: str | None = None


class ReviewDecision(BaseModel):
    id: str
    status: str
    reviewed_by: str


def _review_case(case: EvalCase, feedback: Feedback | None, message: Message | None) -> ReviewCase:
    return ReviewCase(
        id=str(case.id),
        prompt=case.prompt,
        status=case.status,
        source=case.source,
        tags=case.tags,
        created_at=case.created_at.isoformat(),
        expected_intent=case.expected_intent,
        expected_source_ids=case.expected_source_ids,
        expected_sql_pattern=case.expected_sql_pattern,
        expected_rows_predicate=case.expected_rows_predicate,
        message_id=str(message.id) if message is not None else None,
        trace_id=message.trace_id if message is not None else None,
        rating=feedback.rating if feedback is not None else None,
        correction=feedback.correction if feedback is not None else None,
        detail=message.detail if message is not None else None,
    )


@router.get("/review", response_model=ReviewQueue)
async def review_queue(
    _admin: AdminDep,
    factory: SessionFactoryDep,
    limit: int = 50,
) -> ReviewQueue:
    bounded = max(1, min(limit, MAX_REVIEW_CASES))
    async with factory() as session:
        cases = (
            (
                await session.execute(
                    select(EvalCase)
                    .where(EvalCase.status == "review")
                    .order_by(EvalCase.created_at.desc())
                    .limit(bounded)
                )
            )
            .scalars()
            .all()
        )
        message_ids = [case.source_message_id for case in cases if case.source_message_id]
        feedback_by_message: dict[uuid.UUID, Feedback] = {}
        message_by_id: dict[uuid.UUID, Message] = {}
        if message_ids:
            feedback_rows = (
                (
                    await session.execute(
                        select(Feedback)
                        .where(
                            Feedback.message_id.in_(message_ids),
                            Feedback.source == "real",
                        )
                        .order_by(Feedback.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            for row in feedback_rows:
                if row.message_id is not None:
                    feedback_by_message.setdefault(row.message_id, row)
            messages = (
                (await session.execute(select(Message).where(Message.id.in_(message_ids))))
                .scalars()
                .all()
            )
            message_by_id = {message.id: message for message in messages}
    return ReviewQueue(
        cases=[
            _review_case(
                case,
                feedback_by_message.get(case.source_message_id) if case.source_message_id else None,
                message_by_id.get(case.source_message_id) if case.source_message_id else None,
            )
            for case in cases
        ]
    )


async def _reviewable_case(session: AsyncSession, case_id: uuid.UUID) -> EvalCase:
    case = await session.get(EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    if case.status != "review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="case is not awaiting review"
        )
    return case


@router.post("/review/{case_id}/promote", response_model=ReviewDecision)
async def promote_case(
    case_id: uuid.UUID,
    payload: PromoteRequest,
    admin: AdminDep,
    factory: SessionFactoryDep,
) -> ReviewDecision:
    async with factory() as session:
        case = await _reviewable_case(session, case_id)

        if payload.expected_sql_pattern is not None:
            try:
                re.compile(payload.expected_sql_pattern)
            except re.error as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"expected_sql_pattern is not a valid regex: {exc}",
                ) from exc
            case.expected_sql_pattern = payload.expected_sql_pattern
        if payload.expected_intent is not None:
            case.expected_intent = payload.expected_intent.value
        if payload.expected_source_ids is not None:
            case.expected_source_ids = payload.expected_source_ids
        if payload.expected_rows_predicate is not None:
            case.expected_rows_predicate = payload.expected_rows_predicate

        has_expectation = any(
            (
                case.expected_intent,
                case.expected_source_ids,
                case.expected_sql_pattern,
                case.expected_rows_predicate,
            )
        )
        if not has_expectation:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="a promoted case needs at least one expectation",
            )

        case.status = "promoted"
        case.reviewed_by = admin.email
        await session.commit()
    return ReviewDecision(id=str(case_id), status=case.status, reviewed_by=admin.email)


@router.post("/review/{case_id}/reject", response_model=ReviewDecision)
async def reject_case(
    case_id: uuid.UUID,
    admin: AdminDep,
    factory: SessionFactoryDep,
) -> ReviewDecision:
    async with factory() as session:
        case = await _reviewable_case(session, case_id)
        case.status = "rejected"
        case.reviewed_by = admin.email
        await session.commit()
    return ReviewDecision(id=str(case_id), status=case.status, reviewed_by=admin.email)
