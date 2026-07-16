## ADDED Requirements

### Requirement: Advertised RFC 9728 resource is the bare origin
The gateway SHALL advertise the bare origin `<base>` (scheme + host, no path) as the
single RFC 9728 protected-resource identifier, for the root authorization-server
metadata and for every group's protected-resource metadata and 401 `WWW-Authenticate`
challenge, regardless of which group URL was dialed.

#### Scenario: Root protected-resource metadata reports the bare origin
- **WHEN** a client fetches `GET /.well-known/oauth-protected-resource`
- **THEN** the response's `resource` field equals the bare origin `<base>` exactly (no
  trailing path segment)

#### Scenario: Any group's 401 challenge points at the bare-origin resource
- **WHEN** an unauthenticated client sends a request to any group MCP endpoint (e.g.
  `POST /a2web/mcp` or `POST /all/mcp`)
- **THEN** the response is 401 with a `WWW-Authenticate` header whose
  `resource_metadata` URL resolves to protected-resource metadata whose `resource`
  field equals the bare origin `<base>`

#### Scenario: Strict URL-or-origin match succeeds for an arbitrary group path
- **WHEN** a strict RFC 9728/8707 client compares the advertised `resource` against the
  origin of the group URL it dialed (e.g. `<base>/some-group/mcp`)
- **THEN** the comparison succeeds because the advertised `resource` equals that URL's
  origin exactly, for any group name

### Requirement: Advertised resource stays decoupled from the enforced mint/verify audience
Changing what resource is advertised SHALL NOT change how tokens are minted or
verified: one shared authorization-server instance SHALL remain the sole owner of the
audience used for both minting and verification, and a token valid for one group SHALL
remain valid for every group (the existing URL-as-capability posture).

#### Scenario: A token minted via one group's OAuth flow authorizes calls on another group
- **WHEN** a user completes the OAuth flow reached via one group's 401 challenge
- **THEN** the resulting token is accepted for `tools/call` (and other MCP operations)
  on every other group's URL, exactly as before this change

#### Scenario: Mint and verify audiences never diverge
- **WHEN** the gateway boots and constructs the shared authorization server plus each
  group's delegating verifier
- **THEN** the audience value used to mint tokens and the audience value used to verify
  them are the same value, sourced from the same provider instance
