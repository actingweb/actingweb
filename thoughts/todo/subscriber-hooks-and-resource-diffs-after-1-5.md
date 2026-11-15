# Subscribers after specification 1.5: hooks on rebuilds, and the last partial resource diffs

Filed 2026-11-15 by the codex review of `spec-1-5` Phase 3. Phase 3 made
deletes, nested writes and resyncs reach subscribers as specification 1.5
says; these paths were left as they were, each with a reason.

## What is still weak

- **A rebuild runs no data hook.** `rebuild_subscription` (and the owed
  rebuild the callback handler now runs first, and a polled resync marker,
  which hands off to it) applies the baseline and sweeps, but the
  application's `subscription_data_hook` is not called with the baseline, as
  a pushed resync's hook is. A hook-only application (`auto_storage` off)
  never takes the marker path, so it loses nothing; an `auto_storage`
  application's hooks miss what the rebuild applied. Run the hooks once
  with the baseline as `callback_type="resync"` after a successful rebuild.
- **`POST /properties` passes no previous value.** A resource subscriber
  whose resource went with its parent because of a POST (not a PUT) is not
  told. The POST applies its keys one by one inside `_apply_post_params`;
  the previous values would have to be read before the apply pass, for the
  names that have a resource-level subscriber.
- **`SubscriptionManager.notify_subscribers(resource=...)`** still sends
  `{resource: blob}` to a subscription above the resource, which a receiver
  applies as the whole value. Pass `whole` (the subtarget's stored value)
  there, or document that `resource` must carry the whole value.
- **The previous value is read apart from the write.** A concurrent writer
  between the read and the write can make it stale (a key added by the other
  writer and removed by this one is not reported as gone). The same race
  exists for ordinary diffs; reading the old value from the write itself
  needs a backend that returns it.
