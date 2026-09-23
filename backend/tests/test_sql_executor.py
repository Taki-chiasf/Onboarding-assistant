import json
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.text_to_sql.executor import SqlExecutor
from app.text_to_sql.guard import SqlGuardError


class _FakeResult:
    def __init__(self, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
        self._columns = columns
        self._rows = rows

    def keys(self) -> list[str]:
        return self._columns

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        return self._rows[:size]


class _FakeTransaction:
    def __init__(self, conn: "_FakeConnection") -> None:
        self._conn = conn

    async def __aenter__(self) -> "_FakeTransaction":
        self._conn.transactions.append("begin")
        return self

    async def __aexit__(self, *args: object) -> bool:
        self._conn.transactions.append("end")
        return False


class _FakeConnection:
    def __init__(self, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
        self._columns = columns
        self._rows = rows
        self.statements: list[tuple[str, dict[str, Any] | None]] = []
        self.transactions: list[str] = []

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    async def execute(
        self, statement: object, params: dict[str, Any] | None = None
    ) -> _FakeResult | None:
        sql = str(statement)
        self.statements.append((sql, params))
        if (sql.startswith("SELECT") or sql.startswith("WITH")) and "set_config" not in sql:
            return _FakeResult(self._columns, self._rows)
        return None

    async def __aenter__(self) -> "_FakeConnection":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class _FakeEngine:
    def __init__(self, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
        self._columns = columns
        self._rows = rows
        self.connection = _FakeConnection(columns, rows)

    def connect(self) -> _FakeConnection:
        return self.connection


def _engine(rows: list[tuple[Any, ...]]) -> _FakeEngine:
    return _FakeEngine(["id", "name"], rows)


def _sqls(engine: _FakeEngine) -> list[str]:
    return [sql for sql, _ in engine.connection.statements]


async def test_execute_sets_local_context_in_order() -> None:
    engine = _engine([(1, "Ada")])
    executor = SqlExecutor(cast(AsyncEngine, engine))
    result = await executor.execute(
        "SELECT id, name FROM org_members",
        dept="Engineering",
        role="employee",
        principal="ada@engineering.demo.example",
    )

    assert result.columns == ["id", "name"]
    assert result.rows == [(1, "Ada")]
    assert result.truncated is False

    sqls = _sqls(engine)
    assert sqls[0] == "SELECT set_config('app.principal_dept', :dept, true)"
    assert sqls[1] == "SELECT set_config('app.principal_role', :role, true)"
    assert sqls[2] == "SET LOCAL ROLE app_readonly"
    assert sqls[3] == "SELECT set_config('statement_timeout', :ms, true)"
    assert sqls[4] == "SELECT id, name FROM org_members"
    assert any(sql.startswith("INSERT INTO audit_logs") for sql in sqls)
    assert all("SET " not in sql or "SET LOCAL" in sql for sql in sqls)


async def test_execute_uses_only_transaction_local_set() -> None:
    engine = _engine([(1, "Ada")])
    executor = SqlExecutor(cast(AsyncEngine, engine))
    await executor.execute(
        "SELECT 1", dept="Engineering", role="employee", principal="ada@example.com"
    )

    plain_sets = [s for s in _sqls(engine) if s.startswith("SET ") and "SET LOCAL" not in s]
    assert plain_sets == []


async def test_execute_rejects_before_touching_db() -> None:
    engine = _engine([])
    executor = SqlExecutor(cast(AsyncEngine, engine))
    with pytest.raises(SqlGuardError):
        await executor.execute(
            "DROP TABLE org_members", dept="Engineering", role="employee", principal="x"
        )
    assert engine.connection.statements == []


async def test_execute_caps_rows_and_flags_truncation() -> None:
    rows = [(i, f"name-{i}") for i in range(102)]
    engine = _engine(rows)
    executor = SqlExecutor(cast(AsyncEngine, engine), max_rows=100)
    result = await executor.execute(
        "SELECT id, name FROM org_members", dept="Engineering", role="employee", principal="x"
    )

    assert result.truncated is True
    assert len(result.rows) == 100


async def test_execute_audits_query_and_metrics() -> None:
    engine = _engine([(1, "Ada")])
    executor = SqlExecutor(cast(AsyncEngine, engine))
    await executor.execute(
        "SELECT id, name FROM org_members",
        dept="Engineering",
        role="employee",
        principal="ada@engineering.demo.example",
        trace_id="abc123",
    )

    audit = next(
        (params for sql, params in engine.connection.statements if "INSERT INTO audit_logs" in sql),
        None,
    )
    assert audit is not None
    assert audit["principal"] == "ada@engineering.demo.example"
    assert audit["action"] == "sql_query"
    assert audit["trace_id"] == "abc123"
    detail = json.loads(audit["detail"])
    assert detail["query"] == "SELECT id, name FROM org_members"
    assert detail["rows"] == 1


def test_rejects_unsafe_role_name() -> None:
    engine = _engine([])
    with pytest.raises(ValueError):
        SqlExecutor(cast(AsyncEngine, engine), readonly_role="app; DROP ROLE app")
