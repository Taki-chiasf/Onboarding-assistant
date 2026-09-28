"""Feedback on assistant answers.

A thumbs rating, with an optional correction text, is stored against the answer
message. A rating that signals a problem (thumbs down, or a correction) also
files a candidate eval case for admin review; the candidate links back to the
message so the review queue can show the full trace (router verdict, retrieved
sources, executed SQL). Case text is redacted before it is stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.mock_oidc import get_principal
from app.auth.principal import Principal
from app.core.redact import redact_pii
from app.models import Conversation, EvalCase, Feedback, Message

router = APIRouter(prefix="/api", tags=["feedback"])

MAX_CORRECTION_CHARS = 4000


class FeedbackRequest(BaseModel):
    message_id: uuid.UUID
    rating: Literal["up", "down"]
    correction: str | None = Field(default=None, max_length=MAX_CORRECTION_CHARS)


class FeedbackAck(BaseModel):
    message_id: str
    rating: str
    filed: bool


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not configured",
        )
    return async_sessionmaker(engine, expire_on_commit=False)


PrincipalDep = Annotated[Principal, Depends(get_principal)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]


async def _user_prompt(
    session: AsyncSession, conversation_id: uuid.UUID, asked_at: datetime
) -> str | None:
    result = await session.execute(
        select(Message.content)
        .where(
            Message.conversation_id == conversation_id,
            Message.role == "user",
            Message.created_at <= asked_at,
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.post("/feedback", response_model=FeedbackAck)
async def submit_feedback(
    payload: FeedbackRequest,
    principal: PrincipalDep,
    factory: SessionFactoryDep,
) -> FeedbackAck:
    correction = payload.correction.strip() if payload.correction else None

    async with factory() as session:
        message = (
            await session.execute(
                select(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.id == payload.message_id,
                    Message.role == "assistant",
                    Conversation.user_id == principal.sub,
                )
            )
        ).scalar_one_or_none()
        if message is None:
            # Do not distinguish "not yours" from "does not exist".
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")

        await session.execute(
            delete(Feedback).where(Feedback.message_id == message.id, Feedback.source == "real")
        )
        session.add(
            Feedback(
                message_id=message.id,
                rating=payload.rating,
                correction=redact_pii(correction) if correction else None,
                source="real",
                trace_id=message.trace_id,
            )
        )

        candidate = (
            await session.execute(
                select(EvalCase).where(
                    EvalCase.source_message_id == message.id,
                    EvalCase.status == "review",
                )
            )
        ).scalar_one_or_none()
        signals_problem = payload.rating == "down" or correction is not None
        prompt = await _user_prompt(session, message.conversation_id, message.created_at)
        filed = False
        if signals_problem:
            if prompt is not None:
                source = "thumbs_down" if payload.rating == "down" else "correction"
                if candidate is None:
                    session.add(
                        EvalCase(
                            prompt=redact_pii(prompt),
                            status="review",
                            source=source,
                            source_message_id=message.id,
                            tags=[
                                "feedback",
                                f"dept:{principal.dept}",
                                f"role:{principal.role}",
                            ],
                        )
                    )
                else:
                    candidate.source = source
                filed = True
        elif candidate is not None:
            # The thumbs-down was withdrawn; drop the untouched candidate.
            await session.delete(candidate)

        await session.commit()

    return FeedbackAck(message_id=str(payload.message_id), rating=payload.rating, filed=filed)
