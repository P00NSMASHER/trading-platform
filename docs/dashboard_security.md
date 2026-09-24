# Local dashboard security

The private dashboard remains loopback-only and research-only.

## Per-launch authentication

Every dashboard process generates a new high-entropy access token in memory.

- The runtime prints an authenticated bootstrap URL containing the token.
- Opening that URL sets an `HttpOnly; SameSite=Strict` session cookie and immediately redirects to a clean URL without the token.
- The token is not written to the database, runtime config, release manifest, or audit files.
- Raw request-line logging is disabled so the bootstrap query token is not echoed by `BaseHTTPRequestHandler`.
- Restarting the dashboard invalidates the previous token because a new token is generated.

The dashboard uses plain HTTP because it binds only to loopback. The cookie is therefore intentionally not marked `Secure`; a Secure cookie would not be sent over the local HTTP endpoint.

`/healthz` remains unauthenticated because it contains no case/model data and is used by local runtime checks. It is still Host-checked and rate-limited.

## Request controls

Default limits:

- request body: 16 KiB;
- request URI: 4 KiB;
- all requests: 240/minute per client address;
- state-changing requests: 30/minute per client address.

The existing CSRF token remains required for POST review/export actions in addition to the authenticated session cookie.

## Remaining assumptions

Loopback authentication reduces exposure to other local processes and users but is not a substitute for operating-system account security. Keep the local workstation account, private runtime directory, and evidence exports access-controlled.
