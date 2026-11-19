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

## What 4.0 changed (attribute-list-v2-port)

The replica is on the list core: a list diff the replica cannot apply is out
of step and the replica is rebuilt from a baseline (at most one attempt a
minute, reserved by compare-and-swap, never moving the sequence backwards,
deleting what the baseline no longer carries); an owed rebuild runs on the
next callback or `sync_subscription()`. A re-applied value-addressed diff
(`remove`, `update` with `old_item`) is a no-op; a re-applied `append` or
index diff still applies twice. A bulk resync that misses a subscriber is
recorded and re-sent by the next `request_resync()`; a quiet subscription
still waits for it.

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
  4.0 they left pending before the handlers ran (at-most-once by loss).
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
*, key)` (4.0, `thoughts/plans/2026-10-30-spanned-list-items.md` Phase 3)
stores a list item at most once per key, so a re-applied `append` diff can
use it once each diff carries a stable key (for example its sequence number
and position).

## Also, from the 4.0 callback claim (owner-decided plan, verified 2026-11-02)

- **A callback at `claimed + 1` that arrives while a claim runs waits in
  pending** (`callback_processor.py`, the gap branch): the gap branch never
  drains pending, and the gap timeout waits while the claim is live, so on a
  quiet subscription it waits for an application poll or a later callback's
  gap resync. Fix: after the winner's sequence write, re-read pending and
  drain `claimed + 1 ..` in the same delivery.
- **A sequence-write fault after the handlers ran keeps the claim**, which
  expires after `CLAIM_LEASE_SECONDS`; a later poll then runs the batch again
  (auto-storage re-applies it). Retrying the sequence write once before
  folding (above) would close most of it.
- **A poll records and clears past diffs it did not apply**
  (`interface/subscription_manager.py`, `sync_subscription`): a PENDING,
  REJECTED or RESYNC_TRIGGERED result still advances `max_sequence`, so the
  poll clears the publisher past a gap. Stopping there must keep the
  baseline fallback (the poll's way out after a gap reset, when every diff
  reads as pending); a first fix that stopped there trapped a subscription
  after a gap timeout and was reverted.
- **The pre-fetch check is a read, not a claim**
  (`CallbackProcessor.precheck()`, before a low-granularity diff is fetched):
  two deliveries of one sequence can both pass it. The second finds the diff
  gone (the first fetch deleted it) and answers 503, and a failed first
  delivery is recovered only by a resync. Closing it means claiming before the
  fetch, which moves the claim out of the handler (owner-decided plan, entry
  15).
- **The poll's upward-only sequence write reads, then writes**
  (`sync_subscription`, sync and async): a callback recording a higher
  sequence between the read and the write is overwritten. Both writers are
  the same subscriber. The fix is a conditional write ("only if lower"), which
  `DbSubscription.modify` cannot express today; the adoption plan's
  `UpdateItem` item for DynamoDB `DbSubscription.modify`
  (`thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md`) is where it
  fits.
- **A granted text value that parses as JSON is stored as what it parses
  to** (`CallbacksHandler._fetch_single_property` and the baseline's
  `_subtarget_value`: `AwProxy.get_resource` parses any body). A text
  property whose value is `[1,2]`, `42` or `true` reaches the replica as a
  list, a number or a boolean on both paths. Text that is not JSON is stored
  as text since `thoughts/plans/2026-11-17-3-16-pre-rc1-fixes.md`. One rule
  by content type (`text/plain` is text) for both paths is the fix.
- **The pending queue is bounded by count, not by bytes**
  (`CallbackProcessor._add_pending`, `max_pending`, 100 by default): the
  queue is one attribute row, and DynamoDB's row limit is 400 KB, so a few
  large queued diffs can fail the write (a 503 since the pre-validation
  plan, where it was a silent loss). A byte bound, or one row per queued
  callback. Recorded by `2026-11-16-3-16-pre-validation-fixes` (finding 33).
- **State cleanup races a delivery that is taking queued callbacks**
  (`CallbackProcessor.clear_state` against `_drain`): a subscription deleted
  while a delivery prunes the queue can have its queue row written back
  after the delete. The drain's claim reads a state row that is gone and
  ends, so no handler runs; the row is an orphan until the peer's state is
  cleared. Recorded by the same plan; not tested.
- **A queued callback whose handler faults every time blocks the queue**
  (`CallbackProcessor`, since the pre-validation plan): while the next
  callback in line is itself queued the gap timeout does not fire (a resync
  there cleared callbacks already answered), so a head that raises `DbError`
  on every drain is retried by each delivery and later callbacks queue behind
  it until the queue is full. A poll or a resync callback still recovers it.
  A bound on the attempts per queued callback, then the resync.
- **A resync is not fenced against a diff in progress, and takes no care of
  what is queued above it** (`CallbackProcessor._handle_resync[_sync]`;
  verification `2026-11-16-3-16-pre-validation-fixes`, Issue 7). A diff's
  handler that finishes after a resync landed writes its older sequence
  over the resync's (`_finish_batch`, the sequence write is unconditional).
  The resync clears the whole queue, a callback above its own sequence
  included, and does not drain what is queued after the clear. Since 4.0 a
  resume always sends a resync, so suspend, bulk write, resume, one more
  write can leave a quiet subscription without the last write until later
  traffic. Make the sequence write conditional on the claim still being
  current; prune the queue through the resync's sequence instead of
  clearing it, and drain after the resync records its sequence.
- **Duplicate diffs under a publisher sequence that is not an integer come
  back on every poll** (`SubscriptionManager._poll_subscription[_async]`,
  the duplicate-diffs path; verification
  `2026-11-17-3-16-pre-validation-fixes`, Issue 3). Since 4.0 such a
  sequence is neither recorded nor used to clear, and the hooks are not
  told, but the baseline is still fetched and applied on each poll. A
  broken or hostile publisher only; clearing up to the highest diff
  sequence fetched would end it.
