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
both the AS and the single protected resource (`<base>/mcp`). Each group server delegates
token verification to that SAME instance via `RemoteAuthProvider` (no second audience, no
per-group AS routes). Audience is consistent by construction; every group accepts a token
minted at login. Per-group audience isolation, if ever needed, is design B: give each group
its own `base_url=<base>/<group>` (a full self-contained AS) and register one Google redirect
URI per group -- a single Google OAuth client accepts many redirect URIs.

## 2. `get_routes(mcp_path=...)` shapes the resource path AND audience

`get_routes(mcp_path="/mcp")` / `get_well_known_routes(mcp_path="/mcp")`:
- keeps the AS flow routes at the app root (`/authorize`, `/token`, `/register`,
  `/auth/callback`, `/.well-known/oauth-authorization-server`);
- serves the protected-resource metadata at `/.well-known/oauth-protected-resource/mcp`
  (the `mcp_path` is appended after the `resource_base_url` path);
- sets the issuer audience to `<resource_base_url>/mcp`.

A group server's own `http_app()` internally calls `get_routes(mcp_path="/mcp")`, so its 401
`WWW-Authenticate` points at `<base>/.well-known/oauth-protected-resource/mcp` (origin root,
absolute) regardless of the group mount path. a2mcp mounts the ONE root provider's routes
with the matching `mcp_path="/mcp"` so that pointer resolves.

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
