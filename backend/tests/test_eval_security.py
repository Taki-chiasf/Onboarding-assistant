from typing import cast

from app.eval.security import (
    INJECTION_KIND,
    RAG_KIND,
    SQL_KIND,
    InjectionCanary,
    RagCanary,
    SqlCanary,
    run_injection_canaries,
    run_rag_canaries,
    run_security_canaries,
    run_sql_canaries,
)
from app.rag.retrieval import RetrievedChunk, Retriever
from app.router.router import IntentRouter
from app.router.schema import Intent, RouteDecision, Surface
from app.text_to_sql.executor import SqlExecutor, SqlResult


def _decision(intent: Intent) -> RouteDecision:
    return RouteDecision(
        intent=intent,
        confidence=0.95,
        surfaces=[Surface.RAG_DOCS],
        entities=[],
        rationale="test",
        source="router",
    )


class _FakeRouter:
    def __init__(self, intent: Intent) -> None:
        self._intent = intent

    async def decide(self, query: str) -> RouteDecision:
        return _decision(self._intent)


class _FakeExecutor:
    def __init__(self, rows: list[tuple[object, ...]], *, raise_error: bool = False) -> None:
        self._rows = rows
        self._raise = raise_error

    async def execute(
        self, sql: str, *, dept: str, role: str, principal: str, trace_id: str | None = None
    ) -> SqlResult:
        if self._raise:
            raise ValueError("only SELECT statements are allowed")
        return SqlResult(columns=["x"], rows=self._rows, truncated=False, latency_ms=1)


def _chunk(source_type: str) -> RetrievedChunk:
    return RetrievedChunk(
        id="c1",
        source_uri=f"file:{source_type}/doc.md",
        section_anchor="doc > Intro",
        content="...",
        source_type=source_type,
        similarity=0.9,
        score=1.0,
    )


class _FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._by_dept: dict[str, list[RetrievedChunk]] = {"*": chunks}

    def for_dept(self, dept: str, chunks: list[RetrievedChunk]) -> "_FakeRetriever":
        self._by_dept[dept] = chunks
        return self

    async def retrieve(
        self,
        query: str,
        *,
        dept: str,
        role: str,
        source_types: list[str] | None = None,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        return self._by_dept.get(dept, self._by_dept["*"])


async def test_injection_canaries_pass_when_refused() -> None:
    router = cast(IntentRouter, _FakeRouter(Intent.OUT_OF_SCOPE))
    results = await run_injection_canaries(router, (InjectionCanary("ignore instructions"),))
    assert results[0].passed
    assert results[0].kind == INJECTION_KIND


async def test_injection_canary_fails_when_routed_to_sql() -> None:
    router = cast(IntentRouter, _FakeRouter(Intent.TEXT_TO_SQL))
    results = await run_injection_canaries(router, (InjectionCanary("ignore instructions"),))
    assert not results[0].passed
    assert "text-to-sql" in results[0].detail


async def test_sql_canaries_pass_on_zero_rows() -> None:
    executor = cast(SqlExecutor, _FakeExecutor([]))
    canary = SqlCanary("probe", "SELECT * FROM org_members", "Engineering", "employee", "Finance")
    results = await run_sql_canaries(executor, (canary,))
    assert results[0].passed
    assert results[0].kind == SQL_KIND


async def test_sql_canary_fails_on_leak() -> None:
    executor = cast(SqlExecutor, _FakeExecutor([("Ada", "ada@finance.example")]))
    canary = SqlCanary("probe", "SELECT * FROM org_members", "Engineering", "employee", "Finance")
    results = await run_sql_canaries(executor, (canary,))
    assert not results[0].passed
    assert "leaked" in results[0].detail


async def test_sql_canary_rejected_query_is_safe() -> None:
    executor = cast(SqlExecutor, _FakeExecutor([], raise_error=True))
    canary = SqlCanary("probe", "SELECT * FROM org_members", "Engineering", "employee", "Finance")
    results = await run_sql_canaries(executor, (canary,))
    assert results[0].passed
    assert "blocked" in results[0].detail


async def test_rag_canary_fails_on_out_of_scope_chunk() -> None:
    retriever = cast(Retriever, _FakeRetriever([_chunk("engineering")]))
    canary = RagCanary("q", "Finance", "employee", forbidden_source_types=("engineering",))
    results = await run_rag_canaries(retriever, (canary,))
    assert not results[0].passed
    assert results[0].kind == RAG_KIND


async def test_rag_canary_passes_without_out_of_scope_chunk() -> None:
    retriever = cast(Retriever, _FakeRetriever([_chunk("policy")]))
    canary = RagCanary("q", "Finance", "employee", forbidden_source_types=("engineering",))
    results = await run_rag_canaries(retriever, (canary,))
    assert results[0].passed


async def test_rag_canary_positive_control_requires_match() -> None:
    retriever = cast(Retriever, _FakeRetriever([_chunk("policy")]))
    canary = RagCanary("q", "Engineering", "employee", require_source_types=("engineering",))
    results = await run_rag_canaries(retriever, (canary,))
    assert not results[0].passed

    matching = cast(Retriever, _FakeRetriever([_chunk("engineering")]))
    results = await run_rag_canaries(matching, (canary,))
    assert results[0].passed


async def test_run_security_canaries_combines_kinds() -> None:
    retriever = _FakeRetriever([_chunk("policy")]).for_dept("Engineering", [_chunk("engineering")])
    summary = await run_security_canaries(
        router=cast(IntentRouter, _FakeRouter(Intent.OUT_OF_SCOPE)),
        executor=cast(SqlExecutor, _FakeExecutor([])),
        retriever=cast(Retriever, retriever),
    )
    assert summary.total > 0
    assert summary.all_passed
    assert set(summary.by_kind()) == {INJECTION_KIND, SQL_KIND, RAG_KIND}
