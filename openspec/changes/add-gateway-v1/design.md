# Design: add-gateway-v1

Full rationale (why a shim, why not ContextForge/Keycloak/Docker MCP Gateway, the lane,
the client-compat research) lives in the origin spec: `iorlas/homelab` OpenSpec
`add-mcp-gateway` design.md. This file covers only the a2mcp engine.

## Shape: config in, endpoints out

One process. On boot it reads `mcp-gateway.yaml`, builds each endpoint by proxying its
backends, wraps everything in the Google auth shim, and serves streamable-HTTP/SSE that
remote clients (behind homelab's Traefik) reach. No database, no runtime-mutable state.

```
mcp-gateway.yaml ->  [ config loader ]
                          |
                     [ compose: FastMCP as_proxy/mount per endpoint ]
                          |
                     [ auth shim: GoogleProvider (DCR down, Google up) ]
                          |
                     serve HTTP/SSE  (+ /health, + OTel spans)
                          |
                     remote MCP backends (ha-mcp, ...) over the private net
```

## Config schema (v1)

```yaml
auth:
  provider: google         # only value supported in v1
endpoints:
  <name>:                  # each -> its own MCP route/mount
    backends:
      - name: <str>
        url: <backend mcp url>
        transport: sse | streamable
        headers: { ... }   # optional, to REACH the backend (e.g. ha-mcp secret path)
```

Env (from homelab sops): `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `A2MCP_BASE_URL`
(the public https URL), `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Decisions

1. **Auth = build here, direct FastMCP `GoogleProvider` (S2 resolved).** a2kit has no
   Google-DCR helper to adopt: by ADR 0010/0011 it is auth-agnostic on the MCP surface and
   the "blessed recipe" is a doc, first realized in a2web's `build_google_provider`. So
   a2mcp mirrors a2web: construct `GoogleProvider(client_id, client_secret, base_url,
   jwt_signing_key, client_storage, required_scopes)` and pass it as `FastMCP(auth=...)`.
   `jwt_signing_key` (stable env) and a persistent encrypted `client_storage` (FileTreeStore
   + FernetEncryptionWrapper) are REQUIRED — the in-memory default loses tokens on restart
   (daily-reauth trap). Env-gated `StaticTokenVerifier` bearer escape hatch for
   DCR-incompatible clients. Since a2mcp composes proxies rather than authoring tools,
   **a2kit is not a v1 dependency** (pure FastMCP). The test-users gate is enforced at
   Google's consent screen; no allowlist in our config. `base_url` = the public https URL,
   forwarded untouched by Traefik, is the classic footgun.
2. **Composition is FastMCP's job.** Use `FastMCP.as_proxy(url)` + `root.mount(server,
   namespace=...)` (verified against installed fastmcp 3.4.3; `prefix=` is the deprecated
   alias for `namespace=`); our code is the config->mount glue, not a reimplementation.
   **Endpoint model locked (origin design left this open): one MCP URL, nested namespaces**
   `<endpoint>_<backend>_<tool>`. One root `FastMCP(auth=provider)`; each endpoint is a
   sub-server mounted under its name, each backend a proxy mounted under its name. Rationale:
   keeps exactly ONE authorization server and ONE Google redirect URI (per-path endpoint
   URLs would fracture the single registered redirect the origin design mandates), and it is
   the thin choice. Per-path endpoint URLs are a future enhancement gated on FastMCP making
   split AS/resource composition trivial.
3. **Backend credential isolation.** The gateway holds only what it needs to REACH a
   backend (url + optional headers). A backend's own credential (ha-mcp's HA token) stays
   in the backend, which is bound to the private net.
4. **Telemetry = middleware now, native later.** A ~50-line `on_call_tool` middleware
   emits per-call spans to the OTLP endpoint on v2; leave a marked TODO-note to drop it
   for FastMCP 3.0 native OTel at GA.
5. **Health = synthesized.** MCP `ping` only proves transport; do a periodic
   `initialize` -> `tools/list` per backend and expose up/flaky/down at `/health`. Never
   let a hung backend wedge the gateway (bounded timeouts).

## Micro-software lens

Product (T3) = the config-to-endpoints composition. The `google-dcr-shim` is a born-now
T1 primitive (shelf) that should live in a2kit. `backend-proxy` and `per-tool-call OTel`
are FastMCP-provided or soon-native; do not build lasting abstractions over them.
`backend-health` is genuinely ours; shelve if a 2nd FastMCP server wants the same probe.
See `docs/design/primitive-shelf.md`.

## Risks

- **FastMCP pin** (was "3.0 beta, pin v2"): stale as of 2026-07. 3.x is GA; a2kit and a2web
  both pin `fastmcp>=3.2,<4`, so a2mcp does too. Prefer 3.x native OTel over a hand-rolled
  middleware; verify the per-tool-span API against the installed version before coding C4.
- **Client-compat is the real work** (research): claude.ai custom connector and one
  mobile app must be smoke-tested against the live DCR flow. Watch access-token expiry,
  loopback redirect-port variance, and `base_url` mismatches.
