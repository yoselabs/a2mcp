"""Config loader for ``mcp-gateway.yaml`` -- the gateway's only behaviour input.

The whole point of a2mcp: adding a backend is a config edit, never code. This module
parses and validates that config and fails loudly on anything malformed (spec:
"bad config fails fast").
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


class ConfigError(ValueError):
    """Raised when ``mcp-gateway.yaml`` is missing, unparseable, or invalid.

    Carries a human-readable message so the entrypoint can refuse to start with a
    clear error rather than serving a broken surface.
    """


class Backend(BaseModel):
    """One remote MCP backend to proxy into an endpoint.

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
    def _namespace_safe(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                f"backend name {v!r} must be alphanumeric (plus _ or -) to namespace tools"
            )
        return v


class Endpoint(BaseModel):
    """A named group of backends. Its name namespaces its backends' tools."""

    model_config = {"extra": "forbid"}

    backends: list[Backend] = Field(min_length=1)

    @field_validator("backends")
    @classmethod
    def _unique_backend_names(cls, v: list[Backend]) -> list[Backend]:
        names = [b.name for b in v]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate backend names within an endpoint: {sorted(dupes)}")
        return v


class Auth(BaseModel):
    """Auth provider selection. v1 supports only Google (a wrapper, not any-*)."""

    model_config = {"extra": "forbid"}

    provider: Literal["google"] = "google"


class GatewayConfig(BaseModel):
    """The whole ``mcp-gateway.yaml``: an auth provider plus named endpoints."""

    model_config = {"extra": "forbid"}

    auth: Auth = Field(default_factory=Auth)
    endpoints: dict[str, Endpoint] = Field(min_length=1)

    @field_validator("endpoints")
    @classmethod
    def _endpoint_names_safe(cls, v: dict[str, Endpoint]) -> dict[str, Endpoint]:
        for name in v:
            if not name.replace("_", "").replace("-", "").isalnum():
                raise ValueError(f"endpoint name {name!r} must be alphanumeric (plus _ or -)")
        return v


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
