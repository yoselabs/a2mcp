"""C4: per-tool-call OpenTelemetry.

FastMCP 3.x emits OTel spans natively (verified on 3.4.3) but is a no-op until an SDK
and exporter are configured. So a2mcp's job is just: configure the SDK from
``OTEL_EXPORTER_OTLP_ENDPOINT`` when set. We add ONE thin ``on_call_tool`` middleware,
built on FastMCP's own tracer, purely to guarantee the span attributes the spec names
("a span identifying the backend and tool"). It is deliberately not a lasting
abstraction over telemetry -- native spans do the heavy lifting.
"""

from __future__ import annotations

import os

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.telemetry import get_tracer

# Tool names are namespaced ``<endpoint>_<backend>_<tool>`` by composition.
_NAMESPACE_SEP = "_"


def setup_otel_sdk() -> bool:
    """Wire an OTLP exporter if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set.

    Returns True if telemetry was configured. Idempotent-ish: if a TracerProvider is
    already installed we leave it alone (tests / hosts may own it).
    """
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return True  # already configured by the host

    service = os.environ.get("OTEL_SERVICE_NAME", "a2mcp")
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return True


def _split_namespaced(tool_name: str) -> tuple[str | None, str | None, str]:
    """Best-effort split ``endpoint_backend_tool`` -> (endpoint, backend, tool)."""
    parts = tool_name.split(_NAMESPACE_SEP, 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    return None, None, tool_name


class ToolCallSpanMiddleware(Middleware):
    """Open a span per tool call, tagged with backend + tool for attribution."""

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ):
        tool_name = getattr(context.message, "name", "<unknown>")
        endpoint, backend, tool = _split_namespaced(tool_name)
        tracer = get_tracer()
        with tracer.start_as_current_span(f"tool.call {tool_name}") as span:
            span.set_attribute("mcp.tool.name", tool_name)
            span.set_attribute("mcp.tool.short", tool)
            if endpoint:
                span.set_attribute("a2mcp.endpoint", endpoint)
            if backend:
                span.set_attribute("a2mcp.backend", backend)
            return await call_next(context)
