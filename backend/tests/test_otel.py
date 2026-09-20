import logging

from app.core.logging import JsonFormatter
from app.core.otel import init_otel


def test_init_otel_with_endpoint() -> None:
    init_otel("test-service", "http://localhost:4318/v1/traces")


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
