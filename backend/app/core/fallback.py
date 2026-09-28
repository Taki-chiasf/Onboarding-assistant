"""Deterministic fallback detection shared by the answer paths and the console.

A stored answer can be the deterministic no-evidence copy or the model's own
phrasing of it, so detection normalizes case and trailing punctuation. Kept out
of the eval package because the serving paths also mark fallback answers with
it, and out of the answer modules so both answer paths can share it without an
import cycle.
"""

from __future__ import annotations

FALLBACK_TEXTS = ("i don't know", "i do not know", "no matching records")


def normalized_answer(answer: str) -> str:
    return answer.strip().lower().rstrip(".!? ")


def is_dont_know(answer: str) -> bool:
    return normalized_answer(answer) in FALLBACK_TEXTS
