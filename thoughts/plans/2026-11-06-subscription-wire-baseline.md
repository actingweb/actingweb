---
status: proposed
---

# Implementation Plan: the subscription wire between two actors, recorded as it is today

**Date:** 2026-11-06
**Research:** thoughts/research/2026-11-06-subscription-wire-baseline.md
**Branch:** docs/3-16-rollup-records (written here; implement on `release/3.16.0-subscription-wire-baseline`, one PR, one commit per phase)

## Update Log

- **2026-11-06**: `WD9` moved here from the security plan (owner); `WL14`
  split from `WL11.target`. Second review recorded in the Evaluation Notes,
  not folded; a Readiness paragraph says what the plan needs before approval.
- **2026-11-06**: The order, the dependencies between the six plans and
  the gates between them moved to one copy in `thoughts/todo/INDEX.md`
  (owner); the copy here is a pointer. Two gates there are this plan's to
  meet: a recording joins the regression set only once it is byte-identical
  over repeated runs on both backends, and the recordings shaped like Emm's
  use, the import flow included, exist before the `subs_list` plan starts.
  No Emm run for this plan: its diff under `actingweb/` is empty, which
  Phase 2 already verifies. Which plan builds the wire harness, the security
  plan's Phase 0 or this plan's spike, is open.
- **2026-11-07**: The spike is decided (owner): it builds the harness and
  records about four rows on both backends before either this plan or the
  security plan is redrafted; the security plan's Phase 0 lands what the
  spike built. Recorded in the Decisions, the Readiness paragraph and "What
  Already Exists".
- **2026-11-07, later**: The spike is done:
  `thoughts/research/2026-11-07-subscription-wire-spike.md` (harness on
  `spike/subscription-wire-harness`, four rows, one file per row on both
  backends over nine runs). Two premises here are wrong and the redraft
  takes them from the note: a `friend` grant only adds patterns, so a row
  that restricts reads uses `excluded_patterns`; and the gap resync calls
  no data hook. The three decisions are taken on that note. "What Already
  Exists" and Phase 1's `WD9` are stale until the redraft.
- **2026-11-07, decisions (owner)**, taken on the spike note, for the
  redraft: (1) **full transcripts**, recorded from the first scenario step,
  setup excluded; (2) **timestamp tokens carry the format class only**, one
  file per row for both backends, `WD3`'s backend difference asserted
  explicitly instead; (3) **one tier**: every row is in each later plan's
  must-stay-identical list unless that plan names it for re-recording, and
  each row's registry entry names the plan expected to change it; (4)
  **retire** `test_subscription_suspension_flow.py`, the processor-less
  classes of `test_subscription_processing_flow.py` and the
  non-publish-path classes of `test_fanout_flow.py` once rows cover them,
  each deletion naming its covering row or unit test; tighten the rest.
- **2026-11-07, redraft (`/update_plan`)**: rewritten on the four decisions
  above, the spike note and the security plan's redraft (`2303a51`), which
  now lands the harness, `rows.toml` with an owner column, the
  `subscriber` variants, a third recorded app and the CI step. Phase 1's
  rows corrected from the spike (`WD9`'s exclusion grant and skipped data
  hook, `WD18`'s order, `WP5`'s premise, `WD3` asserted, `WD5` without a
  copied configuration) and extended with the rows the second review found
  missing (`WS9`, `WL15` to `WL17`, `WM1`, `WP6`). Phase 2 retires the
  three legacy files and no longer carries the CI step. One more decision
  (owner): the gap resync's skipped data hook is `spec-1-5`'s to fix.

## Overview

No integration test writes to one actor over REST and then asserts what the
other actor holds, so the wire changes the 3.16 plans make would turn no test
red. This plan records what the library does today between a publisher and a
subscriber, for every flow those plans touch, as one checked-in transcript
per flow: every request that crossed the wire, the publisher's queue and the
subscriber's replica. It then brings the existing subscription files to the
point where a green run means something. It changes no library code. After
it, a phase that changes wire behaviour re-records the transcripts of the
rows it names, and the change is a file diff in the commit that makes it.
Lands in 3.16 (tag held), second of the six plans of this date.

## Implementation Order

The order of the six 3.16 plans, what depends on what between them and the
gates between them are kept in one place: `thoughts/todo/INDEX.md`, "Planned
for 3.16: order, dependencies and gates". One PR per plan, one commit per
phase, phases in the order written. What this plan uses from the others is
below.

**Readiness, 2026-11-07.** Redrafted after the spike
(`research/2026-11-07-subscription-wire-spike.md`), on the owner's four
decisions and the security plan's redraft, which lands the harness. The
review of this redraft is under "Third review" in the Evaluation Notes. No
open question remains; approval is the owner's.

**This plan: second.** It needs the security plan merged: that plan's
Phase 0 lands the harness (built by the spike), its rows and `rows.toml`;
its Phases 1 to 3 add the access rows (`WA*`) and the trust rows (`WT*`).
This plan adds every other flow on the same harness and tightens the
existing files. What follows it: each of the four plans after it names,
phase by phase, the rows it re-records, read from `rows.toml`'s owner
column; every other row must stay byte-identical (one tier).

## Decisions Made

- **The spike builds the harness; the security plan lands it** (owner,
  2026-11-07). This plan stays its own PR after the fix.
- **Today's behaviour is proven before it is changed** (owner, 2026-11-06).
- **Its own plan and PR, after the security fix** (owner, 2026-11-06).
- **Recorded transcripts, not hand-written expectations** (owner,
  2026-11-06).
- [New 2026-11-07] **Full transcripts** (owner): every request between the
  actors and a snapshot of both sides after each step, recorded from the
  first scenario step; setup is not recorded.
- [New 2026-11-07] **Timestamp tokens carry the format class only**
  (owner): one file per row for both backends. `WD3`'s backend difference
  (DynamoDB stamps every diff with one value) is asserted explicitly in its
  test, not by the recording.
- [New 2026-11-07] **One tier** (owner): every row is in each later plan's
  must-stay-identical list unless that plan names it for re-recording; the
  owner column in `rows.toml` says which plan is expected to change each
  row.
- [New 2026-11-07] **Retire the legacy files** (owner): the files that test
  nothing on the publish or receive path go once a row covers what they
  meant to; each deletion names its covering row or unit test.
- [New 2026-11-07] **The gap resync's skipped data hook is `spec-1-5`'s to
  fix** (owner): this plan records it in `WD9` and `WD9.subscriber`'s
  registry entries; `spec-1-5`'s next draft takes it.
- **A recording is what the library does, right or wrong.** A row that
  records a defect is an ordinary passing test; its registry entry says
  what is known to be wrong and which plan changes it.
- **The "Expected from reading" columns are not assertions.** Each first
  recording is reviewed against them, and every difference goes into
  "Recorded outcomes" with which of the two was wrong.
- **One file per row and variant**; **a declared difference** (a second
  file with a reason) only when a backend or topology truly differs; an
  undeclared difference fails.
- **The registry lives under `tests/integration/wire/`**, not in
  `thoughts/` (CI does not run for a change under `thoughts/`).
- **Wire tests never rerun** (the security plan's CI step runs them with
  `-p no:rerunfailures`).
- **Later plans add rows as well as re-recording them**, entered in
  `rows.toml` by the phase that adds them.

Deduced; confirm at approval:

- **Re-recording takes explicit row ids** (`WIRE_RECORD=WD9,WS1.target`),
  never "all", and each re-record appends a dated reason line to the row's
  `rows.toml` entry, so a reviewer reads why a file changed next to the
  diff. A driver change lands in its own commit with no recording diff.
- **Order inside a recording follows first appearance**: actors and
  subscriptions are named by first appearance and siblings sorted by name;
  the permission callback's follow-up fetches (a set difference,
  `peer_permissions.py:721-725`) are recorded sorted by path.

## What We're NOT Doing

- **Changing any behaviour** - no diff under `actingweb/` or `examples/`. A
  defect a recording shows is recorded and left to the plan that owns it.
- **The access and trust rows** - the security plan's (`WA*`, `WT*`).
- **Endpoints outside the subscription path** (`/meta`, OAuth, MCP, `/www`
  beyond the list and property forms) - the specification plan's.
- **Fault injection over HTTP** - the unit suites have the seams
  (`tests/test_callback_processor.py`, `tests/test_db_fault_*.py`).
- **A mixed-version pair** - one suite runs one version; the `ListAttribute`
  plan plants the older shape where it matters.
- **The consumer's identity options** (`with_unique_creator`,
  `with_email_as_creator`, indexed properties) - nothing they change travels
  between two actors.
- **Synchronous callbacks on the wire apps** - with the flag on, the
  consumer's import flow deadlocks (spike note); the consumer sets it only on
  Lambda, where the subscriber is another instance.
- **Rewriting the unit suites** - they stay.

## What Already Exists

Landed by the security plan's Phase 0 (from the spike,
`spike/subscription-wire-harness`):

- `tests/integration/_wire.py` - recorder, driver (`Scenario.step` with a
  `settle` condition), snapshot (A's queue, B's replica as scalars and lists
  read separately, callback state, both sides' subscription rows, A's
  suspension rows), normaliser (format-class timestamp tokens, sorted keys,
  ids, subscription ids, hosts, secrets and mid-row names), comparer
  (`WIRE_RECORD`, refused under `CI`; a mismatch writes `<row>.actual.json`).
- `tests/integration/test_harness.py` - keyword options, recording hooks,
  the `wire_import` method (the consumer's import shape), the `subscriber`
  and `subscriber_adopted` trust types.
- `tests/integration/conftest.py` - `wire_app` 5561, `wire_peer_app` 5562,
  `wire_other_app` 5563, `wire_pair` (topology, grant as patterns or a full
  permission object, subtarget, granularity, relationship, capability
  warming, teardown through the library).
- `tests/integration/wire/` with `rows.toml` (an owner column) and the rows
  `WS1.target`, `WL11.target`, `WD6`, `WD8`, `WD10`, `WD10.import`, `WD12`,
  `WQ1` to `WQ3`, `WC1` to `WC4`, `WP1`, the `.subscriber` and
  `.subscriber_adopted` variants of `WD6`, `WQ3`, `WC4`, and `WA1` to
  `WA18`, `WT1` to `WT5`.
- The `wire` marker and its CI step (no reruns, its own junit file).

Already in the tree:

- `tests/integration/test_list_diff_peer_replica.py` - `WL11.target` and
  `WL13` take its cases.
- `tests/integration/test_subscription_callback_flows.py:199-224`,
  `:339-368`, `:497-519` - the receiver's pending queue with hand-built
  callbacks; kept, tightened.
- `tests/integration/test_property_notifications.py:134-137` - the
  target-level delete diff; kept.

## Phase 1: the remaining flows, recorded

Row identifiers continue the security plan's. A suffix is the level of the
subscriber's subscription. Unless a row says otherwise: granularity `high`,
a grant of `*`, both topologies, a warm capability cache. "SDK" marks a step
in the test process through an `ActorInterface` built from the wire app's
configuration. A row that restricts reads grants with `excluded_patterns`
(a `friend` grant only adds patterns).

### Changes

- `tests/integration/test_wire_scalar_properties.py`,
  `test_wire_list_properties.py`, `test_wire_delivery.py`,
  `test_wire_queue_and_lifecycle.py`, `test_wire_permissions.py` - one test
  per row below.
- `tests/integration/wire/*.json`, `wire/rows.toml` - the recordings and
  their entries (owner column, reason lines).
- `tests/integration/test_harness.py` - one wire-app hook for `WD18`: an
  asynchronous method hook that appends to a list through the interface
  (`wire_import` without the suspension).

Scalar properties:

| Row | Steps on the publisher | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WS1.subtarget | `PUT /properties/<p>` with an object, then a string, then `""` | The object stored as one scalar per key; the string answers 400 at the subscriber and stores nothing; the empty value answers 204 | `attribute-list-v2-port` Phase 4 |
| WS2.subtarget | The same with a grant of exactly `<p>` | For the object: a sequence number spent and no callback; the string sent unfiltered | `attribute-list-v2-port` Phase 4 |
| WS3 (three levels) | `PUT /properties/<p>/<k>`, then `PUT /properties/<p>/<k>/<j>` | Target `{p: {k: v}}`; the replica's `p` loses its other keys | `spec-1-5` Phase 3 |
| WS4.target | `POST /properties` with two names | One diff, one callback | - |
| WS5 (three levels) | `DELETE /properties/<p>`, then `DELETE /properties/<q>/<k>` | Target: `{p: ""}`, the replica's key deleted. Subtarget on `p`: nothing stored, no sequence spent (`subscription.py:155`) | `spec-1-5` Phase 3 |
| WS6.target | `DELETE /properties` with three properties | Read: one `{key: ""}` diff per key; the code passes `""`, which stores nothing (`actor.py:3864`, `subscription.py:155`): recorded either way | `spec-1-5` Phase 3 |
| WS7.target | `PUT /properties/transformed` (a hook upper-cases it) | The diff carries the raw request body (`handlers/properties.py:981`) | `spec-1-5` Phase 3 |
| WS8.subtarget | A write to a property outside the subtarget | Nothing | - |
| WS9.target | SDK: `actor.properties[<p>]` set, then deleted | The set sends the hook-transformed value; the delete sends `'""'` as a JSON string, which is stored and sent (`interface/property_store.py:121-126`) | `spec-1-5` Phase 3 |

Lists:

| Row | Steps on the publisher | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WL1 to WL5 (`.target`, `.subtarget`) | `POST /properties {"<l>": {"_type": "list"}}`; `PUT /properties/<l>?index=N`; `POST …/items` add, update, delete; `PUT …/metadata` | `{"index", "value"}`, `{"action": …}`; no list at the subscriber: a scalar named after the list (target; recorded by the spike), scalars `action`, `index`, `value` (subtarget) | `attribute-list-v2-port` Phase 4 |
| WL6 (`.target`, `.subtarget`) | `DELETE /properties/<l>` after an SDK `append` | Target: `{l: ""}` sent; the subscriber deletes a scalar `l` and keeps the list. Subtarget: nothing | `attribute-list-v2-port` Phase 4 |
| WL7.target | `POST /properties` with `items`: 2, 25 and 26 changes, and one mixing a list and a scalar | A text summary under the list's key | `attribute-list-v2-port` Phase 4 |
| WL8 (`.target`, `.subtarget`) | `POST /properties` creating an empty list | A text marker; at subtarget level 400 | `attribute-list-v2-port` Phase 4 |
| WL9.target | `POST /properties/<l>` with an object body | 201, root properties written, the list untouched | `spec-1-5` Phase 1 |
| WL10.target | The web-UI form routes: item add, update, delete; list create; metadata edit; property create and update; the `/www` delete of a list and of a property | Nothing for the first seven; an empty diff (stores nothing) for the deletes | `attribute-list-v2-port` Phase 4 |
| WL11.subtarget | SDK: the operations of `WL11.target` | Scalars `list`, `operation`, `item`, `index`, `length` at the subscriber; no list | `attribute-list-v2-port` Phase 4 |
| WL12.target | SDK: `append` of `0`, `""`, `False`, `None`, `[]`, `{}` | Not read | `attribute-list-v2-port` Phase 2 |
| WL13.target | SDK: an item over the span threshold, appended and updated | A reference diff; nothing applied; a WARNING at the subscriber | - |
| WL14.target | SDK: three `append`s, then `pop(-2)` | Not applied; the replica one item longer | `attribute-list-v2-port` Phase 4 |
| WL15.target | A property named `list:x` set over REST, and a list whose name the library refuses | Read: the `list:` prefix stripped before the filter (`actor.py:2919-2924`); the refused name: not read | `attribute-list-v2-port` Phase 1 |
| WL16.subtarget | `POST /properties` with two names, one the subtarget | The bulk diff at target level is narrowed to the subtarget's value (`actor.py:3999-4014`) | `spec-1-5` Phase 3 |
| WL17.target | SDK: `suspend("properties", "<l>")`, `delete` of the list, `resume` | The resync's baseline for `<l>` is empty; the replica's list: not read | `attribute-list-v2-port` Phase 3 |

Delivery:

| Row | Steps | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WD2 | One write; the format classes of the callback's and both polls' timestamps | The callback `<ts:space>`; both polls `<ts:iso-z>` | `spec-1-5` Phase 3 |
| WD3 | Two writes a second apart | One recording; the test asserts the stored timestamps are equal on DynamoDB and differ on PostgreSQL | `spec-1-5` Phase 3 |
| WD5 | SDK on a running loop (a test-process loop): `append` | The call returns before the callback is answered; the replica equal once the loop's pending tasks have run | `spec-1-5` Phase 4 |
| WD7 | Granularity `none`: a write, then SDK `sync_peer` at the subscriber | No callback; after the sync the replica has the value and a scalar `timestamp`; the queue cleared | - |
| WD9 | Grant `{"patterns": ["allowed"], "excluded_patterns": ["denied"]}`: a write to `denied`, to `allowed`, a wait of 2.5 s, a third write | Recorded by the spike: sequence 1 spent, nothing sent; 2 held; 3 triggers the resync, which polls the unfiltered queue, so `denied` and a scalar `timestamp` reach the replica; the queue cleared; **no data hook for 2 or 3** | `attribute-list-v2-port` Phase 4 (the exposure); `spec-1-5` (the hook) |
| WD11 | SDK suspend, a write, resume, with a `none` subscription | A resync callback is sent | `spec-1-5` Phase 3 |
| WD13 | Two subscribers on the second host, one write | Two callbacks in sibling order, each with its own sequence from 1 | `spec-1-5` Phase 4 |
| WD14 (`.high`, `.low`) | Five subscribers on the publisher's own host, one write | All replicas equal; for `.low` each fetch and acknowledgement nested in its callback | Kept by `spec-1-5` Phase 4 |
| WD15 | One subscriber with a target-level and a subtarget-level subscription over one list; SDK `append` | Two callbacks; the item once in the list, plus the scalars of `WL11.subtarget` | `attribute-list-v2-port` Phase 4, then `spec-1-5` Phase 3 |
| WD16 | SDK: the subscriber's callback row removed; two writes | 403 for each callback (the security plan's publisher-row rule); the publisher's row stays and each write posts again | - |
| WD17 | SDK: the publisher's trust row pointed at `wire_other_app`'s closed path; a write | The write answers; the diff is stored | - |
| WD18 (two hosts) | `POST /methods/<name>` on the publisher; the hook appends on the server's loop | The method answers first; the callback is a sibling after it (the spike's `WD10.import` shape); the replica equal after the settle | `spec-1-5` Phase 4 |
| WD19 | Hand-posted callbacks with A's bearer, each one ahead, one more than `max_pending` (5) | 204 for each held one, then 400 | - |
| WD20 | Subscribe with properties and a list present, no write | The replica holds the permitted baseline, the list included; the subscriber's profile, capability and permission fetches recorded (they run only when the baseline is non-empty, `interface/subscription_manager.py:336-338`) | - |

The queue, and the life of a subscription:

| Row | Steps | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WQ4 | `GET /subscriptions`, `?peerid=`, `?target=` as creator on both actors | Both directions listed | - |
| WQ5 | Subscribe with granularity `medium`; a write | 201; a callback with neither `data` nor `url`; 204, and the sequence advances | `spec-1-5` Phase 3 |
| WQ6 | `PUT …/<subid>` with `{"sequence": null}` | Read: an uncaught `TypeError`, recorded as a 500 | - |
| WC5 | `DELETE /<A>/trust/friend/<B>` with a queued diff and a replica | Both sides' trust and subscription rows gone, the diffs gone; the subscriber's replica and callback state gone (`actor.py:2106-2146`) | `attribute-list-v2-port` Phase 3 |
| WC6 | The publisher deleted, with a subscriber, a queued diff and a suspended target | Diffs go with their subscriptions; the suspension row stays | `subs-list-cache-lifetime` Phase 2 |
| WC7 | SDK: the publisher created again under the same id; a write | Starts suspended and registers nothing | `subs-list-cache-lifetime` Phase 2 |
| WC8 | `WC3` and `WC4` again, recording the lifecycle hooks | `subscription_deleted` with `initiated_by_peer` at each side | - |
| WM1 | SDK, one `Actor` instance: create a subscription for a second subscriber, then write | Read: the instance's memoised subscription list (`actor.py:2466-2469`) misses the new subscriber, which gets no callback | `subs-list-cache-lifetime` Phase 1 |

Permissions between peers:

| Row | Steps | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WP2 | The grant shrunk while the subscriber holds a list it no longer covers | Not deleted (the consumer's default) | - |
| WP3 | The grant deleted | A permission callback; the subscriber's stored permissions: not read | `spec-1-5` Phase 2 |
| WP4 | `WP1`'s recorded body posted again after a newer one, with the bearer | Ignored (older timestamp), 204 | `spec-1-5` Phase 2 |
| WP5 | Subscribe while the publisher has data, with peer profiles on | The profile fetch recorded inside the subscribe, with what it returns | `spec-1-5` Phase 2 (default deny) |
| WP6 | A baseline under a narrow grant (`excluded_patterns`) | What the baseline fetch returns for an excluded property | `spec-1-5` Phase 2 |

### New Tests, both unit and integration tests

- The rows above, integration, both backends, both topologies unless a row
  says otherwise.
- `WD3`'s assertion on stored timestamps, per backend.
- Registry checks in `tests/integration/verify_groups.py`: every scenario
  has a recording and every recording a scenario; every second file has a
  reason; every row has an owner.

### Failure Scenarios

- A recording captures a harness artefact - a cold cache, a setup request,
  a background task; the spike's rules apply (warm cache, setup unrecorded,
  `settle` conditions), and a row that still varies stops the phase.
- A timing-dependent recording - order is nesting and sibling order, never
  time; the only fixed wait is `WD9`'s. Five consecutive runs per backend
  before the commit, never rerun in CI.
- Someone re-records to make a red run green - explicit row ids and the
  reason line; the phase's verification reads the stat against the rows it
  names.
- A row cannot be made deterministic - dropped from the registry with the
  reason under "Recorded outcomes", never kept with a rerun.
- `WD5` asserts a lifetime the garbage collector decides - the scenario
  awaits the loop's pending tasks before it snapshots.
- `WM1` depends on an instance the HTTP path never reuses - it is SDK-only
  by design; it is the one row that can show the stale memo.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time, both backends
- [ ] `poetry run pytest tests/ -m wire -p no:rerunfailures` passes five
      times in a row on each backend, sequentially, and once under
      `make test-all-parallel`
- [ ] `git diff --stat master...HEAD -- actingweb examples` is empty
- [ ] `git diff --stat master...HEAD -- tests/integration/wire` shows no
      change to a recording the security plan made
- [ ] Sensitivity, on a scratch copy and not committed: each of these
      changes at least one recording, and the rows are noted: the `/items`
      add diff's key renamed; `callback_subscription` returning before it
      sends; the `PUT` clear made a no-op; the permission filter returning
      its input; `apply_callback_data` skipping list operations; one key
      added to the callback body
- [ ] "Recorded outcomes" filled: one line for every row whose recording
      differs from "Expected from reading", and one per "not read"

### Recorded outcomes

Filled by the first recording. Already known from the spike: `WL1.target`'s
scalar replica, `WD9` as in the table, the resync and import shapes of
`WD10.import`.

### Implementation Status: Not Started

---

## Phase 2: the existing files, documentation and records

### Changes

Retired, each deletion naming its covering row or unit test in the
verification document:

- `tests/integration/test_subscription_suspension_flow.py` - it posts to
  `/subscriptions/suspend`, which no handler serves, and accepts six
  statuses (`:205`, `:1133`); `WD10`, `WD10.import`, `WD11`, `WL17` and the
  unit suspension tests cover suspension.
- `tests/integration/test_subscription_processing_flow.py` - the sequencing
  and back-pressure classes, which run against `peer_app` with no processor
  (`:565-582`, `:1249-1262`); `WD8`, `WD9`, `WD19` and
  `tests/test_callback_processor.py` cover them. Its publisher-queue tests
  stay and are tightened.
- `tests/integration/test_fanout_flow.py:413-1058` - the classes that test
  `FanOutManager`, a granularity downgrade and a circuit breaker, none on
  the publish path; the first class (`:16-410`, several subscribers on the
  real publish path) is kept, renamed for what it does.
- `tests/integration/test_property_list_notifications.py` - seven
  placeholders; `WL1` to `WL8`.
- `tests/integration/test_list_diff_peer_replica.py` - `WL11.target`,
  `WL13`.

Tightened:

- Every `status_code in […]` and every assertion guarded by `if
  …status_code` in the remaining `test_subscription_*.py`,
  `test_property_notifications.py`, `test_fanout_flow.py` and
  `test_trust_flow.py` becomes one unconditional status. Exceptions:
  `test_subscription_baseline_storage.py:71-93` and
  `test_subscription_sync_coverage.py:321-327`, which rely on the stray
  write `WL9` records; tightened to what the run shows, with a registry
  note naming `spec-1-5` Phase 1.
- The `pytest.skip` calls for missing earlier state become class-scoped
  fixtures, so a failed setup fails.

Documentation and records:

- `tests/integration/README.md`, `XDIST_GROUPS.md`,
  `docs/contributing/testing.rst` - the wire suite: what a recording holds,
  how to re-record one row (explicit ids, the reason line), the one-tier
  rule, the owner column; the stale counts and file names go.
- The four plans after this one - a dated line in each Update Log listing
  the recorded outcomes that contradict it and the rows it owns.
- `thoughts/plans/2026-11-06-spec-1-5.md` - a dated Update Log line: the
  gap resync's skipped data hook is its to fix (owner, 2026-11-07), shown by
  `WD9`.

### New Tests, both unit and integration tests

- None new; the changed files are the tests.

### Failure Scenarios

- A tightened status differs between backends - a real backend difference;
  recorded and reported, not loosened.
- A fixture conversion changes the order tests relied on - each converted
  class passes alone (`-k <class>`) as well as in the file.
- Class-scoped fixtures under CI's reruns - checked on one deliberately
  failing test before the commit.
- A deleted test was the only cover for something - each deletion names the
  row or unit test that covers it.

### Verification

- [ ] Run the contract's `### Checks` full tier verbatim (docs build included)
- [ ] `grep -nE "status_code (in|not in) [\[\(]|if .*status_code" tests/integration/test_subscription_*.py tests/integration/test_property_notifications.py tests/integration/test_fanout_flow.py tests/integration/test_trust_flow.py`
      returns only the two registry-listed exceptions
- [ ] `grep -c "pytest.skip(" tests/integration/test_subscription_*.py tests/integration/test_fanout_flow.py`
      shows 0 for each file
- [ ] `git diff --stat master...HEAD -- actingweb examples` is empty
- [ ] `poetry run python tests/integration/verify_groups.py` passes

### Implementation Status: Not Started

---

## Evaluation Notes

Reviewed 2026-11-06 as "Phase 0" of the security plan, before the owner moved
it here: one evaluator read every expectation against the code (tests,
quality and architecture), and the outside voice ran Codex (outside the
command sandbox) and a fresh-context reviewer. Security, scalability and
usability evaluators were not run: the plan changes no library code and no
public surface. What each finding led to:

### Architecture

- The recorder is feasible as a pure ASGI middleware added after
  `integrate_fastapi`, and has to record an exception as a 500. It records
  every request to the two wire apps, not only `/callbacks`: the fetch, the
  acknowledgement and the peer-to-peer deletes are on other paths.
- An `ActorInterface` built in the test process with a fresh `Config` (as
  `test_list_diff_peer_replica.py:93-113` does) has the default host, no
  synchronous flag and no peer options. The driver builds it from the wire
  app's own configuration; `WD5` uses a copy with the flag off.
- `with_peer_capabilities` is neither needed nor sufficient for a resync
  callback: the trust row's capability and its fetch time decide
  (`actingweb/peer_capabilities.py:81-145`). The fallback row sets both
  through the library.
- Five subscribers on the publisher's own host are safe with the serial
  sender (two or three executor threads per chain, ten available,
  `fastapi_integration.py:621`); `WD14.low` exists because a concurrent
  sender would need eleven.

### Tests and code quality

- About a dozen first-draft expectations were wrong or true at one level
  only; they are corrected in the tables and in the research, and are the
  reason for recordings.
- Rows whose outcome depends on the subscription level or the grant are
  split per level, and the grant is stated.
- The first draft's rule (a `Changes in:` line in each test's docstring,
  checked by grep) could not tell rows in one file apart and only checked
  that a plan file existed. One recording per row replaces it.
- The first draft's counts (185, 62) were greps; the verified counts are 179
  status lists, 47 guarded assertions and 61 skips.
- Three consecutive runs do not find an infrequent flake and CI's reruns
  hide one; five runs, and no reruns for the marker.
- One commit was too large; the harness and fourteen rows are the security
  plan's, the remaining rows are Phase 1 here, the existing files Phase 2.

### Outside voice

- **The baseline delayed the security fix and put passing exploit tests in
  public history** (Codex and the fresh-context reviewer). The owner moved
  the baseline here; the access rows are recorded secured.
- **No release path delivers the fix before 3.16** (the consumer pins
  `=3.15.1`; tags come from `master` only). Put to the owner: it stays in
  3.16.
- **A golden transcript is the simpler mechanism for "the run decides".**
  Taken, by the owner's decision.
- **A check that parses `thoughts/plans/` never runs in CI.** The registry
  is under `tests/integration/wire/`.
- **Stopping the phase to correct plans that are not approved would gate
  everything on them.** Contradictions are recorded here and fixed in each
  plan's next draft.
- **Rows whose "after" is as open as their "before" constrain nothing**
  (`WL12`, `WC6`, parts of `WD5`). Their registry entries say "observed";
  they are not in any later phase's must-stay-identical list until the plan
  that owns them states the outcome.
- **The two topologies differ in cache warmth, and neither is Lambda.**
  Stated as the known topology difference; a registry reason is required.
- **Consumer paths the first draft missed**: a write from an asynchronous
  hook on the server's loop (`WD18`), the peer-profile read (`WP5`), and the
  data hook's payload (the recording hooks, in every row).
- **Cleanup through HTTP swallows failures and cannot delete a recreated
  actor** (`conftest.py:785-786`). The pair's teardown goes through the
  library by id, removes suspension rows, and fails loudly.
- **Line references into `tests/integration/` in the later plans go stale**
  once this plan rewrites those files. Each later plan's Update Log says its
  references there are by test and fixture name from now on.

### Second review, 2026-11-06: recorded, not folded

Two evaluators read the mechanism against the code (feasibility; tests and
quality, with the security, cost and usability of the recordings), then the
outside voice (Codex, outside the command sandbox, and a fresh-context
reviewer) was given their findings. Nothing was run. `[decision]` and
`[research]` as in the security plan.

What is missing:

- **The consumer's one bulk flow has no row.** Its import suspends and
  resumes one subtarget, from an asynchronous handler, around a `clear` and
  appends on a list, with a target-level subscriber
  (`../actingweb_mcp/api/memory_import.py:434`, `:584`). `WD10` suspends the
  whole target and never enters the branch that wraps a list as
  `{subtarget: {"_list": True, "items": …}}` (`actingweb/actor.py:3168`);
  the `ListAttribute` plan cites `WD10` as its list-baseline proof.
- **No row can show a stale subscription memo**, the `subs_list` plan's
  actual risk: every HTTP request builds a fresh `Actor`. It needs an SDK
  row that creates a subscription and writes on one instance.
- Wire-visible changes in the later plans that no row shows: refused list
  names and `list:` scalar keys, a bulk POST at subtarget level, a
  three-segment DELETE, a list removed during suspension, default deny on a
  baseline under a narrow grant. The `ListAttribute` plan lists `WS3` to
  `WS8` as identical though its subtarget-level receiver change would alter
  `WS3` and `WS5` below target level. `[research]`
- `WP5`'s premise is wrong: no profile is fetched when a trust is
  established; it is fetched inside a subscribe when the publisher already
  has data (`interface/subscription_manager.py:336-338`, `:2406-2434`),
  together with capability and permission fetches. Rows have to state the
  publisher's state at subscribe time.

Determinism, all to be designed before a row is recorded:

- Callback order and array order follow random ids: subscriptions come back
  sorted by `peerid:subid` (`db/postgresql/subscription.py:445`,
  `db/dynamodb/subscription.py:278`), so rows with several subscribers and
  every `GET /subscriptions` array flip between runs. Name actors by first
  appearance and sort siblings.
- The permission callback's follow-up fetches iterate a set difference
  (`peer_permissions.py:721-725`): hash-seed order.
- The gap timeout is wall-clock since the oldest held callback
  (`callback_processor.py:422-428`), so any row that holds a callback and
  continues races the wire apps' 2 seconds (`WD19`, `WS2.subtarget`), not
  only `WD9`. A long timeout on the apps, a short one for `WD9` alone.
- The normaliser replaces timestamps with names, which contradicts `WD2`
  (format) and `WD3` (distinct values); tokens have to keep format class and
  equality, or one later change rewrites every recording.
- Nesting by time is the only way to attribute a callback (only `AwProxy`
  sends a correlation header, `aw_proxy.py:93-112`); it holds only while no
  request arrives outside a step. The recorder should fail on that, and
  under a concurrent sender it cannot attribute a low-granularity fetch.
- The teardown as written cannot pass: `Actor.delete` leaves a tombstone for
  30 days (`actingweb/deletion.py:160-172`) and sends peer DELETEs after the
  last step. Per-row teardown is not isolation either: one table namespace
  per worker, shared with every other integration test. `[research]`

The contract and its size:

- `[decision]` **Full transcripts or a projection.** A byte-identical record
  of every request makes cache warmth, setup traffic and incidental fetches
  contractual: a boolean in a trust response or a content type on `/meta`
  rewrites every file and teaches reviewers to ignore diffs. Proposed: for
  most rows record hook payloads, callback bodies and statuses, the queue's
  change and the replica's change (what the consumer reads,
  `../actingweb_mcp/hooks/actingweb/callback_hooks.py:95`, `:122`); the full
  request list only where absence or choreography is the point (`WD6`,
  `WD9`, `WC3`, `WC4`, `WP1`). Either way: record from the first scenario
  step, not setup.
- `[decision]` **Two tiers.** About thirty row-variants as the regression
  net at full ceremony (the consumer's shape: target level, high
  granularity, REST and interface list edits, the import flow, gap and
  resync, several subscribers, the lifecycle rows, permission callbacks);
  the rest recorded once as observations in one topology, in no
  must-stay-identical list until the plan that owns them is approved. Two of
  those plans will be redrafted, and a matrix pinned for them will change.
  What it lets slip: drift below target level and at low granularity during
  the `subs_list` and email PRs.
- `[decision]` **Phase 2: retire, not tighten.**
  `test_subscription_suspension_flow.py` never suspends anything (it posts
  to `/subscriptions/suspend`, which no handler serves, and accepts six
  statuses, `:205`, `:1133`); the sequencing and back-pressure classes of
  `test_subscription_processing_flow.py` run against apps with no processor
  (`:565-582`, `:1249-1262`); `test_fanout_flow.py:413-1058` tests features
  that do not run. Those three files hold 100 of the 179 loose statuses and
  38 of the 61 skips. Moving them to a processing app changes what they
  test; deleting them once the rows exist leaves a small tightening of the
  publisher-queue files. If any subscriber is moved, it goes to
  `subscriber_app`, never to a recording app.
- **Guarding against re-recording to green.** A stat read by a person is the
  only guard. Proposed: a digest per file and an append-only reason line in
  the registry; re-recording takes explicit row ids. Driver changes land in
  their own commit with no recording diff, and the registry carries a driver
  version, or a file can stay identical because the comparer changed with
  the library (`thoughts/plans/2026-11-06-attribute-list-v2-port.md`, Phase
  3).
- **The fourteen cannot stay unchanged.** Every determinism fix above
  rewrites them, and this plan forbids that. Proposed: the security plan's
  Phase 0 is the spike with a handful of rows; this plan opens with a
  driver-only commit that re-records them with no diff under `actingweb/`.
- **Secrets.** Actor creation returns `passphrase`
  (`handlers/factory.py:324-325`); trust creation and the single trust GET
  return `secret` and `verification_token` (`handlers/trust.py:489`,
  `:596-603`); the reciprocal request carries `secret` and `verify`
  (`actor.py:1727-1729`). Redaction by known value misses library-generated
  tokens: redact by key name, guard against token-shaped strings, and use
  `example.test` creators.
- **"Identical" is proven by a run, not by an empty stat.** The later plans'
  phases cite the full tier, which today runs the wire rows only under
  `-n auto` (`Makefile:58`). The checks need a sequential wire line without
  reruns; a `flaky(reruns=0)` marker does override CI's reruns.
- **Cost.** About 87 row-variants in two topologies is about 170 scenarios
  per backend run; five consecutive runs pass a 5% flake 77% of the time and
  cost about 1,700 scenario runs per phase behind "one test run at a time".
  Repeat only the rows a phase records. `[research]` wall time: unmeasured,
  with a 30-minute CI job limit.
- Smaller: the replica snapshot must read lists and scalars separately (a
  scalar hides a list of the same name, `remote_storage.py:255-281`); the
  snapshot does not hold trust rows or stored permissions, which `WC5` and
  `WP3` claim; `WD16`'s step also wipes the replica; a copied configuration
  for `WD5` rebuilds six process-wide stores; handler exceptions never reach
  the recorder; the form routes are not JSON; a mismatch should write the
  actual recording beside the expected one; the guarded-assertion count is
  48.

Only a spike answers: whether a same-host callback nests inside its write;
whether a target-level row matches across backends without a second file;
how large a recording is; how long one wire run takes; whether a resume on
the loop emits a capability fetch at an unpredictable time; whether the
teardown can pass on both backends.

### Unverified notes

- Nothing in this plan has been run. Every expectation is from reading.
- Whether a `flaky(reruns=0)` marker overrides CI's `--reruns 2`; if not, the
  wire step is the only place the marker runs.
- Whether `pytest-rerunfailures` re-creates a class-scoped fixture on a
  rerun.
- The recorder's list grows for a session; its entries are small, but no
  bound was measured.
- Whether the inbound permission store behaves differently with
  `peer_permissions_caching` off; the wire apps have it on.
- The suspension store's subtarget semantics were not read.
- No REST route for suspend and resume was found in the handlers read; the
  route table and `/devtest` were not searched to the end.
