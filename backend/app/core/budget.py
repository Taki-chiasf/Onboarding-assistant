"""Per-user daily token budget and cost aggregation.

The cost ledger already records tokens and spend per user, day, and model. This
module reads it back for two purposes: to enforce a daily token budget before a
request reaches any model, and to aggregate usage for the admin cost dashboard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from opentelemetry import metrics
from opentelemetry.metrics import Counter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLedger

logger = logging.getLogger(__name__)

BUDGET_LIMIT_MESSAGE = "Daily budget reached for your account — resets at 00:00 UTC."

_counter: Counter | None = None
_alerted: set[tuple[str, str]] = set()


def _runaway_counter() -> Counter:
    global _counter
    if _counter is None:
        _counter = metrics.get_meter(__name__).create_counter(
            "cost.runaway", description="Users whose daily spend crossed the alert threshold"
        )
    return _counter


@dataclass(frozen=True)
class Usage:
    tokens: int
    cost_usd: Decimal


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    tokens_used: int
    cost_usd: Decimal
    message: str | None = None
    runaway: bool = False


def evaluate(usage: Usage, *, token_budget: int, cost_alert_usd: float = 0.0) -> BudgetDecision:
    """Decide whether a caller may run another request today.

    The budget is enforced at or above the cap, so the request that would push
    a user over is refused rather than admitted. A non-positive budget disables
    the cap; a non-positive alert threshold disables the runaway flag.
    """
    over_budget = token_budget > 0 and usage.tokens >= token_budget
    runaway = cost_alert_usd > 0 and usage.cost_usd >= Decimal(str(cost_alert_usd))
    return BudgetDecision(
        allowed=not over_budget,
        tokens_used=usage.tokens,
        cost_usd=usage.cost_usd,
        message=BUDGET_LIMIT_MESSAGE if over_budget else None,
        runaway=runaway,
    )


async def daily_usage(session: AsyncSession, *, user_id: str, day: date) -> Usage:
    """Sum a user's tokens and spend for one day."""
    tokens = func.coalesce(func.sum(CostLedger.tokens_in + CostLedger.tokens_out), 0)
    cost = func.coalesce(func.sum(CostLedger.cost_usd), 0)
    row = (
        await session.execute(
            select(tokens, cost).where(CostLedger.user_id == user_id, CostLedger.day == day)
        )
    ).one()
    return Usage(tokens=int(row[0] or 0), cost_usd=Decimal(row[1] or 0))


def record_runaway(user_id: str, decision: BudgetDecision) -> None:
    """Emit a once-per-day runaway alert for a user over the spend threshold."""
    today = datetime.now(UTC).date().isoformat()
    if (user_id, today) in _alerted:
        return
    _alerted.add((user_id, today))
    logger.warning(
        "cost runaway: user=%s tokens=%d cost_usd=%s",
        user_id,
        decision.tokens_used,
        decision.cost_usd,
    )
    _runaway_counter().add(1, {"user_id": user_id})


@dataclass(frozen=True)
class DayUsage:
    day: date
    tokens: int
    cost_usd: Decimal


@dataclass(frozen=True)
class UserUsage:
    user_id: str
    tokens: int
    cost_usd: Decimal


@dataclass(frozen=True)
class ModelUsage:
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


@dataclass(frozen=True)
class CostWindow:
    days: list[DayUsage]
    users: list[UserUsage]
    models: list[ModelUsage]


async def cost_window(session: AsyncSession, *, since: date, until: date) -> CostWindow:
    """Aggregate spend over an inclusive day range by day, user, and model."""
    in_window = (CostLedger.day >= since, CostLedger.day <= until)
    tokens = func.coalesce(func.sum(CostLedger.tokens_in + CostLedger.tokens_out), 0)
    cost = func.coalesce(func.sum(CostLedger.cost_usd), 0)

    day_rows = (
        await session.execute(
            select(CostLedger.day, tokens, cost)
            .where(*in_window)
            .group_by(CostLedger.day)
            .order_by(CostLedger.day)
        )
    ).all()
    user_rows = (
        await session.execute(
            select(CostLedger.user_id, tokens, cost)
            .where(*in_window)
            .group_by(CostLedger.user_id)
            .order_by(cost.desc())
        )
    ).all()
    model_rows = (
        await session.execute(
            select(
                CostLedger.model,
                func.coalesce(func.sum(CostLedger.tokens_in), 0),
                func.coalesce(func.sum(CostLedger.tokens_out), 0),
                cost,
            )
            .where(*in_window)
            .group_by(CostLedger.model)
            .order_by(cost.desc())
        )
    ).all()

    return CostWindow(
        days=[DayUsage(r[0], int(r[1] or 0), Decimal(r[2] or 0)) for r in day_rows],
        users=[UserUsage(str(r[0]), int(r[1] or 0), Decimal(r[2] or 0)) for r in user_rows],
        models=[
            ModelUsage(str(r[0]), int(r[1] or 0), int(r[2] or 0), Decimal(r[3] or 0))
            for r in model_rows
        ],
    )
