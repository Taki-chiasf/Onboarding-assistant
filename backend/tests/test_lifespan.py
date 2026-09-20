import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.main import lifespan


async def test_lifespan_without_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()

    app = FastAPI()
    async with lifespan(app):
        assert app.state.engine is None
        assert app.state.redis is None
        assert app.state.ready_checks == []

    get_settings.cache_clear()


async def test_lifespan_with_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/x")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()

    app = FastAPI()
    async with lifespan(app):
        assert app.state.engine is not None
        assert app.state.redis is not None
        assert len(app.state.ready_checks) == 2

    get_settings.cache_clear()
