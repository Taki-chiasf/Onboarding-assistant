from typing import cast
from unittest.mock import AsyncMock, MagicMock

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.readiness import db_check, redis_check


def _fake_engine(*, ok: bool) -> AsyncEngine:
    engine = MagicMock()
    cm = MagicMock()
    cm.__aexit__ = AsyncMock(return_value=False)
    if ok:
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    else:
        cm.__aenter__ = AsyncMock(side_effect=RuntimeError("down"))
    engine.connect = MagicMock(return_value=cm)
    return cast(AsyncEngine, engine)


async def test_db_check_ok() -> None:
    assert await db_check(_fake_engine(ok=True))() == ("postgres", True)


async def test_db_check_down() -> None:
    assert await db_check(_fake_engine(ok=False))() == ("postgres", False)


async def test_redis_check_ok() -> None:
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    assert await redis_check(cast(redis.Redis, client))() == ("redis", True)


async def test_redis_check_down() -> None:
    client = MagicMock()
    client.ping = AsyncMock(side_effect=RuntimeError("down"))
    assert await redis_check(cast(redis.Redis, client))() == ("redis", False)
