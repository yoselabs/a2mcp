"""C3: the Google-federated DCR OAuth shim.

a2kit deliberately ships no Google-DCR helper (ADR 0010/0011: auth-agnostic on the MCP
surface); the blessed recipe is ``a2kit/docs/patterns/mcp-auth.md``, first realized in
a2web's ``build_google_provider``. a2mcp mirrors that here (shelf: ``google-dcr-shim``,
2nd sighting -- do not extract until a non-divergent 3rd consumer).

DCR is presented downward to clients; ONE fixed Google client is upstream; GCP
test-users are the identity gate (enforced at Google's consent screen, no allowlist in
our config). ``base_url`` MUST be the public https URL or discovery points clients wrong.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


class AuthConfigError(ValueError):
    """Raised on a half-configured or invalid auth setup -- never serve open silently."""


@dataclass(frozen=True)
class AuthEnv:
    """Auth-relevant environment, resolved once at boot."""

    client_id: str | None
    client_secret: str | None
    base_url: str | None
    jwt_signing_key: str | None
    encryption_key: str | None
    oauth_cache_dir: str | None
    static_bearer_tokens: str | None
    required_scopes: tuple[str, ...]

    @classmethod
    def from_environ(cls) -> AuthEnv:
        scopes = os.environ.get("A2MCP_GOOGLE_SCOPES", "openid,email")
        return cls(
            client_id=os.environ.get("GOOGLE_CLIENT_ID") or None,
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET") or None,
            base_url=os.environ.get("A2MCP_BASE_URL") or None,
            jwt_signing_key=os.environ.get("A2MCP_JWT_SIGNING_KEY") or None,
            encryption_key=os.environ.get("A2MCP_OAUTH_ENCRYPTION_KEY") or None,
            oauth_cache_dir=os.environ.get("A2MCP_OAUTH_CACHE_DIR") or None,
            static_bearer_tokens=os.environ.get("A2MCP_STATIC_BEARER_TOKENS") or None,
            required_scopes=tuple(s.strip() for s in scopes.split(",") if s.strip()),
        )


def build_auth_provider(env: AuthEnv | None = None) -> object | None:
    """Build the FastMCP auth provider from env, or None to serve open.

    Precedence and gating (mirrors the blessed recipe):

    - ``A2MCP_STATIC_BEARER_TOKENS`` set -> a ``StaticTokenVerifier`` (escape hatch for
      DCR-incompatible clients / smoke tests). Value is a JSON object
      ``{"<token>": {"client_id": "...", "scopes": [...]}}``.
    - else ``GOOGLE_CLIENT_ID`` unset -> None (endpoint serves OPEN; bind behind
      tailnet/LAN only, and say so loudly at boot).
    - else the full Google recipe. ``GOOGLE_CLIENT_SECRET`` + ``A2MCP_BASE_URL`` +
      ``A2MCP_JWT_SIGNING_KEY`` are then REQUIRED (a missing signing key or token store
      forces a reauth on every restart), else a loud ``AuthConfigError``.
    """
    env = env or AuthEnv.from_environ()

    if env.static_bearer_tokens:
        return _build_static_verifier(env.static_bearer_tokens, env.required_scopes)

    if not env.client_id:
        return None

    missing = [
        name
        for name, value in (
            ("GOOGLE_CLIENT_SECRET", env.client_secret),
            ("A2MCP_BASE_URL", env.base_url),
            ("A2MCP_JWT_SIGNING_KEY", env.jwt_signing_key),
        )
        if not value
    ]
    if missing:
        raise AuthConfigError(
            "Google OAuth is partially configured: GOOGLE_CLIENT_ID is set but "
            f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} missing. "
            "Set all of GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / A2MCP_BASE_URL / "
            "A2MCP_JWT_SIGNING_KEY, or unset GOOGLE_CLIENT_ID to serve open (tailnet only)."
        )

    from fastmcp.server.auth.providers.google import GoogleProvider

    return GoogleProvider(
        client_id=env.client_id,
        client_secret=env.client_secret,
        base_url=env.base_url,
        required_scopes=list(env.required_scopes) or None,
        jwt_signing_key=env.jwt_signing_key,
        client_storage=_build_token_store(env),
    )


def _build_token_store(env: AuthEnv) -> object:
    """Persistent (and, when a key is given, encrypted) OAuth token store.

    The in-memory default loses tokens on restart -> daily-reauth trap. FileTreeStore
    survives restarts; FernetEncryptionWrapper encrypts at rest.
    """
    from key_value.aio.stores.filetree import FileTreeStore

    store_dir = env.oauth_cache_dir or _default_cache_dir()
    store: object = FileTreeStore(data_directory=store_dir)
    if env.encryption_key:
        from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

        # Salt only needs to be STABLE across restarts (so the derived key reproduces).
        store = FernetEncryptionWrapper(
            key_value=store,
            source_material=env.encryption_key,
            salt="a2mcp-oauth-token-store",
        )
    return store


def _default_cache_dir() -> str:
    from pathlib import Path

    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "a2mcp" / "oauth")


def _build_static_verifier(raw: str, required_scopes: tuple[str, ...]) -> object:
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    try:
        tokens = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AuthConfigError(f"A2MCP_STATIC_BEARER_TOKENS is not valid JSON: {e}") from e
    if not isinstance(tokens, dict) or not tokens:
        raise AuthConfigError(
            "A2MCP_STATIC_BEARER_TOKENS must be a non-empty JSON object mapping "
            'token -> claims, e.g. {"secret": {"client_id": "smoke", "scopes": ["email"]}}'
        )
    return StaticTokenVerifier(tokens=tokens, required_scopes=list(required_scopes) or None)
