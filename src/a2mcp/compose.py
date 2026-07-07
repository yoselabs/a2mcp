"""C2: compose config into one FastMCP server.

Endpoint model (locked in design decision 2): ONE root ``FastMCP`` carrying the auth
provider; each endpoint is a sub-server mounted under its name; each backend is a proxy
mounted under its name. Tool names become ``<endpoint>_<backend>_<tool>``. One MCP URL,
one authorization server, one Google redirect URI. Adding a backend is pure config.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.client.transports import (
    ClientTransport,
    SSETransport,
    StreamableHttpTransport,
)
from fastmcp.server import create_proxy
from fastmcp.server.middleware import Middleware
from fastmcp.server.providers.proxy import ProxyClient

from .config import Backend, GatewayConfig


def backend_transport(backend: Backend) -> ClientTransport:
    """Build the client transport that REACHES a backend (url + optional headers).

    ``headers`` carry only what is needed to reach the backend privately (e.g. ha-mcp's
    secret path). A backend's own upstream credential never passes through here.
    """
    headers = backend.headers or None
    if backend.transport == "sse":
        return SSETransport(backend.url, headers=headers)
    # "streamable" and "http" both mean streamable-HTTP downstream.
    return StreamableHttpTransport(backend.url, headers=headers)


def build_backend_proxy(backend: Backend) -> FastMCP:
    """Proxy a single remote MCP backend as a FastMCP server (mirrored, not copied)."""
    client = ProxyClient(backend_transport(backend))
    return create_proxy(client, name=backend.name)


def build_gateway(
    config: GatewayConfig,
    *,
    auth: object | None = None,
    lifespan: Callable[..., Any] | None = None,
    middleware: list[Middleware] | None = None,
) -> FastMCP:
    """Assemble the root gateway server from a validated config.

    Nested namespacing: endpoint sub-server per endpoint (each backend proxy mounted
    under its name), then each endpoint mounted on root under the endpoint name.
    """
    root: FastMCP = FastMCP(name="a2mcp", auth=auth, lifespan=lifespan)
    for m in middleware or []:
        root.add_middleware(m)

    for endpoint_name, endpoint in config.endpoints.items():
        endpoint_server: FastMCP = FastMCP(name=endpoint_name)
        for backend in endpoint.backends:
            endpoint_server.mount(build_backend_proxy(backend), namespace=backend.name)
        root.mount(endpoint_server, namespace=endpoint_name)

    return root
