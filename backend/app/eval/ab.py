"""Model A/B comparisons.

Two decisions the eval run has to make reproducible: whether the local
open-weight router is good enough to be the default, and whether a challenger
SQL generator should replace the incumbent. Both are decided on measured
numbers, never on vibes: the SQL challenger must add at least five points of
execution accuracy without regressing p95 latency, and the local router must
clear the accuracy bar on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.eval.gates import percentile
from app.eval.router_golden import RouterCase
from app.eval.sql_eval import matches_pattern, rows_satisfy, rows_to_dicts
from app.eval.sql_golden import PERSONAS, SqlCase
from app.router.router import IntentRouter
from app.text_to_sql.builder import SqlBuilder
from app.text_to_sql.executor import SqlExecutor

SQL_MIN_GAIN = 0.05
ROUTER_ACCURACY_BAR = 0.90


@dataclass(frozen=True)
class VariantOutcome:
    label: str
    model: str
    accuracy: float
    p95_latency_s: float
    total: int


@dataclass(frozen=True)
class AbDecision:
    adopt: str | None
    reason: str
    gain: float


def decide_sql_challenger(
    incumbent: VariantOutcome,
    challenger: VariantOutcome,
    *,
    min_gain: float = SQL_MIN_GAIN,
) -> AbDecision:
    """Adopt the challenger only on a clear accuracy win without a latency hit."""
    gain = challenger.accuracy - incumbent.accuracy
    if gain + 1e-9 < min_gain:
        return AbDecision(
            adopt=incumbent.model,
            reason=(
                f"challenger gained {gain:+.3f} accuracy, below the {min_gain:.2f} bar"
            ),
            gain=gain,
        )
    if challenger.p95_latency_s > incumbent.p95_latency_s:
        return AbDecision(
            adopt=incumbent.model,
            reason=(
                "challenger met the accuracy bar but regressed p95 latency "
                f"({challenger.p95_latency_s:.2f}s vs {incumbent.p95_latency_s:.2f}s)"
            ),
            gain=gain,
        )
    return AbDecision(
        adopt=challenger.model,
        reason=f"challenger gained {gain:+.3f} accuracy without a latency regression",
        gain=gain,
    )


def decide_local_router(
    local: VariantOutcome,
    api: VariantOutcome,
    *,
    bar: float = ROUTER_ACCURACY_BAR,
) -> AbDecision:
    """Adopt the local router only if it clears the accuracy bar on its own."""
    gain = local.accuracy - api.accuracy
    if local.accuracy < bar:
        return AbDecision(
            adopt=api.model,
            reason=f"local router accuracy {local.accuracy:.3f} is below the {bar:.2f} bar",
            gain=gain,
        )
    return AbDecision(
        adopt=local.model,
        reason=f"local router accuracy {local.accuracy:.3f} clears the {bar:.2f} bar",
        gain=gain,
    )


@dataclass(frozen=True)
class AbResult:
    decision: AbDecision
    variants: list[VariantOutcome]

    def to_dict(self) -> dict[str, Any]:
        return {
            "adopt": self.decision.adopt,
            "reason": self.decision.reason,
            "gain": self.decision.gain,
            "variants": [
                {
                    "label": variant.label,
                    "model": variant.model,
                    "accuracy": variant.accuracy,
                    "p95_latency_s": variant.p95_latency_s,
                    "total": variant.total,
                }
                for variant in self.variants
            ],
        }


async def measure_router(
    router: IntentRouter, cases: Sequence[RouterCase], *, label: str, model: str
) -> VariantOutcome:
    latencies: list[float] = []
    correct = 0
    for case in cases:
        started = perf_counter()
        decision = await router.decide(case.prompt)
        latencies.append(perf_counter() - started)
        correct += int(decision.intent.value == case.expected_intent)
    total = len(cases)
    return VariantOutcome(
        label=label,
        model=model,
        accuracy=correct / total if total else 0.0,
        p95_latency_s=percentile(latencies, 95),
        total=total,
    )


async def measure_sql(
    builder: SqlBuilder,
    executor: SqlExecutor,
    cases: Sequence[SqlCase],
    *,
    label: str,
    model: str,
    personas: tuple[tuple[str, str], ...] = PERSONAS,
) -> VariantOutcome:
    latencies: list[float] = []
    correct = 0
    total = 0
    for case in cases:
        for dept, role in personas:
            if dept not in case.personas:
                continue
            started = perf_counter()
            try:
                built = await builder.build(case.prompt)
                result = await executor.execute(
                    built.sql,
                    dept=dept,
                    role=role,
                    principal=f"ab@{dept.lower()}.demo.example",
                )
                rows = rows_to_dicts(result)
                ok = matches_pattern(case, built.sql) and rows_satisfy(case, rows)
            except Exception:  # noqa: BLE001 - a failed case counts as incorrect
                ok = False
            latencies.append(perf_counter() - started)
            total += 1
            correct += int(ok)
    return VariantOutcome(
        label=label,
        model=model,
        accuracy=correct / total if total else 0.0,
        p95_latency_s=percentile(latencies, 95),
        total=total,
    )


def router_ab_result(local: VariantOutcome, api: VariantOutcome) -> AbResult:
    return AbResult(decision=decide_local_router(local, api), variants=[local, api])


def sql_ab_result(incumbent: VariantOutcome, challenger: VariantOutcome) -> AbResult:
    return AbResult(
        decision=decide_sql_challenger(incumbent, challenger), variants=[incumbent, challenger]
    )
