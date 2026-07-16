# FastMCP 3.4.3 quirks (a2mcp)

Non-obvious behaviours of FastMCP `>=3.2,<4` that a2mcp depends on or works around.
Retained because they are invisible in the code and expensive to rediscover. Re-verify on
any FastMCP upgrade.

## 1. `OAuthProxy` is single-resource, single-audience by construction (the big one)

`OAuthProxy.set_mcp_path()` builds a `JWTIssuer(audience=str(self._resource_url))`
(`fastmcp/server/auth/oauth_proxy/proxy.py`), and verification does a **strict equality**
check on the `aud` claim. One provider instance = one fixed audience.

**Consequence:** "one shared AS at root + N distinct RFC 9728 protected resources
(`/.well-known/oauth-protected-resource/<group>/mcp`)" is **NOT expressible**. A shared AS
mints `aud=<base>/mcp`; a per-group resource verifies `aud=<base>/<group>/mcp`; the token is
rejected, the client gets 401, re-runs discovery, and **loops through re-auth forever** (the
"authorize too often" trap). `/authorize` also rejects a spec-compliant client's RFC 8707
`resource=<base>/<group>/mcp` with `invalid_target` (exact-normalized match against the
provider's one resource; `_normalize_resource_url` strips trailing slash + query, no prefix
match). claude.ai currently omits the `resource` param so it dodges this, but MCP Inspector
and the 2025-06-18 MCP auth spec do not -- do not build on that.

**What a2mcp does (design A, `auth.py::build_group_auth`):** ONE `GoogleProvider` at root is
both the AS and the single protected resource (`<base>`, the bare origin -- see SS1a).
Each group server delegates token verification to that SAME instance via
`RemoteAuthProvider` (no second audience, no per-group AS routes). Audience is consistent
by construction; every group accepts a token minted at login. Per-group audience isolation,
if ever needed, is design B: give each group its own `base_url=<base>/<group>` (a full
self-contained AS) and register one Google redirect URI per group -- a single Google OAuth
client accepts many redirect URIs.

### 1a. Advertised resource can diverge from mint audience -- this is SAFE, not the trap above

The single-audience trap above is about *enforcement*: one AS instance must mint and verify
the same `aud`. It says nothing about what gets *advertised* in RFC 9728 metadata / the 401
`WWW-Authenticate` header -- that's a separate, cosmetic computation
(`AuthProvider._get_resource_url`), and every group's `RemoteAuthProvider.verify_token` just
delegates straight to the one shared `root_provider` instance regardless of what its own
metadata route advertises. Concretely: a2mcp overrides `_get_resource_url` on each group's
provider (`_OriginResourceMixin` / `_OriginRemoteAuthProvider`) to always advertise the bare
origin `<base>`, ignoring the `mcp_path="/mcp"` FastMCP always passes internally when
building that group's own `http_app()` (`mcp_path` doubles as the literal streamable-HTTP
endpoint path, so a2mcp can't just pass a different value there without moving the URL off
`<group>/mcp`). This closes the strict-client bug where `<base>/mcp` matched neither a group
URL nor its origin (RFC 9728/8707 "URL-or-origin" check; e.g. Claude Code SDK), without
touching enforcement at all -- mint audience and verify audience stay the single value set
once by `root_provider.get_routes(mcp_path=None)`.

## 2. `get_routes(mcp_path=...)` shapes the resource path AND audience

`get_routes(mcp_path="/mcp")` / `get_well_known_routes(mcp_path="/mcp")`:
- keeps the AS flow routes at the app root (`/authorize`, `/token`, `/register`,
  `/auth/callback`, `/.well-known/oauth-authorization-server`);
- serves the protected-resource metadata at `/.well-known/oauth-protected-resource/mcp`
  (the `mcp_path` is appended after the `resource_base_url` path, UNLESS `mcp_path` is
  falsy -- `None` or `""` -- in which case no suffix is appended at all: see below);
- sets the issuer audience to `<resource_base_url>/mcp` (or bare `<resource_base_url>` for
  a falsy `mcp_path`).

A group server's own `http_app()` internally ALWAYS calls `get_routes(mcp_path="/mcp")`
(FastMCP hardcodes this to the literal streamable-HTTP endpoint path; a2mcp cannot pass a
different value here without moving the group's URL off `<group>/mcp`). a2mcp's root call
passes `mcp_path=None` instead (SS1a), so its own resource/audience is the bare origin, and
each group's provider overrides `_get_resource_url` to ignore the `"/mcp"` FastMCP hands it
and always return the bare origin too -- otherwise the group's OWN advertised resource would
drift back to `<base>/mcp` regardless of what the root call above does. Root's explicitly
mounted metadata route and every group's (overridden) advertised resource now agree by
construction, both resolving to `<base>/.well-known/oauth-protected-resource` (no suffix).

## 3. `jwt_issuer` is lazily initialised

`provider.jwt_issuer` raises `RuntimeError("JWT issuer not initialized. Ensure get_routes()
is called before token operations.")` until `get_routes()` has run. Any test that mints/reads
tokens must call `get_routes()` first.

## 4. `RemoteAuthProvider.get_routes()` reads `token_verifier.scopes_supported`

`GoogleProvider` exposes no `scopes_supported` attribute, so building a group's `http_app()`
with a `RemoteAuthProvider(token_verifier=<GoogleProvider>)` raises `AttributeError` unless
you pass `scopes_supported=[...]` explicitly to the `RemoteAuthProvider` (it then skips the
delegate lookup). a2mcp passes the configured Google scopes.

## 5. `mount(namespace=...)` prefixing differs per primitive kind

For a backend mounted under `namespace="ha"`:
- tools/prompts: name becomes `ha_<name>` (prefix `<backend>_`);
- resources: uri becomes `<scheme>://ha/<rest>` (backend inserted as the authority);
- resource templates: the attribute is `uri_template` (snake_case), NOT `uriTemplate`.

`GroupScopeMiddleware` resolves the owning backend by prefix (longest-name-first) and
unprefixes before glob-matching, so a glob for one backend can never match another's
primitive.

## 6. Filtered-primitive rejection surfaces differently client-side

Raising `ToolError`/`ResourceError`/`PromptError` in middleware is what the SERVER raises; a
FastMCP `Client` sees a `ToolError` for `tools/call` but a generic `mcp.shared.exceptions.
McpError` for `resources/read` and `prompts/get`. Tests assert accordingly.

## 7. Deploy notes (bit us / would bite in prod)

- Mounted group `http_app()`s each have their own lifespan; the parent app must enter every
  child lifespan (a2mcp uses an `AsyncExitStack` in the parent lifespan).
- MCP endpoints slash-redirect: `POST /consumer/mcp` (no slash) 307s to `/consumer/mcp/`;
  some clients mishandle the redirected POST. Test both.
- Run uvicorn with `proxy_headers=True` / `forwarded_allow_ips="*"` behind the reverse proxy
  so the public https scheme (consent-cookie `Secure`, OAuth redirect URLs) stays correct.
- The OAuth token store (`FileTreeStore` at `A2MCP_OAUTH_CACHE_DIR`) MUST be a persistent
  volume, and `A2MCP_JWT_SIGNING_KEY` MUST be stable, or clients reauthorize on every restart.
- Each group's own `RemoteAuthProvider.get_routes()` (called internally by FastMCP while
  building that group's `http_app()`) self-registers its OWN copy of the well-known
  protected-resource route, nested inside that group's mounted Starlette app -- e.g.
  reachable at `/<group>/.well-known/oauth-protected-resource`, NOT just at the true origin
  root. This is harmless and pre-existing (true before and after SS1a/SS2's origin-only
  fix): clients never hit it because the absolute URL FastMCP puts in the 401
  `WWW-Authenticate` header always points at root's own explicitly-mounted copy. Don't
  "fix" this as a phantom bug if rediscovered; it's dead but inert.
