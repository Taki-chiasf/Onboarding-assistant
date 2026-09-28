"""Grounded answer assembly.

Retrieved chunks are formatted into a numbered context that the grounding
prompt instructs the model to cite inline. The cite-or-die fallback is the
empty-context answer returned without an LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.provider import ChatMessage
from app.prompts.loader import load_prompt, prompt_version
from app.rag.chunker import parse_line_anchor
from app.rag.retrieval import RetrievedChunk

CITE_OR_DIE = "I don't know"
GROUNDING_PROMPT = "grounding"


@dataclass(frozen=True)
class Source:
    id: str
    source_uri: str
    section_anchor: str
    source_type: str
    score: float
    start_line: int | None = None
    end_line: int | None = None


def to_sources(chunks: list[RetrievedChunk]) -> list[Source]:
    sources: list[Source] = []
    for chunk in chunks:
        line_span = parse_line_anchor(chunk.section_anchor)
        sources.append(
            Source(
                id=chunk.id,
                source_uri=chunk.source_uri,
                section_anchor=chunk.section_anchor,
                source_type=chunk.source_type,
                score=chunk.score,
                start_line=line_span[0] if line_span else None,
                end_line=line_span[1] if line_span else None,
            )
        )
    return sources


def build_context(chunks: list[RetrievedChunk]) -> str:
    entries = [
        f"[{index}] ({chunk.source_uri} — {chunk.section_anchor})\n{chunk.content}"
        for index, chunk in enumerate(chunks, start=1)
    ]
    return "\n\n".join(entries)


def build_grounding_messages(
    query: str, chunks: list[RetrievedChunk]
) -> tuple[list[ChatMessage], str]:
    prompt = load_prompt(GROUNDING_PROMPT)
    user_content = prompt.user.format(context=build_context(chunks), query=query)
    messages = [
        ChatMessage(role="system", content=prompt.system),
        ChatMessage(role="user", content=user_content),
    ]
    return messages, prompt_version(GROUNDING_PROMPT)
