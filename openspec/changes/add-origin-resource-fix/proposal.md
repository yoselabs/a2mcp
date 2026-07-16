## Why

a2mcp advertises one fixed RFC 9728 protected-resource identifier, `<base>/mcp`, for
every group. Strict MCP clients (Claude Code SDK) require the advertised `resource` to
equal either the dialed URL or its bare origin; `<base>/mcp` is neither for a group URL
like `<base>/a2web/mcp`, so auth fails on every group, not just one. claude.ai's web
connector only works today because it matches leniently on origin. Fix now: this blocks
any strict RFC 9728/8707 client from using group URLs at all.

## What Changes

- Advertise the bare origin `<base>` as the single RFC 9728 protected resource instead
  of `<base>/mcp`, for the root AS/resource metadata AND for every group's 401
  `WWW-Authenticate` challenge and protected-resource metadata route.
- Root: `build_group_auth` calls `root_provider.get_routes(mcp_path=None)` instead of
  `mcp_path="/mcp"`, so the root provider's own resource/audience becomes bare `<base>`.
- Per group: introduce a small `RemoteAuthProvider` subclass that ignores the
  `mcp_path` FastMCP always passes internally (`"/mcp"`, tied to the literal endpoint
  path) and always advertises the bare origin instead. This is required because a2mcp
  has no way to change what FastMCP passes into that internal call without also moving
  the endpoint off `<group>/mcp`.
- **BREAKING (one-time, self-healing)**: the minted JWT audience changes from
  `<base>/mcp` to `<base>`. Every already-authorized user's stored token stops
  verifying on next call and must complete one fresh OAuth flow after this deploys.
  Not a loop, not ongoing.
- Add a regression test asserting the advertised `resource` equals the bare origin for
  an arbitrary group path, and that a strict URL-or-origin match passes against it.
- Update `docs/design/fastmcp-quirks.md`: the existing "one shared AS + N resources is
  not expressible" framing (SS1) needs a caveat that resource *advertisement* can differ
  from mint *audience* (this change relies on exactly that gap); note the incidental
  fix to the `/authorize` RFC 8707 `resource=` exact-match rejection for group URLs, and
  the pre-existing (still harmless) nested dead well-known-route copy under each group's
  own mounted app.

## Capabilities

### New Capabilities
- `oauth-resource-discovery`: what RFC 9728 protected-resource identity a2mcp advertises
  (root metadata, per-group 401 challenge, per-group metadata route), and how it relates
  to (but stays decoupled from) the single shared mint/verify audience.

### Modified Capabilities
(none — `access-groups`, defined in the still-open `add-access-groups` change, has not
been archived into `openspec/specs/` yet, so there is no existing spec to delta against.
This change only touches auth/discovery behavior, not group scoping semantics.)

## Impact

- `src/a2mcp/auth.py`: `build_group_auth` (root `get_routes` call, new provider
  subclass, per-group provider construction).
- `docs/design/fastmcp-quirks.md`: SS1/SS2 amendments, one new note.
- Test suite: new/updated auth tests covering advertised resource + origin-match
  assertions.
- Deployment: homelab operators should expect one round of re-auth for existing
  Google-OAuth sessions after this ships (not a code change on their side).
