"""Nightly eval loop.

Replays the eval suites, records one run per case, compares the night's metrics
against the last green run at the same ``(prompt_version, model_version)`` pair,
files router misroutes for admin review, writes synthetic feedback when no real
feedback exists, tracks the consecutive green-night streak, and alerts a
webhook when the night is red or a metric regressed.

The suites and the comparison are deterministic and run keyless; the
model-quality numbers and the synthetic rating only become meaningful with a
provider that serves the real models.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.redact import redact_pii
from app.eval.baseline import Baseline, BaselineComparison, compare_to_baseline
from app.eval.eval_run import (
    build_report,
    collect_metrics,
    collect_sections,
    combined_versions,
    to_metric_sources,
)
from app.eval.gates import GATES, evaluate_gates
from app.eval.notify import build_alert, post_alert, summarize_failures
from app.eval.promoted import PromotedResult, replay_promoted_cases
from app.eval.rag_eval import AnswerCaseResult, AnswerEvalSummary, RetrievalEvalSummary
from app.eval.report import RunReport
from app.eval.router_eval import RouterCaseResult, RouterEvalSummary
from app.eval.security import NO_CONTEXT_KIND, RAG_KIND, SQL_KIND, SecuritySummary
from app.eval.sql_eval import SqlEvalSummary
from app.eval.suites import SuiteRun, run_suites
from app.models import EvalCase, EvalRun, Feedback, NightlyEvalRun

logger = logging.getLogger(__name__)

SUITE_ROUTER = "router"
SUITE_SQL = "sql"
SUITE_DOCS = "docs"
SUITE_PROMOTED = "promoted"

SOURCE_ROUTER_SET = "router_set"
SOURCE_SQL_SET = "sql_set"
SOURCE_DOCS_SET = "docs_set"
SOURCE_MISROUTE = "misroute"

GOLDEN_STATUS = "golden"
REVIEW_STATUS = "review"
PROMOTED_STATUS = "promoted"

# The synthetic-rating path stands in for real users pre-pilot; real feedback
# inside the window switches it off.
SYNTHETIC_WINDOW_DAYS = 7
MAX_MISROUTES_PER_RUN = 20


@dataclass(frozen=True)
class CanaryFlags:
    rls: bool | None
    injection: bool | None


@dataclass(frozen=True)
class NightlyMark:
    day: date
    passed: bool


@dataclass(frozen=True)
class NightlyOutcome:
    green: bool
    strict: bool
    keyless: bool
    streak: int
    cases_seeded: int
    runs_written: int
    promoted_total: int
    promoted_failed: int
    synthetic_feedback: int
    misroutes_filed: int
    alert: str | None
    notified: bool
    report: RunReport
    nightly_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "green": self.green,
            "strict": self.strict,
            "keyless": self.keyless,
            "streak": self.streak,
            "cases_seeded": self.cases_seeded,
            "runs_written": self.runs_written,
            "promoted": {"total": self.promoted_total, "failed": self.promoted_failed},
            "synthetic_feedback": self.synthetic_feedback,
            "misroutes_filed": self.misroutes_filed,
            "alert": self.alert,
            "notified": self.notified,
            "nightly_run_id": self.nightly_run_id,
            "report": self.report.to_dict(),
        }


def canary_flags(summary: SecuritySummary) -> CanaryFlags:
    access_kinds = (SQL_KIND, NO_CONTEXT_KIND, RAG_KIND)
    access = [result for result in summary.results if result.kind in access_kinds]
    injection = [result for result in summary.results if result.kind not in access_kinds]
    return CanaryFlags(
        rls=all(result.passed for result in access) if access else None,
        injection=all(result.passed for result in injection) if injection else None,
    )


def green_streak(marks: Sequence[NightlyMark]) -> int:
    """Consecutive calendar days with green runs, ending at the latest run day.

    A day with any red run is red, a missing day breaks the streak, and a red
    latest day means there is no current streak.
    """
    by_day: dict[date, bool] = {}
    for mark in marks:
        by_day[mark.day] = by_day.get(mark.day, True) and mark.passed
    if not by_day:
        return 0
    last = max(by_day)
    if not by_day[last]:
        return 0
    streak = 1
    cursor = last - timedelta(days=1)
    while by_day.get(cursor, False):
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def gates_ok(metrics: dict[str, float], *, strict: bool) -> bool:
    required = [gate.name for gate in GATES] if strict else None
    report = evaluate_gates(metrics, required=required)
    return report.passed if strict else report.evaluated_passed


def golden_case_rows(
    *,
    router_cases: Sequence[Any],
    sql_cases: Sequence[Any],
    docs_cases: Sequence[Any],
) -> list[EvalCase]:
    """The code-defined golden sets as eval-case rows.

    Rows mirror the serializable expectations; the code keeps the source of
    truth for anything not representable (e.g. callable row predicates).
    """
    rows: list[EvalCase] = []
    for case in router_cases:
        rows.append(
            EvalCase(
                id=uuid.uuid4(),
                prompt=case.prompt,
                expected_intent=case.expected_intent,
                tags=list(case.tags) or None,
                status=GOLDEN_STATUS,
                source=SOURCE_ROUTER_SET,
            )
        )
    for case in sql_cases:
        rows.append(
            EvalCase(
                id=uuid.uuid4(),
                prompt=case.prompt,
                expected_sql_pattern=case.expected_sql_pattern,
                tags=[f"dept:{dept}" for dept in case.personas],
                status=GOLDEN_STATUS,
                source=SOURCE_SQL_SET,
            )
        )
    for case in docs_cases:
        rows.append(
            EvalCase(
                id=uuid.uuid4(),
                prompt=case.prompt,
                expected_intent=getattr(case, "expected_intent", None),
                expected_source_ids=list(case.expected_source_ids),
                tags=list(case.tags) or None,
                status=GOLDEN_STATUS,
                source=SOURCE_DOCS_SET,
            )
        )
    return rows


async def seed_golden_cases(
    session: AsyncSession, rows: Sequence[EvalCase]
) -> tuple[dict[tuple[str, str], uuid.UUID], int]:
    sources = (SOURCE_ROUTER_SET, SOURCE_SQL_SET, SOURCE_DOCS_SET)
    existing = (
        (await session.execute(select(EvalCase).where(EvalCase.source.in_(sources))))
        .scalars()
        .all()
    )
    index: dict[tuple[str, str], uuid.UUID] = {
        (row.source or "", row.prompt): row.id for row in existing
    }
    seeded = 0
    for row in rows:
        key = (row.source or "", row.prompt)
        if key in index:
            continue
        session.add(row)
        index[key] = row.id
        seeded += 1
    await session.commit()
    return index, seeded


def router_run_rows(
    summary: RouterEvalSummary,
    index: dict[tuple[str, str], uuid.UUID],
    *,
    flags: CanaryFlags,
    prompt_version: str,
    model_version: str,
) -> list[EvalRun]:
    rows: list[EvalRun] = []
    for result in summary.results:
        case_id = index.get((SOURCE_ROUTER_SET, result.prompt))
        if case_id is None:
            continue
        rows.append(
            EvalRun(
                id=uuid.uuid4(),
                case_id=case_id,
                suite=SUITE_ROUTER,
                passed=result.correct,
                actual_intent=result.actual,
                router_confidence=result.confidence,
                diff=(
                    None
                    if result.correct
                    else result.error
                    or f"expected {result.expected}, got {result.actual or 'error'}"
                ),
                prompt_version=prompt_version,
                model_version=model_version,
                rls_canary_passed=flags.rls,
                injection_canary_passed=flags.injection,
            )
        )
    return rows


def sql_run_rows(
    summary: SqlEvalSummary,
    index: dict[tuple[str, str], uuid.UUID],
    *,
    flags: CanaryFlags,
    prompt_version: str,
    model_version: str,
) -> list[EvalRun]:
    rows: list[EvalRun] = []
    for result in summary.results:
        case_id = index.get((SOURCE_SQL_SET, result.prompt))
        if case_id is None:
            continue
        diff = result.error or summarize_failures(
            (("pattern", result.pattern_ok), ("rows", result.rows_ok))
        )
        rows.append(
            EvalRun(
                id=uuid.uuid4(),
                case_id=case_id,
                suite=SUITE_SQL,
                passed=result.valid and result.correct,
                persona=f"{result.dept}/{result.role}",
                generated_sql=result.sql,
                diff=diff,
                latency_ms=result.latency_ms,
                prompt_version=prompt_version,
                model_version=model_version,
                rls_canary_passed=flags.rls,
                injection_canary_passed=flags.injection,
            )
        )
    return rows


def docs_run_rows(
    retrieval: RetrievalEvalSummary | None,
    answer: AnswerEvalSummary | None,
    index: dict[tuple[str, str], uuid.UUID],
    *,
    flags: CanaryFlags,
    model_version: str,
) -> list[EvalRun]:
    retrieval_by_prompt = (
        {result.prompt: result for result in retrieval.results} if retrieval else {}
    )
    answer_by_prompt = {result.prompt: result for result in answer.results} if answer else {}
    prompts = list(retrieval_by_prompt) or list(answer_by_prompt)
    rows: list[EvalRun] = []
    for prompt in prompts:
        case_id = index.get((SOURCE_DOCS_SET, prompt))
        if case_id is None:
            continue
        recall_hit = retrieval_by_prompt[prompt].hit if prompt in retrieval_by_prompt else None
        judged = answer_by_prompt[prompt].judged_correct if prompt in answer_by_prompt else None
        checks = [check for check in (recall_hit, judged) if check is not None]
        passed = bool(checks) and all(checks)
        diff = None
        if not passed:
            diff = summarize_failures((("recall", recall_hit), ("judge", judged)))
        answer_result = answer_by_prompt.get(prompt)
        rows.append(
            EvalRun(
                id=uuid.uuid4(),
                case_id=case_id,
                suite=SUITE_DOCS,
                passed=passed,
                actual_answer=answer_result.answer if answer_result else None,
                retrieved_source_ids=(
                    list(retrieval_by_prompt[prompt].retrieved)
                    if prompt in retrieval_by_prompt
                    else None
                ),
                judge_passed=judged,
                diff=diff,
                cost_usd=(
                    Decimal(str(answer_result.cost_usd)) if answer_result is not None else None
                ),
                latency_ms=(
                    int(answer_result.latency_s * 1000) if answer_result is not None else None
                ),
                prompt_version=answer_result.prompt_version if answer_result else None,
                model_version=model_version,
                rls_canary_passed=flags.rls,
                injection_canary_passed=flags.injection,
            )
        )
    return rows


def promoted_run_rows(
    results: Sequence[PromotedResult],
    *,
    router_prompt_version: str,
    router_model: str,
    sql_prompt_version: str,
    sql_model: str,
) -> list[EvalRun]:
    rows: list[EvalRun] = []
    for result in results:
        if result.generated_sql is not None or result.sql_valid is not None:
            prompt_version, model_version = sql_prompt_version, sql_model
        elif result.intent_ok is not None:
            prompt_version, model_version = router_prompt_version, router_model
        else:
            prompt_version, model_version = None, None
        rows.append(
            EvalRun(
                id=uuid.uuid4(),
                case_id=result.case_id,
                suite=SUITE_PROMOTED,
                passed=result.passed,
                actual_intent=result.actual_intent,
                router_confidence=result.intent_confidence,
                retrieved_source_ids=list(result.retrieved_source_ids) or None,
                generated_sql=result.generated_sql,
                diff=summarize_failures(
                    (
                        ("intent", result.intent_ok),
                        ("retrieval", result.retrieval_hit),
                        ("sql_valid", result.sql_valid),
                        ("pattern", result.pattern_ok),
                        ("rows", result.rows_ok),
                    ),
                    error=result.error,
                ),
                prompt_version=prompt_version,
                model_version=model_version,
            )
        )
    return rows


def misroute_candidates(
    results: Sequence[RouterCaseResult],
    *,
    existing: set[tuple[str, str]],
    cap: int = MAX_MISROUTES_PER_RUN,
) -> list[EvalCase]:
    """Candidate eval cases for real misroutes, deduped against earlier filings."""
    seen = set(existing)
    candidates: list[EvalCase] = []
    for result in results:
        if result.correct or result.actual is None:
            continue
        key = (SOURCE_MISROUTE, result.prompt)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            EvalCase(
                id=uuid.uuid4(),
                prompt=redact_pii(result.prompt),
                expected_intent=result.expected,
                status=REVIEW_STATUS,
                source=SOURCE_MISROUTE,
                tags=["router", f"actual:{result.actual}"],
            )
        )
        if len(candidates) >= cap:
            break
    return candidates


def should_write_synthetic(real_volume: int) -> bool:
    return real_volume == 0


def synthetic_feedback_rows(
    results: Sequence[AnswerCaseResult], index: dict[tuple[str, str], uuid.UUID]
) -> list[Feedback]:
    rows: list[Feedback] = []
    for result in results:
        case_id = index.get((SOURCE_DOCS_SET, result.prompt))
        if case_id is None:
            continue
        rows.append(
            Feedback(
                id=uuid.uuid4(),
                case_id=case_id,
                rating="pass" if result.judged_correct else "fail",
                correction=None if result.judged_correct else result.judge_reason,
                source="synthetic",
            )
        )
    return rows


async def real_feedback_volume(session: AsyncSession, *, days: int = SYNTHETIC_WINDOW_DAYS) -> int:
    since = datetime.now(UTC) - timedelta(days=days)
    count = (
        await session.execute(
            select(func.count())
            .select_from(Feedback)
            .where(Feedback.source == "real", Feedback.created_at >= since)
        )
    ).scalar()
    return int(count or 0)


async def write_synthetic_feedback(session: AsyncSession, rows: Sequence[Feedback]) -> int:
    if not rows:
        return 0
    case_ids = [row.case_id for row in rows]
    # Refresh rather than accumulate: one stand-in verdict per case.
    await session.execute(
        delete(Feedback).where(Feedback.source == "synthetic", Feedback.case_id.in_(case_ids))
    )
    session.add_all(rows)
    await session.commit()
    return len(rows)


async def load_promoted_cases(session: AsyncSession) -> list[EvalCase]:
    return list(
        (
            await session.execute(
                select(EvalCase)
                .where(EvalCase.status == PROMOTED_STATUS)
                .order_by(EvalCase.created_at.asc())
            )
        )
        .scalars()
        .all()
    )


async def misroute_keys(session: AsyncSession) -> set[tuple[str, str]]:
    rows = (
        await session.execute(
            select(EvalCase.source, EvalCase.prompt).where(EvalCase.source == SOURCE_MISROUTE)
        )
    ).all()
    return {(source or "", prompt) for source, prompt in rows}


async def last_green_run(
    session: AsyncSession, *, prompt_version: str, model_version: str, keyless: bool
) -> NightlyEvalRun | None:
    return (
        await session.execute(
            select(NightlyEvalRun)
            .where(
                NightlyEvalRun.passed,
                NightlyEvalRun.prompt_version == prompt_version,
                NightlyEvalRun.model_version == model_version,
                NightlyEvalRun.keyless == keyless,
            )
            .order_by(NightlyEvalRun.run_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def nightly_marks(session: AsyncSession) -> list[NightlyMark]:
    rows = (await session.execute(select(NightlyEvalRun.run_at, NightlyEvalRun.passed))).all()
    return [
        NightlyMark(day=run_at.astimezone(UTC).date(), passed=passed) for run_at, passed in rows
    ]


def comparison_to_last_green(
    last_green: NightlyEvalRun | None,
    *,
    prompt_version: str,
    model_version: str,
    metrics: dict[str, float],
) -> BaselineComparison | None:
    if last_green is None:
        return None
    return compare_to_baseline(
        Baseline.capture(
            prompt_version=prompt_version, model_version=model_version, metrics=metrics
        ),
        Baseline.capture(
            prompt_version=last_green.prompt_version or "",
            model_version=last_green.model_version or "",
            metrics={name: float(value) for name, value in (last_green.metrics or {}).items()},
        ),
    )


@dataclass(frozen=True)
class Persistence:
    cases_seeded: int
    runs_written: int
    promoted: list[PromotedResult]
    synthetic_feedback: int
    misroutes_filed: int
    comparison: BaselineComparison | None
    streak: int
    green: bool
    nightly_run_id: str


async def persist_night(
    factory: async_sessionmaker[AsyncSession],
    run: SuiteRun,
    metrics: dict[str, float],
    *,
    strict: bool,
) -> Persistence:
    from app.eval.golden import build_golden_set
    from app.eval.router_golden import build_router_set
    from app.eval.sql_golden import build_sql_set

    prompt_version = combined_versions(run.prompt_versions)
    model_version = combined_versions(run.model_versions)
    async with factory() as session:
        rows = golden_case_rows(
            router_cases=build_router_set(),
            sql_cases=build_sql_set(),
            docs_cases=build_golden_set(),
        )
        index, seeded = await seed_golden_cases(session, rows)
        flags = canary_flags(run.security_summary)

        run_rows = router_run_rows(
            run.router_summary,
            index,
            flags=flags,
            prompt_version=run.prompt_versions["router"],
            model_version=run.model_versions["router"],
        )
        if run.sql_summary is not None:
            run_rows.extend(
                sql_run_rows(
                    run.sql_summary,
                    index,
                    flags=flags,
                    prompt_version=run.prompt_versions["sql_builder"],
                    model_version=run.model_versions["sql_builder"],
                )
            )
        if run.retrieval_summary is not None or run.answer_summary is not None:
            run_rows.extend(
                docs_run_rows(
                    run.retrieval_summary,
                    run.answer_summary,
                    index,
                    flags=flags,
                    model_version=run.model_versions["grounding"],
                )
            )

        promoted: list[PromotedResult] = []
        if not run.keyless:
            promoted = await replay_promoted_cases(
                await load_promoted_cases(session),
                router=run.router,
                retriever=run.retriever,
                builder=run.builder,
                executor=run.executor,
            )
            run_rows.extend(
                promoted_run_rows(
                    promoted,
                    router_prompt_version=run.prompt_versions["router"],
                    router_model=run.model_versions["router"],
                    sql_prompt_version=run.prompt_versions["sql_builder"],
                    sql_model=run.model_versions["sql_builder"],
                )
            )
        if run_rows:
            session.add_all(run_rows)
            await session.commit()

        synthetic_written = 0
        if run.answer_summary is not None and not run.keyless:
            if should_write_synthetic(await real_feedback_volume(session)):
                synthetic_written = await write_synthetic_feedback(
                    session, synthetic_feedback_rows(run.answer_summary.results, index)
                )

        misroutes_filed = 0
        if not run.keyless:
            candidates = misroute_candidates(
                run.router_summary.results, existing=await misroute_keys(session)
            )
            if candidates:
                session.add_all(candidates)
                await session.commit()
            misroutes_filed = len(candidates)

        last_green = await last_green_run(
            session,
            prompt_version=prompt_version,
            model_version=model_version,
            keyless=run.keyless,
        )
        comparison = comparison_to_last_green(
            last_green,
            prompt_version=prompt_version,
            model_version=model_version,
            metrics=metrics,
        )
        promoted_failed = sum(1 for result in promoted if not result.passed)
        green = (
            gates_ok(metrics, strict=strict)
            and (comparison is None or comparison.ok)
            and promoted_failed == 0
        )
        marks = await nightly_marks(session)
        marks.append(NightlyMark(day=datetime.now(UTC).date(), passed=green))
        streak = green_streak(marks)

        nightly = NightlyEvalRun(
            id=uuid.uuid4(),
            passed=green,
            strict=strict,
            keyless=run.keyless,
            prompt_version=prompt_version,
            model_version=model_version,
            metrics={name: float(value) for name, value in metrics.items()},
            sections=collect_sections(to_metric_sources(run)),
            regressions=[delta.name for delta in (comparison.regressions if comparison else [])],
            streak=streak,
        )
        session.add(nightly)
        await session.commit()

    return Persistence(
        cases_seeded=seeded,
        runs_written=len(run_rows),
        promoted=promoted,
        synthetic_feedback=synthetic_written,
        misroutes_filed=misroutes_filed,
        comparison=comparison,
        streak=streak,
        green=green,
        nightly_run_id=str(nightly.id),
    )


async def run_nightly(
    *, keyless: bool = False, strict: bool = False, engine: AsyncEngine | None = None
) -> NightlyOutcome:
    settings = get_settings()
    owns_engine = engine is None and bool(settings.database_url)
    active_engine = engine
    if active_engine is None and settings.database_url:
        active_engine = create_async_engine(settings.database_url)
    try:
        run = await run_suites(force_keyless=keyless, engine=active_engine)
        sources = to_metric_sources(run)
        metrics = collect_metrics(sources)

        if active_engine is not None:
            factory = async_sessionmaker(active_engine, expire_on_commit=False)
            persistence = await persist_night(factory, run, metrics, strict=strict)
        else:
            logger.warning("no database configured: the nightly ran without persistence")
            persistence = None

        comparison = persistence.comparison if persistence else None
        report = build_report(
            sources=sources,
            prompt_versions=run.prompt_versions,
            model_versions=run.model_versions,
            baseline=comparison,
            required=[gate.name for gate in GATES] if strict else None,
        )
        green = persistence.green if persistence else gates_ok(metrics, strict=strict)

        promoted_total = len(persistence.promoted) if persistence else 0
        promoted_failed = (
            sum(1 for result in persistence.promoted if not result.passed) if persistence else 0
        )
        streak = persistence.streak if persistence else 0
        alert = build_alert(
            green=green,
            keyless=run.keyless,
            streak=streak,
            report=report,
            regression=comparison,
            promoted_total=promoted_total,
            promoted_failed=promoted_failed,
        )
        notified = False
        if alert is not None and settings.slack_eval_webhook_url:
            notified = await post_alert(settings.slack_eval_webhook_url, alert)

        return NightlyOutcome(
            green=green,
            strict=strict,
            keyless=run.keyless,
            streak=streak,
            cases_seeded=persistence.cases_seeded if persistence else 0,
            runs_written=persistence.runs_written if persistence else 0,
            promoted_total=promoted_total,
            promoted_failed=promoted_failed,
            synthetic_feedback=persistence.synthetic_feedback if persistence else 0,
            misroutes_filed=persistence.misroutes_filed if persistence else 0,
            alert=alert,
            notified=notified,
            report=report,
            nightly_run_id=persistence.nightly_run_id if persistence else None,
        )
    finally:
        if owns_engine and active_engine is not None:
            await active_engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the nightly eval loop")
    parser.add_argument("--keyless", action="store_true", help="force the fake provider")
    parser.add_argument("--strict", action="store_true", help="require every gate to be evaluated")
    parser.add_argument("--json", help="write the outcome JSON to this path instead of stdout")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    outcome = asyncio.run(run_nightly(keyless=args.keyless, strict=args.strict))
    payload = json.dumps(outcome.to_dict(), indent=2, sort_keys=True)
    if args.json:
        Path(args.json).write_text(payload, encoding="utf-8")
    else:
        print(payload)

    for gate in outcome.report.gates.outcomes:
        status = "ok" if gate.passed else "FAIL"
        logger.info(
            "%-28s %-4s %.4f (target %s %.4f)",
            gate.name,
            status,
            gate.value,
            gate.direction,
            gate.target,
        )
    for name in outcome.report.gates.missing:
        logger.warning("gate not evaluated: %s", name)
    logger.info(
        "nightly: green=%s streak=%d seeded=%d runs=%d promoted=%d/%d synthetic=%d misroutes=%d",
        outcome.green,
        outcome.streak,
        outcome.cases_seeded,
        outcome.runs_written,
        outcome.promoted_total - outcome.promoted_failed,
        outcome.promoted_total,
        outcome.synthetic_feedback,
        outcome.misroutes_filed,
    )
    if outcome.alert:
        logger.warning("alert:\n%s", outcome.alert)
    return 0 if outcome.green else 1


if __name__ == "__main__":
    raise SystemExit(main())
