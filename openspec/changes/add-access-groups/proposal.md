## Why

a2mcp v1 serves ONE MCP URL that exposes ALL backends' tools to any GCP test-user: a
single coarse gate, all-or-nothing. There is no way to publish a curated, audience-specific
slice (e.g. a household member should get Home Assistant read + lights, never the admin
everything-surface), and as backends accumulate, one-URL-all-tools also bloats every
client's tool-selection. We want named, audience-scoped groups, each its own URL, each a
deliberately curated subset.

## What Changes

- **BREAKING** (supersedes the in-progress v1 `endpoints` config): replace the
  namespace-only `endpoints` map with a two-part model:
  - top-level `backends`: each MCP server defined ONCE (url, transport, headers);
  - `groups`: named audiences, each referencing backends by name, each published at its
    own MCP URL `<base>/<group>` (e.g. `/admin`, `/consumer`).
- **Per-MCP-server is the primary scoping axis.** A backend is either in a group or not;
  inclusion is the gate. Optional per-primitive globs refine WITHIN a named backend only
  (tool names can collide across servers, so globs are never global and never the sole
  gate).
- **Scoping is symmetric across all MCP primitives** -- tools, resources, AND prompts. A
  backend's resources/prompts are gated by its inclusion, optionally glob-filtered per
  group. Resources are NOT blanket-exposed and NOT auto-derived from tool selection (MCP
  does not bind a resource to a tool); a resource can leak data just like a tool, so it
  gets the same first-class per-group filter.
- **Access is URL-as-capability** (v1 decision): every group URL shares the one Google
  OAuth, so any GCP test-user can authenticate; a group's separation is possession of its
  URL. No per-member enforcement in v1. Enforced per-group membership (email/role
  allowlist) is a documented future upgrade, called out with its residual risk.
- Adding a backend becomes: define it once in `backends`, then list it in each group that
  should carry it.

## Capabilities

### New Capabilities

- `access-groups`: audience-scoped exposure. Named groups, each published at its own MCP
  URL, each curating a subset of backends and (per backend, optionally) their tools,
  resources, and prompts via within-backend globs. Gated by URL-as-capability over the
  shared Google OAuth. Config-driven and git-canonical: adding or re-scoping a backend is
  a config edit, never code.

### Modified Capabilities

- (none in main specs.) This supersedes the config model of the in-progress `gateway`
  capability (`add-gateway-v1`, `endpoints` -> `backends` + `groups`). Flagged for
  reconciliation with that change; no main spec exists to delta yet.

## Impact

- **Config schema** (breaking vs the v1 `endpoints` shape). v1 has not shipped a stable
  config, so blast radius is the single homelab file
  `iorlas/homelab:platform/mcp-gateway/mcp-gateway.yaml`, which migrates from `endpoints`
  to `backends` + `groups`.
- **Engine** (`src/a2mcp/`): config loader (backends + groups + per-primitive filters),
  composition (one composed FastMCP server per group, each mounted at its own HTTP path),
  a per-group primitive-filter middleware (filters `tools/list`, `resources/list`,
  `prompts/list` and rejects calls to filtered items), and per-group discovery/`base_url`.
- **Homelab consumer**: `mcp-gateway.yaml` rewritten to groups; each group URL added as
  its own claude.ai custom connector; README + `[[stack.interface]]` updated (one
  interface per group, or one documenting the group URL pattern).
- **Origin cross-ref**: `iorlas/homelab` ADR 0051 listed per-tool RBAC as a non-goal.
  This change revisits the GROUPING/curation half (audience-scoped surfaces), not
  per-user RBAC, which URL-as-capability deliberately defers.
