from app.rag import (
    Chunk,
    chunk_id,
    chunk_markdown,
    chunk_with_lines,
    content_hash,
    parse_line_anchor,
)

SAMPLE = """# Parental Leave Policy

Intro paragraph that has no heading.

## Eligibility
All employees are eligible for paid parental leave from their first day.

## Duration
Employees receive 16 weeks of fully paid leave.
"""

CODE = """'''Token helpers.'''

import hashlib


def sign(key: str, payload: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def verify(key: str, payload: str, signature: str) -> bool:
    expected = sign(key, payload)
    return expected == signature
"""


def test_chunk_markdown_splits_by_headings() -> None:
    chunks = chunk_markdown(
        "file:policies/parental-leave.md",
        "policy",
        SAMPLE,
        ["dept:all"],
    )

    assert len(chunks) == 3
    assert chunks[0].section_anchor == "Parental Leave Policy"
    assert chunks[1].section_anchor == "Parental Leave Policy > Eligibility"
    assert chunks[2].section_anchor == "Parental Leave Policy > Duration"
    assert all(c.source_uri == "file:policies/parental-leave.md" for c in chunks)
    assert all(c.source_type == "policy" for c in chunks)
    assert all(c.acl_tags == ["dept:all"] for c in chunks)


def test_chunk_indices_are_sequential() -> None:
    chunks = chunk_markdown("file:policies/a.md", "policy", SAMPLE, ["dept:all"])
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_chunk_ids_are_deterministic() -> None:
    first = chunk_markdown("file:policies/a.md", "policy", SAMPLE, ["dept:all"])
    second = chunk_markdown("file:policies/a.md", "policy", SAMPLE, ["dept:all"])
    assert [c.chunk_index for c in first] == [c.chunk_index for c in second]
    assert chunk_id("file:policies/a.md", 1) == chunk_id("file:policies/a.md", 1)
    assert chunk_id("file:policies/a.md", 1) != chunk_id("file:policies/a.md", 2)


def test_content_hash_is_stable_sha256() -> None:
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
    assert len(content_hash("abc")) == 64


def test_chunk_content_hashes_match_content() -> None:
    chunks = chunk_markdown("file:policies/a.md", "policy", SAMPLE, ["dept:all"])
    for chunk in chunks:
        assert chunk.content_hash == content_hash(chunk.content)


def test_long_section_is_split_and_keeps_anchor() -> None:
    long_body = "\n\n".join(f"paragraph {i} with enough words to fill space" for i in range(200))
    text = f"# Big Doc\n\n## Huge Section\n{long_body}\n"
    chunks = chunk_markdown(
        "file:policies/big.md", "policy", text, ["dept:all"], max_chunk_chars=100
    )
    assert len(chunks) > 1
    assert all(c.section_anchor == "Big Doc > Huge Section" for c in chunks)


def test_chunk_is_a_valid_model() -> None:
    chunk = Chunk(
        source_uri="u",
        source_type="policy",
        section_anchor="a",
        content="c",
        content_hash=content_hash("c"),
        chunk_index=0,
        acl_tags=["dept:all"],
    )
    assert chunk.content == "c"


def test_chunk_with_lines_anchors_functions() -> None:
    chunks = chunk_with_lines(
        "file:code/services/auth/tokens.py",
        "code",
        CODE,
        ["dept:Engineering"],
    )

    anchors = [chunk.section_anchor for chunk in chunks]
    assert any("sign" in anchor for anchor in anchors)
    assert any("verify" in anchor for anchor in anchors)
    assert all(parse_line_anchor(anchor) is not None for anchor in anchors)
    assert all(chunk.source_type == "code" for chunk in chunks)
    assert all(chunk.acl_tags == ["dept:Engineering"] for chunk in chunks)


def test_chunk_with_lines_content_matches_the_line_range() -> None:
    chunks = chunk_with_lines("file:code/a.py", "code", CODE, ["dept:Engineering"])
    lines = CODE.splitlines()

    for chunk in chunks:
        start, end = parse_line_anchor(chunk.section_anchor) or (0, 0)
        assert chunk.content == "\n".join(lines[start - 1 : end])


def test_chunk_with_lines_splits_oversized_blocks() -> None:
    body = "\n".join(f"value_{i} = {i}" for i in range(400))
    chunks = chunk_with_lines(
        "file:code/big.py",
        "code",
        f"'''Big module.'''\n\n{body}\n",
        ["dept:all"],
        max_chunk_chars=200,
    )

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 200 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))


def test_chunk_with_lines_is_deterministic() -> None:
    first = chunk_with_lines("file:code/a.py", "code", CODE, ["dept:Engineering"])
    second = chunk_with_lines("file:code/a.py", "code", CODE, ["dept:Engineering"])
    assert [(c.chunk_index, c.section_anchor, c.content_hash) for c in first] == [
        (c.chunk_index, c.section_anchor, c.content_hash) for c in second
    ]
    assert [str(c.chunk_index) for c in first] == [str(i) for i in range(len(first))]
    assert chunk_id("file:code/a.py", 0) == chunk_id("file:code/a.py", 0)


def test_chunk_with_lines_handles_blank_input() -> None:
    assert chunk_with_lines("file:code/empty.py", "code", "\n\n", ["dept:all"]) == []
