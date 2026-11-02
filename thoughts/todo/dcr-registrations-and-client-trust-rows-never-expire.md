# Dynamic client registrations and their system-actor trust rows never expire

Every `POST /oauth/register` writes a client record, an index row and a trust
row that nothing ever deletes. (The per-registration walk of the actor's trust
list is gone in 3.16: it only built a log string, the peer id was already known.)

**Where.** `MCPClientRegistry.register_client`
(`actingweb/oauth2_server/client_registry.py`) stores `created_at` and no TTL;
`_store_client` and `_update_global_index` write without `ttl_seconds`. Removing
a connector in claude.ai or ChatGPT sends nothing to the server, so the records
stay.

**What the 2026-11-01 research found** (the design this item needs starts from
it; `thoughts/research/2026-11-01-single-mode-and-consumer-primitives.md`):

- There are **two trust rows** per registration (one under the system actor,
  one under the user's actor once authorization completes), and only one is
  read by user-token authentication. A TTL on one does not retire the other.
- Neither backend gives a trust row a TTL, so an expiry needs a sweep or a new
  column; the client index bucket and the client record can carry
  `ttl_seconds`.
- Token **rotation writes nothing keyed by client**, so `last_used_at` has to
  be stamped from the token endpoint on purpose.
- The PostgreSQL purge covers a fixed list of token buckets, not the client
  buckets; `delete_expired` answers 0 on a fault on both backends, and DynamoDB
  TTL enablement is unchecked at startup (see "Making `delete_expired` raise" in
  the plan's "What We're NOT Doing").
- **`/authorize` is lenient and `/token` is strict** about an unknown or expired
  client; an expiry rule must say which side rejects, or a connector that
  completes authorization then fails at the token endpoint.
- Client ID Metadata Documents (CIMD) remove the need for most registrations, so
  the expiry design and the CIMD decision should be taken together.

**What the consumer saw live** (not reproduced here): one claude.ai connect
creates two registrations, each with a trust row, and only the second is
used; the Connections page shows both.

**What a fix needs.** A retention decision first: registrations that never
completed an authorization (no code ever issued) can carry a short TTL from
the start; registrations with live tokens cannot expire while the tokens do.
Then the mechanics: a `last_used_at` on the client record stamped from the
token endpoint, a TTL on the never-authorized ones, and a sweep in
`cleanup_expired_tokens` (`token_manager.py:1119`, scheduled-only by its own
warning) for the rest. The trust row goes with its registration
(`revoke_client_tokens` and the client-delete path already pair them). The
per-registration list walk is separate and cheap to fix: the trust row's
peer id is known before the walk.

**Provenance.** Filed 2026-09-25 from the triage of the consumer's connector
audit, `thoughts/research/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`
(report 3, item 5). Reported by the `actingweb_mcp` project on 2026-09-21
out of its `thoughts/plans/2026-09-17-claude-connector-directory-submission.md`.
