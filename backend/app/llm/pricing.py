"""Approximate inference pricing for cost accounting.

Prices are list prices in USD per million tokens (input, output), used only to
populate the cost ledger; they are estimates and not a billing source.
"""

from __future__ import annotations

from decimal import Decimal

PRICE_PER_MILLION: dict[str, tuple[float, float]] = {
    "mistral-large-2512": (0.5, 1.5),
    "mistral-small-2603": (0.15, 0.6),
    "codestral-2508": (0.3, 0.9),
    "magistral-medium-2509": (0.6, 1.8),
    "magistral-small-2509": (0.5, 1.5),
    "mistral-embed": (0.1, 0.1),
    "mistral-ocr-4-0": (0.0, 0.0),
    "mistral-moderation-2603": (0.0, 0.0),
}


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    in_price, out_price = PRICE_PER_MILLION.get(model, (0.0, 0.0))
    total = (in_price * tokens_in + out_price * tokens_out) / 1_000_000.0
    return Decimal(str(round(total, 6)))
