import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_intent: Mapped[str | None] = mapped_column(String(32))
    expected_source_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    expected_sql_pattern: Mapped[str | None] = mapped_column(Text)
    expected_rows_predicate: Mapped[str | None] = mapped_column(Text)
    expected_access_control: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Provenance of a candidate case: which signal filed it and which answer
    # message it came from, so the review queue can show the full trace.
    source: Mapped[str | None] = mapped_column(String(16))
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_cases.id", ondelete="CASCADE"), nullable=False
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Which replay produced the row (router, sql, docs) and under which
    # persona scope, so a failure can be traced to one execution.
    suite: Mapped[str | None] = mapped_column(String(16))
    persona: Mapped[str | None] = mapped_column(String(64))
    actual_answer: Mapped[str | None] = mapped_column(Text)
    actual_intent: Mapped[str | None] = mapped_column(String(32))
    router_confidence: Mapped[float | None] = mapped_column(Float)
    retrieved_source_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    judge_passed: Mapped[bool | None] = mapped_column(Boolean)
    diff: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    rls_canary_passed: Mapped[bool | None] = mapped_column(Boolean)
    injection_canary_passed: Mapped[bool | None] = mapped_column(Boolean)


class NightlyEvalRun(Base):
    __tablename__ = "nightly_eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    strict: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    keyless: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    prompt_version: Mapped[str | None] = mapped_column(String(255))
    model_version: Mapped[str | None] = mapped_column(String(255))
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sections: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    regressions: Mapped[list[str] | None] = mapped_column(JSONB)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
