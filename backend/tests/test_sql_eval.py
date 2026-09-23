import os
from typing import cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.eval.sql_eval import (
    matches_pattern,
    question_from_messages,
    rows_satisfy,
    run_sql_eval,
)
from app.eval.sql_golden import PERSONAS, SqlCase, build_sql_set
from app.llm.provider import ChatMessage
from app.text_to_sql.builder import BuiltSql, SqlBuilder
from app.text_to_sql.executor import SqlExecutor, SqlResult
from scripts.seed import seed

DATABASE_URL = os.environ.get("DATABASE_URL") or ""


def _case(**overrides: object) -> SqlCase:
    fields: dict[str, object] = {
        "prompt": "How many open tickets?",
        "golden_sql": "SELECT count(*) FROM tickets WHERE status = 'open'",
        "expected_sql_pattern": r"count\(\*\).*tickets.*status\s*=\s*'open'",
        "expected_rows_predicate": None,
    }
    fields.update(overrides)
    return SqlCase(**fields)  # type: ignore[arg-type]


def test_matches_pattern() -> None:
    case = _case()
    assert matches_pattern(case, "SELECT count(*) AS n FROM tickets WHERE status = 'open'")
    assert not matches_pattern(case, "SELECT * FROM projects")


def test_rows_satisfy_without_predicate() -> None:
    case = _case()
    assert rows_satisfy(case, [])


def test_rows_satisfy_applies_predicate() -> None:
    case = _case(
        expected_rows_predicate=lambda rows: all(r.get("status") == "available" for r in rows)
    )
    assert rows_satisfy(case, [{"status": "available"}])
    assert not rows_satisfy(case, [{"status": "assigned"}])


def test_question_from_messages() -> None:
    messages = [
        ChatMessage(role="system", content="schema"),
        ChatMessage(role="user", content="Question: How many people work here?\n"),
    ]
    assert question_from_messages(messages) == "How many people work here?"


class _FakeBuilder:
    def __init__(self, sql: str) -> None:
        self._sql = sql

    async def build(self, query: str) -> BuiltSql:
        return BuiltSql(sql=self._sql, prompt_version="sql_builder.v1", tokens_in=10)


class _FakeExecutor:
    def __init__(self, columns: list[str], rows: list[tuple[object, ...]]) -> None:
        self._columns = columns
        self._rows = rows

    async def execute(
        self, sql: str, *, dept: str, role: str, principal: str, trace_id: str | None = None
    ) -> SqlResult:
        return SqlResult(columns=self._columns, rows=self._rows, truncated=False, latency_ms=1)


async def test_run_sql_eval_grades_valid_and_correct() -> None:
    builder = _FakeBuilder("SELECT count(*) FROM tickets WHERE status = 'open'")
    executor = _FakeExecutor(["count"], [(3,)])
    case = _case(
        expected_rows_predicate=lambda rows: len(rows) == 1 and int(rows[0]["count"]) >= 0
    )

    summary = await run_sql_eval(
        cast(SqlBuilder, builder),
        cast(SqlExecutor, executor),
        [case],
        personas=(("Engineering", "employee"),),
    )

    assert summary.total == 1
    assert summary.valid == 1
    assert summary.correct == 1
    assert summary.results[0].row_count == 1


@pytest.fixture(scope="module")
def seeded() -> None:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL is not set")
    sync_engine = create_engine(DATABASE_URL)
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        sync_engine.dispose()
        pytest.skip("Postgres is not reachable")
    seed(sync_engine)
    sync_engine.dispose()


async def test_sql_eval_replays_keylessly_against_real_db(seeded: None) -> None:
    from app.eval.sql_eval import make_keyless_provider

    cases = build_sql_set()
    provider = make_keyless_provider(cases)
    from app.llm.models import load_models

    builder = SqlBuilder(provider, load_models().models["sql_builder"])
    engine = create_async_engine(DATABASE_URL)
    executor = SqlExecutor(engine)
    try:
        summary = await run_sql_eval(builder, executor, cases, personas=PERSONAS)
    finally:
        await engine.dispose()

    assert summary.total >= 40 * len(PERSONAS)
    assert summary.valid_rate == 1.0
    assert summary.correct_rate == 1.0
