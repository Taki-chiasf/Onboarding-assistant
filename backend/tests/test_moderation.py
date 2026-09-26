from typing import cast

from app.core.moderation import ScreenResult, record_screen, screen
from app.llm.fake import FakeProvider
from app.llm.provider import ChatProvider, ModerationVerdict


async def test_screen_reports_checked_and_clean_by_default() -> None:
    result = await screen(FakeProvider(), "mistral-moderation-2603", "how much leave?")
    assert result.checked
    assert not result.flagged


async def test_screen_flags_categories_from_the_provider() -> None:
    provider = FakeProvider(
        moderate_fn=lambda text: ModerationVerdict(flagged=True, categories=("pii",))
    )
    result = await screen(provider, "mistral-moderation-2603", "my iban is ...")
    assert result.checked
    assert result.flagged
    assert result.categories == ("pii",)


async def test_screen_skips_empty_text() -> None:
    provider = FakeProvider(moderate_fn=lambda text: ModerationVerdict(flagged=True))
    result = await screen(provider, "mistral-moderation-2603", "   ")
    assert not result.checked
    assert not result.flagged


async def test_screen_degrades_when_the_provider_errors() -> None:
    class _Boom:
        async def moderate(self, model: str, texts: list[str]) -> list[ModerationVerdict]:
            raise RuntimeError("model not granted on this tier")

    result = await screen(cast(ChatProvider, _Boom()), "mistral-moderation-2603", "hello")
    assert not result.checked
    assert not result.flagged


def test_record_screen_is_a_noop_when_clean() -> None:
    record_screen(ScreenResult(checked=True, flagged=False), where="prompt", subject="alex")
