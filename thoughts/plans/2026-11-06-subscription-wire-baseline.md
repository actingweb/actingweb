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

**Readiness, 2026-11-06.** Not ready to approve as written. A review on
this date (two evaluators and the outside voice, in the Evaluation Notes
under "Second review") found the recording mechanism buildable but not yet
deterministic, the row set about three times the size the regression risk
needs, and the consumer's one bulk flow missing from it. None of it is
folded into the phases. The plan needs its spike, three owner decisions,
and another draft. **The spike is decided** (owner, 2026-11-07): it builds
the recorder and the two consumer-shaped apps, records about four rows on
both backends (a scalar write, a REST list edit, a gap and resync under a
permission filter, the consumer's subtarget suspend and resume around list
writes), repeats each run until it is known whether the recording is
identical, and writes a research note. The three owner decisions (full
transcripts or a projection; two tiers; retire or tighten the legacy files)
are taken on that note, and both this plan and the security plan are then
redrafted.

**This plan: second.** Its spike comes first, before either plan is
redrafted. It needs the security plan merged: that plan's Phase 0 lands the
harness the spike built (two apps shaped like the consumer's, the recorder,
the scenario driver) and records the fourteen flows its own fix must leave
unchanged; this plan adds the rest on the same harness. What follows it: each
of the four plans after it names, phase by phase, the rows it re-records and
the rows it must leave byte-identical.

## Decisions Made

- **The spike builds the harness; the security plan lands it** (owner,
  2026-11-07). The harness is proven by running it, not designed on paper:
  the spike's research note is what the redraft of this plan and of the
  security plan's Phase 0 is written from. This plan stays its own PR after
  the fix.
- **Today's behaviour is proven before it is changed** (owner, 2026-11-06):
  the suite is improved to prove what the library does now, not only the
  flows the plans change; each implementation phase then updates the tests
  explicitly for the behaviour it changes.
- **Its own plan and PR, after the security fix** (owner, 2026-11-06). The
  security PR stays small and carries no test that passes because a hole is
  open.
- **Recorded transcripts, not hand-written expectations** (owner,
  2026-11-06). A first reading of the code got about a dozen of sixty flows
  wrong (research, "Reading is not enough"); a recording cannot, and it
  captures fields nobody thought to assert.

Deduced; confirm at approval:

- **A recording is what the library does, right or wrong.** A row that
  records a defect is an ordinary passing test. Its entry in the row registry
  says what is known to be wrong and which plan is expected to change it.
  That includes `WD9`, which records an exposure the `ListAttribute` plan
  closes two plans later (moved here from the security plan by the owner,
  2026-11-06): the same exposure is already described in that plan and in
  the specification sweep, and it needs an approved trust and a subscription
  to reach, unlike the holes the security plan closes.
- **The "Expected from reading" columns below are not assertions.** They are
  what two readers of the code expect the first recording to show. The first
  recording is reviewed against them row by row, and every difference is
  written into "Recorded outcomes" with which of the two was wrong.
- **One file per row and variant**, so `git diff --stat` on
  `tests/integration/wire/` is a list of the rows a commit changed. A phase
  may change only the files of the rows its plan names; that is checked by
  reading the stat, at each phase's verification.
- **A recording that differs between backends or topologies is a declared
  difference**: a second file, and a line in the registry saying why. An
  undeclared difference fails. Where the reason is not understood, the phase
  stops and reports instead of recording both.
- **The registry lives under `tests/integration/wire/`**, not in
  `thoughts/`: CI does not run for a change under `thoughts/`
  (`.github/workflows/tests.yml:78-83`), so a check that parsed a plan would
  break on the next unrelated PR. The registry's "expected to change in"
  entries are advice until the plan they name is approved; a new draft of
  that plan updates them.
- **Wire tests never rerun.** CI retries a failed test twice
  (`tests.yml:265-269`), which would hide a transcript that holds one run in
  three. The wire marker runs as its own CI step without reruns.
- **A contradiction between a recording and a later plan's premise is
  recorded here and fixed in that plan's next draft**, before that plan
  starts. It does not hold up this plan.
- **Later plans add rows as well as re-recording them.** A row a later phase
  adds (`WD21` in the `ListAttribute` plan's Phase 3, the path-addressed list
  rows and the anonymous opt-in in the specification plan) is entered in the
  registry by that phase, with its recording.
- **Statuses are single-valued** in the existing files this plan touches,
  with one exception: a file a later plan is about to change is tightened
  only to what the run shows and gets a registry entry naming that plan.

## What We're NOT Doing

- **Changing any behaviour** - the commit range has no diff under
  `actingweb/` or `examples/`. A defect a recording shows is recorded and
  left to the plan that owns it, or reported if none does.
- **Recording the open holes** - the security plan has closed them before
  this plan starts; its access rows are recorded in their secured form, by
  that plan.
- **Endpoints outside the subscription path** (`/meta`, trust creation,
  OAuth, MCP, `/www` beyond the list and property forms) - the specification
  plan's Phases 1 and 2 name the existing tests they change.
- **Fault injection over HTTP** (a store fault mid-callback, a failed
  baseline fetch, a delivery inside another's live claim) - needs seams the
  unit suites have (`tests/test_callback_processor.py`,
  `tests/test_callback_in_progress_answer.py`, `tests/test_db_fault_*.py`).
- **A mixed-version pair** - one suite runs one version. The rolling-deploy
  cases are fixtures that plant the older shape, in the plan whose format
  they concern (the `ListAttribute` plan's Phase 2).
- **The consumer's identity options** (`with_unique_creator`,
  `with_email_as_creator`, indexed properties) - they do not change what
  travels between two actors, and the first needs an isolated store.
- **A subscriber on the publisher's own host when the write happens on the
  server's event loop** - with synchronous callbacks in one process the loop
  would wait for itself until the read timeout. Lambda, where the consumer
  sets the flag, answers from another instance. Recorded on two hosts only.
- **Rewriting the unit suites** - they stay.

## What Already Exists

Built by this plan's spike and landed by the security plan's Phase 0, which
merges before this plan. As designed before the spike:

- `tests/integration/test_harness.py` - `create_test_app` options
  `sync_callbacks`, `peer_capabilities`, `peer_permissions`, `peer_profile`,
  `record`; the recorder; the recording hooks.
- `tests/integration/conftest.py` - `wire_app` (5561) and `wire_peer_app`
  (5562), and the `wire_pair` factory with its two topologies and its
  teardown through the library.
- `tests/integration/_wire.py` - the scenario driver, the normaliser and the
  comparison; `WIRE_RECORD=1` to re-record, refused when `CI` is set.
- `tests/integration/wire/` - the registry (`rows.toml`) and fourteen
  recordings: `WS1.target`, `WL11.target`, `WD6`, `WD8`, `WD10`,
  `WD12`, `WQ1`, `WQ2`, `WQ3`, `WC1`, `WC2`, `WC3`, `WC4`, `WP1`; and the
  access rows `WA1` to `WA14` in their secured form.
- The `wire` marker and its CI step.

Already in the tree:

- `tests/integration/test_list_diff_peer_replica.py` - the one file that
  asserts a replica after a real callback; `WL11.target` and `WL13` take its
  cases.
- `tests/integration/test_subscription_callback_flows.py:199-224`,
  `:339-368`, `:497-519` - the receiver's pending queue and duplicates with
  hand-built callbacks; kept, tightened.
- `tests/integration/test_property_notifications.py:134-137` - asserts the
  target-level delete diff; kept.
- `tests/integration/verify_groups.py` - run by the full tier; gains the
  registry checks.

## Phase 1: the remaining flows, recorded

Row identifiers continue the security plan's. A suffix is the level of the
subscriber's subscription (`.target`, `.subtarget`, `.resource`). Unless a
row says otherwise it runs with granularity `high`, a grant of `*`, and in
both topologies. "SDK" marks a step done through `ActorInterface` in the test
process because no route exists; everything else is an HTTP request.

### Changes

- `tests/integration/test_wire_scalar_properties.py`,
  `test_wire_list_properties.py`, `test_wire_delivery.py`,
  `test_wire_queue_and_lifecycle.py`, `test_wire_permissions.py` - one test
  per row below, each a scenario for the driver. The security plan's fourteen
  move into these files unchanged.
- `tests/integration/wire/*.json`, `wire/rows.toml` - the recordings and
  their registry entries.
- `tests/integration/test_harness.py` - one more wire-app hook: an
  asynchronous method hook that appends to a property list through the
  interface (for WD18).

Scalar properties:

| Row | Steps on the publisher | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WS1.subtarget | `PUT /properties/<p>` with an object, then a string, then `""` | The object is stored as one scalar per key; the string makes the subscriber answer 400 and store nothing; the empty value answers 204 | `attribute-list-v2-port` Phase 4 |
| WS2.subtarget | The same with a grant of exactly `<p>` | For the object: a sequence number is spent and no callback is sent (the filter checks `<p>/<key>`); the string is sent unfiltered | `attribute-list-v2-port` Phase 4 |
| WS3 (three levels) | `PUT /properties/<p>/<k>`, then `PUT /properties/<p>/<k>/<j>` | Target `{p: {k: v}}`; the replica's `p` loses its other keys. The deeper write reports `j`'s value as `k`'s | `spec-1-5` Phase 3 |
| WS4.target | `POST /properties` with two names | One diff, one callback | - |
| WS5 (three levels) | `DELETE /properties/<p>`, then `DELETE /properties/<q>/<k>` | Target: a diff `{p: ""}`, the replica's key deleted. Subtarget on `p`: nothing registered, the replica keeps it. The nested delete sends `{q: {k: ""}}` and the replica's `q` is replaced | `spec-1-5` Phase 3 (the subtarget and resource cases) |
| WS6.target | `DELETE /properties` with three properties | One `{key: ""}` diff and callback per key | `spec-1-5` Phase 3 |
| WS7.target | `PUT /properties/transformed` (a wire-app hook upper-cases it) | The diff carries the value as sent; the replica differs from the publisher | `spec-1-5` Phase 3 |
| WS8.subtarget | A write to a property outside the subtarget | Nothing | - |

Lists:

| Row | Steps on the publisher | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WL1 to WL5 (`.target`, `.subtarget`) | `PUT /properties/<l>?index=N`; `/items` add, update, delete; metadata `PUT` | `{"index", "value"}`, `{"action": …}`. No list at the subscriber: a scalar named after the list (target), or scalars named `action`, `index`, `value` (subtarget) | `attribute-list-v2-port` Phase 4 |
| WL6 (`.target`, `.subtarget`) | `DELETE /properties/<l>` after an SDK `append` | Target: `{l: ""}` is sent; the subscriber deletes a scalar `l` and keeps the list. Subtarget: nothing | `attribute-list-v2-port` Phase 4 |
| WL7.target | `POST /properties` with `items`: 2, 25 and 26 changes, and one mixing a list and a scalar | A text summary under the list's key | `attribute-list-v2-port` Phase 4 |
| WL8 (`.target`, `.subtarget`) | `POST /properties` creating an empty list | A text marker; at subtarget level the subscriber answers 400 | `attribute-list-v2-port` Phase 4 |
| WL9.target | `POST /properties/<l>` with an object body | 201, root properties written, the list untouched | `spec-1-5` Phase 1 |
| WL10.target | The web-UI form routes: item add, update, delete; list create; metadata edit; simple property create and update; and the `/www` delete of a list and of a property | Nothing for the first seven; an empty diff for the two deletes | `attribute-list-v2-port` Phase 4 |
| WL11.subtarget | SDK: the operations of `WL11.target` | Scalars named `list`, `operation`, `item`, `index` at the subscriber; no list | `attribute-list-v2-port` Phase 4 |
| WL14.target | SDK: three `append`s, then `pop(-2)` (its own row, so the security plan's `WL11.target` recording is not touched) | Not applied; the replica is one item longer than the publisher's list | `attribute-list-v2-port` Phase 4 |
| WL12.target | SDK: `append` of `0`, `""`, `False`, `None`, `[]`, `{}` | Not read | `attribute-list-v2-port` Phase 2 |
| WL13.target | SDK: an item over the span threshold, appended and updated | A reference diff; nothing applied | - |

Delivery:

| Row | Steps | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WD2 | One write; the row keeps timestamp formats | The callback carries `str()` of a datetime, both polls ISO with `Z` | `spec-1-5` Phase 3 |
| WD3 | Two writes a second apart | DynamoDB: one timestamp for both. PostgreSQL: two. A declared backend difference | `spec-1-5` Phase 3 |
| WD5 | SDK, on a running loop with the synchronous flag off (a copy of the app's configuration): `append` | The call returns before the callback is answered; the replica is equal once the task has run | `spec-1-5` Phase 4 |
| WD7 | Granularity `none`: a write, then SDK `sync_peer` at the subscriber | No callback; after the sync the replica has the value and a scalar named `timestamp`; the queue is cleared | - |
| WD9 | The subscriber may read `allowed` only: a write to `denied`, to `allowed`, a wait of the gap timeout, a third write | Two stored diffs with two sequence numbers and a callback for `allowed` only; it is held pending. The third callback triggers a resync: the subscriber polls the publisher's whole queue, which is not filtered, so `denied`'s value reaches the replica, with a scalar named `timestamp`; the queue is cleared. A recorded exposure (see Decisions) | `attribute-list-v2-port` Phase 4 |
| WD11 | SDK suspend, a write, resume, with a `none` subscription | It is sent a resync callback | `spec-1-5` Phase 3 |
| WD13 | Two subscribers on the second host, one write | Two callbacks, one after the other, each with its own sequence from 1 | `spec-1-5` Phase 4 |
| WD14 (`.high`, `.low`) | Five subscribers on the publisher's own host, one write | All replicas equal; for `.low`, each subscriber's fetch and acknowledgement nested in its callback | Kept by `spec-1-5` Phase 4 |
| WD15 | One subscriber with a target-level and a subtarget-level subscription over one list; SDK `append` | Two callbacks; the item once in the list, plus the scalars of `WL11.subtarget` | `attribute-list-v2-port` Phase 4, then `spec-1-5` Phase 3 |
| WD16 | SDK: the subscriber's callback row removed; two writes | 404 for each callback; the publisher's row stays and each write posts again | - |
| WD17 | SDK: the publisher's trust row pointed at a closed port; a write | The write answers; the diff is stored | - |
| WD18 (two hosts) | `POST /methods/<name>` on the publisher; the hook appends to a list on the server's loop | The callback is sent before the method answers; the replica is equal | `spec-1-5` Phase 4 |
| WD19 | Hand-posted callbacks, each one sequence ahead, one more than `max_pending` | 204 for each held one, then 400 | - |
| WD20 | Subscribe with properties and a list already present, no write | The replica holds the permitted baseline, the list included, before any diff | - |

The queue, and the life of a subscription:

| Row | Steps | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WQ4 | `GET /subscriptions`, `?peerid=`, `?target=` as creator on both actors; `GET /subscriptions/<peer>` as a peer whose trust is not approved | Both directions listed; the unapproved peer's request: not read | - |
| WQ5 | Subscribe with granularity `medium`; a write | 201; a callback with neither `data` nor `url`; 204, and the subscriber's sequence advances | `spec-1-5` Phase 3 |
| WQ6 | `PUT …/<subid>` with `{"sequence": null}`; `GET …/<subid>?_method=PUT&sequence=1` | Not read to the end (an uncaught `TypeError`); the override clears | - |
| WC5 | `DELETE /<A>/trust/friend/<B>` with a queued diff and a replica | Both sides' trust and subscription rows gone, the publisher's diffs gone; the subscriber's replica and callback state: not read | `attribute-list-v2-port` Phase 3 (the side bucket) |
| WC6 | The publisher deleted, with a subscriber, a queued diff and a suspended target | Diffs go with their subscriptions; the suspension row stays | `subs-list-cache-lifetime` Phase 2 |
| WC7 | SDK: the publisher created again under the same id; a write | It starts suspended and registers nothing | `subs-list-cache-lifetime` Phase 2 |
| WC8 | `WC3` and `WC4` again, recording the lifecycle hooks | `subscription_deleted` with `initiated_by_peer` true at the publisher for `WC3`; whether the publisher's own replica store for the subscriber is wiped: not read | - |

Permissions between peers:

| Row | Steps | Expected from reading | Expected to change in |
| --- | --- | --- | --- |
| WP2 | The grant shrunk while the subscriber holds a list it no longer covers | Not deleted (the default, which the consumer keeps) | - |
| WP3 | The grant deleted | No callback | `spec-1-5` Phase 2 |
| WP4 | `WP1`'s recorded body posted again after a newer one, with the bearer | Not read | `spec-1-5` Phase 2 |
| WP5 | Trust established with peer profiles on | The subscriber reads the publisher's profile properties with its bearer; the request and what it returns are recorded | `spec-1-5` Phase 2 (default deny) |

### New Tests, both unit and integration tests

- The rows above, integration, both backends, both topologies.
- Registry checks in `tests/integration/verify_groups.py`: every scenario has
  a recording and every recording a scenario; every second file for a backend
  or a topology has a reason; no recording contains a secret, an actor id or
  a port (the normaliser's own guard).

### Failure Scenarios

- A recording captures a harness artefact, not the library - the two
  topologies differ in one known way: the permission and capability stores
  are rebuilt per application (`actingweb/peer_permissions.py:423`), so a
  subscriber on the second host never has a warm cache. A row that differs
  for that reason says so in the registry; none is recorded without a reason.
- A timing-dependent recording - order is recorded as nesting and as
  "overlaps", never as times. The only fixed wait is the gap timeout in
  `WD9`, which is evaluated only when a callback arrives
  (`actingweb/callback_processor.py:422-428`); the scenario waits it out
  once. The suite passes five consecutive runs on each backend before the
  commit, and never reruns in CI.
- Someone re-records everything to make a red run green - a phase's
  verification reads the stat of `tests/integration/wire/` against the rows
  the phase names; a file outside the list is a regression to explain.
- A "not read" row shows something no plan knows about - recorded, written
  into "Recorded outcomes", reported to the owner before the next plan
  starts.
- A row cannot be made deterministic - it is dropped from the registry with
  the reason, and listed under "Recorded outcomes" as not pinned; it is not
  kept with a rerun.
- The scenario for `WD5` asserts a lifetime the garbage collector decides
  (the task has no other reference, `actingweb/actor.py:2786`) - the scenario
  awaits the loop's pending tasks before it snapshots and records only what
  was sent and stored.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Run the contract's `### Checks` full tier before the phase commit, one
      run at a time, both backends
- [ ] `poetry run pytest tests/integration -m wire -p no:rerunfailures` passes
      five times in a row on each backend, sequentially, and once under
      `make test-all-parallel`
- [ ] `git diff --stat master...HEAD -- actingweb examples` is empty
- [ ] `git diff --stat master...HEAD -- tests/integration/wire` shows no
      change to the fourteen recordings the security plan made
- [ ] Sensitivity, on a scratch copy and not committed: each of these changes
      at least one recording, and the rows are noted. The `/items` add diff's
      key renamed; `callback_subscription` returning before it sends; the
      `PUT` clear made a no-op; the permission filter returning its input;
      `apply_callback_data` skipping list operations; one key added to the
      callback body
- [ ] "Recorded outcomes" is filled: one line for every row whose recording
      differs from "Expected from reading", and one for every "not read"

### Recorded outcomes

Filled by the first recording.

### Implementation Status: Not Started

---

## Phase 2: the existing files, CI, documentation and records

### Changes

- `tests/integration/test_subscription_processing_flow.py`,
  `test_subscription_suspension_flow.py` - each test whose subscriber lives
  on `peer_app` (no `CallbackProcessor`; `conftest.py:934` is the only
  pre-existing app with one) moves it to `wire_peer_app` and asserts the
  state the callback left, or is deleted when a row covers it. The phase
  notes list which.
- Every `status_code in […]` (179) and every assertion guarded by `if
  …status_code` (47) in `test_subscription_*.py`,
  `test_property_notifications.py`, `test_fanout_flow.py` and
  `test_trust_flow.py` becomes one unconditional status. Exception, per
  Decisions: `test_subscription_baseline_storage.py:71-93` and
  `test_subscription_sync_coverage.py:321-327` post to a list and rely on the
  stray write `WL9` records; they are tightened to what the run shows and
  entered in the registry as expected to change in `spec-1-5` Phase 1.
- The 61 `pytest.skip` calls for missing earlier state become class-scoped
  fixtures, so a failed setup fails.
- `tests/integration/test_property_list_notifications.py` - deleted: seven
  placeholders, which `WL1` to `WL8` replace.
- `tests/integration/test_list_diff_peer_replica.py` - deleted; `WL11.target`
  and `WL13` hold its cases.
- `tests/integration/test_fanout_flow.py` - its first class (`:16-410`) is
  kept, renamed for what it does (several subscribers on the real publish
  path). The file says it tests `FanOutManager`, a granularity downgrade and
  a circuit breaker (`:4`, `:412-413`, `:631-637`, `:881-884`); none runs on
  the publish path. Each test in those three classes is kept under a name
  that says what it asserts about the serial sender, or deleted when it
  asserts nothing.
- `tests/integration/README.md`, `XDIST_GROUPS.md`,
  `docs/contributing/testing.rst` - the wire suite: what a recording holds,
  how to re-record one row, the rule that a phase re-records only the rows
  its plan names, the registry. The stale counts and file names go.
- `thoughts/todo/INDEX.md` - nothing to remove; this plan closes no todo.
- The four plans after this one - a dated line in each Update Log listing
  the recorded outcomes that contradict it, for its next draft.

### New Tests, both unit and integration tests

- None new; the changed files are the tests.

### Failure Scenarios

- A tightened status turns out to differ between backends - a real backend
  difference; recorded and reported, not loosened again.
- A fixture conversion changes the order tests relied on - each converted
  class passes alone (`-k <class>`) as well as in the file.
- Class-scoped fixtures under CI's reruns - these files keep reruns (only the
  wire marker is exempt); whether a rerun re-creates a class fixture is
  checked on one deliberately failing test before the commit.
- A deleted test was the only cover for something - each deletion names the
  row or the unit test that covers it, in the phase notes.

### Verification

- [ ] Run the contract's `### Checks` full tier verbatim (docs build included)
- [ ] `grep -nE "status_code (in|not in) [\[\(]|if .*status_code" tests/integration/test_subscription_*.py tests/integration/test_property_notifications.py tests/integration/test_fanout_flow.py tests/integration/test_trust_flow.py`
      returns only the two registry-listed exceptions
- [ ] `grep -c "pytest.skip(" tests/integration/test_subscription_*.py tests/integration/test_fanout_flow.py`
      shows 0 for each file
- [ ] `git diff --stat master...HEAD -- actingweb examples` is empty
- [ ] `poetry run python tests/integration/verify_groups.py` passes with the
      new groups documented

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
