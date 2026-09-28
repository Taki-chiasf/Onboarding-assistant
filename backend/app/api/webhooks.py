"""Signed reingest webhooks.

A repo push or a source edit posts a signed JSON body; a verified request
queues a reingest on the worker queue and records a job row the ingest status
shows. The signature is an HMAC-SHA256 over the raw body (``sha256=<hex>``),
so the endpoint can be public without being open. Reingest is idempotent -
unchanged chunks are skipped by content hash - so a redelivered webhook is
harmless.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import get_settings
from app.ingest.tasks import enqueue_reingest, mark_job
from app.ingest.webhooks import (
    IngestWebhookPayload,
    should_reingest,
    signature_header,
    source_label,
    verify_signature,
)
from app.models import IngestJob

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024


class ReingestAck(BaseModel):
    queued: bool
    source: str
    job_id: str | None = None
    reason: str | None = None


@router.post("/ingest", response_model=ReingestAck, status_code=status.HTTP_202_ACCEPTED)
async def ingest_webhook(request: Request) -> ReingestAck:
    settings = get_settings()
    if not settings.webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook is not configured",
        )
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="payload is too large"
        )
    if not verify_signature(settings.webhook_secret, body, signature_header(request.headers)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook signature"
        )

    try:
        payload = IngestWebhookPayload.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid webhook payload",
        ) from exc

    proceed, reason = should_reingest(payload, branch=settings.webhook_branch)
    if not proceed:
        return ReingestAck(queued=False, source=payload.source, reason=reason)

    engine: AsyncEngine | None = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not configured",
        )

    job_id = uuid.uuid4()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            IngestJob(
                id=job_id,
                source_uri=source_label(payload),
                status="queued",
                started_at=datetime.now(UTC),
            )
        )
        await session.commit()

    try:
        enqueue_reingest(str(job_id))
    except Exception as exc:
        logger.exception("failed to enqueue reingest for %s", payload.source)
        await mark_job(str(job_id), status="failed", error=f"enqueue failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="reingest queue unavailable"
        ) from exc

    logger.info(
        "queued reingest %s for %s (%d changed paths)",
        job_id,
        payload.source,
        len(payload.changed),
    )
    return ReingestAck(queued=True, source=payload.source, job_id=str(job_id))
