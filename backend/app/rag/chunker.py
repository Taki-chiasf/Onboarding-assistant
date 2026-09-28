"""Section-aware chunking for markdown documents and line-anchored chunking
for source files.

A markdown document is split along its heading hierarchy so that each chunk
carries the heading path that locates it in the source. A source file is split
into contiguous line ranges so that each chunk carries a ``file:line`` anchor
that the citation viewer can open. Chunk identifiers and content hashes are
deterministic, which keeps re-ingestion idempotent and lets the evaluation set
reference chunks by stable identifiers.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from pydantic import BaseModel

ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LINE_ANCHOR = re.compile(r"^L(\d+)(?:-L(\d+))?\b")

CODE_SUFFIXES = frozenset({".py", ".sh", ".ts", ".tsx", ".js", ".sql"})

# The label that gives a line range its identity in a citation: the nearest
# symbol above the range for code, the nearest heading for markdown.
LABEL_PATTERNS = (
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function|class)\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*="),
    re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$"),
)

DEFAULT_MAX_CHUNK_CHARS = 2000


class Chunk(BaseModel):
    source_uri: str
    source_type: str
    section_anchor: str
    content: str
    content_hash: str
    chunk_index: int
    acl_tags: list[str]


def chunk_id(source_uri: str, chunk_index: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"chunk:{source_uri}:{chunk_index}")


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _heading_level(line: str) -> int:
    return len(line) - len(line.lstrip("#"))


def _split_by_headings(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Split markdown into (anchor, body) pairs following the heading path."""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    preamble: list[str] = []
    current_anchor: str | None = None
    current_body: list[str] = []

    def flush() -> None:
        nonlocal current_anchor, current_body
        if current_anchor is None:
            return
        sections.append((current_anchor, "\n".join(current_body).strip()))
        current_anchor = None
        current_body = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = ATX_HEADING.match(line)
        if match is None:
            if current_anchor is None:
                preamble.append(line)
            else:
                current_body.append(line)
            continue

        level = _heading_level(line)
        title = match.group(2).strip()
        flush()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_anchor = " > ".join(name for _, name in stack)
        current_body = []

    flush()
    return sections, preamble


def _split_long(text: str, max_chars: int) -> list[str]:
    """Split oversized text on paragraph boundaries, then whitespace."""
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts: list[str] = []
    for paragraph in paragraphs:
        if not parts or len(parts[-1]) + len(paragraph) + 2 > max_chars:
            parts.append(paragraph)
        else:
            parts[-1] = f"{parts[-1]}\n\n{paragraph}"

    result: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            result.append(part)
            continue
        words = part.split()
        buffer = ""
        for word in words:
            if buffer and len(buffer) + len(word) + 1 > max_chars:
                result.append(buffer)
                buffer = word
            else:
                buffer = f"{buffer} {word}".strip()
        if buffer:
            result.append(buffer)
    return result


def chunk_markdown(
    source_uri: str,
    source_type: str,
    text: str,
    acl_tags: list[str],
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> list[Chunk]:
    sections, preamble = _split_by_headings(text)

    title = sections[0][0].split(" > ")[0] if sections else _fallback_title(source_uri)
    body_parts: list[tuple[str, str]] = []

    if preamble and "".join(preamble).strip():
        body_parts.append((title, "\n".join(preamble).strip()))
    body_parts.extend(sections)

    chunks: list[Chunk] = []
    index = 0
    for anchor, body in body_parts:
        for piece in _split_long(body, max_chunk_chars):
            if not piece:
                continue
            chunks.append(
                Chunk(
                    source_uri=source_uri,
                    source_type=source_type,
                    section_anchor=anchor,
                    content=piece,
                    content_hash=content_hash(piece),
                    chunk_index=index,
                    acl_tags=acl_tags,
                )
            )
            index += 1
    return chunks


def _fallback_title(source_uri: str) -> str:
    stem = source_uri.rsplit("/", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return stem.replace("-", " ").title()


def parse_line_anchor(anchor: str) -> tuple[int, int] | None:
    """Read the ``L12-L40`` range out of a line-anchored section anchor."""
    match = LINE_ANCHOR.match(anchor)
    if match is None:
        return None
    start = int(match.group(1))
    return start, int(match.group(2) or start)


def _line_label(line: str) -> str | None:
    for pattern in LABEL_PATTERNS:
        match = pattern.match(line)
        if match is not None:
            return match.group(1).strip()[:64]
    return None


def _block_label(lines: list[str], start: int, end: int) -> str | None:
    """The symbol or heading a block introduces, skipping decorators and comments."""
    for number in range(start, min(end, start + 4) + 1):
        found = _line_label(lines[number - 1])
        if found is not None:
            return found
    return None


def _line_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Contiguous non-blank line ranges (1-based, inclusive), in file order."""
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines, start=1):
        if line.strip():
            start = index if start is None else start
        elif start is not None:
            blocks.append((start, index - 1))
            start = None
    if start is not None:
        blocks.append((start, len(lines)))
    return blocks


def _lines_length(lines: list[str], start: int, end: int) -> int:
    return sum(len(lines[number - 1]) + 1 for number in range(start, end + 1))


def _fit_blocks(
    lines: list[str], blocks: list[tuple[int, int]], max_chunk_chars: int
) -> list[tuple[int, int]]:
    """Split blocks that exceed the budget on line boundaries."""
    fitted: list[tuple[int, int]] = []
    for start, end in blocks:
        if _lines_length(lines, start, end) <= max_chunk_chars:
            fitted.append((start, end))
            continue
        piece_start = start
        length = 0
        for number in range(start, end + 1):
            line_length = len(lines[number - 1]) + 1
            if length and length + line_length > max_chunk_chars:
                fitted.append((piece_start, number - 1))
                piece_start = number
                length = line_length
            else:
                length += line_length
        fitted.append((piece_start, end))
    return fitted


def chunk_with_lines(
    source_uri: str,
    source_type: str,
    text: str,
    acl_tags: list[str],
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> list[Chunk]:
    """Split a source file into chunks carrying ``file:line`` anchors.

    Each chunk is a contiguous run of lines; small blocks separated by blank
    lines group together, and a block that introduces a symbol (a function,
    class, or markdown heading) starts a new chunk. The anchor is
    ``L<start>-L<end> <label>`` where the label is the symbol or heading the
    chunk opens with.
    """
    lines = text.splitlines()
    blocks = _fit_blocks(lines, _line_blocks(lines), max_chunk_chars)

    labels: dict[int, str] = {}
    label = _fallback_title(source_uri)
    for number, line in enumerate(lines, start=1):
        found = _line_label(line)
        if found is not None:
            label = found
        labels[number] = label

    chunks: list[Chunk] = []
    index = 0
    pending: tuple[int, int] | None = None
    pending_label = ""

    def emit(start: int, end: int, chunk_label: str) -> None:
        nonlocal index
        body = "\n".join(lines[start - 1 : end])
        span = f"L{start}-L{end}" if end > start else f"L{start}"
        chunks.append(
            Chunk(
                source_uri=source_uri,
                source_type=source_type,
                section_anchor=f"{span} {chunk_label}",
                content=body,
                content_hash=content_hash(body),
                chunk_index=index,
                acl_tags=acl_tags,
            )
        )
        index += 1

    for block_start, block_end in blocks:
        block_label = _block_label(lines, block_start, block_end)
        if pending is None:
            pending = (block_start, block_end)
            pending_label = block_label or labels[block_start]
        elif block_label is not None or (
            _lines_length(lines, pending[0], block_end) > max_chunk_chars
        ):
            emit(*pending, pending_label)
            pending = (block_start, block_end)
            pending_label = block_label or labels[block_start]
        else:
            pending = (pending[0], block_end)
    if pending is not None:
        emit(*pending, pending_label)
    return chunks
