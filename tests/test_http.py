"""HTTP-surface behaviour: /health at root, per-group URLs, 401 challenge with auth."""

from __future__ import annotations

import json

import httpx
import pytest

from a2mcp.auth import AuthEnv, build_auth_provider, build_group_auth
from a2mcp.config import Backend, BackendRef, GatewayConfig, Group
from a2mcp.server import build_from_config


def _cfg(url: str) -> GatewayConfig:
    return GatewayConfig(
        backends={"ha": Backend(name="ha", url=url)},
        groups={
            "admin": Group(backends=[BackendRef(name="ha")]),
            "consumer": Group(backends=[BackendRef(name="ha", tools=["echo"])]),
        },
    )


@pytest.mark.asyncio
async def test_health_endpoint_over_http(stub_backend: str) -> None:
    gw = build_from_config(_cfg(stub_backend))
    await gw.monitor.probe_once()
    app = gw.http_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["backends"]["ha"]["status"] == "up"
    assert sorted(body["backends"]["ha"]["groups"]) == ["admin", "consumer"]


@pytest.mark.asyncio
async def test_each_group_url_challenges_unauthenticated(stub_backend: str) -> None:
    # Static bearer verifier is a cheap stand-in for "auth is on". No token -> 401 at
    # BOTH group URLs, each advertising where to discover the auth server.
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
    app = gw.http_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", follow_redirects=True
    ) as client:
        for group in ("admin", "consumer"):
            resp = await client.post(
                f"/{group}/mcp/",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert resp.status_code == 401, group
            assert "WWW-Authenticate" in resp.headers, group


@pytest.mark.asyncio
async def test_group_discovery_converges_on_one_resource_and_as(stub_backend: str) -> None:
    # Regression for the audience-mismatch reauth loop: every group's 401 must resolve to
    # ONE protected-resource metadata doc naming a SINGLE resource + the one shared AS. A
    # per-group resource would mint aud=<base>/ but verify aud=<base>/<group>/mcp and loop.
    env = AuthEnv(
        client_id="cid",
        client_secret="sec",
        base_url="https://mcp.example.net",
        jwt_signing_key="k" * 64,
        encryption_key=None,
        oauth_cache_dir=None,
        static_bearer_tokens=None,
        required_scopes=("openid", "email"),
    )
    plan = build_group_auth(["admin", "consumer"], env)
    gw = build_from_config(_cfg(stub_backend), group_auth=plan)
    app = gw.http_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://mcp.example.net", follow_redirects=True
    ) as client:
        resources: set[str] = set()
        auth_servers: set[str] = set()
        for group in ("admin", "consumer"):
            resp = await client.post(
                f"/{group}/mcp/",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert resp.status_code == 401, group
            wa = resp.headers["WWW-Authenticate"]
            meta_url = wa.split('resource_metadata="')[1].split('"')[0]
            meta = await client.get(meta_url)
            assert meta.status_code == 200, (group, meta_url)
            body = meta.json()
            resources.add(body["resource"])
            auth_servers.update(body["authorization_servers"])
        # One shared resource + one shared AS across all groups.
        assert resources == {"https://mcp.example.net/mcp"}
        assert auth_servers == {"https://mcp.example.net/"}
        # The one AS metadata is served at the origin root.
        az = await client.get("/.well-known/oauth-authorization-server")
        assert az.status_code == 200
