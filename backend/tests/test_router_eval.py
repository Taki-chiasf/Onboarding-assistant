from app.eval.router_eval import (
    expected_verdict,
    make_keyless_provider,
    question_from_messages,
    run_router_eval,
)
from app.eval.router_golden import RouterCase, build_router_set
from app.llm.provider import ChatMessage
from app.router.router import IntentRouter
from app.router.schema import Intent


def test_expected_verdict_shapes_per_intent() -> None:
    docs = expected_verdict(RouterCase("q", Intent.RAG_DOCS.value, ()))
    assert docs["intent"] == "rag-docs"
    assert docs["surfaces"] == ["rag-docs"]

    oos = expected_verdict(RouterCase("q", Intent.OUT_OF_SCOPE.value, ()))
    assert oos["intent"] == "out-of-scope"

    amb = expected_verdict(RouterCase("q", Intent.AMBIGUOUS.value, ()))
    assert amb["intent"] == "ambiguous"
    assert amb["surfaces"] == ["rag-docs", "text-to-sql"]


def test_question_from_messages_extracts_prompt() -> None:
    messages = [ChatMessage(role="user", content="Question: who leads Data?")]
    assert question_from_messages(messages) == "who leads Data?"


async def test_keyless_replay_is_fully_accurate() -> None:
    cases = build_router_set()
    router = IntentRouter(make_keyless_provider(cases), "fake-router")

    summary = await run_router_eval(router, cases)

    assert summary.total == len(cases)
    assert summary.accuracy == 1.0

    boundary_correct, boundary_total = summary.ambiguous_boundary()
    assert boundary_total > 0
    assert boundary_correct == boundary_total

    per_intent = summary.by_intent()
    assert set(per_intent) == {intent.value for intent in Intent}
