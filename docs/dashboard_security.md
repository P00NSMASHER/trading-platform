# Local dashboard security

The private dashboard remains loopback-only and research-only.

## Per-launch authentication

Every dashboard process generates two distinct high-entropy secrets in memory: a one-time bootstrap token and a separate session token.

- The runtime prints an authenticated bootstrap URL containing the bootstrap token.
- The bootstrap token is accepted exactly once. A replay of the same URL cannot mint another session.
- Opening that URL sets an `HttpOnly; SameSite=Strict` cookie containing the separate session token and immediately redirects to a clean URL without either token.
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
- state-changing requests: 30/minute per client address;
- concurrent accepted connections: 16;
- per-socket read timeout: 5 seconds.

The concurrent-connection semaphore is acquired before a handler thread is created. Excess connections receive a minimal 503 response and are closed, preventing an unbounded local thread fan-out. Socket timeouts limit slow-client occupancy.

The existing CSRF token remains required for POST review/export actions in addition to the authenticated session cookie.

## Remaining assumptions

Loopback authentication reduces exposure to other local processes and users but is not a substitute for operating-system account security. Keep the local workstation account, private runtime directory, and evidence exports access-controlled.
