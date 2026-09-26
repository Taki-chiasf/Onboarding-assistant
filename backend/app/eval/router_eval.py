"""Intent router evaluation replay.

Replays the golden router set through the router and grades the resolved intent.
Keyless runs use a provider that returns the expected verdict, which exercises
the parse -> guardrail -> decision pipeline end to end; the real-model accuracy
run happens once a keyed environment is available.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core.redact import redact_pii
from app.eval.router_golden import RouterCase, build_router_set
from app.llm.fake import FakeProvider
from app.llm.provider import ChatMessage
from app.router.router import IntentRouter
from app.router.schema import Intent

logger = logging.getLogger(__name__)

_QUESTION_PREFIX = "Question: "


@dataclass(frozen=True)
class RouterCaseResult:
    prompt: str
    expected: str
    actual: str | None
    confidence: float
    source: str
    correct: bool
    error: str | None = None
    tags: tuple[str, ...] = ()


@dataclass
class RouterEvalSummary:
    results: list[RouterCaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct(self) -> int:
        return sum(1 for result in self.results if result.correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    def by_intent(self) -> dict[str, tuple[int, int]]:
        totals: dict[str, tuple[int, int]] = {}
        for result in self.results:
            correct, total = totals.get(result.expected, (0, 0))
            totals[result.expected] = (correct + int(result.correct), total + 1)
        return totals

    def ambiguous_boundary(self) -> tuple[int, int]:
        relevant = [r for r in self.results if r.expected == Intent.AMBIGUOUS.value]
        return sum(1 for r in relevant if r.correct), len(relevant)


def question_from_messages(messages: Sequence[ChatMessage]) -> str:
    for message in reversed(messages):
        if _QUESTION_PREFIX in message.content:
            return message.content.split(_QUESTION_PREFIX, 1)[1].strip()
    return ""


def expected_verdict(case: RouterCase) -> dict[str, object]:
    if case.expected_intent == Intent.RAG_DOCS.value:
        return {"intent": case.expected_intent, "confidence": 0.9, "surfaces": ["rag-docs"]}
    if case.expected_intent == Intent.RAG_CODE.value:
        return {"intent": case.expected_intent, "confidence": 0.9, "surfaces": ["rag-code"]}
    if case.expected_intent == Intent.TEXT_TO_SQL.value:
        return {"intent": case.expected_intent, "confidence": 0.9, "surfaces": ["text-to-sql"]}
    if case.expected_intent == Intent.OUT_OF_SCOPE.value:
        return {"intent": case.expected_intent, "confidence": 0.9}
    return {
        "intent": Intent.AMBIGUOUS.value,
        "confidence": 0.8,
        "surfaces": ["rag-docs", "text-to-sql"],
    }


def make_keyless_provider(cases: list[RouterCase]) -> FakeProvider:
    by_prompt = {case.prompt: expected_verdict(case) for case in cases}

    def chat_fn(model: str, messages: Sequence[ChatMessage]) -> str:
        verdict = by_prompt.get(question_from_messages(messages))
        return json.dumps(verdict) if verdict is not None else "{}"

    return FakeProvider(chat_fn=chat_fn)


async def run_router_eval(router: IntentRouter, cases: list[RouterCase]) -> RouterEvalSummary:
    summary = RouterEvalSummary()
    for case in cases:
        try:
            decision = await router.decide(case.prompt)
            summary.results.append(
                RouterCaseResult(
                    prompt=case.prompt,
                    expected=case.expected_intent,
                    actual=decision.intent.value,
                    confidence=decision.confidence,
                    source=decision.source,
                    correct=decision.intent.value == case.expected_intent,
                    tags=case.tags,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a failing case must not abort the run
            summary.results.append(
                RouterCaseResult(
                    prompt=case.prompt,
                    expected=case.expected_intent,
                    actual=None,
                    confidence=0.0,
                    source="error",
                    correct=False,
                    error=str(exc),
                    tags=case.tags,
                )
            )
    return summary


async def _main() -> None:
    from app.llm.models import load_models

    cases = build_router_set()
    provider = make_keyless_provider(cases)
    router = IntentRouter(provider, load_models().models["router"])
    summary = await run_router_eval(router, cases)

    logger.info(
        "router eval: accuracy=%.2f (%d/%d)", summary.accuracy, summary.correct, summary.total
    )
    for intent, (correct, total) in summary.by_intent().items():
        logger.info("  %s: %d/%d", intent, correct, total)
    correct, total = summary.ambiguous_boundary()
    logger.info("  ambiguous boundary: %d/%d", correct, total)
    for result in summary.results:
        if not result.correct:
            logger.info(
                "  fail: %s -> %s", redact_pii(result.prompt), redact_pii(result.actual or "")
            )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
