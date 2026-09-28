'''Structured logging shared by the services.'''

import json
import logging
import time

from opentelemetry import trace


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        span = trace.get_current_span().get_span_context()
        entry = {
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if span.is_valid:
            entry["trace_id"] = format(span.trace_id, "032x")
        return json.dumps(entry)


def configure(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
