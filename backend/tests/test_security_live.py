"""Live security canary tests.

Run against a real seeded Postgres (skipped when unreachable). The SQL canaries
assert that a caller cannot read another department's rows. The document
canaries only run once the corpus has been ingested, since retrieval needs a
populated chunk store.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.eval.security import run_rag_canaries, run_sql_canaries
from app.llm.fake import FakeProvider
from app.rag.retrieval import Retriever
from app.text_to_sql.executor import SqlExecutor
from scripts.seed import seed

DATABASE_URL = os.environ.get("DATABASE_URL") or ""


@pytest.fixture(scope="module")
def seeded() -> None:
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL is not set")
    sync_engine = create_engine(DATABASE_URL)
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        sync_engine.dispose()
        pytest.skip("Postgres is not reachable")
    seed(sync_engine)
    sync_engine.dispose()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(DATABASE_URL)
    yield engine
    await engine.dispose()


async def test_sql_access_canaries_all_pass(seeded: None, engine: AsyncEngine) -> None:
    results = await run_sql_canaries(SqlExecutor(engine))
    assert results
    assert all(result.passed for result in results), [r.detail for r in results]


async def test_rag_acl_canaries_all_pass(seeded: None, engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM doc_chunks"))).scalar()
    if not count:
        pytest.skip("corpus is not ingested")

    provider = FakeProvider()

    async def embed(texts: list[str]) -> list[list[float]]:
        return await provider.embed("mistral-embed", texts)

    retriever = Retriever(engine, embed)
    results = await run_rag_canaries(retriever)
    assert results
    assert all(result.passed for result in results), [r.detail for r in results]
