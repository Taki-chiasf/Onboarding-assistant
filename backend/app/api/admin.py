"""Admin-only endpoints.

The cost dashboard aggregates the same ledger the budget guard reads, scoped to
callers whose principal carries the admin role.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.mock_oidc import get_principal
from app.auth.principal import Principal
from app.core.budget import cost_window
from app.core.deps import SettingsDep

router = APIRouter(prefix="/api/admin", tags=["admin"])

MAX_WINDOW_DAYS = 90


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
