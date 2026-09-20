from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    monkeypatch.setenv("MOCK_OIDC", "1")
    monkeypatch.setenv("DEV_PRINCIPAL_SUB", "test-user")
    monkeypatch.setenv("DEV_PRINCIPAL_EMAIL", "test@example.com")
    monkeypatch.setenv("DEV_PRINCIPAL_DEPT", "Engineering")
    monkeypatch.setenv("DEV_PRINCIPAL_ROLE", "employee")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    application = create_app()
    yield application
    get_settings.cache_clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
