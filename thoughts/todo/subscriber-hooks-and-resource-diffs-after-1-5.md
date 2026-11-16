# Subscribers after specification 1.5: hooks on rebuilds, and the last partial resource diffs

Filed 2026-11-15 by the codex review of `spec-1-5` Phase 3. Phase 3 made
deletes, nested writes and resyncs reach subscribers as specification 1.5
says; these paths were left as they were, each with a reason.

## What is still weak

- **A rebuild the poll runs tells no data hook.** Half closed by
  `spec-1-5` (iterations log entry 14, PR #178): a callback that runs an
  owed rebuild tells the data hooks and the legacy `subscription` hook the
  baseline once, as `"resync"`, after it settled
  (`handlers/callbacks.py`, `_tell_subscription_hooks`). The rebuild itself
  tells no hook, and `rebuild_subscription` returns the applied baseline
  (`SubscriptionSyncResult.baseline`) for a caller that does. Still silent:
  the poll's paths (`sync_subscription` running an owed rebuild, a polled
  resync marker through `_rebuild_for_marker`, `rebuild_needed`). A
  hook-only application (`auto_storage` off) never takes the marker path,
  so it loses nothing; an `auto_storage` application's hooks miss what a
  polled rebuild applied. Tell the hooks from the poll's caller the same
  way, on its loop for coroutine hooks (entry 12's attempt inside
  `rebuild_subscription` ran them off the loop and before it settled). A
  list diff's rebuild (`ProcessResult.REBUILD`) stays silent on purpose: the
  diff that arrived was told.
- **`SubscriptionManager.notify_subscribers(resource=...)`** still sends
  `{resource: blob}` to a subscription above the resource, which a receiver
  applies as the whole value. Pass `whole` (the subtarget's stored value)
  there, or document that `resource` must carry the whole value.
- **The previous value is read apart from the write.** A concurrent writer
  between the read and the write can make it stale (a key added by the other
  writer and removed by this one is not reported as gone). The same race
  exists for ordinary diffs; reading the old value from the write itself
  needs a backend that returns it.
