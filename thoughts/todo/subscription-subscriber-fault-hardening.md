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

## Also, from the 3.16 callback claim (owner-decided plan, verified 2026-11-02)

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
- **A resync whose baseline fetch fails is applied as an empty baseline**
  (`handlers/callbacks.py`, the resync branch): `_fetch_and_transform_baseline`
  answers `None` for a failed fetch and for an empty response alike, and
  `AwProxy.get_resource` answers `{}` for a non-JSON 2xx and passes some
  error bodies through, so the callback cannot tell them apart; it applies
  `{}` (which changes no stored data) and moves the sequence to the resync's.
  A fix needs the proxy to report a failed fetch distinctly. (Verification
  Issue 5 of the owner-decided plan; a first fix was reverted because it
  refused legitimately empty baselines.)
- **A poll records and clears past diffs it did not apply**
  (`interface/subscription_manager.py`, `sync_subscription`): a PENDING,
  REJECTED or RESYNC_TRIGGERED result still advances `max_sequence`, so the
  poll clears the publisher past a gap. Stopping there must keep the
  baseline fallback (the poll's way out after a gap reset, when every diff
  reads as pending); a first fix that stopped there trapped a subscription
  after a gap timeout and was reverted.
- **`_fetch_and_transform_baseline` reads a baseline with a property named
  `error` as a failed fetch** (`"error" in baseline_response`, sync and async),
  and a list baseline containing the string `"error"` raises on `.get`.
  Belongs with the failed-fetch signal above.

