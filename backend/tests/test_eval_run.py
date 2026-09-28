from app.eval.eval_run import (
    MetricSources,
    build_report,
    collect_metrics,
    collect_sections,
    combined_versions,
)
from app.eval.router_eval import RouterCaseResult, RouterEvalSummary
from app.eval.security import INJECTION_KIND, CanaryResult, SecuritySummary
from app.eval.sql_eval import SqlCaseResult, SqlEvalSummary


def _router_summary() -> RouterEvalSummary:
    def result(expected: str, actual: str | None) -> RouterCaseResult:
        return RouterCaseResult(
            prompt=f"q-{expected}",
            expected=expected,
            actual=actual,
            confidence=0.9,
            source="router",
            correct=expected == actual,
        )

    return RouterEvalSummary(
        results=[
            result("rag-docs", "rag-docs"),
            result("out-of-scope", "out-of-scope"),
            result("out-of-scope", "rag-docs"),
            result("ambiguous", "ambiguous"),
        ]
    )


def _green_router_summary() -> RouterEvalSummary:
    def result(expected: str) -> RouterCaseResult:
        return RouterCaseResult(
            prompt=f"q-{expected}",
            expected=expected,
            actual=expected,
            confidence=0.95,
            source="router",
            correct=True,
        )

    return RouterEvalSummary(
        results=[
            result("rag-docs"),
            result("rag-code"),
            result("text-to-sql"),
            result("out-of-scope"),
            result("ambiguous"),
        ]
    )


def _sql_summary() -> SqlEvalSummary:
    return SqlEvalSummary(
        total=4,
        valid=4,
        correct=3,
        results=[
            SqlCaseResult("q", "Engineering", "employee", True, True, "SELECT 1", None, 1),
            SqlCaseResult("q", "Finance", "employee", True, False, "SELECT 1", None, 0),
        ],
    )


def _security_summary() -> SecuritySummary:
    return SecuritySummary(
        results=[
            CanaryResult("sql:a->b", "sql_access", True, "zero rows"),
            CanaryResult("injection:x", "prompt_injection", True, "refused"),
            CanaryResult("injection:y", "prompt_injection", False, "routed to text-to-sql"),
        ]
    )


def test_collect_metrics_merges_suites() -> None:
    sources = MetricSources(
        router=_router_summary(), sql=_sql_summary(), security=_security_summary()
    )
    metrics = collect_metrics(sources)
    assert metrics["router_accuracy"] == 0.75
    assert metrics["out_of_scope_refusal_rate"] == 0.5
    assert metrics["sql_valid_correct"] == 0.75
    assert metrics["rls_canary_pass_rate"] == 1.0
    assert metrics["injection_canary_pass_rate"] == 0.5


def test_collect_metrics_includes_latency_and_cost() -> None:
    sources = MetricSources(
        answer_latencies_s=[1.0, 2.0, 3.0],
        first_token_latencies_s=[0.5, 0.7],
        costs_usd=[0.001, 0.002, 0.003],
    )
    metrics = collect_metrics(sources)
    assert metrics["p95_answer_latency_s"] == 2.9
    assert metrics["p95_first_token_s"] == 0.69
    assert metrics["median_cost_usd"] == 0.002


def test_collect_metrics_judge_and_dont_know() -> None:
    sources = MetricSources(judge_verdicts=[True, True, False], answers=["a", "b", "c", "d"])
    metrics = collect_metrics(sources)
    assert metrics["judge_correctness"] == 2 / 3
    assert metrics["dont_know_rate"] == 0.0


def test_dont_know_metric_counts_the_phrased_fallback() -> None:
    from app.eval.report import dont_know_metric

    metrics = dont_know_metric(["I don't know.", "no matching records.", "16 weeks"])
    assert metrics["dont_know_rate"] == 2 / 3


def test_collect_sections() -> None:
    sources = MetricSources(
        router=_router_summary(), sql=_sql_summary(), security=_security_summary()
    )
    sections = collect_sections(sources)
    assert sections["router"]["total"] == 4
    assert sections["sql"]["correct_rate"] == 0.75
    assert sections["security"]["by_kind"][INJECTION_KIND] == (1, 2)


def test_build_report_partial_required_passes_and_serializes() -> None:
    report = build_report(
        sources=MetricSources(router=_green_router_summary()),
        prompt_versions={"router": "router.v1"},
        model_versions={"router": "mistral-small-2603"},
        required=["router_accuracy", "out_of_scope_refusal_rate"],
    )
    assert report.gates.passed
    payload = report.to_dict()
    assert payload["passed"] is True
    assert payload["gates"]["passed"] is True
    assert payload["sections"]["router"]["ambiguous_boundary"] == (1, 1)
    assert "router.v1" in report.to_json()


def test_build_report_fails_when_gate_below_bar() -> None:
    report = build_report(
        sources=MetricSources(router=_router_summary()),
        prompt_versions={},
        model_versions={},
        required=["router_accuracy"],
    )
    assert report.metrics["router_accuracy"] == 0.75
    assert not report.gates.passed


def test_combined_versions_sorted_and_joined() -> None:
    assert combined_versions({"b": "two", "a": "one"}) == "one+two"
    assert combined_versions({}) == "unknown"
