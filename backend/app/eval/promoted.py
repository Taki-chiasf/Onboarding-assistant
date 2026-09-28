"""Replay of admin-promoted eval cases.

A promoted case carries the expectations filled in at review time: an expected
intent, expected source ids, and/or a SQL pattern with an optional row
predicate. Every check the case declares is replayed against the same wiring
the golden suites use; the case passes when all of them pass. A check whose
component is unavailable (no retriever without an ingested corpus) fails
instead of silently passing.
"""

from __future__ import annotations

import logging
import operator
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.eval.golden import recall_at_k
from app.eval.sql_eval import rows_to_dicts

if TYPE_CHECKING:
    from app.models import EvalCase
    from app.rag.retrieval import Retriever
    from app.router.router import IntentRouter
    from app.text_to_sql.builder import SqlBuilder
    from app.text_to_sql.executor import SqlExecutor

logger = logging.getLogger(__name__)

DEFAULT_DEPT = "Engineering"
DEFAULT_ROLE = "employee"

_COUNT_RE = re.compile(r"^count\s*(>=|<=|==|!=|>|<|=)\s*(\d+)$")
_COLUMN_RE = re.compile(r"^(all|any):([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

_COMPARISONS: dict[str, Callable[[int, int], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "=": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    "<": operator.lt,
}


def persona_from_tags(tags: Sequence[str] | None) -> tuple[str, str]:
    dept, role = DEFAULT_DEPT, DEFAULT_ROLE
    for tag in tags or ():
        if tag.startswith("dept:") and tag[len("dept:") :]:
            dept = tag[len("dept:") :]
        elif tag.startswith("role:") and tag[len("role:") :]:
            role = tag[len("role:") :]
    return dept, role


def matches_predicate(predicate: str, rows: Sequence[dict[str, Any]]) -> bool:
    """Evaluate the small row-predicate grammar an admin can attach to a case.

    ``count <op> N`` checks the row count; ``all:<column>=<value>`` requires
    every row to carry the value and ``any:<column>=<value>`` at least one.
    """
    text = predicate.strip()
    count_match = _COUNT_RE.match(text)
    if count_match:
        op, raw = count_match.groups()
        return _COMPARISONS[op](len(rows), int(raw))
    column_match = _COLUMN_RE.match(text)
    if column_match:
        mode, column, value = column_match.groups()
        present = [str(row.get(column)) == value for row in rows]
        return all(present) if mode == "all" else any(present)
    raise ValueError(f"unsupported rows predicate: {predicate!r}")


@dataclass(frozen=True)
class PromotedResult:
    case_id: uuid.UUID
    prompt: str
    intent_ok: bool | None = None
    actual_intent: str | None = None
    intent_confidence: float | None = None
    retrieval_hit: bool | None = None
    retrieved_source_ids: tuple[str, ...] = ()
    sql_valid: bool | None = None
    pattern_ok: bool | None = None
    rows_ok: bool | None = None
    generated_sql: str | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        checks = [
            check
            for check in (
                self.intent_ok,
                self.retrieval_hit,
                self.sql_valid,
                self.pattern_ok,
                self.rows_ok,
            )
            if check is not None
        ]
        return bool(checks) and all(checks)


async def replay_case(
    case: EvalCase,
    *,
    router: IntentRouter,
    retriever: Retriever | None,
    builder: SqlBuilder | None,
    executor: SqlExecutor | None,
) -> PromotedResult:
    dept, role = persona_from_tags(case.tags)
    intent_ok: bool | None = None
    actual_intent: str | None = None
    confidence: float | None = None
    retrieval_hit: bool | None = None
    retrieved: tuple[str, ...] = ()
    sql_valid: bool | None = None
    pattern_ok: bool | None = None
    rows_ok: bool | None = None
    generated_sql: str | None = None
    error: str | None = None
    phase = "intent"

    try:
        if case.expected_intent:
            decision = await router.decide(case.prompt)
            actual_intent = decision.intent.value
            confidence = decision.confidence
            intent_ok = actual_intent == case.expected_intent

        if case.expected_source_ids:
            phase = "retrieval"
            if retriever is None:
                retrieval_hit = False
                error = "retriever unavailable: the corpus is not ingested"
            else:
                chunks = await retriever.retrieve(case.prompt, dept=dept, role=role)
                retrieved = tuple(chunk.id for chunk in chunks)
                retrieval_hit = recall_at_k(list(case.expected_source_ids), list(retrieved), k=5)

        if case.expected_sql_pattern:
            phase = "sql"
            if builder is None or executor is None:
                sql_valid = False
                error = "sql replay unavailable without a database engine"
            else:
                built = await builder.build(case.prompt)
                generated_sql = built.sql
                result = await executor.execute(
                    generated_sql,
                    dept=dept,
                    role=role,
                    principal=f"promoted@{dept.lower()}.demo.example",
                )
                sql_valid = True
                pattern_ok = (
                    re.search(case.expected_sql_pattern, generated_sql, re.IGNORECASE) is not None
                )
                if case.expected_rows_predicate:
                    rows_ok = matches_predicate(case.expected_rows_predicate, rows_to_dicts(result))
    except Exception as exc:  # noqa: BLE001 - a failing case must not abort the replay
        error = f"{type(exc).__name__}: {exc}"
        if phase == "intent":
            intent_ok = False
        elif phase == "retrieval":
            retrieval_hit = False
        else:
            sql_valid = False

    return PromotedResult(
        case_id=case.id,
        prompt=case.prompt,
        intent_ok=intent_ok,
        actual_intent=actual_intent,
        intent_confidence=confidence,
        retrieval_hit=retrieval_hit,
        retrieved_source_ids=retrieved,
        sql_valid=sql_valid,
        pattern_ok=pattern_ok,
        rows_ok=rows_ok,
        generated_sql=generated_sql,
        error=error,
    )


async def replay_promoted_cases(
    cases: Sequence[EvalCase],
    *,
    router: IntentRouter,
    retriever: Retriever | None,
    builder: SqlBuilder | None,
    executor: SqlExecutor | None,
) -> list[PromotedResult]:
    results: list[PromotedResult] = []
    for case in cases:
        results.append(
            await replay_case(
                case, router=router, retriever=retriever, builder=builder, executor=executor
            )
        )
    return results
