# Capability: gateway

## ADDED Requirements

### Requirement: Config-driven backends, no code per server

The gateway SHALL derive its entire behaviour from a checked-in `mcp-gateway.yaml`
declaring an auth provider and a set of endpoints, each composing one or more remote MCP
backends. Adding, removing, or regrouping a backend SHALL require only a config edit and
restart, not a code change. A malformed config SHALL fail loudly at startup.

#### Scenario: a backend is added by config only

- WHEN a backend entry is added to `mcp-gateway.yaml` and the gateway restarts
- THEN that backend's tools are served under its endpoint
- AND no gateway source code changed

#### Scenario: bad config fails fast

- WHEN the config is malformed or references an unreachable required field
- THEN the gateway refuses to start with a clear error, rather than serving a broken surface

### Requirement: Google-federated DCR OAuth in front of the backends

The gateway SHALL present a spec-compliant MCP OAuth surface (RFC 9728 discovery plus
RFC 7591 DCR plus PKCE) federated to the operator's Google OAuth app, with GCP
test-users as the identity gate. Unauthenticated requests SHALL be challenged, not
served.

#### Scenario: a client connects via DCR and a Google login

- WHEN an MCP client with no prior registration connects to an endpoint
- THEN it can dynamically register, complete a Google login, and (as a test-user) call the backend tools

#### Scenario: unauthenticated request is challenged

- WHEN a request arrives without a valid token
- THEN the gateway returns 401 plus discovery metadata and serves no tools

### Requirement: Backend credential isolation

A backend's own credential SHALL never be present in the gateway. The gateway SHALL hold
only its Google client secret and whatever is needed to REACH each backend over the
private network.

#### Scenario: backend token stays in the backend

- WHEN the gateway fronts a backend that holds its own upstream token
- THEN that token does not appear in the gateway's environment or config
- AND the backend is reached only over the private network

### Requirement: Telemetry and health

The gateway SHALL emit per-tool-call OpenTelemetry spans to a configured OTLP endpoint
and SHALL expose `/health` reflecting per-backend reachability synthesized from an
`initialize` -> `tools/list` handshake, without a hung backend wedging the gateway.

#### Scenario: a tool call is traced

- WHEN a client invokes a backend tool
- THEN a span identifying the backend and tool is exported to the OTLP endpoint

#### Scenario: a down backend is visible and non-blocking

- WHEN a backend stops answering the health handshake
- THEN `/health` reports it down/flaky
- AND other endpoints keep serving
