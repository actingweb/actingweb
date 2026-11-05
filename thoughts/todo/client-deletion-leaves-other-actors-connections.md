# Deleting a client leaves other local actors' connections to it

When the owner of an SDK-created client deletes it
(`OAuth2ClientManager.delete_client`), the client's tokens and trust rows
on **other** actors of the same server stay.
- Their access tokens keep working for up to an hour, because validation
  never checks that the client exists (`token_manager.py`
  `validate_access_token`).
- Their rows stay listed but inert: refresh and code grants fail once the
  client row is gone.

**Scope, checked against the protocol (2026-11-04):** a client's
connections are always on the server whose registry issued its id. The
authorize callback resolves the user in this server's own store, and
OAuth2 trusts have no remote counterpart. Nothing crosses servers. After
the D1 fix, dynamically registered clients have no deleter, so this
concerns SDK-created clients only. The full record is in Iteration 19 of
`thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md` and D2 of
`thoughts/research/2026-11-04-client-deletion-lifecycle-audit.md`.

**Options:**
1. Token validation checks that the client still exists. This adds one
   load per uncached validation (the cache lasts 300 s), and that load can
   fault.
2. Write a (client → actors) index at authorize time, so that deleting a
   client revokes every connection and removes the inert rows.

Option 1 closes the hour without new state. Option 2 also cleans up the
rows. Decide whether SDK clients are ever authorized by actors other than
their owner in practice (`actingweb_mcp`) before choosing.
