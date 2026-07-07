"""Container entrypoint: ``python -m a2mcp`` (or the ``a2mcp`` script).

Reads the config path from ``A2MCP_CONFIG`` (or the first CLI arg), builds the gateway,
and serves streamable HTTP. Host/port from ``A2MCP_HOST`` / ``A2MCP_PORT``.
"""

from __future__ import annotations

import logging
import os
import sys

from .server import build_gateway_from_path

_DEFAULT_CONFIG = "mcp-gateway.yaml"


def _config_path(argv: list[str]) -> str:
    if len(argv) > 1 and argv[1]:
        return argv[1]
    return os.environ.get("A2MCP_CONFIG", _DEFAULT_CONFIG)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("A2MCP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config_path = _config_path(sys.argv)
    gateway = build_gateway_from_path(config_path)

    host = os.environ.get("A2MCP_HOST", "0.0.0.0")  # noqa: S104 - container binds all by design
    port = int(os.environ.get("A2MCP_PORT", "8000"))
    logging.getLogger("a2mcp").info(
        "serving %d endpoint(s) on http://%s:%d (auth=%s)",
        len(gateway.config.endpoints),
        host,
        port,
        "on" if gateway.auth_enabled else "OPEN",
    )
    gateway.server.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
