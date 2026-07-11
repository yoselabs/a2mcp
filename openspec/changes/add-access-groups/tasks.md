## 1. Config model (backends + groups)

- [x] 1.1 Rework `config.py`: add top-level `backends: {name -> Backend}` and `groups: {name -> Group}`; a `Group` is a list of backend refs, each ref = a backend name (bare = all) or `{name, tools?, resources?, prompts?, exclude?}` with glob lists. Reserve an optional `members` field on `Group` (parsed, not enforced; D5 seam).
- [x] 1.2 Validation (fail-fast): every group backend ref names a defined backend; `groups` non-empty; group names URL-safe (namespace rule); glob lists are strings. Undefined-backend and empty-groups raise `ConfigError` with the offending names.
- [x] 1.3 Migrate/replace the v1 `endpoints` shape. Update `mcp-gateway.example.yaml` to the backends+groups form (an `admin` all-backends group + a filtered `consumer` group). Update tests in `tests/test_config.py`.

## 2. Per-group composition + URLs

- [x] 2.1 In `compose.py`, build ONE composed FastMCP server PER group (reuse `create_proxy`/`mount` per referenced backend; tools namespaced `<backend>_<tool>`, no group prefix).
- [x] 2.2 In `server.py`/`__main__.py`, assemble a parent ASGI app that mounts each group server at `/<group>` so its MCP endpoint is `<base>/<group>/mcp`. Keep the shared GoogleProvider AS at root; ensure each group URL advertises correct RFC 9728 protected-resource metadata.
- [x] 2.3 Update `auth.py` so `A2MCP_BASE_URL` drives per-group resource metadata (each `/<group>/mcp` is its own resource, one shared AS).

## 3. Group scope enforcement (tools + resources + prompts)

- [x] 3.1 Implement `GroupScopeMiddleware`: compile each group's per-backend allow/deny globs once; match tools/prompts by name and resources by `uri`/`uriTemplate`, unprefixed within the backend.
- [x] 3.2 Filter list results: `tools/list`, `resources/list`, `resources/templates/list`, `prompts/list`.
- [x] 3.3 Enforce at call time: reject `tools/call`, `resources/read`, `resources/subscribe`, `prompts/get` for filtered-out items with a clear MCP error (do NOT proxy to the backend). Cover the direct-call-by-name path.
- [x] 3.4 Default-exposure semantics: bare-name/`*` re-filters each list call (later backend additions appear); explicit allow-list freezes the surface; `exclude` wins.

## 4. Health + telemetry

- [x] 4.1 `/health`: keep per-backend `initialize`->`tools/list` probing; report which groups reference each backend (a backend is probed once even if in many groups).
- [x] 4.2 OTel spans: tag each per-tool-call span with the group URL it came through.

## 5. Tests

- [x] 5.1 Config: undefined-backend rejection, empty-groups rejection, bare-vs-refined ref parsing, `members` parsed-but-inert.
- [x] 5.2 Scoping: per-backend glob include/exclude; cross-backend collision safety; symmetric tools/resources/prompts filtering.
- [x] 5.3 Enforcement: filtered-out tool/resource/prompt rejected at call time even when addressed by exact name.
- [x] 5.4 URLs: two groups served at distinct `/<group>/mcp`; unauthenticated group URL returns 401 + protected-resource metadata.

## 6. Ship

- [x] 6.1 Update README (backends+groups model, per-group URLs, URL-as-capability posture + enforced-membership upgrade note, resource scoping).
- [x] 6.2 Build + publish a new digest-pinned GHCR image; record the digest. Local build verified (container boots, serves `/admin/mcp` + `/consumer/mcp`, `/health` reports group fan-out). Published by CI on push to `main` (commit `77ff22a`):
  `ghcr.io/yoselabs/a2mcp@sha256:b473c8ac0505a62745fc2402cbb7cadad7fdb0007241f180c6975319cff49f6b`
  (pin this in homelab `platform/mcp-gateway`, task 7.1). For a semver-pinned image, push a `v*` tag.
- [ ] 6.3 Per-group discovery smoke (throwaway funnel, same method as the v1 deploy spike): verify `/admin/mcp` and `/consumer/mcp` each serve 401 + correct discovery, and that a filtered tool is absent + uncallable in `consumer` but present in `admin`. Use **MCP Inspector before claude.ai** (Inspector sends the RFC 8707 `resource` param, so it is the stricter canary; if it connects, claude.ai will). Confirm a real token minted at the AS actually authorizes a `tools/call` on a group URL (the seam the unit suite mocks): this is what proves the audience fix end-to-end. Test both trailing-slash (`/consumer/mcp/`) and no-slash (`/consumer/mcp`) POSTs.

## 7. Homelab consumer handoff (iorlas/homelab)

- [x] 7.1 Rewrote `platform/mcp-gateway/mcp-gateway.yaml` to `backends` + `groups` (one `home` group, all of ha). Image bumped to digest `b473c8ac`; `A2MCP_OAUTH_CACHE_DIR=/data` on the persistent `mcp-gateway-data` volume; `A2MCP_JWT_SIGNING_KEY` already sops-stable; `--proxy-headers`/`forwarded_allow_ips` already set in the image `__main__`. Traefik unchanged. homelab commit `6d0d051`.
- [x] 7.2 Updated stack README + `[[stack.interface]]` (base_url `https://mcp.shen.iorlas.net/home/mcp`; tools surface `ha_ha_*` until the D6/§8 prefix toggle lands); regenerated inventory; `make lint-arch` green.
- [ ] 7.3 Add each group URL as its own claude.ai custom connector; verify scoping. **USER** (needs deploy + browser). NOTE: with a single `home` group there is no cross-group check yet; revisit when a scoped second group is added.

## 8. Optional per-ref prefix toggle (design D6)

- [x] 8.1 `config.py`: add `prefix: bool = True` to `BackendRef`. Load-time invariant: AT MOST ONE ref per group may set `prefix: false` (else `ConfigError` naming the group). Update `tests/test_config.py`.
- [x] 8.2 `compose.py`: when `ref.prefix` is false, `mount(...)` the backend WITHOUT `namespace` (no `<backend>_` / `<scheme>://<backend>/` prefix).
- [x] 8.3 `scope.py`: attribute an UNPREFIXED name to the group's single unprefixed backend (`_backend_of_name`/`_backend_of_uri` fall back to it when no known `<backend>_` prefix matches), so globs + call-time enforcement still apply. `telemetry.py::_split_namespaced` handles the no-prefix case too.
- [x] 8.4 Tests: single-backend group unprefixed still filters/enforces; same backend prefixed in one group + unprefixed in another; two-unprefixed rejected at load.
- [x] 8.5 Docs: `mcp-gateway.example.yaml` + README document `prefix: false` and BOTH reasons to use it (backend self-prefixes -> avoid `ha_ha_*`; single-backend group -> prefix is noise), plus "assess before adding a backend".
