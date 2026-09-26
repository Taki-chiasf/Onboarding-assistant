import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.admin import get_session_factory
from app.core.budget import cost_window
from app.core.config import get_settings
from app.main import create_app
from app.models import CostLedger


class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows

    def one(self) -> tuple[Any, ...]:
        return self._rows[0]


class _StubSession:
    def __init__(self, results: list[_Rows]) -> None:
        self._results = list(results)

    async def execute(self, statement: object) -> _Rows:
        return self._results.pop(0)

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _app(monkeypatch: pytest.MonkeyPatch, **env: str) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return create_app()


async def test_cost_summary_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="0")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/admin/cost")
    assert resp.status_code == 401
    get_settings.cache_clear()


async def test_cost_summary_forbids_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="employee")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/admin/cost")
    assert resp.status_code == 403
    get_settings.cache_clear()


async def test_cost_summary_needs_a_database_for_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/admin/cost")
    assert resp.status_code == 503
    get_settings.cache_clear()


async def test_cost_summary_serializes_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    session = _StubSession(
        [
            _Rows([(date(2026, 9, 26), 150, Decimal("0.250000"))]),
            _Rows([("alex-chen", 150, Decimal("0.250000"))]),
            _Rows([("mistral-large-2512", 100, 50, Decimal("0.250000"))]),
        ]
    )
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/admin/cost?days=1")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["window_days"] == 1
    assert body["daily_token_budget"] == 200_000
    assert body["days"] == [{"day": "2026-09-26", "tokens": 150, "cost_usd": "0.250000"}]
    assert body["users"][0]["user_id"] == "alex-chen"
    assert body["models"][0]["model"] == "mistral-large-2512"
    get_settings.cache_clear()


async def test_cost_summary_clamps_window(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    app.dependency_overrides[get_session_factory] = lambda: (
        lambda: _StubSession([_Rows([]), _Rows([]), _Rows([])])
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            body = (await c.get("/api/admin/cost?days=365")).json()
    finally:
        app.dependency_overrides.clear()
    assert body["window_days"] == 90
    get_settings.cache_clear()


async def test_cost_window_maps_rows() -> None:
    session = _StubSession(
        [
            _Rows([(date(2026, 9, 26), 150, Decimal("0.25"))]),
            _Rows([("alex-chen", 150, Decimal("0.25"))]),
            _Rows([("mistral-large-2512", 100, 50, Decimal("0.25"))]),
        ]
    )
    window = await cost_window(
        cast(AsyncSession, session), since=date(2026, 9, 26), until=date(2026, 9, 26)
    )
    assert window.days[0].day == date(2026, 9, 26)
    assert window.days[0].tokens == 150
    assert window.users[0].user_id == "alex-chen"
    assert window.models[0].tokens_in == 100
    assert window.models[0].tokens_out == 50


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


@pytest.fixture
async def admin_stack(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    monkeypatch.setenv("MOCK_OIDC", "1")
    monkeypatch.setenv("DEV_PRINCIPAL_SUB", "admin-live-user")
    monkeypatch.setenv("DEV_PRINCIPAL_ROLE", "admin")
    monkeypatch.setenv("DATABASE_URL", _LIVE_DB_URL)
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    application = create_app()
    application.state.engine = live_engine
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield application, c
    get_settings.cache_clear()


async def test_cost_summary_reports_ledger_rows(
    admin_stack: tuple[FastAPI, AsyncClient], live_engine: AsyncEngine
) -> None:
    _app_obj, client = admin_stack
    factory = async_sessionmaker(live_engine, expire_on_commit=False)
    today = datetime.now(UTC).date()
    async with factory() as session:
        session.add(
            CostLedger(
                user_id="admin-live-user",
                day=today,
                model="test-model-live",
                tokens_in=100,
                tokens_out=50,
                cost_usd=Decimal("0.25"),
            )
        )
        await session.commit()
    try:
        resp = await client.get("/api/admin/cost?days=1")
        assert resp.status_code == 200
        body = resp.json()
        users = {u["user_id"]: u for u in body["users"]}
        assert users["admin-live-user"]["tokens"] == 150
        assert users["admin-live-user"]["cost_usd"] == "0.250000"
        models = {m["model"]: m for m in body["models"]}
        assert models["test-model-live"]["tokens_in"] == 100
        assert models["test-model-live"]["tokens_out"] == 50
        assert any(d["day"] == today.isoformat() for d in body["days"])
    finally:
        async with factory() as session:
            await session.execute(delete(CostLedger).where(CostLedger.user_id == "admin-live-user"))
            await session.commit()
