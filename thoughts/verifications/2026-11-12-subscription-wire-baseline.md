# Verification: the subscription wire between two actors, recorded as it is today

**Date:** 2026-11-12
**Plan:** thoughts/plans/2026-11-06-subscription-wire-baseline.md
**Research:** thoughts/research/2026-11-06-subscription-wire-baseline.md (and the spike, thoughts/research/2026-11-07-subscription-wire-spike.md)
**Branch:** release/3.16.0-subscription-wire-baseline (local, six commits, not pushed)
**Commit:** e7df136

First verification of this plan. There is no feature document: the plan
is test-only, and its measure is that a wire change shows as a recording
diff, which the sensitivity check below exercises.

## Automated Check Results

- **Browser QA:** N/A. No phase touches anything a user sees; the web-UI
  form routes are exercised over HTTP by `WL10.target`.
- **Second opinion:** the outside-voice agent ran **Codex** (`codex exec -s
  read-only`, outside the sandbox) and a **fresh-context Claude** reviewer;
  the built-in **code review** ran at high effort (no `--fix`). The
  **security review** was not run: the diff touches no auth, input
  handling or data access in the library (`git diff master...HEAD --
  actingweb examples` is empty). Findings are under Issues Found; one Codex
  finding was rejected (below).
- `poetry run ruff check actingweb tests`: pass
- `poetry run ruff format --check actingweb tests`: pass (557 files)
- `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings)
- `poetry run python tests/integration/verify_groups.py`: pass (43 groups
  documented; wire rows registry consistent; Wire-Phase trailers match)
- `make test-all-parallel` (DynamoDB): pass, 6580 passed, 53 skipped, 1
  xfailed (parallel run, 2026-11-12)
- `make test-all-parallel` (PostgreSQL): pass, 6377 passed, 256 skipped,
  1 xfailed (parallel run, 2026-11-12)
- `sphinx-build -W --keep-going ...`: pass
- The wire step as CI runs it (`pytest tests/ -m wire -p no:rerunfailures`,
  sequential): DynamoDB 298 passed in 247 s; PostgreSQL 298 passed in 93 s.
- Benchmarks: not run; the plan touches no list storage or attribute code.

## Phase Verification

### Phase 1: the remaining flows, recorded - VERIFIED, with issues

**Changes verified:**
- First commit `1929402`: `git show --stat 1929402 -- tests/integration/wire`
  is `rows.toml` only (the schema header), as the plan requires. It holds:
  the async step (`tests/integration/_wire.py:590`, `_run_and_drain`), the
  opt-in callback sort (`_wire.py:557`, `_sort_callback_runs`), the
  replica `read_error` (`_wire.py:407`), the `wire_pair` extensions and
  `class_actor_factory` (`tests/integration/conftest.py:814`), the
  `transformed` hook and `wire_import` `suspend: false`
  (`tests/integration/test_harness.py`), and in `verify_groups.py` the
  `second` key (`:163`) and the trailer check (`:184` `wire_phase_problems`,
  `:241` `check_wire_phase`).
- Second commit `0dade6c`: 63 row variants in 122 files across
  `test_wire_scalar_properties.py`, `test_wire_list_properties.py`,
  `test_wire_delivery.py`, `test_wire_queue_and_lifecycle.py` and
  `test_wire_permissions.py`. `git diff --name-status master...HEAD --
  tests/integration/wire` shows 122 `A` and `rows.toml` `M`: no recording
  the security plans made has changed.
- `git diff --stat master...HEAD -- actingweb examples`: empty.
- No row is `exposure = true`. Since #171/#172 none records data reaching a
  peer that may not read it (`WS2`, `WD9`, `WP6`, `WL16`, each checked in
  the recordings; see the plan's "Recorded outcomes").

**Tests verified:**
- `WD3`'s per-backend timestamp assertion:
  `tests/integration/test_wire_delivery.py:87` (`assert stamps[0] !=
  stamps[1]`, PostgreSQL) and `:91` (`==`, DynamoDB). Both branches ran
  green on their backend.
- `WL13`'s WARNING assertion: `tests/integration/test_wire_list_properties.py:372-378`
  (two "reference to values over the span threshold" records, `append`
  then `update`).
- Planted-violation tests for the registry checks:
  `tests/integration/test_wire_harness.py:356` (registry), `:379` (`second`),
  `:419` (trailer), `:467` (an owner added in the re-recording commit),
  `:429` (async drain), `:448` (sibling sort).
- The normaliser's guard covers every new file: the comparison normalises
  each recording through the guard before it is written or compared
  (`_wire.py`, `normalise`), and all 122 files passed it on both backends.

**Failure Scenarios:**
- Harness artefact: `wire_pair` warms the capability cache by default
  (`conftest.py:1146`, `:1232`); setup is not recorded.
- Timing: five consecutive sequential wire runs per backend at Phase 1
  (297 each), plus the two runs above; never rerun. `WD19` and `WD18`
  remain timing-sensitive (Issue 5).
- Re-recording to green: explicit ids only (`_wire.py:833`), refused under
  `CI` (`:852`), owners checked against the parent commit's registry.
  Bypassable in two commits (Issue 4).
- A row that cannot be made deterministic: none dropped. The rows with
  several subscribers needed the callback sort.
- `WD5`'s task outliving the step: `_wire.py:590` drains the loop.
- `WM1` and an empty memo: `tests/integration/test_wire_queue_and_lifecycle.py:165`
  asserts the memo holds B before B2 subscribes.

**Sensitivity** (plan checkbox; run in Phase 1 on scratch mutations of the
library, reverted, recorded in the plan): all six mutations turned rows red.
The permission-filter mutation was caught only by `WL15` and `WD9`.

**Deviations from plan:**
- `WC8` dropped (`WC3`/`WC4` already record the hook): acceptable, owner to
  confirm.
- The trailer check is local only (CI's shallow checkout): acceptable as a
  deviation, but it needs a todo, filed with this verification.
- `WD18` uses `wire_import` with `suspend: false`; `WS3`/`WS5` are recorded
  in both topologies; `WL1` to `WL5` are split one per REST route. All
  acceptable.

### Phase 2: the legacy files retired - VERIFIED, with one issue

**Changes verified:** `test_subscription_suspension_flow.py`, the
integration `test_property_list_notifications.py` and
`test_list_diff_peer_replica.py` are deleted. Four classes are removed from
`test_subscription_processing_flow.py` and three from
`test_fanout_flow.py`; the kept class is renamed
`TestDiffsQueuedForSeveralSubscribers`. The fourteen groups are gone from
`XDIST_GROUPS.md`.

**Tests verified:** the plan's Phase 2 table names each deletion's cover.
Spot-checked: `tests/test_callback_processor.py` has
`test_fill_gap_processes_pending`, `test_gap_adds_to_pending` and
`test_pending_queue_limit`; `tests/test_fanout.py` covers `FanOutManager`;
`WL11.target` and `WL13.target` cover `test_list_diff_peer_replica.py`.

**Failure scenario** ("a deleted test was the only cover"): no row records
held callbacks draining once the missing sequence arrives; only unit tests
do (Issue 9).

### Phase 3: the remaining subscription files tightened - ISSUES FOUND

**Changes verified:** the plan's greps return nothing. `grep -nE
"status_code (in|not in) [\[\(]|if .*status_code"` over the eleven files
matches no line; `grep -c "pytest.skip("` is 0 in each file. 132 sites are
tightened to the status a logged run showed on both backends. 27 skips
became asserts. `class_actor_factory` fixes the sync-coverage classes,
whose actors were deleted after `test_001`.

**Failure Scenarios:** each converted class passes alone and in its file
(checked in Phase 3). A class-scoped fixture keeps its state across a
`--reruns` retry (checked with a throwaway test).

**Deviations from plan:**
- Skips became asserts, not class-scoped fixtures, except where fixture
  scope was the fault. This meets the plan's purpose (a failed setup
  fails), but it departs from the plan's text: owner to confirm.
- The plan's targets for this phase are met only to the letter of its
  greps. Assertions that cannot fail remain (Issues 1 and 3).

### Phase 4: documentation and records - VERIFIED

- `tests/integration/README.md` and `docs/contributing/testing.rst` have
  "Wire recordings" sections and point at `rows.toml`'s header for the
  schema.
- `XDIST_GROUPS.md` is regenerated from the markers.
- The four later plans have dated Update Log lines.
- `thoughts/todo/INDEX.md` records gate 4 as met.
- The docs build is green.
- Review fix `e7df136` (owners read from the parent commit) is verified by
  `test_wire_harness.py:467`.

## Remaining Tasks

- [ ] Owner decisions on the deviations: skips as asserts, `WC8` dropped,
      the trailer check local only (todo filed:
      `thoughts/todo/wire-phase-check-in-ci.md`).
- [ ] `/iterate_plan` on Issues 1 to 5 below before the PR. Issues 6 to 12
      at the owner's discretion.
- [ ] The first PR run is the first Python 3.11 evidence for every
      recording and tightened status (all were made on 3.14). The CI wire
      step is projected at about 7 min on DynamoDB, against its 10-minute
      limit.
- [ ] The owner's per-phase codex review before the PR.

## Issues Found

### 1. A baseline-storage test returns before anything it is named for
**Severity:** Medium
**Description:** `test_baseline_stores_simple_and_list_properties` asserts
the 204 subscribe and then always returns. The SDK sync and every check
that baseline scalars and lists are stored never run. On `master` the
return was already taken every time (`if response.status_code == 204:`).
Phase 3 made it unconditional instead of fixing it. This is the silent-skip
pattern the phase set out to remove; it is a `return`, so neither of the
plan's greps sees it. The unreachable code also imports
`SubscriptionProcessingConfig` from the wrong module.
**Location:** `tests/integration/test_subscription_baseline_storage.py:121-126`
(`assert response.status_code == 204` … `return`)
**Recommendation:** read the subscription id from the subscriber's listing,
as `_subscription_id` does in `test_subscription_sync_coverage.py`, and let
the rest run.

### 2. The deletion rows cannot see the leftovers they claim are gone
**Severity:** Medium
**Description:** the snapshot reads queued diffs and callback state only
through live subscription rows. If a cleanup removes the rows but leaves
the diff store or the `_callback_state` bucket behind, `WC5` and `WC6` stay
byte-identical, although their `expected` says "A's queued diff … gone" and
"the diffs go with the subscriptions". The teardown does not look for them
either.
**Location:** `tests/integration/_wire.py:342` (`rows =
core.get_subscriptions(callback=False) or []`), `:416` (`rows =
core.get_subscriptions(peerid=publisher.id, callback=True) or []`);
`tests/integration/wire/rows.toml`, `WC5` and `WC6` `expected`.
**Recommendation:** snapshot the diff store and the `_callback_state`
bucket directly, by actor and peer, in those rows (opt-in, as the other
harness additions are), or narrow the two `expected` texts to what the
recording shows.

### 3. Tightened tests that still cannot fail
**Severity:** Medium
**Description:** Phase 3 pinned statuses, but some checks that hold whatever
the code does remain:
- `test_trust_flow.py:564` `assert found_lover or len(str(trusts)) > 0` is
  always true.
- Data-shape guards in `test_subscription_flow.py` skip their body when the
  subscription is not found: `:757` `if sub.get("resource") ==
  "resource":`, `:886` `if "data" in data and len(data["data"]) > 1:`,
  `:911` `if sub.get("granularity") == "low" ...`.
- `test_subscription_sync_coverage.py:176` discards the `sync_peer` result
  (`_ = actor_interface.subscriptions.sync_peer(...)`), so the "cleans dead
  subscription" half of its name is never checked.
- `:384` `assert remote_store.get_list("items") == []` also holds for a sync
  that stores nothing.
- `test_subscription_flow.py:534` pins 400 for a callback its own comment
  calls malformed; whatever a valid callback was meant to prove is gone.

**Location:** as quoted.
**Recommendation:**
- Assert the lookup found exactly one match before each guarded body.
- Assert `result.total_diffs_processed` and that the SDK actor loaded.
- Assert the dead callback subscription is gone.
- Replace the always-true check.
- Decide `test_017`: send a well-formed callback and expect 204, or rename
  it.

### 4. The Wire-Phase check can be bypassed or misread
**Severity:** Medium
**Description:**
- The check ignores merge commits (`--no-merges`), so a recording
  re-recorded while resolving a conflict is never audited.
- Owners come from the parent commit, so one commit can add an owner (no
  `.json` touched, no trailer needed) and the next can re-record under it.
- It diffs against the local `master`; a stale local `master` audits
  commits that are already upstream.
- The pathspec is relative to the working directory, so run from
  `tests/integration/` it reports success without checking anything.
- A malformed `rows.toml` at a parent commit crashes it (`tomllib.loads`
  uncaught).
- The docs call it a pre-commit gate, but it can only check commits that
  already exist.

**Location:** `tests/integration/verify_groups.py:249` (`_git("rev-list",
"--no-merges", "--reverse", f"{merge_base}..HEAD")`), `:218` (`owners =
(rows_before.get(row) or {}).get("owners") or []`), `:238`.
**Recommendation:**
- Read owners at the merge base.
- Include merges, diffed against their first parent.
- Run git from the repository root.
- Report a parse error as a problem.
- Fall back to `origin/master` when the local `master` is behind.
- Reword the docs: it checks commits already made.

### 5. Timing-sensitive rows: WD19, WD18, WD10.import
**Severity:** Medium
**Description:**
- `WD19` must fit five step snapshots, each about fifteen database reads,
  inside the wire apps' 2 s gap timeout. A slow runner makes the
  processor resync instead of answering the recorded 400.
- `WD18` and `WD10.import` record a callback as the method request's
  sibling. The recorder nests by one shared open-request stack
  (`_wire.py:134` `parent = _OPEN[-1] if _OPEN else None`), so a callback
  that reaches B before A's middleware closes the method request would be
  recorded as its child.

All green in ten sequential runs, four parallel runs and the two runs
above; none has been seen on CI.
**Location:** `tests/integration/test_wire_delivery.py:290` (`for sequence
in range(2, 8):`); `conftest.py:1043-1044`; `_wire.py:134`.
**Recommendation:** post `WD19`'s six callbacks in one step (or give the row
a longer gap timeout). Nest by causality, or record the two rows'
top-level order as unordered.

### 6. The callback sort ignores target and granularity
**Severity:** Low
**Description:** the sort key is (receiver, subtarget, resource). Two
sibling callbacks to one subscriber that differ only in target or
granularity keep their random send order. `WM1` has no sort, and will
need it once the memo fix sends to both B and B2.
**Location:** `tests/integration/_wire.py:564-574`
**Recommendation:** use `_sub_order`'s fields in the key. Note in `WM1`'s
entry that the owning phase turns sorting on.

### 7. `_run_and_drain` has no timeout and re-raises task errors
**Severity:** Low
**Description:** a pending task that never finishes hangs the step. A
fire-and-forget task's exception, which production only logs, fails the
step. Only `WD5` uses it today.
**Location:** `tests/integration/_wire.py:590-598`
**Recommendation:** wrap the drain in `asyncio.wait_for`. Decide whether a
task's exception is recorded or raised.

### 8. WL12's `read_error` hides the later steps
**Severity:** Low
**Description:** once B's list cannot be read, every later snapshot is the
same, so what B does with `""`, `False`, `None`, `[]` and `{}` is not
recorded.
**Location:** `tests/integration/_wire.py:407`
**Recommendation:** also record the replica's stored item count and its
metadata length.

### 9. No row records held callbacks draining
**Severity:** Low
**Description:** the Phase 2 table names unit tests for the drain (fixed in
`e7df136`). No wire row sends the missing sequence and records the release
over HTTP with a data hook per released callback.
**Location:** the plan's Phase 2 table (`TestCallbackSequencing`).
**Recommendation:** add a row: post sequences 2 and 3, then 1.

### 10. A duplicate assert, and a subscription id read from a header
**Severity:** Low
**Description:** each subscription setup in `test_property_notifications.py`
asserts 204 twice. The id comes from `Location`, which gives `""` without
a clear error if the header is missing.
**Location:** `tests/integration/test_property_notifications.py:32-36`
(`assert response.status_code == 204, ...` then `assert
response.status_code == 204`)
**Recommendation:** drop the second assert. Read the id from the listing,
or assert the header.

### 11. New test functions have no type hints
**Severity:** Low
**Description:** `CLAUDE.md` asks for type hints on all functions; the new
tests and hooks have none, like the existing wire tests (pyright is clean).
**Location:** e.g. `tests/integration/test_wire_delivery.py`
`def test_wd2_timestamp_formats(wire_pair, topology):`;
`tests/integration/test_harness.py` `def wire_transformed(actor, operation,
value, path):`
**Recommendation:** annotate the new functions, or record that test
functions are exempt.

### 12. `wait_for_quiet` sees only requests that have arrived
**Severity:** Low (note)
**Description:** a scheduled task that has not connected yet can escape its
step. Today only `WD18` and `WD10.import` have such a callback, and both
use `settle=`.
**Location:** `tests/integration/_wire.py:532`
**Recommendation:** none now; keep `settle=` mandatory for top-level
callbacks.

**Rejected:** Codex's claim that `WD9`'s 2.5 s sleep could fall short under
load. The sleep starts after sequence 2's `_received_at` is stored, so load
only lengthens the gap.

## Overall Assessment

The plan is implemented as written, with deviations that are named and
reasoned. Every phase's verification commands pass on the final commit,
and the Full tier is green on both backends. The recordings are
deterministic across every run made: ten sequential, four parallel, and two
more for this document. The library is untouched, and the six sensitivity
mutations show the recordings catch real wire changes. The plan's
central measure, that a wire change becomes a recording diff, is met.

Issues 1 to 5 should go through `/iterate_plan` before the PR. Each is a
test that claims more than it checks (a silent early return, a snapshot
blind to leftovers, assertions that cannot fail) or a gate that can be
bypassed or can flake. None is a library defect, and none is
peer-reachable. The three deviations need the owner's confirmation, and
the first PR run is the first evidence on Python 3.11.
