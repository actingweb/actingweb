# Subscription subscriber: recover cleanly from a store fault

**Filed from** `thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-4.md`
(C4, E4) and the owner's decision of 2026-10-29: the publisher side was made
spec-conformant in plan entry 32 of
`thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md`;
the subscriber side kept its behaviour (entry 33 only corrected comments)
and is this todo.

## The spec's line

`docs/protocol/actingweb-spec.rst`, "Callback Delivery Semantics": callbacks
are at-most-once, the publisher does not retry, and a subscriber that sees a
gap recovers by polling (RECOMMENDED) or a resync. Idempotent handlers and a
periodic backup poll are listed only as guidance "for stronger delivery
guarantees". Everything below goes beyond the minimum; none of it is a spec
violation today.

## What is still weak

- **A handler that faulted part-way is applied twice.** The 503 on a storage
  fault in the handler (`callback_processor.py`, both twins) leaves the diff
  on the publisher; the next poll or gap resync re-applies it. Auto-storage
  re-applies key by key (`remote_storage.py` `apply_callback_data`), and a
  list `append` there is not idempotent, so the part written before the fault
  is written again.
- **Callbacks that finished before the fault are not recorded.** When one
  callback in a drained batch faults, `last_seq` is not advanced for the ones
  before it, so they run again too.
- **A quiet subscription stalls.** After a sequence-write fault is folded
  (D3), the gap timeout is checked only when a later callback arrives
  (`callback_processor.py` gap check), so a subscription with no next change
  waits indefinitely. The resync handlers (`_handle_resync_sync`,
  `_handle_resync`) call `_update_last_seq` unwrapped after the handler ran,
  so they keep D3's shape and answer 503 after work that ran.
- **A drained entry can run twice when two writes fault** (verification
  `thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-6.md`,
  G6). After the handlers ran, a folded `_update_last_seq` fault is followed
  by `_prune_pending`; if that faults too, `last_seq` is stale and the
  drained entries stay pending, so a later drain applies them again. Before
  3.16 they left pending before the handlers ran (at-most-once by loss).
- **Two error rules for one callback.** The consumer data hooks fold their
  errors (`handlers/callbacks.py`); the legacy callback hooks re-raise through
  `hooks.py`. State one rule in the hook docs.

## Options

- Idempotent re-application: key each applied diff by `(subscription,
  sequence)` and skip one already applied, or make auto-storage's list
  operations carry the diff's sequence.
- Record `last_seq` per callback as it completes, not once per batch.
- A backup poll: a bounded `sync_subscription` when a subscription has had a
  gap pending longer than the gap timeout, triggered from the next request
  that touches the actor or from an application timer.
- Retry the sequence write once before folding, and apply the D3 fold in
  both resync handlers.

## Why it waits

The spec does not require it, the failure needs a store fault mid-callback,
and the fix touches the delivery model (idempotency keys) rather than one
site. The library side of the key now exists: `ListProperty.append_once(item,
*, key)` (3.16, `thoughts/plans/2026-10-30-spanned-list-items.md` Phase 3)
stores a list item at most once per key, so a re-applied `append` diff can
use it once each diff carries a stable key (for example its sequence number
and position).
