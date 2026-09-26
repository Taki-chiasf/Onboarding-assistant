from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.chat import enforce_budget, get_chat_orchestrator
from app.auth.principal import Principal
from app.core.budget import (
    BUDGET_LIMIT_MESSAGE,
    BudgetDecision,
    Usage,
    daily_usage,
    evaluate,
)
from app.core.config import get_settings


def test_evaluate_allows_under_budget() -> None:
    decision = evaluate(Usage(tokens=100, cost_usd=Decimal("0.01")), token_budget=1000)
    assert decision.allowed
    assert decision.message is None
    assert not decision.runaway


def test_evaluate_rejects_at_or_over_budget() -> None:
    for tokens in (1000, 1500):
        decision = evaluate(Usage(tokens=tokens, cost_usd=Decimal("0")), token_budget=1000)
        assert not decision.allowed
        assert decision.message == BUDGET_LIMIT_MESSAGE


def test_evaluate_disabled_budget_never_rejects() -> None:
    decision = evaluate(Usage(tokens=10_000_000, cost_usd=Decimal("99")), token_budget=0)
    assert decision.allowed


def test_evaluate_flags_runaway_only_when_threshold_set() -> None:
    usage = Usage(tokens=10, cost_usd=Decimal("2.50"))
    assert evaluate(usage, token_budget=100, cost_alert_usd=1.0).runaway
    assert not evaluate(usage, token_budget=100, cost_alert_usd=0.0).runaway
    assert not evaluate(usage, token_budget=100, cost_alert_usd=5.0).runaway


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def one(self) -> tuple[object, ...]:
        return self._rows[0]

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


class _StubSession:
    def __init__(self, results: list[_Rows]) -> None:
        self._results = list(results)

    async def execute(self, statement: object) -> _Rows:
        return self._results.pop(0)

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


async def test_daily_usage_sums_tokens_and_cost() -> None:
    from datetime import date

    session = _StubSession([_Rows([(1234, Decimal("0.5"))])])
    usage = await daily_usage(
        cast(AsyncSession, session), user_id="alex-chen", day=date(2026, 9, 26)
    )
    assert usage.tokens == 1234
    assert usage.cost_usd == Decimal("0.5")


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.called = False

    async def stream(
        self, query: str, principal: object, conversation_id: object = None, **_: object
    ) -> AsyncIterator[dict[str, object]]:
        self.called = True
        yield {"event": "done", "data": {"answer": "hi"}}


async def test_chat_emits_limit_event_when_over_budget(app: FastAPI, client: AsyncClient) -> None:
    orchestrator = _FakeOrchestrator()
    app.dependency_overrides[get_chat_orchestrator] = lambda: orchestrator
    app.dependency_overrides[enforce_budget] = lambda: BudgetDecision(
        allowed=False,
        tokens_used=500_000,
        cost_usd=Decimal("3.0"),
        message=BUDGET_LIMIT_MESSAGE,
    )
    try:
        resp = await client.post("/api/chat", json={"query": "how much leave?"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert "event: limit" in resp.text
    assert "Daily budget reached" in resp.text
    assert not orchestrator.called


async def test_chat_runs_orchestrator_when_budget_allows(app: FastAPI, client: AsyncClient) -> None:
    orchestrator = _FakeOrchestrator()
    app.dependency_overrides[get_chat_orchestrator] = lambda: orchestrator
    app.dependency_overrides[enforce_budget] = lambda: BudgetDecision(
        allowed=True, tokens_used=1, cost_usd=Decimal("0")
    )
    try:
        resp = await client.post("/api/chat", json={"query": "how much leave?"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert "event: done" in resp.text
    assert orchestrator.called


async def test_enforce_budget_allows_without_engine() -> None:
    """A local run with no database cannot evaluate the cap, so it allows."""
    request = cast(
        Request, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=None)))
    )
    principal = Principal(
        sub="alex-chen", email="alex.chen@demo.example", dept="Engineering", role="employee"
    )
    decision = await enforce_budget(request, principal)
    assert decision.allowed
    get_settings.cache_clear()
