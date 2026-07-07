# Primitive shelf

A living rule-of-three ledger (micro-software method). **Grep this before hand-rolling
any helper.** It prevents both premature abstraction (extract at n=1 on a guess) and
permanent duplication (never notice the 3rd copy).

## The rule

```
1st use  ->  write it inline. Do NOT name it.
2nd use  ->  SHELVE below: name + BOTH call sites + the one-line "lets us stop caring about ..."
3rd use  ->  PROMOTE-REVIEW: extract + refactor all sites together (confirm deep + shape clear).

born-now (skip the shelf):  it fixes a bug  |  it's deep + obviously reusable EXTERNALLY
eviction:  sat at 2 while the two uses DIVERGED -> drop it (coincidence, not a primitive).
```

Extraction is two stages: stage 1 = in-repo module (buys simplification, n=1 fine);
stage 2 = own package (buys reuse-elsewhere, gated on a REAL 2nd consumer). A module can
sit at stage 1 indefinitely. A package MUST NOT import the host.

## Born-now candidate (design intent, verify on build)

### google-dcr-shim  -- lets a FastMCP server stop caring that Google has no DCR
- **Shape:** `OAuthProxy`/`GoogleProvider` wiring that presents DCR downward, holds one
  fixed Google client upstream, mints its own JWTs, gates by GCP test-users.
- **Why born-now:** deep, and reusable across EVERY FastMCP server we run, not just this
  gateway.
- **Home:** almost certainly **a2kit** (our FastMCP auth lib), with a2mcp as consumer #1.
  Build-vs-adopt gate: if a2kit already exposes this, ADOPT; do not reimplement here.
- **Guard:** Google-only is a WRAPPER, not provider-indifference. Do not name it `any-*`
  or add multi-provider branches until a real 2nd provider exists.

## Shelved (2nd sightings)

### google-dcr-shim  -- 2nd sighting (rule-of-three: at 2, do NOT extract yet)
- **Call site 1:** a2web `build_google_provider` (a2web/src/a2web/server.py) — the working
  `GoogleProvider(...)` + FileTreeStore + FernetEncryptionWrapper wiring, per a2kit's
  `docs/patterns/mcp-auth.md` (ADR 0010/0011).
- **Call site 2:** a2mcp `src/a2mcp` auth wiring (this repo, C3) — same recipe, but for a
  proxy-composition gateway rather than a tool-authoring server.
- **Divergence watch:** a2web serves ONE authored surface; a2mcp fronts MANY proxied
  backends behind one provider. If the two wirings stay identical at a 3rd sighting,
  PROMOTE into a2kit (the recipe's own suggested home) as a thin `GoogleProvider` factory.
  If they diverge (e.g. a2mcp needs multi-endpoint redirect handling a2web never wants),
  EVICT — it was a shared doc-pattern, not a shared primitive.
- **Note:** the reusable artifact today is a2kit's *doc* + a2web's code, NOT a package. Copy
  the pattern in-repo for v1; a package is gated on a real, non-divergent 3rd consumer.

## Watch list (evaluate for the shelf as they earn a 2nd consumer)

- **backend-proxy** -- mount/compose a remote MCP backend into an endpoint (FastMCP
  `as_proxy`/`mount`). Today FastMCP provides it; only shelve OUR glue if it recurs.
- **per-tool-call OTel** -- the telemetry middleware. FastMCP 3.0 makes this native; do
  not build a lasting abstraction over a soon-native feature.
- **backend-health** -- the `initialize` -> `tools/list` handshake + `/health`. Genuinely
  ours to build; watch whether other FastMCP servers want the same probe.
