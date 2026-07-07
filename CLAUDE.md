# CLAUDE.md: a2mcp

The write-once engine behind homelab's `platform/mcp-gateway`. A generic,
config-driven MCP gateway on FastMCP that publishes MCP servers behind Google OAuth.
See `README.md`. **Origin spec:** `iorlas/homelab` OpenSpec `add-mcp-gateway` (ADR
0051, Lane 9). Read that for the full rationale before changing the design here.

## What this repo IS

- The reusable gateway software. Behaviour is driven by a declarative
  `mcp-gateway.yaml` (auth provider + endpoints -> backends). The whole point:
  **adding a backend is config, never code.**
- Python, FastMCP, `uv`. Lean dependency surface. The gateway should stay boring.

## What this repo is NOT

- Not homelab. No homelab-specific config, hostnames, or secrets live here (homelab
  supplies those and pulls this as a digest-pinned GHCR image, ADR 0003/0030).
- Not an aggregator of Docker-catalog tools, not a policy/RBAC engine. It fronts our
  own remote MCP servers behind one Google login. Nothing more for v1.

## Operating rules

- **OpenSpec-first.** Propose a change (`/opsx:propose`) before non-trivial work; the
  active build is `add-gateway-v1`.
- **No em-dashes** in any user-facing text. Colons, commas, periods, parentheses.
- **`uv` for deps**, never hand-edited lockfiles.
- **Secrets from env only** (sops-rendered by homelab). Never commit a token; `base_url`
  must be the public https URL or DCR discovery points clients wrong.

## Micro-software discipline (the "shelf")

Build thin. As code grows, watch for **T1 "any-*" primitives** (thin, deep, lets the
consumer stop caring about a substrate quirk) and **shelve** them per the rule-of-three
rather than burying them in the gateway. Consult `docs/design/primitive-shelf.md`
BEFORE hand-rolling any helper, and record sightings there.

Known **born-now** candidate to keep honest from day one:

- **The Google-DCR OAuth shim** (`OAuthProxy`/`GoogleProvider` wiring) is deep and
  obviously reusable across every FastMCP server we run. It likely belongs in **a2kit**
  (our FastMCP auth lib), consumed by a2mcp, NOT reimplemented here. Treat a2mcp's use
  as consumer #1; if a2kit already exposes it, adopt rather than rebuild (build-vs-adopt
  gate). Do not dress a single-provider wrapper as an `any-*` abstraction (Google only
  for v1 is a wrapper, not provider-indifference).

Tiering for this repo: the **product (T3)** is the config-to-endpoints composition +
the lane it serves; the **shim, per-backend proxy, telemetry, and health** are the
pieces to evaluate for the shelf as they earn a 2nd consumer. Do not extract at n=1 on a
guess; the simplification lands with an in-repo module first, a package only on a real
2nd consumer.
