"""Offline retrieval evaluation and answer judging.

Replays the golden set through retrieval to measure recall, and judges
generated answers against their reference context with an LLM judge. Runs as a
one-off command; the nightly scheduling lands with the eval loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter

from app.core.redact import redact_pii
from app.eval.golden import GoldenCase, build_golden_set, recall_at_k
from app.llm.models import ModelConfig, load_models
from app.llm.pricing import compute_cost, estimate_tokens
from app.llm.provider import ChatMessage, ChatProvider
from app.prompts.loader import load_prompt
from app.rag.grounding import build_context, build_grounding_messages
from app.rag.retrieval import Retriever

logger = logging.getLogger(__name__)

EVAL_DEPT = "Engineering"
EVAL_ROLE = "employee"


@dataclass(frozen=True)
class RetrievalCaseResult:
    prompt: str
    expected: list[str]
    retrieved: list[str]
    hit: bool


@dataclass(frozen=True)
class RetrievalEvalSummary:
    recall_at_5: float
    total: int
    hits: int
    results: list[RetrievalCaseResult]


async def run_retrieval_eval(
    retriever: Retriever,
    cases: list[GoldenCase],
    *,
    dept: str = EVAL_DEPT,
    role: str = EVAL_ROLE,
    top_k: int = 5,
) -> RetrievalEvalSummary:
    results: list[RetrievalCaseResult] = []
    hits = 0
    for case in cases:
        chunks = await retriever.retrieve(case.prompt, dept=dept, role=role, top_k=top_k)
        retrieved = [chunk.id for chunk in chunks]
        hit = recall_at_k(case.expected_source_ids, retrieved, k=top_k)
        hits += int(hit)
        results.append(
            RetrievalCaseResult(
                prompt=case.prompt,
                expected=case.expected_source_ids,
                retrieved=retrieved,
                hit=hit,
            )
        )
    total = len(cases)
    rate = hits / total if total else 0.0
    return RetrievalEvalSummary(recall_at_5=rate, total=total, hits=hits, results=results)


async def judge_answer(
    provider: ChatProvider, model: str, query: str, answer: str, context: str
) -> bool:
    prompt = load_prompt("judge")
    user_content = prompt.user.format(context=context, query=query, answer=answer)
    messages = [
        ChatMessage(role="system", content=prompt.system),
        ChatMessage(role="user", content=user_content),
    ]
    verdict = await provider.chat(model, messages)
    return verdict.strip().lower().startswith("pass")


@dataclass(frozen=True)
class AnswerCaseResult:
    prompt: str
    answer: str
    first_token_s: float
    latency_s: float
    cost_usd: float
    judged_correct: bool


@dataclass(frozen=True)
class AnswerEvalSummary:
    results: list[AnswerCaseResult]

    @property
    def first_token_latencies_s(self) -> list[float]:
        return [result.first_token_s for result in self.results]

    @property
    def latencies_s(self) -> list[float]:
        return [result.latency_s for result in self.results]

    @property
    def costs_usd(self) -> list[float]:
        return [result.cost_usd for result in self.results]

    @property
    def judge_verdicts(self) -> list[bool]:
        return [result.judged_correct for result in self.results]

    @property
    def answers(self) -> list[str]:
        return [result.answer for result in self.results]


async def run_answer_eval(
    retriever: Retriever,
    provider: ChatProvider,
    models: ModelConfig,
    cases: list[GoldenCase],
    *,
    dept: str = EVAL_DEPT,
    role: str = EVAL_ROLE,
    top_k: int = 5,
) -> AnswerEvalSummary:
    """Measure the grounded answer path: latency, cost, and judge verdicts.

    Runs the same retrieve -> ground -> stream sequence the chat endpoint uses,
    timing the first token and the full answer and pricing the call from the
    served model. Skipping persistence keeps the eval out of conversation
    history. A judge model grades each answer against the context it was given.
    """
    grounding_model = models.models["grounding"]
    judge_model = models.models["judge"]
    results: list[AnswerCaseResult] = []
    for case in cases:
        chunks = await retriever.retrieve(case.prompt, dept=dept, role=role, top_k=top_k)
        messages, _version = build_grounding_messages(case.prompt, chunks)
        tokens_in = estimate_tokens("".join(message.content for message in messages))

        started = perf_counter()
        first_token_s = 0.0
        parts: list[str] = []
        async for token in provider.stream(grounding_model, messages):
            if not parts:
                first_token_s = perf_counter() - started
            parts.append(token)
        latency_s = perf_counter() - started
        answer = "".join(parts)

        tokens_out = estimate_tokens(answer)
        cost = float(compute_cost(provider.effective_model(grounding_model), tokens_in, tokens_out))
        judged = await judge_answer(
            provider, judge_model, case.prompt, answer, build_context(chunks)
        )
        results.append(
            AnswerCaseResult(
                prompt=case.prompt,
                answer=answer,
                first_token_s=first_token_s,
                latency_s=latency_s,
                cost_usd=cost,
                judged_correct=judged,
            )
        )
    return AnswerEvalSummary(results=results)


async def _main() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings
    from app.llm.client import get_provider

    settings = get_settings()
    if not settings.database_url or not settings.mistral_api_key:
        raise RuntimeError("DATABASE_URL and MISTRAL_API_KEY are required to run the eval")

    provider = get_provider()
    models = load_models()
    engine = create_async_engine(settings.database_url)

    async def embed(texts: list[str]) -> list[list[float]]:
        return await provider.embed(models.models["embed"], texts)

    retriever = Retriever(engine, embed)
    try:
        summary = await run_retrieval_eval(retriever, build_golden_set())
    finally:
        await engine.dispose()

    logger.info(
        "retrieval eval: recall@5=%.2f (%d/%d)", summary.recall_at_5, summary.hits, summary.total
    )
    for result in summary.results:
        if not result.hit:
            logger.info("miss: %s", redact_pii(result.prompt))


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
