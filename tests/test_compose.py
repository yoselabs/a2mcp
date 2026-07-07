"""C2 + V1 + V4: composition proxies a backend and namespaces its tools."""

from __future__ import annotations

import pytest
from fastmcp import Client

from a2mcp.config import Backend, Endpoint, GatewayConfig
from a2mcp.server import build_from_config


def _cfg(**endpoints: Endpoint) -> GatewayConfig:
    return GatewayConfig(endpoints=endpoints)


@pytest.mark.asyncio
async def test_lists_and_calls_backend_tool(stub_backend: str) -> None:
    cfg = _cfg(home=Endpoint(backends=[Backend(name="ha", url=stub_backend)]))
    gw = build_from_config(cfg)

    async with Client(gw.server) as client:
        tools = {t.name for t in await client.list_tools()}
        # V1: nested namespace <endpoint>_<backend>_<tool>
        assert "home_ha_echo" in tools
        assert "home_ha_ping" in tools

        result = await client.call_tool("home_ha_echo", {"text": "hi"})
        assert result.data == "alpha:hi"


@pytest.mark.asyncio
async def test_config_only_second_backend(stub_backend: str, stub_backend2: str) -> None:
    # V4: two endpoints, purely from config, both serve. No code change.
    cfg = _cfg(
        home=Endpoint(backends=[Backend(name="ha", url=stub_backend)]),
        code=Endpoint(backends=[Backend(name="git", url=stub_backend2)]),
    )
    gw = build_from_config(cfg)

    async with Client(gw.server) as client:
        tools = {t.name for t in await client.list_tools()}
        assert "home_ha_echo" in tools
        assert "code_git_echo" in tools

        assert (await client.call_tool("home_ha_echo", {"text": "x"})).data == "alpha:x"
        assert (await client.call_tool("code_git_echo", {"text": "y"})).data == "beta:y"
