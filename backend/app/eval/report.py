"""Run report assembly.

Collects the per-suite summaries into a single set of named metrics, turns them
into a gate report, optionally compares them to a locked baseline, and
serializes the whole thing. Keeping the metric names in one place is what lets
the gate table, the baseline comparison, and the JSON output agree.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.eval.baseline import BaselineComparison
from app.eval.gates import GateReport, evaluate_gates, median, percentile
from app.eval.router_eval import RouterEvalSummary
from app.eval.security import NO_CONTEXT_KIND, RAG_KIND, SQL_KIND, SecuritySummary
from app.eval.sql_eval import SqlEvalSummary
from app.rag.grounding import CITE_OR_DIE
from app.router.schema import Intent
from app.text_to_sql.answer import NO_MATCHING_RECORDS

DONT_KNOW_ANSWERS = frozenset({CITE_OR_DIE, NO_MATCHING_RECORDS})

# The deterministic fallback copy carries no trailing period, but a model
# phrasing the fallback itself usually adds one. Detection normalizes case and
# trailing punctuation so a real "I don't know." counts as a fallback instead
# of hiding from the metric and the console.
FALLBACK_TEXTS = ("i don't know", "i do not know", "no matching records")


def normalized_answer(answer: str) -> str:
    return answer.strip().lower().rstrip(".!? ")


def is_dont_know(answer: str) -> bool:
    return normalized_answer(answer) in FALLBACK_TEXTS


def router_metrics(summary: RouterEvalSummary) -> dict[str, float]:
    out_of_scope = [r for r in summary.results if r.expected == Intent.OUT_OF_SCOPE.value]
    refused = sum(1 for r in out_of_scope if r.actual == Intent.OUT_OF_SCOPE.value)
    metrics = {"router_accuracy": summary.accuracy}
    if out_of_scope:
        metrics["out_of_scope_refusal_rate"] = refused / len(out_of_scope)
    return metrics


def sql_metrics(summary: SqlEvalSummary) -> dict[str, float]:
    return {"sql_valid_correct": summary.correct_rate}


def retrieval_metrics(recall_at_5: float) -> dict[str, float]:
    return {"recall_at_5": recall_at_5}


def security_metrics(summary: SecuritySummary) -> dict[str, float]:
    access_kinds = (SQL_KIND, NO_CONTEXT_KIND, RAG_KIND)
    access = [r for r in summary.results if r.kind in access_kinds]
    injection = [r for r in summary.results if r.kind not in access_kinds]
    metrics: dict[str, float] = {}
    if access:
        metrics["rls_canary_pass_rate"] = sum(1 for r in access if r.passed) / len(access)
    if injection:
        metrics["injection_canary_pass_rate"] = sum(1 for r in injection if r.passed) / len(
            injection
        )
    return metrics


def latency_metrics(
    *,
    answer_latencies_s: Sequence[float] = (),
    first_token_latencies_s: Sequence[float] = (),
    costs_usd: Sequence[float] = (),
) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if answer_latencies_s:
        metrics["p95_answer_latency_s"] = percentile(answer_latencies_s, 95)
    if first_token_latencies_s:
        metrics["p95_first_token_s"] = percentile(first_token_latencies_s, 95)
    if costs_usd:
        metrics["median_cost_usd"] = median(costs_usd)
    return metrics


def judge_metric(verdicts: Sequence[bool]) -> dict[str, float]:
    if not verdicts:
        return {}
    return {"judge_correctness": sum(1 for verdict in verdicts if verdict) / len(verdicts)}


def dont_know_metric(answers: Sequence[str]) -> dict[str, float]:
    if not answers:
        return {}
    fallbacks = sum(1 for answer in answers if is_dont_know(answer))
    return {"dont_know_rate": fallbacks / len(answers)}


@dataclass(frozen=True)
class RunReport:
    prompt_versions: dict[str, str]
    model_versions: dict[str, str]
    metrics: dict[str, float]
    gates: GateReport
    baseline: BaselineComparison | None = None
    sections: dict[str, Any] | None = None

    @classmethod
    def build(
        cls,
        *,
        metrics: Mapping[str, float],
        prompt_versions: Mapping[str, str],
        model_versions: Mapping[str, str],
        required: Sequence[str] | None = None,
        baseline: BaselineComparison | None = None,
        sections: Mapping[str, Any] | None = None,
    ) -> RunReport:
        return cls(
            prompt_versions=dict(prompt_versions),
            model_versions=dict(model_versions),
            metrics={name: float(value) for name, value in metrics.items()},
            gates=evaluate_gates(metrics, required=required),
            baseline=baseline,
            sections=dict(sections) if sections is not None else None,
        )

    @property
    def passed(self) -> bool:
        baseline_ok = self.baseline is None or self.baseline.ok
        return self.gates.passed and baseline_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "prompt_versions": self.prompt_versions,
            "model_versions": self.model_versions,
            "metrics": self.metrics,
            "gates": {
                "passed": self.gates.passed,
                "missing": self.gates.missing,
                "outcomes": [
                    {
                        "name": outcome.name,
                        "value": outcome.value,
                        "target": outcome.target,
                        "direction": outcome.direction,
                        "passed": outcome.passed,
                    }
                    for outcome in self.gates.outcomes
                ],
            },
            "baseline": (
                None
                if self.baseline is None
                else {
                    "ok": self.baseline.ok,
                    "stale": self.baseline.stale,
                    "reason": self.baseline.reason,
                    "regressions": [delta.name for delta in self.baseline.regressions],
                }
            ),
            "sections": self.sections or {},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)
