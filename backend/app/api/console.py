"""Admin console endpoints.

The console reads operational state that already exists elsewhere: the search
index's per-source status, the questions the assistant could not answer or
routed with low confidence, the nightly eval history with the feedback split,
and a flattened span view fetched from the trace backend so a trace can be
inspected without leaving the console.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Float, cast, func, or_, select

from app.api.admin import AdminDep, SessionFactoryDep
from app.core.deps import SettingsDep
from app.eval.gates import GATES
from app.eval.report import FALLBACK_TEXTS, is_dont_know
from app.models import Conversation, DocChunk, Feedback, IngestJob, Message, NightlyEvalRun
from app.router.guardrails import LOW_CONFIDENCE

router = APIRouter(prefix="/api/admin", tags=["console"])

MAX_ROWS = 200
MAX_TRACE_SPANS = 500
MAX_ATTRIBUTE_CHARS = 200
MAX_INGEST_JOBS = 20


class IngestSource(BaseModel):
    source_uri: str
    source_type: str
    chunks: int
    last_ingested: str


class IngestJobStatus(BaseModel):
    id: str
    source_uri: str
    status: str
    rows_written: int | None
    error: str | None
    started_at: str | None
    finished_at: str | None


class IngestStatus(BaseModel):
    total_chunks: int
    total_sources: int
    last_ingested: str | None
    sources: list[IngestSource]
    jobs: list[IngestJobStatus]


class AttentionItem(BaseModel):
    message_id: str
    question: str | None
    answer: str
    reasons: list[str]
    intent: str | None
    confidence: float | None
    trace_id: str | None
    user_id: str | None
    created_at: str


class AttentionList(BaseModel):
    items: list[AttentionItem]


class EvalRunPoint(BaseModel):
    run_at: str
    passed: bool
    strict: bool
    keyless: bool
    streak: int
    regressions: list[str]
    metrics: dict[str, float]


class GateTarget(BaseModel):
    target: float
    direction: str


class FeedbackSplit(BaseModel):
    real: int
    synthetic: int


class EvalHistory(BaseModel):
    runs: list[EvalRunPoint]
    feedback: FeedbackSplit
    latest_sections: dict[str, Any] | None
    gate_targets: dict[str, GateTarget]


class SpanView(BaseModel):
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str | None
    start_ms: float
    duration_ms: float
    status: str
    attributes: dict[str, str]


class TraceView(BaseModel):
    trace_id: str
    found: bool
    spans: list[SpanView]


@router.get("/ingest", response_model=IngestStatus)
async def ingest_status(_admin: AdminDep, factory: SessionFactoryDep) -> IngestStatus:
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    DocChunk.source_uri,
                    DocChunk.source_type,
                    func.count(DocChunk.id),
                    func.max(DocChunk.ingested_at),
                )
                .group_by(DocChunk.source_uri, DocChunk.source_type)
                .order_by(DocChunk.source_uri)
            )
        ).all()
        jobs = (
            (
                await session.execute(
                    select(IngestJob)
                    .order_by(IngestJob.started_at.desc().nullslast())
                    .limit(MAX_INGEST_JOBS)
                )
            )
            .scalars()
            .all()
        )
    sources = [
        IngestSource(
            source_uri=source_uri,
            source_type=source_type,
            chunks=int(chunks),
            last_ingested=last_ingested.isoformat(),
        )
        for source_uri, source_type, chunks, last_ingested in rows
    ]
    return IngestStatus(
        total_chunks=sum(source.chunks for source in sources),
        total_sources=len(sources),
        last_ingested=max((source.last_ingested for source in sources), default=None),
        sources=sources,
        jobs=[
            IngestJobStatus(
                id=str(job.id),
                source_uri=job.source_uri,
                status=job.status,
                rows_written=job.rows_written,
                error=job.error,
                started_at=job.started_at.isoformat() if job.started_at else None,
                finished_at=job.finished_at.isoformat() if job.finished_at else None,
            )
            for job in jobs
        ],
    )


def previous_question(
    index: Mapping[uuid.UUID, Sequence[tuple[datetime, str]]],
    conversation_id: uuid.UUID,
    asked_at: datetime,
) -> str | None:
    """The latest user question at or before the answer was produced."""
    candidate: str | None = None
    for created_at, content in index.get(conversation_id, ()):
        if created_at > asked_at:
            break
        candidate = content
    return candidate


def attention_reasons(content: str, confidence: float | None) -> list[str]:
    reasons: list[str] = []
    if is_dont_know(content):
        reasons.append("dont_know")
    if confidence is not None and confidence < LOW_CONFIDENCE:
        reasons.append("low_confidence")
    return reasons


@router.get("/attention", response_model=AttentionList)
async def attention_list(
    _admin: AdminDep, factory: SessionFactoryDep, limit: int = 20
) -> AttentionList:
    bounded = max(1, min(limit, MAX_ROWS))
    # The stored answer may be the deterministic fallback copy or the model's
    # own phrasing of it, so punctuation and case are normalized before the
    # exact comparison.
    normalized = func.regexp_replace(
        func.btrim(func.lower(Message.content)), r"[.!?[:space:]]+$", ""
    )
    confidence = cast(Message.detail["route"]["router_confidence"].astext, Float)
    async with factory() as session:
        flagged = (
            await session.execute(
                select(Message, Conversation.user_id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.role == "assistant",
                    or_(
                        normalized.in_(FALLBACK_TEXTS),
                        confidence < LOW_CONFIDENCE,
                    ),
                )
                .order_by(Message.created_at.desc())
                .limit(bounded)
            )
        ).all()
        questions: dict[uuid.UUID, list[tuple[datetime, str]]] = {}
        conversation_ids = {message.conversation_id for message, _ in flagged}
        if conversation_ids:
            user_rows = (
                await session.execute(
                    select(Message.conversation_id, Message.content, Message.created_at)
                    .where(
                        Message.conversation_id.in_(conversation_ids),
                        Message.role == "user",
                    )
                    .order_by(Message.created_at.asc())
                )
            ).all()
            for conversation_id, content, created_at in user_rows:
                questions.setdefault(conversation_id, []).append((created_at, content))

    items: list[AttentionItem] = []
    for message, user_id in flagged:
        route = (message.detail or {}).get("route") or {}
        route_confidence = route.get("router_confidence")
        items.append(
            AttentionItem(
                message_id=str(message.id),
                question=previous_question(questions, message.conversation_id, message.created_at),
                answer=message.content,
                reasons=attention_reasons(message.content, route_confidence),
                intent=route.get("intent"),
                confidence=route_confidence,
                trace_id=message.trace_id,
                user_id=user_id,
                created_at=message.created_at.isoformat(),
            )
        )
    return AttentionList(items=items)


@router.get("/eval", response_model=EvalHistory)
async def eval_history(
    _admin: AdminDep, factory: SessionFactoryDep, limit: int = 30
) -> EvalHistory:
    bounded = max(1, min(limit, MAX_ROWS))
    async with factory() as session:
        nightly = (
            (
                await session.execute(
                    select(NightlyEvalRun).order_by(NightlyEvalRun.run_at.desc()).limit(bounded)
                )
            )
            .scalars()
            .all()
        )
        feedback_rows = (
            await session.execute(
                select(Feedback.source, func.count(Feedback.id)).group_by(Feedback.source)
            )
        ).all()

    split = FeedbackSplit(real=0, synthetic=0)
    for source, count in feedback_rows:
        if source == "real":
            split.real = int(count)
        elif source == "synthetic":
            split.synthetic = int(count)

    runs = [
        EvalRunPoint(
            run_at=run.run_at.isoformat(),
            passed=run.passed,
            strict=run.strict,
            keyless=run.keyless,
            streak=run.streak,
            regressions=list(run.regressions or []),
            metrics={name: float(value) for name, value in (run.metrics or {}).items()},
        )
        for run in reversed(nightly)
    ]
    return EvalHistory(
        runs=runs,
        feedback=split,
        latest_sections=nightly[0].sections if nightly else None,
        gate_targets={
            gate.name: GateTarget(target=gate.target, direction=gate.direction) for gate in GATES
        },
    )


def _hex_id(encoded: str | None) -> str | None:
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded).hex()
    except Exception:  # noqa: BLE001 - an already-hex id is fine to pass through
        return encoded


def _span_kind(value: str | None) -> str | None:
    if not value:
        return None
    return value.removeprefix("SPAN_KIND_").lower() or None


def _attribute_text(value: Mapping[str, Any]) -> str | None:
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            text = str(value[key])
            return text[:MAX_ATTRIBUTE_CHARS]
    return None


def parse_tempo_trace(trace_id: str, payload: Mapping[str, Any]) -> TraceView:
    """Flatten Tempo's OTLP JSON into a start-ordered, trace-relative view."""
    collected: list[SpanView] = []
    starts: list[int] = []
    for batch in payload.get("batches") or ():
        for scope in batch.get("scopeSpans") or ():
            for span in scope.get("spans") or ():
                if len(collected) >= MAX_TRACE_SPANS:
                    break
                start_ns = int(span.get("startTimeUnixNano") or 0)
                end_ns = int(span.get("endTimeUnixNano") or start_ns)
                attributes: dict[str, str] = {}
                for attribute in span.get("attributes") or ():
                    text = _attribute_text(attribute.get("value") or {})
                    if text is not None:
                        attributes[str(attribute.get("key"))] = text
                status_code = str((span.get("status") or {}).get("code") or "")
                collected.append(
                    SpanView(
                        span_id=_hex_id(span.get("spanId")) or "",
                        parent_span_id=_hex_id(span.get("parentSpanId")),
                        name=str(span.get("name") or ""),
                        kind=_span_kind(span.get("kind")),
                        start_ms=0.0,
                        duration_ms=(end_ns - start_ns) / 1_000_000,
                        status={
                            "STATUS_CODE_ERROR": "error",
                            "STATUS_CODE_OK": "ok",
                        }.get(status_code, "unset"),
                        attributes=attributes,
                    )
                )
                starts.append(start_ns)
    if not collected:
        return TraceView(trace_id=trace_id, found=False, spans=[])
    origin = min(starts)
    spans = [
        span.model_copy(update={"start_ms": (start - origin) / 1_000_000})
        for start, span in sorted(zip(starts, collected, strict=True), key=lambda item: item[0])
    ]
    return TraceView(trace_id=trace_id, found=True, spans=spans)


@router.get("/traces/{trace_id}", response_model=TraceView)
async def trace_view(trace_id: str, _admin: AdminDep, settings: SettingsDep) -> TraceView:
    if not settings.tempo_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="trace backend is not configured",
        )
    url = f"{settings.tempo_url.rstrip('/')}/api/traces/{trace_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="trace backend unreachable",
            ) from exc
    if response.status_code == 404:
        return TraceView(trace_id=trace_id, found=False, spans=[])
    if not response.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"trace backend returned {response.status_code}",
        )
    return parse_tempo_trace(trace_id, response.json())
