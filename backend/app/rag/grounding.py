"""Grounded answer assembly.

Retrieved chunks are formatted into a numbered context that the grounding
prompt instructs the model to cite inline. The cite-or-die fallback is the
empty-context answer returned without an LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.provider import ChatMessage
from app.prompts.loader import load_prompt, prompt_version
from app.rag.retrieval import RetrievedChunk

CITE_OR_DIE = "I don't know"
GROUNDING_PROMPT = "grounding"


@dataclass(frozen=True)
class Source:
    id: str
    source_uri: str
    section_anchor: str
    score: float


def to_sources(chunks: list[RetrievedChunk]) -> list[Source]:
    return [
        Source(
            id=chunk.id,
            source_uri=chunk.source_uri,
            section_anchor=chunk.section_anchor,
            score=chunk.score,
        )
        for chunk in chunks
    ]


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
