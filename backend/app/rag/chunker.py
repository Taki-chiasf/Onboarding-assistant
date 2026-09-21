"""Section-aware chunking for markdown documents.

A document is split along its heading hierarchy so that each chunk carries the
heading path that locates it in the source. Chunk identifiers and content
hashes are deterministic, which keeps re-ingestion idempotent and lets the
evaluation set reference chunks by stable identifiers.
"""

from __future__ import annotations

import hashlib
import re
import uuid

from pydantic import BaseModel

ATX_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

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
    if stem.endswith(".md"):
        stem = stem[:-3]
    return stem.replace("-", " ").title()
