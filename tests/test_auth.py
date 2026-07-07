"""C3: auth provider gating (open fallback, loud half-config, static escape hatch)."""

from __future__ import annotations

import json

import pytest

from a2mcp.auth import AuthConfigError, AuthEnv, build_auth_provider


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
