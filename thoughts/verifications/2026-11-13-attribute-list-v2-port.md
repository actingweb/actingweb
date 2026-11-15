# Verification: one list implementation for properties and attributes, and list diffs that reach a replica

**Date:** 2026-11-13
**Plan:** thoughts/plans/2026-11-13-attribute-list-v2-port.md
**Research:** thoughts/research/2026-11-05-attribute-list-v2-port.md
**Branch:** release/3.16.0-attribute-list-v2-port (not pushed: Phases 2 and 3
close holes open in v3.15.1)
**Commit:** 6d1387c

No feature document; the Success Measures section is omitted.

## Automated Check Results

- **Browser QA:** not run. Phase 4 changes `handlers/www.py` (the list item
  forms, the metadata form, the list and property create forms now register
  diffs; the list form now stores metadata), but no page's rendering changed.
  The form routes were driven over HTTP, not in a browser:
  `tests/integration/test_list_diff_replica.py` (add, update, delete, list
  create, list delete through `/www`, both levels) and `tests/integration/test_wire_list_properties.py::test_wl10_target`.
  The UI was not exercised in a browser.
- **Second opinion:** three providers.
  - outside-voice (codex `exec -s read-only`, plus a fresh-context Claude
    reviewer) on Phase 4 (`e4177e9..6d1387c`): 8 findings, below.
  - built-in `/code-review` at high effort on the branch: 10 findings, below.
  - built-in security review on the branch: no finding at 8/10 confidence or
    above (SQL bound as parameters; every write bucket-conditional; a peer
    confined to `remote:<peer>`; the list-as-unit filter only after
    `_may_read`; `request_resync` per-subscriber grant check).
  - Outside voice also ran on Phases 1, 2 and 3 during implementation; their
    findings are fixed and recorded under each phase of the plan.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (576 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: pass (groups
  documented, wire rows registry consistent, Wire-Phase trailers match
  owners on all four phase commits).
- `make test-all-parallel`, **DynamoDB**: 7,387 passed, 208 skipped,
  2 xfailed (parallel run on `6d1387c`; no failure to re-run).
- `make test-all-parallel`, **PostgreSQL**: 7,167 passed, 428 skipped,
  2 xfailed (parallel run on `6d1387c`; no failure to re-run).
- `sphinx-build -W --keep-going ...`: pass.
- Benchmarks: run in Phases 1 and 2 (the phases that changed list storage),
  recorded in the plan; Phases 3 and 4 do not change the storage path.
- **Emm's suite on `6d1387c`** (environment 9, the library worktree
  re-pointed, Emm's adoption worktree reinstalled; PostgreSQL migrated to
  `a7b8c9d0e1f2` through Emm's `scripts/migrate_db.py`; `check_ready`
  passed at start):
  - PostgreSQL, `pytest --timeout=180 --deselect tests/test_dependency_pin_guard.py`,
    sequential: **3 failed**, 7,405 passed, 14 skipped, 179 deselected. Two
    are the baseline's (`test_dynamodb_iam_coverage.py::test_role_grants_every_dynamodb_action_the_backend_uses`,
    naming the same two actions as the baseline, `TransactWriteItems` and
    `BatchGetItem`, so the nine attribute methods need no new IAM action;
    `test_stripe_integration.py::...::test_create_subscription_proceeds_with_expired_apple_subscription`).
    The third, `tests/test_trial_state_pure.py::test_table[trial expired, active Apple-args7-None]`,
    is Emm's own date bug, not this plan: its fixture `APPLE_ACTIVE` expires
    at `NOW + 20 days` (2026-11-12, NOW fixed at 2026-10-23), and
    `helpers/trial_state.py:191` calls `has_active_apple_subscription(apple_metadata)`
    without the test's `now`, so it checks the wall clock; with the 24-hour
    grace it fails on any library from 2026-11-13. For Emm to fix.
  - DynamoDB lane, `scripts/test-backends.sh 9`: **3 failed**, 54 passed,
    the baseline's three by name.
  - Verdict: no failure the `master` baseline did not have, apart from the
    date-dependent Emm test.

## Phase Verification

### Records commit (`a0952d9`) - VERIFIED

`verify_groups.py` reads a row's owners at each commit's first parent;
`rows.toml` gave Phases 2-4 the rows they re-record; the plan file landed.
Every later re-recording matched an owner (checked by `verify_groups.py`).

### Phase 1: the list format into `list_core` - VERIFIED

**Changes verified:** `actingweb/list_core.py` (`ListCore` over
`ListStorage`), `actingweb/property_list.py` (`ListProperty` over
`PropertyListStorage`, the moved names re-exported, `import time as time`
for consumers that patch `actingweb.property_list.time.sleep`).
**Tests verified:** `tests/test_list_core.py` (structure, frozen surface,
call parity, rank cap, re-export guard), `tests/test_list_core_fault_suite.py`;
the existing property list suites run unedited apart from three patch
targets.
**Deviations:** recorded under the phase (two hooks and split helpers).

### Phase 2: attribute lists on the list core - VERIFIED, with open issues

**Changes verified:** `actingweb/attribute_list.py`,
`actingweb/attribute_list_store.py`, the nine primitives on both backends,
`AttributeKeyCollision`, revision `a7b8c9d0e1f2`, `check_ready()`
(`AttributeSchemaNotReady`), `actor.attribute_lists(bucket)`, the side bucket
teardown, the tool's `--attributes`.
**Security property demonstrated (bucket-conditional writes):**
`tests/integration/test_db_attribute_buckets.py:171`
`with pytest.raises(AttributeKeyCollision): db.set_attr(... bucket="remote:abc", name="x" ...)`
then `assert flat["abc:x"]["data"] == "flat-bucket"`; every primitive in
`tests/integration/test_attribute_list_primitives.py:218-240` (`put_attr`,
`create_attr_if_not_exists`, `create_attrs_if_not_exist`, `set_attr`), each
asserting the other bucket's row is unchanged. Both backends (the Full tier).
**Tests verified:** `tests/test_attribute_list.py`,
`tests/test_attribute_list_store.py`, `tests/test_attribute_list_seams.py`,
the twelve property suites through `tests/_attribute_parity.py`, the
primitive, migration and row-size integration tests.
**Issues:** the conversion race and two smaller ones below (code review
3, 8, 9, 10).

### Phase 3: the replica on the new lists - VERIFIED, with open issues

**Changes verified:** `actingweb/remote_storage.py` (level shapes, binding,
`ReplicaApplyResult`), `actingweb/callback_processor.py` (`REBUILD`,
`begin_rebuild`, `_mark_or_owe`), `actingweb/handlers/callbacks.py`,
`actingweb/interface/subscription_manager.py` (`rebuild_subscription`,
`_rebuild_owed_and_due`), `actingweb/replica_revocation.py`.
**Security property demonstrated (a list diff bound to its key):**
`tests/test_replica_receiver.py:61`
`test_a_value_naming_another_list_is_a_scalar`: a `{"list": "victim",
"operation": "clear"}` value under key `color` leaves `victim == ["keep"]`
and is stored as the scalar `color`; `:71` the legacy `list:notes` key with
`list: victim` is refused and `victim` kept.
**Tests verified:** `tests/test_replica_receiver.py`,
`tests/test_replica_rebuild.py`, `tests/test_replica_revocation.py`,
`tests/test_callback_processor.py::TestOutOfStepRebuild`, the re-recorded
wire rows (31 in the phase commit, `WP4` in its amend).
**Deviations:** recorded under the phase, with the outside-voice fixes; the
untested items the phase names (cost pins at 500/5,000, revocation teardown
of spanned/old/invalid lists) remain untested.
**Issues:** code review 1, 2, 5, 6, 7 below.

### Phase 4: publishers that emit list diffs - ISSUES FOUND

**Changes verified:** `build_list_diff`/`handle_old_item_fields`
(`actingweb/property_list.py`), every table row in
`actingweb/handlers/properties.py` and `actingweb/handlers/www.py`
(`grep -n '"action":' actingweb/handlers/properties.py` returns nothing),
`Actor.request_resync`, the filter as a unit, the two-diff full state,
CHANGELOG, `docs/migration/v3.16.rst` and thirteen more pages, the todos.
**Tests verified:** `tests/test_list_diff_publishers.py` (17),
`tests/test_list_diff_resync_and_filter.py` (9),
`tests/integration/test_list_diff_replica.py` (both levels, the replica
equals the publisher after every edit). Missing as the plan lists them:
per-row spanned variants, two overlapping bulk requests, and any test with
duplicate values (which is where issue OV2 lives).
**Consumer message:** the plan's note to Emm was dropped (owner); its
content is the migration guide's "What to check in your application"
(hooks that branch on a diff's shape; `deleted_names` beside
`revoked_patterns`; test doubles of the attribute store; bucket sweeps and
`$aux`; direct row reads; the replica API; mixed versions). Still accurate,
with one correction owed: the Emm run did not exercise remote memory through
the new rows (its tests patch `AttributeListStore`, as the checklist says).
**Issues:** outside voice 1-8 below.

### Todos

`attribute-list-shift-design.md` deleted with its `INDEX.md` row; the plan
row in `INDEX.md` updated; `attribute-list-old-layout-removal.md` and
`subscription-docs-status-codes-and-fanout-samples.md` filed with rows; the
four edited todos say what landed. No `INDEX.md` row points at a missing
file.

## Remaining Tasks

- [ ] Fix the peer-reachable Medium-and-above issues below (the stop rule:
      clean means none), through `/iterate_plan`, before the PR.
- [ ] Re-run this verification afterwards.
- [ ] Emm: fix `tests/test_trial_state_pure.py` (pass `now` through
      `helpers/trial_state.py:191`); outside this plan.
- [ ] Browser walk of the web-UI list forms, or an explicit owner decision
      that the HTTP-level tests suffice.

## Issues Found

Peer-reachable means a peer or a REST client can trigger it; ordered by
severity.

### OV2. A v2 delete announced as `remove` by value diverges a replica holding duplicates
**Severity:** High (peer-reachable; silent)
**Description:** REST, bulk and web-UI deletes of a v2 item are `remove`
with the item's value; the receiver removes the first equal item. With
duplicates, or a bulk batch whose update creates a duplicate of the item it
then deletes, the replica removes a different row and nothing marks it out of
step (an index `delete` on a drifted replica raised out of step).
**Location:** `actingweb/handlers/properties.py` (`delete_operation = "remove"`
in the items delete; `_PostListDiffs.deleted`), `actingweb/handlers/www.py`
(`delete_op = "remove"`), receiver `actingweb/remote_storage.py`
`list_attr.remove(data["item"])`.
**Scenario:** bulk on `[A,B,C]`: `{index:0, ...C}`, `{index:2}`. Publisher
`[C,B]`; replica: update A→C gives `[C,B,C]`, `remove C` takes index 0,
leaving `[B,C]`.
**Recommendation:** send `delete` with `index` and `old_item`; the receiver
resolves by value only when the match is unique (as `update` does), else by
index, else out of step.

### OV4. A list-scoped resync resets a target-level subscription's whole sequence
**Severity:** High (peer-reachable through any bulk POST over 25 changes)
**Description:** `request_resync("properties", name)` sends a resync for one
list; the receiver's resync clears the whole subscription's pending queue and
records the resync's sequence (`actingweb/callback_processor.py:895`
`self._clear_pending(...)`, `_update_last_seq(..., sequence)`), but its
baseline only carries that list. A diff for another key in the same request
(or queued in a gap) is dropped for good.
**Location:** `actingweb/handlers/properties.py` (`_PostListDiffs.register`
→ `myself.request_resync("properties", self.name)`).
**Recommendation:** for a target-level subscriber send the list's full state
as diffs (`clear` plus `extend`) under the normal sequence; keep the
list-scoped resync for subscriptions to that list.

### OV1. A bulk batch stopped part way announces nothing of what landed
**Severity:** High (peer-reachable; silent)
**Description:** the stop paths register only `if pair:`, and `pair[key]`
is set only at the end of a list's batch, so a single-key bulk that faults
after some writes registers nothing; over 25 changes `applied` stays False,
so no resync either. The class docstring promises the opposite.
**Location:** `actingweb/handlers/properties.py:1713-1714`
`if pair: self._register_post_diffs(myself, pair)` (and `:1719-1720`);
`_PostListDiffs.register` (`if self.applied:`).
**Recommendation:** register whenever `self._post_lists` holds entries, and
mark a resync batch applied (owed) from its first write.

### CR5. A target-level rebuild deletes another target's replica data
**Severity:** Medium (plausible; not traced end to end)
**Description:** the rebuild deletes every name in `remote:<peer>` its
baseline lacks, but that bucket is shared by every auto-stored subscription
to the peer, and the code does not check `sub.target == "properties"`.
**Location:** `actingweb/interface/subscription_manager.py`
(`if not sub.subtarget and isinstance(baseline, dict):` in
`rebuild_subscription`).
**Recommendation:** restrict the stale-name deletion to `properties`
subscriptions, or to names the subscription's target owns.

### CR2. A list name the replica refuses makes every baseline "failed"
**Severity:** Medium (peer-reachable: a publisher's list named `_x`, or a
name over the subscriber's key limit)
**Description:** `set_list` raises `ValueError` for a refused name, recorded
as `{"error": str(e)}`, so it lands in `ReplicaApplyResult.failed`; the
rebuild stays owed and the full baseline is fetched once a minute for ever.
**Location:** `actingweb/remote_storage.py` (`apply_resync_data`'s generic
`except Exception` → `outcome = (key, {"error": str(e)})`).
**Recommendation:** answer a refused name as `{"error": "refused name"}`
there, as the diff path does.

### OV5. `request_resync` can turn a committed bulk POST into a 503
**Severity:** Medium (peer-reachable)
**Description:** a transient fault in one subscriber's resync raises
`DbError` after the batch committed; the request answers 503, later recorders
never register, the miss record is skipped, and a client retry re-applies
index-based deletes to shifted positions.
**Location:** `actingweb/actor.py` (`_send_resync_callbacks` `raise fault`),
reached from `_PostListDiffs.register`.
**Recommendation:** fold the fault in the handler into the miss record and
keep the 2xx.

### CR1. `set_list` checks sizes before `clear()` against the old layout
**Severity:** Medium (peer-reachable through a baseline)
**Description:** for a replica list in both layouts `check_item_size()`
raises `ListLayoutConflictError` before `clear()` (which removes both), so
the conflict is never repaired and the rebuild repeats; an old-layout list
with an item over the span threshold is deleted instead of spanned.
**Location:** `actingweb/remote_storage.py:243` (`set_list`).
**Recommendation:** clear first (or size-check as v2), then extend.

### CR6. An object whose only key is the subtarget is unwrapped
**Severity:** Medium (peer-reachable; data shape)
**Description:** `set(value) == {subtarget}` treats a scalar such as
`status = {"status": "ok"}` as a full-state wrapper and stores `"ok"`
wrapped as `{"value": "ok"}`.
**Location:** `actingweb/remote_storage.py:502` (and `apply_resync_data`).
**Recommendation:** unwrap only a value whose inner part is a list diff or
the `{"_list": true}` form, or mark the full-state wrapper explicitly.

### CR3. A slow converter recreates a row deleted after another finished
**Severity:** Medium (concurrency; attribute lists only)
**Description:** `_convert()` checks for a finished conversion only before
the second batch onward (`if start and ...`); a converter that read the old
rows before another finished recreates a since-deleted rank on its first
batch.
**Location:** `actingweb/attribute_list.py:493`.
**Recommendation:** check the cleanup marker / `-meta` before the first
batch too.

### OV3. Async callbacks never record a miss; the docs say they do
**Severity:** Medium (docs claim)
**Description:** in async mode a scheduled callback counts as sent, so
`request_resync` records no miss, and a lost `clear` leaves the `extend`
doubling the list. The CHANGELOG and the `request_resync` docstring say
misses are recorded.
**Location:** `actingweb/actor.py` (`return True  # Scheduled (not confirmed)`;
`request_resync` docstring).
**Recommendation:** say "with synchronous callbacks" in both, or record from
the async task.

### OV7. A form-created list now exists before the post hook can refuse it
**Severity:** Medium (owner via web UI; a peer via the form POST)
**Description:** the fix that stores metadata for a form list without a
description runs before the hook; a refusing hook answers 403 with the list
left behind and no diff.
**Location:** `actingweb/handlers/properties.py` and
`actingweb/handlers/www.py` (`list_prop.set_description("")` before the
`execute_property_hooks(... "post" ...)` refusal).
**Recommendation:** run the hook first.

### OV6. A rank-addressed web-UI update with a duplicated old value is dropped
**Severity:** Medium (owner-only)
**Location:** `actingweb/handlers/www.py` (`update_fields["index"] = index`
only when `index is not None`); receiver returns `error: ambiguous`.
**Recommendation:** send the resolved position as `index` always.

### CR7. A failed rebuild leaves a gap the pruned batch can never fill
**Severity:** Low (recovers at the gap timeout or the next owed rebuild)
**Location:** `actingweb/callback_processor.py` (batch stopped at `stop_at`,
pending pruned through the batch's end).

### OV8. The CHANGELOG says bulk changes go "in order"
**Severity:** Low (docs)
**Description:** v2 sends ascending updates, appends, then descending
deletes.

### CR8. `prime_from_rows` leaves the instance on the old layout after a conflict
**Severity:** Low. `actingweb/attribute_list.py:733` (`_settle_layout(None,
fresh=True)` never raises; the comment says it does).

### CR9. A permanent extra point read per fresh `ListAttribute`
**Severity:** Low (cost). `actingweb/attribute_list.py:392`: the old `:meta`
probe on every fresh instance; known and accepted in the plan ("one extra
point read per instance"), filed for removal in
`attribute-list-old-layout-removal.md`.

### CR10. A no-op `try/except BaseException: raise`
**Severity:** Low (hygiene). `actingweb/attribute_list.py:547`.

## Overall Assessment

The four phases are implemented as planned, with recorded deviations, and
the Full tier is green on both backends; both security fixes are
demonstrated by named tests on both backends, and Emm's suite shows nothing
beyond its baseline except its own date-dependent test. The publishers'
shapes are not yet safe on the receiving side: a value-addressed `remove`
with duplicates, a list-scoped resync resetting a target-level
subscription's sequence, and a bulk batch stopped part way each diverge a
replica silently, and all three are reachable by a REST client. Those, and
the medium findings on the rebuild and baseline paths (CR1, CR2, CR5, CR6,
OV5), need an `/iterate_plan` pass before the PR opens. The web-UI forms
were exercised over HTTP, not in a browser.
