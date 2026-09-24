from typing import cast

import pytest

from app.eval.ab import (
    VariantOutcome,
    decide_local_router,
    decide_sql_challenger,
    measure_router,
    measure_sql,
    router_ab_result,
    sql_ab_result,
)
from app.eval.router_eval import make_keyless_provider
from app.eval.router_golden import build_router_set
from app.eval.sql_golden import SqlCase
from app.router.router import IntentRouter
from app.text_to_sql.builder import BuiltSql, SqlBuilder
from app.text_to_sql.executor import SqlExecutor, SqlResult


def _outcome(label: str, model: str, accuracy: float, p95: float) -> VariantOutcome:
    return VariantOutcome(label=label, model=model, accuracy=accuracy, p95_latency_s=p95, total=120)


def test_sql_challenger_adopted_on_clear_win() -> None:
    incumbent = _outcome("large", "mistral-large-2512", 0.86, 4.0)
    challenger = _outcome("reasoner", "magistral-small-2509", 0.91, 3.8)
    decision = decide_sql_challenger(incumbent, challenger)
    assert decision.adopt == "magistral-small-2509"
    assert decision.gain == pytest.approx(0.05)


def test_sql_challenger_rejected_below_gain_bar() -> None:
    incumbent = _outcome("large", "mistral-large-2512", 0.90, 4.0)
    challenger = _outcome("reasoner", "magistral-small-2509", 0.92, 3.5)
    decision = decide_sql_challenger(incumbent, challenger)
    assert decision.adopt == "mistral-large-2512"
    assert "below the" in decision.reason


def test_sql_challenger_rejected_on_latency_regression() -> None:
    incumbent = _outcome("large", "mistral-large-2512", 0.86, 4.0)
    challenger = _outcome("reasoner", "magistral-small-2509", 0.95, 6.5)
    decision = decide_sql_challenger(incumbent, challenger)
    assert decision.adopt == "mistral-large-2512"
    assert "latency" in decision.reason


def test_local_router_adopted_above_bar() -> None:
    local = _outcome("local", "ministral-3:8b", 0.93, 0.5)
    api = _outcome("api", "mistral-small-2603", 0.95, 1.1)
    decision = decide_local_router(local, api)
    assert decision.adopt == "ministral-3:8b"


def test_local_router_falls_back_below_bar() -> None:
    local = _outcome("local", "ministral-3:8b", 0.88, 0.5)
    api = _outcome("api", "mistral-small-2603", 0.95, 1.1)
    decision = decide_local_router(local, api)
    assert decision.adopt == "mistral-small-2603"
    assert "below the" in decision.reason


class _FakeBuilder:
    def __init__(self, sql: str) -> None:
        self._sql = sql

    async def build(self, query: str) -> BuiltSql:
        return BuiltSql(sql=self._sql, prompt_version="sql_builder.v1", tokens_in=10)


class _FakeExecutor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    async def execute(
        self, sql: str, *, dept: str, role: str, principal: str, trace_id: str | None = None
    ) -> SqlResult:
        return SqlResult(columns=["count"], rows=self._rows, truncated=False, latency_ms=1)


async def test_measure_router_reports_accuracy_and_latency() -> None:
    cases = build_router_set()
    router = IntentRouter(make_keyless_provider(cases), "fake-router")
    outcome = await measure_router(router, cases, label="local", model="fake-router")
    assert outcome.label == "local"
    assert outcome.total == len(cases)
    assert outcome.accuracy == 1.0
    assert outcome.p95_latency_s >= 0.0


async def test_measure_sql_reports_accuracy() -> None:
    case = SqlCase(
        prompt="How many open tickets?",
        golden_sql="SELECT count(*) FROM tickets WHERE status = 'open'",
        expected_sql_pattern=r"count\(\*\).*tickets.*status\s*=\s*'open'",
    )
    builder = cast(SqlBuilder, _FakeBuilder(case.golden_sql))
    executor = cast(SqlExecutor, _FakeExecutor([(3,)]))
    outcome = await measure_sql(
        builder,
        executor,
        [case],
        label="incumbent",
        model="mistral-large-2512",
        personas=(("Engineering", "employee"),),
    )
    assert outcome.total == 1
    assert outcome.accuracy == 1.0


def test_ab_result_serializes() -> None:
    local = _outcome("local", "ministral-3:8b", 0.93, 0.5)
    api = _outcome("api", "mistral-small-2603", 0.95, 1.1)
    payload = router_ab_result(local, api).to_dict()
    assert payload["adopt"] == "ministral-3:8b"
    assert len(payload["variants"]) == 2

    incumbent = _outcome("incumbent", "mistral-large-2512", 0.86, 4.0)
    challenger = _outcome("challenger", "magistral-small-2509", 0.92, 3.9)
    payload = sql_ab_result(incumbent, challenger).to_dict()
    assert payload["adopt"] == "magistral-small-2509"
