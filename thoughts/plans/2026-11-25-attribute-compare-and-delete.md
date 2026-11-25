---
status: done
approved: 2026-11-25 by Greger Wedel
verified: thoughts/verifications/2026-11-25-attribute-compare-and-delete-2.md
spec_merged: 2026-11-25
iterations: thoughts/plans/2026-11-25-attribute-compare-and-delete.iterations.md
---

# Implementation Plan: A public compare-and-delete on `Attributes`

**Date:** 2026-11-25
**Lane:** small change
**Source:** `thoughts/todo/attribute-compare-and-delete.md`. It was triaged
from a consumer's inbound report, and its facts were verified on 4.0.0rc3
against DynamoDB Local and PostgreSQL.
**Branch:** fix/4.0.0-attribute-compare-and-delete

## Update Log

- **2026-11-25**: Review against the code, with a probe on DynamoDB Local
  and PostgreSQL (Evaluation Notes 14 to 24). Three owner decisions:
  - `conditional_update_attr` gets the null-row fix too
  - `require_json` refuses a non-finite number for every attribute write
  - `\u0000` in `expected` is left alone

  Folded: the null-row condition covers both ways DynamoDB stores null, the
  caller's value is round-tripped through JSON before the compare,
  `expected` is sanitised on both backends, and the migration guide is
  updated. AC-17 changed; AC-20 to AC-27 added.
- **2026-11-25**: Outside voice on the update (Evaluation Notes 25 to 30).
  Folded: every stored-data condition also requires the row and its bucket,
  the non-finite refusal is worded for attribute data and not list items,
  the replica's answer to a peer's non-finite value is named, and the place
  of the JSON round trip is fixed. AC-26 reworded; AC-28 and AC-29 added.

## Overview

An application can delete an attribute only while it still holds the value
the application read, from the public `Attributes` class:
- **True:** this call deleted the row.
- **False:** the row holds something else, or is gone.
- **`DbError`:** the store faulted.

The backends already implement the operation, but DynamoDB compares the
stored JSON text, so a dict whose keys are in another order never matches.
DynamoDB's value compare elsewhere (`conditional_update_attr`) treats `true`
as equal to `1`, which PostgreSQL does not. The plan:
- gives every DynamoDB value compare one type-aware JSON equality, the same
  one PostgreSQL's `jsonb` applies
- makes a null row match `None` on DynamoDB, as it does on PostgreSQL
- makes the bad-value refusals the same on both backends, for every
  attribute write
- makes the operation public

It closes three races in a consumer that stores dict records
(`actingweb_mcp/helpers/shares.py:424, 1095`). Owner: it ships in 4.0.0
through 4.0.0rc4.

## Decisions Made

- **Small-change lane** (owner, 2026-11-25). One phase, about five code files,
  and no data model, auth or permission change.
- **DynamoDB compares by JSON value: a read, a compare, then a conditional
  write** (owner). This is the shape of `conditional_update_attr`
  (`db/dynamodb/attribute.py:341-443`):
  - a consistent read
  - a value compare
  - the delete or update, conditioned on the row existing, its bucket, and
    the **stored** data

  A writer that changes the row between the read and the write fails the
  condition, and the answer is False.
- **A null row is matched in both of its DynamoDB forms** [Updated
  2026-11-25]. DynamoDB Local shows two:
  - `create_attr_if_absent(data=None)` saves no `data` attribute
  - `conditional_update_attr(new_data=None)` writes `data: {NULL: true}`

  `Attribute.data.does_not_exist()` holds only for the first and
  `Attribute.data == None` only for the second. When the read returns null,
  the condition is the two joined with "or". One private helper builds the
  stored-data condition for every caller.
- **Every stored-data condition also requires the row and its bucket**
  (outside voice on the update, finding 25). `does_not_exist()` on `data`
  also holds for a row that is gone, and an `UpdateItem` on a missing key
  creates the item. `conditional_update_attr` conditions on the data alone
  today (`db/dynamodb/attribute.py:432-434`), so with the null branch a row
  deleted between its read and its update would come back with no `bucket`
  or `name`. The helper returns
  `Attribute.id.exists() & (Attribute.bucket == bucket) & <data condition>`.
- **`conditional_update_attr` gets the null-row condition too** (owner,
  2026-11-25). Today `old_data=None` on a null row answers False on DynamoDB
  and True on PostgreSQL: its condition is `Attribute.data == item.data`,
  which misses a row with no `data` attribute. **Behaviour change** on
  DynamoDB: that call now replaces the row.
- **One type-aware JSON equality for every DynamoDB value compare** (owner,
  from the outside voice's finding 10). Its rules:
  - key order doesn't matter
  - numbers compare numerically: `1.0` equals `1`
  - booleans, numbers, strings, null, lists and objects are distinct kinds:
    `true` is not `1`
  - the caller's value is first round-tripped through JSON
    (`json.loads(json.dumps(value))`) [Updated 2026-11-25]. A tuple then
    matches a stored list and an int key matches the stored string key, as
    they do today on both backends (probe; for `conditional_update_attr`,
    `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_strict_compares_as_the_backend_does`).

  It replaces `normalize_json(a) == normalize_json(b)` in
  `conditional_update_attr` (`:409-414`) and in `create_attr_if_absent`'s
  read-back (`:511`), and serves the two `*_if_data_equals` methods. That
  matches PostgreSQL's `jsonb` equality. **Behaviour change** on DynamoDB: a
  `conditional_update_attr` whose `old_data` differs from the stored value
  only by `true` against `1` now answers False.
- **A string `expected` keeps today's single conditional operation** on
  DynamoDB. List storage calls both methods with strings
  (`attribute_list.py:271-287`), and for a string the text compare already is
  the value compare, so those callers pay no extra read.
- **`set_attr_if_data_equals` gets the same fix** (owner). It has the same
  condition (`db/dynamodb/attribute.py:666-689`).
- **The public method always raises on a fault and takes no `strict` flag**
  (owner). That matches `create_attr_if_absent`.
- **Bad values are refused the same way on both backends, before the store is
  touched** (outside voice, findings 1, 7 and 11).
  - `require_json(expected, "attribute data")` raises `UnserialisableValue`,
    which is both a `ValueError` and a `TypeError`.

  PostgreSQL's two methods today encode `expected` inside their `try`, so a
  bad value becomes `DbError`. They gain the check in front, and their SQL is
  unchanged.
- **`require_json` refuses a non-finite number, for every attribute write**
  (owner, 2026-11-25) [Updated 2026-11-25: was a check in the two
  `*_if_data_equals` methods only]. It encodes with `allow_nan=False`
  (`db/exceptions.py:133`). Today, by probe:
  - `set_attr` with `Infinity` stores the row on DynamoDB and raises
    `DbError` on PostgreSQL, where `jsonb` rejects the token
  - `conditional_update_attr(strict=True)` with a non-finite `old_data`
    answers False on DynamoDB and raises `DbError` on PostgreSQL

  **Behaviour change** on DynamoDB: a write of `NaN` or `Infinity` raises
  `UnserialisableValue`. On PostgreSQL the same write raised `DbError`, and
  now raises `UnserialisableValue`. The strict pre-check of
  `conditional_update_attr` (`db/dynamodb/attribute.py:393-399`,
  `db/postgresql/attribute.py:641-646`) also encodes with `allow_nan=False`,
  so a non-finite `old_data` is the caller's `ValueError` on both backends.
  A DynamoDB row that already holds a non-finite number stays readable. It
  can be overwritten or deleted, but not matched by a compare.

  The refusal covers attribute data, not list items: list storage encodes
  each item to a string before the backend sees it
  (`attribute_list.py:550, 587`), so an item holding `NaN` is stored as
  before on both backends.
- **The JSON round trip of the caller's value sits where its failure keeps
  today's answer** (outside voice on the update, finding 28). It encodes
  with `allow_nan=False`.
  - In the two `*_if_data_equals` methods it follows `require_json`, which
    has already refused what it would refuse.
  - In `conditional_update_attr` it stays inside the `try`, where
    `normalize_json` is today. Without `strict`, an `old_data` JSON cannot
    encode, or a non-finite one, still answers False. With `strict` the
    pre-check has raised first.
- **A peer's non-finite scalar is skipped by the replica on both backends**
  (outside voice on the update, finding 27; owner, 2026-11-25). `RemotePeerStore.set_value` writes through `set_attr`
  (`remote_storage.py:193-201`), and the apply loop logs any exception but
  `DbError` at ERROR and answers `{"error": ...}` for that key
  (`remote_storage.py:602-606`).
  - DynamoDB today: the value is stored.
  - PostgreSQL today: `DbError`, which is re-raised (`:602-603`), so the
    callback fails and the peer sends it again.
  - After the change, both: the key is skipped with the ERROR log, and the
    rest of the callback is applied.

  The key is not marked out of step: a rebuild would fetch the same value
  and meet the same refusal.
  [Updated 2026-11-25, implementation] Both apply loops catch
  `UnserialisableValue` and answer `{"error": "refused", "reason": "not
  JSON"}`. In the resync loop any other error puts the key in
  `results.failed`, which keeps a rebuild owed; refused keys are left out
  of it, as for a key collision (AC-30).
  [Updated 2026-11-25, iteration 2; owner] The key is **deleted**, not
  skipped: the replica never serves the peer's previous value as current.
  This also covers a resource merge into a property stored before the
  refusal that holds `NaN`, which would otherwise refuse every later write
  to it (AC-33 to AC-35).
- **`expected` is sanitised on both backends** [Updated 2026-11-25: was
  DynamoDB only] with `sanitize_json_data`, as `conditional_update_attr`
  sanitises `old_data` (`db/dynamodb/attribute.py:390`,
  `db/postgresql/attribute.py:631`). Stored data was sanitised on write. By
  probe, a lone surrogate in `expected` raises `DbError` on PostgreSQL
  today. The rule:
  - both backends sanitise an `expected` that is not a string
  - a string stays as given at the backend, because list storage compares
    what it wrote (`db/dynamodb/attribute.py:518-525`)
  - the public method sanitises `expected` whatever its type, before the
    backend call
- **The cache is unloaded on False**, as `create_attr_if_absent` does on a loss
  (`attribute.py:636-638`). A caller told to re-read then reads the store.
- **The protocol annotation widens** to `expected: Any`
  (`db/protocols.py:1681-1693`). The docs say a custom backend **must**
  compare by JSON value. A backend that compares text answers False to dicts
  whose keys are in another order.

## What We're NOT Doing

- **A `strict` flag or a folding default.** The consumer asked for the
  strict contract, and SFT-D1's folding default is not a model to copy.
- **Writing canonical, sorted JSON on DynamoDB.** Rows already stored keep
  their key order, so it would still need the read-compare path.
- **Changing PostgreSQL's comparison SQL.** `data = %s::jsonb` already
  compares by value (tested in the triage). Only the refusals move in front.
- **A public `set_attr_if_data_equals` on `Attributes`.**
  `conditional_update_attr(strict=True)` already serves compare-and-swap.
- **A parity test for custom backends.** The library's own parity double
  (`tests/_attribute_parity.py:118-137`) delegates to property storage that
  compares strings, and `tests/mcp_token_double.py:329-345` compares with
  Python `==`. Only list storage calls either, with strings, and the new
  tests run on neither. The requirement on custom backends is documented
  instead.
- **Refusing `\u0000` in `expected`** (owner, 2026-11-25). PostgreSQL's
  `jsonb` cannot hold it, so there the call raises `DbError`. DynamoDB can
  store and match it, and a refusal would leave such a row undeletable by
  compare.
- **The consumer's races.** They are closed in the consumer's code once rc4
  ships.
- **A write that landed but whose answer was lost** (an SDK retry). It answers
  as SFT-3 documents. The general problem is
  `todo/conditional-write-ambiguous-after-sdk-retry.md`.

## What Already Exists

- **The backend methods.** `DbAttribute.delete_attr_if_data_equals` and
  `set_attr_if_data_equals` on both backends
  (`db/postgresql/attribute.py:950-999`, `db/dynamodb/attribute.py:666-711`).
  - A failed condition is False, and anything else is `DbError`.
  - The plan reuses both.
- **DynamoDB's read-compare-condition pattern** in `conditional_update_attr`,
  plus `_condition_failed` and `_is_expected_miss`. Reused.
- **`require_json` and `UnserialisableValue`** (`db/exceptions.py:110-135`),
  the house refusal for a value that can't be serialised. Reused.
- **`sanitize_json_data`**, which every DynamoDB write applies. Reused.
- **`Attributes.create_attr_if_absent`** (`attribute.py:602-641`), the model
  for the refusals, for raising on a fault and for unloading on a loss.
- **`Attributes._unload_after_failed_delete`** (`attribute.py:481-494`), the
  fail-safe after a fault. Reused.
- **`tests/_adoption_helpers.seam_fault`**, the fault injection on both
  backends. On PostgreSQL it faults the one statement whichever seam is named.
- **`tests/test_unserialisable_value.py`**, which checks that every write
  refuses a value that can't be serialised. It gains the two
  `*_if_data_equals` methods.

## Acceptance Criteria

- **AC-1** (main path) — When the stored dict equals `expected`,
  `Attributes.delete_attr_if_data_equals(name, expected)` returns True and the
  row is gone from storage.
- **AC-2** (main path, cache) — After a True on an instance whose bucket was
  fully loaded, `get_attr(name)` answers absent.
- **AC-3** (edge: key order) — When `expected` holds the stored dict's keys in
  another order, including inside a nested dict, the row is deleted. This
  holds on both backends.
- **AC-4** (edge: number spelling) — When `expected` holds `1.0` where `1` is
  stored, the row is deleted on both backends.
- **AC-5** (edge: another value) — When the row holds a different value, the
  call returns False and the row is unchanged.
- **AC-6** (edge: absent) — When no row holds the name, the call returns False.
- **AC-7** (edge: another bucket) — When another bucket owns the composite key,
  the call returns False and that row is unchanged.
- **AC-8** (edge: fault) — When the store faults at the read or at the delete,
  the call raises `DbError` and does not return False.
- **AC-9** (edge: fault, cache) — After a fault on a fully loaded instance, the
  next `get_attr(name)` reads the store.
- **AC-10** (edge: bad value) — When `expected` cannot be encoded as JSON, the
  call raises `UnserialisableValue` on both backends, and the store is not
  touched.
- **AC-11** (edge: no name) — When `name` is missing, the call raises
  `ValueError`.
- **AC-12** (edge: race) — When another writer changes the row after this
  call's read and before its delete, the call returns False and the other
  writer's value stays.
- **AC-13** (backend fix: swap) — `set_attr_if_data_equals` with a dict
  `expected` whose keys are in another order replaces the row's data, on both
  backends.
- **AC-14** (no regression: list storage) — On DynamoDB, a string `expected`
  to either `*_if_data_equals` method makes exactly one conditional write and
  no read.
- **AC-15** (added in plan: outside voice 10) — When `expected` holds `1`
  where `true` is stored, the call returns False and the row is unchanged, on
  both backends.
- **AC-16** (added in plan: owner's decision on the shared compare) — On
  DynamoDB, `conditional_update_attr` with `old_data` holding `1` where `true`
  is stored returns False and writes nothing.
- **AC-17** (added in plan: outside voice 12; changed 2026-11-25: both null
  forms) — When the row stores null and `expected` is `None`, the row is
  deleted, on both backends. On DynamoDB this holds for a null row made by
  `create_attr_if_absent(data=None)` and for one made by
  `conditional_update_attr(new_data=None)`.
- **AC-18** (added in plan: outside voice 2) — After a False on a fully loaded
  instance, `get_attr(name)` returns the value now stored, not the cached
  one.
- **AC-19** (added in plan: outside voice 7) — When `expected` contains a
  non-finite number, the call raises `UnserialisableValue` on both backends,
  and the store is not touched.
- **AC-20** (added in update 2026-11-25: review) — When `expected` holds a
  tuple where a list is stored, and an int key where the string key is
  stored, the row is deleted, on both backends.
- **AC-21** (added in update 2026-11-25: review) — When `expected` holds a
  lone surrogate and the row holds the sanitised value, the public call
  deletes the row on both backends and raises nothing. This holds for a dict
  and for a string value.
- **AC-22** (added in update 2026-11-25: review) — `set_attr_if_data_equals`
  with a dict `expected` that differs from the stored value returns False,
  and the row is unchanged.
- **AC-23** (added in update 2026-11-25: review) — On DynamoDB, when another
  writer changes the row after `set_attr_if_data_equals` reads it and before
  it writes, the call returns False and the other writer's value stays.
- **AC-24** (added in update 2026-11-25: review) — When the store faults at
  the read of `set_attr_if_data_equals` with a dict `expected`, the call
  raises `DbError`.
- **AC-25** (added in update 2026-11-25: owner's decision on null rows) —
  `conditional_update_attr` with `old_data=None` on a null row replaces the
  row's data, on both backends and for both DynamoDB null forms.
- **AC-26** (added in update 2026-11-25: owner's decision on `require_json`;
  reworded the same day: list items are out) — Every attribute write whose
  data holds a non-finite number raises `UnserialisableValue` on both
  backends, and nothing is stored. A list item is not attribute data in
  this sense.
- **AC-27** (added in update 2026-11-25: owner's decision on `require_json`)
  — `conditional_update_attr(strict=True)` with a non-finite number in
  `old_data` raises `ValueError`, not `DbError`, on both backends, and the
  row is unchanged.
- **AC-28** (added in update 2026-11-25: outside voice 25) — On DynamoDB,
  when a null row is deleted after `conditional_update_attr(old_data=None)`
  reads it and before it writes, the call returns False and no row exists
  afterwards.
- **AC-29** (added in update 2026-11-25: outside voice 27) — When a peer's
  callback carries a non-finite scalar for one key and a finite one for
  another, the replica stores the second, answers an error for the first,
  and raises nothing, on both backends.
- **AC-30** (added in implementation: tracing the plan's unverified note on
  the resync path) — When a peer's baseline carries a non-finite scalar for
  one key and a finite one for another, the replica stores the second,
  answers `refused` for the first, and does not count it as failed, so the
  rebuild settles. On both backends.
- **AC-31** (added in implementation: tracing `replica_revocation.py`) —
  When a revocation rewrites a scalar without its revoked parts and the
  kept value cannot be stored (a DynamoDB row written before the refusal,
  holding `NaN`), the name is deleted whole, and the rest of the revocation
  is applied.
- **AC-32** (added in iteration 1) — On DynamoDB, a dict whose one key is
  a DynamoDB type name (`{"S": "x"}`, `{"N": 5}`) is compared and written
  as any other value. The compare-and-delete and the swap match it, and
  `conditional_update_attr` writes it as a row that reads back. On both
  backends.
- **AC-33** (added in iteration 2; owner) — When a peer's callback or
  baseline carries a value the replica cannot store for a key that holds a
  value, the key is deleted and answers `refused`, and the rest is applied.
- **AC-34** (added in iteration 2) — When a baseline carries such a value
  for a name that holds a list, the name ends absent.
- **AC-35** (added in iteration 2; changed in iterations 8 and 11) — On
  DynamoDB, a resource write into a replica property stored before the
  refusal that holds `NaN` replaces the property with the peer's write.
- **AC-36** (added in iteration 3) — An int and a float compare as the
  decimals their JSON text names, on both backends: a stored `10**30`
  matches `1e30`, and a stored `2**70` does not match `float(2**70)`.
- **AC-37** (added in iteration 3) — A circular `expected` raises
  `UnserialisableValue`, and the store is not touched.
- **AC-38** (added in iteration 3) — On DynamoDB, a row at the key whose
  `name` differs is not deleted by a compare.
- **AC-39** (added in iteration 8) — When a peer's resource-level value
  cannot be stored, that path is deleted, the property's other paths stay,
  and the answer is `refused`. On both backends.
- **AC-40** (added in iteration 8) — On DynamoDB, a row whose data cannot
  be read back (written by an earlier release's type-named update) is
  removed by `delete_attr`, `delete_attr_conditional`, `delete_bucket` and
  deleting all of an actor's attributes.
- **AC-41** (added in iteration 11) — A refused resource-level value at a
  path whose parents are missing, or whose parent is not an object, leaves
  the property as it was.

## Traceability

All tests are in `tests/test_attribute_compare_and_delete.py` unless named
otherwise. They are marked `integration` and run on the backend
`DATABASE_BACKEND` selects; CI and the Full tier run both. The cache tests
call `get_bucket()` first, so the instance's cache is authoritative
(`attribute.py:383-386`).

| AC | Phase | Test | Status |
| --- | --- | --- | --- |
| AC-1 | 1 | `::TestPublicCompareAndDelete::test_deletes_when_the_value_matches` | Passing |
| AC-2 | 1 | `::TestPublicCompareAndDelete::test_a_deleted_row_is_absent_on_a_loaded_instance` | Passing |
| AC-3 | 1 | `::TestPublicCompareAndDelete::test_key_order_does_not_matter` (flat and nested) | Passing |
| AC-4 | 1 | `::TestPublicCompareAndDelete::test_a_float_matches_an_equal_integer` | Passing |
| AC-5 | 1 | `::TestPublicCompareAndDelete::test_another_value_is_kept` | Passing |
| AC-6 | 1 | `::TestPublicCompareAndDelete::test_an_absent_row_answers_false` | Passing |
| AC-7 | 1 | `::TestPublicCompareAndDelete::test_another_buckets_row_is_kept` | Passing |
| AC-8 | 1 | `::TestPublicCompareAndDelete::test_a_fault_raises` (seams `get`, `delete`) | Passing |
| AC-9 | 1 | `::TestPublicCompareAndDelete::test_a_fault_unloads_the_cached_entry` | Passing |
| AC-10 | 1 | `::TestPublicCompareAndDelete::test_a_value_json_cannot_encode_is_refused`; `tests/test_unserialisable_value.py` (a bad `expected` to each `*_if_data_equals` added) | Passing |
| AC-11 | 1 | `::TestPublicCompareAndDelete::test_a_missing_name_is_refused` | Passing |
| AC-12 | 1 | `::TestPublicCompareAndDelete::test_a_write_between_read_and_delete_wins` (DynamoDB: a hook on the read writes another value before the delete; PostgreSQL: a second value written first, as its compare is one statement) | Passing |
| AC-13 | 1 | `::TestBackendCompare::test_swap_matches_whatever_the_key_order` | Passing |
| AC-14 | 1 | `::TestBackendCompare::test_a_string_takes_one_conditional_write` (DynamoDB only: counts `Attribute.get`, `delete`, `update`) | Passing |
| AC-15 | 1 | `::TestPublicCompareAndDelete::test_true_is_not_one` | Passing |
| AC-16 | 1 | `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_true_is_not_one` | Passing |
| AC-17 | 1 | `::TestPublicCompareAndDelete::test_a_null_row_matches_none` | Passing |
| AC-18 | 1 | `::TestPublicCompareAndDelete::test_a_loss_unloads_the_cached_entry` | Passing |
| AC-19 | 1 | `::TestPublicCompareAndDelete::test_a_non_finite_number_is_refused` | Passing |
| AC-20 | 1 | `::TestPublicCompareAndDelete::test_a_tuple_and_an_int_key_match` | Passing |
| AC-21 | 1 | `::TestPublicCompareAndDelete::test_a_surrogate_in_expected_is_not_a_fault` (dict and string) | Passing |
| AC-22 | 1 | `::TestBackendCompare::test_swap_keeps_another_value` | Passing |
| AC-23 | 1 | `::TestBackendCompare::test_a_write_between_read_and_swap_wins` (DynamoDB only) | Passing |
| AC-24 | 1 | `::TestBackendCompare::test_a_swap_read_fault_raises` | Passing |
| AC-25 | 1 | `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_a_null_row_matches_none` (both null forms) | Passing |
| AC-26 | 1 | `tests/test_unserialisable_value.py::test_a_non_finite_number_is_refused_before_the_store` (every write) | Passing |
| AC-27 | 1 | `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_a_non_finite_old_value_is_not_an_outage` | Passing |
| AC-28 | 1 | `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_a_null_row_deleted_before_the_write_stays_gone` (DynamoDB only) | Passing |
| AC-29 | 1 | `tests/test_remote_storage_non_finite.py::test_a_non_finite_scalar_is_skipped_and_the_rest_applied` | Passing |
| AC-30 | 1 | `tests/test_remote_storage_non_finite.py::test_a_non_finite_scalar_in_a_baseline_does_not_keep_a_rebuild_owed` | Passing |
| AC-31 | 1 | `tests/test_remote_storage_non_finite.py::test_a_rewrite_that_cannot_be_stored_deletes_the_name` | Passing |
| AC-32 | iteration 1 | `::TestValuesNamedLikeDynamoDBTypes` (5 values × 3 operations) | Passing |
| AC-33 | iteration 2 | `tests/test_remote_storage_non_finite.py::test_a_refused_value_does_not_leave_the_old_one` (callback, baseline) | Passing |
| AC-34 | iteration 2 | `tests/test_remote_storage_non_finite.py::test_a_list_replaced_by_a_refused_scalar_is_gone` | Passing |
| AC-36 | iteration 3 | `::TestIterationThree::test_large_numbers_compare_as_jsonb_does` | Passing |
| AC-37 | iteration 3 | `::TestIterationThree::test_a_circular_value_is_refused_as_unserialisable` | Passing |
| AC-38 | iteration 3 | `::TestIterationThree::test_a_row_under_another_name_is_not_deleted` (DynamoDB only) | Passing |
| AC-35 | iteration 2, 8, 11 | `tests/test_remote_storage_non_finite.py::test_a_resource_write_into_a_legacy_nan_property_replaces_it` (DynamoDB only) | Passing |
| AC-41 | iteration 11 | `tests/test_remote_storage_non_finite.py::test_a_refused_resource_value_creates_and_replaces_nothing` | Passing |
| AC-39 | iteration 8 | `tests/test_remote_storage_non_finite.py::test_a_refused_resource_value_drops_only_its_path` | Passing |
| AC-40 | iteration 8, 12 | `::TestRowsTheOldUpdateCorrupted` (4 deletes; DynamoDB only) | Passing |

## Spec Delta

### `thoughts/specs/store-faults.md`

- **ADDED** (Conditional writes) — `Attributes.delete_attr_if_data_equals(name, expected)`:
  - It deletes the row only when it holds `expected`.
  - True: this call deleted the row.
  - False: the row holds something else, there is no row, or another bucket
    holds the key.
  - A store fault raises `DbError` chained to the backend's exception, never
    False.
  - As with SFT-3, a False doesn't prove the delete did not land.

  (AC-1, AC-5 to AC-8, AC-12, AC-17)
- **ADDED** (Conditional writes) — Before the store is touched:
  - a value JSON cannot encode, or a non-finite number, raises
    `UnserialisableValue`
  - a missing name raises `ValueError`

  (AC-10, AC-11, AC-19)
- **ADDED** (Conditional writes) — On an `Attributes` instance whose bucket
  is loaded, `delete_attr_if_data_equals` leaves no stale entry:
  - after True, `get_attr(name)` answers absent
  - after False or a raise, the next `get_attr(name)` reads the store

  (AC-2, AC-9, AC-18)
- **ADDED** (Conditional writes) — A row that stores null matches `None` in
  every conditional attribute compare, on both backends. (AC-17, AC-25)
- **ADDED** (Conditional writes) — A value in `expected` or `old_data` is
  compared as its JSON encoding: a tuple is a list and an int key is its
  string. (AC-20; for `old_data`,
  `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_strict_compares_as_the_backend_does`)
- **ADDED** (Conditional writes) — A lone surrogate in `expected` is
  replaced before the compare, as it is before a write. (AC-21)
- **ADDED** (Conditional writes) — Every attribute write whose data holds a
  non-finite number (`NaN`, `Infinity`) raises `UnserialisableValue` before
  the store is touched, on both backends. List items are not covered: a
  list stores each item as a string. (AC-26)
- **ADDED** (Conditional writes) — A replica deletes a key whose new value
  it cannot store (a peer's non-finite value, or a merge into a property
  stored before the refusal that holds one). The key answers `refused`, the
  rest of the callback or baseline is applied, the key is not marked out of
  step, and it does not keep a rebuild owed. At a resource path only that
  path is deleted, where it exists, and a stored property JSON cannot hold
  is replaced by the next resource write. (AC-29, AC-30, AC-33 to AC-35,
  AC-39, AC-41)
- **ADDED** (Conditional writes) — A revocation whose rewrite of a scalar
  cannot be stored deletes that name whole. (AC-31)
- **ADDED** (Conditional writes) — A `conditional_update_attr` whose row is
  deleted before its write answers False and creates no row. (AC-28)
- **ADDED** (Conditional writes) — A value whose one key is a DynamoDB
  type name is compared and stored like any other value. (AC-32)
- **ADDED** (Conditional writes) — On DynamoDB, deletes read only a row's
  keys, so a row whose data cannot be read back can be deleted. (AC-40)
- **MODIFIED SFT-4** — "a caller's value that JSON cannot order or encode" →
  "a caller's value that JSON cannot order or encode, a non-finite number
  included". (AC-27)
- **ADDED** (Conditional writes) — Every conditional attribute compare uses
  JSON value equality on both backends:
  - `conditional_update_attr`
  - `create_attr_if_absent`'s read-back
  - `delete_attr_if_data_equals` and `set_attr_if_data_equals`

  Under that equality, key order and number spelling don't matter, and
  booleans, numbers, strings and null are distinct. An int and a float
  compare as the decimals their JSON text names (AC-36).

  (AC-3, AC-4, AC-13, AC-15, AC-16, AC-22 to AC-24)
- **MODIFIED SFT-3** — "the row holds something other than `old_data`" →
  "the row holds something other than `old_data` by JSON value equality (a
  stored `true` is not `1`)". (AC-16)
- **DECISION** — On DynamoDB, a compare by value means a consistent read,
  then a write conditioned on the stored data. A string `expected` keeps a
  single conditional write, so list storage pays no extra read.
- **DECISION** — The public compare-and-delete has no folding mode. Like
  `create_attr_if_absent`, a fault always raises.
- **DECISION** — A custom attribute backend must compare `*_if_data_equals`
  by JSON value. The library's docs state the requirement, and no parity test
  enforces it.
- **DECISION** — `\u0000` in `expected` is not refused. PostgreSQL raises
  `DbError` for it, and DynamoDB stores and matches it.

## Phase 1: One value compare, and the public method

### Changes

- **`actingweb/db/exceptions.py`** — `require_json` encodes with
  `allow_nan=False` (`:133`), so a non-finite number raises
  `UnserialisableValue` from every attribute write on both backends. The
  class docstring names it.
- **`actingweb/db/dynamodb/attribute.py`**
  - **A module-level `json_values_equal(a, b)`.** Both sides are JSON
    values: the caller's side is round-tripped through JSON before the call.
    - dicts compare by key set and by value per key, recursively
    - lists compare by position
    - a bool equals only a bool
    - numbers that are not bools compare numerically
    - strings and None compare as themselves
  - **Callers switched to it:** `conditional_update_attr` (`:409-414`) and
    `create_attr_if_absent`'s read-back (`:511`).
  - **A private `_stored_data_condition(bucket, stored)`:**
    `Attribute.id.exists() & (Attribute.bucket == bucket)`, and:
    - `Attribute.data == stored` when the stored data is not null
    - `Attribute.data.does_not_exist() | (Attribute.data == None)` when it is
  - **`conditional_update_attr`:**
    - its update takes `_stored_data_condition(bucket, item.data)` in place
      of `Attribute.data == item.data` (`:430-435`)
    - the caller's `old_data` is round-tripped inside the `try`, with
      `allow_nan=False`
    - its strict pre-check (`:393-399`) encodes with `allow_nan=False`
  - **`delete_attr_if_data_equals` and `set_attr_if_data_equals`:**
    - **Refusal:** `require_json(expected)`.
    - **A string `expected`:** today's single conditional operation, with
      the string as given.
    - **Any other `expected`,** through one private read-and-compare helper
      that both methods share:
      1. `sanitize_json_data(expected)`, then the JSON round trip.
      2. A consistent read. No row, or another bucket's row, is False.
      3. `json_values_equal`. A mismatch is False.
      4. The delete or update, conditioned on
         `_stored_data_condition(bucket, <the stored data as read>)`.
    - **Outcomes:** a failed condition is False, and any other exception,
      the read included, is `DbError`.
- **`actingweb/db/postgresql/attribute.py`**
  - Both methods run `require_json(expected)` before the `try`, and
    sanitise an `expected` that is not a string. The SQL is unchanged.
  - The strict pre-check of `conditional_update_attr` (`:641-646`) encodes
    with `allow_nan=False`.
  - A null row needs no change: it is stored as `jsonb` null, and
    `data = 'null'::jsonb` already matches it (probe: `expected=None` and
    `old_data=None` both matched).
- **`actingweb/db/protocols.py`** — both methods annotate `expected: Any`.
  Their docstrings state the JSON value equality, and that a custom backend
  must implement it.
- **`actingweb/attribute.py`** — new
  `Attributes.delete_attr_if_data_equals(self, name: str, expected: Any) -> bool`:
  - **Refusals:** `ValueError` for a missing name or an unloaded store, as in
    `create_attr_if_absent`.
  - **Before the backend call:** `sanitize_json_data(expected)`, whatever its
    type.
  - **On True:** it drops the cache entry.
  - **On False:** it drops the cache entry and clears `_bucket_loaded`.
  - **On a raise:** it calls `_unload_after_failed_delete(name)` and
    re-raises.

  Its docstring states the contract, and that a row past its TTL is
  compared and deleted like any other (`get_attr` returns such rows too).
- **`docs/sdk/attributes-buckets.rst`**
  - **A new section, "Deleting only what you read",** next to
    `create_attr_if_absent`. It gives the contract and a sweep example.
  - **Line 125:** "always raises" now names both methods.
  - **Lines 113-115 ("How It Works"):** the compare is by JSON value, a
    stored `true` is not `1`, and a null row matches `None`.
- **`docs/migration/v4.0.rst`**
  - **Line 3621:** "compare the stored data exactly" becomes the JSON value
    equality a custom backend must implement.
  - **Lines 3623-3626:** the `UnserialisableValue` sentence names non-finite
    numbers.
  - **A note for an application that upgrades from 3.x,** with the other
    attribute behaviour changes: `conditional_update_attr` no longer matches
    `true` against `1` on DynamoDB (3.15.1 compared the same way), it
    matches a null row, and a non-finite number is refused.
- **`docs/reference/database-backends.rst`** (567-580) — rewrite the
  conditional-operations paragraph:
  - **The methods that raise:** `create_attr_if_absent` and
    `delete_attr_if_data_equals` both raise on a fault. The paragraph no
    longer says `create_attr_if_absent` is "the one".
  - **Value equality:** every compare is by JSON value, and a custom backend
    must do the same.
- **`CHANGELOG.rst`** (`Unreleased`):
  - **`ADDED`:** the public method.
  - **`FIXED`:** four defects, with a bold **Behavior change:** sentence for
    each but the first.
    - On DynamoDB, both `*_if_data_equals` methods missed a dict whose keys
      were in another order. They have been in the library since 4.0.0rc1.
    - On DynamoDB, `conditional_update_attr` and `create_attr_if_absent`'s
      read-back matched `true` against `1`.
    - On DynamoDB, `conditional_update_attr` with `old_data=None` never
      matched a null row.
    - A non-finite number in an attribute write was stored on DynamoDB and
      raised `DbError` on PostgreSQL. Both now raise `UnserialisableValue`.
      The entry says that list items are not covered, and that a replica
      skips a peer's non-finite scalar and logs it.
- **`thoughts/todo/attribute-compare-and-delete.md`** — deleted with its
  `thoughts/todo/INDEX.md` row when the phase lands.

### New Tests (written first: `/implement_plan` sees them fail before coding)

**`tests/test_attribute_compare_and_delete.py`, `TestPublicCompareAndDelete`**
(fresh actor per test, bucket cleaned up):

| Test | AC | What it does |
| --- | --- | --- |
| `test_deletes_when_the_value_matches` | AC-1 | |
| `test_a_deleted_row_is_absent_on_a_loaded_instance` | AC-2 | `get_bucket()` first |
| `test_key_order_does_not_matter` | AC-3 | `{"a": 1, "b": {"x": 1, "y": 2}}` with the keys reversed at both levels |
| `test_a_float_matches_an_equal_integer` | AC-4 | |
| `test_another_value_is_kept` | AC-5 | |
| `test_an_absent_row_answers_false` | AC-6 | |
| `test_another_buckets_row_is_kept` | AC-7 | bucket `a` name `b:c` against bucket `a:b` name `c` |
| `test_a_fault_raises` | AC-8 | `seam_fault` at `get` and `delete`; the row stays |
| `test_a_fault_unloads_the_cached_entry` | AC-9 | `get_bucket()`, fault, change the row behind the instance; `get_attr` sees the change |
| `test_a_value_json_cannot_encode_is_refused` | AC-10 | a `set`; a seam that fails the test if reached |
| `test_a_missing_name_is_refused` | AC-11 | |
| `test_a_write_between_read_and_delete_wins` | AC-12 | DynamoDB: wraps `Attribute.get` to write another value after the real read. PostgreSQL: a second value written first, as its compare is one statement. False, and the other writer's value stays. |
| `test_true_is_not_one` | AC-15 | stored `{"done": true}`, `expected={"done": 1}` |
| `test_a_null_row_matches_none` | AC-17 | parametrised over the row's maker: `create_attr_if_absent(data=None)` and `conditional_update_attr(new_data=None)` |
| `test_a_loss_unloads_the_cached_entry` | AC-18 | `get_bucket()`, change the row behind the instance, a losing call; `get_attr` returns the new value |
| `test_a_non_finite_number_is_refused` | AC-19 | `float("nan")` and `float("inf")`; a failing seam |
| `test_a_tuple_and_an_int_key_match` | AC-20 | stored `{"1": "x", "t": [1, 2]}`, `expected={1: "x", "t": (1, 2)}` |
| `test_a_surrogate_in_expected_is_not_a_fault` | AC-21 | `set_attr` with `"a\ud800b"` inside a dict and as a string, then the same value as `expected`; True |

**`TestBackendCompare`:**

| Test | AC | What it does |
| --- | --- | --- |
| `test_swap_matches_whatever_the_key_order` | AC-13 | |
| `test_a_string_takes_one_conditional_write` | AC-14 | DynamoDB only: counts calls to `Attribute.get` (0) and to `Attribute.delete` / `Attribute.update` (exactly 1 each) |
| `test_swap_keeps_another_value` | AC-22 | |
| `test_a_write_between_read_and_swap_wins` | AC-23 | DynamoDB only: the wrapped `Attribute.get` of AC-12 |
| `test_a_swap_read_fault_raises` | AC-24 | `seam_fault` at `get` |

**Other files:**

| Test | AC |
| --- | --- |
| `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_true_is_not_one` | AC-16 |
| `tests/test_unserialisable_value.py`: both `*_if_data_equals` added to the parametrised writes | AC-10 at the backend, both backends |
| `tests/test_unserialisable_value.py::test_a_non_finite_number_is_refused_before_the_store`: the same parametrised writes with `{"x": float("inf")}`; nothing is stored | AC-26 |
| `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_a_null_row_matches_none`: both null forms, then `old_data=None` replaces the data | AC-25 |
| `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_a_non_finite_old_value_is_not_an_outage`: `ValueError`, not `DbError`; the row is unchanged. Without `strict` the same call answers False | AC-27 |
| `tests/test_conditional_update_attr.py::TestConditionalUpdateAttrJSONComparison::test_a_null_row_deleted_before_the_write_stays_gone`: DynamoDB only; a wrapped `Attribute.get` deletes the row after the real read; False, and a raw read finds no item | AC-28 |
| `tests/test_remote_storage_non_finite.py::test_a_non_finite_scalar_is_skipped_and_the_rest_applied` (new file): a callback through the replica's apply with `{"a": {"v": inf}, "b": {"v": 1}}`; `b` is stored, `a` answers an error, nothing raises | AC-29 |

The existing JSON comparison tests in `test_conditional_update_attr.py` and
`test_create_attr_if_absent.py` must still pass with the new equality.

### Failure Scenarios

| Codepath | Realistic failure | Covered by |
| --- | --- | --- |
| A DynamoDB read, then a conditional write | another writer between the two | condition on the stored data; AC-12 |
| The read | a fault | `DbError`; AC-8 (`get` seam) |
| The new equality | a caller relied on `true` matching `1` | changelog **Behavior change:**; AC-15, AC-16 |
| A null row on DynamoDB | it has no `data` attribute, or `data: {NULL: true}`, by how it was written | a condition that accepts both; AC-17, AC-25 |
| `require_json` refusing non-finite numbers | a DynamoDB application that stores `NaN` today gets `UnserialisableValue` | changelog **Behavior change:** and the migration note; AC-26 |
| A peer sends a non-finite scalar to a replica | the key is skipped where DynamoDB stored it | ERROR log, the rest applied, named in the changelog; AC-29 |
| A null row deleted between `conditional_update_attr`'s read and its write | the "data absent" condition holds for a missing row, and the update creates one | the row and bucket are part of every stored-data condition; AC-28 |
| A DynamoDB row that already holds a non-finite number | no compare can match it | it stays readable, and `set_attr` or `delete_attr` replaces it; migration note |
| The caller's value compared as raw Python | a tuple or an int key stops matching | the JSON round trip; AC-20 and the existing `test_strict_compares_as_the_backend_does` |
| A surrogate in `expected` on PostgreSQL | `jsonb` rejects it: a `DbError` for a caller's value | sanitised first; AC-21 |
| `\u0000` in `expected` on PostgreSQL | `DbError` | accepted (What We're NOT Doing) |
| An SDK retry after a delete that landed | False for a delete that happened | documented as SFT-3; `todo/conditional-write-ambiguous-after-sdk-retry.md` |
| Stored text that doesn't round-trip through `JSONAttribute` (a row written outside the library) | False, never a wrong delete | the condition on the stored text; docs note |
| List storage gaining a read | a performance regression | the string fast path; AC-14 |

### Verification

- [x] The contract's `### Checks` fast tier, verbatim.
- [x] `tests/test_attribute_compare_and_delete.py`,
  `tests/test_conditional_update_attr.py`, `tests/test_create_attr_if_absent.py`
  and `tests/test_unserialisable_value.py` on both backends, with
  `-p no:rerunfailures`.
- [x] `grep -rnE 'float\("(nan|inf)|math\.(nan|inf)' tests/ examples/ actingweb/`
  for a write of a non-finite attribute value that now meets the refusal.
  Today's hits: `tests/test_callback_pending_drain.py:392` and
  `tests/test_replica_rebuild.py:1109`, neither of which stores one.
- [x] `tests/test_remote_storage_non_finite.py` on both backends.
- [x] The Full tier before the commit.
- [x] The list benchmarks are not required: AC-14 proves the list path is
  unchanged.

### Implementation Status: Complete

### Implementation notes (2026-11-25)

- **Red first.** On DynamoDB, 41 of the new tests failed before the code
  change. With the code stashed on PostgreSQL, 13 failed: the refusals
  (AC-10 at the backend, AC-26, AC-27) and AC-29. The rest already hold
  on PostgreSQL, whose `jsonb` compare needed no change. The public-method
  tests fail on the missing method (`AttributeError`), since the method is
  new.
- **Regression guards that were green before the change**, as the plan
  intended: AC-14 (the string path keeps one write), AC-22 (a different
  dict answers False), AC-25's `null_value` form (`data == None` already
  matched it), and AC-28. AC-28 passed before because the old condition
  never matched a null row with no `data` attribute; it protects the new
  `does_not_exist()` branch, which would otherwise recreate a deleted row.
- **Added AC-30.** The resync path that the plan's unverified notes named
  (`remote_storage.py`, `apply_resync_data`) put a refused value in
  `results.failed`. A baseline with a peer's `NaN` would then keep a
  rebuild owed and refetch the same refusal on every rebuild. Fixed in
  `_guarded` and in the resync loop with one helper.
- **Added AC-31.** `replica_revocation.apply_revoked` writes back a scalar
  without its revoked parts. A DynamoDB replica row stored before the
  refusal can hold `NaN`. The rewrite would then raise and stop the
  revocation partway, leaving revoked data in the replica. Now that name
  is deleted whole (fail closed), with a WARNING.
- **Mixed key types without `strict`.** DynamoDB's
  `conditional_update_attr` now round-trips `old_data` with `json.dumps`
  without `sort_keys`. So `{1: "a", "b": 2}` without `strict` is compared
  (as `{"1": "a", "b": 2}`), as PostgreSQL already did, instead of
  answering False. `strict=True` still refuses it (the pre-check sorts).
- **Verification grep.** It found only the two known hits
  (`tests/test_callback_pending_drain.py:392`,
  `tests/test_replica_rebuild.py:1109`); neither stores an attribute.
- **Release placement.** `delete_attr_if_data_equals` on `Attributes` is a
  new public method, which the owner placed in 4.0.0 through rc4. The
  `require_json` refusal and the compare changes are noted as
  **Behavior change:** in the changelog and as item 37 of the migration
  guide's one-line list.
- **Fast tier.** A parallel run of the unit suite showed one failure,
  `tests/test_property_lookup_command.py::TestReport::test_a_marked_name_exits_zero`.
  The file passes alone (37 passed): it is an isolation flake in
  property-lookup marker state, unrelated to attributes.

---

## Evaluation Notes

**Outside voice:** codex (pinned) and a fresh-context Claude (Opus 5.5),
through the outside-voice agent. My own Pass 1 found one wording point,
folded in: on PostgreSQL, `seam_fault` faults the one statement whichever
seam is named.

| # | From | Finding (`file:line` quoted) | Disposition |
| --- | --- | --- | --- |
| 1 | codex | `db/postgresql/attribute.py:983-996`: `json.dumps(expected)` inside `try`, then `raise DbError` — a bad value is a fault on PostgreSQL | Folded: refusals before the `try`; NOT-doing reworded |
| 2 | codex | `attribute.py:636-638`: `self.data.pop(name, None); self._bucket_loaded = False` on a loss, which the plan didn't mirror on False | Folded: unload on False; AC-18 |
| 3 | codex | `attribute.py:383-386`: "A fully-loaded bucket is AUTHORITATIVE" — cache tests pass vacuously unless the bucket is loaded | Folded: `get_bucket()` first in AC-2, AC-9, AC-18 |
| 4 | codex | plan: "two threads ... repeated 5 times" doesn't hit the read-to-delete window | Folded: AC-12 rewritten as a write injected after the read |
| 5 | codex | plan: "asserts zero reads" doesn't count writes | Folded: AC-14 counts exactly one write |
| 6 | codex | `db/dynamodb/attribute.py:390`: `old_data = sanitize_json_data(...)`, absent from the new path | Folded: `expected` sanitised |
| 7 | codex | `db/exceptions.py:133`: `json.dumps(value)` allows NaN | Folded: non-finite refused; AC-19 |
| 8 | codex | `attribute_list.py:270-287`: every library caller passes `str`, so the value path may be unneeded | Rejected: the consumer's rows are dicts (`actingweb_mcp/helpers/shares.py:424` `data=dict(record)`, `:1095`) |
| 9 | codex | plan: "a custom backend keeps working"; `tests/_attribute_parity.py:118` | Folded in part: the docs say custom backends must compare by value (a DECISION). No parity test: the double compares strings for list storage only |
| 10 | Claude | `db/dynamodb/attribute.py:87-94`: `normalize_json` then `==`, so `{'a': True} == {'a': 1}` | Owner decided: one type-aware equality for every DynamoDB compare, `conditional_update_attr` included; AC-15, AC-16; **Behavior change:** in the changelog |
| 11 | Claude | `tests/test_unserialisable_value.py:65`: `pytest.raises(UnserialisableValue)`, against the plan's bare `TypeError` | Folded: `require_json` first; AC-10 says `UnserialisableValue` |
| 12 | Claude | `pynamodb/attributes.py:704-705`: `if value is None: return None` in `JSONAttribute.serialize` (confirmed: `serialize(None)` is `None`) | Folded: `does_not_exist()` condition for a null row; AC-17; PostgreSQL's null storage checked in the phase |
| 13 | Claude | `docs/reference/database-backends.rst:575`: "`create_attr_if_absent` is the one conditional write that **raises**" | Folded: the paragraph is rewritten, plus `docs/sdk/attributes-buckets.rst:125` |
| 14 | update review, probe | DynamoDB Local raw items: `create_attr_if_absent(data=None)` has no `data`; `conditional_update_attr(new_data=None)` has `'data': {'NULL': True}`. `does_not_exist()` holds only for the first, `== None` only for the second | Folded: a condition that accepts both; AC-17 changed |
| 15 | update review, probe | `db/dynamodb/attribute.py:432-434`: `condition=(Attribute.data == item.data)`. `old_data=None` on a null row: False on DynamoDB, True on PostgreSQL | Owner decided: fixed here; AC-25; **Behavior change:** |
| 16 | update review | `tests/test_conditional_update_attr.py:864-876`: "a tuple in ``old_data`` matches the stored list". Probe: `{1: "x", "t": (1, 2)}` deletes a stored `{"1": "x", "t": [1, 2]}` on both backends today | Folded: JSON round trip before the compare; AC-20 |
| 17 | update review, probe | `db/exceptions.py:133`: `json.dumps(value)`. `set_attr` with `Infinity`: stored on DynamoDB, `DbError` (`InvalidTextRepresentation`) on PostgreSQL | Owner decided: `allow_nan=False` in `require_json`, every write; AC-26, AC-27 |
| 18 | update review, probe | `db/postgresql/attribute.py:992`: `json.dumps(expected)` unsanitised. A lone surrogate in `expected`: `DbError` on PostgreSQL, False on DynamoDB, for a dict and a string | Folded: sanitised on both backends and in the public method; AC-21 |
| 19 | update review, probe | A `\u0000` in `expected`: `DbError` (`UntranslatableCharacter`) on PostgreSQL, a match on DynamoDB | Owner decided: not refused; What We're NOT Doing |
| 20 | update review, probe | Plan: "To check: how a null row is stored". `delete_attr_if_data_equals(expected=None)` on a null row is True on PostgreSQL | Folded: `jsonb` null, no `IS NULL` branch |
| 21 | update review | `docs/migration/v4.0.rst:3621`: "(compare the stored data exactly)"; `git show v3.15.1:actingweb/db/dynamodb/attribute.py:305-312` has the same `normalize_json` compare | Folded: the migration guide is updated, with a note for a 3.x upgrader |
| 22 | update review | Plan: AC-13 is the swap's only test, yet its dict path is new | Folded: a shared read-and-compare helper; AC-22 to AC-24 |
| 23 | update review | `tests/_attribute_parity.py:118-137` (the plan said `:518-541`; the file has 209 lines); `tests/mcp_token_double.py:333`: `row.get("data") != expected` | Folded: reference fixed, third double named |
| 24 | update review | Plan: no Spec Delta statement for AC-2, AC-9, AC-18; `thoughts/README.md`: a landed todo is deleted | Folded: Spec Delta statement added; the todo's deletion is in the phase |
| 25 | outside voice (Claude) | `db/dynamodb/attribute.py:432-434`: `condition=(Attribute.data == item.data)`, with no `Attribute.id.exists()` and no bucket | Folded: every stored-data condition requires the row and its bucket; AC-28 |
| 26 | outside voice (codex) | `attribute_list.py:550`: `value_str, carries_marker = json.dumps(item), True` — `require_json` then sees a string | Folded: AC-26, the Spec Delta and the changelog say list items are not covered |
| 27 | outside voice (Claude) | `remote_storage.py:201`: `db.set_attr(name=name, data=sanitized_value)`; `:604-606`: `except Exception as e: logger.error(...)` | Owner decided: skipped on both backends, not marked out of step; AC-29 |
| 28 | outside voice (Claude) | Plan: only "The strict pre-check … encodes with `allow_nan=False`"; the place of the round trip was open | Folded: inside the `try` in `conditional_update_attr`, so the default mode still answers False |
| 29 | outside voice (codex) | Spec Delta: "A value in `expected` or `old_data` … (AC-20, AC-21)" — both test `expected` only | Folded: the statement is split, and `old_data` cites its existing test |
| 30 | outside voice (Claude) | Verification: `grep -rn "nan\|inf"` matches "info"; `tests/test_unserialisable_value.py:57` already lists `set_attr_if_data_equals`, for `data` | Folded: the grep and the AC-10 row are reworded |

**Unverified notes:**
- Outside voice: the replica's resync path (`remote_storage.py:1049-1051`)
  and `replica_revocation.py:138` were not traced to a guard against a
  non-finite value. `/implement_plan` traces them with AC-29's test.
- Outside voice: the token, session, OAuth and trust stores and
  `examples/demo/` were not traced for a non-finite write. The Verification
  grep and the Full tier cover them.
- The five evaluators were not re-run for this update: the review, the
  probe and the outside voice covered the changed parts.
- Whether a bug that existed only in pre-releases (since 4.0.0rc1) belongs
  under `FIXED`. The plan keeps the `FIXED` entry and names rc1, because rc
  users saw it. `/changelog` may fold it into the release's entry instead.

## Implementation Summary

**Completed:** 2026-11-25
**All phases:** Complete
**Test status:** All passing on the final tree. Full tier:
`verify_groups.py` green; `make test-all-parallel` on DynamoDB 8699 passed
and on PostgreSQL 8445 passed, 0 failed; the Sphinx build with `-W`
succeeded. Lint, format and pyright report 0 errors and 0 warnings. An
earlier Full tier run showed one failure, a bug in the new AC-31 test (it
assigned to a frozen dataclass), now fixed.

### Deviations from Plan
- AC-30 added: the replica's resync loop counted a refused non-finite value
  as failed, which would keep a rebuild owed. Both apply loops now answer it
  `refused`.
- AC-31 added: `apply_revoked` deletes a name whole when its rewrite cannot
  be stored (a legacy DynamoDB row holding `NaN`), instead of stopping the
  revocation partway.
- Migration guide: the 3.x upgrade note is item 37 of "The changes, one line
  each".
- Review before close:
  - The docs' sweep example iterated `get_bucket()` while deleting. That is
    the instance's cache, so the loop raised "dictionary changed size during
    iteration" (reproduced). It now iterates over a copy, the method's
    docstring says so, and `::test_the_documented_sweep_runs` runs the
    pattern.
  - `tests/test_unserialisable_value.py::test_a_list_item_is_not_attribute_data`
    proves the list-item boundary of AC-26.
  - The changelog names the DynamoDB mixed-key `old_data` change as a
    **Behavior change:**.
  - The migration guide's "the one conditional write that raises" is
    reworded.
  - `require_json` is called only from the two attribute backends, so
    "every attribute write" is exact.

### Learnings
- Without `strict`, a DynamoDB `old_data` with mixed key types is now
  compared (the round trip does not sort keys), as on PostgreSQL. With
  `strict` it is still refused.
- On PostgreSQL, `seam_fault` faults every statement in the module, so the
  read-fault tests prove only that a fault raises there.

