"""C5 + V2: health reflects up/down and a hung backend never wedges the gateway."""

from __future__ import annotations

import time

import pytest

from a2mcp.config import Backend, Endpoint, GatewayConfig
from a2mcp.health import HealthMonitor


@pytest.mark.asyncio
async def test_up_backend_reports_up(stub_backend: str) -> None:
    ep = Endpoint(backends=[Backend(name="ha", url=stub_backend)])
    cfg = GatewayConfig(endpoints={"home": ep})
    mon = HealthMonitor(cfg, probe_timeout=5.0)
    await mon.probe_once()
    ha = mon.snapshot()["backends"]["ha"]
    assert ha["status"] == "up"
    assert ha["tools"] == 2
    assert mon.overall() == "ok"


@pytest.mark.asyncio
async def test_down_backend_reports_down_and_others_serve(stub_backend: str) -> None:
    # V2: one dead backend, one live. /health shows the dead one, live one keeps serving.
    cfg = GatewayConfig(
        endpoints={
            "home": Endpoint(backends=[Backend(name="ha", url=stub_backend)]),
            "dead": Endpoint(backends=[Backend(name="gone", url="http://127.0.0.1:1/mcp/")]),
        }
    )
    mon = HealthMonitor(cfg, probe_timeout=2.0)
    await mon.probe_once()  # 1st failure -> flaky
    await mon.probe_once()  # 2nd failure -> down
    snap = mon.snapshot()
    assert snap["backends"]["ha"]["status"] == "up"
    assert snap["backends"]["gone"]["status"] == "down"
    assert snap["status"] == "degraded"  # some up, some down


@pytest.mark.asyncio
async def test_hung_backend_does_not_wedge(unused_hung_url: str) -> None:
    # A backend that accepts the TCP connection but never answers must be bounded by
    # probe_timeout, not hang the probe loop forever.
    cfg = GatewayConfig(
        endpoints={"h": Endpoint(backends=[Backend(name="hung", url=unused_hung_url)])}
    )
    mon = HealthMonitor(cfg, probe_timeout=1.0)
    start = time.monotonic()
    await mon.probe_once()
    elapsed = time.monotonic() - start
    assert elapsed < 5.0  # bounded well under any real hang
    assert mon.snapshot()["backends"]["hung"]["status"] in ("flaky", "down")
