## Context

`build_group_auth` (`src/a2mcp/auth.py:143-183`) wires one shared Google `OAuthProxy` at
root plus a `RemoteAuthProvider` per group that delegates token verification to it
(design D2/A, documented in `docs/design/fastmcp-quirks.md` SS1). Two independent things
are computed from a `mcp_path` argument, and today they're accidentally coupled to the
same value with the wrong effect:

- **Mint/verify audience** (enforced): set once via `root_provider.get_routes(mcp_path=
  "/mcp")`, which calls `OAuthProxy.set_mcp_path` and bakes `audience=<base>/mcp` into a
  `JWTIssuer`. Every group's `RemoteAuthProvider.verify_token` delegates straight to this
  ONE `root_provider` instance — group identity never enters the audience check. This is
  already internally consistent today; the "one shared AS at root + N distinct RFC 9728
  resources" trap that SS1 warns about (re-auth loop) does not apply here, because
  nothing about advertised resource identity feeds back into verification.
- **Advertised resource** (cosmetic: RFC 9728 metadata + 401 `WWW-Authenticate`): FastMCP
  internally calls `group_provider.get_routes(mcp_path=streamable_http_path)` when
  building each group's own `http_app()` (`fastmcp/server/http.py:535`), and
  `streamable_http_path` is always `"/mcp"` — it's also the literal endpoint path, so
  a2mcp cannot vary it without moving the URL off `<group>/mcp`. The base
  `AuthProvider._get_resource_url(path)` (`fastmcp/server/auth/auth.py:343`)
  unconditionally appends any truthy `path` to `resource_base_url`. Since every group's
  `RemoteAuthProvider` is constructed with `resource_base_url=base` (bare), this always
  yields `base + "/mcp"` — identical for every group, and not equal to the group's own
  URL or the origin. That mismatch is the literal reported bug.

## Goals / Non-Goals

**Goals:**
- Make the advertised RFC 9728 `resource` equal to the bare origin `<base>`, for root
  metadata and for every group's 401 challenge / metadata route, satisfying strict
  clients' "URL-or-origin" check against any group URL.
- Keep the v1 one-AS/one-resource/one-redirect-URI model intact (no per-group resources,
  no new redirect URIs, no second audience).
- Keep mint audience == verify audience (already true today; must stay true).

**Non-Goals:**
- Per-group resource/audience isolation (that's design B in the quirks doc: separate
  `base_url=<base>/<group>` per group, out of scope here).
- Changing the actual MCP endpoint mount paths (`<base>/<group>/mcp` stays as-is).
- Fixing the pre-existing nested dead well-known-route copy (harmless, documented, not
  touched).

## Decisions

**D1: Root resource/audience moves to bare origin via `mcp_path=None`.**
Change `root_provider.get_routes(mcp_path="/mcp")` to `mcp_path=None`. `_get_resource_url`
treats a falsy path as "no suffix", so this alone fixes root's own resource AND (since
`OAuthProxy.set_mcp_path` derives the `JWTIssuer` audience from the same computation)
the minted/verified audience, in one call. Alternative considered: pass `mcp_path=""`
instead of `None` — behaviorally identical (`if path:` treats both as falsy); `None` is
clearer at the call site about intent.

**D2: Per-group provider overrides `_get_resource_url` to ignore FastMCP's `mcp_path`.**
FastMCP always calls the group's own provider with `mcp_path="/mcp"` internally (tied to
the real endpoint path) — a2mcp cannot change or intercept that argument through public
constructor options. Introduce a small subclass:

```python
class _OriginResourceAuthProvider(RemoteAuthProvider):
    """Advertises the bare resource_base_url regardless of the mcp_path FastMCP passes.

    FastMCP always calls get_routes(mcp_path="/mcp") internally (mcp_path doubles as the
    literal endpoint path, which a2mcp cannot vary without moving the URL). Overriding
    _get_resource_url is the only seam that lets resource ADVERTISEMENT diverge from
    that fixed value while leaving ENFORCEMENT (delegated to the shared root_provider,
    untouched by this class) exactly as it is today.
    """

    def _get_resource_url(self, path: str | None = None) -> AnyHttpUrl | None:
        return self.resource_base_url or self.base_url
```

Use this subclass instead of plain `RemoteAuthProvider` when constructing each group's
provider in `build_group_auth`. Alternatives considered:
- *Monkeypatching `get_routes` per instance*: works but less discoverable/testable than
  a named subclass; rejected.
- *Passing `resource_base_url` differently per call*: doesn't help — the bug is that
  `path` gets appended at all, not what it's appended to.
- *Changing FastMCP's `streamable_http_path`*: would move the actual endpoint URL
  (`<group>/mcp` -> something else), breaking the deployed URL contract; rejected.

**D3: No change to `RemoteAuthProvider.verify_token` or the shared `root_provider`
delegation.** Verification is untouched; only what's advertised changes. This is what
keeps constraint "mint audience == verify audience" trivially true — both are still one
value, owned by one instance, unaffected by D2.

## Risks / Trade-offs

- **[Risk] Changing the minted audience string invalidates every already-issued token**
  → **Mitigation**: this is inherent to fixing the bug (the audience string must
  change), affects each user exactly once, and self-heals via the existing OAuth flow
  (401 -> re-auth -> new token with new audience). Call out in the proposal/changelog;
  no code-level mitigation needed since the store already treats tokens as ordinary
  bearer credentials with no special migration path.
- **[Risk] A stale/cached deployment mixes an old-audience root_provider with a
  new-code group provider (rolling deploy)** → **Mitigation**: both live in the same
  process/image; there is no partial-deploy scenario for a single a2mcp instance. Note
  for the homelab operator: bump the whole image atomically (already the deploy model,
  digest-pinned).
- **[Risk] `/authorize`'s exact-normalized `resource=` match could regress for some
  in-flight client mid-migration** → **Mitigation**: the match becomes MORE permissive
  after this change (bare origin vs a path-suffixed value), not less; no client that
  worked before can start failing at `/authorize` because of this specific change.
- **[Trade-off] Every group now advertises an identical resource identifier** → this was
  already true before the fix (`<base>/mcp` for all groups); no new trade-off introduced,
  just a different shared value. URL-as-capability security posture (documented in
  auth.py's `GroupAuth` docstring) is unchanged: any authenticated test-user can still
  reach any group URL, per-group resource identity was never meant to enforce anything.

## Migration Plan

1. Land the code change (D1 + D2) behind normal review/tests, no feature flag needed
   (single fixed behavior, no per-deployment variance).
2. Cut a new digest-pinned image (per repo convention: `docs/README` GHCR flow).
3. Bump the pinned digest in the homelab consumer repo (`platform/mcp-gateway`).
4. On deploy, expect and communicate one round of forced re-auth for existing sessions.
5. Rollback: revert the digest pin; old image mints/verifies the old (buggy but
   internally-consistent) `<base>/mcp` audience again, so rollback is a plain digest
   revert with no data migration either direction (DiskStore token entries under the old
   audience are simply orphaned, not corrupted, and get evicted/ignored normally).

## Open Questions

- None blocking. One naming choice left to `tasks.md`/implementation: exact placement of
  `_OriginResourceAuthProvider` (co-located in `auth.py` next to `GroupAuth`, matching
  existing file organization).
