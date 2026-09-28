"""Writes the synthetic document corpus to disk (markdown + a few PDFs).

The corpus is synthetic and deterministic: running this script always produces
identical files, so the committed corpus is reproducible without any external
data source.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fpdf import FPDF

from scripts.corpus import CATEGORIES, PDF_SOURCES

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "seed_corpus"


def write_markdown(root: Path) -> int:
    written = 0
    for category, docs in CATEGORIES.items():
        category_dir = root / category
        category_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in docs:
            path = category_dir / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written += 1
    return written


def _plain_text(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        stripped = line.lstrip("#").strip()
        if stripped.startswith("-"):
            stripped = "- " + stripped[1:].strip()
        lines.append(stripped)
    return "\n".join(lines)


def write_pdfs(root: Path, markdown_root: Path) -> int:
    pdf_dir = root / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for pdf_name, source in PDF_SOURCES:
        source_path = markdown_root / source
        content = _plain_text(source_path.read_text(encoding="utf-8"))
        pdf = FPDF()
        pdf.set_margins(left=15, top=15, right=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        for line in content.splitlines():
            if line.strip():
                pdf.multi_cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
        pdf.output(str(pdf_dir / pdf_name))
        written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the sample document corpus")
    parser.add_argument("--out", type=Path, default=CORPUS_ROOT)
    args = parser.parse_args()

    markdown_count = write_markdown(args.out)
    pdf_count = write_pdfs(args.out, args.out)
    print(f"wrote {markdown_count} markdown files and {pdf_count} PDFs to {args.out}")


if __name__ == "__main__":
    main()
