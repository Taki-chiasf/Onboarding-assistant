"""Conversation history lifecycle: encryption at rest, erasure, key rotation.

Message bodies and conversation titles are sealed under per-conversation data
keys, themselves wrapped by the key-encryption key from the environment. Reads
pass plaintext through unchanged, so a stack that never configured a key, or
rows written before one was, keep working; the CLI backfills those rows and
rewraps the data keys when the key rotates.

Erasure is owner-scoped: a caller can only delete conversations they own, and a
request for someone else's conversation reads as missing. Deletion hard-cascades
to messages and their feedback, drops still-unreviewed eval candidates derived
from those messages, and records an audit entry; promoted or rejected eval cases
survive with their redacted prompt.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.crypto import (
    KEY_BYTES,
    Cipher,
    DecryptionError,
    decode_key,
    get_cipher,
    is_token,
    open_text,
    seal_text,
)
from app.models import AuditLog, Conversation, EvalCase, Feedback, Message

logger = logging.getLogger(__name__)


def conversation_context(conversation_id: uuid.UUID) -> str:
    """Associated data binding a wrapped data key to its conversation."""
    return f"conversation:{conversation_id}:dek"


def title_context(conversation_id: uuid.UUID) -> str:
    return f"conversation:{conversation_id}:title"


def message_context(message_id: uuid.UUID) -> str:
    return f"message:{message_id}"


@dataclass(frozen=True)
class DeletionResult:
    conversations: int
    messages: int
    feedback: int
    pending_cases: int


@dataclass(frozen=True)
class BackfillResult:
    keys_created: int
    titles: int
    messages: int
    # Conversations whose stored key does not open with the configured key.
    # Left untouched (their sealed rows cannot be read or safely rewritten) and
    # reported so an operator can retry with the right key.
    unreadable: int = 0


@dataclass(frozen=True)
class RotationResult:
    rewrapped: int
    skipped: int


def ensure_key(cipher: Cipher, conversation: Conversation) -> Cipher:
    """The conversation's data cipher, creating and wrapping a key when missing.

    A conversation that predates encryption gets its key on first write, and a
    plaintext title is sealed in the same step.
    """
    if conversation.key_wrapped is not None:
        raw = cipher.open(conversation.key_wrapped, context=conversation_context(conversation.id))
        return Cipher(raw)
    raw = os.urandom(KEY_BYTES)
    conversation.key_wrapped = cipher.seal(raw, context=conversation_context(conversation.id))
    if conversation.title is not None and not is_token(conversation.title):
        conversation.title = seal_text(
            Cipher(raw), conversation.title, context=title_context(conversation.id)
        )
    return Cipher(raw)


def open_wrapped_key(
    cipher: Cipher | None, wrapped: str | None, *, conversation_id: uuid.UUID
) -> Cipher | None:
    """Unwrap a stored data key, or None when the conversation has no key yet."""
    if cipher is None or wrapped is None:
        return None
    return Cipher(cipher.open(wrapped, context=conversation_context(conversation_id)))


def open_conversation_key(cipher: Cipher | None, conversation: Conversation) -> Cipher | None:
    return open_wrapped_key(cipher, conversation.key_wrapped, conversation_id=conversation.id)


def read_text(dek: Cipher | None, stored: str, *, context: str) -> str:
    """Decrypt a stored field, passing legacy plaintext through unchanged."""
    if not is_token(stored):
        return stored
    if dek is None:
        raise DecryptionError("stored value is encrypted but no key is available")
    return open_text(dek, stored, context=context)


async def _owned_conversation(
    session: AsyncSession, *, user_id: str, conversation_id: uuid.UUID, for_update: bool
) -> Conversation | None:
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def record_user_message(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    trace_id: str,
    conversation_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Store the caller's message, opening a conversation when needed.

    The conversation id is only honored when it belongs to the caller: an id
    that is unknown, foreign, or already deleted starts a fresh conversation
    instead of appending to a history the caller does not own.
    """
    cipher = get_cipher()
    conversation: Conversation | None = None
    if conversation_id is not None:
        conversation = await _owned_conversation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            for_update=cipher is not None,
        )
    if conversation is None:
        conversation = Conversation(id=uuid.uuid4(), user_id=user_id, title=query[:255])
        if cipher is not None:
            ensure_key(cipher, conversation)
        session.add(conversation)
    message_id = uuid.uuid4()
    content = query
    if cipher is not None:
        dek = ensure_key(cipher, conversation)
        content = seal_text(dek, query, context=message_context(message_id))
    session.add(
        Message(
            id=message_id,
            conversation_id=conversation.id,
            role="user",
            content=content,
            trace_id=trace_id,
        )
    )
    await session.commit()
    return conversation.id


async def seal_message(
    session: AsyncSession, *, conversation_id: uuid.UUID, message_id: uuid.UUID, text: str
) -> str:
    """The stored form of an answer body, sealed under the conversation key."""
    cipher = get_cipher()
    if cipher is None:
        return text
    conversation = (
        await session.execute(
            select(Conversation).where(Conversation.id == conversation_id).with_for_update()
        )
    ).scalar_one_or_none()
    if conversation is None:
        logger.warning("sealing a message for a missing conversation %s", conversation_id)
        return text
    dek = ensure_key(cipher, conversation)
    return seal_text(dek, text, context=message_context(message_id))


async def delete_conversations(
    session: AsyncSession, *, user_id: str, conversation_id: uuid.UUID | None = None
) -> DeletionResult:
    """Erase the caller's conversation(s) with a hard cascade.

    Messages and their feedback go through the foreign-key cascade; eval
    candidates still awaiting review are dropped too, while promoted or rejected
    cases survive with their redacted prompt. Deleting a conversation the caller
    does not own reports zero, so an erase never becomes an existence oracle.
    """
    owner_filter = [Conversation.user_id == user_id]
    if conversation_id is not None:
        owner_filter.append(Conversation.id == conversation_id)
    conversation_ids = (
        (await session.execute(select(Conversation.id).where(*owner_filter))).scalars().all()
    )
    if not conversation_ids:
        return DeletionResult(0, 0, 0, 0)

    message_filter = Message.conversation_id.in_(conversation_ids)
    message_ids = select(Message.id).where(message_filter)
    messages = (
        await session.execute(select(func.count()).select_from(Message).where(message_filter))
    ).scalar_one()
    feedback = (
        await session.execute(
            select(func.count()).select_from(Feedback).where(Feedback.message_id.in_(message_ids))
        )
    ).scalar_one()
    case_filter = EvalCase.status == "review", EvalCase.source_message_id.in_(message_ids)
    pending_cases = (
        await session.execute(select(func.count()).select_from(EvalCase).where(*case_filter))
    ).scalar_one()

    await session.execute(delete(EvalCase).where(*case_filter))
    await session.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
    session.add(
        AuditLog(
            principal=user_id,
            action="conversation.delete" if conversation_id is not None else "history.delete",
            target=str(conversation_id) if conversation_id is not None else None,
        )
    )
    await session.commit()
    return DeletionResult(
        conversations=len(conversation_ids),
        messages=int(messages),
        feedback=int(feedback),
        pending_cases=int(pending_cases),
    )


async def backfill(
    session: AsyncSession, *, cipher: Cipher, user_id: str | None = None
) -> BackfillResult:
    """Seal plaintext history and wrap any missing data keys.

    A conversation whose stored key does not open with the configured key is
    left untouched and counted as unreadable: its sealed rows cannot be read,
    and minting a new key would orphan them. ``user_id`` scopes the pass to one
    account, which is useful when the stack runs shared.
    """
    statement = select(Conversation)
    if user_id is not None:
        statement = statement.where(Conversation.user_id == user_id)
    conversations = (await session.execute(statement)).scalars().all()
    keys_created = 0
    titles = 0
    messages = 0
    unreadable = 0
    for conversation in conversations:
        had_key = conversation.key_wrapped is not None
        plaintext_title = conversation.title is not None and not is_token(conversation.title)
        try:
            dek = ensure_key(cipher, conversation)
        except DecryptionError:
            unreadable += 1
            logger.warning(
                "history backfill: conversation %s keeps a key from another key-encryption key; "
                "skipping",
                conversation.id,
            )
            continue
        if not had_key:
            keys_created += 1
        if plaintext_title:
            titles += 1
        rows = (
            (
                await session.execute(
                    select(Message).where(Message.conversation_id == conversation.id)
                )
            )
            .scalars()
            .all()
        )
        for message in rows:
            if not is_token(message.content):
                message.content = seal_text(
                    dek, message.content, context=message_context(message.id)
                )
                messages += 1
    await session.commit()
    return BackfillResult(
        keys_created=keys_created, titles=titles, messages=messages, unreadable=unreadable
    )


async def rotate_keys(
    session: AsyncSession, *, new_cipher: Cipher, old_key: bytes, user_id: str | None = None
) -> RotationResult:
    """Rewrap every stored data key from the old key-encryption key to the new one.

    A conversation whose key opens with neither key is an error rather than a
    skip: the pass rolls back instead of partially rotating the database.
    ``user_id`` scopes the pass to one account.
    """
    old_cipher = Cipher(old_key)
    rewrapped = 0
    skipped = 0
    statement = select(Conversation).where(Conversation.key_wrapped.is_not(None))
    if user_id is not None:
        statement = statement.where(Conversation.user_id == user_id)
    conversations = (await session.execute(statement)).scalars().all()
    for conversation in conversations:
        wrapped = conversation.key_wrapped
        if wrapped is None:
            continue
        context = conversation_context(conversation.id)
        try:
            new_cipher.open(wrapped, context=context)
            skipped += 1
            continue
        except DecryptionError:
            pass
        try:
            key = old_cipher.open(wrapped, context=context)
        except DecryptionError as exc:
            raise DecryptionError(
                f"conversation {conversation.id}: data key opens with neither the current nor "
                "the previous key"
            ) from exc
        conversation.key_wrapped = new_cipher.seal(key, context=context)
        rewrapped += 1
    await session.commit()
    return RotationResult(rewrapped=rewrapped, skipped=skipped)


def _engine() -> AsyncEngine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to manage conversation history")
    return create_async_engine(settings.database_url)


async def _run_backfill(user: str | None) -> BackfillResult:
    cipher = get_cipher()
    if cipher is None:
        raise RuntimeError("ENCRYPTION_KEY is required to encrypt conversation history")
    engine = _engine()
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            return await backfill(session, cipher=cipher, user_id=user)
    finally:
        await engine.dispose()


async def _run_rotate(old_key: str, user: str | None) -> RotationResult:
    cipher = get_cipher()
    if cipher is None:
        raise RuntimeError("ENCRYPTION_KEY is required to rotate conversation keys")
    engine = _engine()
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            return await rotate_keys(
                session, new_cipher=cipher, old_key=decode_key(old_key), user_id=user
            )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Encrypt conversation history or rewrap its data keys"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backfill_command = commands.add_parser(
        "backfill", help="seal plaintext history under ENCRYPTION_KEY"
    )
    backfill_command.add_argument("--user", default=None, help="limit to one user id")
    rotate = commands.add_parser("rotate", help="rewrap data keys under a new ENCRYPTION_KEY")
    rotate.add_argument("--old-key", required=True, help="base64 key the data keys use now")
    rotate.add_argument("--user", default=None, help="limit to one user id")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    if args.command == "backfill":
        backfilled = asyncio.run(_run_backfill(args.user))
        logger.info(
            "history backfill: keys_created=%d titles=%d messages=%d unreadable=%d",
            backfilled.keys_created,
            backfilled.titles,
            backfilled.messages,
            backfilled.unreadable,
        )
    else:
        rotated = asyncio.run(_run_rotate(args.old_key, args.user))
        logger.info("history rotate: rewrapped=%d skipped=%d", rotated.rewrapped, rotated.skipped)


if __name__ == "__main__":
    main()
