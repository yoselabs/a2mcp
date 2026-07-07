"""C1: config loader validates and fails loud."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from a2mcp.config import ConfigError, load_config


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "mcp-gateway.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_valid_minimal_config(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        auth:
          provider: google
        endpoints:
          home:
            backends:
              - name: ha
                url: http://ha-mcp:8087/mcp
                transport: sse
        """,
    )
    cfg = load_config(p)
    assert cfg.auth.provider == "google"
    assert list(cfg.endpoints) == ["home"]
    ha = cfg.endpoints["home"].backends[0]
    assert ha.name == "ha"
    assert ha.transport == "sse"


def test_auth_defaults_to_google(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        endpoints:
          home:
            backends:
              - { name: ha, url: http://ha-mcp:8087/mcp }
        """,
    )
    cfg = load_config(p)
    assert cfg.auth.provider == "google"
    assert cfg.endpoints["home"].backends[0].transport == "streamable"


def test_missing_file_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_no_endpoints_fails(tmp_path: Path) -> None:
    p = _write(tmp_path, "auth: {provider: google}\nendpoints: {}\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_unknown_key_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        endpoints:
          home:
            backends:
              - { name: ha, url: http://x/mcp, bogus: 1 }
        """,
    )
    with pytest.raises(ConfigError):
        load_config(p)


def test_unsupported_provider_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        auth: {provider: okta}
        endpoints:
          home:
            backends:
              - { name: ha, url: http://x/mcp }
        """,
    )
    with pytest.raises(ConfigError):
        load_config(p)


def test_duplicate_backend_names_fail(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        endpoints:
          home:
            backends:
              - { name: ha, url: http://x/mcp }
              - { name: ha, url: http://y/mcp }
        """,
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(p)


def test_malformed_yaml_fails(tmp_path: Path) -> None:
    p = tmp_path / "mcp-gateway.yaml"
    p.write_text("endpoints: [unclosed\n")
    with pytest.raises(ConfigError):
        load_config(p)
