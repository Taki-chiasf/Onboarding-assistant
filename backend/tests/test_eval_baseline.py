from pathlib import Path

from app.eval.baseline import (
    Baseline,
    baseline_key,
    baseline_path,
    compare_to_baseline,
    load_baseline,
    save_baseline,
)


def _baseline(**metrics: float) -> Baseline:
    return Baseline.capture(
        prompt_version="router.v1",
        model_version="mistral-small-2603",
        metrics={"router_accuracy": 0.92, "p95_answer_latency_s": 5.0, **metrics},
        created_at="2026-09-24T00:00:00+00:00",
    )


def test_baseline_key_sanitizes_versions() -> None:
    assert baseline_key("router.v1", "mistral-small-2603") == "router.v1__mistral-small-2603"
    assert baseline_key("a/b c", "x:y") == "a_b_c__x_y"


def test_baseline_json_roundtrip() -> None:
    baseline = _baseline()
    restored = Baseline.from_json(baseline.to_json())
    assert restored == baseline


def test_save_and_load(tmp_path: Path) -> None:
    baseline = _baseline()
    path = save_baseline(baseline, tmp_path)
    assert path == baseline_path("router.v1", "mistral-small-2603", tmp_path)
    assert load_baseline(path) == baseline


def test_compare_within_tolerance_is_ok() -> None:
    baseline = _baseline()
    current = _baseline(router_accuracy=0.90)
    comparison = compare_to_baseline(current, baseline)
    assert comparison.ok
    assert comparison.regressions == []


def test_compare_flags_min_direction_regression() -> None:
    baseline = _baseline(router_accuracy=0.90)
    current = _baseline(router_accuracy=0.80)
    comparison = compare_to_baseline(current, baseline)
    assert not comparison.ok
    assert [delta.name for delta in comparison.regressions] == ["router_accuracy"]


def test_compare_flags_max_direction_regression() -> None:
    baseline = _baseline(p95_answer_latency_s=5.0)
    current = _baseline(p95_answer_latency_s=6.0)
    comparison = compare_to_baseline(current, baseline)
    assert [delta.name for delta in comparison.regressions] == ["p95_answer_latency_s"]


def test_compare_marks_stale_on_model_bump() -> None:
    baseline = _baseline()
    current = Baseline.capture(
        prompt_version="router.v1",
        model_version="mistral-small-2701",
        metrics={"router_accuracy": 0.95},
    )
    comparison = compare_to_baseline(current, baseline)
    assert comparison.stale
    assert not comparison.ok
    assert "re-lock" in comparison.reason


def test_compare_reports_missing_metric() -> None:
    baseline = _baseline()
    current = Baseline.capture(
        prompt_version="router.v1",
        model_version="mistral-small-2603",
        metrics={"router_accuracy": 0.95},
    )
    comparison = compare_to_baseline(current, baseline)
    assert "p95_answer_latency_s" in comparison.missing
    assert not comparison.ok
