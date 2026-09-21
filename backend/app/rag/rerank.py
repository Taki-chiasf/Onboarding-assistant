"""Cross-encoder reranker.

The default retrieval path uses hybrid ranking only; the cross-encoder is an
optional, self-hosted stage that can be swapped in when the demo host has CPU
headroom. It is kept out of the import path of the retrieval module so the
runtime image does not need the model stack unless configured.
"""

from __future__ import annotations

from typing import Any

from app.rag.retrieval import RetrievedChunk


class CrossEncoderReranker:
    """Reorders candidates with a sentence-transformers cross-encoder."""

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_id)
        return self._model

    async def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not chunks:
            return chunks
        model = self._load()
        pairs = [(query, chunk.content) for chunk in chunks]
        scores: list[float] = [float(score) for score in model.predict(pairs)]
        ranked = sorted(
            zip(chunks, scores, strict=True), key=lambda item: item[1], reverse=True
        )
        return [chunk for chunk, _ in ranked]
