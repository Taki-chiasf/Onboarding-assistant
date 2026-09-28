import os
import uuid
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
from app.models import CostLedger, EvalCase, Feedback, Message


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def one(self) -> Any:
        return self._rows[0]

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _StubSession:
    def __init__(self, results: list[_Rows], *, get_result: Any = None) -> None:
        self._results = list(results)
        self._get_result = get_result
        self.committed = False

    async def execute(self, statement: object) -> _Rows:
        return self._results.pop(0)

    async def get(self, model: Any, ident: Any) -> Any:
        return self._get_result

    async def commit(self) -> None:
        self.committed = True

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


def _review_case(*, status: str = "review", source_message_id: uuid.UUID | None = None) -> EvalCase:
    return EvalCase(
        id=uuid.uuid4(),
        prompt="How much leave do I get?",
        status=status,
        source="thumbs_down",
        source_message_id=source_message_id,
        tags=["feedback", "dept:Engineering"],
        created_at=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
    )


async def test_review_queue_forbids_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="employee")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/admin/review")
    assert resp.status_code == 403
    get_settings.cache_clear()


async def test_review_queue_needs_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/admin/review")
    assert resp.status_code == 503
    get_settings.cache_clear()


async def test_review_queue_serializes_the_filed_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    message = Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role="assistant",
        content="16 weeks",
        trace_id="trace-9",
        detail={"route": {"intent": "rag-docs"}},
        created_at=datetime(2026, 9, 28, 12, 1, tzinfo=UTC),
    )
    case = _review_case(source_message_id=message.id)
    feedback = Feedback(
        message_id=message.id,
        rating="down",
        correction="missing the policy citation",
        source="real",
        trace_id="trace-9",
    )
    session = _StubSession([_Rows([case]), _Rows([feedback]), _Rows([message])])
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/admin/review")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()["cases"][0]
    assert body["id"] == str(case.id)
    assert body["prompt"] == "How much leave do I get?"
    assert body["rating"] == "down"
    assert body["correction"] == "missing the policy citation"
    assert body["message_id"] == str(message.id)
    assert body["trace_id"] == "trace-9"
    assert body["detail"] == {"route": {"intent": "rag-docs"}}
    assert body["created_at"].startswith("2026-09-28T12:00")
    get_settings.cache_clear()


async def test_review_queue_is_empty_without_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    session = _StubSession([_Rows([])])
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/admin/review")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == {"cases": []}
    get_settings.cache_clear()


async def test_promote_requires_an_expectation(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    case = _review_case()
    session = _StubSession([], get_result=case)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/api/admin/review/{case.id}/promote", json={})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 422
    assert case.status == "review"
    get_settings.cache_clear()


async def test_promote_rejects_an_invalid_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    case = _review_case()
    session = _StubSession([], get_result=case)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/admin/review/{case.id}/promote",
                json={"expected_sql_pattern": "SELECT ("},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 422
    assert case.status == "review"
    get_settings.cache_clear()


async def test_promote_marks_the_case_reviewed(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(
        monkeypatch,
        MOCK_OIDC="1",
        DEV_PRINCIPAL_ROLE="admin",
        DEV_PRINCIPAL_EMAIL="admin@example.com",
    )
    case = _review_case()
    session = _StubSession([], get_result=case)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/admin/review/{case.id}/promote",
                json={
                    "expected_intent": "rag-docs",
                    "expected_source_ids": ["chunk-1"],
                    "expected_sql_pattern": r"org_members.*role\s*=\s*'manager'",
                    "expected_rows_predicate": "count>=1",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {
        "id": str(case.id),
        "status": "promoted",
        "reviewed_by": "admin@example.com",
    }
    assert case.status == "promoted"
    assert case.expected_intent == "rag-docs"
    assert case.expected_source_ids == ["chunk-1"]
    assert case.expected_sql_pattern == r"org_members.*role\s*=\s*'manager'"
    assert case.expected_rows_predicate == "count>=1"
    assert case.reviewed_by == "admin@example.com"
    assert session.committed is True
    get_settings.cache_clear()


async def test_promote_conflicts_outside_review(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    case = _review_case(status="promoted")
    session = _StubSession([], get_result=case)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/admin/review/{case.id}/promote",
                json={"expected_intent": "rag-docs"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 409
    get_settings.cache_clear()


async def test_promote_reports_a_missing_case(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    session = _StubSession([], get_result=None)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                f"/api/admin/review/{uuid.uuid4()}/promote",
                json={"expected_intent": "rag-docs"},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 404
    get_settings.cache_clear()


async def test_reject_marks_the_case(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(
        monkeypatch,
        MOCK_OIDC="1",
        DEV_PRINCIPAL_ROLE="admin",
        DEV_PRINCIPAL_EMAIL="admin@example.com",
    )
    case = _review_case()
    session = _StubSession([], get_result=case)
    app.dependency_overrides[get_session_factory] = lambda: lambda: session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/api/admin/review/{case.id}/reject")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert case.status == "rejected"
    assert case.reviewed_by == "admin@example.com"
    get_settings.cache_clear()
