# Verification: A public compare-and-delete on `Attributes` (re-run)

**Date:** 2026-11-25
**Plan:** thoughts/plans/2026-11-25-attribute-compare-and-delete.md
**Branch:** fix/4.0.0-attribute-compare-and-delete
**Commit:** 086c4fe (the implementation and iterations 1 to 13 are uncommitted in the working tree)

## Automated Check Results

- **Browser QA:** N/A. No phase touches anything a user sees.
- **Second opinion:** the outside-voice agent, with codex
  (`codex exec -s read-only`) and a fresh-context Claude, ran twice on the
  iteration delta: once on entries 1 to 7 and once on entries 8 to 10. Each
  finding was fixed in entries 8 to 12 or accepted below. I reviewed
  entries 11 to 13 myself (a small, simplifying delta) and found the
  legacy-property gap that entry 13 fixes. `/code-review` was not re-run:
  the delta since it ran was reviewed twice by the outside voice
  ("scale reviews to the delta").
- **`ruff check actingweb tests`:** pass.
- **`ruff format --check actingweb tests`:** pass.
- **`pyright actingweb tests`:** 0 errors, 0 warnings.
- **`tests/integration/verify_groups.py`:** pass.
- **`make test-all-parallel` (DynamoDB):** 8728 passed, 217 skipped,
  2 xfailed, 0 failed.
- **`make test-all-parallel` (PostgreSQL):** 8468 passed, 477 skipped,
  2 xfailed, 0 failed.
- **`sphinx-build -W ...`:** build succeeded.
- **Benchmarks:** not re-run. The list path is unchanged since the first
  verification's run (26 passed), and AC-14 still proves one conditional
  write and no read.

The checks ran once, on the final code, with no other test run alongside
them.

## Phase Verification

### Phase 1 and iterations 1 to 13 - VERIFIED

**Changes verified (iterations):**
- `actingweb/db/dynamodb/attribute.py`:
  - `_serialised` covers every data condition and `.set()`
  - `_stored_data_condition(bucket, name, stored)`
  - `json_values_equal`, with the decimal compare for an int against a
    float
  - `_KEY_FIELDS` on the four delete reads (`set_attr` with no data,
    `delete_attr_conditional`, `delete_bucket`,
    `DbAttributeBucketList.delete`)
- `actingweb/db/dynamodb/actor.py`: `rename_creator`'s `equals` and marker
  conditions use `_serialised`. The outside voice checked them: only
  strings reach them, and the serialised condition is unchanged.
- `actingweb/remote_storage.py`:
  - `_refused_unserialisable` deletes the scalar, then logs
  - `_merge_resource` replaces a legacy root and drops only an existing
    refused path
  - a refused value deletes a legacy property
  - `_is_json` and `_without_path`
- `actingweb/attribute.py`: `require_json` runs before the sanitiser.
- `CHANGELOG.rst`, `docs/sdk/attributes-buckets.rst` and
  `docs/migration/v4.0.rst`: updated for entries 2, 6, 9, 11 and 12.

**Deviations from plan:** entries 2, 8 and 11 changed the replica rule.
Entry 2's delete-the-key rule is the owner's 2026-11-25 decision; entries
8 and 11 refine it at resource level. All are recorded in the iterations
log and in the plan's Decisions, ACs and Spec Delta.

## Acceptance Criteria

AC-1 to AC-31 are as in the previous verification, and their tests are
unchanged and passing. AC-35 changed, so it is listed again below.

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-32 | `tests/test_attribute_compare_and_delete.py::TestValuesNamedLikeDynamoDBTypes` - 5 values × (delete `is True` and the row is gone; swap `is True` and the data equals the value; update reads back as the value) | Yes (15 failures plus 3 teardown errors before the fix) | Pass |
| AC-33 | `tests/test_remote_storage_non_finite.py::test_a_refused_value_does_not_leave_the_old_one` - `remote.get_value("a") is None` after a previous `{"v": 3}` | Yes (red before) | Pass |
| AC-34 | `::test_a_list_replaced_by_a_refused_scalar_is_gone` - no list and no scalar | Yes (a guard; green before) | Pass |
| AC-35 | `::test_a_resource_write_into_a_legacy_nan_property_replaces_it` - `== {"y": {"v": 2}}`; a refused write then deletes the property | Yes | Pass (DynamoDB; skipped on PostgreSQL, which cannot hold NaN) |
| AC-36 | `tests/test_attribute_compare_and_delete.py::TestIterationThree::test_large_numbers_compare_as_jsonb_does` - `is match`, both directions | Yes (red on DynamoDB, green on PostgreSQL before: parity proven) | Pass |
| AC-37 | `::test_a_circular_value_is_refused_as_unserialisable` - `_untouchable()` and `UnserialisableValue` | Yes (red before) | Pass |
| AC-38 | `::test_a_row_under_another_name_is_not_deleted` - `is False`; the row remains | Yes (red before) | Pass (DynamoDB) |
| AC-39 | `tests/test_remote_storage_non_finite.py::test_a_refused_resource_value_drops_only_its_path` - `== {"x": 1}` | Yes (red before) | Pass |
| AC-40 | `::TestRowsTheOldUpdateCorrupted` - 4 deletes; `get_bucket(...) == {}` | Yes (red before) | Pass (DynamoDB) |
| AC-41 | `tests/test_remote_storage_non_finite.py::test_a_refused_resource_value_creates_and_replaces_nothing` - `== {"a": 5}` | Yes. The test was written after the code; entry 8's code would have failed it. | Pass |

Every AC is covered.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-25-attribute-compare-and-delete.md
**Iterations since:** entries 1 to 13 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Type-named dicts corrupt or never match (High) | Fixed | entries 1, 9, 12; AC-32, AC-40 |
| 2. A refused peer value leaves the old one (Medium) | Fixed (owner: delete) | entry 2; AC-33 |
| 3. A legacy `NaN` blocks resource writes (Medium) | Fixed | entries 8, 11, 13; AC-35 |
| 4. A list deleted before a refused scalar (Low) | Fixed (the name ends absent; named in the changelog) | AC-34 |
| 5. The sweep raises on a legacy `NaN` row (Low) | Fixed (documented) | entry 6 |
| 6. The sanitiser ran before the refusal (Low) | Fixed | entry 4; AC-37 |
| 7. Numbers past 2**53 (Low) | Fixed | entry 3; AC-36 |
| 8. Cost wording (Low) | Fixed | entry 6 |
| 9. The null condition lacked `name` (Low) | Fixed | entry 5; AC-38 |
| 10. Test type hints (Low) | Fixed | entry 7 |
| Remaining task: owner approval of AC-30 and AC-31 | Done (owner, 2026-11-25) | iterations log, header |

**Findings of the outside voice on the iteration delta, and where they
went:**
- **Entry 2 deleted the whole property at resource level, and the peer's
  valid write was lost (Medium):** fixed in entries 8 and 11.
- **The changelog had no entry for the type-name defect, and corrupt rows
  could not be removed (Medium):** fixed in entries 9 and 12.
- **Entry 8's leaf strip (Medium and Low):** list items shifted, it
  recursed deeply, and dropped values were not logged. Fixed by removing it
  in entry 11.
- **A refused write created or replaced parents (Low):** fixed in entry 11.
- **`delete_attr_conditional` read the full row, and the docs did not
  cover corrupt rows (Low):** fixed in entry 12.
- **The changelog's examples were wrong (Medium):** fixed in entry 12.
- **The `delete_list` branch was unreachable, and the log line came
  before the delete (Low):** fixed in entry 10.

## Remaining Tasks

None.

## Issues Found

No open issue at Medium or above that a peer can reach. Accepted without
code (Low, local only or pre-existing):

- **A `subtarget` starting `list:` in `_merge_resource`** is not refused,
  as `_apply_entry` refuses one. It comes from the local subscription row,
  not from a peer, and predates this plan (outside voice, iteration delta,
  finding 4).
- **Keys that collide after encoding** (`{1: "a", "1": "b"}`) never match
  on DynamoDB. That predates this plan in `conditional_update_attr`.
- **`\u0000` in `expected` on PostgreSQL raises `DbError`.** This is the
  plan's decision.
- **PostgreSQL `set_attr_if_data_equals` writes `data` unsanitised.** This
  predates the plan; only list storage calls it, with ASCII JSON.
- **A 3.x DynamoDB pending-callback queue holding a `NaN` callback at
  upgrade time** makes `_swap_pending` raise. The guard has been in place
  since rc1.
- **Library writers fed parsed request JSON that holds `inf`** now fail
  with `ValueError` on both backends (PostgreSQL already failed). Not
  traced writer by writer.
- **Stored text that `json.dumps` did not write** (a row written outside
  the library) never matches a DynamoDB compare. Such a call answers
  False and never deletes the wrong row. Documented in the plan's Failure
  Scenarios.

## Spec Merge

- `thoughts/specs/store-faults.md`: merged. 14 statements added (SFT-5 to
  SFT-18), 2 modified (SFT-3, SFT-4) and 4 decisions added (SFT-D4 to
  SFT-D7).

## Overall Assessment

The plan and its 13 iterations are implemented and verified:
- `Attributes.delete_attr_if_data_equals` is public, with the strict
  contract the consumer asked for.
- Every conditional attribute compare uses one JSON value equality on both
  backends. Tests show where the backends agree: numbers, null rows,
  `true` against `1`, tuples and int keys.
- Non-finite numbers are refused on every attribute write.
- The DynamoDB serialisation defect, which predates this release and could
  leave an actor undeletable, is fixed, and rows it already wrote can be
  removed.
- The replica fails closed on a value it cannot store, without losing
  paths it was never sent.

Every AC has a test that asserts its result. The Full tier is green on
both backends, with no open issue at Medium or above that a peer can
reach. It is ready to commit. The consumer closes its races once rc4
ships.
