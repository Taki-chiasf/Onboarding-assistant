from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_instrumented = False


def init_otel(service_name: str, endpoint: str) -> None:
    global _instrumented

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    if not _instrumented:
        FastAPIInstrumentor().instrument()
        _instrumented = True
