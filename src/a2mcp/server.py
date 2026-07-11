"""Server assembly: config -> auth -> one FastMCP server per group -> parent ASGI app.

Each group server is mounted at ``/<group>`` in a parent Starlette app, so its MCP
endpoint is ``<base>/<group>/mcp`` (design D2). The health monitor and ``/health`` live at
the parent root; the parent lifespan runs the monitor plus every group app's own lifespan.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from .auth import GroupAuth, build_group_auth
from .compose import build_group_servers
from .config import GatewayConfig, load_config
from .health import HealthMonitor
from .telemetry import setup_otel_sdk

log = logging.getLogger("a2mcp")


@dataclass
class Gateway:
    """A built gateway: one FastMCP server per group plus its shared health monitor."""

    servers: dict[str, FastMCP]
    monitor: HealthMonitor
    config: GatewayConfig
    auth_enabled: bool
    root_auth_routes: list[object] = field(default_factory=list)

    def http_app(self) -> Starlette:
        """Assemble the parent ASGI app: shared AS at root, each group at ``/<group>``."""
        group_apps = {name: server.http_app() for name, server in self.servers.items()}

        @asynccontextmanager
        async def lifespan(_app: Starlette) -> AsyncIterator[None]:
            await self.monitor.start()
            async with AsyncExitStack() as stack:
                # Run each group app's own lifespan (FastMCP session manager, auth, etc.).
                for app in group_apps.values():
                    await stack.enter_async_context(app.router.lifespan_context(app))
                try:
                    yield
                finally:
                    await self.monitor.stop()

        routes = [
            Route("/health", self.monitor.route(), methods=["GET"]),
            # The one shared Authorization Server + each group's protected-resource
            # metadata, at the origin root so client discovery resolves (design D2).
            *self.root_auth_routes,
            *(Mount(f"/{name}", app=app) for name, app in group_apps.items()),
        ]
        return Starlette(routes=routes, lifespan=lifespan)


def build_from_config(
    config: GatewayConfig,
    *,
    auth: object | None = None,
    group_auth: GroupAuth | None = None,
    health_interval: float = 30.0,
) -> Gateway:
    """Compose a gateway from an already-loaded config (test-friendly seam).

    ``group_auth`` (the boot path) gives each group its own provider plus the shared root
    AS + per-group metadata routes. ``auth`` (tests) applies one provider to every group
    with no root routes. Telemetry + scope middleware are added inside ``build_group_server``;
    the health monitor is shared and started by the parent lifespan.
    """
    monitor = HealthMonitor(config, interval=health_interval)
    if group_auth is not None:
        servers = build_group_servers(config, providers=group_auth.providers)
        auth_enabled = any(p is not None for p in group_auth.providers.values())
        root_routes = group_auth.root_routes
    else:
        servers = build_group_servers(config, auth=auth)
        auth_enabled = auth is not None
        root_routes = []
    return Gateway(
        servers=servers,
        monitor=monitor,
        config=config,
        auth_enabled=auth_enabled,
        root_auth_routes=root_routes,
    )


def build_gateway_from_path(config_path: str, *, health_interval: float = 30.0) -> Gateway:
    """Full boot path: load config, wire telemetry, build auth, compose per group.

    Any config or auth error propagates -- the entrypoint refuses to start (fail fast).
    """
    config = load_config(config_path)
    if setup_otel_sdk():
        log.info("OpenTelemetry configured: exporting per-tool-call spans via OTLP")
    group_auth = build_group_auth(list(config.groups))
    if not any(p is not None for p in group_auth.providers.values()):
        log.warning(
            "No auth provider configured (GOOGLE_CLIENT_ID unset): serving OPEN. "
            "Bind behind a tailnet/LAN only -- do not expose publicly."
        )
    return build_from_config(config, group_auth=group_auth, health_interval=health_interval)
