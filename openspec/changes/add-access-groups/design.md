## Context

a2mcp v1 (`add-gateway-v1`) composes all backends into ONE root FastMCP server, served at
one MCP URL, tools namespaced `<endpoint>_<backend>_<tool>`. `endpoints` is namespace-only:
it groups tool NAMES, not audiences, and every tool is visible to any authenticated GCP
test-user. This change makes exposure audience-scoped: named groups, each its own URL,
each a curated subset of backends and their primitives.

Constraints carried from v1: config-driven and git-canonical (adding/re-scoping a backend
is a config edit, never code); one shared Google OAuth client (GoogleProvider/OAuthProxy,
DCR downward); FastMCP v2-stable; backend credentials stay in the backends.

## Goals / Non-Goals

**Goals:**
- Named groups, each published at its own MCP URL, each exposing a deliberately curated
  subset of backends.
- Per-MCP-server as the primary scoping axis, with optional per-primitive glob refinement
  scoped WITHIN a backend.
- Symmetric scoping across tools, resources, and prompts.
- Define each backend once; reference it from the groups that carry it.
- Keep v1 as the degenerate one-group case, so rollback is a config edit.

**Non-Goals:**
- Per-user / per-member enforcement (URL-as-capability is the v1 gate; membership is a
  documented upgrade seam, not built here).
- Per-tool RBAC policy engine, quotas, or multi-tenant governance.
- Changing the auth mechanism (shared Google DCR shim stays).

## Decisions

### D1. Config model: top-level `backends` + `groups` that reference them

Backends are defined once (url, transport, headers). Groups reference backends by name and
optionally filter their primitives, and each group is its own URL.

```yaml
auth: { provider: google }
backends:
  ha:      { url: http://100.101.177.110:8087/mcp, transport: sse }
  weather: { url: http://.../mcp, transport: streamable }
groups:
  admin:                                   # bare names = all primitives of each
    backends: [ha, weather]
  consumer:
    backends:
      - name: ha
        tools:     [get_*, "*_state", light_*, switch_*]   # allow-globs, within ha only
        exclude:   ["*_config"]                             # deny-globs, applied after allow
        resources: ["*"]                                    # default; all of ha's resources
      # prompts omitted -> default all; a backend name alone -> all tools+resources+prompts
```

Alternatives rejected: inline backend definitions per group (repeats connection details,
drifts); extend `endpoints` with filters (endpoints are namespace-only and carry no URL or
audience semantics, so it would conflate two concepts).

### D2. One composed FastMCP server per group, mounted at its own HTTP path

Build N group servers (each proxies/mounts its backends via the existing
`create_proxy`/`mount` path from compose.py) and assemble a parent ASGI app that mounts
each group server under `/<group>`, so the group's MCP endpoint is `<base>/<group>/mcp`
(e.g. `https://mcp.shen.iorlas.net/consumer/mcp`). Within a group URL, tools are
`<backend>_<tool>` (group is implied by the URL, so no group prefix; this drops v1's
`<endpoint>_` segment). The shared GoogleProvider AS (`/authorize`, `/token`, `/register`)
lives once at root.

Alternative rejected: one root server with per-request path-based filtering. FastMCP
composition is per-server; N small group servers keep each group's surface a real, testable
object rather than a filter over a shared surface.

**Auth correction (validated against FastMCP 3.4.3 during build, Fable council review):**
the original plan gave each group URL its OWN RFC 9728 resource
(`/.well-known/oauth-protected-resource/<group>/mcp`, per-group `resource_base_url`). That
is BROKEN on FastMCP 3.4.3: `OAuthProxy` is single-resource, single-audience by construction
(`set_mcp_path` -> `JWTIssuer(audience=str(resource_url))`, verified with strict equality).
A shared AS at root mints `aud=<base>/mcp`, but a per-group resource verifies
`aud=<base>/<group>/mcp`, so EVERY authenticated request 401s and the client reauths in a
loop (the "authorize too often" trap). "One AS, N distinct resources" is not expressible
without forking the issuer. So v1 uses ONE protection domain: a single `GoogleProvider` at
root is both the AS and the one protected resource (`<base>/mcp`, served at
`/.well-known/oauth-protected-resource/mcp`). Each group server delegates token verification
to that instance via a `RemoteAuthProvider` (no second audience, no per-group AS routes), so
a group URL still challenges 401 and its metadata resolves at the origin root. This is honest
with the security model: under URL-as-capability any test-user can complete the flow against
any group URL anyway, so a per-group resource identity would enforce nothing. Per-group
audience isolation, if ever wanted, is Design B (per-group `base_url`, one Google redirect URI
PER group) -- deferred.

### D3. Per-primitive filtering via a portable middleware, enforced at call time

A `GroupScopeMiddleware` bound to each group server enforces that group's per-backend
globs on BOTH discovery and invocation:
- filters `tools/list`, `resources/list`, `resources/templates/list`, `prompts/list` to
  matching entries;
- REJECTS `tools/call`, `resources/read`, `resources/subscribe`, `prompts/get` for items
  that do not match (so a hidden item cannot be invoked by guessing its name -- listing
  alone is not a security boundary).

Globs match the UNPREFIXED primitive name within its backend (tools/prompts by name;
resources by `uri` / template `uriTemplate`). Because a backend is only reachable if the
group includes it, cross-server tool-name collisions cannot leak: `light_*` in `consumer`
scopes ha's tools only, never another backend's.

Alternatives rejected: FastMCP `include_tags`/`exclude_tags` (needs tags on upstream tools
we do not own, and does not cover resources uniformly); filtering at proxy-build time
(proxied remote primitives are discovered dynamically, so a list-time middleware is robust
to backends adding/removing primitives after start).

### D4. Default-exposure semantics

A bare backend name, or a primitive selector of `["*"]`, exposes ALL of that backend's
primitives -- including ones the backend ADDS later (the proxy is dynamic; the middleware
re-filters each list call). A group that must stay frozen to a known surface uses an
explicit allow-list instead of `*`. `exclude` always wins over allow. This default keeps
"admin = everything" trivially correct and is documented so operators choose `*` vs an
explicit list deliberately.

### D5. Auth = URL-as-capability, with an enforced-membership seam

All group URLs share the one Google OAuth; any GCP test-user can authenticate. A group's
separation is possession of its URL; there is no per-member check in v1. The upgrade seam:
an optional `members: [email|role]` per group + a post-auth `GroupMembershipMiddleware` that
checks the verified identity claim and returns 403 for non-members. Additive, no
re-architecture. Recorded now so the config schema can reserve `members` as optional.

### D6. Tool prefix is a per-ref toggle, default on ("all or nothing per backend")

Within a group URL, a backend's tools/prompts are namespaced `<backend>_<tool>` and its
resources `<scheme>://<backend>/<rest>`. The prefix does DOUBLE duty: (1) it disambiguates
names that collide across backends, and (2) it is the routing key `GroupScopeMiddleware`
uses to map a tool back to its backend and apply that backend's globs. It is uniform per
backend (all its primitives or none), never partial.

The prefix is often noise: a single-backend group (`consumer = [ha]`) has nothing to collide
with, and a backend that already self-prefixes its own tool names (e.g. tools arriving as
`ha_*`) becomes an ugly `ha_ha_*`. So a group's ref MAY set `prefix: false` to mount that
backend without the namespace.

- The flag lives on the **backend REF** (per group), not the backend, so `ha` can be
  unprefixed in `consumer` yet prefixed in `admin`. Default is `true`.
- **Default `true`, explicit `false`** (NOT an automatic "prefix iff >1 backend" heuristic):
  a count-driven prefix would SILENTLY RENAME a group's tools the moment a second backend is
  added, breaking every client that saved a tool name and contradicting D4's "explicit list
  freezes the surface." Predictability wins; the operator opts out deliberately.
- **Load-time invariant (fail-fast):** AT MOST ONE ref per group may be `prefix: false`.
  With two unprefixed backends, a bare name like `get_state` is ambiguous -- the scope
  middleware cannot tell whose globs apply -- so `ConfigError`. This needs only the flags and
  the group's ref count, not the remote tool lists, so it is statically checkable.
- **Middleware/telemetry consequence:** with an unprefixed backend, a name carrying no known
  `<backend>_` prefix is attributed to that group's single unprefixed backend (there is at
  most one). `GroupScopeMiddleware` and `_split_namespaced` learn this rule; this is why
  `prefix: false` is a real change, not just dropping the mount namespace.
- **Two distinct reasons to set it, both documented:** (A) the backend self-prefixes (avoid
  `ha_ha_*`); (B) a single-backend group where the prefix is pure noise. The example config
  and README call out both, plus the "assess before adding a backend" guidance.

Alternatives rejected: automatic multiplicity heuristic (silent renames on growth); a
per-backend (global) flag (cannot be clean-when-alone in one group and disambiguated in
another); per-tool prefix control (violates "all or nothing per backend", and the collision
it would manage is better solved by including fewer backends per group).

## Risks / Trade-offs

- **URL-as-capability is weak against a malicious test-user.** A curious/hostile test-user
  who guesses `/admin` gets its full surface. -> Mitigation: keep the test-users set tiny
  and trusted; use non-obvious group names if wanted; ship the enforced-membership seam
  (D5) when the set grows.
- **Filtering must be enforced at call time, not just hidden in lists.** A list-only filter
  leaks on direct invocation. -> Mitigation: D3 rejects calls to filtered items.
- **Dynamic resources (templates, subscriptions) must respect filters.** -> Mitigation:
  filter templates list and gate `resources/read` + `resources/subscribe`.
- **FastMCP multi-mount + per-group OAuth discovery is unproven in this repo.** The v1
  spike proved single-URL discovery; per-`/<group>/mcp` protected-resource metadata must be
  re-verified. -> Mitigation: repeat the throwaway-funnel discovery smoke per group URL
  before the homelab config migrates (same method as the v1 deploy spike).
- **Breaking config change.** -> Mitigation: v1 has not shipped a stable config; the only
  consumer is one homelab file, migrated in lockstep. v1 behavior == a single group named
  e.g. `home` containing all backends, so rollback is a config revert.

## Migration Plan

1. Engine: config loader (backends + groups + per-primitive globs + optional members),
   composition (per-group server + mount at `/<group>`), `GroupScopeMiddleware`, per-group
   discovery/`base_url`. Health probing per backend is unchanged; `/health` reports which
   groups reference each backend.
2. Publish a new digest-pinned image.
3. Per-group discovery smoke (throwaway funnel) before touching homelab.
4. Homelab: rewrite `platform/mcp-gateway/mcp-gateway.yaml` to backends + groups; add each
   group URL as its own claude.ai connector; update README + `[[stack.interface]]` (one per
   group, or one documenting the `<base>/<group>/mcp` pattern). Traefik needs NO change (the
   `Host(mcp.shen.iorlas.net)` rule already forwards every path to the container).
5. Rollback: revert the config to one all-backends group.

## Open Questions

- Path shape `<base>/<group>/mcp` (chosen, least FastMCP friction) vs `<base>/<group>`.
- Whether to require every backend to belong to at least one group (lint/validation) so a
  defined-but-unreferenced backend is flagged rather than silently dead.
- Resource glob target confirmation: match `uri` and `uriTemplate` (chosen) vs a separate
  selector for templates.
