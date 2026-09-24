"""Evaluation gates and report statistics.

The pass/fail bars the project commits to, drawn from the metric table and the
latency/cost non-functional targets, plus the percentile/median helpers the
runners use when they summarize latency and cost samples. A gate names one
metric, a numeric target, and whether the value should stay at or above the
target (a rate) or at or below it (a latency or a cost).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricGate:
    name: str
    target: float
    direction: str
    description: str

    def passed(self, value: float) -> bool:
        if self.direction == "min":
            return value >= self.target
        if self.direction == "max":
            return value <= self.target
        raise ValueError(f"unknown gate direction: {self.direction!r}")


GATES: tuple[MetricGate, ...] = (
    MetricGate("router_accuracy", 0.90, "min", "Router accuracy including out-of-scope"),
    MetricGate("out_of_scope_refusal_rate", 0.90, "min", "Out-of-scope refusal rate"),
    MetricGate("recall_at_5", 0.85, "min", "Recall@5 for document retrieval"),
    MetricGate("sql_valid_correct", 0.85, "min", "SQL valid-and-correct rate"),
    MetricGate("judge_correctness", 0.80, "min", "LLM-judge answer correctness"),
    MetricGate("dont_know_rate", 0.15, "max", "I don't know fallback rate"),
    MetricGate(
        "rls_canary_pass_rate", 1.0, "min", "Access-control and row-level-security canaries"
    ),
    MetricGate("injection_canary_pass_rate", 1.0, "min", "Prompt-injection canaries"),
    MetricGate("p95_answer_latency_s", 8.0, "max", "p95 full-answer latency"),
    MetricGate("p95_first_token_s", 2.5, "max", "p95 turn-1 first-token latency"),
    MetricGate("median_cost_usd", 0.01, "max", "Median cost per answer"),
)

GATE_BY_NAME: dict[str, MetricGate] = {gate.name: gate for gate in GATES}


@dataclass(frozen=True)
class MetricOutcome:
    name: str
    value: float
    target: float
    direction: str
    passed: bool


@dataclass(frozen=True)
class GateReport:
    outcomes: list[MetricOutcome]
    missing: list[str]

    @property
    def evaluated(self) -> int:
        return len(self.outcomes)

    @property
    def failed(self) -> list[MetricOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.passed]

    @property
    def evaluated_passed(self) -> bool:
        return not self.failed

    @property
    def passed(self) -> bool:
        """True only when every required metric was evaluated and met its target."""
        return not self.missing and not self.failed


def evaluate_gates(
    metrics: Mapping[str, float], *, required: Sequence[str] | None = None
) -> GateReport:
    """Grade the supplied metrics against the gates.

    Only metrics present in ``metrics`` are graded. ``required`` lists the gate
    names that must be present for the run to count as complete (defaults to
    every known gate); names that are absent land in ``missing`` and make the
    report fail. Passing an explicit ``required`` lets a partial environment
    report the gates it can actually evaluate without claiming a full pass.
    """
    names = list(required) if required is not None else [gate.name for gate in GATES]
    outcomes: list[MetricOutcome] = []
    missing: list[str] = []
    for name in names:
        gate = GATE_BY_NAME.get(name)
        if gate is None:
            raise KeyError(f"unknown gate: {name}")
        if name not in metrics:
            missing.append(name)
            continue
        value = float(metrics[name])
        outcomes.append(
            MetricOutcome(
                name=name,
                value=value,
                target=gate.target,
                direction=gate.direction,
                passed=gate.passed(value),
            )
        )
    return GateReport(outcomes=outcomes, missing=missing)


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile; ``p`` is in 0-100. Empty input yields 0."""
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def median(values: Sequence[float]) -> float:
    return percentile(values, 50.0)
