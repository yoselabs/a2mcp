## Why

a2mcp is the write-once engine behind homelab's `platform/mcp-gateway` (origin spec:
`iorlas/homelab` OpenSpec `add-mcp-gateway`, ADR 0051, exposure Lane 9). It publishes
self-hosted MCP servers to off-tailnet AI clients (claude.ai, mobile AI apps, MCP CLIs)
behind Google OAuth, via a thin FastMCP `OAuthProxy`/`GoogleProvider` shim: DCR
downward, one fixed Google client upstream, GCP test-users as the gate. Behaviour is
fully config-driven so adding a backend is never a code change.

This change is **v1**: the minimum that fronts one backend (`ha-mcp`) end to end for a
real claude.ai custom connector, with the config, auth, telemetry, and health seams in
place so later backends are pure config.

## What Changes

- Python project (`uv`), FastMCP-based, with a Dockerfile and a GHCR publish (digest
  pinned).
- **Config loader** for `mcp-gateway.yaml` (auth provider plus endpoints -> backends).
  This is the only behaviour input.
- **Composition**: proxy/mount each backend into its endpoint (FastMCP
  `as_proxy`/`mount`), namespaced.
- **Auth shim**: Google-federated DCR via `GoogleProvider`/`OAuthProxy`, secrets from
  env, `base_url` = the public https URL. Reuse a2kit if it already exposes this (see the
  primitive shelf: `google-dcr-shim` is a born-now candidate that likely belongs in
  a2kit, not here).
- **Telemetry**: per-tool-call OpenTelemetry spans, OTLP endpoint from env (v2
  middleware; switch to FastMCP 3.0 native OTel at GA).
- **Health**: per-backend `initialize` -> `tools/list` handshake, exposed at `/health`.

## Capabilities

### New Capabilities

- `gateway`: a config-driven FastMCP gateway that fronts remote MCP backends as
  per-domain endpoints behind a Google-federated DCR OAuth shim, with per-tool-call
  telemetry and backend health, and with backend credentials isolated in the backends.

## Impact

- Consumed by homelab as a pinned image; no homelab-specific code lives here.
- Depends on FastMCP (and optionally a2kit for the auth shim). FastMCP 3.0 is beta at
  mid-2026; ship on v2-stable plus a small OTel middleware.

## Non-goals

- Not aggregating Docker-catalog tools as local sandboxed containers.
- Not per-tool RBAC or multi-tenant governance.
- Not multiple auth providers. Google only for v1 (a wrapper, not an `any-*`
  abstraction; do not pretend otherwise).
