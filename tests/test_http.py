"""HTTP-surface behaviour: /health over HTTP, and 401 challenge when auth is on."""

from __future__ import annotations

import json

import httpx
import pytest

from a2mcp.auth import AuthEnv, build_auth_provider
from a2mcp.config import Backend, Endpoint, GatewayConfig
from a2mcp.server import build_from_config


def _cfg(url: str) -> GatewayConfig:
    return GatewayConfig(endpoints={"home": Endpoint(backends=[Backend(name="ha", url=url)])})


@pytest.mark.asyncio
async def test_health_endpoint_over_http(stub_backend: str) -> None:
    gw = build_from_config(_cfg(stub_backend))
    await gw.monitor.probe_once()
    app = gw.server.http_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["backends"]["ha"]["status"] == "up"


@pytest.mark.asyncio
async def test_unauthenticated_mcp_request_is_challenged(stub_backend: str) -> None:
    # Static bearer verifier is a cheap stand-in for "auth is on" (real DCR/Google is the
    # manual client-compat gate). No token -> challenged, not served.
    auth = build_auth_provider(
        AuthEnv(
            client_id=None,
            client_secret=None,
            base_url=None,
            jwt_signing_key=None,
            encryption_key=None,
            oauth_cache_dir=None,
            static_bearer_tokens=json.dumps({"good": {"client_id": "smoke", "scopes": []}}),
            required_scopes=(),
        )
    )
    gw = build_from_config(_cfg(stub_backend), auth=auth)
    app = gw.server.http_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", follow_redirects=True
    ) as client:
        resp = await client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert resp.status_code == 401
    # RFC 9728: the challenge advertises where to discover the auth server.
    assert "WWW-Authenticate" in resp.headers
