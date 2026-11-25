# Per-name grant editing, grant cleanup and a remote-copy listing

**Filed:** 2026-11-25, by the A2A research
(`thoughts/research/2026-11-24-a2a-actor-interface.md`, owner decision 10).
Not part of the A2A plans; A2A needs none of it.

The library stores and evaluates per-relationship grants (the trust type's
defaults plus the override row in `trust_permissions`), but the only editing
call replaces a whole category (`store_permissions`, `update_permissions`).
A consumer that grants or revokes one name has to read the row, edit
`patterns` or `excluded_patterns` itself and write the category back, and it
needs one code path per starting model:

- **starts with everything** (a pattern such as `memory_*`): revoke by adding
  an exclusion
- **starts with nothing**: grant by adding a pattern

One consumer (Emm, `../actingweb_mcp`) carries all of this itself:
`api/trust.py:276-563` (per relationship) and `api/memory_types.py:333-513`
(one name across relationships).

## What would move into the library

All of it stays inside one actor, so the mini-app model holds.

1. **Per-name editing:** grant a name to a peer, revoke it, grant all and
   revoke all. Each is stated against the final result, and the library
   chooses which list to edit, so both starting models use the same call.
   The permission callback to the peer is sent as it is today.
2. **Who can see a name:** for one name, the relationships whose final
   grant admits it, built from the override rows and the evaluator.
3. **Grant cleanup when data or a subscription is deleted.** Only the library
   sees every create and delete. A grant naming a deleted list applies again
   when a list of the same name is created. The cleanup goes beside the
   cleanup on trust delete (`delete_reciprocal_trust`, `actor.py`). The
   consumer does this today when its lists are created or deleted and when a
   subscription is deleted.
4. **A listing of a peer's synchronised copies with their sync time.** It
   would be a method on `RemotePeerStore`. Today the consumer reaches under
   it, building an `AttributeListStore` from `store.bucket` to read
   `updated_at` (`repositories/peer_helpers.py:89-160`).
5. **The peer's stored grant, described as reconciliation only.** These pieces
   promise an access filter nobody uses:
   - `has_property_access` has no callers
   - `apply_permission_data` is never called
   - the `sync_peer` docstring is wrong
   - `peer_permissions_caching` is ignored

   Document them, or deprecate them first. Removing a documented name is a
   major release (`CONTRIBUTING.rst`).

## What stays with the application

- **Which peers count as sharing**, for example a relationship and a peer
  type.
- **Who may see a synchronised copy.** One consumer admits an MCP client to a
  peer's copy by that client's access to the local name. That is a policy for
  the actor's own clients, not a rule for third parties.
- **Subscribing when a trust is approved.** One call already does it.

## Decided, not to reopen

- No check of the publisher's grant before a copy is shown onwards: the
  protocol states no terms for passing data on.
- The revocation default stays: a copy is kept unless the application opts
  into `auto_delete_on_revocation`.

Both are owner decisions of 2026-11-25, in the research note.

Additive, so a minor release. It needs `/plan_feature`, and a spec delta
against the trust-permissions capability.
