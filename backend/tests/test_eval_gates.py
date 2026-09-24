import pytest

from app.eval.gates import (
    GATES,
    evaluate_gates,
    median,
    percentile,
)


def _all_passing() -> dict[str, float]:
    return {
        "router_accuracy": 0.95,
        "out_of_scope_refusal_rate": 1.0,
        "recall_at_5": 0.9,
        "sql_valid_correct": 0.9,
        "judge_correctness": 0.85,
        "dont_know_rate": 0.05,
        "rls_canary_pass_rate": 1.0,
        "injection_canary_pass_rate": 1.0,
        "p95_answer_latency_s": 6.0,
        "p95_first_token_s": 2.0,
        "median_cost_usd": 0.002,
    }


def test_all_gates_pass_at_target() -> None:
    report = evaluate_gates(_all_passing())
    assert report.passed
    assert report.missing == []
    assert report.evaluated == len(GATES)


def test_gate_fails_below_minimum() -> None:
    metrics = _all_passing()
    metrics["router_accuracy"] = 0.89
    report = evaluate_gates(metrics)
    assert not report.passed
    assert [outcome.name for outcome in report.failed] == ["router_accuracy"]


def test_max_direction_gate_fails_above_target() -> None:
    metrics = _all_passing()
    metrics["p95_answer_latency_s"] = 8.5
    report = evaluate_gates(metrics)
    assert not report.passed
    assert [outcome.name for outcome in report.failed] == ["p95_answer_latency_s"]


def test_missing_gate_is_reported_and_fails() -> None:
    metrics = _all_passing()
    del metrics["recall_at_5"]
    report = evaluate_gates(metrics)
    assert report.missing == ["recall_at_5"]
    assert not report.passed


def test_partial_required_reports_only_evaluated() -> None:
    report = evaluate_gates({"router_accuracy": 1.0}, required=["router_accuracy"])
    assert report.passed
    assert report.missing == []


def test_unknown_gate_raises() -> None:
    with pytest.raises(KeyError):
        evaluate_gates({}, required=["does_not_exist"])


def test_evaluated_passed_ignores_missing() -> None:
    report = evaluate_gates({"router_accuracy": 0.95}, required=["router_accuracy", "recall_at_5"])
    assert report.evaluated_passed
    assert not report.passed
    assert report.missing == ["recall_at_5"]


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile([4.0], 95) == 4.0
    assert percentile([], 95) == 0.0


def test_percentile_p95_bounds_top() -> None:
    values = [float(i) for i in range(1, 101)]
    result = percentile(values, 95)
    assert 95.0 <= result <= 100.0
    assert result == pytest.approx(95.05, abs=0.1)


def test_median() -> None:
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([]) == 0.0
