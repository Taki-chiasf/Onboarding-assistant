import os
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.eval.baseline import Baseline, compare_to_baseline
from app.eval.eval_run import MetricSources, build_report
from app.eval.golden import build_golden_set
from app.eval.nightly import (
    MAX_MISROUTES_PER_RUN,
    SOURCE_DOCS_SET,
    SOURCE_MISROUTE,
    SOURCE_ROUTER_SET,
    SOURCE_SQL_SET,
    SUITE_ROUTER,
    CanaryFlags,
    NightlyMark,
    canary_flags,
    docs_run_rows,
    golden_case_rows,
    green_streak,
    misroute_candidates,
    promoted_run_rows,
    real_feedback_volume,
    router_run_rows,
    run_nightly,
    should_write_synthetic,
    sql_run_rows,
    synthetic_feedback_rows,
)
from app.eval.promoted import PromotedResult, matches_predicate, persona_from_tags, replay_case
from app.eval.rag_eval import (
    AnswerCaseResult,
    AnswerEvalSummary,
    RetrievalCaseResult,
    RetrievalEvalSummary,
)
from app.eval.report import RunReport
from app.eval.router_eval import RouterCaseResult, RouterEvalSummary
from app.eval.router_golden import build_router_set
from app.eval.security import RAG_KIND, SQL_KIND, CanaryResult, SecuritySummary
from app.eval.sql_eval import SqlCaseResult, SqlEvalSummary
from app.eval.sql_golden import build_sql_set
from app.llm.fake import FakeProvider
from app.models import EvalCase, EvalRun, Feedback, NightlyEvalRun
from app.router.router import IntentRouter
from app.router.schema import Intent, RouteDecision
from app.text_to_sql.builder import SqlBuilder
from app.text_to_sql.executor import SqlExecutor


def test_green_streak_counts_consecutive_days() -> None:
    today = date(2026, 9, 28)
    assert green_streak([]) == 0
    assert green_streak([NightlyMark(today, True)]) == 1
    assert (
        green_streak(
            [
                NightlyMark(today - timedelta(days=2), True),
                NightlyMark(today - timedelta(days=1), True),
                NightlyMark(today, True),
            ]
        )
        == 3
    )
    assert (
        green_streak([NightlyMark(today - timedelta(days=2), True), NightlyMark(today, True)]) == 1
    )
    assert (
        green_streak([NightlyMark(today - timedelta(days=1), True), NightlyMark(today, False)]) == 0
    )
    assert green_streak([NightlyMark(today, True), NightlyMark(today, False)]) == 0
    assert green_streak([NightlyMark(today, True), NightlyMark(today, True)]) == 1


def test_matches_predicate_grammar() -> None:
    rows = [{"status": "active", "n": "1"}, {"status": "active", "n": "2"}]
    assert matches_predicate("count >= 1", rows)
    assert matches_predicate("count == 2", rows)
    assert not matches_predicate("count > 2", rows)
    assert matches_predicate("count = 0", [])
    assert matches_predicate("all:status=active", rows)
    assert not matches_predicate("all:status=done", rows)
    assert matches_predicate("any:status=active", rows)
    assert not matches_predicate("any:status=done", rows)
    with pytest.raises(ValueError):
        matches_predicate("unsupported clause", rows)


def test_persona_from_tags_defaults_and_overrides() -> None:
    assert persona_from_tags(None) == ("Engineering", "employee")
    assert persona_from_tags(["dept:Finance", "role:admin"]) == ("Finance", "admin")
    assert persona_from_tags(["dept:", "role:"]) == ("Engineering", "employee")


def test_canary_flags_split_access_from_injection() -> None:
    summary = SecuritySummary(
        results=[
            CanaryResult("a", SQL_KIND, True, ""),
            CanaryResult("b", RAG_KIND, False, ""),
            CanaryResult("c", "prompt_injection", True, ""),
        ]
    )
    flags = canary_flags(summary)
    assert flags.rls is False
    assert flags.injection is True
    assert canary_flags(SecuritySummary(results=[])) == CanaryFlags(rls=None, injection=None)


def test_golden_case_rows_mirror_the_sets() -> None:
    router_cases = build_router_set()
    sql_cases = build_sql_set()
    docs_cases = build_golden_set()
    rows = golden_case_rows(router_cases=router_cases, sql_cases=sql_cases, docs_cases=docs_cases)
    by_source = Counter(row.source for row in rows)
    assert by_source[SOURCE_ROUTER_SET] == len(router_cases)
    assert by_source[SOURCE_SQL_SET] == len(sql_cases)
    assert by_source[SOURCE_DOCS_SET] == len(docs_cases)
    assert all(row.status == "golden" for row in rows)
    assert all(row.id is not None for row in rows)
    sql_row = next(row for row in rows if row.source == SOURCE_SQL_SET)
    assert sql_row.expected_sql_pattern
    docs_row = next(row for row in rows if row.source == SOURCE_DOCS_SET)
    assert docs_row.expected_source_ids


def test_router_run_rows_map_the_grade() -> None:
    summary = RouterEvalSummary(
        results=[
            RouterCaseResult("q1", "rag-docs", "text-to-sql", 0.4, "router", False),
            RouterCaseResult("q2", "rag-docs", "rag-docs", 0.9, "router", True),
        ]
    )
    index = {(SOURCE_ROUTER_SET, "q1"): uuid.uuid4(), (SOURCE_ROUTER_SET, "q2"): uuid.uuid4()}
    rows = router_run_rows(
        summary,
        index,
        flags=CanaryFlags(rls=True, injection=False),
        prompt_version="router.v1",
        model_version="small-model",
    )
    assert [row.suite for row in rows] == [SUITE_ROUTER, SUITE_ROUTER]
    assert rows[0].passed is False
    assert rows[0].actual_intent == "text-to-sql"
    assert rows[0].diff == "expected rag-docs, got text-to-sql"
    assert rows[0].rls_canary_passed is True
    assert rows[0].injection_canary_passed is False
    assert rows[0].prompt_version == "router.v1"
    assert rows[0].model_version == "small-model"
    assert rows[1].passed is True
    assert rows[1].diff is None


def test_sql_run_rows_carry_persona_sql_and_failures() -> None:
    summary = SqlEvalSummary(
        total=1,
        valid=1,
        correct=0,
        results=[
            SqlCaseResult(
                "q",
                "Finance",
                "employee",
                True,
                False,
                "SELECT 1",
                None,
                0,
                pattern_ok=True,
                rows_ok=False,
                latency_ms=12,
            )
        ],
    )
    index = {(SOURCE_SQL_SET, "q"): uuid.uuid4()}
    rows = sql_run_rows(
        summary,
        index,
        flags=CanaryFlags(rls=True, injection=True),
        prompt_version="sql_builder.v1",
        model_version="builder-model",
    )
    row = rows[0]
    assert row.persona == "Finance/employee"
    assert row.generated_sql == "SELECT 1"
    assert row.passed is False
    assert row.diff == "failed: rows"
    assert row.latency_ms == 12


def _retrieval(hit: bool) -> RetrievalEvalSummary:
    return RetrievalEvalSummary(
        recall_at_5=float(hit),
        total=1,
        hits=int(hit),
        results=[RetrievalCaseResult("q", ["chunk-a"], ["chunk-a"] if hit else ["chunk-b"], hit)],
    )


def _answer(judged: bool, *, reason: str | None = None) -> AnswerEvalSummary:
    return AnswerEvalSummary(
        results=[
            AnswerCaseResult(
                "q",
                "the answer",
                0.4,
                1.5,
                0.002,
                judged,
                judge_reason=reason,
                prompt_version="grounding.v1",
            )
        ]
    )


def test_docs_run_rows_merge_recall_and_judge() -> None:
    index = {(SOURCE_DOCS_SET, "q"): uuid.uuid4()}
    rows = docs_run_rows(
        _retrieval(True),
        _answer(True),
        index,
        flags=CanaryFlags(rls=True, injection=True),
        model_version="grounding-model",
    )
    row = rows[0]
    assert row.passed is True
    assert row.retrieved_source_ids == ["chunk-a"]
    assert row.judge_passed is True
    assert row.cost_usd == Decimal("0.002")
    assert row.latency_ms == 1500
    assert row.prompt_version == "grounding.v1"
    assert row.diff is None

    rows = docs_run_rows(
        _retrieval(False),
        _answer(False, reason="missed the citation"),
        index,
        flags=CanaryFlags(rls=True, injection=True),
        model_version="grounding-model",
    )
    row = rows[0]
    assert row.passed is False
    assert row.judge_passed is False
    assert row.diff is not None
    assert "recall" in row.diff and "judge" in row.diff


def test_promoted_run_rows_note_the_failing_check() -> None:
    result = PromotedResult(
        case_id=uuid.uuid4(),
        prompt="q",
        intent_ok=False,
        actual_intent="rag-docs",
        intent_confidence=0.7,
    )
    rows = promoted_run_rows(
        [result],
        router_prompt_version="router.v1",
        router_model="small-model",
        sql_prompt_version="sql_builder.v1",
        sql_model="builder-model",
    )
    row = rows[0]
    assert row.passed is False
    assert row.actual_intent == "rag-docs"
    assert row.diff == "failed: intent"
    assert row.prompt_version == "router.v1"
    assert row.suite == "promoted"


def test_misroute_candidates_dedup_skip_and_cap() -> None:
    results = [
        RouterCaseResult(f"q{i}", "rag-docs", "text-to-sql", 0.3, "router", False)
        for i in range(25)
    ]
    results.append(RouterCaseResult("c", "rag-docs", "rag-docs", 0.9, "router", True))
    results.append(RouterCaseResult("e", "rag-docs", None, 0.0, "error", False))
    existing = {(SOURCE_MISROUTE, "q0")}

    candidates = misroute_candidates(results, existing=existing)

    assert len(candidates) == MAX_MISROUTES_PER_RUN
    assert candidates[0].prompt == "q1"
    assert candidates[0].expected_intent == "rag-docs"
    assert candidates[0].status == "review"
    assert candidates[0].source == SOURCE_MISROUTE
    assert candidates[0].tags == ["router", "actual:text-to-sql"]
    assert all(candidate.prompt not in {"q0", "c", "e"} for candidate in candidates)


def test_synthetic_feedback_maps_verdicts_and_switches_off() -> None:
    assert should_write_synthetic(0) is True
    assert should_write_synthetic(1) is False

    results = [
        AnswerCaseResult("q1", "a", 0.1, 0.2, 0.0, True),
        AnswerCaseResult("q2", "b", 0.1, 0.2, 0.0, False, judge_reason="wrong number"),
    ]
    index = {(SOURCE_DOCS_SET, "q1"): uuid.uuid4(), (SOURCE_DOCS_SET, "q2"): uuid.uuid4()}
    rows = synthetic_feedback_rows(results, index)
    assert rows[0].rating == "pass"
    assert rows[0].correction is None
    assert rows[0].source == "synthetic"
    assert rows[0].case_id == index[(SOURCE_DOCS_SET, "q1")]
    assert rows[1].rating == "fail"
    assert rows[1].correction == "wrong number"


def _green_report() -> RunReport:
    summary = RouterEvalSummary(
        results=[
            RouterCaseResult("q", "rag-docs", "rag-docs", 0.95, "router", True),
            RouterCaseResult("o", "out-of-scope", "out-of-scope", 0.9, "router", True),
        ]
    )
    return build_report(
        sources=MetricSources(router=summary),
        prompt_versions={"router": "router.v1"},
        model_versions={"router": "small-model"},
        required=["router_accuracy", "out_of_scope_refusal_rate"],
    )


def _red_report() -> RunReport:
    summary = RouterEvalSummary(
        results=[RouterCaseResult("q", "rag-docs", "text-to-sql", 0.4, "router", False)]
    )
    return build_report(
        sources=MetricSources(router=summary),
        prompt_versions={"router": "router.v1"},
        model_versions={"router": "small-model"},
        required=["router_accuracy"],
    )


def test_build_alert_silent_when_green_and_unremarkable() -> None:
    from app.eval.notify import build_alert

    assert (
        build_alert(
            green=True,
            keyless=False,
            streak=3,
            report=_green_report(),
            regression=None,
            promoted_total=0,
            promoted_failed=0,
        )
        is None
    )


def test_build_alert_reports_gates_and_regressions() -> None:
    from app.eval.notify import build_alert

    regression = compare_to_baseline(
        Baseline.capture(
            prompt_version="router.v1", model_version="m", metrics={"router_accuracy": 0.80}
        ),
        Baseline.capture(
            prompt_version="router.v1", model_version="m", metrics={"router_accuracy": 0.95}
        ),
    )
    alert = build_alert(
        green=False,
        keyless=True,
        streak=0,
        report=_red_report(),
        regression=regression,
        promoted_total=4,
        promoted_failed=1,
    )
    assert alert is not None
    assert "RED" in alert
    assert "gate failed: router_accuracy" in alert
    assert "regression vs last green: router_accuracy" in alert
    assert "promoted cases: 3/4 passing" in alert
    assert "keyless smoke run" in alert


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


class _FakeClient:
    def __init__(self, response: _FakeResponse | None = None, error: bool = False) -> None:
        self._response = response or _FakeResponse()
        self._error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, *, json: dict[str, Any]) -> _FakeResponse:
        self.calls.append((url, json))
        if self._error:
            raise RuntimeError("network down")
        return self._response


async def test_post_alert_sends_payload_and_swallows_failures() -> None:
    from app.eval.notify import post_alert

    client = _FakeClient()
    assert await post_alert("https://hook.example/x", "text", client=cast(Any, client)) is True
    assert client.calls == [("https://hook.example/x", {"text": "text"})]

    failing = _FakeClient(_FakeResponse(500))
    assert await post_alert("https://hook.example/x", "text", client=cast(Any, failing)) is False

    broken = _FakeClient(error=True)
    assert await post_alert("https://hook.example/x", "text", client=cast(Any, broken)) is False


class _FakeRouter:
    prompt_version = "router.v1"

    def __init__(self, intent: Intent) -> None:
        self._intent = intent

    async def decide(self, query: str) -> RouteDecision:
        return RouteDecision(
            intent=self._intent,
            confidence=0.8,
            surfaces=[],
            entities=[],
            rationale="test",
            source="router",
        )


async def test_replay_case_grades_intent_and_uncertainty() -> None:
    case = EvalCase(id=uuid.uuid4(), prompt="q", expected_intent="rag-docs", status="promoted")
    result = await replay_case(
        case,
        router=cast(IntentRouter, _FakeRouter(Intent.RAG_DOCS)),
        retriever=None,
        builder=None,
        executor=None,
    )
    assert result.passed is True
    assert result.actual_intent == "rag-docs"
    assert result.intent_confidence == 0.8

    wrong = await replay_case(
        case,
        router=cast(IntentRouter, _FakeRouter(Intent.TEXT_TO_SQL)),
        retriever=None,
        builder=None,
        executor=None,
    )
    assert wrong.passed is False
    assert wrong.intent_ok is False
    assert wrong.actual_intent == "text-to-sql"


async def test_replay_case_fails_a_check_whose_component_is_missing() -> None:
    case = EvalCase(
        id=uuid.uuid4(),
        prompt="q",
        expected_source_ids=["chunk-a"],
        status="promoted",
    )
    result = await replay_case(
        case,
        router=cast(IntentRouter, _FakeRouter(Intent.RAG_DOCS)),
        retriever=None,
        builder=None,
        executor=None,
    )
    assert result.passed is False
    assert result.retrieval_hit is False
    assert result.error is not None
    assert "corpus" in result.error


_LIVE_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture
async def live_engine() -> AsyncIterator[AsyncEngine]:
    if not _LIVE_DB_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    engine = create_async_engine(_LIVE_DB_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_nightly_runs_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("MISTRAL_API_KEY", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("SLACK_EVAL_WEBHOOK_URL", raising=False)
    get_settings.cache_clear()
    try:
        outcome = await run_nightly(keyless=True)
    finally:
        get_settings.cache_clear()

    assert outcome.green is True
    assert outcome.keyless is True
    assert outcome.runs_written == 0
    assert outcome.nightly_run_id is None
    assert outcome.alert is None


async def test_nightly_keyless_persists_runs_and_a_streak(live_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(live_engine, expire_on_commit=False)
    nightly_id: uuid.UUID | None = None
    try:
        # Start from a clean eval set so the seeding path is deterministic.
        async with factory() as session:
            await session.execute(
                delete(EvalCase).where(
                    EvalCase.source.in_((SOURCE_ROUTER_SET, SOURCE_SQL_SET, SOURCE_DOCS_SET))
                )
            )
            await session.commit()

        outcome = await run_nightly(keyless=True, engine=live_engine)

        assert outcome.green is True
        assert outcome.cases_seeded > 0
        assert outcome.runs_written > 0
        assert outcome.streak >= 1
        assert outcome.alert is None
        assert outcome.notified is False
        assert outcome.nightly_run_id is not None
        nightly_id = uuid.UUID(outcome.nightly_run_id)

        async with factory() as session:
            nightly = await session.get(NightlyEvalRun, nightly_id)
            assert nightly is not None
            assert nightly.passed is True
            assert nightly.keyless is True
            assert nightly.streak >= 1
            assert nightly.metrics is not None and "router_accuracy" in nightly.metrics

            run = (
                await session.execute(select(EvalRun).where(EvalRun.suite == SUITE_ROUTER).limit(1))
            ).scalar_one_or_none()
            assert run is not None
            assert run.passed is True
            assert run.actual_intent is not None

        # A second run in the same day must not double the streak.
        second = await run_nightly(keyless=True, engine=live_engine)
        assert second.streak == outcome.streak
        if second.nightly_run_id is not None:
            async with factory() as session:
                await session.execute(
                    delete(NightlyEvalRun).where(
                        NightlyEvalRun.id == uuid.UUID(second.nightly_run_id)
                    )
                )
                await session.commit()
    finally:
        async with factory() as session:
            await session.execute(
                delete(EvalCase).where(
                    EvalCase.source.in_((SOURCE_ROUTER_SET, SOURCE_SQL_SET, SOURCE_DOCS_SET))
                )
            )
            if nightly_id is not None:
                await session.execute(delete(NightlyEvalRun).where(NightlyEvalRun.id == nightly_id))
            await session.commit()


async def test_real_feedback_volume_counts_recent_rows(live_engine: AsyncEngine) -> None:
    factory = async_sessionmaker(live_engine, expire_on_commit=False)
    feedback_id = uuid.uuid4()
    async with factory() as session:
        session.add(Feedback(id=feedback_id, rating="up", source="real"))
        await session.commit()
    try:
        async with factory() as session:
            assert await real_feedback_volume(session) >= 1
    finally:
        async with factory() as session:
            await session.execute(delete(Feedback).where(Feedback.id == feedback_id))
            await session.commit()


async def test_promoted_sql_case_replays_against_the_database(live_engine: AsyncEngine) -> None:
    provider = FakeProvider(
        responses={"sql-model": "SELECT count(*) AS headcount FROM org_members"}
    )
    builder = SqlBuilder(cast(Any, provider), "sql-model")
    executor = SqlExecutor(live_engine)
    case = EvalCase(
        id=uuid.uuid4(),
        prompt="How many people work here?",
        expected_sql_pattern=r"count\(\*\).*org_members",
        expected_rows_predicate="count >= 1",
        status="promoted",
    )

    result = await replay_case(
        case,
        router=cast(IntentRouter, _FakeRouter(Intent.TEXT_TO_SQL)),
        retriever=None,
        builder=builder,
        executor=executor,
    )

    assert result.sql_valid is True
    assert result.pattern_ok is True
    assert result.rows_ok is True
    assert result.passed is True
    assert result.generated_sql == "SELECT count(*) AS headcount FROM org_members"
