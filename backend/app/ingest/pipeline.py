"""Corpus ingestion: chunk, embed, and upsert documents into the vector store.

The pipeline is idempotent per chunk: a chunk is identified by its position in
the source, and its content hash decides whether it is inserted, updated, or
skipped on re-ingestion. Embeddings are only computed for chunks whose content
changed, which keeps re-runs cheap and static documents cached.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.ingest.ocr import ocr_pdf_markdown
from app.llm.provider import MistralProvider
from app.models import DocChunk
from app.rag import Chunk, chunk_id, chunk_markdown

CORPUS_ROOT = Path(__file__).resolve().parents[2] / "seed_corpus"

logger = logging.getLogger(__name__)

SOURCE_TYPE_BY_CATEGORY: dict[str, str] = {
    "policies": "policy",
    "handbook": "handbook",
    "runbooks": "runbook",
    "engineering": "engineering",
    "pdfs": "policy",
}

ACL_TAGS_BY_SOURCE_TYPE: dict[str, list[str]] = {
    "policy": ["dept:all", "role:employee"],
    "handbook": ["dept:all", "role:employee"],
    "runbook": ["dept:all", "role:employee"],
    "engineering": ["dept:Engineering", "role:employee"],
}

DEFAULT_ACL_TAGS = ["dept:all", "role:employee"]

EMBED_BATCH_SIZE = 64


@dataclass(frozen=True)
class CorpusFile:
    source_uri: str
    source_type: str
    path: Path


@dataclass(frozen=True)
class UpsertPlan:
    to_insert: list[Chunk]
    to_update: list[tuple[uuid.UUID, Chunk, int]]
    skipped: int


@dataclass
class IngestStats:
    files: int
    inserted: int
    updated: int
    skipped: int
    embedded: int
    failed: int = 0


def source_type_for(category: str) -> str:
    return SOURCE_TYPE_BY_CATEGORY.get(category, "handbook")


def acl_tags_for(source_type: str) -> list[str]:
    return ACL_TAGS_BY_SOURCE_TYPE.get(source_type, DEFAULT_ACL_TAGS)


def iter_corpus(root: Path) -> list[CorpusFile]:
    files: list[CorpusFile] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".md", ".pdf"}:
            continue
        relative = path.relative_to(root)
        files.append(
            CorpusFile(
                source_uri=f"file:{relative.as_posix()}",
                source_type=source_type_for(relative.parts[0]),
                path=path,
            )
        )
    return files


def chunk_file(corpus_file: CorpusFile, markdown: str) -> list[Chunk]:
    return chunk_markdown(
        corpus_file.source_uri,
        corpus_file.source_type,
        markdown,
        acl_tags_for(corpus_file.source_type),
    )


def plan_upsert(
    existing: dict[int, tuple[uuid.UUID, str, int]], chunks: list[Chunk]
) -> UpsertPlan:
    to_insert: list[Chunk] = []
    to_update: list[tuple[uuid.UUID, Chunk, int]] = []
    skipped = 0
    for chunk in chunks:
        if chunk.chunk_index not in existing:
            to_insert.append(chunk)
            continue
        existing_id, existing_hash, existing_version = existing[chunk.chunk_index]
        if existing_hash == chunk.content_hash:
            skipped += 1
        else:
            to_update.append((existing_id, chunk, existing_version + 1))
    return UpsertPlan(to_insert=to_insert, to_update=to_update, skipped=skipped)


async def embed_chunks(
    provider: MistralProvider,
    model: str,
    chunks: list[Chunk],
    *,
    batch_size: int = EMBED_BATCH_SIZE,
) -> dict[int, list[float]]:
    embeddings: dict[int, list[float]] = {}
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = await provider.embed(model, [chunk.content for chunk in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            embeddings[chunk.chunk_index] = vector
    return embeddings


async def ingest_files(
    engine: AsyncEngine,
    provider: MistralProvider,
    embed_model: str,
    ocr_model: str,
    files: list[CorpusFile],
) -> IngestStats:
    stats = IngestStats(files=len(files), inserted=0, updated=0, skipped=0, embedded=0)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        for corpus_file in files:
            try:
                if corpus_file.path.suffix == ".pdf":
                    markdown = await ocr_pdf_markdown(
                        provider,
                        ocr_model,
                        corpus_file.path.name,
                        corpus_file.path.read_bytes(),
                    )
                else:
                    markdown = corpus_file.path.read_text(encoding="utf-8")
            except Exception:
                # One unreadable document must not abandon the rest of the corpus.
                logger.exception("failed to read corpus file: %s", corpus_file.path.name)
                stats.failed += 1
                continue
            chunks = chunk_file(corpus_file, markdown)

            result = await session.execute(
                select(DocChunk).where(DocChunk.source_uri == corpus_file.source_uri)
            )
            existing = {
                row.chunk_index: (row.id, row.content_hash, row.version)
                for row in result.scalars()
            }
            plan = plan_upsert(existing, chunks)
            stats.skipped += plan.skipped

            changed = plan.to_insert + [chunk for _, chunk, _ in plan.to_update]
            embeddings = await embed_chunks(provider, embed_model, changed)
            stats.embedded += len(changed)

            for chunk in plan.to_insert:
                session.add(
                    DocChunk(
                        id=chunk_id(corpus_file.source_uri, chunk.chunk_index),
                        source_uri=chunk.source_uri,
                        source_type=chunk.source_type,
                        section_anchor=chunk.section_anchor,
                        acl_tags=chunk.acl_tags,
                        embedding=embeddings[chunk.chunk_index],
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        chunk_index=chunk.chunk_index,
                        version=1,
                    )
                )
                stats.inserted += 1

            for existing_id, chunk, new_version in plan.to_update:
                await session.execute(
                    update(DocChunk)
                    .where(DocChunk.id == existing_id)
                    .values(
                        section_anchor=chunk.section_anchor,
                        acl_tags=chunk.acl_tags,
                        embedding=embeddings[chunk.chunk_index],
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        version=new_version,
                    )
                )
                stats.updated += 1

        await session.commit()
    return stats
