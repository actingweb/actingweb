# Dynamic client registrations and their system-actor trust rows never expire

Every `POST /oauth/register` writes a client record and a trust row that
nothing ever deletes, and registration itself lists every trust row the
actor has.

**Where.** `MCPClientRegistry.register_client`
(`actingweb/oauth2_server/client_registry.py:61-71`) stores `created_at` and
no TTL; `_store_client` (`:300-311`) and `_update_global_index` (`:565-574`)
write without `ttl_seconds`. `_create_client_trust_relationship` walks
`actor_interface.trust.relationships` to find the row it just created
(`:462-465`), a full list per registration. Removing a connector in claude.ai
or ChatGPT sends nothing to the server, so the records stay.

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
