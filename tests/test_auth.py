"""C3: auth provider gating (open fallback, loud half-config, static escape hatch)."""

from __future__ import annotations

import json

import pytest

from a2mcp.auth import AuthConfigError, AuthEnv, build_auth_provider, build_group_auth


def _authorize_params(*, resource: str, redirect_uri: str) -> object:
    from mcp.server.auth.provider import AuthorizationParams

    return AuthorizationParams(
        state="xyz",
        scopes=["openid", "email"],
        code_challenge="c" * 43,
        redirect_uri=redirect_uri,  # type: ignore[arg-type]
        redirect_uri_provided_explicitly=True,
        resource=resource,
    )


def _authorize_client(*, redirect_uri: str) -> object:
    from mcp.shared.auth import OAuthClientInformationFull

    return OAuthClientInformationFull(
        redirect_uris=[redirect_uri],  # type: ignore[list-item]
        client_id="test-client",
    )


def _env(**over: object) -> AuthEnv:
    base = dict(
        client_id=None,
        client_secret=None,
        base_url=None,
        jwt_signing_key=None,
        encryption_key=None,
        oauth_cache_dir=None,
        static_bearer_tokens=None,
        required_scopes=("openid", "email"),
    )
    base.update(over)
    return AuthEnv(**base)  # type: ignore[arg-type]


def test_no_client_id_serves_open() -> None:
    assert build_auth_provider(_env()) is None


def test_half_configured_fails_loud() -> None:
    with pytest.raises(AuthConfigError, match="partially configured"):
        build_auth_provider(_env(client_id="cid"))  # missing secret/base_url/signing key


def test_full_google_builds_provider(tmp_path) -> None:
    provider = build_auth_provider(
        _env(
            client_id="cid",
            client_secret="secret",
            base_url="https://mcp.example.com",
            jwt_signing_key="0" * 64,
            oauth_cache_dir=str(tmp_path),
        )
    )
    from fastmcp.server.auth.providers.google import GoogleProvider

    assert isinstance(provider, GoogleProvider)


def test_encrypted_store_when_key_present(tmp_path) -> None:
    provider = build_auth_provider(
        _env(
            client_id="cid",
            client_secret="secret",
            base_url="https://mcp.example.com",
            jwt_signing_key="0" * 64,
            encryption_key="pw",
            oauth_cache_dir=str(tmp_path),
        )
    )
    assert provider is not None


def test_static_bearer_escape_hatch() -> None:
    provider = build_auth_provider(
        _env(static_bearer_tokens=json.dumps({"tok": {"client_id": "smoke", "scopes": []}}))
    )
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    assert isinstance(provider, StaticTokenVerifier)


def test_static_bearer_bad_json_fails() -> None:
    with pytest.raises(AuthConfigError, match="not valid JSON"):
        build_auth_provider(_env(static_bearer_tokens="{oops"))


def test_group_auth_shares_one_as_and_one_verifier(tmp_path) -> None:
    # Design A: ONE Google AS + one protected resource at root; every group delegates
    # token verification to that single instance (consistent audience, no reauth loop).
    env = _env(
        client_id="cid",
        client_secret="secret",
        base_url="https://mcp.example.net",
        jwt_signing_key="0" * 64,
        oauth_cache_dir=str(tmp_path),
    )
    plan = build_group_auth(["admin", "consumer"], env)
    assert set(plan.providers) == {"admin", "consumer"}
    paths = {getattr(r, "path", "") for r in plan.root_routes}
    # The one shared AS + one root protected resource live at root.
    assert "/.well-known/oauth-authorization-server" in paths
    assert "/authorize" in paths and "/token" in paths and "/auth/callback" in paths
    # EXACTLY ONE protected resource, at the bare origin every group's 401 points to (no
    # /mcp suffix: strict RFC 9728/8707 clients require the advertised resource to equal
    # the dialed URL or its origin, and a fixed <base>/mcp suffix matches neither for a
    # group URL). A per-group resource would mint aud=<base> but verify aud=<base>/<group>
    # -> a 401 reauth loop.
    pr = [p for p in paths if "oauth-protected-resource" in p]
    assert pr == ["/.well-known/oauth-protected-resource"]
    admin_v = plan.providers["admin"].token_verifier  # type: ignore[union-attr]
    consumer_v = plan.providers["consumer"].token_verifier  # type: ignore[union-attr]
    assert admin_v is consumer_v  # same instance -> one audience by construction


def test_group_auth_advertises_bare_origin_per_group(tmp_path) -> None:
    # Regression for the reported bug: strict clients (Claude Code SDK) require the
    # advertised resource to equal the dialed group URL's origin, not <base>/mcp.
    env = _env(
        client_id="cid",
        client_secret="secret",
        base_url="https://mcp.example.net",
        jwt_signing_key="0" * 64,
        oauth_cache_dir=str(tmp_path),
    )
    plan = build_group_auth(["a2web", "all"], env)
    for group in ("a2web", "all"):
        provider = plan.providers[group]
        routes = provider.get_routes(mcp_path="/mcp")  # type: ignore[union-attr]
        resource_url = str(provider._get_resource_url("/mcp"))  # type: ignore[union-attr]
        assert resource_url.rstrip("/") == "https://mcp.example.net"
        well_known_paths = {getattr(r, "path", "") for r in routes}
        assert "/.well-known/oauth-protected-resource" in well_known_paths


def test_group_auth_mint_and_verify_audience_stay_identical(tmp_path) -> None:
    # Mint audience == verify audience must survive the origin-only advertisement change.
    # Every group's provider.verify_token delegates to the SAME root_provider instance
    # (constructed once, before any group's own get_routes runs), so whatever each group
    # advertises for discovery cannot desync mint vs. verify -- there is only one audience,
    # owned by one object, for the whole plan.
    env = _env(
        client_id="cid",
        client_secret="secret",
        base_url="https://mcp.example.net",
        jwt_signing_key="0" * 64,
        oauth_cache_dir=str(tmp_path),
    )
    plan = build_group_auth(["a2web", "all"], env)
    root_provider = plan.providers["a2web"].token_verifier  # type: ignore[union-attr]
    assert str(root_provider.jwt_issuer.audience).rstrip("/") == "https://mcp.example.net"
    for group in ("a2web", "all"):
        provider = plan.providers[group]
        # Each group's own (advertisement-only) get_routes call must not create or
        # mutate a second JWTIssuer / audience on the shared root_provider.
        provider.get_routes(mcp_path="/mcp")  # type: ignore[union-attr]
        assert provider.token_verifier is root_provider  # type: ignore[union-attr]
        assert str(root_provider.jwt_issuer.audience).rstrip("/") == "https://mcp.example.net"


@pytest.mark.asyncio
async def test_authorize_accepts_bare_origin_resource(tmp_path) -> None:
    # Regression-guard: a strict client that discovers resource=<base> (the bare origin,
    # what this change now advertises) and echoes it back at /authorize must NOT get
    # invalid_target. Before this change, only resource=<base>/mcp was accepted, which no
    # strict client discovers anymore.
    env = _env(
        client_id="cid",
        client_secret="secret",
        base_url="https://mcp.example.net",
        jwt_signing_key="0" * 64,
        oauth_cache_dir=str(tmp_path),
    )
    plan = build_group_auth(["a2web"], env)
    root_provider = plan.providers["a2web"].token_verifier  # type: ignore[union-attr]
    root_provider.get_routes(mcp_path=None)  # ensure _resource_url is initialized

    redirect_uri = "https://client.example.com/callback"
    client = _authorize_client(redirect_uri=redirect_uri)
    params = _authorize_params(resource="https://mcp.example.net", redirect_uri=redirect_uri)

    result = await root_provider.authorize(client, params)
    assert isinstance(result, str) and result  # no AuthorizeError raised


def test_group_auth_open_has_no_root_routes() -> None:
    # No GOOGLE_CLIENT_ID -> serve open; nothing to mount at root.
    plan = build_group_auth(["admin"], _env())
    assert plan.root_routes == []
    assert plan.providers == {"admin": None}
