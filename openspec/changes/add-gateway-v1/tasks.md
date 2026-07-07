# Tasks: add-gateway-v1

## S: Scaffold

- [x] S1. `uv` project: `pyproject.toml`, `src/a2mcp/`, ruff + pytest. Pin `fastmcp>=3.2,<4` (3.x is GA as of 2026-07; the earlier "pin v2-stable" note is stale, confirmed against a2kit + a2web which both pin `>=3.2,<4`).
- [x] S2. RESOLVED (build-vs-adopt gate): a2kit does NOT expose a Google-DCR shim to adopt. Per a2kit ADR 0010/0011 it is auth-agnostic on the MCP surface and hands a FastMCP provider to `FastMCP(auth=...)`; the "blessed Google recipe" is a doc (`a2kit/docs/patterns/mcp-auth.md`), first realized in a2web's `build_google_provider`. => a2mcp wires FastMCP `GoogleProvider` DIRECTLY, mirroring a2web. a2mcp composes proxies (does not author tools), so **a2kit is not a v1 dependency**; pure FastMCP. Record `google-dcr-shim` 2nd sighting on the shelf (a2web = 1st, a2mcp = 2nd); do NOT extract a package at n=2 while call sites may still diverge.

## C: Core

- [x] C1. Config loader + schema validation for `mcp-gateway.yaml` (auth provider, endpoints -> backends). Fail loud on a bad config. => `src/a2mcp/config.py`, 8 tests.
- [x] C2. Composition: for each endpoint, `create_proxy`/`mount` its backends (namespaced). One process serves all endpoints as routes/mounts. => `src/a2mcp/compose.py` (nested `<endpoint>_<backend>_<tool>`; `create_proxy` replaces deprecated `as_proxy`).
- [x] C3. Auth shim: FastMCP `GoogleProvider` (direct, mirroring a2web), secrets + `base_url` from env; `jwt_signing_key` + persistent encrypted `client_storage` (FileTreeStore + FernetEncryptionWrapper) required; open-serve fallback; half-config loud fail; env-gated `StaticTokenVerifier` escape hatch. => `src/a2mcp/auth.py`, 6 tests; unauth 401 + WWW-Authenticate verified over HTTP.
- [x] C4. Telemetry: FastMCP 3.4 native OTel confirmed installed; a2mcp wires the OTLP SDK from `OTEL_EXPORTER_OTLP_ENDPOINT` + a thin `on_call_tool` span middleware on FastMCP's own tracer for `backend`/`tool` attribution. => `src/a2mcp/telemetry.py`.
- [x] C5. Health: periodic `initialize` -> `tools/list` per backend, bounded per-probe timeout (hung backend cannot wedge), `/health` with per-backend up/flaky/down. => `src/a2mcp/health.py`, 3 tests.

## P: Package

- [x] P1. Dockerfile (slim Python, uv, non-root, `/config` + `/data` volumes). Entry: read config path from env, serve. => built locally + ran the image; `/health` served, down-backend correctly reported 503.
- [x] P2. CI: `.github/workflows/ci.yml` runs ruff + pytest, then on push/tag builds + pushes to `ghcr.io/yoselabs/a2mcp` and records the digest in the job summary (homelab pins by digest, ADR 0003).

## V: Verify

- [~] V1. Automated: client lists + calls a namespaced backend tool through the gateway (in-memory + live `python -m a2mcp` boot smoke); unauth request 401 + WWW-Authenticate. **The live claude.ai custom-connector Google DCR smoke remains the manual client-compat gate** (needs real Google creds + a claude.ai connector) before homelab flips "done".
- [x] V2. `/health` reflects a backend going down (test + live image: down backend => 503 with error); a hung backend (accept-but-never-answer socket) is bounded by `probe_timeout` and does not wedge.
- [x] V3. Per-tool-call span carries `a2mcp.backend` / `a2mcp.endpoint` / `mcp.tool.name`, captured via an in-memory OTel exporter. (OTLP HTTP exporter is wired from env; sending to a live collector is the deploy-time check.)
- [x] V4. Config-only extension: a 2nd endpoint/backend added purely in the `GatewayConfig` serves both, no code change.

## Handoff

- [ ] H1. Publish the image digest to the homelab `add-mcp-gateway` change (tasks H2/R7) so the homelab wiring can pin it and deploy. **Pending the first push to `main`** (CI emits the digest); then hand it to homelab.
