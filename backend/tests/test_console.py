import base64
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api.admin import get_session_factory
from app.api.console import parse_tempo_trace, previous_question
from app.core.config import get_settings
from app.core.otel import current_trace_id
from app.eval.report import DONT_KNOW_ANSWERS
from app.main import create_app
from app.models import Conversation, Feedback, IngestJob, Message, NightlyEvalRun

CITE_OR_DIE = sorted(DONT_KNOW_ANSWERS)[0]


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _StubSession:
    def __init__(self, results: list[_Rows]) -> None:
        self._results = list(results)

    async def execute(self, statement: object) -> _Rows:
        return self._results.pop(0)

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _app(monkeypatch: pytest.MonkeyPatch, **env: str) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return create_app()


def _use_session(app: FastAPI, session: _StubSession) -> None:
    app.dependency_overrides[get_session_factory] = lambda: lambda: session


async def _get(app: FastAPI, path: str) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get(path)


def test_is_dont_know_normalizes_punctuation_and_case() -> None:
    from app.core.fallback import is_dont_know

    assert is_dont_know("I don't know")
    assert is_dont_know("I don't know.")
    assert is_dont_know("  No matching records.  ")
    assert not is_dont_know("I don't know the exact date, but roughly two weeks.")
    assert not is_dont_know("16 weeks")


def test_attention_reasons_flag_the_phrased_fallback() -> None:
    from app.api.console import attention_reasons

    assert attention_reasons("I don't know.", 0.9) == ["dont_know"]
    assert attention_reasons("16 weeks", 0.4) == ["low_confidence"]
    assert attention_reasons("16 weeks", 0.9) == []


def test_current_trace_id_reads_the_active_span() -> None:
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("turn") as span:
        trace_id = current_trace_id()
        assert trace_id == f"{span.get_span_context().trace_id:032x}"
        assert len(trace_id) == 32


def test_previous_question_pairs_the_latest_question_before_the_answer() -> None:
    conversation_id = uuid.uuid4()
    asked = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    index = {
        conversation_id: [
            (asked - timedelta(minutes=10), "first question"),
            (asked - timedelta(minutes=5), "second question"),
            (asked + timedelta(minutes=1), "later question"),
        ]
    }
    assert previous_question(index, conversation_id, asked) == "second question"
    assert previous_question(index, uuid.uuid4(), asked) is None


async def test_console_endpoints_require_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="employee")
    for path in ("/api/admin/ingest", "/api/admin/attention", "/api/admin/eval"):
        resp = await _get(app, path)
        assert resp.status_code == 403, path
    get_settings.cache_clear()


async def test_console_endpoints_need_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    for path in ("/api/admin/ingest", "/api/admin/attention", "/api/admin/eval"):
        resp = await _get(app, path)
        assert resp.status_code == 503, path
    get_settings.cache_clear()


async def test_ingest_status_serializes_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    ingested = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    job = SimpleNamespace(
        id=uuid.uuid4(),
        source_uri="repo:refs/heads/main",
        status="done",
        rows_written=4,
        error=None,
        started_at=ingested,
        finished_at=ingested + timedelta(seconds=30),
    )
    session = _StubSession(
        [
            _Rows(
                [
                    ("file:policies/a.md", "policy", 3, ingested),
                    ("file:runbooks/b.md", "runbook", 2, ingested + timedelta(minutes=5)),
                ]
            ),
            _Rows([job]),
        ]
    )
    _use_session(app, session)
    try:
        resp = await _get(app, "/api/admin/ingest")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_chunks"] == 5
    assert body["total_sources"] == 2
    assert body["sources"][0]["source_uri"] == "file:policies/a.md"
    assert body["sources"][0]["chunks"] == 3
    assert body["last_ingested"].startswith("2026-09-28T10:05")
    assert body["jobs"] == [
        {
            "id": str(job.id),
            "source_uri": "repo:refs/heads/main",
            "status": "done",
            "rows_written": 4,
            "error": None,
            "started_at": "2026-09-28T10:00:00+00:00",
            "finished_at": "2026-09-28T10:00:30+00:00",
        }
    ]
    get_settings.cache_clear()


async def test_attention_list_maps_reasons_and_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    conversation_id = uuid.uuid4()
    asked = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    answer = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role="assistant",
        content=CITE_OR_DIE,
        trace_id="trace-1",
        detail={"fallback": True, "route": {"intent": "ambiguous", "router_confidence": 0.2}},
        created_at=asked,
    )
    question = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role="user",
        content="How many days of leave?",
        created_at=asked - timedelta(seconds=5),
    )
    session = _StubSession(
        [
            _Rows([(answer, "alex-chen", None)]),
            _Rows(
                [
                    (
                        question.id,
                        conversation_id,
                        question.content,
                        question.created_at,
                        None,
                    )
                ]
            ),
        ]
    )
    _use_session(app, session)
    try:
        resp = await _get(app, "/api/admin/attention")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["question"] == "How many days of leave?"
    assert item["reasons"] == ["dont_know", "low_confidence"]
    assert item["intent"] == "ambiguous"
    assert item["confidence"] == 0.2
    assert item["user_id"] == "alex-chen"
    assert item["trace_id"] == "trace-1"
    get_settings.cache_clear()


async def test_eval_history_serializes_runs_and_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    early = NightlyEvalRun(
        id=uuid.uuid4(),
        run_at=datetime(2026, 9, 27, 2, 0, tzinfo=UTC),
        passed=True,
        strict=False,
        keyless=False,
        streak=1,
        metrics={"router_accuracy": 0.92},
        regressions=[],
    )
    late = NightlyEvalRun(
        id=uuid.uuid4(),
        run_at=datetime(2026, 9, 28, 2, 0, tzinfo=UTC),
        passed=False,
        strict=True,
        keyless=False,
        streak=0,
        metrics={"router_accuracy": 0.85},
        sections={"router": {"total": 232}},
        regressions=["router_accuracy"],
    )
    session = _StubSession([_Rows([late, early]), _Rows([("real", 3), ("synthetic", 54)])])
    _use_session(app, session)
    try:
        resp = await _get(app, "/api/admin/eval")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert [run["run_at"][:10] for run in body["runs"]] == ["2026-09-27", "2026-09-28"]
    assert body["runs"][1]["regressions"] == ["router_accuracy"]
    assert body["runs"][1]["metrics"]["router_accuracy"] == 0.85
    assert body["feedback"] == {"real": 3, "synthetic": 54}
    assert body["latest_sections"] == {"router": {"total": 232}}
    assert body["gate_targets"]["router_accuracy"] == {"target": 0.9, "direction": "min"}
    get_settings.cache_clear()


def _tempo_payload() -> dict[str, Any]:
    def span_id(raw: bytes) -> str:
        return base64.b64encode(raw).decode()

    parent = b"parent-span-0001"
    child = b"child-span-00001"
    return {
        "batches": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "app.router"},
                        "spans": [
                            {
                                "traceId": span_id(b"trace-id-0000001"),
                                "spanId": span_id(child),
                                "parentSpanId": span_id(parent),
                                "name": "retrieve",
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": "1000500000",
                                "endTimeUnixNano": "1002500000",
                                "attributes": [
                                    {"key": "retrieve.top_k", "value": {"intValue": "5"}},
                                ],
                                "status": {"code": "STATUS_CODE_ERROR", "message": "boom"},
                            },
                            {
                                "traceId": span_id(b"trace-id-0000001"),
                                "spanId": span_id(parent),
                                "parentSpanId": "",
                                "name": "chat",
                                "kind": "SPAN_KIND_SERVER",
                                "startTimeUnixNano": "1000000000",
                                "endTimeUnixNano": "1003000000",
                                "attributes": [
                                    {"key": "user.dept", "value": {"stringValue": "Engineering"}},
                                ],
                                "status": {},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def test_parse_tempo_trace_flattens_and_orders_spans() -> None:
    view = parse_tempo_trace("abc", _tempo_payload())

    assert view.found is True
    assert [span.name for span in view.spans] == ["chat", "retrieve"]
    root, child = view.spans
    assert root.start_ms == 0.0
    assert root.duration_ms == 3.0
    assert root.kind == "server"
    assert root.status == "unset"
    assert root.attributes == {"user.dept": "Engineering"}
    assert child.start_ms == 0.5
    assert child.duration_ms == 2.0
    assert child.status == "error"
    assert child.attributes["retrieve.top_k"] == "5"
    assert child.span_id == b"child-span-00001".hex()
    assert child.parent_span_id == b"parent-span-0001".hex()
    assert root.parent_span_id is None


def test_parse_tempo_trace_reports_a_missing_trace() -> None:
    view = parse_tempo_trace("abc", {"batches": []})
    assert view.found is False
    assert view.spans == []


async def test_trace_view_requires_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin")
    resp = await _get(app, "/api/admin/traces/abc")
    assert resp.status_code == 503
    get_settings.cache_clear()


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    def __init__(
        self, response: _FakeResponse | None = None, error: bool = False, **_: Any
    ) -> None:
        self._response = response or _FakeResponse(200)
        self._error = error
        self.urls: list[str] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def get(self, url: str) -> _FakeResponse:
        self.urls.append(url)
        if self._error:
            import httpx

            raise httpx.ConnectError("down")
        return self._response


async def test_trace_view_parses_the_backend_response(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(
        monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin", TEMPO_URL="http://tempo:3200"
    )
    client = _FakeAsyncClient(_FakeResponse(200, _tempo_payload()))
    monkeypatch.setattr("app.api.console.httpx.AsyncClient", lambda **_: client)
    try:
        resp = await _get(app, "/api/admin/traces/trace-abc")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["spans"][0]["name"] == "chat"
    assert client.urls == ["http://tempo:3200/api/traces/trace-abc"]
    get_settings.cache_clear()


async def test_trace_view_handles_missing_and_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(
        monkeypatch, MOCK_OIDC="1", DEV_PRINCIPAL_ROLE="admin", TEMPO_URL="http://tempo:3200"
    )
    monkeypatch.setattr(
        "app.api.console.httpx.AsyncClient", lambda **_: _FakeAsyncClient(_FakeResponse(404))
    )
    missing = await _get(app, "/api/admin/traces/nope")
    assert missing.status_code == 200
    assert missing.json() == {"trace_id": "nope", "found": False, "spans": []}

    monkeypatch.setattr(
        "app.api.console.httpx.AsyncClient", lambda **_: _FakeAsyncClient(error=True)
    )
    down = await _get(app, "/api/admin/traces/nope")
    assert down.status_code == 502
    get_settings.cache_clear()


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


def _live_app(monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", _LIVE_DB_URL)
    monkeypatch.setenv("MOCK_OIDC", "1")
    monkeypatch.setenv("DEV_PRINCIPAL_ROLE", "admin")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    application = create_app()
    application.state.engine = engine
    return application


async def test_console_reads_live_rows(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> None:
    app = _live_app(monkeypatch, live_engine)
    factory = async_sessionmaker(live_engine, expire_on_commit=False)
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()
    nightly_id = uuid.uuid4()
    feedback_id = uuid.uuid4()
    job_id = uuid.uuid4()
    asked = datetime.now(UTC)
    async with factory() as session:
        session.add(
            Conversation(id=conversation_id, user_id="console-live-user", title="Console live")
        )
        session.add(
            Message(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                role="user",
                content="What is the sabbatical policy?",
                created_at=asked,
            )
        )
        session.add(
            Message(
                id=message_id,
                conversation_id=conversation_id,
                role="assistant",
                content=CITE_OR_DIE,
                trace_id="trace-console-live",
                detail={
                    "fallback": True,
                    "route": {"intent": "rag-docs", "router_confidence": 0.9},
                },
                created_at=asked + timedelta(seconds=1),
            )
        )
        session.add(
            NightlyEvalRun(
                id=nightly_id,
                passed=True,
                keyless=True,
                streak=1,
                metrics={"router_accuracy": 1.0},
                sections={"router": {"total": 232}},
            )
        )
        session.add(Feedback(id=feedback_id, rating="up", source="real"))
        session.add(
            IngestJob(
                id=job_id,
                source_uri="repo:refs/heads/main",
                status="done",
                rows_written=5,
                started_at=asked,
                finished_at=asked + timedelta(seconds=2),
            )
        )
        await session.commit()

    try:
        ingest = await _get(app, "/api/admin/ingest")
        assert ingest.status_code == 200
        assert ingest.json()["total_chunks"] > 0
        jobs = ingest.json()["jobs"]
        assert any(job["id"] == str(job_id) and job["status"] == "done" for job in jobs)

        attention = await _get(app, "/api/admin/attention")
        assert attention.status_code == 200
        ours = [item for item in attention.json()["items"] if item["message_id"] == str(message_id)]
        assert len(ours) == 1
        assert ours[0]["question"] == "What is the sabbatical policy?"
        assert ours[0]["reasons"] == ["dont_know"]

        history = await _get(app, "/api/admin/eval")
        assert history.status_code == 200
        assert any(run["run_at"] for run in history.json()["runs"])
        assert history.json()["feedback"]["real"] >= 1
    finally:
        async with factory() as session:
            await session.execute(delete(Feedback).where(Feedback.id == feedback_id))
            await session.execute(delete(NightlyEvalRun).where(NightlyEvalRun.id == nightly_id))
            await session.execute(delete(IngestJob).where(IngestJob.id == job_id))
            await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
            await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
            await session.commit()
        get_settings.cache_clear()
