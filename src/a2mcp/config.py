"""Config loader for ``mcp-gateway.yaml`` -- the gateway's only behaviour input.

The whole point of a2mcp: adding or re-scoping a backend is a config edit, never code.
This module parses and validates that config and fails loudly on anything malformed
(spec: "bad config fails fast").

Model (add-access-groups):

- ``backends``: each remote MCP server defined ONCE (name -> url, transport, headers).
- ``groups``: named audiences, each its own MCP URL, each referencing backends by name
  and optionally refining which primitives (tools/resources/prompts) are exposed via
  within-backend globs. ``exclude`` deny-globs win over allow-globs.
- ``members`` on a group is parsed but INERT in v1 (the D5 enforced-membership seam);
  access is URL-as-capability over the shared Google OAuth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class ConfigError(ValueError):
    """Raised when ``mcp-gateway.yaml`` is missing, unparseable, or invalid.

    Carries a human-readable message so the entrypoint can refuse to start with a
    clear error rather than serving a broken surface.
    """


def _namespace_safe(kind: str, name: str) -> str:
    """Reject a name that is not URL-/namespace-safe (alphanumeric plus ``_`` / ``-``)."""
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"{kind} name {name!r} must be alphanumeric (plus _ or -)")
    return name


class Backend(BaseModel):
    """One remote MCP backend, defined once and referenced by groups.

    ``headers`` are only what the gateway needs to REACH the backend over the private
    network (e.g. ha-mcp's secret path). A backend's OWN upstream credential never
    lives here -- it stays in the backend (credential isolation).
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    transport: Literal["sse", "streamable", "http"] = "streamable"
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name_safe(cls, v: str) -> str:
        return _namespace_safe("backend", v)


class BackendRef(BaseModel):
    """A group's reference to one backend, optionally refining its exposed primitives.

    A bare backend name in the YAML (a plain string) is normalized to this with all
    selectors defaulting to ``["*"]`` (expose everything of that kind). Explicit allow
    lists freeze the surface; ``exclude`` deny-globs are applied after allow and win.

    Globs match the UNPREFIXED primitive name within THIS backend only (tools/prompts
    by name; resources by ``uri`` / template ``uriTemplate``). They never cross backends.
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    tools: list[str] = Field(default_factory=lambda: ["*"])
    resources: list[str] = Field(default_factory=lambda: ["*"])
    prompts: list[str] = Field(default_factory=lambda: ["*"])
    exclude: list[str] = Field(default_factory=list)
    # When False, mount this backend WITHOUT the `<backend>_` name prefix (design D6): for a
    # single-backend group where the prefix is noise, or a backend that already self-prefixes
    # its own tool names. Default True. At most one ref per group may set this False (the
    # prefix is the scope routing key; two unprefixed backends make a bare name ambiguous).
    prefix: bool = True

    @field_validator("name")
    @classmethod
    def _name_safe(cls, v: str) -> str:
        return _namespace_safe("backend", v)


class Group(BaseModel):
    """A named audience, published at its own MCP URL, curating a subset of backends.

    ``members`` is parsed but INERT in v1 -- the reserved seam for a future post-auth
    ``GroupMembershipMiddleware`` (design D5). v1 access is URL-as-capability.
    """

    model_config = {"extra": "forbid"}

    backends: list[BackendRef] = Field(min_length=1)
    members: list[str] = Field(default_factory=list)

    @field_validator("backends", mode="before")
    @classmethod
    def _coerce_bare_names(cls, v: object) -> object:
        """Let a group list a backend as a bare string (``[ha]``) or a refined mapping."""
        if isinstance(v, list):
            return [{"name": item} if isinstance(item, str) else item for item in v]
        return v

    @field_validator("backends")
    @classmethod
    def _unique_backend_refs(cls, v: list[BackendRef]) -> list[BackendRef]:
        names = [b.name for b in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate backend refs within a group: {sorted(dupes)}")
        return v

    @field_validator("backends")
    @classmethod
    def _at_most_one_unprefixed(cls, v: list[BackendRef]) -> list[BackendRef]:
        unprefixed = [b.name for b in v if not b.prefix]
        if len(unprefixed) > 1:
            raise ValueError(
                "at most one backend per group may set prefix: false (the prefix attributes "
                f"a tool to its backend for scope enforcement); got {sorted(unprefixed)}"
            )
        return v


class Auth(BaseModel):
    """Auth provider selection. v1 supports only Google (a wrapper, not any-*)."""

    model_config = {"extra": "forbid"}

    provider: Literal["google"] = "google"


class GatewayConfig(BaseModel):
    """The whole ``mcp-gateway.yaml``: auth, backends defined once, and named groups."""

    model_config = {"extra": "forbid"}

    auth: Auth = Field(default_factory=Auth)
    backends: dict[str, Backend] = Field(min_length=1)
    groups: dict[str, Group] = Field(min_length=1)

    @field_validator("backends", mode="before")
    @classmethod
    def _inject_backend_names(cls, v: object) -> object:
        """Let a backend omit its own ``name`` (the map key is the name)."""
        if isinstance(v, dict):
            return {
                key: {**val, "name": val.get("name", key)} if isinstance(val, dict) else val
                for key, val in v.items()
            }
        return v

    @field_validator("groups")
    @classmethod
    def _group_names_safe(cls, v: dict[str, Group]) -> dict[str, Group]:
        for name in v:
            _namespace_safe("group", name)
        return v

    @model_validator(mode="after")
    def _refs_resolve(self) -> GatewayConfig:
        """Fail fast if any group references a backend not defined under ``backends``."""
        defined = set(self.backends)
        missing: list[str] = []
        for group_name, group in self.groups.items():
            for ref in group.backends:
                if ref.name not in defined:
                    missing.append(f"{group_name} -> {ref.name}")
        if missing:
            raise ValueError(
                "group references undefined backend(s): "
                + ", ".join(missing)
                + f". Defined backends: {sorted(defined)}"
            )
        # Every backend key must match its own name (guards a hand-written mismatch).
        for key, backend in self.backends.items():
            if backend.name != key:
                raise ValueError(
                    f"backend key {key!r} disagrees with its name {backend.name!r}"
                )
        return self


def load_config(path: str | Path) -> GatewayConfig:
    """Read and validate ``mcp-gateway.yaml``. Raise ``ConfigError`` on any problem."""
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        raise ConfigError(f"config is not valid YAML ({p}): {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__} ({p})")
    try:
        return GatewayConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(f"invalid config ({p}):\n{e}") from e
