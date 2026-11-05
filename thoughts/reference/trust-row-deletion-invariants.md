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
delete (step 7).

| # | Step | Before the row? | On a fault | Retry reaches it by |
| --- | --- | --- | --- | --- |
| 1 | Remote DELETE to the peer (peer trusts only) | yes | a refusal or no answer is logged; with `delete_peer`, the call answers False and the row stays. A 404 counts as deleted (the peer has no row) | the row |
| 2 | Subscriptions, remote-peer store, callback state, peer profile, capabilities, peer permissions | yes | a raised `DbError` stops it, row stays. Their return values are not checked: a store that answers False instead of raising lets the row go with its data left (subscriptions are non-strict: a fault leaves orphans) | the row (when it raised) |
| 3a | Owner (the client row is in this actor's bucket, and the index names no other actor): `disable_client` (tokens, then index row, then client row; both rows confirmed) | yes | `DbError`, row stays, and the client row stays (a token store that cannot list every token raises before any row goes; an index row confirmed gone with the client row not is a failure) | the row; `client_owned_by` reads the client row and the missing index names nobody else, so the retry takes 3a again |
| 3b | Connection, including a client row the index gives to another actor: `revoke_connection_tokens` (this actor's tokens for the client; chains marked first; a bucket the first pass cannot read raises) | yes | `DbError`, row stays | the row |
| 4 | Provider tokens `oauth_tokens:<peer_id>` (OAuth2 rows) | yes | `DbError`, row stays | the row |
| 5 | Lifecycle hook `trust_deleted`, before the core delete: `DELETE /<actor>/trust/<rel>/<peer>` and `TrustManager.delete_relationship`. The sweep (step 6) uses the latter, so sibling rows fire it on every route | yes | a `DbError` propagates (503), row stays; any other hook exception is logged and the delete goes on | the row; **the hook fires again on a retry** |
| 6 | Sibling sweep: this actor's other rows of the client, each through the full route (steps 1-9 for that row). The deletes it makes skip their own sweep (`MCPClientRegistry.sweeping`, a context-local guard) | yes | `DbError` after trying every row (an exception, or a refused delete of a row still listed, counts as a fault); this row stays, and so do the siblings that faulted | the row, on every route (the one-row route retries the same peer id and sweeps again) |
| 7 | **The row** (`DbTrust.delete`) | n/a | `DbError`, row stays | the row |
| 8 | Custom permissions (shared store and its cache) | no | `DbError`; the permissions are left with no row (inert: nothing reads them without a row). The siblings are already gone (step 6) | no route. The next row created for the same peer id clears them first: `Trust.create` when no row exists (a peer's trust, approved again), `TrustManager.create_or_update_oauth_trust` for OAuth2 rows |
| 9 | MCP cache eviction (`finally`, once the row is gone) | no | cannot fault | n/a |

When the row delete returns False, the row was already gone (an earlier
row's step 6, or a peer's reciprocal DELETE). The bulk loop re-reads the
row and raises only if it is still there.

**Which rows name a client** (steps 3, 4 and 6). A row with an
`oauth_client_id` names that client; only the library's OAuth2 paths write
the field (`TrustManager.create_or_update_oauth_trust`), and no trust route
lets a peer set it. A row without it names a client by its peer id: with an
OAuth2 `established_via`, or, from before that field (3.4), only when
`trust_lookup.legacy_oauth2_row` admits it: an OAuth2-family peer-id
prefix, and no baseuri or one ending in `/<actor_id>` (so a row written
before the fqdn or protocol changed still matches). `Trust`, both legacy
arms of the sweep's `client_trusts_for_deletion` and the MCP resolver's
`find_client_trust` use that one gate.

**Scope of the rules.** They hold for the store and within one process. The
permission store's cache (`TrustPermissionStore._cache`) is per process and
has no TTL: after a delete in one worker, another worker can serve its
cached permissions for a row with the same peer id until it restarts. See
`thoughts/todo/mcp-cache-lifecycle-and-revocation.md`.

## Known residue (accepted)

- **Step 8:** permissions left behind by a fault stay until a row with the
  same peer id is created, which clears them first. They grant nothing,
  since every evaluation starts from a row. `Trust.create` reads, clears
  and creates in three calls: two creates for the same peer id racing an
  owner's permission write can clear that write. Both creates are pending
  requests for one peer; an insert-if-absent would close it.
- **Step 2:** a side store that answers False instead of raising lets the
  row go with its data left. The stores raise on a fault under the 3.16
  fault contract; a False is a reported write failure, not checked here.
- **Step 6, a deterministic error:** any exception counts as a fault, so a
  row that always fails (a bug, a malformed row) answers 503 on every
  retry, on every route, until an operator removes it. The log names the
  row ("Error deleting trust relationship <peer_id> for client ...").
- **Step 3a, a client row another actor's index names:** treated as a
  connection; the copied row in this actor's bucket stays (inert: the token
  endpoint authenticates through the index) until the actor is deleted.
- **Step 3a, a token store that never lists:** a `TokenStoreUnavailable`
  that never clears stops the owner's `Trust.delete` for good;
  `OAuth2ClientManager.delete_client` (non-strict) still deletes the
  client.
- **Step 6, actor gone:** the sweep returns without a sweep when the
  actor's row cannot be loaded. Only actor deletion reaches it, and that
  wipes the actor's trust rows itself.
- **Remote-DELETE skip:** `Actor.delete_reciprocal_trust` skips the remote
  DELETE for any row with an OAuth2-family peer-id prefix, wider than the
  origin gate above. It decides only whether a peer is notified, never what
  is deleted locally, and `is_valid_peer_id` stops a peer from creating
  such a row since 3.4.
- **Step 5:** a retry fires `trust_deleted` again. Hooks must tolerate this
  (they already must, because the protocol allows a repeated DELETE).
- **D2:** an owner deleting a client leaves other actors' connections on
  the same server. See `thoughts/todo/client-deletion-leaves-other-actors-connections.md`.
