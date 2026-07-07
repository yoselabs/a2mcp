"""Server assembly: config -> auth -> composed gateway -> ASGI app.

Ties the five seams together into one FastMCP server and its HTTP app, with the health
monitor bound to the app lifespan and ``/health`` exposed as a custom route.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastmcp import FastMCP

from .auth import build_auth_provider
from .compose import build_gateway
from .config import GatewayConfig, load_config
from .health import HealthMonitor
from .telemetry import ToolCallSpanMiddleware, setup_otel_sdk

log = logging.getLogger("a2mcp")


@dataclass
class Gateway:
    """A built gateway: the FastMCP server plus its health monitor."""

    server: FastMCP
    monitor: HealthMonitor
    config: GatewayConfig
    auth_enabled: bool


def build_from_config(
    config: GatewayConfig,
    *,
    auth: object | None = None,
    health_interval: float = 30.0,
) -> Gateway:
    """Compose a gateway from an already-loaded config (test-friendly seam)."""
    monitor = HealthMonitor(config, interval=health_interval)

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[None]:
        await monitor.start()
        try:
            yield
        finally:
            await monitor.stop()

    server = build_gateway(
        config,
        auth=auth,
        lifespan=lifespan,
        middleware=[ToolCallSpanMiddleware()],
    )
    server.custom_route("/health", methods=["GET"])(monitor.route())

    return Gateway(server=server, monitor=monitor, config=config, auth_enabled=auth is not None)


def build_gateway_from_path(config_path: str, *, health_interval: float = 30.0) -> Gateway:
    """Full boot path: load config, wire telemetry, build auth, compose.

    Any config or auth error propagates -- the entrypoint refuses to start (fail fast).
    """
    config = load_config(config_path)
    if setup_otel_sdk():
        log.info("OpenTelemetry configured: exporting per-tool-call spans via OTLP")
    auth = build_auth_provider()
    if auth is None:
        log.warning(
            "No auth provider configured (GOOGLE_CLIENT_ID unset): serving OPEN. "
            "Bind behind a tailnet/LAN only -- do not expose publicly."
        )
    return build_from_config(config, auth=auth, health_interval=health_interval)
