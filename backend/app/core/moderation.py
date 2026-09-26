"""Moderation screen for user input and ingested content.

The deterministic redaction in ``app.core.redact`` is always on. This screen is
an assist: it flags abuse and personal data so the redaction layer and the
operators know when content carried it. It never blocks a request and never
raises, so a provider that is missing, throttled, or not granted on the account
tier degrades to "unchecked" instead of failing the turn.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from opentelemetry import metrics
from opentelemetry.metrics import Counter

from app.llm.provider import ChatProvider, ModerationVerdict

logger = logging.getLogger(__name__)

_counter: Counter | None = None


def _flagged_counter() -> Counter:
    global _counter
    if _counter is None:
        _counter = metrics.get_meter(__name__).create_counter(
            "moderation.flagged", description="Inputs flagged by the moderation screen"
        )
    return _counter


@dataclass(frozen=True)
class ScreenResult:
    checked: bool
    flagged: bool
    categories: tuple[str, ...] = ()


async def screen(provider: ChatProvider, model: str, text: str) -> ScreenResult:
    """Run the moderation screen over one text, degrading to unchecked on error."""
    if not text.strip():
        return ScreenResult(checked=False, flagged=False)
    try:
        verdicts = await provider.moderate(model, [text])
    except Exception as exc:  # noqa: BLE001 - a screen that cannot run must not fail the work
        logger.debug("moderation unavailable: %s", exc)
        return ScreenResult(checked=False, flagged=False)
    verdict: ModerationVerdict = verdicts[0] if verdicts else ModerationVerdict(flagged=False)
    return ScreenResult(checked=True, flagged=verdict.flagged, categories=verdict.categories)


def record_screen(result: ScreenResult, *, where: str, subject: str) -> None:
    """Log and count a flagged screen. A clean or unchecked result is a no-op."""
    if not result.flagged:
        return
    categories = ", ".join(result.categories) or "unspecified"
    logger.warning("moderation flagged %s (subject=%s): %s", where, subject, categories)
    _flagged_counter().add(1, {"where": where})
