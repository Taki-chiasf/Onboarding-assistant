from pathlib import Path

from scripts.corpus import CATEGORIES, PDF_SOURCES
from scripts.generate_corpus import CORPUS_ROOT, write_markdown, write_pdfs


def test_corpus_has_enough_documents() -> None:
    total = sum(len(docs) for docs in CATEGORIES.values())
    assert total >= 40


def test_pdf_sources_reference_real_documents() -> None:
    known: set[str] = set()
    for category, docs in CATEGORIES.items():
        for filename, _ in docs:
            known.add(f"{category}/{filename}")
    for _, source in PDF_SOURCES:
        assert source in known


def test_generated_markdown_matches_committed(tmp_path: Path) -> None:
    written = write_markdown(tmp_path)
    assert written >= 40

    committed = {p.relative_to(CORPUS_ROOT) for p in CORPUS_ROOT.rglob("*.md")}
    generated = {p.relative_to(tmp_path) for p in tmp_path.rglob("*.md")}
    assert committed == generated


def test_generated_pdfs_match_committed(tmp_path: Path) -> None:
    write_markdown(tmp_path)
    written = write_pdfs(tmp_path, tmp_path)
    assert written == 3

    committed = [p.name for p in (CORPUS_ROOT / "pdfs").glob("*.pdf")]
    generated = [p.name for p in (tmp_path / "pdfs").glob("*.pdf")]
    assert sorted(committed) == sorted(generated)
