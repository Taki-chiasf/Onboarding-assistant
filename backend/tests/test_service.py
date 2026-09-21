import pytest

from app.core.config import get_settings
from app.ingest.service import run_ingest


async def test_run_ingest_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await run_ingest()
    get_settings.cache_clear()


async def test_run_ingest_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://example")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        await run_ingest()
    get_settings.cache_clear()
