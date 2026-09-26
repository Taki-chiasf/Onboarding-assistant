import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import AuditLog
from app.retention import RetentionResult, purge_expired, run_retention


class _Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _Session:
    def __init__(self, counts: list[int]) -> None:
        self._counts = list(counts)
        self.committed = False

    async def execute(self, statement: object) -> _Result:
        return _Result(self._counts.pop(0))

    async def commit(self) -> None:
        self.committed = True


async def test_purge_expired_reports_rows_deleted() -> None:
    session = _Session([3, 5])
    result = await purge_expired(
        cast(AsyncSession, session), days=90, now=datetime(2026, 9, 26, tzinfo=UTC)
    )
    assert result == RetentionResult(audit_logs=3, eval_runs=5)
    assert session.committed


_LIVE_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture
async def live_engine() -> AsyncIterator[AsyncEngine]:
    if not _LIVE_DB_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    engine = create_async_engine(_LIVE_DB_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_run_retention_deletes_only_expired_rows(live_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(live_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    principal = f"retention-test-{uuid.uuid4().hex}"
    async with factory() as session:
        session.add(AuditLog(principal=principal, action="x", ts=now - timedelta(days=200)))
        session.add(AuditLog(principal=principal, action="x", ts=now - timedelta(days=1)))
        await session.commit()
        rows = (
            await session.execute(select(AuditLog.id).where(AuditLog.principal == principal))
        ).scalars()
        ids = list(rows)
    assert len(ids) == 2
    try:
        result = await run_retention(live_engine, days=90)
        assert result.audit_logs >= 1
        async with factory() as session:
            remaining = list(
                (
                    await session.execute(
                        select(AuditLog.id).where(AuditLog.principal == principal)
                    )
                ).scalars()
            )
        assert len(remaining) == 1
    finally:
        async with factory() as session:
            await session.execute(delete(AuditLog).where(AuditLog.principal == principal))
            await session.commit()
