"""Retention job for query logs and the eval set.

Keeps stored data inside the retention window: query audit logs and eval-run
records older than the window are deleted. Conversation-history erasure is a
separate, user-requested concern and is not handled here.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.models import AuditLog, EvalRun

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetentionResult:
    audit_logs: int
    eval_runs: int


async def purge_expired(
    session: AsyncSession, *, days: int, now: datetime | None = None
) -> RetentionResult:
    """Delete audit logs and eval runs older than ``days`` from ``now``."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    audit = await session.execute(delete(AuditLog).where(AuditLog.ts < cutoff))
    runs = await session.execute(delete(EvalRun).where(EvalRun.run_at < cutoff))
    await session.commit()
    return RetentionResult(
        audit_logs=cast(CursorResult[Any], audit).rowcount or 0,
        eval_runs=cast(CursorResult[Any], runs).rowcount or 0,
    )


async def run_retention(engine: AsyncEngine, *, days: int) -> RetentionResult:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        return await purge_expired(session, days=days)


async def _run(days: int) -> RetentionResult:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to run retention")
    engine = create_async_engine(settings.database_url)
    try:
        result = await run_retention(engine, days=days)
    finally:
        await engine.dispose()
    logger.info(
        "retention: deleted audit_logs=%d eval_runs=%d older than %d days",
        result.audit_logs,
        result.eval_runs,
        days,
    )
    return result


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Delete logs and eval records past retention")
    parser.add_argument("--days", type=int, default=None, help="override RETENTION_DAYS")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    days = args.days if args.days is not None else get_settings().retention_days
    asyncio.run(_run(days))


if __name__ == "__main__":
    main()
