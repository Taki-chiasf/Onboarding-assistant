import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth.mock_oidc import get_principal
from app.auth.principal import Principal
from app.core.config import get_settings
from app.core.crypto import (
    Cipher,
    DecryptionError,
    decode_key,
    generate_key,
    is_token,
    seal_text,
)
from app.history import (
    RotationResult,
    backfill,
    ensure_key,
    message_context,
    open_conversation_key,
    read_text,
    record_user_message,
    rotate_keys,
    seal_message,
    title_context,
)
from app.main import create_app
from app.models import AuditLog, Conversation, EvalCase, Feedback, Message

_LIVE_DB_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def live_engine() -> AsyncIterator[AsyncEngine]:
    if not _LIVE_DB_URL:
        pytest.skip("TEST_DATABASE_URL not configured")
    engine = create_async_engine(_LIVE_DB_URL, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


def _cipher() -> Cipher:
    return Cipher(os.urandom(32))


def _factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _activate_key(monkeypatch: pytest.MonkeyPatch, value: str | None = None) -> str:
    key = value or generate_key()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    return key


def _live_app(
    monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine, principal: Principal
) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", _LIVE_DB_URL)
    monkeypatch.setenv("MOCK_OIDC", "1")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    get_settings.cache_clear()
    application = create_app()
    application.state.engine = engine
    application.dependency_overrides[get_principal] = lambda: principal
    return application


def test_ensure_key_wraps_a_fresh_key_and_seals_the_title() -> None:
    cipher = _cipher()
    conversation = Conversation(id=uuid.uuid4(), user_id="u", title="How much leave?")

    dek = ensure_key(cipher, conversation)

    assert is_token(conversation.key_wrapped)
    assert is_token(conversation.title)
    title = conversation.title or ""
    assert read_text(dek, title, context=title_context(conversation.id)) == "How much leave?"
    probe = dek.seal(b"probe", context="probe")
    assert ensure_key(cipher, conversation).open(probe, context="probe") == b"probe"


def test_ensure_key_leaves_a_sealed_title_alone() -> None:
    cipher = _cipher()
    conversation = Conversation(id=uuid.uuid4(), user_id="u", title=None)

    ensure_key(cipher, conversation)

    assert conversation.title is None


def test_open_conversation_key_needs_a_cipher_and_a_wrapped_key() -> None:
    cipher = _cipher()
    conversation = Conversation(id=uuid.uuid4(), user_id="u", title=None)

    assert open_conversation_key(None, conversation) is None
    assert open_conversation_key(cipher, conversation) is None


def test_read_text_passes_plaintext_and_rejects_a_keyless_token() -> None:
    token = seal_text(_cipher(), "secret", context="message:x")

    assert read_text(None, "legacy plaintext", context="message:x") == "legacy plaintext"
    with pytest.raises(DecryptionError):
        read_text(None, token, context="message:x")


async def test_seal_message_is_a_passthrough_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()

    stored = await seal_message(
        cast(AsyncSession, MagicMock()),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        text="plain answer",
    )

    assert stored == "plain answer"


class _Scalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _StubSession:
    def __init__(self, results: list[list[object]]) -> None:
        self._results = list(results)
        self.committed = False

    async def execute(self, statement: object) -> _Result:
        return _Result(self._results.pop(0))

    async def commit(self) -> None:
        self.committed = True


async def test_backfill_reports_a_foreign_key_without_touching_it() -> None:
    """A conversation sealed under another key is unreadable to this run; the
    backfill must report it instead of aborting or minting a new key."""
    conversation = Conversation(id=uuid.uuid4(), user_id="u", title="sealed")
    ensure_key(Cipher(os.urandom(32)), conversation)
    wrapped = conversation.key_wrapped
    stub = _StubSession([[conversation]])
    session = cast(AsyncSession, stub)

    result = await backfill(session, cipher=Cipher(os.urandom(32)))

    assert result.unreadable == 1
    assert result.messages == 0
    assert conversation.key_wrapped == wrapped
    assert stub.committed is True


async def test_encrypted_history_reads_back_through_the_api(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> None:
    _activate_key(monkeypatch)
    principal = Principal(
        sub="history-live-user", email="history@example.com", dept="Engineering", role="employee"
    )
    application = _live_app(monkeypatch, live_engine, principal)
    factory = _factory(live_engine)
    question = "How much parental leave do I get?"
    answer = "16 weeks, cited from the policy page."
    answer_id = uuid.uuid4()

    async with factory() as session:
        conversation_id = await record_user_message(
            session, user_id=principal.sub, query=question, trace_id="trace-enc"
        )
    async with factory() as session:
        stored = await seal_message(
            session,
            conversation_id=conversation_id,
            message_id=answer_id,
            text=answer,
        )
        session.add(
            Message(id=answer_id, conversation_id=conversation_id, role="assistant", content=stored)
        )
        await session.commit()

    try:
        async with factory() as session:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None and is_token(conversation.key_wrapped)
            assert is_token(conversation.title)
            rows = (
                (
                    await session.execute(
                        select(Message)
                        .where(Message.conversation_id == conversation_id)
                        .order_by(Message.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            assert [row.role for row in rows] == ["user", "assistant"]
            assert all(is_token(row.content) for row in rows)
            assert question not in {row.content for row in rows}

        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get("/api/conversations")
            assert listed.status_code == 200
            mine = [row for row in listed.json() if row["id"] == str(conversation_id)]
            assert mine and mine[0]["title"] == question

            history = await client.get(f"/api/conversations/{conversation_id}/messages")
            assert history.status_code == 200
            assert [row["content"] for row in history.json()] == [question, answer]
    finally:
        async with factory() as session:
            await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
            await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
            await session.commit()


async def test_a_foreign_conversation_id_starts_a_new_conversation(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> None:
    _activate_key(monkeypatch)
    factory = _factory(live_engine)

    async with factory() as session:
        owned_id = await record_user_message(
            session, user_id="history-owner", query="owner question", trace_id="trace-a"
        )
    async with factory() as session:
        forked_id = await record_user_message(
            session,
            user_id="history-intruder",
            query="intruder question",
            trace_id="trace-b",
            conversation_id=owned_id,
        )

    try:
        assert forked_id != owned_id
        async with factory() as session:
            owned_rows = (
                (await session.execute(select(Message).where(Message.conversation_id == owned_id)))
                .scalars()
                .all()
            )
            assert [row.role for row in owned_rows] == ["user"]
            forked = await session.get(Conversation, forked_id)
            assert forked is not None and forked.user_id == "history-intruder"
    finally:
        async with factory() as session:
            await session.execute(
                delete(Message).where(Message.conversation_id.in_([owned_id, forked_id]))
            )
            await session.execute(
                delete(Conversation).where(Conversation.id.in_([owned_id, forked_id]))
            )
            await session.commit()


async def test_delete_cascades_and_scopes_to_the_owner(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> None:
    _activate_key(monkeypatch)
    principal = Principal(
        sub="history-delete-user", email="delete@example.com", dept="Engineering", role="employee"
    )
    other = Principal(
        sub="history-other-user", email="other@example.com", dept="People", role="employee"
    )
    application = _live_app(monkeypatch, live_engine, principal)
    factory = _factory(live_engine)
    answer_id = uuid.uuid4()
    case_id = uuid.uuid4()
    asked_at = datetime.now(UTC)
    other_id: uuid.UUID | None = None

    async with factory() as session:
        conversation_id = await record_user_message(
            session, user_id=principal.sub, query="What is the expense limit?", trace_id="trace-d"
        )
    async with factory() as session:
        session.add(
            Message(
                id=answer_id,
                conversation_id=conversation_id,
                role="assistant",
                content="plaintext answer",
                detail={"sources": []},
                created_at=asked_at,
            )
        )
        await session.flush()
        session.add(Feedback(id=uuid.uuid4(), message_id=answer_id, rating="down", source="real"))
        session.add(
            EvalCase(
                id=case_id,
                prompt="What is the expense limit?",
                status="review",
                source="thumbs_down",
                source_message_id=answer_id,
            )
        )
        await session.commit()
    async with factory() as session:
        other_id = await record_user_message(
            session, user_id=other.sub, query="other question", trace_id="trace-e"
        )

    try:
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            foreign = await client.delete(f"/api/conversations/{other_id}")
            assert foreign.status_code == 404

            own = await client.delete(f"/api/conversations/{conversation_id}")
            assert own.status_code == 200
            assert own.json() == {
                "conversations": 1,
                "messages": 2,
                "feedback": 1,
                "pending_cases": 1,
            }

            again = await client.delete(f"/api/conversations/{conversation_id}")
            assert again.status_code == 404

            everything = await client.delete("/api/conversations")
            assert everything.status_code == 200
            assert everything.json()["conversations"] == 0

        async with factory() as session:
            assert await session.get(Conversation, conversation_id) is None
            assert await session.get(Conversation, other_id) is not None
            assert await session.get(EvalCase, case_id) is None
            messages = (
                (
                    await session.execute(
                        select(Message).where(Message.conversation_id == conversation_id)
                    )
                )
                .scalars()
                .all()
            )
            assert messages == []
            audits = (
                (await session.execute(select(AuditLog).where(AuditLog.principal == principal.sub)))
                .scalars()
                .all()
            )
            assert [audit.action for audit in audits] == ["conversation.delete"]
    finally:
        async with factory() as session:
            await session.execute(delete(EvalCase).where(EvalCase.source_message_id == answer_id))
            await session.execute(delete(Feedback).where(Feedback.message_id == answer_id))
            ids = [conversation_id] + ([other_id] if other_id is not None else [])
            await session.execute(delete(Message).where(Message.conversation_id.in_(ids)))
            await session.execute(delete(Conversation).where(Conversation.id.in_(ids)))
            await session.execute(
                delete(AuditLog).where(AuditLog.principal.in_([principal.sub, other.sub]))
            )
            await session.commit()


async def test_backfill_seals_plaintext_and_rotate_rewraps(
    monkeypatch: pytest.MonkeyPatch, live_engine: AsyncEngine
) -> None:
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()
    factory = _factory(live_engine)
    answer_id = uuid.uuid4()
    async with factory() as session:
        conversation_id = await record_user_message(
            session, user_id="history-backfill", query="plaintext question", trace_id="trace-f"
        )
    async with factory() as session:
        session.add(
            Message(
                id=answer_id,
                conversation_id=conversation_id,
                role="assistant",
                content="plaintext answer",
            )
        )
        await session.commit()

    key_a = generate_key()
    key_b = generate_key()
    try:
        async with factory() as session:
            first = await backfill(
                session, cipher=Cipher(decode_key(key_a)), user_id="history-backfill"
            )
        assert (first.keys_created, first.titles, first.messages) == (1, 1, 2)

        async with factory() as session:
            second = await backfill(
                session, cipher=Cipher(decode_key(key_a)), user_id="history-backfill"
            )
        assert (second.keys_created, second.titles, second.messages) == (0, 0, 0)

        async with factory() as session:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None and is_token(conversation.title)
            query_text = read_text(
                open_conversation_key(Cipher(decode_key(key_a)), conversation),
                conversation.title or "",
                context=title_context(conversation_id),
            )
            assert query_text == "plaintext question"

        async with factory() as session:
            rotated = await rotate_keys(
                session,
                new_cipher=Cipher(decode_key(key_b)),
                old_key=decode_key(key_a),
                user_id="history-backfill",
            )
        assert rotated == RotationResult(rewrapped=1, skipped=0)

        async with factory() as session:
            conversation = await session.get(Conversation, conversation_id)
            assert conversation is not None and conversation.key_wrapped is not None
            with pytest.raises(DecryptionError):
                Cipher(decode_key(key_a)).open(
                    conversation.key_wrapped, context=f"conversation:{conversation_id}:dek"
                )
            current = Cipher(decode_key(key_b)).open(
                conversation.key_wrapped, context=f"conversation:{conversation_id}:dek"
            )
            answer = await session.get(Message, answer_id)
            assert answer is not None
            assert read_text(
                Cipher(current), answer.content, context=message_context(answer_id)
            ) == ("plaintext answer")

        async with factory() as session:
            again = await rotate_keys(
                session,
                new_cipher=Cipher(decode_key(key_b)),
                old_key=decode_key(key_b),
                user_id="history-backfill",
            )
        assert again == RotationResult(rewrapped=0, skipped=1)
    finally:
        async with factory() as session:
            await session.execute(delete(Message).where(Message.conversation_id == conversation_id))
            await session.execute(delete(Conversation).where(Conversation.id == conversation_id))
            await session.commit()
