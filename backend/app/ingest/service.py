"""Wiring for corpus ingestion: config, engine, and provider assembly."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.ingest.pipeline import CORPUS_ROOT, ingest_files, iter_corpus
from app.llm.client import get_provider
from app.llm.models import load_models


async def run_ingest() -> dict[str, int]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to run ingestion")
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY is required to run ingestion")

    models = load_models()
    engine = create_async_engine(settings.database_url)
    moderation_model = models.models["moderation"] if settings.moderation_enabled else None
    try:
        stats = await ingest_files(
            engine,
            get_provider(),
            models.models["embed"],
            models.models["ocr"],
            iter_corpus(CORPUS_ROOT),
            moderation_model=moderation_model,
        )
    finally:
        await engine.dispose()

    return {
        "files": stats.files,
        "inserted": stats.inserted,
        "updated": stats.updated,
        "skipped": stats.skipped,
        "embedded": stats.embedded,
        "failed": stats.failed,
        "flagged": stats.flagged,
    }
