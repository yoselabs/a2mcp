# a2mcp: slim, uv-based, boring. Behaviour comes from the mounted mcp-gateway.yaml.
FROM python:3.12-slim AS build

# uv from its official image (pinned by digest in CI via the base tag we trust).
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install deps first (cached) from the frozen lockfile, then the project itself.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime ---
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 a2mcp
WORKDIR /app

COPY --from=build --chown=a2mcp:a2mcp /app/.venv /app/.venv
COPY --from=build --chown=a2mcp:a2mcp /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    A2MCP_CONFIG=/config/mcp-gateway.yaml \
    A2MCP_HOST=0.0.0.0 \
    A2MCP_PORT=8000 \
    A2MCP_OAUTH_CACHE_DIR=/data/oauth

USER a2mcp
EXPOSE 8000

# Config is mounted at /config; the persistent OAuth token store lives at /data.
VOLUME ["/data"]

# Entry: read config path from env, serve streamable HTTP.
CMD ["python", "-m", "a2mcp"]
