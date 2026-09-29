# Logout can race a refresh rotation and leave a live pair

Found by the 3.15.1 verification
(`thoughts/verifications/2026-09-29-logout-does-not-revoke-refresh-chain.md`,
issue I1). Rated Medium by the owner; not fixed in 3.15.1.

`OAuth2SessionManager.revoke_session` reads the presented row and then
`revoke_token_chain` runs `delete_by_chain` over the two SPA token buckets. A
refresh that consumed the old refresh token just before the sweep mints its
successors afterwards (`oauth2_spa.py`, `_generate_actingweb_token` then
`create_refresh_token`, both with the same `chain_id`). Those rows are written
after the sweep has passed, so logout answers success for a chain that still
has a working access and refresh token. The window is milliseconds and needs
the client (or a thief) to refresh at the moment of logout; the theft response
has the same shape. The tests run revoke and refresh one after the other.

Two fix shapes, not evaluated against each other:

- After minting, the rotation re-checks the chain's anchor (the consumed
  refresh row, or a chain-revoked marker) and deletes what it minted when the
  chain was revoked meanwhile.
- `revoke_token_chain` sweeps twice (a second `delete_by_chain` after the
  first) and reports a fault when the second still deletes rows.

A marker row would also serve the DynamoDB growth path (a GSI on `chain_id`).
Needs a test that interleaves the two operations on the fault-injecting double
(`chain_delete_hook` is the shape).
