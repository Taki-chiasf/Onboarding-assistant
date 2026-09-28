"""Suite orchestration shared by the one-off eval run and the nightly loop.

Runs the eval suites the environment can reach and keeps both the per-suite
summaries and the constructed components. The one-off gates run merges the
summaries into metrics; the nightly loop also records per-case results and
replays promoted cases against the same wiring.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import text

from app.eval.rag_eval import AnswerEvalSummary, RetrievalEvalSummary
from app.eval.router_eval import RouterEvalSummary
from app.eval.security import SecuritySummary
from app.eval.sql_eval import SqlEvalSummary

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from app.llm.provider import ChatProvider
    from app.rag.retrieval import Retriever
    from app.router.router import IntentRouter
    from app.text_to_sql.builder import SqlBuilder
    from app.text_to_sql.executor import SqlExecutor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SuiteRun:
    keyless: bool
    router: IntentRouter
    router_summary: RouterEvalSummary
    security_summary: SecuritySummary
    prompt_versions: dict[str, str] = field(default_factory=dict)
    model_versions: dict[str, str] = field(default_factory=dict)
    sql_summary: SqlEvalSummary | None = None
    retrieval_summary: RetrievalEvalSummary | None = None
    answer_summary: AnswerEvalSummary | None = None
    # The components that produced the summaries, so a caller can replay more
    # cases through the same provider wiring and database engine.
    provider: ChatProvider | None = None
    builder: SqlBuilder | None = None
    executor: SqlExecutor | None = None
    retriever: Retriever | None = None


async def corpus_ready(engine: AsyncEngine) -> bool:
    try:
        async with engine.connect() as conn:
            count = (await conn.execute(text("SELECT count(*) FROM doc_chunks"))).scalar()
    except Exception:  # noqa: BLE001 - a missing table just means "not ingested yet"
        return False
    return bool(count)


async def run_suites(*, force_keyless: bool = False, engine: AsyncEngine | None = None) -> SuiteRun:
    """Run the suites; the caller owns the engine's lifecycle.

    Without an engine the SQL, retrieval, answer, and database-backed canary
    suites are skipped, which is what a backend-only environment can run.
    """
    from app.core.config import get_settings
    from app.eval.router_golden import build_router_set
    from app.eval.security import run_security_canaries
    from app.eval.sql_golden import PERSONAS, build_sql_set
    from app.llm.client import get_provider
    from app.llm.fake import FakeProvider
    from app.llm.models import load_models
    from app.prompts.loader import prompt_version
    from app.rag.retrieval import Retriever
    from app.router.router import IntentRouter
    from app.text_to_sql.builder import SqlBuilder
    from app.text_to_sql.executor import SqlExecutor

    settings = get_settings()
    models = load_models()
    keyless = force_keyless or not settings.mistral_api_key
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

    prompt_versions = {
        "router": router.prompt_version,
        "sql_builder": prompt_version("sql_builder"),
        "sql_summarize": prompt_version("sql_summarize"),
        "grounding": prompt_version("grounding"),
        "judge": prompt_version("judge"),
    }
    model_versions = {
        "router": provider.effective_model(models.models["router"]),
        "sql_builder": provider.effective_model(models.models["sql_builder"]),
        "grounding": provider.effective_model(models.models["grounding"]),
        "judge": provider.effective_model(models.models["judge"]),
    }

    sql_summary: SqlEvalSummary | None = None
    security_summary: SecuritySummary
    retrieval_summary: RetrievalEvalSummary | None = None
    answer_summary: AnswerEvalSummary | None = None
    builder: SqlBuilder | None = None
    executor: SqlExecutor | None = None
    retriever: Retriever | None = None

    if engine is not None:
        builder = SqlBuilder(
            sql_keyless(sql_cases) if keyless else provider, models.models["sql_builder"]
        )
        executor = SqlExecutor(
            engine,
            readonly_role=settings.sql_readonly_role,
            statement_timeout_ms=settings.sql_statement_timeout_ms,
            max_rows=settings.sql_max_rows,
        )
        sql_summary = await run_sql_eval(builder, executor, sql_cases, personas=PERSONAS)

        async def embed(texts: list[str]) -> list[list[float]]:
            return await provider.embed(models.models["embed"], texts)

        # Retrieval compares the query embedding with the stored chunk
        # embeddings, so it is only meaningful when the same provider embedded
        # the corpus. Keyless runs use canned vectors and would grade an
        # invalid positive control, so they skip retrieval.
        retriever = (
            Retriever(engine, embed) if (await corpus_ready(engine) and not keyless) else None
        )
        security_summary = await run_security_canaries(
            router=router, executor=executor, retriever=retriever, engine=engine
        )
        if retriever is not None:
            from app.eval.golden import build_golden_set
            from app.eval.rag_eval import run_answer_eval, run_retrieval_eval

            golden = build_golden_set()
            retrieval_summary = await run_retrieval_eval(retriever, golden)
            answer_summary = await run_answer_eval(retriever, provider, models, golden)
    else:
        security_summary = await run_security_canaries(router=router)
        logger.warning("no database engine: skipping SQL and retrieval suites")

    return SuiteRun(
        keyless=keyless,
        router=router,
        router_summary=router_summary,
        security_summary=security_summary,
        prompt_versions=prompt_versions,
        model_versions=model_versions,
        sql_summary=sql_summary,
        retrieval_summary=retrieval_summary,
        answer_summary=answer_summary,
        provider=provider,
        builder=builder,
        executor=executor,
        retriever=retriever,
    )
