# Verification: Spanned list items, Phase 3, fourth run (closing)

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-idempotent-append
**Commit:** 18d7541, plus the Phase 3 tree with entries 66-78 (committed
with this document)

**Scope.** Entries 75-77, which answer verification 10; the fourth review
round of them; and entry 78, which withdraws entry 75 in response. This run
closes the plan: Phases 1-2 were verified through verification 7 and merged
in PR #162, and Phase 3 through verifications 8-11.

**Stopping point.** Clean means no High or Critical, and no Medium that is
neither fixed nor recorded as an accepted limit with its rationale.
Adversarial rounds briefed to think like chaos engineers always find
something; four rounds on Phase 3 went from two Highs, to Mediums, to a
High introduced by a fix (the mark). That fix is withdrawn rather than
patched. Another round was not run after the withdrawal: it only removes
code, and what remains has been reviewed three times.

## Automated Check Results

- **Browser QA:** N/A (no UI).
- **Second opinion (round 4, at entries 75-77):** outside-voice agent,
  providers codex and a fresh-context Claude reviewer. Four findings and one
  unverified note. Two failures caused by the mark were reproduced with the
  unit-test fakes.
- **Built-in code review (round 4)** (`/code-review high`): 10 findings.
- **Built-in security review:** nothing at or above its bar, last run at
  entries 66-70. Entries 71-78 add no new reach: the public result fields,
  `repair_keys()` behind `write`, `clear()`'s key rule, and a mark that was
  then removed.
- **Full tier at entries 66-78** (this tree):
  - ruff, format (460 files) and pyright: 0/0.
  - `verify_groups.py`: 51 documented.
  - DynamoDB (`make test-all-parallel`): 4956 passed, 40 skipped, 1 xfailed.
  - PostgreSQL (`make test-all-parallel`): 4764 passed, 232 skipped, 1
    xfailed.
  - sphinx `-W`: pass.
  - The xfailed test is the strict `xfail` that pins the unkeyed `append()`
    SDK-retry duplicate (`thoughts/todo/conditional-write-ambiguous-after-sdk-retry.md`).
- **Benchmark** (run alone, after a pause, medians):

  | Benchmark | Median |
  | --- | --- |
  | `to_list()` | 13.35 ms |
  | `items_with_handles()` | 13.36 ms |
  | append + remove | 24.84 ms |
  | spanned `to_list()` | 32.38 ms |
  | spanned `items_with_handles()` | 29.59 ms |
  | spanned, `resolve=False` | 14.86 ms |

  The Phase 2 baseline is 11.62 / 15.36 / 35.46 ms. A run taken straight
  after the suites showed 23.9 ms for `to_list()`; the quiet re-run shows
  that was load, not code.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-10.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| V10-1: a writer deletes a head a repeat adopted | Accepted limit (entry 78) | The mark that closed it caused V11-1 and V11-2 and is withdrawn. The budget exit no longer deletes. The loser-path window is documented in the guide's "An answer can be overtaken" paragraph. |
| V10-2: an SDK retry of an adoption create is quiet | Fixed | entry 76; `test_an_sdk_retry_of_an_adoption_create_still_announces` |
| V10-3: token normalisation | Fixed | entry 76 |
| V10-4: smaller edges | Fixed | entry 76; `TestVerification10` |
| V10-5: `clear()` leaves old dangling rows | Fixed | entry 76; `test_clear_removes_an_aged_dangling_key_row` |
| V10-6: documentation precision | Fixed | entry 77 |

## Issues Found (round 4) and their fate

### V11-1. The mark broke the SDK-retry read-back, losing an item
**Severity:** High
**Source:** Claude 1 (reproduced).
**Fate:** the mark is withdrawn (entry 78), so this cannot occur. Without
the mark, nothing rewrites another call's head, and `_landed_anyway`'s
byte equality holds again.

### V11-2. A repeat that marked a head and lost left a silent duplicate
**Severity:** Medium
**Sources:** Claude 2 (reproduced); code review 1.
**Fate:** withdrawn with the mark (entry 78). Without the mark, a loser
deletes its own copy as the guide says.

### V11-3. `RuntimeError` at the budget exit can leave the head stored
**Severity:** Low
**Sources:** codex 4; code review 4.
**Fate:** this is now the documented behaviour (entry 78). The exit
deletes nothing, because deleting could remove an item a repeat is
adopting. The docstring, guide and migration guide say the item may be
stored and a repeat with the key finishes it.
`test_attempt_budget_keeps_the_head_for_a_repeat_to_finish` pins it: one
item, and one announcement on the repeat.

### V11-4. Documentation overstatements
**Severity:** Low
**Source:** Claude 3.
**Fate:** fixed with entry 78. The mark paragraph is gone, `RuntimeError`
is reworded, the loser-path window is stated, and `_landed_anyway`'s
"unique to the call" holds again.

### V11-5. The remaining code-review items
**Severity:** Low
- **Stale handle after a mark (code review 2).** Gone with the mark.
- **The loser returning a winner deleted under it (code review 3).** Part
  of the accepted window in V10-1. The guide names it.
- **`compact()` repairs keys before the span check (code review 7).**
  Documented in the `compact()` docstring (entry 78).
- **Accepted for the plan's own reasons, not changed:**
  - the first call's O(heads) strong read (code review 5). The plan
    decided it, and the owner chose the strong read in verification 8;
  - stale hints after `compact()`, repaired by the next repeat (code review
    6). The plan decided this;
  - `compact()` computing the key findings twice (code review 10), an
    operator path;
  - the duplicated arbitration code (code review 9). A refactor is not
    worth its risk at this point;
  - the mark's size margin (code review 8). Gone with the mark.

## Accepted limits (documented)

Each is in `docs/guides/property-lists.rst`, "Idempotent appends":
- **At-most-once announcement.** A call that stops between its key row
  and its diff leaves the item unannounced. `compact()` and
  `repair_keys()` never announce.
- **The loser-path window.** A winner deleted and a loser's copy adopted,
  both within the loser's check-to-delete instant. One `created=False` for
  an item then removed; the next repeat creates it.
- **A delete before a writer's key row.** It behaves as plain `append()`
  racing a delete or `clear()`.
- **Maintenance.** `compact()` and `repair_keys()` need writes quiesced and
  host clocks in sync. The one-hour in-flight guard reads the writer
  token's timestamp.
- **Faults after the item write.** Any exception after the item write may
  follow a stored item. A repeat with the key converges.

## Documentation sweep (the owner's request), final state

- **Updated and checked against the code:**
  - `docs/guides/property-lists.rst`: guarantees, "Idempotent appends", the
    v2 repair sentence.
  - `docs/migration/v3.16.rst`: item 16, "Idempotent appends".
  - `CHANGELOG.rst`: the ADDED entry.
  - `docs/sdk/authenticated-views.rst`: `append_once` requires `write`.
  - `docs/sdk/developer-api.rst`.
  - Docstrings: `append_once`, `repair_keys`, `verify`, `compact`,
    `_landed_anyway`.
  - The script docstring.
  - `thoughts/todo/`: the closed todo deleted, the SDK-retry todo
    narrowed, the subscriber todo and its `INDEX.md` row updated.
- **Not changed:** `actingweb.property_list` still has no autodoc page;
  this predates the plan.

## Overall Assessment

Phase 3 delivers `append_once` as planned, with the strong scan the owner
chose and the maintenance, announcement and documentation work four review
rounds asked for. Nothing above Low remains that is not a documented limit
with its rationale. The tests pin every protocol branch the reviews named,
on both backends, and the full tier is green. The plan is verified; PR 2
can open.
