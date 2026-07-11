"""Scope enforcement is symmetric across tools, resources, and prompts (D3)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastmcp import Client, FastMCP
from fastmcp.utilities.tests import run_server_in_process
from mcp.shared.exceptions import McpError

from a2mcp.config import Backend, BackendRef, GatewayConfig, Group
from a2mcp.server import build_from_config


def _make_rich_stub(name: str) -> FastMCP:
    server: FastMCP = FastMCP(name=name)

    @server.tool
    def get_state() -> str:
        return "s"

    @server.resource("resource://data/public")
    def public() -> str:
        return "p"

    @server.resource("resource://secret/private")
    def secret() -> str:
        return "x"

    @server.resource("resource://item/{id}")
    def item(id: str) -> str:
        return id

    @server.prompt
    def greet() -> str:
        return "hi"

    @server.prompt
    def internal_debug() -> str:
        return "dbg"

    return server


def _run(name: str, host: str, port: int) -> None:
    _make_rich_stub(name).run(transport="http", host=host, port=port)


@pytest.fixture
def rich_backend() -> Iterator[str]:
    with run_server_in_process(_run, "rb") as url:
        yield f"{url}/mcp/"


def _gw(ref: BackendRef, url: str):
    cfg = GatewayConfig(
        backends={"rb": Backend(name="rb", url=url)},
        groups={"g": Group(backends=[ref])},
    )
    return build_from_config(cfg)


@pytest.mark.asyncio
async def test_resource_glob_filters_and_enforces(rich_backend: str) -> None:
    # Allow only the public resource; secret is hidden AND uncallable by exact uri.
    gw = _gw(
        BackendRef(name="rb", resources=["resource://data/*"]),
        rich_backend,
    )
    async with Client(gw.servers["g"]) as client:
        uris = {str(r.uri) for r in await client.list_resources()}
        assert "resource://rb/data/public" in uris
        assert "resource://rb/secret/private" not in uris
        # Direct read of the filtered resource is rejected, not proxied.
        with pytest.raises(McpError):
            await client.read_resource("resource://rb/secret/private")
        # Allowed one still reads.
        assert await client.read_resource("resource://rb/data/public")


@pytest.mark.asyncio
async def test_resource_default_independent_of_tools(rich_backend: str) -> None:
    # Scope tools to a subset; resources stay default (all exposed).
    gw = _gw(BackendRef(name="rb", tools=["nonexistent_*"]), rich_backend)
    async with Client(gw.servers["g"]) as client:
        assert not await client.list_tools()  # tools filtered to nothing
        uris = {str(r.uri) for r in await client.list_resources()}
        assert "resource://rb/data/public" in uris
        assert "resource://rb/secret/private" in uris


@pytest.mark.asyncio
async def test_prompt_glob_filters_and_enforces(rich_backend: str) -> None:
    gw = _gw(BackendRef(name="rb", prompts=["greet"]), rich_backend)
    async with Client(gw.servers["g"]) as client:
        names = {p.name for p in await client.list_prompts()}
        assert "rb_greet" in names
        assert "rb_internal_debug" not in names
        with pytest.raises(McpError):
            await client.get_prompt("rb_internal_debug")
        assert await client.get_prompt("rb_greet")


@pytest.mark.asyncio
async def test_resource_template_filtered(rich_backend: str) -> None:
    gw = _gw(BackendRef(name="rb", resources=["resource://data/*"]), rich_backend)
    async with Client(gw.servers["g"]) as client:
        templates = {t.uriTemplate for t in await client.list_resource_templates()}
        # The item template lives under resource://item/... -> filtered out.
        assert not any("item" in t for t in templates)


@pytest.mark.asyncio
async def test_unprefixed_backend_names_bare_and_still_enforces(rich_backend: str) -> None:
    # prefix: false -> bare tool names, and scoping still applies to the unprefixed backend.
    ref = BackendRef(name="rb", prefix=False, tools=["get_state"], prompts=["greet"])
    gw = _gw(ref, rich_backend)
    async with Client(gw.servers["g"]) as client:
        names = {t.name for t in await client.list_tools()}
        assert "get_state" in names  # bare, no rb_ prefix
        assert not any(n.startswith("rb_") for n in names)
        # Filtered-out prompt is rejected at call time, addressed by its bare name.
        prompts = {p.name for p in await client.list_prompts()}
        assert prompts == {"greet"}
        with pytest.raises(McpError):
            await client.get_prompt("internal_debug")


@pytest.mark.asyncio
async def test_same_backend_prefixed_and_unprefixed_across_groups(rich_backend: str) -> None:
    cfg = GatewayConfig(
        backends={"rb": Backend(name="rb", url=rich_backend)},
        groups={
            "admin": Group(backends=[BackendRef(name="rb")]),  # default prefix
            "consumer": Group(backends=[BackendRef(name="rb", prefix=False)]),
        },
    )
    gw = build_from_config(cfg)
    async with Client(gw.servers["admin"]) as client:
        assert "rb_get_state" in {t.name for t in await client.list_tools()}
    async with Client(gw.servers["consumer"]) as client:
        names = {t.name for t in await client.list_tools()}
        assert "get_state" in names and "rb_get_state" not in names
