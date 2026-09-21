from decimal import Decimal

from app.llm.pricing import compute_cost, estimate_tokens


def test_estimate_tokens_approximates_length() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 100) == 25
    assert estimate_tokens("") == 1


def test_compute_cost_uses_price_table() -> None:
    cost = compute_cost("mistral-large-2512", 1_000_000, 1_000_000)
    assert cost == Decimal("2.000000")


def test_compute_cost_unknown_model_is_zero() -> None:
    assert compute_cost("unknown-model", 1000, 1000) == Decimal("0")
