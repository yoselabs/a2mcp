"""C5 + V2: health reflects up/down, reports groups, hung backend never wedges."""

from __future__ import annotations

import time

import pytest

from a2mcp.config import Backend, BackendRef, GatewayConfig, Group
from a2mcp.health import HealthMonitor


def _cfg(backends: dict[str, Backend], groups: dict[str, Group]) -> GatewayConfig:
    return GatewayConfig(backends=backends, groups=groups)


@pytest.mark.asyncio
async def test_up_backend_reports_up_and_groups(stub_backend: str) -> None:
    # One backend referenced by two groups is probed ONCE and lists both groups.
    cfg = _cfg(
        {"ha": Backend(name="ha", url=stub_backend)},
        {
            "admin": Group(backends=[BackendRef(name="ha")]),
            "consumer": Group(backends=[BackendRef(name="ha", tools=["echo"])]),
        },
    )
    mon = HealthMonitor(cfg, probe_timeout=5.0)
    await mon.probe_once()
    backends = mon.snapshot()["backends"]
    assert list(backends) == ["ha"]  # probed once, not per group
    ha = backends["ha"]
    assert ha["status"] == "up"
    assert ha["tools"] == 2
    assert sorted(ha["groups"]) == ["admin", "consumer"]
    assert mon.overall() == "ok"


@pytest.mark.asyncio
async def test_down_backend_reports_down_and_others_serve(stub_backend: str) -> None:
    cfg = _cfg(
        {
            "ha": Backend(name="ha", url=stub_backend),
            "gone": Backend(name="gone", url="http://127.0.0.1:1/mcp/"),
        },
        {
            "home": Group(backends=[BackendRef(name="ha")]),
            "dead": Group(backends=[BackendRef(name="gone")]),
        },
    )
    mon = HealthMonitor(cfg, probe_timeout=2.0)
    await mon.probe_once()  # 1st failure -> flaky
    await mon.probe_once()  # 2nd failure -> down
    snap = mon.snapshot()
    assert snap["backends"]["ha"]["status"] == "up"
    assert snap["backends"]["gone"]["status"] == "down"
    assert snap["status"] == "degraded"


@pytest.mark.asyncio
async def test_hung_backend_does_not_wedge(unused_hung_url: str) -> None:
    cfg = _cfg(
        {"hung": Backend(name="hung", url=unused_hung_url)},
        {"h": Group(backends=[BackendRef(name="hung")])},
    )
    mon = HealthMonitor(cfg, probe_timeout=1.0)
    start = time.monotonic()
    await mon.probe_once()
    elapsed = time.monotonic() - start
    assert elapsed < 5.0
    assert mon.snapshot()["backends"]["hung"]["status"] in ("flaky", "down")
