## ADDED Requirements

### Requirement: Backends defined once, referenced by groups

The gateway config SHALL define each backend once under a top-level `backends` map
(name -> url, transport, optional headers), and SHALL define `groups`, each of which
references backends by name. A group that references an undefined backend name SHALL fail
config validation at load (fail-fast, no partial serving).

#### Scenario: Group references a defined backend
- **WHEN** the config defines backend `ha` and a group `admin` with `backends: [ha]`
- **THEN** the gateway loads and group `admin` exposes backend `ha`

#### Scenario: Group references an undefined backend
- **WHEN** a group references `backends: [ghost]` and no backend `ghost` is defined
- **THEN** config load fails with a clear error naming the group and the missing backend

#### Scenario: Adding a backend is a config-only edit
- **WHEN** a new backend is added to `backends` and listed in one or more groups
- **THEN** those groups expose it after a reload, with no code change

### Requirement: Each group is published at its own MCP URL

The gateway SHALL serve each group as an independent MCP endpoint at `<base>/<group>/mcp`.
Each group URL SHALL be an authenticated resource whose unauthenticated request returns a
401 with RFC 9728 protected-resource metadata that references the one shared Authorization
Server. Tools within a group URL SHALL be namespaced `<backend>_<tool>` (the group is
implied by the URL, with no group prefix).

Note (FastMCP 3.4.3 constraint, see design.md): all group URLs share ONE protected-resource
identity and audience served at the origin root (`/.well-known/oauth-protected-resource/mcp`);
they are NOT distinct per-group resources. A per-group resource would mint an AS-audience the
group verifier rejects, causing an endless reauth loop. Per-group audience isolation is a
deferred upgrade (Design B), not required by v1's URL-as-capability model.

#### Scenario: Distinct group URLs
- **WHEN** groups `admin` and `consumer` are configured
- **THEN** `<base>/admin/mcp` and `<base>/consumer/mcp` are served as separate MCP endpoints

#### Scenario: Shared discovery metadata resolves to the one AS
- **WHEN** a client's unauthenticated request to any group URL is challenged and it follows
  the `resource_metadata` pointer
- **THEN** the metadata resolves at the origin root, names the one shared resource, and
  references the single shared Authorization Server

### Requirement: Backend inclusion is the primary scoping gate

A group URL SHALL expose the primitives of ONLY the backends it references. A backend not
referenced by a group SHALL be unreachable through that group's URL for listing and for
invocation.

#### Scenario: Unreferenced backend is invisible
- **WHEN** group `consumer` references `[ha]` and not `weather`
- **THEN** `weather` tools, resources, and prompts do not appear in `consumer` lists and cannot be called via the `consumer` URL

### Requirement: Optional per-primitive glob refinement within a backend

For each backend a group references, the group MAY refine which primitives are exposed via
allow-globs (`tools`, `resources`, `prompts`) and deny-globs (`exclude`). Globs SHALL match
the unprefixed primitive name within that backend only (tools/prompts by name; resources by
`uri` and template `uriTemplate`). A bare backend name, or an omitted/`["*"]` selector,
SHALL expose all of that backend's primitives of that kind. `exclude` SHALL be applied after
allow and SHALL win on conflict. Globs of one backend SHALL never match another backend's
primitives.

#### Scenario: Tool allow-glob
- **WHEN** group `consumer` scopes backend `ha` with `tools: [get_*, light_*]`
- **THEN** only ha tools matching those globs are listed and callable in `consumer`

#### Scenario: Exclude wins over allow
- **WHEN** a backend is scoped `tools: ["*"], exclude: ["*_config"]`
- **THEN** tools matching `*_config` are not listed and not callable, even though `*` allowed them

#### Scenario: Globs do not cross backends
- **WHEN** group `consumer` includes backends `ha` and `weather`, and scopes `ha` with `tools: [get_*]`
- **THEN** the `get_*` glob filters ha only; weather's tools are governed by weather's own selector, unaffected

### Requirement: Scoping is symmetric across tools, resources, and prompts

The gateway SHALL apply group scoping identically to tools, resources (including resource
templates), and prompts. Resources SHALL NOT be blanket-exposed and SHALL NOT be derived
from tool selection; they are gated by the same backend-inclusion plus optional glob
mechanism.

#### Scenario: Resource scoping is independent of tools
- **WHEN** a group scopes a backend's `tools` to a subset but leaves `resources` default
- **THEN** all of that backend's resources are exposed, and the tool subset is unaffected

#### Scenario: Prompt filtering
- **WHEN** a group scopes a backend's `prompts` with an allow-glob
- **THEN** only matching prompts are listed and retrievable in that group

### Requirement: Filtering is enforced at call time, not only in listings

The gateway SHALL reject invocation of any primitive excluded from a group, independent of
whether the client discovered it via a list. This applies to `tools/call`, `resources/read`,
`resources/subscribe`, and `prompts/get`.

#### Scenario: Direct call to a filtered tool is rejected
- **WHEN** a client calls a tool that is filtered out of the group, by its exact name
- **THEN** the gateway returns an error and does not proxy the call to the backend

#### Scenario: Read of a filtered resource is rejected
- **WHEN** a client reads a resource URI that is filtered out of the group
- **THEN** the gateway returns an error and does not proxy the read

### Requirement: Default-exposure semantics for new primitives

When a group exposes a backend via a bare name or `["*"]`, primitives the backend adds later
SHALL become visible in that group automatically. When a group uses an explicit allow-list,
only primitives matching that list SHALL be exposed, so later additions stay hidden until
the list is updated.

#### Scenario: Wildcard exposes later additions
- **WHEN** a group exposes backend `ha` with all tools and ha later adds a new tool
- **THEN** the new tool appears in that group without a config change

#### Scenario: Explicit list freezes the surface
- **WHEN** a group scopes `ha` with an explicit tool allow-list and ha adds a new tool
- **THEN** the new tool does not appear in that group until the allow-list is updated

### Requirement: Group access is gated by the shared OAuth (URL-as-capability)

Every group URL SHALL require a valid bearer token from the shared Google-federated
Authorization Server. An unauthenticated request SHALL receive `401` with protected-resource
metadata, not a tool list. In v1 the gateway SHALL NOT enforce per-member group membership:
any authenticated GCP test-user MAY use any group URL. Per-member enforcement is out of
scope for this change.

#### Scenario: Unauthenticated request is challenged
- **WHEN** an unauthenticated client hits a group URL
- **THEN** it receives `401` with a `WWW-Authenticate: Bearer resource_metadata=...` pointer

#### Scenario: Any test-user may use any group URL
- **WHEN** an authenticated test-user connects to a group URL
- **THEN** access is granted regardless of which group, with no per-member check
