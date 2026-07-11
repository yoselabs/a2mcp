"""C2: compose config into ONE FastMCP server PER GROUP (design D2).

Each group is its own server: every backend the group references is proxied and mounted
under the backend name, so tools become ``<backend>_<tool>`` (no group prefix -- the group
is implied by the URL the server is mounted at). Each group server carries the shared auth
provider, a ``GroupScopeMiddleware`` bound to that group's globs, and the per-tool-call
telemetry middleware. ``server.py`` mounts each group server at ``/<group>``.

Adding a backend is pure config: define it under ``backends``, list it in a group.
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

from .config import Backend, GatewayConfig, Group
from .scope import GroupScopeMiddleware
from .telemetry import ToolCallSpanMiddleware


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


def build_group_server(
    group_name: str,
    group: Group,
    backends: dict[str, Backend],
    *,
    auth: object | None = None,
    lifespan: Callable[..., Any] | None = None,
    extra_middleware: list[Middleware] | None = None,
) -> FastMCP:
    """Assemble one group's FastMCP server from the backends it references.

    Backend inclusion is the primary gate; the ``GroupScopeMiddleware`` refines within
    each backend and enforces the same globs at call time.
    """
    server: FastMCP = FastMCP(name=group_name, auth=auth, lifespan=lifespan)
    # Scope middleware first so it filters/guards before telemetry and the proxies.
    server.add_middleware(GroupScopeMiddleware(group))
    prefixed = tuple(r.name for r in group.backends if r.prefix)
    unprefixed = next((r.name for r in group.backends if not r.prefix), None)
    server.add_middleware(
        ToolCallSpanMiddleware(
            group=group_name, prefixed_backends=prefixed, unprefixed_backend=unprefixed
        )
    )
    for m in extra_middleware or []:
        server.add_middleware(m)
    for ref in group.backends:
        proxy = build_backend_proxy(backends[ref.name])
        # prefix: false (D6) -> mount without a namespace, so tools keep their bare names.
        # The loader guarantees at most one unprefixed backend per group, so the scope
        # middleware can still attribute a bare name to it.
        if ref.prefix:
            server.mount(proxy, namespace=ref.name)
        else:
            server.mount(proxy)
    return server


def build_group_servers(
    config: GatewayConfig,
    *,
    auth: object | None = None,
    providers: dict[str, object | None] | None = None,
    lifespan: Callable[..., Any] | None = None,
    extra_middleware: list[Middleware] | None = None,
) -> dict[str, FastMCP]:
    """Build one FastMCP server per group, keyed by group name.

    ``providers`` (group name -> provider) gives each group its own auth provider so it
    can advertise per-group protected-resource metadata; ``auth`` is the fallback applied
    to every group when no per-group provider is given (tests / single-resource setups).
    """
    return {
        name: build_group_server(
            name,
            group,
            config.backends,
            auth=(providers.get(name) if providers is not None else auth),
            lifespan=lifespan,
            extra_middleware=extra_middleware,
        )
        for name, group in config.groups.items()
    }
