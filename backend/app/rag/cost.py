"""Cost ledger recording."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLedger


async def record_cost(
    session: AsyncSession,
    *,
    user_id: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: Decimal,
    day: date | None = None,
) -> None:
    target_day = day or datetime.now(UTC).date()
    stmt = insert(CostLedger).values(
        user_id=user_id,
        day=target_day,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[CostLedger.user_id, CostLedger.day, CostLedger.model],
        set_={
            "tokens_in": stmt.excluded.tokens_in + CostLedger.tokens_in,
            "tokens_out": stmt.excluded.tokens_out + CostLedger.tokens_out,
            "cost_usd": stmt.excluded.cost_usd + CostLedger.cost_usd,
        },
    )
    await session.execute(stmt)
