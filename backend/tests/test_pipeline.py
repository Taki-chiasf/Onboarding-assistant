import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ingest import pipeline as pipeline_mod
from app.ingest.pipeline import (
    CorpusFile,
    acl_tags_for,
    chunk_file,
    embed_chunks,
    ingest_files,
    iter_corpus,
    plan_upsert,
    source_type_for,
)
from app.llm import MistralProvider
from app.rag import Chunk, content_hash


def _chunk(index: int, body: str) -> Chunk:
    return Chunk(
        source_uri="file:a.md",
        source_type="policy",
        section_anchor="A",
        content=body,
        content_hash=content_hash(body),
        chunk_index=index,
        acl_tags=["dept:all"],
    )


def test_source_type_mapping() -> None:
    assert source_type_for("policies") == "policy"
    assert source_type_for("handbook") == "handbook"
    assert source_type_for("runbooks") == "runbook"
    assert source_type_for("engineering") == "engineering"
    assert source_type_for("pdfs") == "policy"


def test_acl_tags_restrict_engineering() -> None:
    assert acl_tags_for("engineering") == ["dept:Engineering", "role:employee"]
    assert acl_tags_for("policy") == ["dept:all", "role:employee"]


def test_iter_corpus_discovers_files(tmp_path: Path) -> None:
    (tmp_path / "policies").mkdir()
    (tmp_path / "engineering").mkdir()
    (tmp_path / "policies" / "a.md").write_text("# A")
    (tmp_path / "engineering" / "b.md").write_text("# B")
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "c.pdf").write_bytes(b"%PDF")
    (tmp_path / "ignored.txt").write_text("x")

    files = iter_corpus(tmp_path)

    assert len(files) == 3
    uris = {f.source_uri for f in files}
    assert "file:policies/a.md" in uris
    assert "file:engineering/b.md" in uris
    assert "file:pdfs/c.pdf" in uris
    by_uri = {f.source_uri: f for f in files}
    assert by_uri["file:engineering/b.md"].source_type == "engineering"
    assert by_uri["file:pdfs/c.pdf"].source_type == "policy"


def test_chunk_file_sets_acl_and_type() -> None:
    corpus_file = CorpusFile(
        source_uri="file:engineering/b.md", source_type="engineering", path=Path("b.md")
    )
    chunks = chunk_file(corpus_file, "# Title\n\n## Section\nbody")
    assert chunks
    assert all(c.source_type == "engineering" for c in chunks)
    assert all(c.acl_tags == ["dept:Engineering", "role:employee"] for c in chunks)


def test_plan_upsert_inserts_new_chunks() -> None:
    chunks = [_chunk(0, "a"), _chunk(1, "b")]
    plan = plan_upsert({}, chunks)
    assert [c.chunk_index for c in plan.to_insert] == [0, 1]
    assert plan.to_update == []
    assert plan.skipped == 0


def test_plan_upsert_skips_unchanged() -> None:
    chunk = _chunk(0, "same")
    existing = {0: (uuid.uuid4(), chunk.content_hash, 1)}
    plan = plan_upsert(existing, [chunk])
    assert plan.to_insert == []
    assert plan.to_update == []
    assert plan.skipped == 1


def test_plan_upsert_updates_changed_content() -> None:
    chunk = _chunk(0, "new body")
    existing_id = uuid.uuid4()
    existing = {0: (existing_id, content_hash("old body"), 3)}
    plan = plan_upsert(existing, [chunk])
    assert plan.to_insert == []
    assert plan.skipped == 0
    assert len(plan.to_update) == 1
    updated_id, updated_chunk, new_version = plan.to_update[0]
    assert updated_id == existing_id
    assert updated_chunk is chunk
    assert new_version == 4


async def test_embed_chunks_batches_and_maps() -> None:
    provider = MagicMock(spec=MistralProvider)
    provider.embed = AsyncMock(
        side_effect=lambda model, texts: [[float(len(t))] for t in texts]
    )
    chunks = [_chunk(0, "a"), _chunk(1, "b"), _chunk(2, "c")]

    embeddings = await embed_chunks(provider, "mistral-embed", chunks, batch_size=2)

    assert embeddings == {0: [1.0], 1: [1.0], 2: [1.0]}
    assert provider.embed.await_count == 2


class _FakeResult:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def scalars(self) -> list[SimpleNamespace]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows
        self.added: list[object] = []
        self.committed = False

    async def execute(self, statement: object) -> _FakeResult:
        return _FakeResult(self._rows)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


def _fake_provider() -> MagicMock:
    provider = MagicMock(spec=MistralProvider)
    provider.embed = AsyncMock(side_effect=lambda model, texts: [[1.0] * 3 for _ in texts])
    return provider


def _markdown_file(tmp_path: Path) -> CorpusFile:
    path = tmp_path / "policies" / "a.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Title\n\n## A\nbody", encoding="utf-8")
    return CorpusFile(source_uri="file:policies/a.md", source_type="policy", path=path)


async def test_ingest_files_inserts_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession([])
    monkeypatch.setattr(
        pipeline_mod,
        "async_sessionmaker",
        lambda engine, expire_on_commit: (lambda: session),
    )

    stats = await ingest_files(
        MagicMock(), _fake_provider(), "mistral-embed", "mistral-ocr-4-0",
        [_markdown_file(tmp_path)],
    )

    assert stats.files == 1
    assert stats.inserted > 0
    assert stats.updated == 0
    assert stats.skipped == 0
    assert stats.embedded == stats.inserted
    assert session.committed
    assert len(session.added) == stats.inserted


async def test_ingest_files_skips_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus_file = _markdown_file(tmp_path)
    chunks = chunk_file(corpus_file, corpus_file.path.read_text(encoding="utf-8"))
    existing_rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            chunk_index=c.chunk_index,
            content_hash=c.content_hash,
            version=1,
        )
        for c in chunks
    ]
    session = _FakeSession(existing_rows)
    monkeypatch.setattr(
        pipeline_mod,
        "async_sessionmaker",
        lambda engine, expire_on_commit: (lambda: session),
    )

    stats = await ingest_files(
        MagicMock(), _fake_provider(), "mistral-embed", "mistral-ocr-4-0", [corpus_file]
    )

    assert stats.inserted == 0
    assert stats.updated == 0
    assert stats.skipped == len(chunks)
    assert stats.embedded == 0


def _pdf_file(tmp_path: Path) -> CorpusFile:
    path = tmp_path / "pdfs" / "guide.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4")
    return CorpusFile(source_uri="file:pdfs/guide.pdf", source_type="policy", path=path)


async def test_ingest_continues_past_an_unreadable_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession([])
    monkeypatch.setattr(
        pipeline_mod,
        "async_sessionmaker",
        lambda engine, expire_on_commit: (lambda: session),
    )
    provider = _fake_provider()
    provider.ocr_pdf = AsyncMock(side_effect=RuntimeError("ocr unavailable"))

    stats = await ingest_files(
        MagicMock(),
        provider,
        "mistral-embed",
        "mistral-ocr-4-0",
        [_pdf_file(tmp_path), _markdown_file(tmp_path)],
    )

    assert stats.files == 2
    assert stats.failed == 1
    assert stats.inserted > 0
    assert session.committed


async def test_ingest_marks_a_file_unreadable_when_it_cannot_be_decoded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _FakeSession([])
    monkeypatch.setattr(
        pipeline_mod,
        "async_sessionmaker",
        lambda engine, expire_on_commit: (lambda: session),
    )
    path = tmp_path / "policies" / "bad.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00binary")
    corpus_file = CorpusFile(source_uri="file:policies/bad.md", source_type="policy", path=path)

    stats = await ingest_files(
        MagicMock(), _fake_provider(), "mistral-embed", "mistral-ocr-4-0", [corpus_file]
    )

    assert stats.failed == 1
    assert stats.inserted == 0
