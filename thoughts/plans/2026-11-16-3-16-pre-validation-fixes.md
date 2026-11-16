---
status: done
approved: 2026-11-16 by Greger Wedel
---

# Implementation Plan: the fixes 3.16 takes before its release validation

**Date:** 2026-11-16
**Research:** none as a document. The six todos this plan closes were each
verified when filed; three read-only passes re-checked them against `master`
at `e928e5b` on 2026-11-16, and what they changed is under "What the checks
changed" below.
**Branch:** `release/3.16.0-pre-validation-fixes` (one PR; one commit per
phase, Phase 2's preceded by a `rows.toml`-only ownership commit; the
branch's first commit, `6635c2c`, is the todo index after #178)

## Overview

Six open todos are either gaps 3.16 itself creates, breaking changes that
belong in a minor, or things the release validation would trip over. This
plan closes them so that `3-16-release-validation` is the last plan before
`3.16.0rc1` and reads a library that is not about to change under it. The
order in `thoughts/todo/INDEX.md` ("Planned for 3.16") gains this plan as
5b, before plan 6.

## What the checks changed

- **The low-granularity race is a receiver bug at every granularity**
  (code reading, not yet reproduced). A callback N+1 that arrives while N
  holds the claim is queued as pending (`callback_processor.py:713-762`);
  N's delivery read the pending queue before it claimed (`:783-789`) and
  never reads it again, so nothing drains N+1. It recovers only when a later
  callback arrives after `gap_timeout_seconds`, or on a poll.
- **The pending queue is an unguarded read-modify-write row**
  (`_add_pending` `:619-631`, `_prune_pending` `:639-642`): one writer and
  one pruner can lose an entry, as two writers can.
- **The "PostgreSQL" concurrency test never touches PostgreSQL.** Its config
  comes from `tests/_adoption_helpers.py:34` (`database="dynamodb"`), and a
  keyword wins over the environment. The claim is right (the handler ran
  once); the test pins one of two safe answers on a 0.2 s sleep. PostgreSQL's
  claim (`db/postgresql/attribute.py:671`, `:585`) has no concurrency test.
- **3.15.1 advertises `subscriptionresync`**, as every version since 3.10.0
  does. The full-state fallback is reached only with a fresh capability
  cache that lacks the tag: a pre-3.10 or non-library peer, or a 200 with an
  odd body. An empty or expired cache already means "send a resync"
  (`actor.py:5112-5116`). A pre-3.10 receiver has no replica: it hands the
  body to the application's hook (`v3.9.2 callbacks.py:163-171`). All of the
  todo's remaining defects are still in the code, the single-property crash
  included.
- **Specification 1.5 describes the fallback**
  (`docs/protocol/actingweb-spec.rst:4068-4072`, "To a subscriber that does
  not advertise the tag, the publisher instead sends the full subscribed
  state as ordinary diffs"; also `:301`, `:306`, `:343`, `:348`, `:3321`,
  `:3480`, `:3794`, `:4375`).
- **The library's trust page already links to the new-trust form**
  (`aw-actor-www-trust.html:9`, since July). The demo ships its own
  `aw-actor-www-trust.html` and `aw-actor-www-root.html` without the link,
  which is what the browser walk saw. Neither dashboard links to the form.
- **The poll never tells the legacy `subscription` hook**, for ordinary
  polled diffs either (`subscription_manager.py` has no
  `execute_callback_hooks` call).
- **The new-trust handler sees one failure, not several**: every peer-side
  cause is `return False` in `actor.py` (`:2323`, `:2336`, `:2345`, `:2365`,
  `:2398`), and an existing trust returns a row like a new one.

## Decisions Made

- **`CallbackOauthHandler` is removed** (owner, 2026-11-16) - routed by
  neither integration; a tombstone `ImportError` names the migration guide,
  as `FanOutManager`'s does.
- **The full-state fallback is dropped; a resume always sends a resync
  callback** (owner, 2026-11-16) - it removes four defects and the code that
  holds them; only a pre-3.10 or non-library subscriber notices, and it
  already gets a resync whenever the cache is empty or expired.
- **Specification 1.5 is reworded to match** (owner, 2026-11-16) - 1.5 is
  not released: a publisher MAY send a resync to any subscriber, a
  subscriber that does not know the type re-reads on its own schedule, and
  the full state as ordinary diffs stays a form a publisher MAY use; the
  library does not.
- **The pending race: reproduce, then fix** (owner, 2026-11-16) - a
  deterministic test is written first; if it does not fail as the reading
  predicts, the claim-loop change stops and the finding is reported.
- **The new-trust form answers a failure with a message and an empty form**
  (owner, 2026-11-16, after the security review) - the redirect carries a
  code only; nothing from a request is rendered, so a link from another
  site cannot prefill the form.
- **A poll that rebuilt the replica from a baseline tells the data hooks
  once, as `"resync"`** - [Updated 2026-11-16, owner, after implementation:
  not a quiet poll. With nothing to fetch the poll refreshes the replica
  from a baseline every time, and a consumer's hook that notifies its UI on
  `"resync"` would do so on every poll.] One rule for the poll paths that
  rebuild (owed, marker, out of step, diffs fetched and none applied); the
  exception is a rebuild after a list diff the same poll already told, as on
  the pushed path. The poll tells the legacy `subscription` hook nothing
  today, and this plan does not start.
- **`notify_subscribers(resource=...)` sends the stored whole value for
  `properties`; for another target the docs say `resource` data must be the
  whole value** - the library has no store to read for an application's own
  target.
- **Pending-queue writes are compare-and-swap** - the drain makes a writer
  race a pruner on every delivery; the attribute store's conditional write
  (`_cas_state` uses it) guards the row, with a re-read and retry.
- **One message code for every peer-side failure of the new-trust form** -
  separate codes would let the form probe hosts (unreachable, not an actor,
  refused); local validation keeps its own codes.
- **`supports_resync_callbacks()` stays** - it is documented consumer API
  (`docs/guides/subscriptions.rst:419`); only what the resume alone used
  goes.
- **The default OAuth2 `redirect_uri` becomes `/oauth/callback`** (owner,
  2026-11-16, during Phase 3) - the old default `/oauth` does not handle
  the callback (it starts the sign-in again).
- **The concurrency test follows the run's backend** through a
  `database=` keyword on `make_config`, whose other 55 importers keep
  DynamoDB.

## What We're NOT Doing

- The previous value read apart from the write (third bullet of
  `subscriber-hooks-and-resource-diffs-after-1-5.md`) - needs a backend that
  returns the old value from the write; the file stays, trimmed to it.
- Telling the legacy `subscription` hook from the poll - no poll path does;
  a separate decision about that hook's future.
- Keeping the new-trust form's input after a failure - the safe carriers (a
  cookie, a same-origin check) are more code than three short fields are
  worth before a release candidate.
- Naming why a trust could not be created - `actor.py` returns `False` for
  every cause; a reason is a change to the trust API.
- A size limit on a diff that carries a whole value, and back-off or
  breakers for outbound callbacks (`outbound-callback-backpressure.md`) -
  additive, optional in specification 1.5; the docs point at
  `request_resync` for a large change.
- A byte bound on the pending queue (`max_pending` counts entries;
  DynamoDB's row limit is 400 KB) and state cleanup racing a drain's prune
  after a subscription is deleted - existing behaviour; recorded in
  `subscription-subscriber-fault-hardening.md`.
- A resync whose send fails on a running loop with nobody waiting - nothing
  records it today either (`actor.py:5295`); Phase 2 pins the behaviour in a
  test and the docs keep saying which deployments wait.
- Replacing the demo's own trust and dashboard templates with the library's
  - the demo's styling is its own; this plan adds the same links and labels
  to both.
- Splitting the trust page and the handler removal into a later PR
  (suggested by the outside voice) - owner decided on 2026-11-16 that the
  validation is the last thing before rc1, so they land before it.

## What Already Exists

- `actingweb/handlers/callbacks.py:971-1025` `_tell_subscription_hooks` and
  `SubscriptionSyncResult.baseline` - the callback's rebuild already tells
  the hooks; the poll reuses `run_subscription_data_hooks` with the guard
  its four ordinary call sites use.
- `actingweb/callback_processor.py` `_cas_state`, `_claim`,
  `_release_claim` - the claim and its compare-and-swap; the pending row
  gets the same conditional write.
- `actingweb/actor.py` `register_diffs(whole=..., previous=...)` - the
  property handlers pass the stored value
  (`handlers/properties.py:1796-1801`); `previous` is already a callable
  resolved only when a subscriber needs it.
- `actingweb/actor.py:5167` the resync send, and `resync_marker` for peers
  without an endpoint and `none` subscriptions - what remains after the
  fallback goes.
- `actingweb/config.py:60-66` `FANOUT_REMOVED`, `actingweb/fanout.py:9-11`,
  `tests/test_subscription_processing.py:86` - the tombstone pattern and its
  test.
- `actingweb/handlers/www.py:846` the `error` template variable of
  `aw-actor-www-trust-new.html:10` (it carries a configuration error today);
  `peer_approved` is already in the rows passed as `trusts` (`www.py:818`).
- `tests/integration/test_callback_delivery_shapes.py` the two-write test,
  an `xfail` today; `tests/integration/test_callback_processor_concurrency.py`.

## Acceptance Criteria

- **AC-1** - When callback N+1 arrives while N is being processed, on the
  sync path, both handlers run, in order, each once, and the stored pending
  queue is empty, with no further callback or poll.
- **AC-2** - The same on the async path.
- **AC-3** - Two simultaneous low-granularity writes to a publisher with
  four subscribers reach every replica within the test's wait.
- **AC-4** - Two concurrent deliveries of one callback run the handler once
  and answer `processed` and `in_progress`, on every run, on the backend the
  run is configured for.
- **AC-5** - A resume sends a callback of type `resync` to a subscriber with
  a callback endpoint whose cached capabilities lack `subscriptionresync`.
- **AC-6** - A resume of a subscription to one property (a subtarget) sends
  its resync and records it; nothing raises and the resume is not lost.
- **AC-7** - `notify_subscribers("properties", data, subtarget=s,
  resource=r)` sends a subscriber at target or subtarget level the whole
  stored value of `s`, less what its grant excludes.
- **AC-8** - A poll that replaced the replica from a baseline calls the
  data hooks once with the baseline, the recorded sequence and `"resync"`.
  [Updated 2026-11-16, owner: a poll that rebuilt it; a quiet poll, with
  nothing to fetch, calls no hook.]
- **AC-9** - A poll whose rebuild did not settle calls no data hook.
- **AC-10** - On the async poll, a coroutine data hook is scheduled on the
  caller's loop and runs there.
- **AC-11** - `import actingweb.handlers.callback_oauth` raises an
  `ImportError` that names `docs/migration/v3.16.rst`.
- **AC-12** - The trust list shows, per row, the state of both sides: a row
  both sides approved, a row waiting on the peer and a row waiting on this
  actor each read differently.
- **AC-13** - The dashboard and the trust list each link to the new-trust
  form, in the library's templates and the demo's.
- **AC-14** - A new-trust submit that fails returns to the form (a 302, on
  both integrations) with the message for its code.
- **AC-15** - A new-trust submit for a peer that already has a trust returns
  to the list with a notice saying so. [Updated 2026-11-16: "already has"
  is a trust this actor approved; with the same relationship it is paired
  again, as before the plan, and the notice says that; with another,
  nothing changes and the notice says that.]
- **AC-16** - Nothing from the query string is rendered on the form or the
  list: a known code shows the library's fixed text, an unknown code shows
  nothing, and any other parameter is ignored.
- **AC-17** (added in plan: the pending row's race) - A pending entry
  written while another delivery prunes the queue is still in the queue
  afterwards.

## Traceability

| AC | Phase | Test | Status |
| --- | --- | --- | --- |
| AC-1 | 1 | `tests/test_callback_pending_drain.py::test_a_callback_queued_behind_a_live_claim_is_processed_sync` (two cases: queued before and after N's sequence write) | Passing |
| AC-2 | 1 | `tests/test_callback_pending_drain.py::test_a_callback_queued_behind_a_live_claim_is_processed_async` (the same two cases) | Passing |
| AC-3 | 1 | `tests/integration/test_callback_delivery_shapes.py::test_two_simultaneous_low_granularity_writes_reach_every_replica` (the `xfail` removed) | Passing |
| AC-4 | 1 | `tests/integration/test_callback_processor_concurrency.py::test_two_concurrent_deliveries_run_the_handler_once` (event-gated, run's backend) | Passing |
| AC-17 | 1 | `tests/test_callback_pending_drain.py::test_a_queue_write_during_a_prune_is_kept` | Passing |
| AC-5 | 2 | `tests/test_resume_always_resyncs.py::test_a_peer_cached_without_resync_is_sent_a_resync`; wire row `WD12` (`test_wd12_resume_to_a_peer_cached_without_resync`) | Passing |
| AC-6 | 2 | `tests/test_resume_always_resyncs.py::test_a_single_property_subscription_resumes` | Passing |
| AC-7 | 2 | `tests/test_notify_subscribers_whole_value.py::test_a_resource_notification_sends_the_whole_stored_value` (real store; target-level and subtarget-level subscribers; a grant that excludes a sibling key) | Passing |
| AC-8 | 2 | `tests/test_replica_rebuild.py::test_a_poll_that_replaced_the_replica_tells_the_data_hooks` (parametrised: owed, marker, out of step, none applied; sync and async); `::test_a_quiet_poll_tells_no_hook` | Passing |
| AC-9 | 2 | `tests/test_replica_rebuild.py::test_a_polled_rebuild_that_did_not_settle_tells_no_hook` | Passing |
| AC-10 | 2 | `tests/test_replica_rebuild.py::test_the_async_poll_runs_a_coroutine_hook_on_its_loop` (the hook records its running loop; the test drains the task and compares by identity) | Passing |
| AC-11 | 3 | `tests/test_subscription_processing.py::test_the_removed_callback_oauth_module_raises_its_pointer` | Passing |
| AC-12 | 3 | `tests/test_www_trust_pages.py::test_the_trust_list_shows_both_sides` (one row per state of the matrix); browser walk | Passing |
| AC-13 | 3 | `tests/test_www_trust_pages.py::test_the_new_trust_form_is_linked`; `tests/test_demo_example.py::test_the_demo_trust_templates_render` | Passing |
| AC-14 | 3 | `tests/test_www_trust_pages.py::test_a_failed_new_trust_returns_to_the_form`, `::test_a_peer_side_failure_has_one_message`, `::test_an_unexpected_error_shows_nothing_of_itself` (Flask and FastAPI); browser walk | Passing |
| AC-15 | 3 | `tests/test_www_trust_pages.py::test_an_existing_trust_is_paired_again_and_says_so`, `::test_an_existing_trust_with_another_relationship_returns_a_notice` | Passing |
| AC-16 | 3 | `tests/test_www_trust_pages.py::test_nothing_from_the_query_string_is_rendered` (unknown code; `peer_url`, `trust_type` and markup as parameters) | Passing |

## Spec Delta

This repository keeps no living specs (`thoughts/README.md` lists no
`specs/`); `docs/` carries the behaviour, and each phase names its pages.
The protocol specification changes in Phase 2, by the owner's decision
above: the passages at `docs/protocol/actingweb-spec.rst:301`, `:306`,
`:343`, `:348`, `:3321`, `:3480`, `:3794`, `:4068-4072` and `:4375` are
reworded so that a publisher MAY send a resync to any subscriber and MAY
send the full state as ordinary diffs to one that does not advertise the
tag, and the 1.5 changelog entry at `:348` no longer says "Added".

## Phase 1: the receiver keeps every callback

### Changes

- `actingweb/callback_processor.py`, `process_callback` and
  `process_callback_sync`, by these rules:
  1. **After queueing, one re-check.** A delivery that queued its callback
     reads the state row and the sequence once more. If its callback has
     become the next one and no claim is live, it claims and processes it;
     if it loses that claim it answers as a queued callback does today. It
     never re-enters the retry loop (a second pass would queue a second
     copy and could end as `REJECTED`).
  2. **After the sequence write, a drain.** A delivery that recorded its
     sequence reads the pending queue again. A queued next callback is
     taken only through `_claim` on a fresh state row and sequence; a lost
     claim ends the drain silently. Entries at or below the recorded
     sequence are leftovers and are never run.
  3. **A drained callback cannot change the first one's answer.** An
     ordinary handler error is folded as today (the sequence moves on); a
     `DbError` releases the claim, leaves the entry queued and ends the
     drain; a `REBUILD` result is returned to the caller. The drain does not
     run after a stop, a `REBUILD` or a sequence that was not recorded.
  4. **A bound.** At most a fixed number of rounds and a fixed share of
     `CLAIM_LEASE_SECONDS` per delivery; the rest stays queued for the next
     delivery. Each round costs one pending read and one claim, chained from
     the row and sequence just written.
  5. **Pruning.** Whatever a delivery processed from the queue, its own
     entry included, is pruned.
  6. **The pending row is written by compare-and-swap** in `_add_pending`
     and `_prune_pending`, with a re-read and retry.
  The cost on the common path (in order, nothing queued) is one more read
  of the pending row per callback; the plan accepts it and the changelog
  does not hide it.
- `tests/integration/test_callback_processor_concurrency.py` - one event,
  set when a delivery has its answer; the winner's handler waits on it with
  a timeout far under the lease and records whether the wait succeeded, and
  the test asserts that in its own thread. The config comes from
  `make_config(database=DATABASE_BACKEND)`; the docstring says what it
  covers.
- `tests/_adoption_helpers.py` - `make_config` gains a keyword-only
  `database="dynamodb"`.
- `tests/integration/test_callback_delivery_shapes.py` - the `xfail` goes.
- `CHANGELOG.rst` - FIXED: a callback that arrived while the previous one
  was being processed stayed queued until later traffic; a queue entry
  could be lost to a concurrent prune.
- `thoughts/todo/` - `low-granularity-concurrent-writes-replica.md` and
  `callback-concurrency-test-sequential-postgresql.md` deleted with their
  index rows; `subscription-subscriber-fault-hardening.md` gains the byte
  bound and the cleanup race.

**If the reproduction does not fail:** rules 1 to 5 are not implemented,
the two-write test keeps its `xfail` and its todo stays, with what was
learned. The concurrency test, `make_config`, and the compare-and-swap on
the pending row (rule 6, with AC-17) still land, and Phases 2 and 3 proceed.

### New Tests (written first: `/implement_plan` sees them fail before coding)

`tests/test_callback_pending_drain.py`, two processors on one subscriber, no
threads and no timing:

- AC-1, queued before the sequence write: A's handler for 1 calls B's
  delivery of 2 inline; B sees the live claim, queues and answers pending;
  A then records 1. Asserts the handlers ran `[1, 2]`, the sequence is 2 and
  the stored queue is empty.
- AC-1, queued after: B's wrapped `_add_pending` runs A's whole delivery of
  1 and then does the real write. The same asserts.
- AC-2: both cases with coroutine handlers.
- AC-17: a prune's read, then a queue write, then the prune's write: the
  written entry is in the queue.
- A queued callback two ahead (3 while 1 is processed, 2 never sent) stays
  queued: the drain does not skip a gap.
- A drained callback whose handler raises an ordinary error: the first
  answer is unchanged and the sequence moves on, as an undrained failure
  does today.
- A drained callback whose handler raises `DbError`: the first callback is
  `processed`, the sequence stays at it, the entry stays queued and the
  claim is released.
- A drain that returns `REBUILD` hands it to the caller.
- More queued callbacks than the bound: the bound's worth is processed, the
  rest stays queued, and the next delivery takes them.
- A delivery that processed itself is not run again by the other delivery's
  drain (each handler once).

The concurrency test as changed - AC-4.

### Failure Scenarios

- The drain outlives the claim's lease under a steady stream - rule 4's
  bound; the over-the-bound test.
- The store faults while a drained callback is applied - rule 3; the
  `DbError` test (the first callback's 204 is not turned into a 503).
- Two deliveries both try to process the same queued callback - rule 2's
  claim; the each-handler-once test.
- A queue write lands between a prune's read and write - rule 6; AC-17.
- The subscription is deleted while a drain runs - the drain's claim reads
  a state row that is gone and ends; not tested here, recorded with the
  cleanup race in the fault-hardening todo.

### Verification

- [ ] The reproduction tests fail before the change, on the stranded entry,
      then pass; if they do not fail, the stop rule above
- [ ] The two-write test's failure rate measured before the fix (50 runs
      alone on each backend); after the fix, enough runs that the old rate
      would have shown at least five failures, all passing
- [ ] Fast tier, then Full tier on both backends before the commit

### Notes from implementation (2026-11-16)

- **The reproduction failed as predicted**: against the unchanged receiver
  10 of the 11 new tests failed on the stranded entry or the lost queue
  write (the gap test is a guard and passes before and after).
- **The two-write test**: 50 of 50 runs failed on each backend before the
  change (run alone, one at a time); 10 of 10 passed on each after it.
- **Rule 1 is the drain, started without a known sequence.** The delivery
  that queued its callback takes whatever is next in line, its own callback
  or the ones before it, through the same claim on a fresh row. That is
  what makes "the next delivery takes the rest" true after a bounded drain.
  It answers `PROCESSED` when its own callback was among them, `REBUILD`
  when one is due, `PENDING` otherwise.
- **The bound is 20 callbacks and 5 seconds since the delivery started**
  (`DRAIN_MAX_CALLBACKS`, `DRAIN_SECONDS`), not a share of the 60-second
  lease: the publisher waits for the first callback's answer with a
  10-second read timeout (`callback_sender.DIFF_TIMEOUT`).
- **A fresh state row and sequence are read only when something is queued
  next**, so the common path costs the one queue read the plan accepted.
- **A queue write that cannot be made raises `DbError`** (a 503; the
  publisher keeps the diff). It was unchecked, and the callback was
  answered 204.
- **A store fault in the handler of a delivery's own queued callback** (rule
  1) leaves it queued and answers `PENDING`, as for any drained callback;
  the next delivery runs it again.
- **Refactor**: the handler loop and what follows it (sequence write, prune,
  out-of-step marks) moved out of the two twins into `_run_handlers` /
  `_run_handlers_sync` and `_finish_batch`, which the drain shares.
- **AC-17's red run** hooked `_get_pending` (the queue's only read before
  the change); the test as committed hooks `_read_pending_row`.
- **AC-4** passes before and after on DynamoDB (a test change, no red run);
  it now runs on the run's backend.
- A minor: no route, hook name, kwarg, response field or option changes in
  this phase.

### Review of the phase commit (codex `gpt-5.6-sol` and a fresh-context reviewer, 2026-11-16)

Eleven findings on `6d30934`; fixed in the commit after it unless noted:

- **A handler of 5 seconds or more left the drain no round** (High): the
  clock started with the delivery. The first queued callback is now always
  taken; the bounds apply after it, from the drain's start.
- **One claim covered up to 20 callbacks under one 60-second lease, with
  the sequence written after the batch** (High): the drain claims one
  callback per round and records its sequence before the next. A fault
  midway no longer re-runs callbacks that succeeded (Low, same fix), and
  the time bound is checked between callbacks (Medium, same fix).
- **A callback left at the head of the queue made the next delivery trigger
  the gap resync**, which clears the queue (Medium): the gap timeout is not
  checked while the next callback in line is itself queued; the drain takes
  it. The 21st callback behind one delivery, with no traffic after it, still
  waits for the next delivery or poll (rule 4, accepted).
- **The drain read the queue before the state row** (Low): row, sequence,
  then queue, as the in-order path.
- **A queued `NaN` made every later queue swap lose on DynamoDB** (Low,
  peer-reachable): a callback with a non-finite number is refused.
- **A queue write that landed but was reported lost queued a second copy**
  (Low): a sequence is queued once. No back-off between the five tries:
  accepted, the row is per subscription.
- **An in-order delivery whose own sequence was queued left the entry**
  (Low): pruned.
- **Tests that passed with the behaviour removed** (Medium): the once-only
  test races at the claim; two queue writes at once; the time bound; the
  head-of-queue case with the gap timeout passed; the fault, error and
  rebuild cases on both twins.
- Accepted: a `DbError` on the drain's claim write is logged and may leave
  a claim live for its lease with nobody running it (the in-order path
  raises there; the drain must not change the first callback's answer).

### Implementation Status: Complete

---

## Phase 2: what a publisher sends on resume and on a resource write; what a poll tells

### Changes

- `actingweb/actor.py` - `_callback_subscription_resync` sends the resync
  callback to every subscriber with an endpoint; the capability check, the
  fallback branch, `_get_full_state_for_subscription` and
  `_filter_full_state` go (the marker path for peers without an endpoint and
  `none` subscriptions stays). The resume no longer reads capabilities.
- `actingweb/property_list.py` - `fit_full_state` and its export
  (`:105`) go.
- `actingweb/peer_capabilities.py` - `supports_resync_callbacks_cached`
  goes if the resume was its only reader; `supports_resync_callbacks()`
  stays.
- `actingweb/interface/subscription_manager.py`:
  - `notify_subscribers` passes the subtarget's stored value as `whole`
    when the target is `properties` and a resource is given, resolved only
    when a subscriber above the resource matches (`register_diffs` takes it
    as a callable, as it takes `previous`). A subtarget that is not in the
    store sends what was passed, as today.
  - `sync_subscription` and its async twin tell the data hooks once where
    they return, when the result carries a baseline, under the guard the
    ordinary polled diffs use, and not when the same poll already told a
    list diff that led to the rebuild. The two baseline paths outside a
    rebuild (`:1238` no diffs, `:1502` none applied) set the result's
    baseline. The result carries the subscription's target, so no site
    looks the subscription up twice. On the async side the call is after
    the `await`, on the caller's loop.
- `docs/protocol/actingweb-spec.rst` - the passages in "Spec Delta".
- `tests/integration/wire/rows.toml` - an ownership commit gives `WD12` to
  this plan's Phase 2 first; in the phase commit the row's expected text
  becomes "a resync", and the test (renamed from
  `test_wd12_full_state_fallback`) keeps stripping the tag from the trust
  row.
- Tests that pin the fallback:
  - deleted, fallback only: `test_list_diff_resync_and_filter.py`
    `TestFullStateIsTwoDiffs`, `test_property_list_spans.py`
    `TestFullStateFallback`, `test_property_list_span_iterations.py:511`,
    `test_v2_cost_library_callers.py:206`,
    `test_property_tree_grants.py:202`;
  - re-pinned on the baseline read: a value too deep for the grant filter is
    left out, not `null` (`test_property_tree_grants.py:236`); what a resync
    does for a publisher with a holed list
    (`test_property_list_repair.py:241`; `properties?format=full` answers
    409 for it today, so the test first records which read the baseline
    uses);
  - trimmed: `test_grant_stored_text.py:345` keeps its diff asserts;
    `tests/test_peer_capabilities.py:110` follows what stays.
- Docs: `docs/guides/subscriptions.rst` (`:94-95`, `:329-331` with its
  example, `:549-551`, `:594-595`, and `notify_subscribers` with
  `resource`, pointing at `request_resync` for a large value; `:675` says a
  direct `rebuild_subscription` call tells no hook),
  `docs/sdk/actor-interface.rst`, `docs/reference/hooks-reference.rst`
  (`:233-234`: a poll tells the data hook only, the legacy hook is told on
  the callback path),
  `docs/migration/v3.16.rst` (`:1996-1997` reworded; new checklist items
  and the line at `:19` that lists the items most applications check: a
  data hook is called with `"resync"` from a poll and must take a whole
  baseline twice; a resume always sends a resync; `resource=` sends the
  whole stored value, so a subscriber that relied on the partial
  `{resource: value}` or a publisher that redacts outside the grant must
  check).
- `CHANGELOG.rst` - the `Unreleased` entries that describe fixes to the
  fallback (`:985`, `:1294-1297`, `:1307`) are rewritten: 3.16 never ships
  that path. New: CHANGED, a resume always sends a resync (**Behavior
  change**); CHANGED, the resource notification sends the whole value
  (**Behavior change**); CHANGED, a data hook is called with `"resync"`
  from a poll (**Behavior change**).
- `thoughts/todo/` - `full-state-fallback-replica.md` deleted with its row;
  `subscriber-hooks-and-resource-diffs-after-1-5.md` trimmed to the previous
  value's read, its row reworded.

### New Tests (written first)

- `tests/test_resume_always_resyncs.py` - AC-5, AC-6, and: the resume makes
  no capability read; a peer without an endpoint still gets a marker; a
  `none` subscription still gets a marker; a resync whose send fails is
  recorded as pending when the write waited; on a running loop with nobody
  waiting it is not (pins today's limit).
- `tests/test_notify_subscribers_whole_value.py` - AC-7, and: a subscriber
  at resource level gets the resource's value; with no subscriber above the
  resource the store is not read; a subtarget absent from the store; a list
  subtarget; another target passes the data through.
- `tests/test_replica_rebuild.py` - AC-8, AC-9, AC-10, and: a settled empty
  baseline `{}` is told; a rebuild after a list diff the poll told tells no
  second hook; an out-of-step diff with no sequence tracking, which told
  nothing, is followed by the baseline.

### Failure Scenarios

- The resync's send fails - recorded and sent again on the next resume when
  the write waited; the running-loop case is pinned as a known limit.
- A pre-3.10 subscriber ignores the resync - it has no library replica; the
  changelog and the specification say it re-reads on its own schedule.
- The subtarget is gone from the store when `notify_subscribers` resolves
  `whole` - sends what was passed; tested.
- A hook that is not idempotent for a whole baseline - the migration guide's
  new checklist item.
- A poll's coroutine hook is cancelled before it runs - as for ordinary
  polled diffs today; the hooks reference says "scheduled".

### Verification

- [ ] Fast tier, then Full tier on both backends before the commit
- [ ] `verify_groups.py`: `WD12` is the only changed recording, owned by
      this phase
- [ ] `grep -rn "full_state\|supports_resync_callbacks_cached" actingweb/ docs/`
      shows no dead reference
- [ ] `tests/test_spec_option_tags.py` still passes against the reworded
      specification
- [ ] Docs build with `-W`

### Notes from implementation (2026-11-16)

- **Red first**: 12 poll-hook cases, 5 resume cases and the whole-value
  case failed on the behaviour before the change (the resume cases by
  taking the removed path).
- **The poll tells at its return through a wrapper**: `sync_subscription`
  and `sync_subscription_async` call `_poll_subscription[_async]` (the
  former bodies) and then `_tell_polled_baseline`. `SubscriptionSyncResult`
  gains `target` and `subtarget`, set with `baseline`.
- **A quiet poll tells the hook every time** (the no-diffs path fetches a
  baseline on each poll with `auto_storage`). This is what the plan's rule
  says; it is the path a polling application will notice most. The
  changelog, the hooks reference and the migration guide's item 31 say so.
  Raised with the owner in the hand-off as the one choice worth a second
  look.
- **Removed with the fallback**, beyond the plan's list:
  `Actor._resolve_list_heads` and `Actor._list_state_reference` (only the
  full state used them), with their tests
  (`test_property_list_span_iterations.py`, `TestW4...` and `TestM5...`).
- **Not re-pinned, against the plan**:
  - *a value too deep for the grant filter is left out, not `null`*: the
    baseline read already has this test
    (`tests/integration/test_property_grants_flow.py::test_a_value_too_deep_to_filter_is_withheld_not_null`);
    the fallback's copy is deleted.
  - *a publisher with a holed list*: `TestResyncSkipsCorruptedListsOnly`
    tested the removed function directly and is deleted without a
    replacement. What the baseline read does there is existing behaviour
    this plan does not change (the list's read answers 409 and the
    subscriber counts the list as failed, so the rebuild stays owed), but
    no test in this plan pins the two together. Open for the verification.
- **`WD12`** re-recorded as a resync (ownership commit `2fd8e3f` first);
  the test is `test_wd12_resume_to_a_peer_cached_without_resync` and now
  waits for the replica to settle. The subscriber ends with `y` as an
  object, no `x`, and the list once: the three defects the row recorded
  are gone.
- **Specification**: three more passages than the plan listed said
  "SHOULD send only to a subscriber that advertises" (`:60`, the tag's
  definition at `:853`, the recovery list at `:4395`); reworded with the
  rest.
- **`docs/sdk/actor-interface.rst`** needed no change (its
  `notify_subscribers` sample has no `resource`).
- A minor: `SubscriptionSyncResult` gains two fields;
  `supports_resync_callbacks_cached` and `fit_full_state` are removed.
- **A new todo line**: `notify_subscribers(resource=...)` reads the stored
  value apart from the application's write (in
  `subscriber-hooks-and-resource-diffs-after-1-5.md`).

### Implementation Status: Complete

---

## Phase 3: the public surface and the trust page

### Changes

- `actingweb/handlers/callback_oauth.py`, `actingweb/handlers/__init__.py`,
  `actingweb/config.py` - the class goes; the module raises an
  `ImportError`: "CallbackOauthHandler was removed in 3.16; neither
  integration routed it. The OAuth2 callback is served under /oauth by
  integrate_flask and integrate_fastapi: remove the import, and see
  docs/migration/v3.16.rst"; `__all__` loses the name.
- `actingweb/config.py:381` - the default `redirect_uri` is `/oauth`, and
  the integrations route `/oauth/callback`: the phase first finds what
  serves the default; if nothing does, that is reported to the owner before
  the default is touched (not this plan's to change silently).
- `docs/reference/handlers.rst` - the `automodule` block and its note go;
  `docs/migration/v3.16.rst` (the "does not start" warning at `:43` and a
  removal paragraph) and `CHANGELOG.rst` (REMOVED, "routed by neither
  integration") name it.
- `actingweb/handlers/www.py` - the new-trust POST answers every failure
  with `set_status(302)` and a redirect built from `_www_path()` and one
  code from a fixed set: `peer_url_required`, `relationship_too_long`,
  `trust_type_required`, `create_failed` (every peer-side cause),
  `server_error` (the exception is logged, never written). A peer that
  already had a trust (a row with the submitted base URI before the create)
  redirects to the list with `notice=trust_exists`. The two GETs map a known
  code to a fixed text; a configuration error on the form wins over a code.
- `actingweb/templates/` - `aw-actor-www-trust.html`: the status cell reads
  from both sides, with no new column:

  | Own | Peer | Verified | Reads |
  | --- | --- | --- | --- |
  | approved | approved | yes | Active |
  | approved | no | either | Waiting for peer |
  | pending | approved | yes | Awaiting your approval |
  | pending | no | yes | Awaiting both |
  | pending | either | no | Unverified |

  and the notice (`role="status"`, a new `.aw-notice` in `base.html`; errors
  get `role="alert"`). `aw-actor-www-root.html`: a link to the new-trust
  form. Rows whose peer side does not apply (an OAuth2 client's row) keep
  today's label; the phase checks what `peer_approved` holds on them first.
- `examples/demo/templates/aw-actor-www-trust.html`,
  `aw-actor-www-root.html` - the same labels, legend, notice and links.
- `docs/guides/web-ui.rst` - the trust pages; `docs/migration/v3.16.rst` -
  a row for `POST /www/trust/new` (a 400 with text becomes a 302);
  `CHANGELOG.rst` (CHANGED, **Behavior change** for a client that read the
  400's text).
- `thoughts/todo/` - `callback-oauth-handler-unrouted.md` and
  `web-ui-trust-page-gaps.md` deleted with their rows; the index's 3.16
  table lists this plan.

### New Tests (written first)

`tests/integration/test_www_trust_pages.py`, each test with its own actor
and trust rows (no test depends on another), redirects not followed, then a
GET of `Location`:

- AC-12 to AC-16 as in the Traceability table, on Flask and FastAPI for the
  redirects.
- A submitted `peer_url` with `\r\n` or `//host` never reaches the
  `Location` header.
- The 500 branch: the handler's exception text is not in the response
  (an in-process handler test).

`tests/test_demo_example.py` - the demo's two templates rendered with
autoescape and rows for each state: the labels, the links and the notice
are present.

`tests/test_subscription_processing.py` - AC-11, beside the `FanOutManager`
tombstone test; `from actingweb.handlers import *` does not raise.

### Failure Scenarios

- A link from another site with form parameters - nothing is prefilled;
  AC-16.
- A redirect loses its status on Flask (`flask_integration.py:735` copies
  the handler's status, 200 by default) - `set_status(302)`; AC-14 on both
  integrations.
- The peer cannot be reached - one message for every peer-side cause;
  AC-14's `create_failed` case.
- A wildcard import of `actingweb.handlers` meets the tombstone - `__all__`
  loses the name; tested.

### Verification

- [ ] Fast tier, then Full tier on both backends before the commit
- [ ] Docs build with `-W`
- [ ] Browser walk on the demo in local QA mode (`CLAUDE.md`, "App"): the
      trust list with a row in each state it can be put in, the links, each
      form failure, the existing-trust notice, at desktop width and 375 px
      (the page body does not scroll sideways); console read after each step
- [ ] Emm's suite on the branch (gate 2), recorded in the verification

### Notes from implementation (2026-11-16)

- **Red first** for the handler tests (a 400 where a 302 is expected, the
  missing labels, the missing dashboard link). The demo template test was
  written after the templates changed (no red run); the tombstone test
  failed on the module importing cleanly.
- **The default `redirect_uri` is now `/oauth/callback`** (owner,
  2026-11-16, after the check the plan asked for): `/oauth` is not the
  callback. Checked afterwards with a request on both integrations with
  OAuth configured: `GET /oauth?code=x&state=y` answers 302 to the
  provider's authorize URL (the path is taken for an actor id and an
  unauthenticated browser is sent to sign in), while `/oauth/callback`
  attempts the token exchange. So a provider redirecting to the old default
  looped back to itself; "nothing served it", as first reported to the
  owner, was a reading of the route table, and the texts now say what the
  request showed;
  `config.py` and `app.py` defaulted to it. The wire rows `WG15` and `WG16`
  showed what that meant: a provider configured through `with_oauth()`
  without a `redirect_uri` was sent `<root>/oauth` (the provider classes
  ignore `config.oauth`'s default only when no provider entry exists), so
  the default was not dead, it was broken. Both rows re-recorded (ownership
  commit first); both defaults, the pinning test, `configuration.rst`,
  `routing-overview.rst`, the changelog and the migration guide follow.
- **The tombstone says `/oauth/callback`**, not "under /oauth" as the plan
  drafted: it is the path that is served.
- **`from actingweb.handlers import *` never worked** (the package lists
  lazily loaded names it does not import; it raises `AttributeError` on
  `master` too), so the planned wildcard test asserts that `__all__` no
  longer lists the module instead.
- **The status label is computed in the handler** (`trust_status_label`,
  set as `status_label` on each row) rather than in each template, so the
  library's template and the demo's cannot disagree. A row whose peer has no
  endpoint (`_has_peer_endpoint`: an OAuth2 or MCP client) gets `None` and
  keeps the approved and verified badges; `peer_approved` is false on those
  rows (they are created without it), which would have read "Waiting for
  peer".
- **"Already has a trust" means a row this actor has approved** with the
  submitted base URI. A row waiting for this actor's approval is not that:
  creating toward its peer is how it is approved, and an existing test
  (`test_trust_re_pair.py::TestTheCreateRoutesAfterReverify5::test_the_web_form`)
  pins it.
- **The tests are `tests/test_www_trust_pages.py`**, in process on Flask and
  FastAPI with the library's templates and the real store, not under
  `tests/integration/` (no server fixture is needed, and the Flask
  integration has none there).
- A minor: a default changes, a module is removed, two template variables
  and a handler's answers change.

### Review of the Phase 2 commit (codex `gpt-5.6-sol` and a fresh-context reviewer, 2026-11-16)

Nothing High. Fixed in the Phase 3 commit unless noted:

- **A baseline that was skipped or had an entry that could not be stored
  was told to the hooks** (Low to Medium): told only when all of it was
  applied; the docstring says an empty whole-target baseline with nothing to
  fetch tells nothing.
- **`notify_subscribers` passed `whole=None` on every call**, which broke an
  application's `register_diffs` override with the older signature (Medium,
  not peer-reachable): passed only when set.
- **A `ValueError` from the lazy read** (a `list:` name) escaped the
  per-subscriber fold (Low): answered as "nothing stored".
- **Stale text** in `request_resync`, `callback_sender` and the properties
  handler; the drain's comment about the publisher's timeout; the log line
  for a refused callback.
- Tests: a subtarget subscriber with an exclusion; no `whole` on a plain
  notification; a skipped and a partly stored baseline; a dead mock line.
- **Not fixed, filed**: a `list:`-named key inside a stored property passes
  a subtarget subscriber unfiltered (the reviewer's Medium; predates the
  plan, needs an owner-stored `list:` key with an exclusion beneath it):
  `thoughts/todo/subtarget-diff-list-key-exclusion.md`. A queued callback
  whose handler faults every time blocks its queue until a poll or a resync
  (Low): in the fault-hardening todo.
- Accepted: the ordered-unit machinery in `callback_sender` has no
  multi-send caller left; it stays (small, tested, and a resync plus a diff
  may use it).

### Implementation Status: Complete

---

## Implementation Summary

**Completed:** 2026-11-16
**All phases:** Complete
**Test status:** Full tier green on both backends for Phases 1 and 2
(DynamoDB 7,940 passed, PostgreSQL 7,712 passed, docs clean). Phase 3's
Full tier ran with two wire rows failing (`WG15`, `WG16`: the recorded
provider redirect carried the old default `redirect_uri`) and a title
underline in the migration guide; all else passed (7,964 and 7,736). The
two rows were re-recorded under an ownership commit, and
`tests/integration/test_wire_grants.py` (23 tests) and the docs build were
re-run green on both backends; the whole suite was not run a second time.

**Commits:** `ac5aec5` (plan), `6d30934` (Phase 1), `09823be` (Phase 1
review fixes), `2fd8e3f` (ownership of `WD12`), `480b12a` (Phase 2),
`334fdaf` (ownership of `WG15`, `WG16`), `d62021b` (Phase 3). Two commits
carry a staged todo deletion that belongs to the phase after them
(`09823be`: `full-state-fallback-replica.md`; `334fdaf`: the two Phase 3
todos); the tree at each phase commit is right.

**Browser walk** (headless Playwright against the demo in local QA mode,
1280 and 375 px): every step met its expectation: the five status labels,
the links from the dashboard and the list, each form failure back on the
form with its message and an empty form, the existing-trust notice with no
second row, nothing from a tampered query string on the page, no sideways
scroll, no console error. Fixed from it: the demo's "New trust" button lost
its label on hover. Left as they are (the demo's own styling, low): the
status badges' contrast, three waiting states in one colour, the dashboard's
button row at 375 px, a legend of relationship types that does not match
the form, and long peer ids breaking mid-word at desktop width.

**The consumer's suite on `d62021b`** (environment 9, the library worktree
at `d62021b`; `creator-to-email` dry run first: 1 scanned, nothing to move;
no schema change): **PostgreSQL** 3 failed, 7,405 passed, 14 skipped, 179
deselected; **DynamoDB lane** 3 failed, 54 passed. The same six failures by
name as the run on `2f1a891` (the baseline's five and the date-dependent
`test_trial_state_pure` case), nothing new or gone. Logs:
`../actingweb_mcp/.claude/worktrees/emm9-{pg,dyn}-d62021b.log`. Its suite
does not poll a quiet subscription, so it does not show the effect of the
poll's `"resync"` hook call there.

### Deviations from Plan

- **Phase 1**: the drain takes one callback per claim, always the first,
  then at most 20 and none after 5 seconds (not a share of the lease); a
  callback left at the head of the queue no longer triggers the gap resync;
  a queue write that cannot be made is a 503; a non-finite number is
  refused. Rule 1 is the same drain, started without a known sequence.
- **Phase 2**: two fallback tests were deleted and not re-pinned (the deep
  value has a test on the baseline read already; the holed list has none
  that joins publisher and subscriber); a baseline is told only when all of
  it was applied; two more helpers went with the fallback; three more
  specification passages were reworded.
- **Phase 3**: the default `redirect_uri` changed (owner decision during
  the phase); the status label is computed in the handler; the tests are in
  process under `tests/`; the wildcard-import test became an `__all__`
  check.

### Learnings

- The gap timeout and the pending queue interact: anything that leaves the
  next callback in line queued must not be read as a gap.
- A "dead" default was live: `with_oauth()` copied the `/oauth` default into
  the provider entry, so only an application that passed its own
  `redirect_uri` had a working callback. The wire rows showed it.
- A quiet poll with `auto_storage` fetches and applies a whole baseline
  every time; telling the hook there would have been the most visible
  effect of this plan for a polling application, and is why it does not.

### After the implementation: two owner decisions and the Phase 3 review (2026-11-16)

In one commit after `40f33f0`:

- **A quiet poll tells no hook** (owner). AC-8's "no diffs" case became
  `test_a_quiet_poll_tells_no_hook`; the baseline is still applied.
- **The `list:` key finding is fixed, not filed** (owner; the Phase 2
  reviewer's Medium): beneath a subtarget a `list:<x>` key passes whole only
  when its value is a list diff; anything else is filtered at its path
  (`tests/test_grant_stored_text.py::TestListDiffObjects::test_a_stored_value_under_a_list_key_is_filtered_beneath_it`).
  A first attempt removed the exemption outright and broke two tests from
  earlier verifications that pin it for list diffs. Residual: a stored
  object under such a key that itself has `list` and `operation` keys is
  still read as a list diff.
- **The `/oauth` premise was checked with a request** (see Phase 3's
  notes); the texts were corrected.
- **From the review of `d62021b`** (codex `gpt-5.6-sol` and a fresh-context
  reviewer; nothing High):
  - *The "trust exists" check had removed the form's re-pair* (Medium):
    before this plan a submit for an approved peer with the same
    relationship rotated the secret. It does again, to the stored base URI,
    and the list says so (`trust_repaired`); another relationship changes
    nothing and says so (`trust_exists`; it was a bare failure). The base
    URI is matched without host case, a default port or a trailing slash.
  - *"Active" for a row both approved but not verified*: now "Waiting for
    peer"; the matrix test has that row and an OAuth2 client's row.
  - `_stored_property` folds `ValueError` only; a stale comment in
    `oauth2.py`; the docstring says a refused key is in the baseline the
    hook gets.
  - Tests: the three untested "applied whole" guards (the reapply path, on
    both twins); the hostile `peer_url` now reaches the create and the
    exception path.
  - Accepted: a link from another site can show one of the fixed messages
    on a signed-in owner's page (fixed text, no state change).
- **Stale evidence corrected**: the two-write test was re-run on the tree
  with one callback per claim, 5 of 5 on each backend; the drain tests run
  on PostgreSQL in a PostgreSQL run (19 passed, none skipped).
- **A final Full tier passed on `40f33f0`'s code** before this commit
  (DynamoDB 7,966 passed, PostgreSQL 7,738, docs clean), and again after it
  (recorded in the commit message).

### Open after this plan

- `thoughts/todo/demo-qa-mode-basic-auth-challenge.md`.
- Three lines in `subscription-subscriber-fault-hardening.md` and one in
  `subscriber-hooks-and-resource-diffs-after-1-5.md`.
- No verification document yet: `/verify_implementation` writes it and
  quotes the consumer suite's run below.

---

## Evaluation Notes

**Outside voice:** codex (ran outside the sandbox, read-only), with a
fresh-context reviewer.

| # | From | Finding (`file:line` quoted) | Disposition |
| --- | --- | --- | --- |
| 1 | Architecture, Usability | `docs/protocol/actingweb-spec.rst:4068` "To a subscriber that does not advertise the tag, the publisher instead sends the full subscribed state as ordinary diffs" - the plan expected no such sentence | Owner decided: reword the specification (Decisions, Spec Delta, Phase 2) |
| 2 | Security | `handlers/www.py:827` `if path == "trust/new":`, a GET with no cross-site check - values in the redirect let another site prefill the form | Owner decided: message only, nothing prefilled (AC-14, AC-16) |
| 3 | Architecture | `callback_processor.py:344` `sub.handle.modify(seqnr=new_seq)` is outside the claim's compare-and-swap - a drain could run N+1 twice | Folded: Phase 1 rule 2 and the each-handler-once test |
| 4 | Architecture, Tests | `callback_processor.py:892` `if drained:` - a self-processed entry is never pruned | Folded: rule 5; AC-1 asserts the stored queue |
| 5 | Architecture | `callback_processor.py:628` `pending.append(callback)` has no dedupe - re-entering the loop queues twice | Folded: rule 1, one re-check |
| 6 | Architecture, Tests | `callback_processor.py:857` `raise` and `:1293` "at-most-once semantics means we don't retry" - a drained failure could change N's answer, and the planned test contradicted the code | Folded: rule 3 and two tests |
| 7 | Scalability, Security | `subscription_config.py:40` `max_pending: int = 100`, `callback_processor.py:102` `CLAIM_LEASE_SECONDS = 60.0` - no bound on the drain | Folded: rule 4 and its test |
| 8 | Scalability | `callback_processor.py:785` - one more consistent read of the pending row per in-order callback | Accepted and stated in Phase 1; a flag on the state row would put a second writer on the claim's row |
| 9 | Outside voice | `callback_processor.py:639-642` `kept = [...]` then `_set_pending(...)` - the drain makes a writer race a pruner | Folded: rule 6 and AC-17 (a compare-and-swap on the pending row, not the suggested move into the state row, which would rewrite the payloads on every claim) |
| 10 | Tests | `callback_processor.py:1218-1227` - the planned "after the queue write" interleaving passes today | Folded: the two interleavings in Phase 1's tests |
| 11 | Tests | `callback_processor.py:858` `except Exception` swallows an assert in the handler | Folded: the concurrency test asserts in its own thread |
| 12 | Tests | `tests/_adoption_helpers.py:34` `database="dynamodb",`, about 55 importers | Folded: a keyword, not the environment |
| 13 | Tests | `test_callback_delivery_shapes.py:132` "it XPASSed on CI" - 20 runs prove nothing without the old rate | Folded: Phase 1 Verification |
| 14 | Outside voice | Phase 1's stop rule left the rest of the phase undefined | Folded: "If the reproduction does not fail" |
| 15 | Architecture, Tests, Outside voice | `subscription_manager.py:1476-1480` the break before the hook at `:1489`; `:1238`, `:1502` baseline paths outside a rebuild - AC-8 contradicted the Changes and missed paths | Folded: one rule (Decisions), AC-8, tell at the return |
| 16 | Outside voice | `handlers/callbacks.py:134-138` `task = loop.create_task(hook(*args))` - AC-10 could only assert scheduling | Folded: AC-10 reworded, the test drains the task |
| 17 | Outside voice | `actor.py:5295` `return bool(unit.delivered) if waited else True` - a failed resync on a running loop is recorded nowhere | Folded as a pinned limit (Not Doing, Phase 2 test); existing behaviour for every 3.10+ peer |
| 18 | Architecture | `docs/guides/subscriptions.rst:419` `if caps.supports_resync_callbacks():` is documented API | Folded: it stays |
| 19 | Tests | `property_list.py:105` `"fit_full_state",`; `test_property_tree_grants.py:236`; `test_property_list_repair.py:241` - coverage that deletion would lose | Folded: Phase 2's test list |
| 20 | Usability | `docs/guides/subscriptions.rst:94`, `:329`, `:549`, `:594`; `docs/migration/v3.16.rst:1996`; `CHANGELOG.rst:985`, `:1294`, `:1307` describe the fallback | Folded: Phase 2's docs |
| 21 | Usability | `docs/migration/v3.16.rst:19` lists the items applications check - most changes had no item | Folded: Phase 2 and 3 docs |
| 22 | Scalability, Security | `actor.py:5708` `if not subs: return`; `subscription_manager.py:709` - `whole` read before anyone needs it, and more disclosed than was passed | Folded: resolved lazily; grant test in AC-7; **Behavior change** |
| 23 | Scalability | `subscription_manager.py:2712` - the owed sites would look the subscription up twice | Folded: the result carries the target |
| 24 | Security, Usability | `www.py:1040` one message for peer-side failures; `actor.py:2323` `return False` for every cause | Folded: one `create_failed` code |
| 25 | Architecture | `flask_integration.py:735` `response.status_code = webobj.response.status_code` | Folded: `set_status(302)`, both integrations in AC-14 |
| 26 | Architecture, Usability | `www.py:846` `"error": trust_types_error` already uses the variable | Folded: the configuration error wins |
| 27 | Usability | `aw-actor-www-trust.html:39` covers the own side only - states unspecified | Folded: the matrix in Phase 3 |
| 28 | Usability | `config.py:65` the tombstone pattern - text unspecified | Folded: the text in Phase 3 |
| 29 | Outside voice | `handlers/__init__.py:6` `"callback_oauth",` - the class was never importable from the package | Folded: AC-11 names the module only |
| 30 | Outside voice | `config.py:381` `self.oauth["redirect_uri"] = self.proto + self.fqdn + "/oauth"` | Folded as a check in Phase 3, reported before any change |
| 31 | Tests | `test_www_templates.py:271` `pytest.skip("Actor not created...")` - a new test there could skip and pass | Folded: a new self-contained file; a demo template render test |
| 32 | Security | `www.py:1036` the safe redirect pattern | Folded: `_www_path()` and a fixed code set; the `\r\n` test |
| 33 | Outside voice | `subscription_config.py:23`, `db/dynamodb/attribute.py:105` `MAX_ROW_BYTES` - the queue is bounded by count | Recorded in the fault-hardening todo (Not Doing) |
| 34 | Outside voice (codex) | Split the trust page and the handler removal into a later PR | Rejected: owner decided they land before the validation |
| 35 | Scalability | `www.py:979` unbounded `description` in the redirect | Moot: no values in the redirect |

**Unverified notes** (concerns that could not cite a line):
- What `peer_approved` holds on an OAuth2 client's trust row (Phase 3 checks
  first).
- Whether the baseline fetch of a resync uses `format=full` (Phase 2's
  holed-list test records it).
- A poll that drains a pushed callback tells only the data hooks, never the
  legacy hook.
- Whether both drains racing can answer `in_progress` for an entry already
  queued (a 503 the publisher retries; harmless if so).
