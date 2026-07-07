"""C4 + V3: a tool call emits a span identifying the backend and tool."""

from __future__ import annotations

import pytest
from fastmcp import Client
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from a2mcp.config import Backend, Endpoint, GatewayConfig
from a2mcp.server import build_from_config
from a2mcp.telemetry import _split_namespaced


def test_split_namespaced() -> None:
    assert _split_namespaced("home_ha_get_state") == ("home", "ha", "get_state")
    assert _split_namespaced("a_b") == ("a", None, "b")
    assert _split_namespaced("solo") == (None, None, "solo")


@pytest.mark.asyncio
async def test_tool_call_emits_backend_span(stub_backend: str) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Our middleware uses fastmcp's tracer, which resolves the global provider.
    trace._TRACER_PROVIDER = None  # reset any prior global
    trace.set_tracer_provider(provider)

    ep = Endpoint(backends=[Backend(name="ha", url=stub_backend)])
    cfg = GatewayConfig(endpoints={"home": ep})
    gw = build_from_config(cfg)
    async with Client(gw.server) as client:
        await client.call_tool("home_ha_echo", {"text": "z"})

    provider.force_flush()
    spans = exporter.get_finished_spans()
    tool_spans = [s for s in spans if s.name.startswith("tool.call")]
    assert tool_spans, f"no tool.call span among {[s.name for s in spans]}"
    attrs = tool_spans[0].attributes or {}
    assert attrs.get("a2mcp.backend") == "ha"
    assert attrs.get("a2mcp.endpoint") == "home"
    assert attrs.get("mcp.tool.name") == "home_ha_echo"
