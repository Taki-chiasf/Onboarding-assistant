import logging
from typing import cast

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.logging import JsonFormatter
from app.core.otel import init_otel


def test_init_otel_with_endpoint() -> None:
    init_otel("test-service", "http://localhost:4318/v1/traces")


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
