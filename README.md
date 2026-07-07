# a2mcp

A generic, **config-driven MCP gateway** on [FastMCP](https://gofastmcp.com) (Python).
It publishes self-hosted MCP servers to off-tailnet AI clients (claude.ai custom
connectors, mobile AI apps, MCP CLIs) behind **Google OAuth**, via a thin
`OAuthProxy`/`GoogleProvider` shim: Dynamic Client Registration (DCR) downward to
clients, one fixed Google client upstream, GCP test-users as the identity gate.

Its behaviour is 100% driven by a checked-in config file. **Adding a backend is a
config edit, never a code change.**

```yaml
# mcp-gateway.yaml
auth:
  provider: google        # client_id/secret from env; allowlist = GCP test-users
endpoints:
  home:
    backends:
      - { name: ha, url: http://ha-mcp:8087/mcp, transport: sse }
```

## What it does

- **Composes** one or more remote MCP backends into per-domain endpoints (FastMCP
  `as_proxy`/`mount`).
- **Fronts** them with a Google-federated OAuth Authorization Server (DCR down, Google
  up) so web + mobile AI clients can connect where oauth2-proxy and Traefik cannot.
- **Emits** per-tool-call OpenTelemetry spans.
- **Health-checks** backends (`initialize` -> `tools/list`), exposed at `/health`.
- **Isolates** backend credentials: a backend's own token never enters this gateway;
  it holds only its Google secret plus what it needs to reach each backend privately.

## Where it fits

This is the write-once engine behind homelab's `platform/mcp-gateway` stack. The
**origin spec** is `iorlas/homelab` OpenSpec change `add-mcp-gateway` (ADR 0051,
exposure Lane 9). Homelab pulls this as a digest-pinned GHCR image and supplies the
declarative config; there is no homelab-specific code here.

## Stack

Python, FastMCP, `uv`. See `CLAUDE.md` for conventions and the micro-software
discipline, and `docs/design/primitive-shelf.md` before hand-rolling any helper.

## Run it

```bash
uv sync
cp mcp-gateway.example.yaml mcp-gateway.yaml   # point backends at your MCP servers
uv run a2mcp                                    # serves http://0.0.0.0:8000 (+ /health)
# or: docker build -t a2mcp . && docker run -p 8000:8000 \
#       -v $PWD/mcp-gateway.yaml:/config/mcp-gateway.yaml:ro a2mcp
```

With `GOOGLE_CLIENT_ID` unset the gateway serves **open** (bind behind a tailnet/LAN
only). Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `A2MCP_BASE_URL` /
`A2MCP_JWT_SIGNING_KEY` to turn on the Google-federated DCR OAuth. See
`mcp-gateway.example.yaml` for the full env list.

## Status

v1 engine built (config, composition, Google-DCR auth, native OTel, health; Docker + CI).
Tracked in OpenSpec change `add-gateway-v1` (run `openspec status`). Remaining before
homelab flips "done": the manual **claude.ai custom-connector DCR smoke** (client-compat
gate) and publishing the first image digest for homelab to pin.
