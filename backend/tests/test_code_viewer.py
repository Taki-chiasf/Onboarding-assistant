import os
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.api.code import corpus_relative_path, resolve_corpus_file
from app.core.config import get_settings
from app.main import create_app
from app.models import DocChunk
from app.rag import chunk_id, content_hash

CODE_SOURCE = "file:code/services/auth/tokens.py"


def test_corpus_relative_path_accepts_plain_relative_sources() -> None:
    assert corpus_relative_path(CODE_SOURCE) == "code/services/auth/tokens.py"
    assert corpus_relative_path("file:code/README.md") == "code/README.md"


def test_corpus_relative_path_rejects_escapes() -> None:
    assert corpus_relative_path("code/README.md") is None
    assert corpus_relative_path("file:") is None
    assert corpus_relative_path("file:/etc/passwd") is None
    assert corpus_relative_path("file:code/../../etc/passwd") is None
    assert corpus_relative_path("file:code/./README.md") is None


def test_resolve_corpus_file_stays_inside_the_corpus() -> None:
    resolved = resolve_corpus_file(CODE_SOURCE)
    assert resolved is not None
    assert resolved.name == "tokens.py"

    assert resolve_corpus_file("file:code/nope.py") is None
    assert resolve_corpus_file("file:code/../../pyproject.toml") is None


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Connection:
    def __init__(self, value: object, calls: list[dict[str, object]]) -> None:
        self._value = value
        self._calls = calls

    async def execute(self, statement: object, params: dict[str, object]) -> _Result:
        self._calls.append(params)
        return _Result(self._value)

    async def __aenter__(self) -> "_Connection":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class _Engine:
    def __init__(self, value: object) -> None:
        self._value = value
        self.calls: list[dict[str, object]] = []

    def connect(self) -> _Connection:
        return _Connection(self._value, self.calls)


def _app(monkeypatch: pytest.MonkeyPatch, **env: str) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return create_app()


async def _get(app: FastAPI, path: str) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_code_file_requires_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1")
    response = await _get(app, f"/api/code/file?source_uri={CODE_SOURCE}")
    assert response.status_code == 503


async def test_code_file_hides_unindexed_and_invisible_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1")
    app.state.engine = cast(AsyncEngine, _Engine(None))

    not_visible = await _get(app, f"/api/code/file?source_uri={CODE_SOURCE}")
    assert not_visible.status_code == 404

    traversal = await _get(app, "/api/code/file?source_uri=file:code/../../pyproject.toml")
    assert traversal.status_code == 404

    missing = await _get(app, "/api/code/file?source_uri=file:code/nope.py")
    assert missing.status_code == 404


async def test_code_file_returns_content_and_line_range(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1")
    engine = _Engine(1)
    app.state.engine = cast(AsyncEngine, engine)

    response = await _get(app, f"/api/code/file?source_uri={CODE_SOURCE}&start=45&end=60")

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "code/services/auth/tokens.py"
    assert body["language"] == "python"
    assert "def verify_token" in body["content"]
    assert body["start_line"] == 45
    assert body["end_line"] == 60
    assert body["line_count"] > 1
    assert body["truncated"] is False
    assert engine.calls
    assert engine.calls[0]["dept"] == "dept:Engineering"
    assert engine.calls[0]["roles"] == ["role:employee"]


async def test_code_file_normalizes_the_line_range(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1")
    app.state.engine = cast(AsyncEngine, _Engine(1))

    response = await _get(app, f"/api/code/file?source_uri={CODE_SOURCE}&start=0&end=-5")

    body = response.json()
    assert body["start_line"] == 1
    assert body["end_line"] == 1


_LIVE_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture
async def live_engine() -> AsyncIterator[AsyncEngine]:
    if not _LIVE_DB_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    engine = create_async_engine(_LIVE_DB_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


def _live_app(monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine, **env: str) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", _LIVE_DB_URL)
    monkeypatch.setenv("MOCK_OIDC", "1")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    application = create_app()
    application.state.engine = engine
    return application


async def test_code_file_checks_the_index_acl(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    chunk = DocChunk(
        id=chunk_id(CODE_SOURCE, 0),
        source_uri=CODE_SOURCE,
        source_type="code",
        section_anchor="L45-L60 verify_token",
        acl_tags=["dept:Engineering", "role:employee"],
        embedding=[0.0] * 1024,
        content="def verify_token(settings, token): ...",
        content_hash=content_hash("def verify_token(settings, token): ..."),
        chunk_index=0,
        version=1,
    )
    factory = async_sessionmaker(live_engine, expire_on_commit=False)
    inserted = False
    async with factory() as session:
        # A seeded database may already index the corpus file; use its chunk
        # and leave it in place, otherwise insert one for this test.
        if await session.get(DocChunk, chunk.id) is None:
            session.add(chunk)
            await session.commit()
            inserted = True

    try:
        engineering = _live_app(monkeypatch, live_engine)
        allowed = await _get(
            engineering, f"/api/code/file?source_uri={CODE_SOURCE}&start=45&end=60"
        )
        assert allowed.status_code == 200
        assert "def verify_token" in allowed.json()["content"]

        finance = _live_app(monkeypatch, live_engine, DEV_PRINCIPAL_DEPT="Finance")
        denied = await _get(finance, f"/api/code/file?source_uri={CODE_SOURCE}")
        assert denied.status_code == 404
    finally:
        if inserted:
            async with factory() as session:
                await session.execute(delete(DocChunk).where(DocChunk.id == chunk.id))
                await session.commit()
        get_settings.cache_clear()
