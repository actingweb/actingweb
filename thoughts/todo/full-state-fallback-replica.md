# The full-state fallback corrupts a subscriber's replica

**Found** 2026-11-07 by the first recording of wire row `WD12`
(`tests/integration/wire/WD12.*.json`, both backends, both topologies),
`thoughts/plans/2026-11-06-peer-authorisation-fixes.md` Phase 0.

## What the recording shows

A publisher that believes its subscriber lacks `subscriptionresync` (the trust
row's cached `aw_supported`) answers a `resume()` with the fallback in
`actingweb/actor.py:3494-3530`: it stores the full state as a diff and sends a
low-granularity callback, with no `type`. The subscriber fetches it and applies
it as an ordinary diff:

- a list's full state is an `extend` (`actor.py:3500`), so the items the
  subscriber already holds are appended again (`WD12`: `notes` holds `{"n": 1}`
  twice);
- a scalar's full state is the stored string (`"y": "{\"v\": 2}"`), so the
  replica stores `{"value": "{\"v\": 2}"}` where a normal diff stores the
  object `{"v": 2}`;
- a property deleted while suspended is not mentioned, so the subscriber keeps
  it if it had it.

A 3.16 library always advertises `subscriptionresync`, so the fallback is
reached only for a peer on an older library or with a stale capability cache
(the row's capabilities are cached for `CAPABILITIES_TTL_HOURS`).

Related, same day: a read of a replica list during a resync rewrite raises
`IndexError` (`remote_storage.py:151`, `RemotePeerStore.get_list` iterating
while the rewrite removes items); seen from a test's poll under parallel load.

## Options

- Mark the fallback callback as a resync (`type: resync` with the diff URL),
  and have the subscriber replace rather than apply: needs the subscriber side
  to accept a resync whose data is fetched from a diff URL.
- Send the full state with replace semantics (a list `replace` operation, the
  scalar decoded), so an older subscriber applying it as a diff ends right.
- Drop the fallback: every supported version advertises resync.

Whichever is chosen, `WD12`'s recording changes; `rows.toml` must name the
phase that owns it. The `ListAttribute` plan
(`thoughts/plans/2026-11-06-attribute-list-v2-port.md`) rewrites the replica's
list application and is the natural owner of the list half.
