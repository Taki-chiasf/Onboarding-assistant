import logging
from typing import cast

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.logging import JsonFormatter
from app.core.otel import _traces_endpoint, init_otel


def test_init_otel_with_endpoint() -> None:
    init_otel("test-service", "http://localhost:4318/v1/traces")


def test_traces_endpoint_appends_path() -> None:
    assert _traces_endpoint("http://otel-collector:4318") == "http://otel-collector:4318/v1/traces"
    assert _traces_endpoint("http://x:4318/") == "http://x:4318/v1/traces"
    assert _traces_endpoint("http://x:4318/v1/traces") == "http://x:4318/v1/traces"


def test_init_otel_records_spans() -> None:
    init_otel("test-service", "")
    provider = cast(TracerProvider, trace.get_tracer_provider())
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test-span"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test-span"


async def test_fastapi_request_produces_span() -> None:
    init_otel("test-service", "")
    provider = cast(TracerProvider, trace.get_tracer_provider())
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    app = FastAPI()
    FastAPIInstrumentor.instrument_app(app)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "1"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/ping")

    spans = exporter.get_finished_spans()
    assert len(spans) >= 1


def test_json_formatter_includes_exception() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        "path",
        1,
        "boom",
        None,
        (ValueError, ValueError("bad"), None),
    )
    output = formatter.format(record)
    assert '"exception"' in output
    assert "ValueError: bad" in output
