# Verification: Spanned list items (Phases 1 and 2), second run

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-spanned-list-items
**Commit:** fd7767f (plus an uncommitted fix to the QA setup order in
`examples/demo/README.md` and `CLAUDE.md`, made during this run)

**Scope.** Phases 1 and 2 and the plan's iteration entries 1-17. Phase 3
(`append_once`) is not implemented, so the plan's `verified:` link is not set
and the plan stays `status: active`. No feature document exists.

**No todos.** At the owner's direction (2026-10-31), nothing found while
verifying this plan is filed for later. The two todos the first iteration
batch created were fixed in batch two and deleted; every finding below is
open work for this plan, to be fixed in the next iteration batch before PR 1
opens.

## Automated Check Results

- **Browser QA:** Ran. Provider: headless Playwright 1.61.1 (Node, Chromium
  headless shell, outside the sandbox); no window opened. The QA account came
  from the new local mode (`DEMO_QA_BASIC_AUTH=true`, `localhost:5055`, a
  throwaway actor created through `POST /` and deleted afterwards). Main path
  works end to end; nine findings (two medium, seven low), folded in below.
- **Second opinion:** outside-voice agent, providers codex
  (`codex exec -s read-only`) and a fresh-context Claude reviewer: 17
  findings (one refuted by the agent itself), folded in below.
- **Built-in code review** (`/code-review high a176a82..fd7767f`, no
  `--fix`): 10 findings, folded in below.
- **Built-in security review:** no finding at or above the confidence bar.
  Checked and closed: XSS through `|tojson` in the new templates, the
  plain-text error bodies, CSRF relative to the existing posture, the
  `DEMO_QA_BASIC_AUTH` guard, the permission view's new methods, the `$aux`
  check, `_landed_anyway`, the digest, `fit_full_state`.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (455 files).
- `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings).
- `poetry run python tests/integration/verify_groups.py`: pass (51 groups).
- `make test-all-parallel` (DynamoDB): pass, 4,598 passed, 40 skipped.
- `make test-all-parallel` (PostgreSQL, the contract's env): pass, 4,446
  passed, 192 skipped.
- `sphinx-build -W --keep-going ...`: pass.
- Benchmarks: not re-run in this pass (no change to the plain-list read
  path since the 2026-10-31 run, which was within 5% of the baseline).

## Phase Verification

### Phase 1 - VERIFIED

Unchanged since the first verification except entries 7 (bulk pre-check),
14 (the 9,999-part cap) and 15 (status mappings), each tested in
`tests/test_list_item_limits.py` and `tests/test_property_list_span_iterations.py`.
One residual: the part cap does not account for non-ASCII splits (L1 below).

### Phase 2 - ISSUES FOUND

**Changes verified:** the iteration entries 1-17 are present as described:
`_write_spanning`/`_landed_anyway` (`property_list.py`), `_ItemGone` and
`_resolve_pairs`, compact's pre-copy, `delete()`'s age gate, the tolerant
`_handle_for`/`_unresolved_or_item`/`_head_equals`, `sweep_span_orphans()`,
`_sought_size`, `fit_full_state` and `Actor._list_state_reference`,
`Properties._delete_side_partition`'s `$aux` check and leak WARNING, the
SHA-256 digest, `WwwHandler._list_action_error`, and the demo's list page.

**Tests verified:** `tests/test_property_list_span_iterations.py` holds one
class per finding (each failed before its fix, recorded in the plan); the
full suites above pass on both backends.

**Deviations from plan:** three fixes created new problems (H1's fix leaks
bodies on known failures, M1's fix leaves unsweepable rows, M2's fix can
delete pre-3.16 user items); see V1, V3, V7.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| H1 ambiguous head write loses the item | Fixed, with a regression (V3) | Iteration 1; `TestH1AmbiguousHeadWriteKeepsTheBodies` |
| H2 concurrent delete answers 409 | Fixed | Iteration 2; `TestH2ConcurrentDeleteIsNotCorruption` |
| H3 compact duplicates on an unreadable span | Fixed, with a regression (V3) | Iteration 3; `TestH3CompactRefusesBeforeWritingAnything` |
| M1 `delete()` races an in-flight append | Fixed, with a regression (V7) | Iteration 4; `TestM1DeleteKeepsAFreshUnnamedGeneration` |
| M2 malformed heads block the list | Fixed, with a regression (V1) | Iteration 5; `TestM2MalformedHeadsCanBeRemoved` |
| M3 identity verify blocks the sweep | Fixed | Iteration 6; `TestM3IdentityVerifyReportsABrokenSpan` |
| M4 bulk 413 after partial writes | Fixed | Iteration 7; `TestBulk413WritesNothing` |
| M5 reference diffs overflow / no resync | Fixed (receiver fetch stays out of scope); residuals L4, L5 | Iteration 12; `TestM5FullStateFitsTheDiffRow` |
| M6 threshold change hides spanned items | Fixed | Iteration 10; `TestM6ValueScansAfterAThresholdChange` |
| M7 sweep rebalances | Fixed | Iteration 11; `TestM7SweepWithoutRebalance` |
| M8 `$aux` actor wiped on delete | Fixed for delete; write side open (L3) | Iteration 13; `TestM8AndL4ActorLevelSweep` |
| L1 limit pair / `$` precondition | Fixed; non-ASCII residual (L1 below) | Iteration 14 |
| L2 status mappings | Fixed; escaping bug (V9) | Iteration 15; `TestHandlerStatusMappings` |
| L3 metadata GET isolation | Fixed | Iteration 15 |
| L4 envelope-shaped pre-3.16 items, leak log, digest | Leak log and digest fixed; digest repair gap (V2); pre-3.16 items now deleted by the sweep (V1) | Iterations 13, 16 |
| Browser QA not run | Ran | This document |
| www UI gaps (first browser walk) | Fixed; new form issues (V4-V6, V8) | Iteration 17 |

## Remaining Tasks

- [ ] Fix V1-V9 and L1-L10 below in the next iteration batch, each with a
      regression test, before PR 1 opens (no todos, by the owner's
      direction).
- [ ] Commit the QA setup-order fix to `examples/demo/README.md` and
      `CLAUDE.md` (the first start creates the tables and stops with
      `UniqueCreatorNotReady`; the backfill runs after it).
- [ ] Phase 3 (`append_once`) on its own branch after PR 1 opens.

## Issues Found

### V1. The span sweep deletes user items that predate 3.16
**Severity:** High
**Description:** a v2 item stored since 3.14 that is a dict whose first key
is `__aw_env` with a value other than `1` (`{"__aw_env": "x", ...}`) starts
like an envelope, fails `parse`, and is classed a malformed head;
`sweep_span_orphans()` (and `--repair --sweep-spans`, which now triggers on
malformed heads) deletes it with only a WARNING. The first verification
asked for such items to be reported, not removed.
**Location:** `actingweb/property_list_span.py` `parse` (`if next(iter(obj))
!= ENVELOPE_MARKER or isinstance(marker, bool) or marker != 1: raise
EnvelopeError`); `actingweb/property_list.py` `_sweep_spans` (`for rank in
malformed: ... delete_if_value_equals(...)`);
`actingweb/maintenance/verify_property_lists.py` sweep trigger.
**Recommendation:** remove only heads with the exact marker `1` that fail a
later check; report the rest, or put their removal behind an explicit flag.

### V2. A digest or size mismatch gives a 409 its named repair cannot fix
**Severity:** Medium
**Description:** `_read_span` rejects a body whose bytes or SHA-256 differ,
so reads raise `ListItemSpanError` ("3 body row(s) but 3 matching row(s)
were found; run ... --sweep-spans"), but `_span_inventory` compares row names
only: `verify(spans=True)` reports nothing, the sweep removes nothing, and
`compact()` aborts on every run. Raised by the code review and the outside
voice.
**Location:** `actingweb/property_list.py:1017` (`if span.sha256 is not None
and value_digest(joined) != span.sha256: return None, found`); `_span_inventory`
(`if set(by_gen.get(span.gen, [])) != expected`).
**Recommendation:** let `verify(spans=True)` and the sweep check content
(they already pay for every body byte), and word the 409 for this case.

### V3. Known failed writes now leak body generations
**Severity:** Medium
**Description:** `_write_spanning` keeps the bodies on every exception from
`head_write`, including failures where no head was written (the append and
insert rank loops' "too many rank collisions" and rank-cap `RuntimeError`, a
`_v2_last_rank()` fault), and logs them as "unknown outcome"; every retry of
a contended spanned append leaks another generation until the aged sweep.
`_v2_extend` keeps the in-flight item's bodies the same way. `compact()`
pre-copies every moving item, and a storm or a `set()` returning `False` in
the write loop leaves all remaining copies. The comment in `_v2_append`
still says an exhausted loop deletes the bodies.
**Location:** `actingweb/property_list.py:965` (`_write_spanning`), the
`_v2_append` comment, `_v2_extend`'s fault path (`head_spans[created + 1 :]`),
`_v2_compact` write loop.
**Recommendation:** distinguish not-landed failures (a typed exception from
the rank loops, a `False` from `set`) from unknown outcomes; delete bodies on
the former, keep them only on the latter; in compact, delete the copies of
items not yet written.

### V4. The demo's item forms address items by position
**Severity:** Medium
**Description:** the edit and delete forms post `item_index`
(`loop.index0`), and the handler resolves that position against a fresh read
at POST time, so a list changed between page load and submit (a peer, a
second tab) makes "Delete item 3" delete, or "Save item" overwrite, a
different item, with no error. Raised by the code review and the outside
voice.
**Location:** `examples/demo/templates/aw-actor-www-property.html` (the
hidden `item_index` inputs); `actingweb/handlers/www.py` update and delete
actions.
**Recommendation:** post the item's rank and a digest of its raw value, and
refuse when they no longer match.

### V5. The demo's item forms ignore read-only lists
**Severity:** Medium
**Description:** `www.py` computes `is_read_only` from the put hook and
passes it to the template, which never reads it; the `/items` POST runs no
property hook before writing, so a list an app protects with a put hook gets
working Add, Save and Delete buttons.
**Location:** `actingweb/handlers/www.py:354` (`is_read_only`), the `/items`
POST branch; the demo template.
**Recommendation:** hide the forms when `is_read_only`, and run the put hook
in the `/items` POST.

### V6. A corrupted list shows as "This list is empty"
**Severity:** Medium
**Description:** when loading a list fails, `www.py` sets `value` to the
corruption message and `list_items = []`; the new list branch never renders
`value`, so the owner sees an empty list and can keep adding to it.
**Location:** `actingweb/handlers/www.py:390`;
`examples/demo/templates/aw-actor-www-property.html` (`This list is empty.`).
**Recommendation:** render the error message in the list branch.

### V7. `delete()`'s age gate leaves rows nothing can sweep
**Severity:** Medium
**Description:** `delete()` now keeps unnamed body generations younger than
an hour; once the meta row is gone, `sweep_span_orphans()`/`compact()` refuse
the list and `verify_orphans` reports `{id}$aux` rows only when the actor is
gone, so they stay until the actor is deleted. If an in-flight append's head
lands after the delete, the kept bodies make it a whole item that a list
recreated under the same name adopts as valid data (before the fix it read as
a 409). Raised by the code review, the outside voice and codex.
**Location:** `actingweb/property_list.py:2814` (`young = {...}` in
`delete()`).
**Recommendation:** decide between documenting that `delete()` needs writes
quiesced (and reverting to a full sweep), and recording deleted list names so
a later sweep can finish them.

### V8. The demo's list page loads and posts whole items
**Severity:** Medium
**Description:** the page resolves every item (`www.py:378`
`list_items = list_prop.to_list()`) and puts each item's full JSON in a
textarea: unbounded page size and read cost for a list of large items. The
textarea holds `tojson` output (keys sorted, `<>&'` and non-ASCII as
`\uXXXX`), so saving an item unchanged rewrites it with reordered keys and a
diff, the size label counts escaped characters, and form encoding grows the
post (`&` to `%26`) past the demo's request limit: the browser walk saw
Werkzeug's bare HTML 413 for an item of 4 MiB and for 1.5 MiB of `&`, and
the large item's preview shows only `{"body": "zzz…` (keys sorted).
**Location:** `actingweb/handlers/www.py:378`;
`examples/demo/templates/aw-actor-www-property.html` (preview, textarea,
size label); `examples/demo/application.py` (`MAX_CONTENT_LENGTH`,
`MAX_FORM_MEMORY_SIZE` = max + 64 KiB).
**Recommendation:** read with `resolve=False`, show spanned items as size
plus preview and load one item for editing; render with key order and
non-ASCII preserved; size the demo's request limits for form encoding (or
post JSON).

### V9. The www plain-text error body is HTML-escaped
**Severity:** Low (a bug in iteration 15)
**Description:** `_list_action_error` passes the message through
`html.escape` and serves it as `text/plain`, so `'` shows as `&#x27;`.
**Location:** `actingweb/handlers/www.py` `_list_action_error`.
**Recommendation:** do not escape a `text/plain` body.

### Lows
- **L1.** The 9,999-part cap can still be exceeded by a non-ASCII `str()`
  fallback item (parts fall short of the threshold on character boundaries),
  failing in `split_parts` with a plain `ValueError` instead of 413
  (`property_list_span.py` `validate_limit_pair`; `split_parts`). Compute the
  part count in `_check_item_size`.
- **L2.** `fit_full_state` treats any dict value with `list` and `operation`
  keys as a list diff, so a scalar property of that shape is stripped
  (`property_list.py` `fit_full_state`). Pass the known list names.
- **L3.** The `$aux` collision is checked on delete only: a spanning write
  for `alice` still writes into an existing actor `alice$aux`'s partition
  (`property_list.py` `_write_bodies`, `aux = self._aux()`).
- **L4.** A single-list full-state resync reads the heads twice
  (`actor.py` `_list_state_reference` then `list(list_attr)`), and sizes a
  keyed envelope by its raw head.
- **L5.** `update_by_handle` from a spanned item to a plain one: a retried
  CAS that committed returns `False` (503) and leaves the old generation;
  `_landed_anyway` covers spanned new heads only. Unverified by test.
- **L6.** `DEMO_QA_BASIC_AUTH`'s guard takes `APP_HOST_FQDN` up to the first
  `:`, and the dev server binds `0.0.0.0`: an unset `APP_HOST_FQDN` in a
  container passes the guard with OAuth off. Bind `127.0.0.1` in QA mode and
  parse the host properly (`examples/demo/application.py`).
- **L7.** Basic credentials are resent on a cross-site POST, so in QA mode
  (and any deployment without OAuth) the item forms are CSRF-able; OAuth
  sessions are covered by `SameSite=Lax`. Add an Origin check to the www POST
  handlers or note the QA-only exposure.
- **L8.** Browser walk: invalid JSON in the edit form saves the item as a
  string with no warning; a whitespace-only value passes `required`; at
  375 px the properties table scrolls inside its card; plain-text error pages
  have no viewport and no way back; the www 500 arm still echoes `str(e)`.
- **L9.** New test doubles in `tests/test_property_list_span_iterations.py`
  (and the earlier span test files) override methods without type hints,
  under `# type: ignore[no-untyped-def]`; the contract requires type hints
  on all functions.
- **L10.** The uncommitted README/`CLAUDE.md` setup order (Remaining Tasks).

## Overall Assessment

Every finding of the first verification is closed, the full tier is green on
both backends, the security review found nothing, and the web UI was
exercised in a browser for the first time, through the new local QA account:
the list page's main path (link, items, edit, large-item edit, delete, add)
works end to end.

Not ready to merge. Three of the fixes traded a visible failure for a quieter
one: the span sweep can delete pre-3.16 user items (V1), known-failed writes
now leak body generations (V3), and `delete()` leaves rows no tool can reach
(V7). A digest mismatch is a 409 its remedy cannot clear (V2), and the demo's
new item forms act by position and ignore read-only lists (V4, V5). Fix V1-V9
and the Lows in the next iteration batch, then verify again.
