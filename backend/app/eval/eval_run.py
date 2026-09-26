"""Eval-run orchestration and command line.

Runs the suites it can reach from the current environment, merges their
summaries into one set of named metrics, grades them against the gates, and
optionally compares to a locked baseline. The metric collection is kept free of
I/O so it can be unit-tested without a database or a model; the CLI wires the
real (or keyless) provider to it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

from app.eval.baseline import (
    Baseline,
    BaselineComparison,
    compare_to_baseline,
    load_baseline,
    save_baseline,
)
from app.eval.gates import GATES
from app.eval.rag_eval import AnswerEvalSummary
from app.eval.report import (
    RunReport,
    dont_know_metric,
    judge_metric,
    latency_metrics,
    retrieval_metrics,
    router_metrics,
    security_metrics,
    sql_metrics,
)
from app.eval.router_eval import RouterEvalSummary
from app.eval.security import SecuritySummary
from app.eval.sql_eval import SqlEvalSummary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetricSources:
    router: RouterEvalSummary | None = None
    sql: SqlEvalSummary | None = None
    security: SecuritySummary | None = None
    recall_at_5: float | None = None
    answer_latencies_s: Sequence[float] = field(default_factory=tuple)
    first_token_latencies_s: Sequence[float] = field(default_factory=tuple)
    costs_usd: Sequence[float] = field(default_factory=tuple)
    judge_verdicts: Sequence[bool] = field(default_factory=tuple)
    answers: Sequence[str] = field(default_factory=tuple)


def collect_metrics(sources: MetricSources) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if sources.router is not None:
        metrics.update(router_metrics(sources.router))
    if sources.sql is not None:
        metrics.update(sql_metrics(sources.sql))
    if sources.security is not None:
        metrics.update(security_metrics(sources.security))
    if sources.recall_at_5 is not None:
        metrics.update(retrieval_metrics(sources.recall_at_5))
    metrics.update(
        latency_metrics(
            answer_latencies_s=sources.answer_latencies_s,
            first_token_latencies_s=sources.first_token_latencies_s,
            costs_usd=sources.costs_usd,
        )
    )
    metrics.update(judge_metric(sources.judge_verdicts))
    metrics.update(dont_know_metric(sources.answers))
    return metrics


def collect_sections(sources: MetricSources) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    if sources.router is not None:
        sections["router"] = {
            "accuracy": sources.router.accuracy,
            "total": sources.router.total,
            "by_intent": sources.router.by_intent(),
            "ambiguous_boundary": sources.router.ambiguous_boundary(),
        }
    if sources.sql is not None:
        sections["sql"] = {
            "valid_rate": sources.sql.valid_rate,
            "correct_rate": sources.sql.correct_rate,
            "total": sources.sql.total,
        }
    if sources.security is not None:
        sections["security"] = {
            "pass_rate": sources.security.pass_rate,
            "by_kind": sources.security.by_kind(),
        }
    return sections


def build_report(
    *,
    sources: MetricSources,
    prompt_versions: dict[str, str],
    model_versions: dict[str, str],
    baseline: BaselineComparison | None = None,
    required: Sequence[str] | None = None,
) -> RunReport:
    return RunReport.build(
        metrics=collect_metrics(sources),
        prompt_versions=prompt_versions,
        model_versions=model_versions,
        baseline=baseline,
        required=required,
        sections=collect_sections(sources),
    )


def combined_versions(versions: dict[str, str]) -> str:
    return "+".join(sorted(versions.values())) if versions else "unknown"


async def _corpus_ready(engine: AsyncEngine) -> bool:
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            count = (await conn.execute(text("SELECT count(*) FROM doc_chunks"))).scalar()
    except Exception:  # noqa: BLE001 - a missing table just means "not ingested yet"
        return False
    return bool(count)


async def _run_suites(
    args: argparse.Namespace,
) -> tuple[MetricSources, dict[str, str], dict[str, str]]:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings
    from app.eval.router_golden import build_router_set
    from app.eval.security import run_security_canaries
    from app.eval.sql_golden import PERSONAS, build_sql_set
    from app.llm.client import get_provider
    from app.llm.fake import FakeProvider
    from app.llm.models import load_models
    from app.rag.retrieval import Retriever
    from app.router.router import IntentRouter
    from app.text_to_sql.builder import SqlBuilder
    from app.text_to_sql.executor import SqlExecutor

    settings = get_settings()
    models = load_models()
    keyless = args.keyless or not settings.mistral_api_key
    if keyless:
        logger.warning("running keyless: model-quality metrics are pipeline smoke tests only")

    from app.eval.router_eval import make_keyless_provider as router_keyless
    from app.eval.router_eval import run_router_eval
    from app.eval.sql_eval import make_keyless_provider as sql_keyless
    from app.eval.sql_eval import run_sql_eval

    router_cases = build_router_set()
    sql_cases = build_sql_set()

    provider = FakeProvider() if keyless else get_provider()
    router_provider = router_keyless(router_cases) if keyless else provider
    router = IntentRouter(router_provider, models.models["router"])
    router_summary = await run_router_eval(router, router_cases)

    from app.prompts.loader import prompt_version

    prompt_versions = {
        "router": router.prompt_version,
        "sql_builder": prompt_version("sql_builder"),
        "sql_summarize": prompt_version("sql_summarize"),
    }
    model_versions = {
        "router": provider.effective_model(models.models["router"]),
        "sql_builder": provider.effective_model(models.models["sql_builder"]),
        "grounding": provider.effective_model(models.models["grounding"]),
        "judge": provider.effective_model(models.models["judge"]),
    }

    sql_summary: SqlEvalSummary | None = None
    security_summary: SecuritySummary | None = None
    answer_summary: AnswerEvalSummary | None = None
    recall: float | None = None

    if settings.database_url:
        engine = create_async_engine(settings.database_url)
        try:
            sql_builder = SqlBuilder(
                sql_keyless(sql_cases) if keyless else provider, models.models["sql_builder"]
            )
            executor = SqlExecutor(
                engine,
                readonly_role=settings.sql_readonly_role,
                statement_timeout_ms=settings.sql_statement_timeout_ms,
                max_rows=settings.sql_max_rows,
            )
            sql_summary = await run_sql_eval(sql_builder, executor, sql_cases, personas=PERSONAS)

            embed_provider = provider if not keyless else FakeProvider()

            async def embed(texts: list[str]) -> list[list[float]]:
                return await embed_provider.embed(models.models["embed"], texts)

            corpus_ready = await _corpus_ready(engine)
            retriever = Retriever(engine, embed) if corpus_ready else None
            security_summary = await run_security_canaries(
                router=router, executor=executor, retriever=retriever
            )
            if retriever is not None and not keyless:
                from app.eval.golden import build_golden_set
                from app.eval.rag_eval import run_answer_eval, run_retrieval_eval

                golden = build_golden_set()
                retrieval = await run_retrieval_eval(retriever, golden)
                recall = retrieval.recall_at_5
                answer_summary = await run_answer_eval(retriever, provider, models, golden)
        finally:
            await engine.dispose()
    else:
        security_summary = await run_security_canaries(router=router)
        logger.warning("DATABASE_URL is not set: skipping SQL and retrieval suites")

    sources = MetricSources(
        router=router_summary,
        sql=sql_summary,
        security=security_summary,
        recall_at_5=recall,
        answer_latencies_s=answer_summary.latencies_s if answer_summary else (),
        first_token_latencies_s=(
            answer_summary.first_token_latencies_s if answer_summary else ()
        ),
        costs_usd=answer_summary.costs_usd if answer_summary else (),
        judge_verdicts=answer_summary.judge_verdicts if answer_summary else (),
        answers=answer_summary.answers if answer_summary else (),
    )
    return sources, prompt_versions, model_versions


async def _main_async(args: argparse.Namespace) -> int:
    sources, prompt_versions, model_versions = await _run_suites(args)

    baseline_comparison: BaselineComparison | None = None
    baseline_file = args.baseline
    if baseline_file:
        path = Path(baseline_file)
        if path.exists():
            baseline_comparison = compare_to_baseline(
                Baseline.capture(
                    prompt_version=combined_versions(prompt_versions),
                    model_version=combined_versions(model_versions),
                    metrics=collect_metrics(sources),
                ),
                load_baseline(path),
            )

    required = [gate.name for gate in GATES] if args.strict else None
    report = build_report(
        sources=sources,
        prompt_versions=prompt_versions,
        model_versions=model_versions,
        baseline=baseline_comparison,
        required=required,
    )

    if args.write_baseline:
        baseline = Baseline.capture(
            prompt_version=combined_versions(prompt_versions),
            model_version=combined_versions(model_versions),
            metrics=report.metrics,
        )
        saved = save_baseline(baseline)
        logger.info("baseline written to %s", saved)

    output = report.to_json()
    if args.json:
        Path(args.json).write_text(output, encoding="utf-8")
    else:
        print(output)

    for outcome in report.gates.outcomes:
        status = "ok" if outcome.passed else "FAIL"
        logger.info(
            "%-28s %-4s %.4f (target %s %.4f)",
            outcome.name,
            status,
            outcome.value,
            outcome.direction,
            outcome.target,
        )
    for name in report.gates.missing:
        logger.warning("gate not evaluated: %s", name)

    if args.strict:
        ok = report.gates.passed and (report.baseline is None or report.baseline.ok)
    else:
        ok = report.gates.evaluated_passed and (report.baseline is None or report.baseline.ok)
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the eval gates")
    parser.add_argument("--keyless", action="store_true", help="force the fake provider")
    parser.add_argument("--strict", action="store_true", help="require every gate to be evaluated")
    parser.add_argument("--baseline", help="path to a locked baseline JSON to compare against")
    parser.add_argument("--write-baseline", action="store_true", help="write the run as a baseline")
    parser.add_argument("--json", help="write the report JSON to this path instead of stdout")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
