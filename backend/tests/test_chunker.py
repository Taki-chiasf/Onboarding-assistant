from app.rag import Chunk, chunk_id, chunk_markdown, content_hash

SAMPLE = """# Parental Leave Policy

Intro paragraph that has no heading.

## Eligibility
All employees are eligible for paid parental leave from their first day.

## Duration
Employees receive 16 weeks of fully paid leave.
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
