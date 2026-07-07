# Tasks: add-gateway-v1

## S: Scaffold

- [ ] S1. `uv` project: `pyproject.toml`, `src/a2mcp/`, ruff + pytest. Pin FastMCP v2-stable.
- [ ] S2. Decide the a2kit dependency: does a2kit already expose a Google-DCR shim? If yes, ADOPT it (build-vs-adopt gate, shelf `google-dcr-shim`); if no, wire it here and note it as the born-now candidate to graduate into a2kit later.

## C: Core

- [ ] C1. Config loader + schema validation for `mcp-gateway.yaml` (auth provider, endpoints -> backends). Fail loud on a bad config.
- [ ] C2. Composition: for each endpoint, `as_proxy`/`mount` its backends (namespaced). One process serves all endpoints as routes/mounts.
- [ ] C3. Auth shim: `GoogleProvider`/`OAuthProxy` (or a2kit), secrets + `base_url` from env. Verify DCR is presented downward and Google is upstream.
- [ ] C4. Telemetry: per-tool-call OTel middleware -> `OTEL_EXPORTER_OTLP_ENDPOINT`. Mark the FastMCP-3.0-native TODO.
- [ ] C5. Health: periodic `initialize` -> `tools/list` per backend, bounded timeouts, `/health` with per-backend status.

## P: Package

- [ ] P1. Dockerfile (slim Python, uv). Entry: read config path from env/arg, serve.
- [ ] P2. CI: build + publish to `ghcr.io/iorlas/a2mcp`, record the digest (homelab pins by digest, ADR 0003).

## V: Verify

- [ ] V1. Local: run against a stub MCP backend; a client completes the Google DCR flow and lists+calls a tool.
- [ ] V2. `/health` reflects a backend going down; a hung backend does not wedge the gateway.
- [ ] V3. Per-tool-call spans reach a local OTLP collector.
- [ ] V4. Config-only extension: add a 2nd stub backend via YAML, no code change, both endpoints serve.

## Handoff

- [ ] H1. Publish the image digest to the homelab `add-mcp-gateway` change (tasks H2/R7) so the homelab wiring can pin it and deploy.
