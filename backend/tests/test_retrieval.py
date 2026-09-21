from typing import cast

from sqlalchemy.ext.asyncio import AsyncEngine

from app.rag.retrieval import (
    RetrievedChunk,
    Retriever,
    acl_fragment,
    acl_visible,
    fuse_and_rank,
    rrf_fuse,
)


def _chunk(chunk_id: str, similarity: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        source_uri=f"file:docs/{chunk_id}.md",
        section_anchor="Doc",
        content=f"content of {chunk_id}",
        source_type="policy",
        similarity=similarity,
        score=0.0,
    )


def test_acl_visible_dept_and_role() -> None:
    assert acl_visible(["dept:all", "role:employee"], "Engineering", "employee")
    assert acl_visible(["dept:Engineering", "role:employee"], "Engineering", "employee")
    assert not acl_visible(["dept:Engineering", "role:employee"], "Finance", "employee")
    assert not acl_visible(["dept:all", "role:admin"], "Engineering", "employee")
    assert acl_visible(["dept:all", "role:all"], "Engineering", "employee")


def test_acl_fragment_references_params() -> None:
    fragment = acl_fragment()
    assert ":dept" in fragment
    assert ":role" in fragment
    assert "dept:all" in fragment
    assert "role:all" in fragment


def test_rrf_fuse_combines_rankings() -> None:
    fused = rrf_fuse([["a", "b"], ["b", "a"]])
    assert fused["a"] == fused["b"]
    assert fused["a"] > 0.0


def test_rrf_fuse_rewards_higher_rank() -> None:
    fused = rrf_fuse([["a", "b", "c"]])
    assert fused["a"] > fused["b"] > fused["c"]


def test_fuse_and_rank_merges_and_scores() -> None:
    vector = [_chunk("a", 0.9), _chunk("b", 0.8)]
    fts = [_chunk("b", 0.0), _chunk("c", 0.0)]
    trgm = [_chunk("c", 0.0)]
    ranked = fuse_and_rank(vector, fts, trgm, top_k=3)

    ids = [chunk.id for chunk in ranked]
    assert len(ids) == 3
    assert set(ids) == {"a", "b", "c"}
    assert ranked[0].score >= ranked[1].score >= ranked[2].score
    by_id = {chunk.id: chunk for chunk in ranked}
    assert by_id["b"].similarity == 0.8


def test_fuse_and_rank_honors_top_k() -> None:
    vector = [_chunk(str(i)) for i in range(10)]
    ranked = fuse_and_rank(vector, [], [], top_k=4)
    assert len(ranked) == 4


def test_fuse_and_rank_empty() -> None:
    assert fuse_and_rank([], [], [], top_k=5) == []


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> list[dict[str, object]]:
        return self._rows


class _FakeConnection:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results

    async def execute(self, statement: object, params: dict[str, object]) -> _FakeResult:
        return self._results.pop(0)

    async def __aenter__(self) -> "_FakeConnection":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class _FakeEngine:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = results

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._results)


def _row(chunk_id: str, similarity: float) -> dict[str, object]:
    return {
        "id": chunk_id,
        "source_uri": f"file:docs/{chunk_id}.md",
        "section_anchor": "Doc",
        "content": f"content {chunk_id}",
        "source_type": "policy",
        "similarity": similarity,
    }


async def test_retriever_retrieves_and_ranks() -> None:
    engine = _FakeEngine(
        [
            _FakeResult([_row("a", 0.9), _row("b", 0.8)]),
            _FakeResult([_row("b", 0.1), _row("c", 0.0)]),
            _FakeResult([_row("c", 0.0)]),
        ]
    )

    async def embed(texts: list[str]) -> list[list[float]]:
        assert texts == ["what is parental leave?"]
        return [[0.1] * 1024]

    retriever = Retriever(cast(AsyncEngine, engine), embed)
    chunks = await retriever.retrieve(
        "what is parental leave?", dept="Engineering", role="employee"
    )

    assert len(chunks) == 3
    assert chunks[0].score >= chunks[1].score >= chunks[2].score
