"""Shared fixtures: a real stub MCP backend served over HTTP in a subprocess."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastmcp import FastMCP
from fastmcp.utilities.tests import run_server_in_process


def _make_stub(name: str) -> FastMCP:
    server: FastMCP = FastMCP(name=name)

    @server.tool
    def echo(text: str) -> str:
        """Return the text back."""
        return f"{name}:{text}"

    @server.tool
    def ping() -> str:
        """Liveness word."""
        return "pong"

    return server


def _run_stub(name: str, host: str, port: int) -> None:
    # run_server_in_process passes host/port as kwargs (provide_host_and_port=True).
    _make_stub(name).run(transport="http", host=host, port=port)


@pytest.fixture
def stub_backend() -> Iterator[str]:
    """A live stub MCP backend; yields its ``/mcp/`` URL."""
    with run_server_in_process(_run_stub, "alpha") as url:
        yield f"{url}/mcp/"


@pytest.fixture
def stub_backend2() -> Iterator[str]:
    with run_server_in_process(_run_stub, "beta") as url:
        yield f"{url}/mcp/"


@pytest.fixture
def unused_hung_url() -> Iterator[str]:
    """A listening socket that accepts connections but never answers (simulates hang)."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)  # backlog: connects complete the handshake, we never accept/respond
    port = sock.getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp/"
    finally:
        sock.close()
