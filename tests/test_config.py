"""C1: config loader validates the backends+groups model and fails loud."""

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
        backends:
          ha:
            url: http://ha-mcp:8087/mcp
            transport: sse
        groups:
          admin:
            backends: [ha]
        """,
    )
    cfg = load_config(p)
    assert cfg.auth.provider == "google"
    assert list(cfg.backends) == ["ha"]
    assert cfg.backends["ha"].name == "ha"
    assert cfg.backends["ha"].transport == "sse"
    assert list(cfg.groups) == ["admin"]
    ref = cfg.groups["admin"].backends[0]
    assert ref.name == "ha"
    # Bare name -> expose everything of each kind.
    assert ref.tools == ["*"] and ref.resources == ["*"] and ref.prompts == ["*"]
    assert ref.exclude == []


def test_auth_defaults_to_google(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        backends:
          ha: { url: http://ha-mcp:8087/mcp }
        groups:
          admin: { backends: [ha] }
        """,
    )
    cfg = load_config(p)
    assert cfg.auth.provider == "google"
    assert cfg.backends["ha"].transport == "streamable"


def test_refined_backend_ref_parses(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        backends:
          ha: { url: http://ha-mcp:8087/mcp }
        groups:
          consumer:
            backends:
              - name: ha
                tools: [get_*, light_*]
                exclude: ["*_config"]
        """,
    )
    cfg = load_config(p)
    ref = cfg.groups["consumer"].backends[0]
    assert ref.tools == ["get_*", "light_*"]
    assert ref.exclude == ["*_config"]
    # Unspecified selectors keep the expose-all default.
    assert ref.resources == ["*"] and ref.prompts == ["*"]


def test_members_parsed_but_inert(tmp_path: Path) -> None:
    # v1 does not enforce members; it is only parsed (the D5 seam).
    p = _write(
        tmp_path,
        """
        backends:
          ha: { url: http://ha-mcp:8087/mcp }
        groups:
          admin:
            backends: [ha]
            members: [you@example.com, role:admin]
        """,
    )
    cfg = load_config(p)
    assert cfg.groups["admin"].members == ["you@example.com", "role:admin"]


def test_missing_file_fails_loud(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_no_groups_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "backends: { ha: { url: http://x/mcp } }\ngroups: {}\n",
    )
    with pytest.raises(ConfigError):
        load_config(p)


def test_no_backends_fails(tmp_path: Path) -> None:
    p = _write(tmp_path, "backends: {}\ngroups: { admin: { backends: [ha] } }\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_group_references_undefined_backend_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        backends:
          ha: { url: http://x/mcp }
        groups:
          admin:
            backends: [ghost]
        """,
    )
    with pytest.raises(ConfigError, match="undefined backend"):
        load_config(p)


def test_unknown_key_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        backends:
          ha: { url: http://x/mcp, bogus: 1 }
        groups:
          admin: { backends: [ha] }
        """,
    )
    with pytest.raises(ConfigError):
        load_config(p)


def test_unsupported_provider_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        auth: {provider: okta}
        backends:
          ha: { url: http://x/mcp }
        groups:
          admin: { backends: [ha] }
        """,
    )
    with pytest.raises(ConfigError):
        load_config(p)


def test_unsafe_group_name_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        backends:
          ha: { url: http://x/mcp }
        groups:
          "bad/name": { backends: [ha] }
        """,
    )
    with pytest.raises(ConfigError, match="alphanumeric"):
        load_config(p)


def test_duplicate_backend_ref_in_group_fails(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        backends:
          ha: { url: http://x/mcp }
        groups:
          admin:
            backends: [ha, ha]
        """,
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(p)


def test_malformed_yaml_fails(tmp_path: Path) -> None:
    p = tmp_path / "mcp-gateway.yaml"
    p.write_text("groups: [unclosed\n")
    with pytest.raises(ConfigError):
        load_config(p)
