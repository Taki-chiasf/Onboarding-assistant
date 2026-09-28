"""RQ task entrypoints for ingestion."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import redis
from rq import Queue
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.ingest.service import run_ingest
from app.models import IngestJob

logger = logging.getLogger(__name__)


async def mark_job(
    job_id: str | None,
    *,
    status: str,
    rows_written: int | None = None,
    error: str | None = None,
) -> None:
    """Advance one tracked ingest job. A missing row or database is a no-op."""
    if not job_id:
        return
    settings = get_settings()
    if not settings.database_url:
        return
    engine = create_async_engine(settings.database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            job = await session.get(IngestJob, uuid.UUID(job_id))
            if job is None:
                return
            job.status = status
            if rows_written is not None:
                job.rows_written = rows_written
            if error is not None:
                job.error = error[:2000]
            if status in {"done", "failed"}:
                job.finished_at = datetime.now(UTC)
            await session.commit()
    finally:
        await engine.dispose()


async def _run_job(job_id: str | None) -> dict[str, int]:
    await mark_job(job_id, status="running")
    try:
        result = await run_ingest()
    except Exception as error:
        logger.exception("ingestion job %s failed", job_id)
        await mark_job(job_id, status="failed", error=f"{type(error).__name__}: {error}")
        raise
    await mark_job(job_id, status="done", rows_written=result["inserted"] + result["updated"])
    return result


def ingest_corpus_job(job_id: str | None = None) -> dict[str, int]:
    return asyncio.run(_run_job(job_id))


def enqueue_corpus() -> None:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required to enqueue ingestion")
    conn = redis.from_url(settings.redis_url)
    Queue("default", connection=conn).enqueue(ingest_corpus_job)


def enqueue_reingest(job_id: str) -> None:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required to enqueue ingestion")
    conn = redis.from_url(settings.redis_url)
    Queue("default", connection=conn).enqueue(ingest_corpus_job, job_id)
