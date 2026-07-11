"""C2 + scoping: per-group composition, glob filtering, call-time enforcement."""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from a2mcp.config import Backend, BackendRef, GatewayConfig, Group
from a2mcp.server import build_from_config


def _cfg(backends: dict[str, Backend], groups: dict[str, Group]) -> GatewayConfig:
    return GatewayConfig(backends=backends, groups=groups)


@pytest.mark.asyncio
async def test_lists_and_calls_backend_tool(stub_backend: str) -> None:
    cfg = _cfg(
        {"ha": Backend(name="ha", url=stub_backend)},
        {"admin": Group(backends=[BackendRef(name="ha")])},
    )
    gw = build_from_config(cfg)

    async with Client(gw.servers["admin"]) as client:
        tools = {t.name for t in await client.list_tools()}
        # No group prefix: <backend>_<tool>.
        assert "ha_echo" in tools
        assert "ha_ping" in tools

        result = await client.call_tool("ha_echo", {"text": "hi"})
        assert result.data == "alpha:hi"


@pytest.mark.asyncio
async def test_two_groups_share_backend_config_only(stub_backend: str) -> None:
    # One backend defined once, referenced by two groups. No code change.
    cfg = _cfg(
        {"ha": Backend(name="ha", url=stub_backend)},
        {
            "admin": Group(backends=[BackendRef(name="ha")]),
            "consumer": Group(backends=[BackendRef(name="ha", tools=["echo"])]),
        },
    )
    gw = build_from_config(cfg)

    async with Client(gw.servers["admin"]) as client:
        assert {"ha_echo", "ha_ping"} <= {t.name for t in await client.list_tools()}

    async with Client(gw.servers["consumer"]) as client:
        names = {t.name for t in await client.list_tools()}
        assert "ha_echo" in names
        assert "ha_ping" not in names  # filtered by the allow-glob


@pytest.mark.asyncio
async def test_unreferenced_backend_is_invisible(
    stub_backend: str, stub_backend2: str
) -> None:
    cfg = _cfg(
        {
            "ha": Backend(name="ha", url=stub_backend),
            "git": Backend(name="git", url=stub_backend2),
        },
        {"consumer": Group(backends=[BackendRef(name="ha")])},
    )
    gw = build_from_config(cfg)
    async with Client(gw.servers["consumer"]) as client:
        names = {t.name for t in await client.list_tools()}
        assert any(n.startswith("ha_") for n in names)
        assert not any(n.startswith("git_") for n in names)


@pytest.mark.asyncio
async def test_exclude_wins_over_allow(stub_backend: str) -> None:
    # echo allowed by "*", denied by exclude -> not listed, not callable.
    cfg = _cfg(
        {"ha": Backend(name="ha", url=stub_backend)},
        {"g": Group(backends=[BackendRef(name="ha", tools=["*"], exclude=["echo"])])},
    )
    gw = build_from_config(cfg)
    async with Client(gw.servers["g"]) as client:
        names = {t.name for t in await client.list_tools()}
        assert "ha_ping" in names
        assert "ha_echo" not in names


@pytest.mark.asyncio
async def test_filtered_tool_rejected_at_call_time(stub_backend: str) -> None:
    # Enforcement: even addressed by exact name, a filtered tool is rejected.
    cfg = _cfg(
        {"ha": Backend(name="ha", url=stub_backend)},
        {"g": Group(backends=[BackendRef(name="ha", tools=["ping"])])},
    )
    gw = build_from_config(cfg)
    async with Client(gw.servers["g"]) as client:
        with pytest.raises(ToolError):
            await client.call_tool("ha_echo", {"text": "x"})
        # The allowed one still works.
        assert (await client.call_tool("ha_ping")).data == "pong"


@pytest.mark.asyncio
async def test_glob_does_not_cross_backends(
    stub_backend: str, stub_backend2: str
) -> None:
    # ha scoped to echo only; git left default. git's echo must still be exposed.
    cfg = _cfg(
        {
            "ha": Backend(name="ha", url=stub_backend),
            "git": Backend(name="git", url=stub_backend2),
        },
        {
            "g": Group(
                backends=[
                    BackendRef(name="ha", tools=["echo"]),
                    BackendRef(name="git"),
                ]
            )
        },
    )
    gw = build_from_config(cfg)
    async with Client(gw.servers["g"]) as client:
        names = {t.name for t in await client.list_tools()}
        assert "ha_echo" in names and "ha_ping" not in names  # ha filtered
        assert "git_echo" in names and "git_ping" in names  # git unaffected
