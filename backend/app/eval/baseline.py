"""Reproducibility baselines.

A baseline records the metric values a green run produced at a specific
``(prompt_version, model_version)`` pair, so later runs can be compared
apples-to-apples. Two rules matter: a regression beyond the tolerance is
flagged, and a model-version bump marks the baseline stale so it is re-locked
rather than silently reused against shifted numbers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.eval.gates import GATE_BY_NAME

REGRESSION_TOLERANCE = 0.05
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "eval_baselines"

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def baseline_key(prompt_version: str, model_version: str) -> str:
    return f"{_UNSAFE.sub('_', prompt_version)}__{_UNSAFE.sub('_', model_version)}"


@dataclass(frozen=True)
class Baseline:
    prompt_version: str
    model_version: str
    metrics: dict[str, float]
    created_at: str

    @classmethod
    def capture(
        cls,
        *,
        prompt_version: str,
        model_version: str,
        metrics: Mapping[str, float],
        created_at: str | None = None,
    ) -> Baseline:
        return cls(
            prompt_version=prompt_version,
            model_version=model_version,
            metrics={name: float(value) for name, value in metrics.items()},
            created_at=created_at or datetime.now(UTC).isoformat(),
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "prompt_version": self.prompt_version,
                "model_version": self.model_version,
                "metrics": self.metrics,
                "created_at": self.created_at,
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> Baseline:
        data = json.loads(raw)
        return cls(
            prompt_version=str(data["prompt_version"]),
            model_version=str(data["model_version"]),
            metrics={str(name): float(value) for name, value in data["metrics"].items()},
            created_at=str(data["created_at"]),
        )


@dataclass(frozen=True)
class MetricDelta:
    name: str
    baseline: float
    current: float
    delta: float
    regressed: bool
    direction: str


@dataclass(frozen=True)
class BaselineComparison:
    stale: bool
    deltas: list[MetricDelta]
    regressions: list[MetricDelta]
    missing: list[str]

    @property
    def ok(self) -> bool:
        return not self.stale and not self.regressions and not self.missing

    @property
    def reason(self) -> str:
        if self.stale:
            return "baseline recorded for a different model version; re-lock required"
        if self.missing:
            return f"metrics missing from the current run: {', '.join(self.missing)}"
        if self.regressions:
            names = ", ".join(delta.name for delta in self.regressions)
            return f"regression beyond tolerance: {names}"
        return "within baseline"


def _direction(name: str) -> str:
    gate = GATE_BY_NAME.get(name)
    return gate.direction if gate else "min"


def _regressed(name: str, current: float, baseline: float, tolerance: float) -> bool:
    if _direction(name) == "max":
        threshold = baseline * (1.0 + tolerance) if baseline > 0 else tolerance
        return current > threshold
    threshold = baseline * (1.0 - tolerance) if baseline > 0 else -tolerance
    return current < threshold


def compare_to_baseline(
    current: Baseline,
    baseline: Baseline,
    *,
    tolerance: float = REGRESSION_TOLERANCE,
) -> BaselineComparison:
    """Compare a run against a locked baseline.

    A model-version mismatch marks the comparison stale (the check is not
    meaningful across checkpoints); the deltas are still reported for context.
    """
    deltas: list[MetricDelta] = []
    regressions: list[MetricDelta] = []
    missing: list[str] = []
    for name, base_value in baseline.metrics.items():
        if name not in current.metrics:
            missing.append(name)
            continue
        current_value = current.metrics[name]
        delta = MetricDelta(
            name=name,
            baseline=base_value,
            current=current_value,
            delta=current_value - base_value,
            regressed=_regressed(name, current_value, base_value, tolerance),
            direction=_direction(name),
        )
        deltas.append(delta)
        if delta.regressed:
            regressions.append(delta)
    return BaselineComparison(
        stale=current.model_version != baseline.model_version,
        deltas=deltas,
        regressions=regressions,
        missing=missing,
    )


def baseline_path(
    prompt_version: str, model_version: str, directory: Path = DEFAULT_DIR
) -> Path:
    return directory / f"{baseline_key(prompt_version, model_version)}.json"


def save_baseline(baseline: Baseline, directory: Path = DEFAULT_DIR) -> Path:
    path = baseline_path(baseline.prompt_version, baseline.model_version, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(baseline.to_json(), encoding="utf-8")
    return path


def load_baseline(path: Path) -> Baseline:
    return Baseline.from_json(path.read_text(encoding="utf-8"))
