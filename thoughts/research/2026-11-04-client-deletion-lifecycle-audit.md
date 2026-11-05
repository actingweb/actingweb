# Research: OAuth2/MCP client deletion and client-trust lifecycle audit

**Date:** 2026-11-04
**Branch:** release/3.16.0-dependency-security
**Commit:** ec62ca6
**Origin:** four verification rounds of
`thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md` kept
finding edge defects in client deletion. On 2026-11-04 the owner chose to
stop iterating and audit the lifecycle as a design instead.

Method: a read-only code audit (no tests run). I re-checked the two High
findings against the code by hand; the lines are cited below. Anything not
traced is marked unverified. Paths are relative to `actingweb/`.

## Research Questions

1. **Which paths delete a client or a client trust row, in what order, and
   can a retry finish each?** No HTTP route deletes a client directly.
   Clients are deleted by `OAuth2ClientManager.delete_client` (SDK), by the
   `Trust.delete` cascade and by actor deletion or adoption. The trust UI
   deletes a trust row, which cascades. See [Entry points](#entry-points).
2. **Can a row shape authorise without being deletable?** No, not on the
   actor being deleted: deletion's arms 1 and 2 are the resolver's. The
   gaps are scope (one actor per call) and the cascade. See
   [Shapes](#peer-id-shapes).
3. **What can a deleted client's leftovers still authorise?** At most an
   hour of full access when both the token revocation and a trust row
   delete fail, or when the row sits on another actor. See
   [Leftovers](#leftover-authorisation).
4. **Do the hooks fire?** `trust_deleted` fires through `config._hooks`
   even from the registry. This corrects the verification's suspicion.
   Its payload and timing differ by path, and there is no client-deleted
   hook. See [Hooks](#hooks).

## Entry points

| Entry | Order of side effects | What a fault leaves; retry |
| --- | --- | --- |
| `DELETE /<id>/trust/<rel>/<peer>` (`handlers/trust.py:886-1041`) | hook → `delete_reciprocal_trust` (`actor.py:2003-2223`): subscriptions, custom permissions (`:2102-2114`), peer stores, trust row (`:2216-2220`) → `Trust.delete` cascade `registry.delete_client(cid, actor_id=<this actor>)` (`trust.py:161-176`) → cache eviction | A cascade fault is folded (`trust.py:174`) and the route answers 204. Its retry answers 404, so only the SDK can finish. |
| `OAuth2ClientManager.delete_client` (`interface/oauth_client_manager.py:156-200`) | ownership check → revoke this actor's tokens (`client_registry.py:362-375`, a listing fault is logged and passed) → client row, then index row, each confirmed (`:384-389`) → every trust row of the client on this actor (`:591-677`), each cascading back in | A trust fault answers 503. The retry's not-found path sweeps the leftover rows (Iteration 15) but answers False. If only the index row went, the client row is never deleted (D9). |
| Actor deletion (`deletion_finish.py:51-244`) | tombstone → hook → generation bump → revoke all tokens → index rows of owned clients → `Actor.delete`, whose trust deletes cascade into full `delete_client` calls | Resumable from the tombstone, but the cascades act globally (D1) |
| Adoption clean (`oauth2.py:3042-3086`) | bump → revoke → purge relationships (cascades) → `_delete_actor_clients` | Next sign-in retries; same D1 effect |
| `ActorInterface.delete()` / `Actor.delete()` | as `Actor.delete` above, without the finisher | Index rows of owned clients are left; only `actingweb-deletions` finishes them |

## Peer-id shapes

| Shape | Written by | Authorised | Deleted | Cascades |
| --- | --- | --- | --- | --- |
| A `oauth2_client:mcp_x:mcp_x`, tagged | registration; on the owner's actor, or on **`OAUTH2_SYSTEM_ACTOR`** for `/oauth/register` (`oauth2_server.py:96-104`) | arm 1 | arm 1 | yes |
| B `oauth2_client:<email>:mcp_x`, tagged | MCP authorize callback, on the **user's** actor (`oauth2_server.py:390,403-424`) | arm 1 | arm 1 | yes |
| C1 `oauth2_client:<n>:<n>`, untagged legacy | older client-credentials code | arm 2 | arm 2 | yes |
| C2 `oauth2:<n>:<n>`, untagged legacy | older code | arm 2 | arm 2 | **no** (`trust.py:195-221`: neither the prefix nor `type` matches) |
| D `<source>:<email>:<cid>`, untagged legacy | older interactive flow | no | arm 3, exactly 3 segments | `oauth2_client:` prefix only |

Client ids are always `mcp_<hex>` (`client_registry.py:93`). Two-segment
`oauth2_client:<email>` rows have no current writer.

## Leftover authorisation

- Validating an MCP access token never checks that its client exists
  (`token_manager.py:296-332`); the request is authorised only if a trust
  row is found, and MCP fails closed without one (`handlers/mcp.py:1160-1181`).
- Other processes may keep serving a cached token for up to 300 s
  (`mcp.py:117`). This is documented.
- Tokens not revoked on `TokenStoreUnavailable`
  (`client_registry.py:366-375`) plus a surviving trust row give full
  access until the token expires (at most 1 h, `token_manager.py:80`).
- Refresh and code grants stop as soon as the client row or its index row
  is gone (`load_client_strict`, `oauth2_server.py:529,613-615`).
- Client deletion bumps no session generation, unlike actor deletion and
  adoption, so a refresh racing the revocation sweep can mint a pair that
  survives it (D8).
- The provider token response, including Google's refresh token, is stored
  at `store["oauth_tokens:<peer_id>"]` (`trust_manager.py:643-656`) and is
  never deleted with the trust or the client (D7).

## Hooks

- `trust_deleted` fires through `config._hooks`
  (`interface/actor_interface.py:77-82`, set by `ActingWebApp.get_config`,
  `interface/app.py:1498,1505`).
- The trust handler passes `trust_data` and `initiated_by_peer`.
  `TrustManager.delete_relationship` passes neither.
- `Actor.delete` fires no hook for the primary rows, but its cascades fire
  it for sibling rows while the actor is being wiped.
- Hooks fire before the delete, so a fault and its retry fire them twice.
- There is no client-deleted hook.

## Defects

**High**

- **D1. Deleting one actor's connection disables the client for every
  actor.** Checked by hand:
  - The cascade passes the trust's own actor
    (`trust.py:169`: "`registry.delete_client(oauth2_client_id, actor_id=self.actor_id)`").
  - `delete_client` keeps the caller's actor (`client_registry.py:338`:
    "`if not actor_id and client_data:`") and never compares it with
    `client_data["actor_id"]`.
  - It confirm-deletes a client row that is absent from that actor's
    bucket (gone counts as deleted), then deletes the **global** index row
    (`:387-389`).
  - `/oauth/register` puts the client on the system actor
    (`oauth2_server.py:96-104`), and `/oauth/authorize` checks only that
    the client exists and the redirect URI matches (`:161-166`).

  So any user who authorizes a client and then disconnects it, deletes
  their actor or is adopted disables the client's token grants for every
  other user. An attacker who knows a victim client's id can do this on
  purpose: authorize it as themselves, then delete their own row.
  Unverified: whether deployed MCP clients share one registration across
  users (claude.ai, Claude Code).
- **D2. Deleting a client leaves its connections on every other actor.**
  Revocation (`client_registry.py:364`) and the trust sweep (`:625`) cover
  only the actor they are given. Another user's shape-B row and tokens
  survive: up to an hour of full access, then a permanent row with its
  permissions. Nothing records which actors authorized a client, so no
  retry can find them.

**Medium**

- **D3.** Two faults (token listing, then a trust row) leave up to an hour
  of full access, and only an SDK retry finishes the deletion.
- **D4.** The trust UI answers 204 while the cascade has failed and the
  client is still live (`trust.py:174`, `actor.py:2220`,
  `handlers/trust.py:1041`).
- **D5.** Deleting a C2 `oauth2:` row deletes only the trust, not the
  client, its index row or its tokens. The cascade parses the peer id
  instead of reading `oauth_client_id`.
- **D6.** Custom permissions are deleted before the trust row
  (`actor.py:2102-2114` before `:2216-2220`). A fault in between leaves a
  row on the trust type's defaults, which can be wider than the custom
  permissions were.
- **D7.** Provider tokens, including Google's refresh token, are kept after
  disconnect (`trust_manager.py:647-656`).
- **D8.** No generation fence on client deletion.

**Low**

- **D9.** A half-deleted client (only the index row gone) is never
  finished.
- **D10.** A retry that finished the sweep answers False, the same as a
  client that never existed.
- **D11.** On DynamoDB, trust `modify` is a whole-item PutItem
  (`db/dynamodb/trust.py:314-317`), which can recreate a row deleted
  between the load and the save. PostgreSQL's UPDATE cannot.
- **D12.** Hook payloads and timing differ by path.
- **D13.** The cascade re-enters `delete_client` once per row, and in actor
  deletion every nested call logs "missing from global index". Shape-A and
  client rows accumulate on the system actor with no expiry for
  dynamically registered clients. `is_oauth2_trust` omits
  `oauth2_interactive`.

**Adjacent, unverified:** a confidential client from `/oauth/register` can
use `client_credentials`, which mints tokens for `client_data["actor_id"]`,
the system actor (`oauth2_server.py:661-682`), with a `trust_type` taken
from the registration body (`client_registry.py:105,564`). Check what the
MCP handler then serves.

## Design options

1. **Separate deleting a connection from deleting a client.** This is the
   fix for D1 and D5. Deleting a trust row revokes that actor's tokens for
   the client and removes that actor's rows only. The client, its index
   row and other actors' state are deleted only by the owner
   (`client_data["actor_id"]`), or when its last connection goes, if that
   is the chosen policy. `Trust.delete` routes by `oauth_client_id`, not by
   parsing the peer id.
2. **Record each connection.** Write an index row per (client, actor) at
   authorize time, so that deleting a client can reach every actor (D2).
3. **One ordered, idempotent routine with a durable intent.** A tombstone
   under the system actor, reusing the lease and resume pattern of
   `deletion_finish.py`, with these steps:
   1. Delete the index row, which disables the client.
   2. Bump a per-client fence (D8).
   3. Revoke tokens on every connected actor.
   4. Delete the trust rows, then their permissions (fixes D6).
   5. Delete the provider-token entries (D7) and the client row.
   6. Fire one client-deleted hook, then mark the intent done.

   Each step is then safe to stop at and resumable by any retry or an
   operator command (D3, D9, D10).
4. **Make DynamoDB trust `modify` conditional** on `attribute_exists`
   (D11), and have the authorize callback re-check that the client exists
   before it writes its row.
