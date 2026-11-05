# Deleting a trust row: steps, faults and retries

How one trust row is deleted (`Actor.delete_reciprocal_trust` → `Trust.delete`),
what each step leaves behind when it faults, and how a retry reaches it.
Every change to this path is checked against the two rules below, and
`TestTrustDeletionConverges` in `tests/integration/test_trust_oauth_integration.py` holds them for each step.
The table is updated in the same change as the code.

## The rules

1. **A fault never ends in success.** A step that cannot confirm its work
   raises `DbError` (503 through the integrations), never a 204 or `True`.
2. **A raise leaves a retry handle.** After a `DbError`, retrying through
   the same route finishes the job. Either the row is still there, or what
   is left behind grants nothing and is reachable some other way (the
   "Retry reaches it by" column). When the retries succeed, nothing that
   authorises this connection is left. For an owner that includes the
   client; for any other actor, its tokens and rows.

"The route" means three things:
- **One row:** `DELETE /<actor>/trust/<rel>/<peer>` or
  `TrustManager.delete_relationship`. Once the row is gone, it answers 404.
- **Every row:** `Actor.delete`, `purge_relationships` or
  `delete_all_relationships`, which re-read the actor's rows on each call.
- **A client:** `OAuth2ClientManager.delete_client`. Its not-found path
  ends the actor's connection.

## Order, per row

The second column says whether a step runs before or after the row
delete (step 6).

| # | Step | Before the row? | On a fault | Retry reaches it by |
| --- | --- | --- | --- | --- |
| 1 | Remote DELETE to the peer (peer trusts only) | yes | logged as a refusal; with `delete_peer`, the call answers False and the row stays | the row |
| 2 | Subscriptions, remote-peer store, callback state, peer profile, capabilities, peer permissions | yes | `DbError`, row stays (subscriptions are non-strict: a fault leaves orphans) | the row |
| 3a | Owner: `disable_client` (tokens, client row, index row) | yes | `DbError`, row and client stay | the row (the retry then takes 3b, since the client is gone) |
| 3b | Connection: `revoke_connection_tokens` (this actor's tokens for the client; chains marked first) | yes | `DbError`, row stays | the row |
| 4 | Provider tokens `oauth_tokens:<peer_id>` (OAuth2 rows) | yes | `DbError`, row stays | the row |
| 5 | Lifecycle hook `trust_deleted` (one-row route, before the core delete) | yes | as the hook does | the row; **the hook fires again on a retry** |
| 6 | **The row** (`DbTrust.delete`) | n/a | `DbError`, row stays | the row |
| 7 | Custom permissions (shared store and its cache) | no | `DbError`; the permissions are left with no row (inert: nothing reads them without a row) | no route. A new OAuth2 row with the same peer id clears them first (`TrustManager.create_or_update_oauth_trust`) |
| 8 | Sibling sweep: this actor's other rows of the client | no | `DbError` after trying every row; the rows that faulted stay. For an owner they are inert (the client is gone); for a connection they are token-less, but they still authorise a new login (step 3b ran for every row) | each leftover row, in the trust list, through any route |
| 9 | MCP cache eviction (`finally`, once the row is gone) | no | cannot fault | n/a |

When the row delete returns False, the row was already gone (an earlier
row's step 8, or a peer's reciprocal DELETE). The bulk loop re-reads the
row and raises only if it is still there.

## Known residue (accepted)

- **Step 7:** permissions left behind by a fault stay until a row with the
  same peer id is created. They grant nothing, since every evaluation
  starts from a row.
- **Step 5:** a retry fires `trust_deleted` again. Hooks must tolerate this
  (they already must, because the protocol allows a repeated DELETE).
- **D2:** an owner deleting a client leaves other actors' connections on
  the same server. See `thoughts/todo/client-deletion-leaves-other-actors-connections.md`.
