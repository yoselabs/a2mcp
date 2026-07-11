# a2mcp

A generic, **config-driven MCP gateway** on [FastMCP](https://gofastmcp.com) (Python).
It publishes self-hosted MCP servers to off-tailnet AI clients (claude.ai custom
connectors, mobile AI apps, MCP CLIs) behind **Google OAuth**, via a thin
`OAuthProxy`/`GoogleProvider` shim: Dynamic Client Registration (DCR) downward to
clients, one fixed Google client upstream, GCP test-users as the identity gate.

Its behaviour is 100% driven by a checked-in config file. **Adding or re-scoping a
backend is a config edit, never a code change.**

```yaml
# mcp-gateway.yaml
auth:
  provider: google        # client_id/secret from env; allowlist = GCP test-users
backends:                 # each backend defined ONCE
  ha: { url: http://ha-mcp:8087/mcp, transport: sse }
groups:                   # named audiences, each its own MCP URL
  admin:                  # bare names = all tools/resources/prompts of each backend
    backends: [ha]
  consumer:               # a curated slice of the SAME backends
    backends:
      - name: ha
        tools:   [get_*, light_*, switch_*]   # allow-globs, WITHIN ha only
        exclude: ["*_config"]                 # deny-globs win over allow
```

## Access groups

Each **group** is published at its own MCP URL, `<base>/<group>/mcp` (e.g.
`https://mcp.example.net/admin/mcp`, `/consumer/mcp`), and exposes a deliberately
curated subset:

- **Backend inclusion is the primary gate.** A group sees only the backends it lists.
- **Optional per-primitive globs refine WITHIN a backend.** `tools` / `resources` /
  `prompts` are allow-globs; `exclude` is deny-globs applied after and wins on conflict.
  Globs match the unprefixed primitive name within that backend only (tools/prompts by
  name, resources by `uri`/`uriTemplate`), so a `light_*` in one group never leaks
  another backend's colliding tool.
- **Scoping is symmetric across tools, resources, AND prompts.** A resource can leak
  data like a tool, so it gets the same first-class filter; resources are never
  blanket-exposed or auto-derived from tool selection.
- **Filtering is enforced at call time, not just hidden from lists.** A tool/resource/
  prompt filtered out of a group is rejected on direct invocation by exact name, and is
  never proxied to the backend.
- **Default exposure:** a bare backend name (or `["*"]`) exposes everything of that kind,
  including primitives a backend ADDS later (the surface re-filters each list call). An
  explicit allow-list instead freezes the surface until you edit it.

Within a group URL, tools are namespaced `<backend>_<tool>` (the group is implied by the
URL, no group prefix).

### Access is URL-as-capability (v1)

Every group URL shares the **one** Google OAuth Authorization Server (one redirect URI),
so any GCP test-user can authenticate; a group's separation is **possession of its URL**.
An unauthenticated request to any `<base>/<group>/mcp` returns 401 with RFC 9728
protected-resource metadata that resolves at the origin root and points at that single
shared AS. (All groups share one protected-resource identity and audience: FastMCP's
`OAuthProxy` is single-audience by construction, so a distinct per-group resource would
mint an AS token the group rejects and loop the client through re-auth forever. Since any
test-user can use any group URL anyway, a per-group resource identity would enforce
nothing.) There is **no per-member enforcement in v1**: keep the test-user set tiny and
trusted; use non-obvious group names if you want. Config reserves an optional `members:`
list per group as the seam for a future post-auth membership check (returns 403 for
non-members) that is additive, not a re-architecture.

## What it does

- **Composes** the referenced backends into one FastMCP server PER group (FastMCP
  `create_proxy`/`mount`), each mounted at `<base>/<group>/mcp`.
- **Fronts** them with a Google-federated OAuth Authorization Server (DCR down, Google
  up) so web + mobile AI clients can connect where oauth2-proxy and Traefik cannot.
- **Enforces** each group's scope on both discovery and invocation (`GroupScopeMiddleware`).
- **Emits** per-tool-call OpenTelemetry spans, tagged with the group URL, backend, tool.
- **Health-checks** backends (`initialize` -> `tools/list`), exposed at `/health`; each
  backend is probed once and reports which groups reference it.
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
uv run a2mcp                                    # serves each group at /<group>/mcp (+ /health)
# or: docker build -t a2mcp . && docker run -p 8000:8000 \
#       -v $PWD/mcp-gateway.yaml:/config/mcp-gateway.yaml:ro a2mcp
```

With `GOOGLE_CLIENT_ID` unset the gateway serves **open** (bind behind a tailnet/LAN
only). Set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `A2MCP_BASE_URL` /
`A2MCP_JWT_SIGNING_KEY` to turn on the Google-federated DCR OAuth. See
`mcp-gateway.example.yaml` for the full env list.

### Staying logged in (avoiding constant re-auth)

Three things must all hold or clients re-authorize on every restart:

1. **Persist the token store.** Mount a persistent volume at `A2MCP_OAUTH_CACHE_DIR`; the
   default lives on the container filesystem and is wiped on redeploy.
2. **Pin `A2MCP_JWT_SIGNING_KEY`.** If it rotates, every issued token is invalidated on
   restart. Generate once (`openssl rand -hex 32`) and keep it stable.
3. **One shared audience.** Handled in code: all group URLs share one Authorization Server
   and one protected-resource audience, so a token minted at login is accepted by every
   group. (A per-group resource would mint a token the group rejects and loop forever.)

## Status

Engine built: config (`backends` + `groups`), per-group composition, per-group scope
enforcement (tools/resources/prompts, at call time), Google-DCR auth with one shared AS +
one root RFC 9728 resource (groups delegate token verification to it), native OTel, health;
Docker + CI. Tracked in OpenSpec
change `add-access-groups` (run `openspec status`). Remaining before homelab flips "done":
publishing a new digest-pinned image, the per-group **claude.ai custom-connector DCR smoke**
(client-compat + discovery gate), and the homelab config migration to `backends` + `groups`.
