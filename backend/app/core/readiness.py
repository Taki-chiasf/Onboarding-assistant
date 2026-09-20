from collections.abc import Awaitable, Callable

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

ReadyCheck = Callable[[], Awaitable[tuple[str, bool]]]


def db_check(engine: AsyncEngine) -> ReadyCheck:
    async def _check() -> tuple[str, bool]:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return "postgres", True
        except Exception:
            return "postgres", False

    return _check


def redis_check(client: redis.Redis) -> ReadyCheck:
    async def _check() -> tuple[str, bool]:
        try:
            await client.ping()
            return "redis", True
        except Exception:
            return "redis", False

    return _check
