from typing import cast

from sqlalchemy.ext.asyncio import AsyncEngine

from app.eval.security import (
    INJECTION_KIND,
    NO_CONTEXT_KIND,
    RAG_KIND,
    SQL_KIND,
    InjectionCanary,
    RagCanary,
    SqlCanary,
    run_contextless_canaries,
    run_injection_canaries,
    run_rag_canaries,
    run_security_canaries,
    run_sql_canaries,
)
from app.rag.retrieval import RetrievedChunk, Retriever
from app.router.router import IntentRouter
from app.router.schema import Intent, RouteDecision, Surface
from app.text_to_sql.executor import SqlExecutor, SqlResult
from app.text_to_sql.guard import SqlGuardError


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
    def __init__(
        self,
        rows: list[tuple[object, ...]],
        *,
        raise_error: bool = False,
        error: BaseException | None = None,
    ) -> None:
        self._rows = rows
        self._raise = raise_error
        self._error = error

    async def execute(
        self, sql: str, *, dept: str, role: str, principal: str, trace_id: str | None = None
    ) -> SqlResult:
        if self._error is not None:
            raise self._error
        if self._raise:
            raise SqlGuardError("only SELECT statements are allowed")
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


async def test_sql_canary_infrastructure_error_fails() -> None:
    """A probe that never ran must not be counted as a pass."""
    executor = cast(SqlExecutor, _FakeExecutor([], error=ConnectionError("database is down")))
    canary = SqlCanary("probe", "SELECT * FROM org_members", "Engineering", "employee", "Finance")
    results = await run_sql_canaries(executor, (canary,))
    assert not results[0].passed
    assert "did not run" in results[0].detail


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


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeCM:
    def __init__(self, value: object | None = None) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self if self._value is None else self._value

    async def __aexit__(self, *args: object) -> bool:
        return False


class _FakeConnection:
    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts
        self.statements: list[str] = []

    def begin(self) -> _FakeCM:
        return _FakeCM()

    async def execute(self, statement: object) -> _FakeResult | None:
        sql = str(statement)
        self.statements.append(sql)
        if "SET LOCAL ROLE" in sql:
            return None
        view = sql.split("FROM ")[1].split()[0]
        return _FakeResult(self._counts.get(view, 0))


class _FakeEngine:
    def __init__(self, counts: dict[str, int]) -> None:
        self.connection = _FakeConnection(counts)

    def connect(self) -> _FakeCM:
        return _FakeCM(self.connection)


async def test_contextless_canaries_pass_on_zero_rows() -> None:
    engine = _FakeEngine({})
    results = await run_contextless_canaries(cast(AsyncEngine, engine))
    assert len(results) == 5
    assert all(result.passed for result in results)
    assert all(result.kind == NO_CONTEXT_KIND for result in results)


async def test_contextless_canary_fails_on_leaked_rows() -> None:
    engine = _FakeEngine({"assets": 12})
    results = await run_contextless_canaries(cast(AsyncEngine, engine))
    leaked = [r for r in results if not r.passed]
    assert len(leaked) == 1
    assert "12" in leaked[0].detail


async def test_contextless_canary_counts_as_access_control() -> None:
    from app.eval.report import security_metrics

    engine = _FakeEngine({})
    summary = await run_security_canaries(
        router=cast(IntentRouter, _FakeRouter(Intent.OUT_OF_SCOPE)),
        executor=cast(SqlExecutor, _FakeExecutor([])),
        engine=cast(AsyncEngine, engine),
    )
    assert set(summary.by_kind()) == {INJECTION_KIND, SQL_KIND, NO_CONTEXT_KIND}
    metrics = security_metrics(summary)
    assert metrics["rls_canary_pass_rate"] == 1.0
    assert metrics["injection_canary_pass_rate"] == 1.0
