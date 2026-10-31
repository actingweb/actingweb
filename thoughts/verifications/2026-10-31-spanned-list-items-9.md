# Verification: Spanned list items, Phase 3, second run

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-idempotent-append
**Commit:** 18d7541, plus the uncommitted Phase 3 tree with entries 66-70

**Scope.** Iteration entries 66-70, which answer verification 8 (V8-1 to
V8-10). The owner asked to iterate until a run is clean, then open PR 2.
No feature document and no consumer message.

## Automated Check Results

- **Browser QA:** N/A (no UI).
- **Second opinion:** outside-voice agent, providers codex and a
  fresh-context Claude reviewer: 12 findings (3 codex, 9 Claude), 2
  unverified.
- **Built-in code review** (`/code-review high`): 10 findings.
- **Built-in security review:** nothing at or above its bar. It checked:
  - the permission view and `repair_keys()` reachability (operator and
    application only);
  - key and hash leakage;
  - row-name collisions (anchored `KEY_ROW_RE`, the list name in the row
    name, the per-actor HMAC);
  - whether a caller can steer the age guard or `by` (no: tokens are
    minted on the server, and `encode_item` refuses envelope-shaped
    items);
  - forged announcements;
  - deserialization.
- **Full tier**, at entries 66-70:
  - ruff, format and pyright: 0/0.
  - `verify_groups.py`: 51 documented.
  - DynamoDB: 4944 passed, 40 skipped, 1 xfailed.
  - PostgreSQL: 4752 passed, 232 skipped, 1 xfailed.
  - sphinx `-W`: pass.
- **Benchmark** (run alone, medians):

  | Benchmark | Median |
  | --- | --- |
  | `to_list()` | 15.75 ms |
  | `items_with_handles()` | 14.11 ms |
  | append + remove | 23.51 ms |
  | spanned `to_list()` | 39.38 ms |
  | spanned `items_with_handles()` | 33.34 ms |
  | spanned, `resolve=False` | 12.11 ms |

  All within the noise of the earlier runs.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-8.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| V8-1 (High): a deleted head was adopted | Fixed | entry 66; `test_v8_1_an_item_deleted_before_adoption_is_not_returned` |
| V8-2: the eventual scan missed a crashed head | Fixed (strong scan, the owner's choice) | entry 66; `test_v8_2_the_crash_hole_scan_is_strongly_consistent` asserts every range read is strong |
| V8-3 (High): repairs acted on in-flight calls | Fixed; two gaps left (V9-2) | entry 67; three `test_v8_3_*` tests |
| V8-4: a finished call was never announced | Fixed; the announcement can still be lost (V9-1) | entry 68; two `test_v8_4_*` tests |
| V8-5: docs overclaimed | Mostly fixed; three wordings still overclaim (V9-6) | entry 70 |
| V8-6: docs missing the new API | Fixed | entry 70 |
| V8-7: rank cache off by one | Fixed | entry 69; two `test_v8_7_*` tests |
| V8-8: a carried head outgrew the row | Fixed | entry 69; `test_v8_8_*` |
| V8-9: protocol edges | Partly; the lost adoption still writes a third copy (V9-5) | entry 69; `test_v8_9_*` |
| V8-10: script gating untested | Fixed | `TestRepairScript` |

## Issues Found

### V9-1. An announcement can still be lost, and the docs promise "exactly once"
**Severity:** Medium
**Sources:** codex 1 and 2; Claude 2.
**Location:**
- `actingweb/property_list.py`, `_v2_append_once`: `announce=named.by in
  (None, tok)`.
- `actingweb/interface/property_store.py`, `if result._announce:`.

**Failure:** `by` records who wrote the key row, not whether that call
announced the item. In two cases nobody does:
- An adopter crashes between creating the key row and announcing.
- An adopter backs out because the head changed after the slow writer had
  already decided to stay quiet.

In both, later repeats stay quiet. Exactly-once delivery would need a
second write after the diff, and a crash before that write would then
announce twice: it is at-most-once or at-least-once, not both.
**Recommendation:**
- state "at most once" in every place the docs promise more;
- make the back-out compare the key and token, not the raw bytes, so a
  rewrite never backs out;
- make the announcement contract a public field, not a private one.

### V9-2. Two in-flight gaps in the repair and report
**Severity:** Medium
**Sources:** code review 2 and 9.
**Location:** `_key_findings`, second loop. A key row that names a token
missing from the read is dropped without an in-flight check (when the key
has older heads), and `_key_report` lists every head of an unkeyed key,
fresh ones included.
**Failure:** a repair deletes a running call's key row and writes one
naming a deleted head. The next repeat adopts again and announces a second
time.
**Recommendation:** skip a key whose row names an in-flight token not in the
read, and filter the unkeyed list by age.

### V9-3. The budget exit can delete a head another call adopted
**Severity:** Medium
**Sources:** code review 1; Claude 6.
**Location:** `_v2_append_once` after the loop: `self._retire_own_head(...)`
with no re-read.
**Failure:** a repeat adopts our head in the gap and answers `created=False`
for an item we then delete.
**Recommendation:** re-read the key row; if it names our token, return
`created=True`.

### V9-4. `clear()` frees the key of an item that survives it
**Severity:** Medium
**Source:** Claude 1.
**Location:** `clear()`: `self._delete_aux_rows(self._aux_names("key"))`.
**Failure:** a racing `append_once` keeps its head but loses its key row. A
repeat then adopts the head and announces a second time.
**Recommendation:** delete only the key rows of the heads `clear()`
deleted, as it already does for bodies.

### V9-5. Smaller protocol and API edges
**Severity:** Low
**Sources:** code review 3-6 and 10; Claude 5, 7 and 8; codex 3; Claude 9.
- **Diff position.** An adopted item's diff is an `append`, but the item
  can sit anywhere in the list, so subscribers order it last. It should be
  an `insert` at its position.
- **Wrappers.** `repair_keys()` is missing from the notifying list and the
  permission view (the guide points at `actor.property_lists.<name>`).
- **Lost adoption.** When the adoption create loses to a key row naming
  another head, the call writes a third copy instead of following that
  row.
- **Missing token.** A keyed head with no token is normalised to `""` in
  its key row and then never matched (`None != ""`).
- **Count.** `repair_keys()` leaves `count_hint` low when it only creates a
  key row.
- **Private contract.** `NotifyingListProperty` reads the private
  `_announce` field.
- **Clocks.** The one-hour guard compares host clocks: a token minted far in
  the future hides damage indefinitely, and a slow clock lets a repair
  touch a live call. Name clock sync as a precondition, and treat a token
  dated more than an hour ahead as old.

### V9-6. Documentation that is still wrong
**Severity:** Medium (the owner wants the docs exact)
**Sources:** Claude 3 and 4; codex 2.
- "a ``DbError`` from its key-row create, or from deleting a losing copy,
  can follow an item that committed" (guide and docstring) is incomplete.
  A timeout on the head write, the read-backs, a non-best-effort drop and a
  `ListItemSpanError` from `_resolve` can all follow a stored item.
- "log lines name neither the key nor its hash" is false on PostgreSQL,
  whose backend error logs name the row `list:{name}-$key-{hash}`
  (`actingweb/db/postgresql/property.py:140, :651, :725`).
- "exactly once" (V9-1).

Accepted, not issues:
- The O(heads) strong read on a first call (code review 7) is the plan's
  decision; V8-2 made it strong.
- `compact()` computing the key findings twice (code review 8) is an
  operator path; it costs one small prefix read and one parse of each head.
- `_best_effort` catches `RuntimeError` (Claude, unverified); both backends
  implement every method it calls.

## Overall Assessment

Entries 66-70 close verification 8's Highs, and nothing this run found is
High or Critical. Each review round now finds smaller edges, mostly on
paths that need a crash or a concurrent operator rewrite, but four Mediums
and the documentation wording should be fixed before PR 2 opens, as the
owner asked for a clean run. The plan keeps no `verified:` link until then.
