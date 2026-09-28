import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api.feedback import get_session_factory
from app.auth.mock_oidc import get_principal
from app.auth.principal import Principal
from app.core.config import get_settings
from app.main import create_app
from app.models import Conversation, EvalCase, Feedback, Message


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _StubSession:
    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = False

    async def execute(self, statement: object) -> _Result:
        return self._results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def get(self, model: Any, ident: Any) -> Any:
        return None

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _message(*, role: str = "assistant") -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role=role,
        content="16 weeks",
        trace_id="trace-1",
        created_at=datetime(2026, 9, 28, 10, 0, tzinfo=UTC),
    )


def _use_session(app: FastAPI, session: _StubSession) -> None:
    app.dependency_overrides[get_session_factory] = lambda: lambda: session


async def test_feedback_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_OIDC", "0")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    application = create_app()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as c:
            resp = await c.post(
                "/api/feedback", json={"message_id": str(uuid.uuid4()), "rating": "up"}
            )
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 401


async def test_feedback_needs_a_database(app: FastAPI, client: AsyncClient) -> None:
    resp = await client.post(
        "/api/feedback", json={"message_id": str(uuid.uuid4()), "rating": "up"}
    )
    assert resp.status_code == 503


async def test_feedback_rejects_an_unknown_message(app: FastAPI, client: AsyncClient) -> None:
    session = _StubSession([_Result([])])
    _use_session(app, session)
    try:
        resp = await client.post(
            "/api/feedback", json={"message_id": str(uuid.uuid4()), "rating": "up"}
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 404


async def test_feedback_validates_the_rating(app: FastAPI, client: AsyncClient) -> None:
    session = _StubSession([])
    _use_session(app, session)
    try:
        resp = await client.post(
            "/api/feedback", json={"message_id": str(uuid.uuid4()), "rating": "sideways"}
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 422


async def test_thumbs_down_files_a_candidate_eval_case(app: FastAPI, client: AsyncClient) -> None:
    message = _message()
    session = _StubSession(
        [
            _Result([message]),  # the answered message
            _Result([]),  # replace existing feedback
            _Result([]),  # no candidate yet
            _Result([(uuid.uuid4(), "How much parental leave do I get?", None)]),  # the user prompt
        ]
    )
    _use_session(app, session)
    try:
        resp = await client.post(
            "/api/feedback", json={"message_id": str(message.id), "rating": "down"}
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json() == {"message_id": str(message.id), "rating": "down", "filed": True}
    assert session.committed is True

    feedback = [obj for obj in session.added if isinstance(obj, Feedback)]
    cases = [obj for obj in session.added if isinstance(obj, EvalCase)]
    assert len(feedback) == 1
    assert feedback[0].rating == "down"
    assert feedback[0].source == "real"
    assert feedback[0].trace_id == "trace-1"
    assert len(cases) == 1
    assert cases[0].status == "review"
    assert cases[0].source == "thumbs_down"
    assert cases[0].source_message_id == message.id
    assert cases[0].prompt == "How much parental leave do I get?"
    assert cases[0].tags == ["feedback", "dept:Engineering", "role:employee"]


async def test_feedback_redacts_the_correction_text(app: FastAPI, client: AsyncClient) -> None:
    message = _message()
    session = _StubSession(
        [
            _Result([message]),
            _Result([]),
            _Result([]),
            _Result([(uuid.uuid4(), "How do I reach the vendor?", None)]),
        ]
    )
    _use_session(app, session)
    try:
        resp = await client.post(
            "/api/feedback",
            json={
                "message_id": str(message.id),
                "rating": "down",
                "correction": "the answer was right but mail me at alex@corp.example",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    feedback = [obj for obj in session.added if isinstance(obj, Feedback)][0]
    assert feedback.correction is not None
    assert "alex@corp.example" not in feedback.correction
    assert "[email]" in feedback.correction


async def test_thumbs_up_withdraws_the_candidate(app: FastAPI, client: AsyncClient) -> None:
    message = _message()
    candidate = EvalCase(
        id=uuid.uuid4(),
        prompt="How much leave?",
        status="review",
        source="thumbs_down",
        source_message_id=message.id,
    )
    session = _StubSession(
        [
            _Result([message]),
            _Result([]),
            _Result([candidate]),
            _Result([(uuid.uuid4(), "How much leave?", None)]),
        ]
    )
    _use_session(app, session)
    try:
        resp = await client.post(
            "/api/feedback", json={"message_id": str(message.id), "rating": "up"}
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["filed"] is False
    assert session.deleted == [candidate]
    assert [obj for obj in session.added if isinstance(obj, EvalCase)] == []


async def test_plain_thumbs_up_files_nothing(app: FastAPI, client: AsyncClient) -> None:
    message = _message()
    session = _StubSession(
        [
            _Result([message]),
            _Result([]),
            _Result([]),
            _Result([(uuid.uuid4(), "How much leave?", None)]),
        ]
    )
    _use_session(app, session)
    try:
        resp = await client.post(
            "/api/feedback", json={"message_id": str(message.id), "rating": "up"}
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["filed"] is False
    assert [obj for obj in session.added if isinstance(obj, EvalCase)] == []


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


def _live_app(
    monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine, principal: Principal
) -> FastAPI:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    application = create_app()
    application.state.engine = engine
    application.dependency_overrides[get_principal] = lambda: principal
    return application


async def test_feedback_round_trip_against_database(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> None:
    employee = Principal(
        sub="feedback-live-user", email="employee@example.com", dept="Engineering", role="employee"
    )
    admin = Principal(
        sub="feedback-live-admin", email="admin@example.com", dept="People", role="admin"
    )
    application = _live_app(monkeypatch, live_engine, employee)
    admin_application = _live_app(monkeypatch, live_engine, admin)
    factory = async_sessionmaker(live_engine, expire_on_commit=False)

    conversation_id = uuid.uuid4()
    question_id = uuid.uuid4()
    answer_id = uuid.uuid4()
    asked_at = datetime.now(UTC)
    detail = {
        "sources": [{"id": "chunk-1", "source_uri": "file:docs/a.md"}],
        "route": {"intent": "rag-docs", "router_confidence": 0.9},
    }
    async with factory() as session:
        session.add(Conversation(id=conversation_id, user_id=employee.sub, title="Feedback live"))
        session.add(
            Message(
                id=question_id,
                conversation_id=conversation_id,
                role="user",
                content="How much leave do I get?",
                created_at=asked_at,
            )
        )
        session.add(
            Message(
                id=answer_id,
                conversation_id=conversation_id,
                role="assistant",
                content="16 weeks",
                trace_id="trace-live-fb",
                detail=detail,
                created_at=asked_at + timedelta(seconds=1),
            )
        )
        await session.commit()

    try:
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            down = await client.post(
                "/api/feedback",
                json={
                    "message_id": str(answer_id),
                    "rating": "down",
                    "correction": "should cite the policy page",
                },
            )
            assert down.status_code == 200
            assert down.json()["filed"] is True

            history = await client.get(f"/api/conversations/{conversation_id}/messages")
            assert history.status_code == 200
            answer_row = history.json()[1]
            assert answer_row["feedback"] == {
                "rating": "down",
                "correction": "should cite the policy page",
            }

            up = await client.post(
                "/api/feedback", json={"message_id": str(answer_id), "rating": "up"}
            )
            assert up.status_code == 200
            assert up.json()["filed"] is False

        async with factory() as session:
            feedback_rows = (
                (await session.execute(select(Feedback).where(Feedback.message_id == answer_id)))
                .scalars()
                .all()
            )
            assert len(feedback_rows) == 1
            assert feedback_rows[0].rating == "up"
            assert feedback_rows[0].correction is None
            cases = (
                (
                    await session.execute(
                        select(EvalCase).where(EvalCase.source_message_id == answer_id)
                    )
                )
                .scalars()
                .all()
            )
            assert cases == []

        admin_transport = ASGITransport(app=admin_application)
        async with AsyncClient(transport=admin_transport, base_url="http://test") as admin_client:
            # File again so there is a candidate to review.
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                again = await client.post(
                    "/api/feedback",
                    json={
                        "message_id": str(answer_id),
                        "rating": "down",
                        "correction": "missing the policy citation",
                    },
                )
                assert again.status_code == 200

            queue = await admin_client.get("/api/admin/review")
            assert queue.status_code == 200
            ours = [case for case in queue.json()["cases"] if case["message_id"] == str(answer_id)]
            assert len(ours) == 1
            filed = ours[0]
            assert filed["prompt"] == "How much leave do I get?"
            assert filed["rating"] == "down"
            assert filed["correction"] == "missing the policy citation"
            assert filed["detail"]["route"]["intent"] == "rag-docs"
            assert filed["message_id"] == str(answer_id)

            promoted = await admin_client.post(
                f"/api/admin/review/{filed['id']}/promote",
                json={"expected_intent": "rag-docs", "expected_source_ids": ["chunk-1"]},
            )
            assert promoted.status_code == 200
            assert promoted.json()["status"] == "promoted"
            assert promoted.json()["reviewed_by"] == admin.email

            queue_after = await admin_client.get("/api/admin/review")
            remaining = [
                case for case in queue_after.json()["cases"] if case["message_id"] == str(answer_id)
            ]
            assert remaining == []

            rejected = await admin_client.post(f"/api/admin/review/{filed['id']}/reject")
            assert rejected.status_code == 409
    finally:
        async with factory() as session:
            await session.execute(delete(EvalCase).where(EvalCase.source_message_id == answer_id))
            await session.execute(delete(Feedback).where(Feedback.message_id == answer_id))
            await session.execute(delete(Message).where(Message.id.in_([question_id, answer_id])))
            await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
            await session.commit()
