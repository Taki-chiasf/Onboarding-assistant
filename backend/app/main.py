import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.api import admin, auth, chat, code, console, feedback, health, oidc, webhooks
from app.auth.oidc import load_oidc_config
from app.core.config import INSECURE_SESSION_SECRET, Settings, get_settings
from app.core.crypto import InvalidKeyError, get_cipher
from app.core.logging import configure_logging
from app.core.otel import init_otel
from app.core.readiness import ReadyCheck, db_check, redis_check

logger = logging.getLogger(__name__)


def _harden_auth(settings: Settings) -> None:
    """Refuse auth configurations that look fine and are not.

    Static mode ignores cookie sessions entirely, so the placeholder secret
    means nothing there. Anywhere a session cookie is trusted, the placeholder
    is treated as "unset": OIDC deployments are refused outright, and the
    persona demo falls back to an ephemeral secret that exists for exactly one
    boot, so the published constant can never forge a session.
    """
    configured_oidc = load_oidc_config(settings) is not None
    if configured_oidc and settings.mock_oidc == 1:
        raise RuntimeError(
            "MOCK_OIDC=1 ignores the configured OIDC provider and signs every "
            "request in as the same developer principal; set MOCK_OIDC=0 when "
            "an issuer is configured"
        )
    if settings.session_secret != INSECURE_SESSION_SECRET:
        return
    if configured_oidc:
        raise RuntimeError(
            "SESSION_SECRET is unset while an OIDC provider is configured "
            "that will issue session cookies; cookies signed with the shipped "
            "placeholder would be forgeable. Set SESSION_SECRET to a real "
            "random value."
        )
    if settings.mock_oidc != 1:
        settings.session_secret = secrets.token_urlsafe(32)
        logger.warning(
            "SESSION_SECRET is unset; generated an ephemeral secret for this "
            "boot only. Cookie sessions expire on restart and are unique per "
            "instance. Set SESSION_SECRET for anything beyond local use."
        )


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
    try:
        cipher = get_cipher()
    except InvalidKeyError as exc:
        raise RuntimeError(f"ENCRYPTION_KEY is invalid: {exc}") from exc
    if cipher is None:
        logger.warning("ENCRYPTION_KEY is not set; conversation history is stored unencrypted")
    _harden_auth(settings)

    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
    FastAPIInstrumentor.instrument_app(app)
    app.include_router(health.router)
    app.include_router(oidc.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(code.router)
    app.include_router(webhooks.router)
    app.include_router(feedback.router)
    app.include_router(admin.router)
    app.include_router(console.router)
    return app


app = create_app()
