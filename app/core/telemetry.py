from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar, cast

from flask import Flask

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except Exception:  # pragma: no cover - optional dependency guard
    trace: Any = None

F = TypeVar("F", bound=Callable[..., Any])


def init_tracing(app: Flask) -> None:
    if trace is None:
        app.logger.warning("OpenTelemetry dependencies missing; tracing disabled")
        return
    endpoint = (app.config.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    if not endpoint:
        app.logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set; tracing disabled")
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "pindora-pms"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FlaskInstrumentor().instrument_app(app)

    from app.extensions import db

    with app.app_context():
        engine = getattr(db, "engine", None)
        if engine is not None:
            SQLAlchemyInstrumentor().instrument(engine=engine)


def traced(span_name: str | None = None) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if trace is None:
                return func(*args, **kwargs)
            tracer = trace.get_tracer("pindora-pms.services")
            name = span_name or func.__qualname__
            with tracer.start_as_current_span(name):
                return func(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


def trace_http_call(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if trace is None:
        return fn(*args, **kwargs)
    tracer = trace.get_tracer("pindora-pms.http")
    with tracer.start_as_current_span(name) as span:
        span.set_attribute("http.target", name)
        return fn(*args, **kwargs)
