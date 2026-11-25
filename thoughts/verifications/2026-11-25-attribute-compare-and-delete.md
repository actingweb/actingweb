# Verification: A public compare-and-delete on `Attributes`

**Date:** 2026-11-25
**Plan:** thoughts/plans/2026-11-25-attribute-compare-and-delete.md
**Branch:** fix/4.0.0-attribute-compare-and-delete
**Commit:** 086c4fe (the implementation is uncommitted in the working tree)

## Automated Check Results

- **Browser QA:** N/A. No phase touches anything a user sees (library code,
  docs, tests).
- **Second opinion:** the outside-voice agent ran two providers. Codex ran as
  `codex exec -s read-only` on the working-tree diff (`codex review` needs
  commits), and a fresh-context Claude ran alongside it. The built-in
  `/code-review high` ran in this session. Security review was not run as a
  separate skill: the code review and the outside voice both had the
  attacker and chaos brief over the replica (peer input) paths. Their
  findings are below.
- **`ruff check actingweb tests`:** pass.
- **`ruff format --check actingweb tests`:** pass (642 files).
- **`pyright actingweb tests`:** 0 errors, 0 warnings.
- **`tests/integration/verify_groups.py`:** pass.
- **`make test-all-parallel` (DynamoDB):** 8699 passed, 217 skipped,
  2 xfailed, 0 failed.
- **`make test-all-parallel` (PostgreSQL):** 8445 passed, 471 skipped,
  2 xfailed, 0 failed.
- **`sphinx-build -W ...`:** build succeeded.
- **Benchmarks** (`tests/performance -m benchmark`, alone, DynamoDB):
  26 passed. Median `test_list_attribute_append_remove` 24.0 ms;
  `test_list_attribute_to_list` 18.5 ms. There is no stored baseline. AC-14
  is the evidence that the list path is unchanged: one conditional write and
  no read.

All the runs above were on the final code tree. The only edits since were
to the plan document.

## Phase Verification

### Phase 1: One value compare, and the public method - ISSUES FOUND

**Changes verified:**
- `actingweb/db/exceptions.py`: `require_json` encodes with
  `allow_nan=False`, and the docstring names non-finite numbers. Matches
  the plan.
- `actingweb/db/dynamodb/attribute.py:87-156`: `normalize_json`
  (`allow_nan=False`), `as_json`, `json_values_equal` and
  `_stored_data_condition` (row, bucket and data; the null row accepted in
  both forms). Matches the plan.
- `actingweb/db/dynamodb/attribute.py:722-790`: `_matching_row` (a string
  costs one write; any other value costs a sanitised round trip and a
  consistent read), plus both `*_if_data_equals`. Matches the plan.
- `conditional_update_attr` round-trips `old_data` inside the `try`, and the
  strict pre-check refuses non-finite values. Matches the plan.
- `create_attr_if_absent`'s read-back uses `json_values_equal`. Matches the
  plan.
- `actingweb/db/postgresql/attribute.py`: `_expected` refuses and sanitises
  before the `try`, and the strict pre-check uses `allow_nan=False`. Matches
  the plan.
- `actingweb/db/protocols.py`: `expected: Any`, with the contract for
  custom backends. Matches the plan.
- `actingweb/attribute.py:640-700`: the public method, with its refusals and
  cache handling (pop on True; pop and unload on False; unload on a raise).
  Matches the plan.
- `actingweb/remote_storage.py:595-620, 990-1000` and
  `actingweb/replica_revocation.py`: AC-30 and AC-31 were added during
  implementation and are recorded in the plan's notes. They are not yet
  owner-approved.
- Docs, changelog, and the deletion of the todo with its `INDEX.md` row:
  present. The plan's deferral
  `todo/conditional-write-ambiguous-after-sdk-retry.md` exists and has an
  `INDEX.md` row.

**Failure Scenarios table:** each row has the test or handling the plan
promised:
- the window between read and write: `tests/test_attribute_compare_and_delete.py:211`, `:383`
- a read fault: `:169`, `:396`
- `true` is not `1`: `:227`, `tests/test_conditional_update_attr.py:316`
- both null forms: `:237`, `tests/test_conditional_update_attr.py:373`
- non-finite numbers: `tests/test_unserialisable_value.py:83`
- a peer's non-finite value: `tests/test_remote_storage_non_finite.py:26`
- a null row deleted mid-call: `tests/test_conditional_update_attr.py:393`
- tuples and int keys: `:277`
- surrogates: `:288`
- list storage: `:332`

**Deviations from plan:** AC-30 and AC-31 were added. The docs sweep example
was corrected. A test for the list-item boundary was added. All are recorded
in the plan's notes and are acceptable, pending the owner's approval of
AC-30 and AC-31.

## Acceptance Criteria

All tests in `tests/test_attribute_compare_and_delete.py` unless named.

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-1 | `:110` `test_deletes_when_the_value_matches` - `is True`; `_row(...) is None` | Yes | Pass (both backends) |
| AC-2 | `:119` - `get_bucket()` first; `attrs.get_attr("r") is None` | Yes | Pass |
| AC-3 | `:130` - nested keys reversed; the row is gone | Yes | Pass |
| AC-4 | `:137` - `{"n": 1.0}` against `1`; the row is gone | Yes | Pass |
| AC-5 | `:145` - `is False`; data is `{"v": 2}` | Yes | Pass |
| AC-6 | `:153` - `is False` | Yes | Pass |
| AC-7 | `:160` - bucket `a`/`b:c` against `a:b`/`c`; the other row is kept | Yes | Pass |
| AC-8 | `:169` - `pytest.raises(DbError)` at `get` and `delete`; the row stays | Yes | Pass |
| AC-9 | `:179` - after a fault, `get_attr` sees the change made behind the instance | Yes | Pass |
| AC-10 | `:198` - `_untouchable()` plus `UnserialisableValue`; `tests/test_unserialisable_value.py:70` (two `expected` rows) | Yes | Pass |
| AC-11 | `:206` - `ValueError` | Yes | Pass |
| AC-12 | `:211` - a write injected after the read; `False`, and the other value stays | Yes | Pass |
| AC-13 | `:316` - swap with reversed keys; data replaced | Yes (red on DynamoDB before the change) | Pass |
| AC-14 | `:332` - `calls == ["delete"]` / `["update"]` | Yes (a regression guard) | Pass (DynamoDB; skipped on PostgreSQL by design) |
| AC-15 | `:227` - `{"done": 1}` against `true`; `False`, unchanged | Yes | Pass |
| AC-16 | `tests/test_conditional_update_attr.py:316` - `is False`; data unchanged | Yes | Pass |
| AC-17 | `:237` - both makers; `True`, the row is gone | Yes | Pass |
| AC-18 | `:256` - after a loss, `get_attr` returns `{"v": 2}` | Yes | Pass |
| AC-19 | `:269` - NaN and inf; `_untouchable()` | Yes | Pass |
| AC-20 | `:277` - a tuple and an int key; the row is gone | Yes | Pass |
| AC-21 | `:288` - dict and string surrogates; `True` | Yes | Pass |
| AC-22 | `:372` - `False`, unchanged | Yes (a guard) | Pass |
| AC-23 | `:383` - an injected write; `False`, the other value stays | Yes | Pass (DynamoDB) |
| AC-24 | `:396` - `DbError` at `get` | Yes (red before the change) | Pass |
| AC-25 | `tests/test_conditional_update_attr.py:373` - both forms; data replaced | Yes | Pass |
| AC-26 | `tests/test_unserialisable_value.py:83` (9 writes) plus `:96`, the list-item boundary | Yes | Pass |
| AC-27 | `tests/test_conditional_update_attr.py:992` - `ValueError` not `DbError`; without `strict`, `False` | Yes | Pass |
| AC-28 | `tests/test_conditional_update_attr.py:393` - `pytest.raises(DoesNotExist)` on a raw read | Yes (a guard for the new branch) | Pass (DynamoDB) |
| AC-29 | `tests/test_remote_storage_non_finite.py:26` - `"error" in result["a"]`; `b` stored | Yes | Pass |
| AC-30 | `tests/test_remote_storage_non_finite.py:42` - `result.failed == []` | Yes | Pass |
| AC-31 | `tests/test_remote_storage_non_finite.py:60` - `"legacy"` deleted | Yes | Pass |

Every AC is covered. The issues below concern behaviour that no AC
describes.

## Remaining Tasks

- [ ] Owner approval of AC-30 and AC-31, which were added in implementation.
- [ ] Fix issues 1 to 4 and the Low items listed under "Fix", through
  `/iterate_plan`.

## Issues Found

### 1. A dict whose one key is a DynamoDB type name corrupts the row or never matches
**Severity:** High
**Description:** PynamoDB takes a dict with one key such as `S`, `N`, `M`,
`L`, `NULL` or `BOOL` as an already-serialised AttributeValue, and skips
`JSONAttribute.serialize`. A probe on DynamoDB Local showed:
- `delete_attr_if_data_equals("k", {"S": "x"})` on a row holding that
  value answers False, where PostgreSQL deletes it
- with `{"N": 5}` it raises `DbError` (`SerializationException`), so it
  answers 503 on every retry
- `conditional_update_attr(new_data={"S": "x"})` writes the bare `x`. The
  row can then no longer be read, and `delete_bucket` raises `DbError` on
  it, which blocks actor deletion

The last one already happens on 4.0.0rc3 (probe with the change stashed).
`set_attr_if_data_equals` with a dict `data` has the same `.set()` path.
`set_attr` (a model save) is not affected, so the replica's peer writes are
safe.
**Location:** `actingweb/db/dynamodb/attribute.py:156`
`return row & (Attribute.data == stored)`; `:477`
`[Attribute.data.set(new_data)]`; `:766`
`actions=[Attribute.data.set(data)]`
**Recommendation:** Pass the values to the condition and the update
already serialised (`{"S": json.dumps(...)}`), as `JSONAttribute.serialize`
would. Add a regression test with `{"S": ...}` and `{"N": ...}` for the
compare-and-delete, the swap and `conditional_update_attr`.

### 2. A refused peer value leaves the replica's old value in place
**Severity:** Medium (a peer can trigger it)
**Description:** When a peer changes a key from a finite value to `NaN`, the
key is answered `refused`. The previous value stays in the replica as if it
were current, and nothing marks it stale. AC-31 deletes the name in the same
situation, so the diff applies two different rules.
**Location:** `actingweb/remote_storage.py:610` `_refused_unserialisable`;
`:655`, `:1064` `self.set_value(key, {"value": value})`
**Recommendation:** Fail closed: delete the key (scalar or list) when its new
value cannot be stored. This changes the owner's 2026-11-25 decision
("skipped"), so it needs the owner.

### 3. A legacy `NaN` in a replica property blocks every resource-level write to it
**Severity:** Medium (a peer can trigger it)
**Description:** A resource merge writes back the whole stored root. A
DynamoDB row stored before the refusal that holds `NaN` in another path
makes every later merge into that property refused. Each refusal is logged
as "not JSON", and none counts as failed, so the property stays stuck.
**Location:** `actingweb/remote_storage.py:690`
`self.set_value(subtarget, root)`
**Recommendation:** The same rule as issue 2: delete the name when its new
value cannot be stored.

### 4. In a baseline, a list is deleted before the scalar that replaces it is refused
**Severity:** Low
**Location:** `actingweb/remote_storage.py:1059-1064`
**Recommendation:** Under issue 2's rule the name ends up absent, which is
consistent. Name the outcome in the changelog.

### 5. The documented sweep raises on a legacy `NaN` row
**Severity:** Low (the application's own data, DynamoDB only, written
before rc4)
**Location:** `docs/sdk/attributes-buckets.rst:236`
**Recommendation:** Say in the docs that a stored non-finite value raises
`UnserialisableValue` from the compare, and that a sweep that may meet one
deletes it with `delete_attr`.

### 6. The public method sanitises before it refuses
**Severity:** Low
**Description:** A circular `expected` raises `RecursionError` instead of
`UnserialisableValue`.
**Location:** `actingweb/attribute.py:677`
**Recommendation:** Call `require_json` first.

### 7. Integers and floats beyond 2**53 are not compared as `jsonb` compares them
**Severity:** Low
**Description:** For example, `10**30` against `1e30`.
**Location:** `actingweb/db/dynamodb/attribute.py:118`
**Recommendation:** When an int meets a float, compare
`Decimal(repr(float))` with the int.

### 8. The cost note is inaccurate for a string `expected`
**Severity:** Low
**Description:** The docs and changelog say the compare costs a read, but a
string costs none.
**Location:** `docs/sdk/attributes-buckets.rst:252`; `CHANGELOG.rst:22`
**Recommendation:** Add "for a value that is not a string".

### 9. The null-row condition does not check `name`
**Severity:** Low
**Location:** `actingweb/db/dynamodb/attribute.py:153`
**Recommendation:** Add `Attribute.name == name`.

### 10. Three new tests lack type hints
**Severity:** Low
**Location:** `tests/test_conditional_update_attr.py:316, 373, 393`
**Recommendation:** Add the hints (the project requires them).

### Accepted without code (Low, or the application's own input only)
- **Keys that collide after encoding** (`{1: "a", "1": "b"}`) never match
  on DynamoDB. That was already true of `conditional_update_attr`.
- **`\u0000` in `expected` on PostgreSQL raises `DbError`.** This is the
  plan's decision (What We're NOT Doing).
- **PostgreSQL `set_attr_if_data_equals` writes `data` unsanitised.** This
  predates the diff. Only list storage calls it, with ASCII JSON strings.
- **A 3.x DynamoDB pending-callback queue holding a `NaN` callback at
  upgrade time** makes `_swap_pending` raise. The queue guard
  (`callback_processor.py:680`) has been in place since 4.0.0rc1.
- **Library writers fed parsed request JSON** (`1e999` parses to `inf`) now
  fail with `ValueError` on both backends. On PostgreSQL they already failed
  (`DbError`). Not traced writer by writer: Unverified.

## Spec Merge

- `thoughts/specs/store-faults.md`: not merged. Issue 1 (High) is open.

## Overall Assessment

The plan is implemented as written. Every AC has a test that asserts its
result, and the Full tier is green on both backends. It is not clean yet,
for two reasons:
- **Issue 1 (High):** a DynamoDB serialisation defect in the new
  compare-and-delete, and in the update path the plan touched, where the
  update path can leave an unreadable row that blocks `delete_bucket`.
- **Issues 2 and 3 (Medium):** a peer can trigger them. The replica keeps
  a stale value, or blocks a property, when a peer's value is refused.

Issue 2's fix reverses an owner decision and needs the owner. Issues 1 to
10 (except the accepted ones) go to `/iterate_plan`. AC-30 and AC-31 await
the owner's approval.
