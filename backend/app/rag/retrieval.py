"""Hybrid retrieval over the document chunk store.

Candidates come from three legs — vector cosine, full-text (`ts_rank`), and
trigram fuzzy — each filtered by the caller's access tags in SQL, then fused
with reciprocal-rank fusion and re-ranked before the top-k cutoff.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.sql.elements import TextClause

from app.models.rag import EMBEDDING_DIM

EmbedFn = Callable[[list[str]], Awaitable[list[list[float]]]]

DEFAULT_TOP_K = 5
DEFAULT_THRESHOLD = 0.3
DEFAULT_CANDIDATE_LIMIT = 50
RRF_K = 60


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    source_uri: str
    section_anchor: str
    content: str
    source_type: str
    similarity: float
    score: float


class Reranker(Protocol):
    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]: ...


class IdentityReranker:
    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        return chunks


def acl_visible(tags: Sequence[str], dept: str, role: str) -> bool:
    return ("dept:all" in tags or f"dept:{dept}" in tags) and (
        "role:all" in tags or f"role:{role}" in tags
    )


def acl_fragment() -> str:
    return (
        "(acl_tags ? 'dept:all' OR acl_tags ? :dept) "
        "AND (acl_tags ? 'role:all' OR acl_tags ? :role)"
    )


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def fuse_and_rank(
    vector: Sequence[RetrievedChunk],
    fts: Sequence[RetrievedChunk],
    trgm: Sequence[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    by_id: dict[str, RetrievedChunk] = {}
    rankings: list[list[str]] = []

    for ranked_chunks in (vector, fts, trgm):
        ordering: list[str] = []
        for chunk in ranked_chunks:
            existing = by_id.get(chunk.id)
            if existing is None or chunk.similarity > existing.similarity:
                by_id[chunk.id] = chunk
            ordering.append(chunk.id)
        rankings.append(ordering)

    fused = rrf_fuse(rankings)
    ordered = sorted(
        (replace(by_id[chunk_id], score=score) for chunk_id, score in fused.items()),
        key=lambda chunk: chunk.score,
        reverse=True,
    )
    return ordered[:top_k]


_VECTOR_SQL = (
    "SELECT id::text AS id, source_uri, section_anchor, content, source_type, "
    "1 - (embedding <=> :query) AS similarity "
    "FROM doc_chunks "
    "WHERE (1 - (embedding <=> :query)) >= :threshold AND {scope} "
    "ORDER BY embedding <=> :query LIMIT :limit"
)

_FTS_SQL = (
    "SELECT id::text AS id, source_uri, section_anchor, content, source_type, "
    "ts_rank(search_vector, websearch_to_tsquery('english', :query)) AS similarity "
    "FROM doc_chunks "
    "WHERE search_vector @@ websearch_to_tsquery('english', :query) AND {scope} "
    "ORDER BY similarity DESC LIMIT :limit"
)

_TRGM_SQL = (
    "SELECT id::text AS id, source_uri, section_anchor, content, source_type, "
    "similarity(content, :query) AS similarity "
    "FROM doc_chunks "
    "WHERE content % :query AND {scope} "
    "ORDER BY similarity DESC LIMIT :limit"
)

_SOURCE_TYPE_FILTER = "source_type = ANY(:source_types)"


def _scope(restrict_types: bool) -> str:
    scope = acl_fragment()
    if restrict_types:
        scope = f"({scope}) AND {_SOURCE_TYPE_FILTER}"
    return scope


def _vector_stmt(restrict_types: bool = False) -> TextClause:
    return text(_VECTOR_SQL.format(scope=_scope(restrict_types))).bindparams(
        bindparam("query", type_=Vector(EMBEDDING_DIM))
    )


def _fts_stmt(restrict_types: bool = False) -> TextClause:
    return text(_FTS_SQL.format(scope=_scope(restrict_types)))


def _trgm_stmt(restrict_types: bool = False) -> TextClause:
    return text(_TRGM_SQL.format(scope=_scope(restrict_types)))


class Retriever:
    def __init__(
        self,
        engine: AsyncEngine,
        embed: EmbedFn,
        *,
        reranker: Reranker | None = None,
    ) -> None:
        self._engine = engine
        self._embed = embed
        self._reranker: Reranker = reranker or IdentityReranker()

    async def retrieve(
        self,
        query: str,
        *,
        dept: str,
        role: str,
        source_types: Sequence[str] | None = None,
        top_k: int = DEFAULT_TOP_K,
        threshold: float = DEFAULT_THRESHOLD,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> list[RetrievedChunk]:
        embedding = (await self._embed([query]))[0]
        restrict_types = bool(source_types)
        params: dict[str, object] = {
            "dept": f"dept:{dept}",
            "role": f"role:{role}",
            "limit": limit,
        }
        if restrict_types:
            params["source_types"] = list(source_types) if source_types else []

        async with self._engine.connect() as conn:
            vector = await self._run(
                conn,
                _vector_stmt(restrict_types),
                params | {"query": embedding, "threshold": threshold},
            )
            fts = await self._run(conn, _fts_stmt(restrict_types), params | {"query": query})
            trgm = await self._run(conn, _trgm_stmt(restrict_types), params | {"query": query})

        pool = fuse_and_rank(vector, fts, trgm, top_k=min(3 * top_k, limit))
        ranked = await self._reranker.rerank(query, pool)
        return ranked[:top_k]

    @staticmethod
    async def _run(
        conn: AsyncConnection, statement: TextClause, params: dict[str, object]
    ) -> list[RetrievedChunk]:
        result = await conn.execute(statement, params)
        chunks: list[RetrievedChunk] = []
        for row in result.mappings():
            chunks.append(
                RetrievedChunk(
                    id=str(row["id"]),
                    source_uri=str(row["source_uri"]),
                    section_anchor=str(row["section_anchor"]),
                    content=str(row["content"]),
                    source_type=str(row["source_type"]),
                    similarity=float(row["similarity"]),
                    score=0.0,
                )
            )
        return chunks
