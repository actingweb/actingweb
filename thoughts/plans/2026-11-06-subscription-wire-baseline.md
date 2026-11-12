---
status: done
verified: thoughts/verifications/2026-11-12-subscription-wire-baseline-4.md
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
- **2026-11-07, review of the redraft folded**: two evaluators and the
  outside voice; under "Third review". Two decisions (owner): `rows.toml` is
  the only copy of which phase may change which recording, by plan and
  phase, checked by `verify_groups.py`; the old Phase 2 is split into
  Phases 2 (retire), 3 (tighten) and 4 (documentation and records) in the
  same PR. Row expectations and owners corrected; `WP5` merged into `WD20`.
- **2026-11-08, from the security plan's implementation**: "What Already
  Exists" points at `rows.toml` instead of listing rows. Landed beyond this
  plan's text there: the snapshot already holds both sides' trust rows, the
  publisher's grant and the subscriber's peer permissions (this plan's
  Phase 1 first commit needs only the `WD18` hook and the async steps);
  `WIRE_RECORD` takes row ids; the registry check covers `[reserved]`
  owners and ranges, but not the `Wire-Phase` trailer, which stays this
  plan's.

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
This plan adds every other flow on the same harness, retires the legacy
files and tightens the rest. What follows it: each of the four plans after
it may change only the recordings `rows.toml` assigns to its phase; every
other recording stays byte-identical (one tier, gate 5).

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
- [New 2026-11-07] **One tier** (owner): every row is in the regression set.
  There is no "observed" state; the first draft's note that `WL12`, `WC6`
  and parts of `WD5` are observations is withdrawn.
- [New 2026-11-07] **`rows.toml` is the only copy of which phase may change
  which recording** (owner, review of the redraft): each row variant names
  its owners as `plan:phase`; `verify_groups.py` checks that every
  recording a commit changes is owned by the phase the commit implements
  (named in the commit message trailer `Wire-Phase: <plan>:<phase>`). The
  later plans quote it and drop their own "Re-recorded" and "Identical"
  lists at their next draft; their Update Logs say so from this redraft.
- [New 2026-11-07] **Retire the legacy files** (owner): the files that test
  nothing on the publish or receive path go once a row covers what they
  meant to; each deletion names its covering row or unit test.
- [New 2026-11-07] **Three phases after the recordings, one PR** (owner,
  review of the redraft): retire, tighten, documentation and records, each
  its own commit.
- [New 2026-11-07] **The gap resync's skipped data hook is `spec-1-5`'s to
  fix** (owner): `WD9` records it, owned by `spec-1-5:3` as well as
  `attribute-list-v2-port:4`.
- [New 2026-11-07] **Exposure rows are recorded here** (owner, 2026-11-06,
  when `WD9` moved here): the security plan's rule that no test passes
  because a hole is open is scoped to that PR. A row that records data
  reaching a peer that may not read it is marked `exposure = true` in
  `rows.toml` (`WD9`, `WS2.subtarget`, `WP6`, and `WL16` if its recording
  shows it), and `verify_groups.py` lists them.
- **A recording is what the library does, right or wrong**; its registry
  entry says what is known to be wrong.
- **The "Expected from reading" columns are not assertions**; each first
  recording is reviewed against them and every difference goes into
  "Recorded outcomes".
- **One file per row variant**; a second file only for a declared backend
  or topology difference with a reason.
- **The registry lives under `tests/integration/wire/`.**
- **Wire tests never rerun.**
- **Later plans add rows** under ids reserved for them in `rows.toml`.

Deduced; confirm at approval:

- **Re-recording takes explicit row ids** (`WIRE_RECORD=WD9,WS1.target`),
  never "all", and appends a dated reason line to the row's entry.
- **A driver or harness change lands in its own commit with no recording
  diff**; Phase 1 opens with one (the `WD18` hook and the snapshot
  extension).
- **Order inside a recording follows first appearance**; the permission
  callback's follow-up fetches are recorded sorted by path.

## What We're NOT Doing

- **Changing any behaviour** - no diff under `actingweb/` or `examples/`.
- **The access and trust rows** - the security plan's (`WA*`, `WT*`).
- **Endpoints outside the subscription path** - the specification plan's.
- **Fault injection over HTTP** - the unit suites have the seams.
- **A mixed-version pair** - one suite runs one version.
- **The consumer's identity options** - nothing they change travels between
  two actors.
- **Synchronous callbacks on the wire apps** - with the flag on, the
  consumer's import flow deadlocks (spike note); the consumer sets it only on
  Lambda.
- **Rewriting the unit suites** - they stay.
- **`WP5` as its own row** - `WD20` records the same subscribe-time profile
  fetch with the wire apps' profile setting on; one row, one owner.

## What Already Exists

Landed by the security plan, which merges before this plan: its Phase 0
lands the harness (from the spike, `spike/subscription-wire-harness`),
`rows.toml` and its Phase 0 rows; its Phases 1 to 3 add `WA1` to `WA18` and
`WT1` to `WT5`.

- `tests/integration/_wire.py` - recorder, driver (`Scenario.step` with a
  `settle` condition), snapshot (A's queue, B's replica as scalars and lists
  read separately, callback state, both sides' subscription rows, A's
  suspension rows), normaliser (format-class timestamp tokens, sorted keys,
  ids, subscription ids, hosts, secrets, mid-row names; a guard that fails
  on any 32-hex string, `localhost:55xx` or unknown bearer that survives),
  comparer (`WIRE_RECORD`, refused under `CI`; a mismatch writes
  `<row>.actual.json`).
- `tests/integration/test_harness.py` - keyword options (the wire apps run
  with processing, capabilities, permissions and profiles on, synchronous
  callbacks off, a 2 s gap timeout, `max_pending` 5), recording hooks, the
  `wire_import` method, the `subscriber` and `subscriber_adopted` types.
- `tests/integration/conftest.py` - `wire_app` 5561, `wire_peer_app` 5562,
  `wire_other_app` 5563 (the same worker's tables), `wire_pair`.
- `tests/integration/wire/` with `rows.toml`, the list of rows and their
  owners (the only copy; read it rather than a list here). The security
  plan's rows are its Phase 0 flows, `WA1` to `WA18` and `WT1` to `WT5`;
  the schema has a `topologies` key (one file per topology) beside
  `second`, and `WIRE_RECORD` takes row ids.
- The `wire` marker and its CI step (no reruns, its own junit file; the wire
  step fits the 30-minute job at about 3.5 minutes per backend with this
  plan's rows).

Already in the tree:

- `tests/integration/test_list_diff_peer_replica.py` - `WL11.target` and
  `WL13` take its cases (its WARNING assertion moves to `WL13`'s test).
- `tests/integration/test_subscription_callback_flows.py:199-224`,
  `:339-368`, `:497-519` - kept, tightened.
- `tests/integration/test_property_notifications.py:134-137` - kept.

## Phase 1: the remaining flows, recorded

Row identifiers continue the security plan's. A suffix is the variant:
`.target`, `.subtarget`, `.resource` for the subscription level, `.high`,
`.low` for granularity; "(three levels)" means all three variants. Unless a
row says otherwise: granularity `high`, a grant of `*`, both topologies, a
warm capability cache, writes over REST. "SDK" marks a step in the test
process through an `ActorInterface` built from the wire app's
configuration. A row that restricts reads grants with `excluded_patterns`.
"Owners" is what `rows.toml` records (`plan:phase`; AL =
`attribute-list-v2-port`, SL = `subs-list-cache-lifetime`, S = `spec-1-5`).

### Changes

First commit, no recording diff (a harness change):

- `tests/integration/test_harness.py` - an asynchronous method hook that
  appends to a list through the interface (`WD18`).
- `tests/integration/_wire.py` - the snapshot gains both sides' trust rows
  (secrets redacted by key) and B's stored peer permissions (`WC5`, `WP3`);
  async steps (`Scenario.step` accepts a coroutine and awaits it, and a
  `settle` that awaits the loop's pending tasks) for `WD5`.
- `tests/integration/verify_groups.py` - the `rows.toml` checks: every
  scenario has a recording and every recording a scenario; every second
  file has a reason; every row variant has owners; the commit's changed
  recordings are owned by its `Wire-Phase` trailer; exposure rows listed.
- `tests/integration/wire/rows.toml` - the schema, documented at its top:

  ```toml
  [reserved]                      # id ranges a later plan may add
  "attribute-list-v2-port" = ["WD21-WD29", "WL18-WL29"]
  "spec-1-5" = ["WS10-WS19", "WL30-WL39", "WA19-WA29"]
  "subs-list-cache-lifetime" = ["WM2-WM9"]
  "email-as-creator-at-write-time" = ["WE1-WE9"]

  [rows."WS1.subtarget"]
  test = "test_wire_scalar_properties.py::test_ws1"
  owners = ["attribute-list-v2-port:4"]
  exposure = false
  expected = "The object stored as one scalar per key; ..."
  reason = ["2026-11-07 first recording (subscription-wire-baseline:1)"]
  # a declared second file: second = { file = "WS1.subtarget.postgresql.json", why = "..." }
  ```

Second commit: the rows below, their files and entries.

- `tests/integration/test_wire_scalar_properties.py`,
  `test_wire_list_properties.py`, `test_wire_delivery.py`,
  `test_wire_queue_and_lifecycle.py`, `test_wire_permissions.py`.

Scalar properties:

| Row | Steps on the publisher | Expected from reading | Owners |
| --- | --- | --- | --- |
| WS1.subtarget | `PUT /properties/<p>` with an object, then a string, then `""` | The object stored as one scalar per key; the string answers 400 at the subscriber and stores nothing; the empty value answers 204 | AL:4 |
| WS2.subtarget | The same with a grant of exactly `<p>` | For the object: a sequence number spent and no callback; the string sent unfiltered. Exposure | AL:4 |
| WS3 (three levels) | `PUT /properties/<p>/<k>`, then `PUT /properties/<p>/<k>/<j>` | Target `{p: {k: v}}`; the replica's `p` loses its other keys | `.target` S:3; `.subtarget`, `.resource` AL:4, S:3 |
| WS4.target | `POST /properties` with two names | One diff, one callback | - |
| WS5 (three levels) | `DELETE /properties/<p>`, then `DELETE /properties/<q>/<k>` | Target: `{p: ""}`, the replica's key deleted. Subtarget on `p`: nothing stored, no sequence spent (`subscription.py:155`) | `.target` -; `.subtarget`, `.resource` AL:4, S:3 |
| WS6.target | `DELETE /properties` with three properties | Three diffs `{key: ""}`, one per key with its own sequence (`interface/property_store.py:126`, through `clear()`), and two registrations of `""` that store nothing (`property_store.py:215`, `handlers/properties.py:1770`) | S:3 |
| WS7.target | `PUT /properties/transformed` (a hook upper-cases it) | The diff carries the raw request body (`handlers/properties.py:981`) | S:3 |
| WS8.subtarget | A write to a property outside the subtarget | Nothing | - |
| WS9.subtarget | SDK: `actor.properties[<p>]` set, then deleted | The set sends the hook-transformed value; the delete sends `'""'`, which is truthy, so it is stored and sent and passes the filter unfiltered (`actor.py:2904-2906`), unlike `WS5.subtarget` | AL:4, S:3 |

Lists:

| Row | Steps on the publisher | Expected from reading | Owners |
| --- | --- | --- | --- |
| WL1 to WL5 (`.target`, `.subtarget`) | `POST /properties {"<l>": {"_type": "list"}}`; `PUT /properties/<l>?index=N`; `POST …/items` add, update, delete; `PUT …/metadata` | `{"index", "value"}`, `{"action": …}`; no list at the subscriber: a scalar named after the list (target), scalars `action`, `index`, `value` (subtarget) | AL:4 |
| WL6 (`.target`, `.subtarget`) | `DELETE /properties/<l>` after an SDK `append` | Target: `{l: ""}` sent; the subscriber deletes a scalar `l` and keeps the list. Subtarget: nothing | AL:4 |
| WL7.target | `POST /properties` with `items`: 2, 25 and 26 changes, and one mixing a list and a scalar | A text summary under the list's key | AL:4 |
| WL8 (`.target`, `.subtarget`) | `POST /properties` creating an empty list | A text marker; at subtarget level 400 | AL:4 |
| WL9.target | `POST /properties/<l>` with an object body | 201, root properties written, the list untouched | S:1 |
| WL10.target | The web-UI form routes (item add, update, delete; list create; metadata edit; property create and update) and the `/www` delete of a list and of a property | Nothing for the first seven; for the deletes an empty registration that stores nothing | AL:4 |
| WL11.subtarget | SDK: the operations of `WL11.target` | Scalars `list`, `operation`, `item`, `index`, `length`; no list | AL:4 |
| WL12.target | SDK: `append` of `0`, `""`, `False`, `None`, `[]`, `{}` | Not read | AL:2 |
| WL13.target | SDK: an item over the span threshold (390,000 bytes on the wire apps), appended and updated | A reference diff; nothing applied; the test asserts the subscriber's WARNING | AL:4 |
| WL14.target | SDK: three `append`s, then `pop(-2)` | Not applied; the replica one item longer | AL:4 |
| WL15.target | With a grant excluding `x`: a property named `list:x` set over REST | The filter strips `list:` before evaluating (`actor.py:2910-2916`), so the excluded `x` is withheld; what listings and the baseline do with `list:x`: not read | AL:4 |
| WL16.subtarget | `POST /properties` with two names, one the subtarget | The bulk diff narrowed to the subtarget's value (`actor.py:3999-4014`) | AL:4 |
| WL17.target | SDK: `suspend("properties", "<l>")`, `delete` of the list, `resume` | B's baseline GET of `<l>` answers an error; the fetch returns nothing and `{}` is applied (`interface/subscription_manager.py:2191-2196`, `handlers/callbacks.py:589-595`); the replica keeps the list | AL:4 |

Delivery:

| Row | Steps | Expected from reading | Owners |
| --- | --- | --- | --- |
| WD2 | One write; the format classes of the callback's and both polls' timestamps | The callback `<ts:space>`; both polls `<ts:iso-z>` | S:3 |
| WD3 | Two writes a second apart | One recording; the test asserts the stored timestamps are equal on DynamoDB and differ on PostgreSQL | S:3 |
| WD5 | Async step, SDK on the test's running loop: `append` | The call returns before the callback is answered; the replica equal once the loop's pending tasks have run | S:4 |
| WD7 | Granularity `none`: a write, then SDK `sync_peer` at the subscriber | No callback; the sync's profile, capability and permission fetches (`subscription_manager.py:1669-1720`); the replica has the value and a scalar `timestamp`; the queue cleared | - |
| WD9 | Grant excluding `denied`: a write to `denied`, to `allowed`, a wait of 2.5 s, a third write | As the spike recorded: sequence 1 spent, nothing sent; 2 held; 3 triggers the resync, which polls the unfiltered queue, so `denied` and a scalar `timestamp` reach the replica; the queue cleared; no data hook for 2 or 3. Exposure | AL:4, S:3 |
| WD11 | SDK suspend, a write, resume, with a `none` subscription | A resync callback is sent | S:3 |
| WD13 | Two subscribers on the second host, one write | Two callbacks in sibling order, each from sequence 1 | S:4 |
| WD14 (`.high`, `.low`) | Five subscribers on the publisher's own host, one REST write | All replicas equal; callbacks one after another (the write runs in the executor, `actor.py:2790-2793`); for `.low` each fetch and acknowledgement nested in its callback | - |
| WD15 | One subscriber with a target-level and a subtarget-level subscription over one list; SDK `append` | Two callbacks; the item once in the list, plus the scalars of `WL11.subtarget` | AL:4, S:3 |
| WD16 | SDK: the subscriber's callback row removed with `delete_subscription(callback=True)`; two writes | The subscriber's replica wiped with the row (`actor.py:2558-2580`); each callback 403 (the security plan's publisher-row rule; 404 before it); the publisher's row stays and each write posts again | - |
| WD17 | SDK: the publisher's trust row pointed at an unbound port; a write | The write answers; the diff is stored; nothing recorded on the wire | - |
| WD18 (two hosts) | `POST /methods/<name>` on the publisher; the hook appends on the server's loop | The method answers first; the callback a sibling after it (the spike's `WD10.import` shape); the replica equal after the settle | S:4 |
| WD19 | Hand-posted callbacks with A's bearer, each one ahead, one more than `max_pending` (5) | 204 for each held one, then 400 | - |
| WD20 | Subscribe with properties and a list present, no write | The permitted baseline, the list included; the profile, capability and permission fetches the wire apps' settings turn on (`subscription_manager.py:2419-2467`), run only because the baseline is non-empty (`:336-338`) | S:2 |

The queue, and the life of a subscription:

| Row | Steps | Expected from reading | Owners |
| --- | --- | --- | --- |
| WQ4 | `GET /subscriptions`, `?peerid=`, `?target=` as creator on both actors | Both directions listed | - |
| WQ5 | Subscribe with granularity `medium`; a write | 201; a callback with neither `data` nor `url`; 204, and the sequence advances | S:3 |
| WQ6 | `PUT …/<subid>` with `{"sequence": null}` | The `TypeError` is not caught by the handler (`handlers/subscription.py:405-411`) and is answered 500 by the integration's catch-all (`fastapi_integration.py:2759-2791`) | - |
| WC5 | `DELETE /<A>/trust/friend/<B>` with a queued diff and a replica | Both sides' trust and subscription rows gone, the diffs gone; B's replica and callback state gone (`actor.py:2106-2146`) | - (run by hand in AL:3) |
| WC6 | The publisher deleted, with a subscriber, a queued diff and a suspended target | Diffs go with their subscriptions; the suspension row stays | SL:2 |
| WC7 | SDK: the publisher created again under the same id; a write | Starts suspended and registers nothing | SL:2 |
| WC8 | `WC3` and `WC4` again, recording the lifecycle hooks | `subscription_deleted` with `initiated_by_peer` at each side | - |
| WM1 | B1 subscribed. SDK, one `Actor` instance of A: a write (its memo becomes `[B1]`); B2 subscribes over REST; the same instance writes again | B2 gets no callback for the second write: the memo is reset only on that instance's own creates (`actor.py:2345-2353`, `:2468-2471`) | SL:2 |

Permissions between peers:

| Row | Steps | Expected from reading | Owners |
| --- | --- | --- | --- |
| WP2 | The grant shrunk while the subscriber holds a list it no longer covers | Not deleted (the consumer's default) | - |
| WP3 | `DELETE /<A>/trust/<rel>/<B>/permissions` | No permission callback (`trust_permissions.py:563-594` does not notify); B's stored permissions unchanged and stale | S:2 |
| WP4 | `WP1`'s body posted again after a newer one, with the bearer | Not stored (older timestamp); the change detection on the older body still runs and the hook payload carries its `permission_changes` (`handlers/callbacks.py:253-258`, `:329-336`) | S:2 |
| WP6 | A baseline under a grant excluding one property | What B's baseline fetch returns for the excluded property. Exposure if it is returned | S:2 |

### New Tests, both unit and integration tests

- The rows above, integration, both backends, both topologies unless a row
  says otherwise.
- `WD3`'s timestamp assertion per backend; `WL13`'s WARNING assertion.
- The `rows.toml` checks in `verify_groups.py`, each with a test that a
  planted violation fails it.
- The normaliser's guard over every new file: a planted secret, actor id,
  `localhost:5563` or unknown bearer in any of them fails.

### Failure Scenarios

- A recording captures a harness artefact - the spike's rules (warm cache,
  setup unrecorded, `settle` conditions); a row that still varies stops the
  phase.
- A timing-dependent recording - order is nesting and sibling order; the
  only fixed wait is `WD9`'s. Five consecutive runs per backend before the
  commit (a local, pre-commit step, about 35 minutes), never rerun in CI.
- Someone re-records to make a red run green - explicit ids, the reason
  line, and `verify_groups.py` refusing a changed recording the commit's
  phase does not own.
- A row cannot be made deterministic - dropped with the reason under
  "Recorded outcomes".
- `WD5`'s task outlives the step - the async `settle` awaits pending tasks.
- `WM1` shows nothing because the memo was empty - the first write fills it
  with `[B1]`; the test asserts that before B2 subscribes.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Run the contract's `### Checks` full tier before each commit, one run
      at a time, both backends
- [x] The first commit's `git show --stat HEAD -- tests/integration/wire` is
      empty apart from `rows.toml`'s schema header
- [x] `poetry run pytest tests/ -m wire -p no:rerunfailures` passes five
      times in a row on each backend, sequentially, and once under
      `make test-all-parallel`
- [x] `git diff --stat master...HEAD -- actingweb examples` is empty
- [x] No recording the security plan made has changed
- [x] Sensitivity, on a scratch copy and not committed: each of these
      changes at least one recording, and the rows are noted: the `/items`
      add diff's key renamed; `callback_subscription` returning before it
      sends; the `PUT` clear made a no-op; the permission filter returning
      its input; `apply_callback_data` skipping list operations; one key
      added to the callback body
- [x] "Recorded outcomes" filled; the row-variant count recorded (about 65
      rows, 128 variants by the tables above)

### Recorded outcomes

Filled by the first recording (2026-11-11, DynamoDB, compared on
PostgreSQL). **63 row variants in 122 files**, one file per row for both
backends (no `second` file was needed). Each row's `expected` in
`rows.toml` says what it records; that is the record, and this list keeps
only where the recording differs from the tables above. Most differences
come from the two security PRs (#171, #172), which landed after the tables
were written.

- **No exposure remains.** `WS2.subtarget` is identical to `WS1.subtarget`
  (a subtarget diff is judged once by its name since #171, so the object's
  keys are not filtered and no sequence is spent); `WD9`'s poll is answered
  filtered (sequence 1 as `{}`), so `denied` never reaches B; `WP6`'s
  baseline returns `shown` only; `WL16` sends only the subtarget's value.
  Every row is `exposure = false`; the four rows keep their owners.
- `WS1.subtarget`, `WS9.subtarget`: after B answers a string 400, the next
  diff is held as pending behind the refused sequence, so the empty value
  and the SDK delete change nothing at B.
- `WS3.target`: `PUT p/k/j` sends A's merged `k`, which carries a key step
  1's body dropped; `WS5.target`: `DELETE q/k` leaves B's `q` as
  `{k: ""}`, losing its other keys.
- `WS6.target`: three callbacks, in the order one, three, two; the two
  no-op registrations do not show on the wire.
- `WS7.target`: the diff carries the raw body (`blue`), and A stores the
  hook's value as JSON text (`"\"BLUE\""`): publisher and subscriber
  disagree. `WS9.subtarget`: the SDK set sends the hook's value (`BLUE`).
- `WL7.target`: 2, 25 and 26 changes give the same text summary; there is
  no threshold at 25.
- `WL9.target`: 400, not 201; nothing is written (no stray root write).
  Phase 3's note on `test_subscription_baseline_storage.py` depends on this.
- `WL10.target`: the seven form routes write at A (A's listing in the
  snapshot) and send nothing; the two `/www` deletes each send
  `{name: ""}` (not an empty registration). The form-created empty list
  never appears in A's listing.
- `WL12.target`: from the first falsy append, B's replica list cannot be
  read (`IndexError`), recorded as `read_error`.
- `WL15.target`: `PUT /properties/list:x` answers 500 (the store refuses a
  `list:` name), so no scalar `list:x` can be made over REST; the excluded
  `x` is queued and not sent.
- `WD7`: the sync fetches `/properties`, `/methods` and `/actions` after
  the poll and clear (no profile or permission fetch). `WD20` and `WM1`'s
  subscribe fetch the baseline, then `/properties` again, `/methods`,
  `/actions` and `/permissions/<B>`.
- `WQ5`: the medium callback reaches the data hook as `{}`.
- `WP3`: deleting the grant now sends a permission callback (the plan
  expected none) and B stores the `friend` default: not stale.
- `WP4`: the older callback is answered 204, not stored, and no
  permissions hook runs.
- `WC7`: nothing is sent after the re-creation because no trust or
  subscription survives the delete; the suspension row does.
- `WM1`: confirmed: the second write through the same instance reaches B
  only, and B2 keeps the old value.

### Implementation notes (Phase 1)

- **What the first commit needed.** The snapshot already held both sides'
  trust rows, the grants and B's peer permissions, and `WIRE_RECORD`
  already took row ids (the 2026-11-08 log line). The harness commit adds:
  - an async step (`Scenario.step` runs an `async` action on its own loop
    and drains the tasks it left);
  - `Scenario.sort_callbacks`, opt-in for rows with several subscribers or
    subscriptions (`WD13`, `WD14`, `WD15`): the publisher sends in
    random-id order, so each run of sibling callbacks is sorted by the
    receiver's name, then by subtarget and resource;
  - the replica snapshot records a list that cannot be read
    (`read_error`, for `WL12`) instead of failing;
  - `wire_pair` extensions: `resource`, `add_subscriber`, `subscribe`
    (another subscription), `deleted` (an actor the row deletes);
  - the `transformed` property hook (`WS7`, `WS9`), and `wire_import`
    with `"suspend": false` (`WD18`'s async append; a new method would
    have changed `WG6`'s recorded method listing);
  - `verify_groups.py`: the `second` key and the `Wire-Phase` trailer
    check, each with planted-violation tests.
- **The `Wire-Phase` check reads owners from the parent commit** (fixed
  after review): a commit cannot add itself as an owner and re-record in
  one go.
- **Deviation: the `Wire-Phase` check is local only.** CI's test job
  checks out at depth 1, so the check finds no merge base there and says
  it was skipped. Making it run in CI means a `fetch-depth: 0` checkout in
  that job: the owner's call, not made here.
- **Deviation: `WC8` dropped.** `WC3` and `WC4` already record the
  `subscription_deleted` hook and its `initiated_by_peer`. The subscriber's
  side runs no such hook in either row, so `WC8` would add nothing.
- **The `WL1` to `WL5` split** (the tables group them): `WL1` items add,
  `WL2` update, `WL3` delete, `WL4` `PUT ?index=N`, `WL5` metadata; each at
  target and subtarget level, over a two-item list B already holds.
- `WS3` and `WS5` are recorded in both topologies (the default), so 12
  files where the table implied 6.
- **Stability:** five consecutive wire runs per backend, sequential, no
  reruns: 297 passed in each (DynamoDB 3.5 to 5 min, PostgreSQL 1.5 min;
  CI's wire step allows 10).
- **Sensitivity** (scratch mutations of the library, reverted, over the
  new files and `test_wire_peer_paths.py`), each turning rows red: the
  `/items` add diff's `value` key renamed (`WL1`, 4 variants);
  `callback_subscription` returning before it sends (almost every row);
  the `PUT` clear a no-op (`WD7`, `WD9`, `WD12`, `WQ3`, 10 variants); the
  permission filter returning its input (`WL15`, `WD9`: the thinnest cover,
  since the security plans' `WA`/`WG` rows were not in this run);
  `apply_callback_data` skipping list operations (every list row at target
  level, `WD5`, `WD15`, `WD18`); one key added to the callback body (almost
  every row).
- **Full tier:** green on both backends. The first `make test-all-parallel`
  failed once each: `WL7.target[two_hosts]` on DynamoDB (no `.actual.json`
  left, so not a recording difference) and
  `test_verification_fetch.py::test_a_full_pool_refuses_at_once` on
  PostgreSQL (a library timing test); both passed three times alone and in
  two more parallel runs per backend. Treated as load flakes; watch `WL7`.
- `WD19` holds five callbacks within the 2 s gap timeout; it has stayed
  inside it in every run so far, but it is the one row a slow runner could
  push past it.

### Implementation Status: Complete

---

## Phase 2: the legacy files retired

### Changes

Each deletion names its covering rows or unit tests in the verification
document:

- `tests/integration/test_subscription_suspension_flow.py` - it never
  suspends (it posts to `/subscriptions/suspend`, which no handler serves;
  six statuses at `:1138`). Its classes and their cover:
  `TestResyncCallbacks` (`:584-823`; `WD6`, `WD10`, `WD12`),
  `TestSubscriptionWithPeerCapabilities` (`:843-990`; `WD12`, `WD20`),
  `TestMultipleSubscribersSuspension` (`:1316-`; `WD13`, `WD14`), the rest
  (`WD10`, `WD10.import`, `WD11`, `WL17`, the unit suspension tests).
- `tests/integration/test_subscription_processing_flow.py` - the classes
  whose subscriber has no processor: `TestSubscriptionProcessingFlow`
  (`:18-542`, subscriber on `peer_app` at `:71-77`), `TestResyncStateHandling`
  (`:969-1227`), and the sequencing and back-pressure classes (`:565-`,
  `:1249-1276`). Cover: `WD8`, `WD9`, `WD19`, `WQ1` to `WQ3` and
  `tests/test_callback_processor.py`. Its remaining publisher-queue classes
  stay (Phase 3).
- `tests/integration/test_fanout_flow.py:412-1073` - the classes that test
  `FanOutManager`, a granularity downgrade and a circuit breaker, none on the
  publish path; the first class (`:16-410`) is kept, renamed for what it
  does.
- `tests/integration/test_property_list_notifications.py` - seven
  placeholders; `WL1` to `WL8`.
- `tests/integration/test_list_diff_peer_replica.py` - `WL11.target`,
  `WL13`.
- `tests/integration/XDIST_GROUPS.md` - the retired groups removed.

### New Tests, both unit and integration tests

- None; the rows of Phase 1 are the cover.

### Failure Scenarios

- A deleted test was the only cover for something - each deletion names
  its cover; one with none is kept and moved to Phase 3's list.

### Verification

- [x] Run the contract's `### Checks` full tier verbatim
- [x] `poetry run python tests/integration/verify_groups.py` passes
- [x] The verification document lists every deleted class with its cover (the table above, for the verification to carry)

### Implementation notes (Phase 2)

Retired, each with its cover (rows in `wire/rows.toml`, unit files under
`tests/`):

| Retired | What it tested | Cover |
| --- | --- | --- |
| `test_subscription_suspension_flow.py`, `TestSubscriptionSuspensionFlow` | diffs while "suspended" (it posted to a route nothing serves) | `WD10`, `WD11`, `WL17`; `tests/test_subscription_suspension.py` |
| same file, `TestResyncCallbacks` | hand-sent resync and low-granularity callbacks | `WD6`, `WD10`, `WD12`, `WD14.low` |
| same file, `TestSubscriptionWithPeerCapabilities` | a trust's capability fields | `WD12`, `WD20`; `tests/test_peer_capabilities.py`, `tests/test_supported_options.py`, `test_peer_capabilities_integration.py` |
| same file, `TestSuspensionWithSubtarget` | subtarget suspension (never suspended) | `WD10.import`, `WL17` |
| same file, `TestResyncOnResume` | a hand-sent resync | `WD10`, `WD11` |
| same file, `TestMultipleSubscribersSuspension` | one write to three subscribers | `WD13`, `WD14.high` |
| `test_subscription_processing_flow.py`, `TestSubscriptionProcessingFlow` | in-order, duplicate, list and resync callbacks; cleanup on trust delete | `WS1.target`, `WD8`, `WL11.target`, `WD10`, `WC5`; the kept `TestCleanupOnTrustDeletion` |
| same file, `TestCallbackSequencing` | out-of-order delivery and gaps, a filled gap draining the held callbacks | `WD4` (added by iteration 7), `WD9`, `WD19`; `tests/test_callback_processor.py` (`test_gap_adds_to_pending`, `test_fill_gap_processes_pending`, `test_pending_callbacks_sorted`) |
| same file, `TestResyncStateHandling` | the publisher's queue after a resync | `WD9`, `WQ1` to `WQ3` |
| same file, `TestBackPressure` | many out-of-order callbacks | `WD19`; `tests/test_callback_processor.py` |
| `test_fanout_flow.py`, `TestGranularityDowngrade`, `TestCircuitBreakerBehavior`, `TestCircuitBreakerRecovery` | `FanOutManager` features, none on the publish path | `tests/test_fanout.py`; `WD13`, `WD14` |
| `test_property_list_notifications.py` (integration) | seven placeholders | `WL1` to `WL8` |
| `test_list_diff_peer_replica.py` | `remove_where`/`update_where` and a spanned item at the replica | `WL11.target`, `WL13.target` (its WARNING assertion moved there) |

- Kept in `test_subscription_processing_flow.py`:
  `TestPeerCapabilitiesInSubscriptions`, `TestPeerCapabilitiesIntegration`,
  `TestCleanupOnTrustDeletion` (Phase 3 tightens them). The kept first
  class of `test_fanout_flow.py` is renamed
  `TestDiffsQueuedForSeveralSubscribers` for what it does.
- `XDIST_GROUPS.md`: the fourteen retired groups removed (several rows
  named files that no longer existed; Phase 4 fixes the rest of the
  table's stale names).
- `tests/test_property_list_notifications.py` (the unit file, which
  `test_v2_list_mutation_committed.py` imports) is a different file and
  stays.

- Full tier green on DynamoDB; on PostgreSQL one isolation flake in
  `test_deletions_command.py` (another run's lease), green three times
  alone.

### Implementation Status: Complete

---

## Phase 3: the remaining subscription files tightened

### Changes

- In the remaining `test_subscription_*.py`, `test_property_notifications.py`,
  `test_fanout_flow.py` and `test_trust_flow.py`: every `status_code in […]`
  and every assertion guarded by `if …status_code` becomes one
  unconditional status. Measured on 2026-11-07 after Phase 2's retirements:
  125 status lists and 35 guarded assertions in nine files.
- A status that truly differs between backends is asserted per backend
  (`DATABASE_BACKEND`), with a `rows.toml`-style note in the test naming
  the plan that owns the difference; never loosened.
- `test_subscription_baseline_storage.py:77`, `:89` and
  `test_subscription_sync_coverage.py:327` rely on the stray write `WL9`
  records: tightened to the status the run shows, each with a comment
  naming `spec-1-5:1`.
- The `pytest.skip` calls for missing earlier state (41, measured) become
  class-scoped fixtures, so a failed setup fails.
  `test_subscription_sync_coverage.py:412`, `:444` skip because the SDK
  cannot find the actor; they get an `ActorInterface` built from the app's
  configuration, as the wire driver does.

### New Tests, both unit and integration tests

- None new; the changed files are the tests.

### Failure Scenarios

- A fixture conversion changes the order tests relied on - each converted
  class passes alone (`-k <class>`) and in the file.
- Class-scoped fixtures under CI's reruns - checked on one deliberately
  failing test before the commit.

### Verification

- [x] Run the contract's `### Checks` full tier verbatim
- [x] `grep -nE "status_code (in|not in) [\[\(]|if .*status_code" tests/integration/test_subscription_*.py tests/integration/test_property_notifications.py tests/integration/test_fanout_flow.py tests/integration/test_trust_flow.py`
      returns nothing, apart from per-backend assertions, each with its note
- [x] `grep -c "pytest.skip(" tests/integration/test_subscription_*.py tests/integration/test_fanout_flow.py`
      shows 0 for each file

### Implementation notes (Phase 3)

- **Measured after Phase 2:** 132 loose sites (status lists and
  status-guarded branches) in eleven files, and 27 `pytest.skip` calls (the
  plan's 125, 35 and 41 predate Phase 2 and the security PRs).
- **How each status was chosen:** a scratch rewrite routed every
  `.status_code` read through a probe that logged file, line and status;
  the files ran on both backends. 129 sites showed one status, the same on
  both, and became `== <status>`. One loop (`test_fanout_flow.py`, the
  large-payload check) sees 404 for the subscription `test_050` deleted and
  200 for the rest, now asserted per subscriber. No status differs between
  the backends, so no per-backend assertion was needed.
- **Guards:** a guard that always held became an unconditional assert with
  its body; one that never held lost a body that never ran (its `else`, if
  any, became the path). Two dead bodies in `test_trust_flow.py` (the
  unapproved trust's fields) were revived against the 202 the run shows.
  The three `/meta/actingweb/supported` blocks parsed plain text as JSON
  and so asserted nothing; they now assert `subscriptionresync` among the
  options.
- **Deviation: skips became asserts, not fixtures.** Each
  `if not <earlier state>: pytest.skip(...)` is `assert <state>, <msg>`:
  a failed setup fails, which is the plan's point, without rewriting the
  ordered classes. Where the cause was fixture scope, a fixture was added:
  `class_actor_factory` (class scope, in `conftest.py`) for
  `test_subscription_sync_coverage.py`, whose `actor_factory` deleted the
  actors when `test_001` ended. That, not the configuration, was why the
  SDK "could not find" the actor.
- **Failures the skips hid, now fixed in the tests:** the sync-coverage
  subscription id was read from a 201 body the 204 subscribe never has
  (read from the subscriber's listing now); a stale import
  (`SubscriptionProcessingConfig` lives in `actingweb.subscription_config`);
  `test_004`'s trust check observed 404 only because the actors were
  already deleted (200, as its comment says); list items posted in a shape
  the API refuses (400; now created as a list and added with
  `action: add`); `test_027` expected sequence 1 on a `meta` subscription
  nothing writes (0).
- **Today's behaviour pinned:** `TestSyncSubscriptionBaseline.test_003`
  asserts A's replica list stays empty after the sync: B's REST item adds
  were queued as diffs, and a REST list diff is not applied as a list
  operation (`WL1`), with a comment naming `attribute-list-v2-port:4`.
- `test_subscription_baseline_storage.py` no longer relies on `WL9`'s
  stray write: the security PRs moved its writes to the collection (201),
  so no `spec-1-5:1` comment was needed.
- Each converted class passes alone and in its file; a class-scoped
  fixture keeps its state across a `--reruns` retry (checked with a
  throwaway test that fails once).

- Full tier green on both backends.

### Implementation Status: Complete

---

## Phase 4: documentation and records

### Changes

- `tests/integration/README.md`, `XDIST_GROUPS.md`,
  `docs/contributing/testing.rst` - the wire suite: what a recording holds;
  re-recording one row (`WIRE_RECORD=<ids>`, refused under `CI`, the reason
  line, `<row>.actual.json` on a mismatch); one tier; `rows.toml`'s schema,
  owners and reserved ids; the `Wire-Phase` trailer; exposure rows; the
  stale counts and file names go.
- The later plans (`subs-list-cache-lifetime`, `attribute-list-v2-port`,
  `spec-1-5`, `email-as-creator-at-write-time`) - a dated Update Log line
  each: the recorded outcomes that contradict it, the line references into
  `tests/integration/` that Phases 2 and 3 removed or moved (for example
  `spec-1-5` citing `test_list_diff_peer_replica.py:103` and
  `test_subscription_baseline_storage.py:71-93`).
- `thoughts/todo/INDEX.md` - gate 4 met.

### New Tests, both unit and integration tests

- None beyond the docs build in the full tier.

### Failure Scenarios

- The testing guide drifts from `rows.toml`'s schema - the schema is
  documented once, at the top of `rows.toml`, and the guide links to it.

### Verification

- [x] Run the contract's `### Checks` full tier verbatim (docs build included)
- [x] `git diff --stat master...HEAD -- actingweb examples` is empty

### Implementation notes (Phase 4)

- `tests/integration/README.md`: the stale test counts, file list, a
  missing `FUTURE_WORK.md` link and a nonexistent workflow name replaced;
  a "Wire recordings" section. `docs/contributing/testing.rst`: a "Wire
  Recordings" section; both point at `rows.toml`'s header for the schema.
- `XDIST_GROUPS.md`: every row's file column regenerated from the
  `xdist_group` markers (thirteen named files that no longer exist); six
  rows for groups no test uses removed.
- The four later plans each have a dated Update Log line: the recorded
  outcomes that contradict them and the `tests/integration/` references the
  baseline removed or moved.
- `thoughts/todo/INDEX.md`: gate 4 met, plan 1 implemented, #172 merged.
- Checks: docs-only, so the docs build (strict) and the fast tier, both
  green; Phase 3's Full tier covers the code.

### Implementation Status: Complete

---

## Evaluation Notes

### Third review, 2026-11-07: the redraft

Two evaluators (tests, code quality and architecture together; scalability,
security and usability together, the plan being test-only) and the outside
voice (Codex, outside the command sandbox, and a fresh-context reviewer).
Nothing was run. Disposition:

Taken to the owner and decided: `rows.toml` as the only copy of row owners,
by plan and phase, checked by `verify_groups.py`; the old Phase 2 split into
three phases in the same PR.

Folded as mechanical:

- Row expectations corrected: `WM1` (the memo is reset on the instance's own
  create, so the second subscriber arrives over REST), `WP3` (a deleted
  grant sends no callback), `WS6` (three diffs and two no-ops), `WS9` (only
  the subtarget variant differs from `WS5`), `WD20` and `WP5` merged,
  `WP4` (the hook payload), `WQ6` (500 by the integration), `WD16` (the
  replica wipe and the security plan's 403), `WL15` and `WL17`
  (preconditions), `WD17` (an unbound port), `WD5` (an async step), `WD14`
  (a REST write), `WD7` (the sync's metadata fetches), `WL13` (its log
  assertion).
- The snapshot extended for `WC5` and `WP3`; a harness commit before the
  rows.
- Owners: the eight that named a phase which, in the later plan, keeps
  them identical (`WL15`, `WL17`, `WC5`, `WM1`, `WL16`, `WS9`, `WD9`, `WP6`),
  and per-variant owners for `WS3` and `WS5`; reserved id ranges.
- No "observed" state (one tier); exposure rows marked; the secrets guard
  over new files.
- Phase 2's class lists, ranges and cover; the measured counts; greps that
  can pass; per-backend statuses; the SDK-not-found skips; `INDEX.md`.
- The contradiction about when the `WA` and `WT` rows land.

Unverified notes:

- Whether attribute-list Phase 4's receiver change alters `WL13`; owned by
  `AL:4` so either outcome is allowed.
- `WD18`'s ordering rests on the spike's `WD10.import` recording only.
- What listings and the baseline do with a scalar named `list:x`
  (`db/dynamodb/property.py:885` excludes `list:` names on DynamoDB).

### Earlier reviews

The sections below are the reviews of earlier drafts, kept as they were.

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

## Implementation Summary

**Completed:** 2026-11-11
**All phases:** Complete (five commits on
`release/3.16.0-subscription-wire-baseline`, local; no PR yet)
**Test status:** All passing: the Full tier on both backends at Phases 1
to 3, five consecutive wire runs per backend at Phase 1, the fast tier and
the strict docs build at Phase 4. `git diff master...HEAD -- actingweb
examples` is empty.

### Deviations from Plan

(Owner, 2026-11-12: the skips as asserts and `WC8` dropped are accepted;
the trailer check stays local for now, `thoughts/todo/wire-phase-check-in-ci.md`.)

- The `Wire-Phase` trailer check runs locally only: CI's test job checks
  out at depth 1. Running it in CI needs `fetch-depth: 0` there (owner's
  call, not made).
- `WC8` dropped (`WC3`/`WC4` already record the hooks); `WS3`/`WS5` in both
  topologies; `WL1` to `WL5` split one per REST list route.
- `WD18` uses `wire_import` with `"suspend": false` instead of a new
  method, which would have changed `WG6`'s recorded method listing.
- Skips became asserts, not class-scoped fixtures, except where fixture
  scope was the fault (`class_actor_factory`).
- No row is an exposure: the two security PRs closed what the tables
  expected (`WS2`, `WD9`, `WP6`, `WL16`).

### Learnings

- Rows with several subscribers or subscriptions are only deterministic if
  sibling callbacks are sorted: the publisher sends in random-id order.
- The legacy skips hid five real test faults, one a fixture-scope bug
  (`actor_factory` deleting a class's actors after its first method).
- A harness addition can change existing recordings indirectly (a new
  method shows in a recorded `/methods` listing): run every existing row
  after any harness change, not only the new ones.
- Today's faults the recordings now pin, for their owners: `WS7` (A stores
  the hook value as JSON text, B gets the raw body), `WL12` (unreadable
  replica after a falsy append), `WL15` (500 on a `list:` name), `WM1`
  (stale memo), `WQ6` (500 on a null sequence).

## Iterations


### 2026-11-12, after verification thoughts/verifications/2026-11-12-subscription-wire-baseline.md

Scope (owner, 2026-11-12): the five Medium issues and the cheap Low ones
(6, 7, 8, 10), a drain row for Issue 9; Issue 11 (type hints) recorded as a
decision. Deviations (a) skips as asserts and (b) `WC8` dropped are accepted;
(c) the trailer check stays local for now (`thoughts/todo/wire-phase-check-in-ci.md`).


#### 1. The Wire-Phase check reads owners at the merge base, merges included

**Category**: Verification fix (Issue 4)

**What changed**:
- Owners come from `rows.toml` at the merge base. An owner added on the
  branch, in the re-recording commit or an earlier one, does not count; an
  ownership change lands on `master` first.
- A recording absent at the merge base was added on the branch and may
  change freely there.
- Merge commits are checked against their first parent.
- git runs from the repository root, so the working directory no longer
  matters.
- The base is the newer of `origin/master` and `master`.
- An unparsable registry at the merge base is reported as a problem.
- The docs say it checks commits already made, not "pre-commit".

**Files affected**:
- `tests/integration/verify_groups.py`: `wire_phase_problems(commit,
  changes, trailers, rows_base, base_files)`, `_merge_base`, the rewritten
  `check_wire_phase`.
- `tests/integration/test_wire_harness.py`: the table test, plus an owner
  added on the branch and two scratch-repository tests (a merge re-recording
  under a branch-only owner, checked from a subdirectory; an unparsable
  registry).
- `tests/integration/wire/rows.toml` (header), `tests/integration/README.md`,
  `docs/contributing/testing.rst`: the rule as it now is.

**Rationale**: the verification's Issue 4. The check was bypassable in two
commits and blind to merges. Reading owners at the merge base also lets
this branch revise its own new rows (Issues 2, 5, 8) without owning them.

#### 2. The baseline-storage test runs past its subscribe

**Category**: Verification fix (Issue 1)

**What changed**: `test_baseline_stores_simple_and_list_properties` no
longer returns after the 204 subscribe; it reads the subscription id from
actor A's own listing, and everything after it now runs. Running it showed
three more faults, all in the test, each fixed:
- **No list:** the two "list" writes posted `{"value": "Item n"}` to the
  collection, which writes a scalar named `value`. The test now creates
  `test_items` and adds two items with `action: add`.
- **Wrong module:** `SubscriptionProcessingConfig` is imported from
  `actingweb.subscription_config`.
- **Wrong call:** the profile assertion expected `sync_subscription` to
  store a peer profile; only `sync_peer` refreshes it
  (`actingweb/interface/subscription_manager.py`, the refresh after the
  per-subscription syncs). The test calls `sync_peer` and checks it synced
  the one subscription.

It also asserts the SDK actor loaded. It now checks what its name says:
both scalars, both list items and the profile.

**Files affected**:
- `tests/integration/test_subscription_baseline_storage.py`

**Rationale**: the verification's Issue 1. On `master` the early return
already ran every time; Phase 3 had made it unconditional instead of
fixing it.

#### 3. Tightened tests that could not fail now can

**Category**: Verification fix (Issue 3)

**What changed**:
- **Guards in `test_subscription_flow.py`:** each condition was logged on a
  run per backend. Every one held every time, and each lookup loop matched
  exactly once, so they were rewritten:
  - the 16 `if "data" in data …` / `if len(...)` guards are unconditional
    asserts;
  - the three `for sub in …: if <match>:` loops are
    `matches = [...]; assert len(matches) == 1; sub = matches[0]`, so a
    missing subscription fails the test.
- **`test_017` renamed** `…_valid_subid_malformed_body`. Its 400 pins a
  valid id with a non-callback body, against `test_016`'s 403 for an
  unknown id.
- **`test_trust_flow.py` `test_028`:** `assert found_lover or
  len(str(trusts)) > 0` is now `assert found_lover`.
- **`test_subscription_sync_coverage.py`:**
  - `test_004` asserts its `sync_peer` result: success, nothing synced, and
    A lists no subscription for B, because B's delete in `test_003`
    already cleaned A's side.
  - `TestSyncSubscriptionBaseline.test_003` asserts `diffs_processed == 4`
    beside the empty list, so a sync that stores nothing fails.
  - All four SDK lookups go through `_sdk_actor`, which fails if the actor
    is not found.

**Files affected**:
- `tests/integration/test_subscription_flow.py`
- `tests/integration/test_trust_flow.py`
- `tests/integration/test_subscription_sync_coverage.py`

**Rationale**: the verification's Issue 3. Phase 3's greps covered status
guards only; these assertions passed whatever the code did.

#### 4. The cleanup rows read the stores, not only the live rows

**Category**: Verification fix (Issue 2)

**What changed**: `Scenario.snapshot_stores`, opt-in, adds `stores` to
each actor's snapshot, read directly: every queued diff
(`get_subscription_diff_list(...).fetch(actor_id=...)`) and every
`_callback_state` entry, with peer and subscription named. It is on for
`WC5`, `WC6` and `WC7`, re-recorded on both backends. Today every store is
empty after the cleanup. A scratch mutation (the subscription delete not
clearing its diffs) turns `WC5` red on its `stores.diffs`.

**Files affected**:
- `tests/integration/_wire.py`: `_snapshot_stores`, `snapshot(..., stores=)`,
  `Scenario.snapshot_stores`.
- `tests/integration/test_wire_queue_and_lifecycle.py`: the three rows opt
  in.
- `tests/integration/wire/WC5.*.json`, `WC6.*.json`, `WC7.*.json`;
  `rows.toml` (`expected` and `reason` for the three).

**Rationale**: the verification's Issue 2. The queue and callback state
were read only through live subscription rows, so leftovers of a deleted
subscription were invisible to the rows that claim they are gone.

#### 5. The timing-sensitive rows no longer depend on the runner

**Category**: Verification fix (Issue 5)

**What changed**:
- **`WD19`** posts sequences 2 to 7 in one step and snapshots once. The
  step's result lists each status (204 five times, then 400), and the
  recording was re-recorded on both backends. The six posts now fit inside
  the 2 s gap timeout however slow the snapshots are.
- **`WD18` and `WD10.import`** set `Scenario.hoist_callbacks_from =
  ("/methods/",)`. A subscription callback recorded under the method
  request is moved to follow it, so the recording is the same whichever
  side of the race the callback lands on. Neither recording changed:
  `WD10.import` is the security plan's, and its bytes are identical.

**Files affected**:
- `tests/integration/_wire.py`: `_hoist_callbacks` and
  `Scenario.hoist_callbacks_from`.
- `tests/integration/test_wire_delivery.py` (`WD19`, `WD18`),
  `tests/integration/test_wire_peer_paths.py` (`WD10.import`, opt-in only).
- `tests/integration/test_wire_harness.py`: a hoist test (nested and
  sibling give the same result).
- `tests/integration/wire/WD19.*.json`; `rows.toml` (`WD19` reason, `WD18`
  expected).

**Rationale**: the verification's Issue 5. These rows had been green
throughout, but each depended on timing that a slower runner could flip.

#### 6. The harness's sort key, async drain and unreadable-list snapshot

**Category**: Verification fix (Issues 6, 7, 8)

**What changed**:
- **Sort key:** `_sort_callback_runs` now sorts by receiver, target,
  subtarget, resource and granularity, so a subscriber's sibling callbacks
  that differ only in target or granularity are ordered too. `WD13` to
  `WD15` are unchanged.
- **Async drain:** `_run_and_drain` gives up after 30 s (`TimeoutError`).
  A failing fire-and-forget task is recorded in the step's result as
  `task_errors` instead of raised, as production only logs it. `WD5` is
  unchanged. Two harness tests pin both.
- **Unreadable list:** a replica list that cannot be read is recorded with
  its stored length beside `read_error`. `WL12.target` was re-recorded:
  the length grows 1 to 6 while the items stay unreadable.

**Files affected**:
- `tests/integration/_wire.py`: `_sort_callback_runs`, `_run_and_drain`,
  `_snapshot_replica`.
- `tests/integration/test_wire_harness.py`: the two drain tests.
- `tests/integration/wire/WL12.target.*.json`; `rows.toml` (`WL12.target`).

**Rationale**: the verification's Issues 6 to 8, the cheap Low items. They
were in scope because each was minutes of work.

#### 7. A row for held callbacks draining (`WD4`)

**Category**: Verification fix (Issue 9)

**What changed**: new row `WD4`, both topologies, recorded on DynamoDB and
compared on PostgreSQL. Sequences 2 and 3 are posted to B by hand with
A's bearer and held behind the missing 1. Sequence 1 then releases them in
order, one data hook each, and B ends with `x = 3`, `last_seq` 3 and
nothing pending. `WD19` shares its post helper (`_post_callback`).

**Files affected**:
- `tests/integration/test_wire_delivery.py`: `_post_callback`,
  `test_wd4_held_callbacks_drain`.
- `tests/integration/wire/WD4.*.json`; `rows.toml` (`WD4`, owners none).
- The plan's Phase 2 table: `WD4` added to `TestCallbackSequencing`'s cover.

**Rationale**: the verification's Issue 9. The retired
`TestCallbackSequencing` covered the drain over HTTP; only unit tests did
afterwards.

#### 8. One status assert per subscription setup, and a strict Location read

**Category**: Verification fix (Issue 10)

**What changed**: each of the six subscription setups in
`test_property_notifications.py` asserted 204 twice (a Phase 3 artefact:
the dedupe missed pairs split by a comment). It now asserts once, and
reads the id with `response.headers["Location"]` plus `assert
subscription_id`, so a missing header fails where it happens, not as a
confusing status later.

**Files affected**:
- `tests/integration/test_property_notifications.py`

**Rationale**: the verification's Issue 10.

#### 9. Type hints on test functions: recorded, not added

**Category**: Decision (Issue 11)

**What changed**: nothing in code. The new test functions and harness
hooks carry no annotations, like every existing wire test and test hook,
and pyright is clean on `tests`. Whether `CLAUDE.md`'s "type hints are
required on all functions" covers pytest test functions and fixtures is
the owner's call; this iteration follows the files' existing convention.

**Rationale**: the verification's Issue 11; out of the owner's chosen
scope for this iteration.


### 2026-11-12, after verification thoughts/verifications/2026-11-12-subscription-wire-baseline-2.md

Scope (owner, 2026-11-12): all eight issues of the second verification.

#### 10. The async drain settles on Python 3.11 and records every failed task

**Category**: Bug fix (Issues 1 and 2)

**What changed**: `_run_and_drain` no longer uses `asyncio.wait_for`.
- **The 3.11 bug:** 3.11's `wait_for` runs its coroutine in a task of its
  own. The drain, which waits for every task but the caller's, found that
  task, waited for itself, and timed out after 30 s. The bug came from
  iteration 6 and broke `WD5` and two harness tests on CI's required 3.11
  contexts. It was invisible locally, where Python is 3.14.
- **The fix:** the drain waits in the caller's task, under `async with
  asyncio.timeout(...)`.
- **Failed tasks:** the step captures every task it creates through the
  loop's task factory. A task that failed before the drain began, and so
  no longer appears in `all_tasks()`, is now recorded in `task_errors`.
  The names are sorted.
- **Regression tests:**
  - `test_the_drain_does_not_depend_on_wait_for_running_it_in_a_task`
    gives `wait_for` 3.11's shape. It hung on the old code and passes now.
  - `test_a_task_that_failed_before_the_action_returned_is_recorded`
    failed on the old code.

**Files affected**:
- `tests/integration/_wire.py`: `_run_and_drain`.
- `tests/integration/test_wire_harness.py`: the two tests.

**Rationale**: the second verification's Issues 1 (High) and 2.

#### 11. `test_004` exercises the dead-subscription cleanup

**Category**: Verification fix (Issue 3)

**What changed**:
- **`test_003`:** it now deletes B's subscription row for A through the
  library at B, not over REST. B's REST delete also removes A's side,
  which left A with nothing dead. The test asserts that B answers 404 for
  the subscription and that A still lists it.
- **`test_004`:** it asserts that `sync_peer` got a 404 for that one
  subscription, deleted A's dead subscription, and kept the trust (200).
- **Sensitivity:** a scratch mutation of
  `actingweb/interface/subscription_manager.py` left out the cleanup's
  `sub_obj.delete()`. It turned `test_004` red and was reverted.

**Files affected**:
- `tests/integration/test_subscription_sync_coverage.py`:
  `TestSyncPeerTrustRevocation.test_003`, `test_004`.

**Rationale**: the second verification's Issue 3. Iteration 3 had only
relabelled the gap.

#### 12. The Wire-Phase check accepts a branch that merges `master` in

**Category**: Bug fix (Issue 4)

**What changed**: a merge commit's changes are still read against its
first parent, less every file whose content equals its version on another
parent. Such a file was taken over unchanged, and it was checked where
that parent changed it: on `master`, or at its own commit in the range.
What a merge changes itself, such as a conflict resolution, is still
checked.
- **New test:** `test_merging_master_in_does_not_need_master_s_trailers`
  failed on the old check.
- **Updated test:** the merge test's merge now re-records the row itself,
  so it is still flagged.

**Files affected**:
- `tests/integration/verify_groups.py`: `check_wire_phase`.
- `tests/integration/test_wire_harness.py`: the two scratch-repository
  tests.

**Rationale**: the second verification's Issue 4. The check rejected a
correct history and could not be satisfied by a single trailer.

#### 13. The last conditional assert in `test_subscription_flow.py`

**Category**: Verification fix (Issue 5)

**What changed**: `test_034`'s `if isinstance(first_data, dict) and
"data1" in first_data:` is now an assert. It holds on both backends.
Iteration 3's claim that every guard had become unconditional is true from
here on.

**Files affected**: `tests/integration/test_subscription_flow.py`.

**Rationale**: the second verification's Issue 5.

#### 14. The list-sync test shows the diffs were applied, not only counted

**Category**: Verification fix (Issue 6)

**What changed**:
- **New assert:** `TestSyncSubscriptionBaseline.test_003` also asserts
  that A's subscription moved four sequences on during the sync.
- **Correction to iteration 3:** it said `diffs_processed == 4` makes "a
  sync that stores nothing" fail. It does not, because the counter
  counts a diff whatever its handler stored. The replica list itself
  stays empty today (`WL1`'s known fault, owned by
  `attribute-list-v2-port:4`).

**Files affected**: `tests/integration/test_subscription_sync_coverage.py`.

**Rationale**: the second verification's Issue 6.

#### 15. Store leftovers keep their order whatever their ids

**Category**: Verification fix (Issue 7)

**What changed**: `_snapshot_stores(actor, names)` orders queued diffs by
sequence and content, and callback-state entries by kind, peer name and
content. The random subscription id comes only last, as a tie-break. A
harness test swaps two leftovers' ids and gets the same order. The
recordings are unchanged: every store is empty today.

**Files affected**:
- `tests/integration/_wire.py`: `_content_key`, `_snapshot_stores`,
  `snapshot`.
- `tests/integration/test_wire_harness.py`:
  `test_store_leftovers_keep_their_order_whatever_their_ids`.

**Rationale**: the second verification's Issue 7. The defect was latent:
it would have made a cleanup regression show as a flake, not as a diff.

#### 16. What `WD19` and the hoisted rows can and cannot show

**Category**: Verification fix (Issue 8)

**What changed**: wording only, in `rows.toml`.
- **`WD19`'s reason:** "on any runner" is gone. The six posts must still
  land within 2 s of the first.
- **`WD18` and `WD10.import` `expected`:** each now says the row cannot
  tell a callback sent inside the method request from one sent after it.

No recording changed, so the commit needs no trailer.

**Files affected**: `tests/integration/wire/rows.toml`.

**Rationale**: the second verification's Issue 8.


### 2026-11-12, after verification thoughts/verifications/2026-11-12-subscription-wire-baseline-3.md

Scope (owner, 2026-11-12): all five findings of the third verification.

#### 17. The drain records only unhandled task errors, and cleans up when it gives up

**Category**: Verification fix (Issues 1 and 3)

**What changed**:
- **Unretrieved errors only:** a task's error lands in `task_errors` only
  when nobody retrieved it. The check reads the task's `_log_traceback`
  flag before the drain reads the exception. A task that was awaited, or
  gathered with `return_exceptions` (fanout's deliveries), had its error
  handled, and is no longer reported.
- **Cancelled tasks:** they are no longer counted as errors.
- **When the drain gives up:** on a timeout, or when the action raises,
  the drain cancels the tasks still running, waits up to 1 s for them,
  and reads every done task's exception before the error goes up.
- **The flag:** it behaves the same on 3.11 and 3.14 (the C `_asyncio`
  task on both).
- **New tests:** `test_failures_the_action_handled_are_not_task_errors`
  and `test_a_timed_out_drain_cancels_what_is_still_running`. Both failed
  on the previous drain, and both pass on 3.14 and 3.11.

**Files affected**:
- `tests/integration/_wire.py`: `_run_and_drain`.
- `tests/integration/test_wire_harness.py`: the two tests.

**Rationale**: the third verification's Issues 1 and 3. Iteration 10's
capture of every task over-reported. A recording would have claimed an
unhandled failure for a delivery that fanout counts as failed.

#### 18. Store leftovers sort without their clock fields

**Category**: Verification fix (Issue 2)

**What changed**: the sort key now leaves out `claimed_at`,
`_received_at` and `timestamp` at any depth, and reads a diff stored as a
JSON string first. The harness test's stub values now carry clock fields
that run opposite to their content. It failed on the previous key.

**Files affected**:
- `tests/integration/_wire.py`: `_CLOCK_FIELDS`, `_without_clock`,
  `_content_key`.
- `tests/integration/test_wire_harness.py`:
  `test_store_leftovers_keep_their_order_whatever_their_ids`.

**Rationale**: the third verification's Issue 2. Iteration 15's key began
with wall-clock fields, so leftovers would have sorted by claim or
receipt time.

#### 19. `test_004` checks the trust on both sides

**Category**: Verification fix (Issue 4)

**What changed**: after the sync, `test_004` reads A's trust in B and B's
trust in A, and expects 200 for both.

**Files affected**: `tests/integration/test_subscription_sync_coverage.py`.

**Rationale**: the third verification's Issue 4.

#### 20. The docs build ignores local virtualenvs at the root

**Category**: Verification fix (Issue 5)

**What changed**: `conf.py`'s `exclude_patterns` adds `.venv*` and
`.venv*/**`. The `.venv311` used for Python 3.11 runs holds Sphinx's own
`.rst` templates, which failed `sphinx-build -W` locally with 22
warnings. A fresh build (`-E`) now passes with `.venv311` present. This
is outside the plan's test-only scope, but it keeps the contract's Full
tier usable alongside the 3.11 venv, as the `.claude/**` exclusion did
for worktrees.

**Files affected**: `conf.py`.

**Rationale**: the third verification's Issue 5.
