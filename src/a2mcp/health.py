"""C5: synthesized backend health.

MCP ``ping`` only proves transport; real health is an ``initialize`` -> ``tools/list``
handshake. A background task probes each backend on an interval with BOUNDED timeouts so
a hung backend can never wedge the gateway. ``/health`` reports per-backend up/flaky/down.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from fastmcp import Client
from starlette.requests import Request
from starlette.responses import JSONResponse

from .compose import backend_transport
from .config import Backend, GatewayConfig

# consecutive failures at/above which a backend is "down" (below it, "flaky").
_DOWN_THRESHOLD = 2


@dataclass
class BackendHealth:
    name: str
    groups: list[str]  # which groups reference this backend (it is probed once)
    status: str = "unknown"  # unknown | up | flaky | down
    tools: int | None = None
    consecutive_failures: int = 0
    last_ok: float | None = None
    last_checked: float | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "groups": self.groups,
            "status": self.status,
            "tools": self.tools,
            "last_ok": self.last_ok,
            "last_checked": self.last_checked,
            "error": self.error,
        }


class HealthMonitor:
    """Tracks and periodically refreshes per-backend reachability."""

    def __init__(
        self,
        config: GatewayConfig,
        *,
        interval: float = 30.0,
        probe_timeout: float = 5.0,
    ) -> None:
        self.interval = interval
        self.probe_timeout = probe_timeout
        # Probe each backend ONCE, even if many groups reference it. Record which groups
        # do, so /health shows the fan-out (a down backend degrades every group using it).
        groups_of: dict[str, list[str]] = {name: [] for name in config.backends}
        for group_name, group in config.groups.items():
            for ref in group.backends:
                groups_of[ref.name].append(group_name)
        self._backends: list[tuple[Backend, BackendHealth]] = [
            (backend, BackendHealth(name=name, groups=groups_of[name]))
            for name, backend in config.backends.items()
        ]
        self._task: asyncio.Task[None] | None = None

    @property
    def statuses(self) -> list[BackendHealth]:
        return [h for _, h in self._backends]

    async def probe_once(self) -> None:
        """Probe every backend once, concurrently, each bounded by ``probe_timeout``."""
        await asyncio.gather(
            *(self._probe_backend(b, h) for b, h in self._backends),
            return_exceptions=True,
        )

    async def _probe_backend(self, backend: Backend, health: BackendHealth) -> None:
        now = time.time()
        health.last_checked = now
        try:
            tools = await asyncio.wait_for(self._handshake(backend), timeout=self.probe_timeout)
        except (Exception, asyncio.CancelledError) as e:  # noqa: BLE001 - health never raises
            health.consecutive_failures += 1
            health.error = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            health.status = "down" if health.consecutive_failures >= _DOWN_THRESHOLD else "flaky"
            return
        health.consecutive_failures = 0
        health.tools = len(tools)
        health.last_ok = now
        health.error = None
        health.status = "up"

    async def _handshake(self, backend: Backend) -> list[object]:
        # `async with Client` performs initialize; list_tools is the real tools/list.
        async with Client(backend_transport(backend)) as client:
            return await client.list_tools()

    def overall(self) -> str:
        statuses = {h.status for h in self.statuses}
        if statuses <= {"up"} and statuses:
            return "ok"
        if "up" in statuses:
            return "degraded"
        return "down"

    def snapshot(self) -> dict[str, object]:
        return {
            "status": self.overall(),
            "backends": {h.name: h.as_dict() for h in self.statuses},
        }

    async def _run(self) -> None:
        while True:
            await self.probe_once()
            await asyncio.sleep(self.interval)

    async def start(self) -> None:
        await self.probe_once()  # seed status before serving
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def route(self):
        """A Starlette handler for ``/health``. 200 if any backend up, else 503."""

        async def health_endpoint(_request: Request) -> JSONResponse:
            snap = self.snapshot()
            code = 200 if snap["status"] in ("ok", "degraded") else 503
            return JSONResponse(snap, status_code=code)

        return health_endpoint
