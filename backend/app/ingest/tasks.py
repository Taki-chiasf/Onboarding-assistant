"""RQ task entrypoints for ingestion."""

from __future__ import annotations

import asyncio

import redis
from rq import Queue

from app.core.config import get_settings
from app.ingest.service import run_ingest


def ingest_corpus_job() -> dict[str, int]:
    return asyncio.run(run_ingest())


def enqueue_corpus() -> None:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL is required to enqueue ingestion")
    conn = redis.from_url(settings.redis_url)
    Queue("default", connection=conn).enqueue(ingest_corpus_job)
