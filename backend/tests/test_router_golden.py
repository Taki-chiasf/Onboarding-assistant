from app.eval.router_golden import build_router_set
from app.router.schema import Intent

MIN_CASES = 200


def test_router_set_has_minimum_coverage() -> None:
    cases = build_router_set()
    assert len(cases) >= MIN_CASES


def test_router_set_covers_all_intents() -> None:
    intents = {case.expected_intent for case in build_router_set()}
    assert intents == {intent.value for intent in Intent}


def test_router_set_has_no_duplicate_prompts() -> None:
    prompts = [case.prompt for case in build_router_set()]
    assert len(prompts) == len(set(prompts))


def test_router_set_includes_boundary_and_traps() -> None:
    cases = build_router_set()
    assert any("trap" in case.tags for case in cases)
    assert any("injection" in case.tags for case in cases)
    assert any(case.expected_intent == Intent.AMBIGUOUS.value for case in cases)
