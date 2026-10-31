# Verification: Spanned list items (Phases 1 and 2), third run

**Date:** 2026-10-31
**Plan:** thoughts/plans/2026-10-30-spanned-list-items.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-spanned-list-items
**Commit:** 04c859f

**Scope.** Phases 1 and 2 and iteration entries 18-30 (the third batch,
`1d2b584..04c859f`), including the REST permission fallback the owner folded
in. Phase 3 is not implemented: the plan's `verified:` link is not set and the
plan stays `status: active`. No feature document. **No todos** (owner,
2026-10-31): every finding below is open work for this plan.

## Automated Check Results

- **Browser QA:** Ran during the batch, at this tree. Provider: headless
  Playwright 1.61.1 (Node, Chromium headless shell, outside the sandbox); no
  window opened. Account: the local QA mode (`DEMO_QA_BASIC_AUTH=true`,
  `localhost:5055` bound to loopback, a throwaway actor deleted afterwards).
  One full walk of the rebuilt list page and three focused re-checks; the
  findings they raised are fixed in iteration 30 and re-checked green (the
  stacked phone table: card body 259/259, every Delete button inside; text
  edit; empty-item messages; Back keeps typed text). Not walked: a deployment
  with a base path (W1, W10), a v1 list in the UI (W6), multi-line text items
  (W5).
- **Second opinion:** outside-voice agent, providers codex
  (`codex exec -s read-only`) and a fresh-context Claude reviewer: 11 + 8
  findings (codex's first adjudicated "not a finding" by the agent), folded in
  below.
- **Built-in code review** (`/code-review high 1d2b584..04c859f`, no `--fix`):
  10 findings, folded in below (one partly corrected: plain `verify()` reads
  no bodies; only `verify(spans=True)` and the sweep do).
- **Built-in security review:** no finding at or above the bar. Checked: the
  fail-closed permission branch, the back link and error page (escaping, open
  redirect), template autoescape and `?edit=` reflection, `item_rank` IDOR
  scope, the Origin check as a bypass, read-only enforcement, error-page
  leakage, envelope parsing, the QA-mode guard.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (455 files).
- `poetry run pyright actingweb tests`: pass (0 errors, 0 warnings).
- `poetry run python tests/integration/verify_groups.py`: pass (51 groups).
- `make test-all-parallel` (DynamoDB): pass, 4,621 passed, 40 skipped.
- `make test-all-parallel` (PostgreSQL): pass, 4,457 passed, 204 skipped.
- `sphinx-build -W --keep-going ...`: pass.

## Phase Verification

### Phase 1 - VERIFIED, with W1 and W11 against the demo and www

### Phase 2 - ISSUES FOUND

Iteration entries 18-30 are present as described; their regression tests
(`tests/test_property_list_span_iterations.py`, the V-named classes, and
`tests/test_list_item_limits.py` `TestWwwListPageAndActions`,
`TestRestPermissionFailsClosed`, `TestWwwBrowserWalkFollowUps`) pass, and the
V1, V2, V3 and V7 classes were shown to fail on the previous library code.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-31-spanned-list-items-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| V1 sweep deletes pre-3.16 items | Fixed; the fix over-reaches (W2) | Iteration 18; `TestV1PreReleaseItemsAreNeverSwept` |
| V2 digest mismatch unfixable | Fixed | Iteration 19; `TestV2ContentMismatchIsFoundAndSwept` |
| V3 known failures leak bodies | Fixed; a read-back gap remains (W3) | Iteration 20; `TestV3KnownFailuresDeleteTheirBodies` |
| V4 forms act by position | Fixed | Iteration 25; `test_a_stale_page_cannot_act_on_another_item` |
| V5 read-only ignored | Fixed; probe duplicated (W9) | Iterations 25-26; `test_read_only_list_refuses_writes` |
| V6 corrupted list shown empty | Fixed | Iteration 25; `test_corrupted_list_page_says_so` |
| V7 `delete()` unsweepable rows | Fixed (full sweep, quiescence documented) | Iteration 22; `TestV7DeleteSweepsEveryGeneration` |
| V8 page loads whole items | Fixed | Iteration 25; `test_list_page_reads_heads_only_and_keeps_json_order` |
| V9 double-escaped error body | Fixed | Iteration 26; `test_error_page_has_a_back_link_and_unescaped_reason` |
| L1 non-ASCII part count | Fixed | Iteration 23; `TestL1NonAsciiPartCount` |
| L2 scalar stripped by `fit_full_state` | Fixed | Iteration 24 |
| L3 `$aux` collision on write | Accepted: migration-guide audit plus the delete-side check | Iteration 13 |
| L4 single-list double read | Fixed; new error paths (W4) | Iteration 24 |
| L5 retried CAS 503 | Fixed; now also accepts a lost plain CAS (W8) | Iteration 21 |
| L6 QA guard | Fixed for `python application.py`; not under WSGI (W11) | Iteration 28 |
| L7 CSRF | Partly: list actions only, and breaks base paths (W1) | Iteration 26 |
| L8 browser walk lows | Fixed; text edit has a line-ending gap (W5) | Iterations 26, 30 |
| L9 untyped test doubles | Fixed | Iteration 29 |
| L10 setup order | Fixed | Commit `1d2b584` |
| REST fallback (folded in) | Fixed; changelog overstates it (W7) | Iteration 27 |

## Remaining Tasks

- [ ] Fix W1-W14 in the next iteration batch, each with a regression test,
      before PR 1 opens; walk the web UI again with a base-path deployment
      and a v1 list.
- [ ] Phase 3 (`append_once`) on its own branch after PR 1 opens.

## Issues Found

### W1. The www Origin check refuses every list edit on a deployment with a base path
**Severity:** High
**Description:** `config.fqdn` may carry a base path (`demo.actingweb.io/base`,
`www.py:159`), so `urlparse(origin).netloc != self.config.fqdn` is always true
there and add, update and delete answer 403. The comparison also ignores
case, default ports and scheme, and refuses `Origin: null` (sent under
`Referrer-Policy: no-referrer`). It covers the `/items` actions only: the
other www POSTs, and the GET `?_method=DELETE` link that deletes a list, stay
open to cross-site requests (pre-existing; `SameSite=Lax` does not cover a
top-level GET).
**Location:** `actingweb/handlers/www.py:1041`.
**Recommendation:** compare with `urlparse(self.config.root)` (scheme, host
lowercased, default port normalised); decide `Origin: null`; apply one check
to every www mutation (making deletion a POST), or record the remaining
exposure in `security.rst`.

### W2. A damaged library envelope reads as a plain item and its bodies get swept
**Severity:** High
**Description:** iteration 18 makes anything without the exact marker a plain
item, including a library envelope truncated into invalid JSON and an
envelope from a later version (`"__aw_env": 2`). Such a head is served as its
raw text or as a dict, `verify()` does not report it, and since no parsed
head names its body generation, the aged sweep deletes the bodies a repair
could have recovered.
**Location:** `actingweb/property_list_span.py:216` (`and marker == 1`), `:236`
(`if not carries_library_marker(raw): return None`).
**Recommendation:** keep `EnvelopeError` for a value with the prefix whose JSON
is invalid or whose marker is an int other than 1; only a valid object with a
non-int marker value (a pre-3.16 user item) is plain.

### W3. A read-back that faults after a `False` deletes bodies of a head that may have landed
**Severity:** Medium
**Description:** `_probed_write` and `_v2_extend` clear the in-flight mark when
the create returns, before `_landed_anyway` reads the row; if that read raises
(the same throttling that made the SDK retry), the failure is treated as
known not landed and the bodies are deleted.
**Location:** `actingweb/property_list.py:2504`, `:3126`, `:2619-2620`.
**Recommendation:** treat a raise from the read-back as an unknown outcome
(keep the mark set until it returns).

### W4. A single-list full-state resync can raise on a malformed head or a concurrent delete
**Severity:** Medium
**Description:** `_list_state_reference` sizes items with
`encoded_size(json.dumps(item))`, which raises `TypeError` for the
`UNRESOLVED` a malformed head yields; the resolve loop's `item_at()` raises
`IndexError` when an item is deleted between the head read and the resolve.
Only `ValueError`/`ListCorruptionError` are caught, so the callback aborts.
**Location:** `actingweb/actor.py:3443`, `:3327`.
**Recommendation:** size `UNRESOLVED` from the raw head, and drop an item gone
by the time it is resolved (as `_resolve_pairs` does).

### W5. Saving a multi-line text item unchanged alters it
**Severity:** Medium
**Description:** the text edit form round-trips the string through a
`<textarea>`; browsers submit line breaks as CRLF and HTML drops a leading
newline, and the handler stores `item_value` verbatim.
**Location:** `examples/demo/templates/aw-actor-www-property.html:62-63`;
`actingweb/handlers/www.py:1129`.
**Recommendation:** normalise `\r\n` to `\n` for `item_format=text`, and emit a
newline after `<textarea>` so a leading newline survives.

### W6. v1 list items can no longer be edited in the demo
**Severity:** Medium
**Description:** the Edit link needs a rank; v1 entries have none, and the old
inline form was removed. Lazy migration is off by default, so existing lists
stay v1.
**Location:** `examples/demo/templates/aw-actor-www-property.html` (`{% if
entry.rank %}`); `actingweb/handlers/www.py` `_list_page_items`.
**Recommendation:** support `?edit=<index>` (positional, as v1 is) for v1
entries.

### W7. The changelog and web UI docs misdescribe two changes
**Severity:** Medium
**Description:** a custom template that renders `list_items` with `tojson`
raises `TypeError` on a spanned item (the changelog says it shows
`UNRESOLVED`), and `docs/guides/web-ui.rst:217` documents only `list_items`.
The REST fail-closed change only fires when building the evaluator, or the
legacy check, raises (`permission_evaluator.py:138-140` and `:260-265`
already deny on their own errors); "sees 403s where it saw 200s" overstates
it.
**Location:** `CHANGELOG.rst` (the web UI and REST entries);
`docs/guides/web-ui.rst:217`; `docs/reference/security.rst`.
**Recommendation:** correct both entries and document `list_entries`,
`edit_entry` and `list_error`.

### W8. A lost plain CAS can report success
**Severity:** Low
**Description:** iteration 21's read-back accepts any head equal to the new
value, so `update_by_handle` answers `True` (and cascades and touches) when
another writer stored the same plain value; this contradicts the documented
"a failed condition is the answer" and `_landed_anyway`'s own rule.
**Location:** `actingweb/property_list.py:1016` (`_row_holds`).
**Recommendation:** read back only spanned heads (whose bytes are unique), and
document the plain case as the remaining SDK-retry ambiguity.

### W9. The read-only probe is duplicated and unguarded
**Severity:** Low
**Description:** `_list_is_read_only` repeats the GET page's put-hook probe with
a different value (`{}` vs `lookup or {}`), runs outside the action's
`try`, and fires the application's put hook on every action.
**Location:** `actingweb/handlers/www.py:116`.
**Recommendation:** one helper for both, inside the error handling.

### W10. The error page's links ignore the base path and rely on inline script
**Severity:** Low
**Location:** `actingweb/handlers/www.py:1032` (`self._list_back = f"/{actor_id}/www/..."`),
the `onclick` in `_list_action_error`.
**Recommendation:** build the link from `_get_consistent_urls(actor_id)["actor_www"]`;
the `href` already falls back when a CSP blocks the inline handler.

### W11. The QA mode can be switched on under WSGI
**Severity:** Low (env-gated)
**Description:** the loopback bind is inside `if __name__ == "__main__"`, and
`APP_HOST_FQDN` defaults to `localhost:5000`, so a WSGI deployment with
`DEMO_QA_BASIC_AUTH=true` and no `APP_HOST_FQDN` passes the guard with OAuth
off.
**Location:** `examples/demo/application.py:103`, `:319`.
**Recommendation:** in QA mode require `APP_HOST_FQDN` explicitly and refuse to
start unless run as `__main__`.

### W12. The sweep reads every body twice
**Severity:** Low
**Description:** `--repair --sweep-spans` runs `verify(spans=True)` (a content
read) and then the sweep (another), and compact copies moved items again. A
plain `verify()` reads no bodies (the code review's claim otherwise does not
hold). Also unverified: whether `get_prefix` pages past 1 MB, which the
content check now depends on for a large generation.
**Location:** `actingweb/maintenance/verify_property_lists.py`;
`actingweb/property_list.py` `_sweep_spans`.
**Recommendation:** let the sweep reuse the verify pass's inventory, and pin
paging with a test.

### W13. Envelope heads are JSON-decoded twice per parse
**Severity:** Low
**Location:** `actingweb/property_list_span.py:206` (`carries_library_marker`
then `parse`).
**Recommendation:** decode once.

### W14. `ListProperty` keeps the in-flight mark on the instance
**Severity:** Low
**Description:** an instance shared across threads could see another call's
mark; no library path nests writes and the mark is reset on entry. Whether any
application shares an instance across threads is unverified.
**Location:** `actingweb/property_list.py` `_head_write_in_flight`.
**Recommendation:** pass a per-call probe object instead of an attribute.

## Overall Assessment

The second verification's findings are closed or narrowed, both full suites
are green, the security review is clean, and the rebuilt web UI passed its
browser walks on a localhost deployment.

Not ready to merge. W1 breaks every list edit on a base-path deployment (the
shape `demo.actingweb.io`'s configuration allows), and W2 trades V1's data
loss for a quieter one: a damaged envelope's bodies are swept. W3-W7 are
real but narrow. Fix W1-W7 (and the Lows) in the next iteration batch, walk
the UI with a base path and a v1 list, then verify again.
