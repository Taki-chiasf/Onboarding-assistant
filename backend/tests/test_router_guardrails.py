from app.router.guardrails import keyword_override, resolve_verdict
from app.router.schema import Intent, RouterVerdict, Surface


def _verdict(**overrides: object) -> RouterVerdict:
    data: dict[str, object] = {"intent": "rag-docs", "confidence": 0.9}
    data.update(overrides)
    return RouterVerdict.model_validate(data)


def test_keyword_override_detects_structured_questions() -> None:
    assert keyword_override("Who is the lead of the Data team?") == Intent.TEXT_TO_SQL
    assert keyword_override("How do I connect to the VPN?") == Intent.RAG_DOCS
    assert keyword_override("banana smoothie recipe") is None


def test_low_confidence_with_keyword_match_overrides() -> None:
    decision = resolve_verdict("Who is the lead of the Data team?", _verdict(confidence=0.3))

    assert decision.intent == Intent.TEXT_TO_SQL
    assert decision.source == "keyword_override"
    assert decision.surfaces == [Surface.TEXT_TO_SQL]


def test_low_confidence_without_match_becomes_ambiguous() -> None:
    decision = resolve_verdict("banana smoothie recipe", _verdict(confidence=0.3))

    assert decision.intent == Intent.AMBIGUOUS
    assert decision.source == "low_confidence"
    assert decision.clarify is not None


def test_keyword_never_overrides_confident_verdict() -> None:
    decision = resolve_verdict(
        "How do I request leave?",
        _verdict(intent="text-to-sql", confidence=0.9, surfaces=["text-to-sql"]),
    )

    assert decision.intent == Intent.TEXT_TO_SQL
    assert decision.source == "router"


def test_two_surfaces_disambiguate() -> None:
    decision = resolve_verdict(
        "tell me about the team",
        _verdict(
            intent="rag-docs",
            confidence=0.8,
            surfaces=["rag-docs", "text-to-sql"],
        ),
    )

    assert decision.intent == Intent.AMBIGUOUS
    assert decision.source == "surface_disambiguation"
    assert decision.clarify is not None
    assert decision.clarify.kind == "surface"
    assert len(decision.clarify.options) == 2


def test_secondary_intent_disambiguates() -> None:
    decision = resolve_verdict(
        "what is the leave policy and who took leave",
        _verdict(intent="rag-docs", confidence=0.6, secondary="text-to-sql", surfaces=["rag-docs"]),
    )

    assert decision.intent == Intent.AMBIGUOUS
    assert decision.source == "interpretation_disambiguation"
    assert decision.clarify is not None
    assert decision.clarify.kind == "interpretation"


def test_out_of_scope_passes_through() -> None:
    decision = resolve_verdict(
        "what is the weather", _verdict(intent="out-of-scope", confidence=0.9)
    )

    assert decision.intent == Intent.OUT_OF_SCOPE
    assert decision.source == "router"
    assert decision.clarify is None


def test_single_surface_passthrough_fills_default_surface() -> None:
    decision = resolve_verdict("how much leave", _verdict(intent="rag-docs", confidence=0.9))

    assert decision.intent == Intent.RAG_DOCS
    assert decision.surfaces == [Surface.RAG_DOCS]
