"""Schema-aware SQL generation.

Turns a natural-language question into a single read-only SELECT using the
builder prompt, then re-validates the model's output through the same guard the
executor uses. Builder output is never trusted: it is re-checked before it can
reach the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.llm.pricing import estimate_tokens
from app.llm.provider import ChatMessage, ChatProvider
from app.prompts.loader import load_prompt, prompt_version
from app.text_to_sql.guard import validate_query

SQL_BUILDER_PROMPT = "sql_builder"

_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class BuiltSql:
    sql: str
    prompt_version: str
    tokens_in: int


def extract_sql(text: str) -> str:
    """Return the first statement text, stripping code fences and a trailing semicolon."""
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1)
    stripped = text.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    return stripped


class SqlBuilder:
    def __init__(self, provider: ChatProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def build(self, query: str) -> BuiltSql:
        prompt = load_prompt(SQL_BUILDER_PROMPT)
        messages = [
            ChatMessage(role="system", content=prompt.system),
            ChatMessage(role="user", content=prompt.user.format(query=query)),
        ]
        tokens_in = estimate_tokens("".join(message.content for message in messages))
        raw = await self._provider.chat(self._model, messages)
        sql = validate_query(extract_sql(raw))
        return BuiltSql(
            sql=sql, prompt_version=prompt_version(SQL_BUILDER_PROMPT), tokens_in=tokens_in
        )
