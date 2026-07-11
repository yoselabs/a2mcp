"""C3: auth provider gating (open fallback, loud half-config, static escape hatch)."""

from __future__ import annotations

import json

import pytest

from a2mcp.auth import AuthConfigError, AuthEnv, build_auth_provider, build_group_auth


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
    # EXACTLY ONE protected resource, at the path every group's 401 points to. A per-group
    # resource would mint aud=<base>/ but verify aud=<base>/<group>/mcp -> a 401 reauth loop.
    pr = [p for p in paths if "oauth-protected-resource" in p]
    assert pr == ["/.well-known/oauth-protected-resource/mcp"]
    admin_v = plan.providers["admin"].token_verifier  # type: ignore[union-attr]
    consumer_v = plan.providers["consumer"].token_verifier  # type: ignore[union-attr]
    assert admin_v is consumer_v  # same instance -> one audience by construction


def test_group_auth_open_has_no_root_routes() -> None:
    # No GOOGLE_CLIENT_ID -> serve open; nothing to mount at root.
    plan = build_group_auth(["admin"], _env())
    assert plan.root_routes == []
    assert plan.providers == {"admin": None}
