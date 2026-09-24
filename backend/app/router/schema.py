"""Intent router types.

The router returns one of five intents with a confidence, the concrete answer
surfaces, extracted entities, and a short rationale. The same Pydantic model
drives the JSON schema handed to the model, so the structured-output contract
and the re-validation step can never drift apart.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Intent(StrEnum):
    RAG_DOCS = "rag-docs"
    RAG_CODE = "rag-code"
    TEXT_TO_SQL = "text-to-sql"
    OUT_OF_SCOPE = "out-of-scope"
    AMBIGUOUS = "ambiguous"


class Surface(StrEnum):
    RAG_DOCS = "rag-docs"
    RAG_CODE = "rag-code"
    TEXT_TO_SQL = "text-to-sql"


SURFACE_LABELS: dict[Surface, str] = {
    Surface.RAG_DOCS: "Company documents",
    Surface.RAG_CODE: "Engineering docs",
    Surface.TEXT_TO_SQL: "Live org data",
}


class RouterVerdict(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    secondary: str = ""
    surfaces: list[Surface] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    rationale: str = ""


class ClarifyOption(BaseModel):
    surface: Surface
    label: str


class ClarifyPrompt(BaseModel):
    kind: Literal["surface", "interpretation"]
    question: str
    options: list[ClarifyOption]


RouteSource = Literal[
    "router",
    "keyword_override",
    "low_confidence",
    "surface_disambiguation",
    "interpretation_disambiguation",
    "parse_fallback",
    "pinned",
]


class RouteDecision(BaseModel):
    intent: Intent
    confidence: float
    surfaces: list[Surface]
    entities: list[str]
    rationale: str
    source: RouteSource
    clarify: ClarifyPrompt | None = None


def verdict_json_schema() -> dict[str, Any]:
    """JSON schema handed to the model for its structured verdict."""
    return RouterVerdict.model_json_schema()
