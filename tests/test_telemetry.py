"""C4 + V3: a tool call emits a span identifying the group, backend, and tool."""

from __future__ import annotations

import pytest
from fastmcp import Client
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from a2mcp.config import Backend, BackendRef, GatewayConfig, Group
from a2mcp.server import build_from_config
from a2mcp.telemetry import _split_namespaced


def test_split_namespaced() -> None:
    # With known prefixed backends, split at the backend marker.
    assert _split_namespaced("ha_get_state", ("ha",)) == ("ha", "get_state")
    # A bare name (unprefixed backend) is attributed to it, not split.
    assert _split_namespaced("get_state", (), "ha") == ("ha", "get_state")
    # No backend info -> best-effort first-underscore split.
    assert _split_namespaced("a_b") == ("a", "b")
    assert _split_namespaced("solo") == (None, "solo")


@pytest.mark.asyncio
async def test_tool_call_emits_group_and_backend_span(stub_backend: str) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace._TRACER_PROVIDER = None  # reset any prior global
    trace.set_tracer_provider(provider)

    cfg = GatewayConfig(
        backends={"ha": Backend(name="ha", url=stub_backend)},
        groups={"admin": Group(backends=[BackendRef(name="ha")])},
    )
    gw = build_from_config(cfg)
    async with Client(gw.servers["admin"]) as client:
        await client.call_tool("ha_echo", {"text": "z"})

    provider.force_flush()
    spans = exporter.get_finished_spans()
    tool_spans = [s for s in spans if s.name.startswith("tool.call")]
    assert tool_spans, f"no tool.call span among {[s.name for s in spans]}"
    attrs = tool_spans[0].attributes or {}
    assert attrs.get("a2mcp.backend") == "ha"
    assert attrs.get("a2mcp.group") == "admin"
    assert attrs.get("a2mcp.group.url") == "/admin/mcp"
    assert attrs.get("mcp.tool.name") == "ha_echo"
