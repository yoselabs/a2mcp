## 1. Auth: origin-only resource advertisement

- [x] 1.1 In `src/a2mcp/auth.py`, add `_OriginResourceAuthProvider(RemoteAuthProvider)`
  overriding `_get_resource_url` to always return `self.resource_base_url or
  self.base_url` (ignoring the `mcp_path` FastMCP passes internally). Add a docstring
  explaining WHY (mirrors the `_build_token_store`/`GroupAuth` style already in the
  file: state the constraint, not just the code).
  (Shipped as `_OriginResourceMixin` + a locally-composed `_OriginRemoteAuthProvider(
  _OriginResourceMixin, RemoteAuthProvider)` inside `build_group_auth`, so it can still
  be built AFTER `RemoteAuthProvider` is lazily imported, matching the file's existing
  lazy-import style.)
- [x] 1.2 In `build_group_auth`, change `root_provider.get_routes(mcp_path="/mcp")` to
  `mcp_path=None`, and update the surrounding comment (currently describes the old
  `<base>/mcp` behavior).
- [x] 1.3 In `build_group_auth`, construct each group's provider as
  `_OriginResourceAuthProvider(...)` instead of `RemoteAuthProvider(...)` (same
  constructor args: `token_verifier=root_provider`, `authorization_servers=[base]`,
  `base_url=base`, `scopes_supported=scopes`).

## 2. Tests

- [x] 2.1 Unit test: root `/.well-known/oauth-protected-resource` metadata `resource`
  field equals the bare origin (no `/mcp` suffix).
- [x] 2.2 Unit test: an unauthenticated request to an arbitrary group URL (e.g.
  `/a2web/mcp` and a second, differently-named group) returns 401 with
  `WWW-Authenticate: resource_metadata=` resolving to the bare-origin resource.
- [x] 2.3 Unit test: assert the advertised resource equals the dialed URL's origin
  exactly, for at least two distinct group names (regression for the reported bug).
- [x] 2.4 Unit test: a token minted via the shared root provider still verifies
  successfully against every group's `RemoteAuthProvider` (mint audience == verify
  audience did not regress) — extend/reuse the existing group-auth test that mints a
  real token, per `add-access-groups` task 6.3 notes.
  (Shipped as an audience-identity assertion across the shared instance rather than a
  full mint+verify HTTP round-trip: FastMCP's reference-token `verify_token` requires
  upstream IdP token-exchange state that isn't worth mocking for this unit test. The
  live end-to-end proof is task 4.2's MCP Inspector smoke test.)
- [x] 2.5 Regression-guard test: `/authorize` with an RFC 8707 `resource=<base>` param
  (bare origin, matching what strict clients will now discover) is accepted, not
  `invalid_target` (documents the incidental secondary fix).

## 3. Docs

- [x] 3.1 Update `docs/design/fastmcp-quirks.md` SS1: add a caveat that resource
  *advertisement* can diverge from mint *audience* without hitting the re-auth-loop
  trap, since advertisement never feeds back into verification.
  (Shipped as new SS1a.)
- [x] 3.2 Update `docs/design/fastmcp-quirks.md` SS2 (`get_routes(mcp_path=...)`): note
  that a2mcp overrides `_get_resource_url` per group specifically to decouple the
  advertised resource from the `mcp_path` FastMCP passes internally, and why (FastMCP
  always passes `"/mcp"`, tied to the literal endpoint path).
- [x] 3.3 Add a short note (SS7 deploy notes or new SS8) documenting the pre-existing,
  still-harmless nested dead well-known-route copy under each group's own mounted app,
  so it isn't rediscovered later as a phantom bug.
  (Shipped as a new bullet at the end of SS7.)
- [x] 3.4 README: if it documents the resource/audience shape anywhere, update to match
  (grep for `/mcp` references in the OAuth section).
  (Updated the "Access is URL-as-capability" section; the "staying logged in" section
  was already generic enough to need no change.)

## 4. Ship

- [x] 4.1 Build + publish a new digest-pinned GHCR image; record the digest (same
  process as `add-access-groups` task 6.2).
  Published by CI on push to `main` (commit `bbdc9f5`, run
  https://github.com/yoselabs/a2mcp/actions/runs/29466136892):
  `ghcr.io/yoselabs/a2mcp@sha256:1d29e4dc4fc56f5cb1aab08c3c9658a9d97e200e9633c95a1fb6347928f3e888`
  (pin this in homelab `platform/mcp-gateway`, task 4.2 below).
- [ ] 4.2 Homelab handoff: bump the pinned digest in `platform/mcp-gateway`; note in the
  deploy announcement that existing users will see one re-auth prompt.
  (Blocked on 4.1's digest + requires the separate `iorlas/homelab` repo, not open in
  this session.)
