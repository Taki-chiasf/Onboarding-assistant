"""Row-level security canary tests.

These run against a real Postgres (seeded via the demo data script) and are
skipped when no database is reachable, which keeps the default offline test
run green. They assert the security property the whole query layer depends on:
a caller only sees rows in their own department, and the department context is
transaction-scoped rather than connection-scoped.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.text_to_sql.executor import SqlExecutor
from scripts.seed import seed

DATABASE_URL = os.environ.get("DATABASE_URL") or ""
PGBOUNCER_URL = os.environ.get("PGBOUNCER_URL") or ""


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


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest.fixture
async def executor(engine: AsyncEngine) -> SqlExecutor:
    return SqlExecutor(engine)


async def test_employee_sees_only_own_department(seeded: None, executor: SqlExecutor) -> None:
    result = await executor.execute(
        "SELECT dept FROM org_members",
        dept="Engineering",
        role="employee",
        principal="ada@engineering.demo.example",
    )
    assert result.rows
    assert {dept for (dept,) in result.rows} == {"Engineering"}


async def test_cross_department_canary_returns_zero_rows(
    seeded: None, executor: SqlExecutor
) -> None:
    result = await executor.execute(
        "SELECT * FROM org_members WHERE dept = 'Finance'",
        dept="Engineering",
        role="employee",
        principal="ada@engineering.demo.example",
    )
    assert result.rows == []


async def test_admin_sees_every_department(seeded: None, engine: AsyncEngine) -> None:
    executor = SqlExecutor(engine, max_rows=500)
    result = await executor.execute(
        "SELECT dept FROM org_members",
        dept="People",
        role="admin",
        principal="jordan.lee@people.demo.example",
    )
    assert len(result.rows) == 120
    assert {dept for (dept,) in result.rows} == {
        "Engineering",
        "People",
        "Finance",
        "Sales",
        "Marketing",
        "Design",
        "Support",
        "Legal",
    }


async def test_deny_by_default_without_context(seeded: None, engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SET LOCAL ROLE app_readonly"))
            result = await conn.execute(text("SELECT * FROM org_members"))
            assert result.fetchall() == []


async def test_no_view_leaks_unassigned_rows_without_context(
    seeded: None, engine: AsyncEngine
) -> None:
    """Unassigned rows are shared, but only once a principal context exists."""
    views = ("org_members", "projects", "assets", "okrs", "tickets")
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SET LOCAL ROLE app_readonly"))
            for view in views:
                count = (await conn.execute(text(f"SELECT count(*) FROM {view}"))).scalar_one()
                assert count == 0, f"{view} leaked {count} rows without context"


async def test_unassigned_rows_are_shared_with_a_context(
    seeded: None, executor: SqlExecutor
) -> None:
    """The share branch stays available to an authenticated caller."""
    result = await executor.execute(
        "SELECT count(*) AS available FROM assets WHERE assignee_email IS NULL",
        dept="Engineering",
        role="employee",
        principal="ada@engineering.demo.example",
    )
    assert result.rows[0][0] > 0


async def test_idp_claims_drive_row_level_security(seeded: None, engine: AsyncEngine) -> None:
    """A principal mapped from IdP claims is scoped by RLS end to end."""
    from app.auth.claims import principal_from_claims

    executor = SqlExecutor(engine, max_rows=500)
    employee = principal_from_claims(
        {
            "sub": "auth0|u1",
            "email": "ada@engineering.demo.example",
            "dept": "Engineering",
            "role": "employee",
        },
        dept_claim="dept",
        role_claim="role",
        email_claim="email",
    ).principal

    own = await executor.execute(
        "SELECT dept FROM org_members",
        dept=employee.dept,
        role=employee.role,
        principal=employee.email,
    )
    assert {dept for (dept,) in own.rows} == {"Engineering"}

    cross = await executor.execute(
        "SELECT * FROM org_members WHERE dept = 'Finance'",
        dept=employee.dept,
        role=employee.role,
        principal=employee.email,
    )
    assert cross.rows == []

    admin = principal_from_claims(
        {"sub": "auth0|hr", "dept": "People", "role": "admin"},
        dept_claim="dept",
        role_claim="role",
        email_claim="email",
    ).principal
    everything = await executor.execute(
        "SELECT dept FROM org_members",
        dept=admin.dept,
        role=admin.role,
        principal=admin.email,
    )
    assert len(everything.rows) == 120


async def test_department_context_is_transaction_scoped(seeded: None, engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SET LOCAL ROLE app_readonly"))
            await conn.execute(text("SET LOCAL app.principal_dept = 'Engineering'"))
            await conn.execute(text("SET LOCAL app.principal_role = 'employee'"))
            first = await conn.execute(text("SELECT dept FROM org_members"))
            assert {dept for (dept,) in first.fetchall()} == {"Engineering"}

        async with conn.begin():
            await conn.execute(text("SET LOCAL ROLE app_readonly"))
            second = await conn.execute(text("SELECT dept FROM org_members"))
            assert second.fetchall() == []


@pytest.mark.skipif(not PGBOUNCER_URL, reason="PGBOUNCER_URL is not set")
async def test_cross_department_canary_through_pgbouncer(seeded: None) -> None:
    engine = create_async_engine(PGBOUNCER_URL)
    executor = SqlExecutor(engine)
    try:
        result = await executor.execute(
            "SELECT * FROM org_members WHERE dept = 'Finance'",
            dept="Engineering",
            role="employee",
            principal="ada@engineering.demo.example",
        )
        assert result.rows == []
    finally:
        await engine.dispose()
