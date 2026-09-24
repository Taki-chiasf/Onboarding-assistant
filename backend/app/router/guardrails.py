"""Deterministic guardrails around the router verdict.

The model's verdict is never trusted on its own. These rules pin the ordering
the product depends on: a keyword override is only consulted when confidence is
already below the floor, it never overrides a confident verdict, and the two
disambiguation cases (two answer surfaces, or a plausible second intent) resolve
to ``ambiguous`` with concrete options for the user to pick from.
"""

from __future__ import annotations

import re

from app.router.schema import (
    SURFACE_LABELS,
    ClarifyOption,
    ClarifyPrompt,
    Intent,
    RouteDecision,
    RouterVerdict,
    RouteSource,
    Surface,
)

LOW_CONFIDENCE = 0.5
SURFACE_CONFIDENCE = 0.75
INTERPRETATION_CONFIDENCE = 0.75
MAX_CLARIFY_OPTIONS = 3

SURFACE_DISAMBIGUATION_QUESTION = (
    "Do you want the answer from our documents, or from live company data?"
)
INTERPRETATION_DISAMBIGUATION_QUESTION = "Which of these do you mean?"

SURFACE_BY_INTENT: dict[Intent, Surface] = {
    Intent.RAG_DOCS: Surface.RAG_DOCS,
    Intent.RAG_CODE: Surface.RAG_CODE,
    Intent.TEXT_TO_SQL: Surface.TEXT_TO_SQL,
}
ALL_SURFACES: tuple[Surface, ...] = (
    Surface.RAG_DOCS,
    Surface.RAG_CODE,
    Surface.TEXT_TO_SQL,
)

_TEXT_TO_SQL_PATTERNS = (
    re.compile(r"\bwho(?:'s| is| are)\b[^?]*\b(lead|manager|owner|head)\b", re.IGNORECASE),
    re.compile(r"\b(lead|manager|owner|head) of\b", re.IGNORECASE),
    re.compile(
        r"\bhow many\s+(projects|tickets|assets|members|employees|people|okrs?|objectives)\b",
        re.IGNORECASE,
    ),
)

_RAG_DOCS_PATTERNS = (
    re.compile(r"\bhow do i\b", re.IGNORECASE),
    re.compile(r"\bwhere (?:is|are|can i find)\b", re.IGNORECASE),
    re.compile(r"\b(policy|handbook|runbook|guide|procedure)\b", re.IGNORECASE),
)


def keyword_override(query: str) -> Intent | None:
    """Best-effort intent for a low-confidence verdict, or None when unsure."""
    if any(pattern.search(query) for pattern in _TEXT_TO_SQL_PATTERNS):
        return Intent.TEXT_TO_SQL
    if any(pattern.search(query) for pattern in _RAG_DOCS_PATTERNS):
        return Intent.RAG_DOCS
    return None


def _dedupe_surfaces(surfaces: list[Surface]) -> list[Surface]:
    ordered: list[Surface] = []
    for surface in surfaces:
        if surface not in ordered:
            ordered.append(surface)
    return ordered


def _option(surface: Surface) -> ClarifyOption:
    return ClarifyOption(surface=surface, label=SURFACE_LABELS[surface])


def _surface_options(surfaces: list[Surface]) -> list[ClarifyOption]:
    candidates = _dedupe_surfaces(surfaces) or list(ALL_SURFACES)
    return [_option(surface) for surface in candidates[:MAX_CLARIFY_OPTIONS]]


def _surface_clarify(surfaces: list[Surface]) -> ClarifyPrompt:
    return ClarifyPrompt(
        kind="surface",
        question=SURFACE_DISAMBIGUATION_QUESTION,
        options=_surface_options(surfaces),
    )


def _coerce_surface(value: str) -> Surface | None:
    try:
        return Surface(value)
    except ValueError:
        pass
    try:
        return SURFACE_BY_INTENT.get(Intent(value))
    except ValueError:
        return None


def _interpretation_clarify(verdict: RouterVerdict) -> ClarifyPrompt:
    candidates: list[Surface] = list(verdict.surfaces)
    primary = SURFACE_BY_INTENT.get(verdict.intent)
    if primary is not None:
        candidates.append(primary)
    secondary = _coerce_surface(verdict.secondary)
    if secondary is not None:
        candidates.append(secondary)

    options = _surface_options(candidates)
    if len(options) < 2:
        return _surface_clarify(candidates)
    return ClarifyPrompt(
        kind="interpretation",
        question=INTERPRETATION_DISAMBIGUATION_QUESTION,
        options=options,
    )


def _ambiguous(
    verdict: RouterVerdict, source: RouteSource, clarify: ClarifyPrompt
) -> RouteDecision:
    return RouteDecision(
        intent=Intent.AMBIGUOUS,
        confidence=verdict.confidence,
        surfaces=verdict.surfaces,
        entities=verdict.entities,
        rationale=verdict.rationale,
        source=source,
        clarify=clarify,
    )


def resolve_verdict(query: str, verdict: RouterVerdict) -> RouteDecision:
    """Apply the guardrail ordering to a parsed verdict."""
    if verdict.confidence < LOW_CONFIDENCE:
        override = keyword_override(query)
        if override is not None:
            surface = SURFACE_BY_INTENT[override]
            return RouteDecision(
                intent=override,
                confidence=verdict.confidence,
                surfaces=[surface],
                entities=verdict.entities,
                rationale=verdict.rationale,
                source="keyword_override",
            )
        return _ambiguous(verdict, "low_confidence", _interpretation_clarify(verdict))

    if len(_dedupe_surfaces(verdict.surfaces)) >= 2 and verdict.confidence >= SURFACE_CONFIDENCE:
        return _ambiguous(verdict, "surface_disambiguation", _surface_clarify(verdict.surfaces))

    if verdict.secondary.strip() and verdict.confidence < INTERPRETATION_CONFIDENCE:
        return _ambiguous(
            verdict, "interpretation_disambiguation", _interpretation_clarify(verdict)
        )

    if verdict.intent == Intent.AMBIGUOUS:
        return _ambiguous(verdict, "router", _interpretation_clarify(verdict))

    surfaces = _dedupe_surfaces(verdict.surfaces)
    if not surfaces and verdict.intent in SURFACE_BY_INTENT:
        surfaces = [SURFACE_BY_INTENT[verdict.intent]]
    return RouteDecision(
        intent=verdict.intent,
        confidence=verdict.confidence,
        surfaces=surfaces,
        entities=verdict.entities,
        rationale=verdict.rationale,
        source="router",
    )
