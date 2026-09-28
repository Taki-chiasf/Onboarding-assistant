import hashlib
import hmac
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.ingest.webhooks import (
    IngestWebhookPayload,
    branch_ref,
    expected_signature,
    should_reingest,
    signature_header,
    source_label,
    verify_signature,
)
from app.main import create_app


def _sign(secret: str, body: bytes) -> str:
    return expected_signature(secret, body)


def test_expected_signature_is_sha256_hex() -> None:
    body = b'{"source":"repo"}'
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert expected_signature("secret", body) == f"sha256={digest}"


def test_verify_signature_accepts_only_the_matching_hmac() -> None:
    body = b'{"source":"repo"}'
    good = _sign("secret", body)
    assert verify_signature("secret", body, good)
    assert verify_signature("secret", body, f"  {good}  ")
    assert not verify_signature("secret", body, _sign("other", body))
    assert not verify_signature("secret", body, None)
    assert not verify_signature("secret", b'{"source":"drive"}', good)
    assert not verify_signature("", body, good)


def test_signature_header_prefers_the_github_header() -> None:
    assert signature_header({"x-hub-signature-256": "a"}) == "a"
    assert signature_header({"x-webhook-signature": "b"}) == "b"
    assert signature_header({"x-hub-signature-256": "a", "x-webhook-signature": "b"}) == "a"
    assert signature_header({}) is None


def test_branch_ref_normalizes() -> None:
    assert branch_ref("main") == "refs/heads/main"
    assert branch_ref("refs/heads/release") == "refs/heads/release"


def test_should_reingest_filters_branches_and_sources() -> None:
    push_main = IngestWebhookPayload(source="repo", ref="refs/heads/main")
    push_other = IngestWebhookPayload(source="repo", ref="refs/heads/feature")
    manual = IngestWebhookPayload(source="repo")
    drive = IngestWebhookPayload(source="drive", changed=["file:policies/a.md"])

    assert should_reingest(push_main, branch="main") == (True, None)
    assert should_reingest(push_other, branch="main") == (
        False,
        "ref is not the tracked branch",
    )
    assert should_reingest(manual, branch="main") == (True, None)
    assert should_reingest(drive, branch="main") == (True, None)


def test_source_label_names_the_repo_branch() -> None:
    assert source_label(IngestWebhookPayload(source="repo", ref="refs/heads/main")) == (
        "repo:refs/heads/main"
    )
    assert source_label(IngestWebhookPayload(source="drive")) == "drive"


def test_payload_rejects_unknown_sources_and_oversized_changes() -> None:
    with pytest.raises(ValidationError):
        IngestWebhookPayload(source="wiki")
    with pytest.raises(ValidationError):
        IngestWebhookPayload(source="drive", changed=[f"file:{i}" for i in range(501)])


def _app(monkeypatch: pytest.MonkeyPatch, **env: str) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from app.core.config import get_settings

    get_settings.cache_clear()
    return create_app()


async def _post(app: FastAPI, body: bytes, signature: str | None) -> Any:
    headers = {"content-type": "application/json"}
    if signature is not None:
        headers["x-hub-signature-256"] = signature
    return await _post_with_headers(app, body, headers)


async def _post_with_headers(app: FastAPI, body: bytes, headers: dict[str, str]) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/webhooks/ingest", content=body, headers=headers)


async def test_webhook_is_unconfigured_without_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, WEBHOOK_SECRET="")
    response = await _post(app, b'{"source":"drive"}', "sha256=x")
    assert response.status_code == 503


async def test_webhook_rejects_a_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, WEBHOOK_SECRET="s3cret")
    body = b'{"source":"drive"}'

    missing = await _post(app, body, None)
    assert missing.status_code == 401

    wrong = await _post(app, body, "sha256=deadbeef")
    assert wrong.status_code == 401


async def test_webhook_rejects_an_unknown_source(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, WEBHOOK_SECRET="s3cret")
    body = b'{"source":"wiki"}'
    response = await _post(app, body, _sign("s3cret", body))
    assert response.status_code == 422


async def test_webhook_ignores_other_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, WEBHOOK_SECRET="s3cret")
    body = b'{"source":"repo","ref":"refs/heads/feature","changed":["services/auth/app.py"]}'
    response = await _post(app, body, _sign("s3cret", body))

    assert response.status_code == 202
    payload = response.json()
    assert payload["queued"] is False
    assert payload["reason"] == "ref is not the tracked branch"
    assert payload["job_id"] is None


class _FakeSession:
    def __init__(self, added: list[Any]) -> None:
        self._added = added

    def add(self, obj: Any) -> None:
        self._added.append(obj)

    async def commit(self) -> None:
        return None

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


async def test_webhook_records_and_queues_a_verified_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(monkeypatch, WEBHOOK_SECRET="s3cret")
    added: list[Any] = []
    queued: list[str] = []
    monkeypatch.setattr(
        "app.api.webhooks.async_sessionmaker",
        lambda engine, expire_on_commit: lambda: _FakeSession(added),
    )
    monkeypatch.setattr("app.api.webhooks.enqueue_reingest", queued.append)
    app.state.engine = cast(AsyncEngine, object())

    body = b'{"source":"repo","ref":"refs/heads/main","changed":["services/auth/app.py"]}'
    response = await _post(app, body, _sign("s3cret", body))

    assert response.status_code == 202
    payload = response.json()
    assert payload["queued"] is True
    assert payload["source"] == "repo"
    assert uuid.UUID(payload["job_id"])
    assert queued == [payload["job_id"]]
    assert len(added) == 1
    job = added[0]
    assert job.source_uri == "repo:refs/heads/main"
    assert job.status == "queued"
    assert job.started_at is not None


async def test_webhook_marks_the_job_failed_when_the_queue_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(monkeypatch, WEBHOOK_SECRET="s3cret")
    marked: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "app.api.webhooks.async_sessionmaker",
        lambda engine, expire_on_commit: lambda: _FakeSession([]),
    )

    def boom(job_id: str) -> None:
        raise RuntimeError("redis is down")

    async def record(job_id: str, *, status: str, **kwargs: Any) -> None:
        marked.append({"job_id": job_id, "status": status, **kwargs})

    monkeypatch.setattr("app.api.webhooks.enqueue_reingest", boom)
    monkeypatch.setattr("app.api.webhooks.mark_job", record)
    app.state.engine = cast(AsyncEngine, object())

    body = b'{"source":"drive","changed":["file:policies/a.md"]}'
    response = await _post(app, body, _sign("s3cret", body))

    assert response.status_code == 502
    assert marked and marked[0]["status"] == "failed"
    assert "enqueue failed" in marked[0]["error"]


_LIVE_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture
async def live_engine() -> AsyncIterator[AsyncEngine]:
    from sqlalchemy.ext.asyncio import create_async_engine

    if not _LIVE_DB_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    engine = create_async_engine(_LIVE_DB_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_webhook_queues_live_and_marks_job_progress(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> None:
    from sqlalchemy import delete, select

    from app.core.config import get_settings
    from app.ingest.tasks import mark_job
    from app.models import IngestJob

    app = _app(monkeypatch, WEBHOOK_SECRET="s3cret")
    # _app clears DATABASE_URL for offline apps; point it back at the live
    # database so mark_job can advance the row the endpoint wrote.
    monkeypatch.setenv("DATABASE_URL", _LIVE_DB_URL)
    get_settings.cache_clear()
    app.state.engine = live_engine
    queued: list[str] = []
    monkeypatch.setattr("app.api.webhooks.enqueue_reingest", queued.append)

    body = b'{"source":"repo","ref":"refs/heads/main"}'
    response = await _post(app, body, _sign("s3cret", body))
    assert response.status_code == 202
    job_id = uuid.UUID(response.json()["job_id"])
    assert queued == [str(job_id)]

    factory = async_sessionmaker(live_engine, expire_on_commit=False)
    try:
        async with factory() as session:
            job = await session.get(IngestJob, job_id)
            assert job is not None
            assert job.status == "queued"
            assert job.finished_at is None

        await mark_job(str(job_id), status="running")
        await mark_job(str(job_id), status="done", rows_written=7)

        async with factory() as session:
            job = await session.get(IngestJob, job_id)
            assert job is not None
            assert job.status == "done"
            assert job.rows_written == 7
            assert job.finished_at is not None
            reloaded = (
                await session.execute(select(IngestJob).where(IngestJob.id == job_id))
            ).scalar_one()
            assert reloaded.source_uri == "repo:refs/heads/main"
    finally:
        async with factory() as session:
            await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
            await session.commit()
        get_settings.cache_clear()
