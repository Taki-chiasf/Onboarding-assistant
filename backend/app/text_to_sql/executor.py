"""Scoped read-only SQL execution.

Every query runs inside a single transaction that sets the caller's department
and role as transaction-local settings (via ``set_config(..., true)``, the
parameterized equivalent of ``SET LOCAL``), drops to the read-only database
role, and applies a statement timeout. The transaction-local settings are the
whole point: a session-level setting would leak across pooled connections. Rows
are capped and every execution is written to the audit log.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.text_to_sql.guard import validate_query

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

ACTION_SQL_QUERY = "sql_query"


@dataclass(frozen=True)
class SqlResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool
    latency_ms: int


class SqlExecutor:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        readonly_role: str = "app_readonly",
        statement_timeout_ms: int = 5000,
        max_rows: int = 100,
    ) -> None:
        if not _IDENTIFIER.match(readonly_role):
            raise ValueError(f"invalid read-only role name: {readonly_role!r}")
        self._engine = engine
        self._readonly_role = readonly_role
        self._timeout_ms = statement_timeout_ms
        self._max_rows = max_rows

    async def execute(
        self,
        sql: str,
        *,
        dept: str,
        role: str,
        principal: str,
        trace_id: str | None = None,
    ) -> SqlResult:
        validate_query(sql)

        started = perf_counter()
        async with self._engine.connect() as conn:
            async with conn.begin():
                await conn.execute(
                    text("SELECT set_config('app.principal_dept', :dept, true)"),
                    {"dept": dept},
                )
                await conn.execute(
                    text("SELECT set_config('app.principal_role', :role, true)"),
                    {"role": role},
                )
                await conn.execute(text(f"SET LOCAL ROLE {self._readonly_role}"))
                await conn.execute(
                    text("SELECT set_config('statement_timeout', :ms, true)"),
                    {"ms": str(self._timeout_ms)},
                )
                result = await conn.execute(text(sql))
                columns = list(result.keys())
                rows = [tuple(row) for row in result.fetchmany(self._max_rows + 1)]

            truncated = len(rows) > self._max_rows
            rows = rows[: self._max_rows]
            latency_ms = int((perf_counter() - started) * 1000)

            async with conn.begin():
                await conn.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(principal, action, target, trace_id, detail) "
                        "VALUES (:principal, :action, :target, :trace_id, "
                        "CAST(:detail AS JSONB))"
                    ),
                    {
                        "principal": principal,
                        "action": ACTION_SQL_QUERY,
                        "target": None,
                        "trace_id": trace_id,
                        "detail": json.dumps(
                            {
                                "query": sql,
                                "rows": len(rows),
                                "truncated": truncated,
                                "latency_ms": latency_ms,
                            }
                        ),
                    },
                )

        return SqlResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
            latency_ms=latency_ms,
        )
