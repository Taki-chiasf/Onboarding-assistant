"""Text-to-SQL evaluation replay.

Replays the golden SQL set through the builder, guard, and executor once per
persona, then grades each case for validity (the guard accepts the statement)
and correctness (the SQL matches its expected pattern and the executed rows
satisfy its predicate). Runs as a one-off command; the nightly scheduling lands
with the eval loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core.redact import redact_pii
from app.eval.sql_golden import PERSONAS, SqlCase, build_sql_set
from app.llm.provider import ChatMessage
from app.text_to_sql.builder import SqlBuilder
from app.text_to_sql.executor import SqlExecutor, SqlResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SqlCaseResult:
    prompt: str
    dept: str
    role: str
    valid: bool
    correct: bool
    sql: str | None
    error: str | None
    row_count: int


@dataclass(frozen=True)
class SqlEvalSummary:
    total: int
    valid: int
    correct: int
    results: list[SqlCaseResult]

    @property
    def valid_rate(self) -> float:
        return self.valid / self.total if self.total else 0.0

    @property
    def correct_rate(self) -> float:
        return self.correct / self.total if self.total else 0.0


def rows_to_dicts(result: SqlResult) -> list[dict[str, Any]]:
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]


def matches_pattern(case: SqlCase, sql: str) -> bool:
    return re.search(case.expected_sql_pattern, sql, re.IGNORECASE) is not None


def rows_satisfy(case: SqlCase, rows: list[dict[str, Any]]) -> bool:
    if case.expected_rows_predicate is None:
        return True
    return case.expected_rows_predicate(rows)


async def run_sql_eval(
    builder: SqlBuilder,
    executor: SqlExecutor,
    cases: list[SqlCase],
    personas: tuple[tuple[str, str], ...] = PERSONAS,
) -> SqlEvalSummary:
    results: list[SqlCaseResult] = []
    valid = 0
    correct = 0
    for case in cases:
        for dept, role in personas:
            if dept not in case.personas:
                continue
            try:
                built = await builder.build(case.prompt)
                result = await executor.execute(
                    built.sql,
                    dept=dept,
                    role=role,
                    principal=f"eval@{dept.lower()}.demo.example",
                )
                rows = rows_to_dicts(result)
                case_correct = matches_pattern(case, built.sql) and rows_satisfy(case, rows)
                valid += 1
                correct += int(case_correct)
                results.append(
                    SqlCaseResult(
                        prompt=case.prompt,
                        dept=dept,
                        role=role,
                        valid=True,
                        correct=case_correct,
                        sql=built.sql,
                        error=None,
                        row_count=len(rows),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a failing case must not abort the run
                results.append(
                    SqlCaseResult(
                        prompt=case.prompt,
                        dept=dept,
                        role=role,
                        valid=False,
                        correct=False,
                        sql=None,
                        error=str(exc),
                        row_count=0,
                    )
                )
    return SqlEvalSummary(total=len(results), valid=valid, correct=correct, results=results)


def question_from_messages(messages: Sequence[ChatMessage]) -> str:
    prefix = "Question: "
    for message in reversed(messages):
        if prefix in message.content:
            return message.content.split(prefix, 1)[1].strip()
    return ""


def make_keyless_provider(cases: list[SqlCase]) -> Any:
    from app.llm.fake import FakeProvider

    golden = {case.prompt: case.golden_sql for case in cases}

    def chat_fn(model: str, messages: Sequence[ChatMessage]) -> str:
        return golden.get(question_from_messages(messages), "")

    return FakeProvider(chat_fn=chat_fn)


async def _main() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings
    from app.llm.models import load_models

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to run the SQL eval")

    cases = build_sql_set()
    provider = make_keyless_provider(cases)
    builder = SqlBuilder(provider, load_models().models["sql_builder"])

    engine = create_async_engine(settings.database_url)
    executor = SqlExecutor(engine)
    try:
        summary = await run_sql_eval(builder, executor, cases)
    finally:
        await engine.dispose()

    logger.info(
        "sql eval: valid=%.2f correct=%.2f (%d/%d)",
        summary.valid_rate,
        summary.correct_rate,
        summary.correct,
        summary.total,
    )
    for result in summary.results:
        if not result.correct:
            logger.info(
                "fail: %s [%s/%s] %s",
                redact_pii(result.prompt),
                result.dept,
                result.role,
                redact_pii(result.error or ""),
            )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
