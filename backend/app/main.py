from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.api import admin, auth, chat, health, oidc
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.otel import init_otel
from app.core.readiness import ReadyCheck, db_check, redis_check


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    engine: AsyncEngine | None = None
    redis_client: redis.Redis | None = None
    checks: list[ReadyCheck] = []

    if settings.database_url:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        checks.append(db_check(engine))
    if settings.redis_url:
        redis_client = redis.from_url(settings.redis_url)
        checks.append(redis_check(redis_client))

    app.state.ready_checks = checks
    app.state.engine = engine
    app.state.redis = redis_client

    yield

    if engine is not None:
        await engine.dispose()
    if redis_client is not None:
        await redis_client.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_otel(settings.app_name, settings.otel_exporter_otlp_endpoint)

    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
    FastAPIInstrumentor.instrument_app(app)
    app.include_router(health.router)
    app.include_router(oidc.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    return app


app = create_app()
