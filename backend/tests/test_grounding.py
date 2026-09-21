from app.prompts.loader import load_prompt, prompt_version
from app.rag.grounding import (
    CITE_OR_DIE,
    build_context,
    build_grounding_messages,
    to_sources,
)
from app.rag.retrieval import RetrievedChunk


def _chunk(index: str, source_uri: str, anchor: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=index,
        source_uri=source_uri,
        section_anchor=anchor,
        content=content,
        source_type="policy",
        similarity=0.9,
        score=0.5,
    )


def test_prompt_registry_loads_grounding() -> None:
    prompt = load_prompt("grounding")
    assert prompt.name == "grounding"
    assert prompt.version == "1"
    assert "ONLY the context" in prompt.system
    assert "{context}" in prompt.user
    assert "{query}" in prompt.user


def test_prompt_version_format() -> None:
    assert prompt_version("grounding") == "grounding.v1"


def test_build_context_numbers_entries() -> None:
    chunks = [
        _chunk("a", "file:docs/a.md", "A", "body a"),
        _chunk("b", "file:docs/b.md", "B", "body b"),
    ]
    context = build_context(chunks)
    assert "[1]" in context
    assert "[2]" in context
    assert "body a" in context
    assert "file:docs/a.md" in context


def test_build_grounding_messages_formats_query() -> None:
    chunks = [_chunk("a", "file:docs/a.md", "A", "16 weeks of leave")]
    messages, version = build_grounding_messages("How much leave?", chunks)
    assert version == "grounding.v1"
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert "How much leave?" in messages[1].content
    assert "16 weeks of leave" in messages[1].content


def test_to_sources_maps_fields() -> None:
    chunks = [_chunk("a", "file:docs/a.md", "A", "body")]
    sources = to_sources(chunks)
    assert sources[0].id == "a"
    assert sources[0].source_uri == "file:docs/a.md"
    assert sources[0].score == 0.5


def test_cite_or_die_is_exact_fallback() -> None:
    assert CITE_OR_DIE == "I don't know"
