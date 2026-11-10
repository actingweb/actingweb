# Verification: a peer's grant is the answer on every route (re-run 1)

**Security, unpublished.** Keep local under the same rule as the plan: never
push before the fix.

**Date:** 2026-11-10
**Plan:** thoughts/plans/2026-11-10-grant-enforcement-per-route.md
**Research:** thoughts/research/2026-11-10-grant-enforcement-per-route.md
**Branch:** fix/3.16.0-grant-enforcement (local only)
**Commit:** 0cef4d6 (iterations 23-27 on top of `10f9563`, iterations 1-22)

Second verification. Scope: the iteration commits `78b5953..0cef4d6`,
checked against the previous verification's Issues Found, with reviews
scaled to the delta (`10f9563..0cef4d6`, 33 files, +636/-161). The phases
themselves were verified in the previous document and are not re-walked.

## Automated Check Results

The Full tier ran on the tree of `0cef4d6` before its commit (the commit
adds only `WG15.json` and plan entry 27 over that tree; `WG15` re-run on
both backends after re-recording).

- **ruff check / ruff format --check / pyright**: pass, 0 errors, 0
  warnings.
- **verify_groups.py**: pass ("All 57 groups documented", "Wire rows
  registry consistent").
- **Unit**: 5042 passed, 43 skipped, 1 xfailed.
- **DynamoDB, `make test-all-parallel`**: 6493 passed, 60 skipped, 1
  xfailed; `WG15` failed before its re-recording (the confirmation page
  grew by entry 25's `error` block and gutter, 2419 → 2442 characters;
  nothing else in the recording differed). Passes after.
- **PostgreSQL, `make test-all-parallel`**: 6290 passed, 263 skipped, 1
  xfailed; `WG15` as above.
- **PostgreSQL, sequential**: 1385 passed; fails `WG15` (as above) and
  `test_callback_processor_concurrency` (fails on `master` too; todo
  `callback-concurrency-test-sequential-postgresql.md`).
- **Docs** (`sphinx-build -W ...`): pass.
- **Emm's suite** on `0cef4d6` (library worktree
  `.claude/worktrees/master-5a7e07f` at `0cef4d6`; Emm's `emm-3-16`
  unchanged; environment 9): PostgreSQL 2 failed / 7406 passed / 14
  skipped / 179 deselected; DynamoDB lane 3 failed / 54 passed. The same
  five baseline failures by name as at `78b5953` and on `master`. No new
  failure.
- **Browser QA:** not re-run. The only page changed since the walk of
  `10f9563` is the confirmation refusal (entry 25); its HTML/JSON split is
  covered over HTTP by
  `test_a_refusal_is_a_page_for_a_browser_and_json_for_a_client`, and the
  walk that found F-003/F-004 was on the same template.
- **Second opinion:** outside-voice agent, providers codex
  (`codex exec -s read-only`, unsandboxed) and a fresh-context Claude
  reviewer. Findings folded below.
- **Code review** (built-in, high, `10f9563..0cef4d6`): 10 findings, folded
  below.
- **Security review** (built-in brief, scoped to the delta): no
  high-confidence vulnerabilities; two notes (nested-JSON filter, async
  hook order) folded below.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-10-grant-enforcement-per-route.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Developer views leak and overwrite excluded parts | Fixed | Iterations 1, 24 (`as_json_object`, `authenticated_views.py`) |
| 2. JSON-text diff skips the exclusion filter | Fixed, with a new gap | Iterations 2, 23; nested *objects* still raise in the filter's walk (Issue C below) |
| 3. Other targets never re-checked at delivery | Partly open | Iterations 3, 23; application targets now pass on approval alone (Issue F) |
| 4. Bare collection route skips a stated rule | Fixed | Iterations 4, 23 (bare JSON-RPC decided by its body's method) |
| 5. Spoofable host on the confirmation page | Fixed | Iteration 5 (`_shown_host`, userinfo refused) |
| 6. A code issued with no trust row | Fixed, with a new failure path | Iterations 6, 23; a `DbError` from the override drop leaves a stuck re-type (Issue A) |
| 7. `trust_deleted` for a row that survives | Fixed on REST and sync; open on async `sync_peer` | Iterations 7, 11, 23 (Issue B) |
| 8. PUT restore from a cached snapshot | Fixed | Iteration 8 |
| 9. Custom `DbTrust` backends: Breaking lead | Fixed | Iteration 9, CHANGELOG |
| 10. Smaller Phase 3 defects | Fixed or accepted | Iterations 10-20, 26 |
| 11. Smaller Phase 4 and Phase 1-2 defects | Fixed or accepted | Iterations 10-20, 26; the absent-row cleanup reopened a window (Issue D) |

## Remaining Tasks

- [ ] Issues A-K below (a third iteration batch).
- [ ] Decision on Issue F (what decides an application target at delivery).

## Issues Found

### A. A failed re-type leaves the old, wider override, and a retry cannot repair it
**Severity:** High
**Description:** The type changes first; `_drop_client_override` then
removes the old override. A `DbError` from `delete_permissions` escapes
past the rollback (`except DbError: raise`), so the row reads the new type
while the old override (whose own `trust_type` decides in the evaluator)
stays. On retry `old_type == trust_type`, `retyped` is False, and the
override is never dropped: the client keeps the old access with no error.
The rollback `db.modify(relationship=old_type)` result is also ignored.
`test_a_failed_type_change_keeps_the_override` covers only a failing
`modify`.
**Location:** `actingweb/interface/trust_manager.py:661-678`
(`old_type != trust_type`, `db.modify(relationship=old_type)`).
**Recommendation:** decide "re-typed" from the row type *or* a stored
override whose `trust_type` differs from the approved one; roll back on
`DbError` too, then re-raise; test the drop raising and the retry.

### B. Async `sync_peer` fires `trust_deleted` before, and apart from, the delete
**Severity:** Medium
**Description:** `sync_peer_async` reads the row, awaits
`fire_deleted_async`, then calls `delete_reciprocal_trust_async` with no
`before_local_delete` and no `expected_secret`. A failed delete fires the
hook again on every later sync; a concurrent REST delete fires it twice; a
re-pair in between is reported as the old row and then deleted. Sync hooks
also now run on the event loop (they ran in a worker thread). The
changelog states the "only for a row still there" guarantee for both
twins.
**Location:** `actingweb/interface/subscription_manager.py:2711-2731`;
`actingweb/interface/hooks.py:1384`.
**Recommendation:** keep the callback in the delete (re-read, fire only
when present), bridging to the loop for coroutine hooks and running sync
hooks off-loop; test ordering and "no row, no hook".

### C. Deeply nested objects still raise in the exclusion filter
**Severity:** Medium
**Description:** `as_json_object` catches `RecursionError` from the
parser, but `_drop` recurses over objects; an object nested ~5000 deep
(≈30 KB) parses and then raises in `drop_excluded`. On push the error
escapes the per-subscriber loop (it catches `DbError` only): later
subscribers get no diff and the writer gets 500 after the commit. The test
uses nested arrays, which `_drop` does not walk. Separately, a value the
parser cannot read is now treated as text and delivered unfiltered
(security review note).
**Location:** `actingweb/permission_evaluator.py:236`
(`kept[key] = _drop(patterns, child_path, child)`), `:249`.
**Recommendation:** make `_drop`/`_prune_emptied` iterative or
depth-bounded with a fail-closed result (withhold the value, not deliver it
raw); test nested objects.

### D. The absent-row cleanup can remove a re-paired row's override
**Severity:** Low
**Description:** A retried `DELETE /trust` that finds no row calls
`_after_row_delete(True, peerid)`, which deletes permissions
unconditionally. A re-pair between the read and that delete loses its new
override (falls back to type defaults, possibly wider), and the call
reports True.
**Location:** `actingweb/trust.py:182`.
**Recommendation:** re-check absence right before `delete_permissions`, or
record the window in `thoughts/reference/trust-row-deletion-invariants.md`.

### E. A refused bulk `items` update answers 500 with no diff when the hook raises
**Severity:** Medium
**Description:** Entry 23 records the key when the hook returns None, but
the canonical refusal raises `_HookDenied`, which the generic
`except Exception` turns into 500 without setting `pair[key]`. The test
patches `_run_hooks` to return None.
**Location:** `actingweb/handlers/properties.py:436`, `:1956`.
**Recommendation:** catch `_HookDenied` before the generic handler, record
the key, answer 403; test with a hook that denies.

### F. Application targets pass delivery on approval alone (decision needed)
**Severity:** Medium
**Description:** `_may_still_subscribe` returns `snapshot.approved` for any
target outside `SUBSCRIBABLE`, dropping `subscription_allowed`'s client
refusal and access-table row. A relationship downgrade no longer stops an
existing application-target subscription, and an OAuth2 client holding one
the application made can pull its diffs. Entry 23 relaxed this because the
creation check refused subscriptions the application created itself.
**Location:** `actingweb/actor.py:4164-4165`.
**Recommendation:** see the question to the owner (keep approval only;
add the client refusal; or re-check the access-table row except for
application-made subscriptions).

### G. Expired or spent confirmations still show raw JSON to a browser
**Severity:** Low
**Description:** Only the four refusals inside `_handle_confirmation` render
the page; an error from `handle_confirmation` goes through
`answer_callback` → `error_response` as JSON. The JSON/page test also
differs from `answer_callback`'s. An application's own
`aw-oauth-confirm.html` without an `error` branch renders an empty
Approve form on refusal; the 503 text says "Go back", which replays a
spent provider code (reload is the retry); a template render failure
answers 200.
**Location:** `actingweb/handlers/oauth2_endpoints.py:648`, `:688`, `:748`;
`fastapi_integration.py` ~`:2297`, `flask_integration.py` ~`:1459`.
**Recommendation:** route every confirmation error through
`_confirm_refusal`; document `error` in the template contract (migration
guide); "reload this page"; keep the status on the render fallback.

### H. A secret rotated with the approval sends the notice to the old URL
**Severity:** Low
**Description:** The replaced-row check compares the re-read secret with
the pre-write one, so `modify_trust_and_notify(approved=True, secret=new)`
discards its own write's base URI.
**Location:** `actingweb/actor.py:2090`.
**Recommendation:** compare with the secret this call wrote when it wrote
one.

### I. A refused bare JSON-RPC call answers HTTP 200
**Severity:** Low
**Description:** The JSON-RPC refusal is a 200 with error `-32000`, and an
unauthenticated call gets no challenge, where the named path answers 403.
Not a bypass.
**Location:** `actingweb/handlers/methods.py:182`, `:309` (and the async
twin).
**Recommendation:** set 403 (and the auth response for a 401) when the
body's method is refused.

### J. Duplication
**Severity:** Low
**Description:** `fire_deleted_async` re-implements `fire_deleted` and
`_execute_lifecycle_hook` (argument contract and error policy); the
parse-then-gate block is copied between `methods.py` and
`async_methods.py`.
**Location:** `actingweb/interface/trust_manager.py:634`;
`actingweb/handlers/methods.py:158-191`.
**Recommendation:** one argument builder for the hook; one shared gate
helper.

### K. Hygiene
**Severity:** Low
**Description:** `def test_an_approved_peer_gets_its_application_diffs(self,
actor) -> None:` has no type hint on `actor` (project rule).
**Location:** `tests/test_grant_stored_text.py:252`.
**Recommendation:** annotate.

### Noted, not filed
- The window between `delete_reciprocal_trust`'s re-read and the row
  delete (`actor.py:3168`) is the remaining window already recorded in
  `trust-row-deletion-invariants.md`.
- The re-type's brief window with the new type and the old override is
  closed by A's fix order and rollback.

## Overall Assessment

The second batch closed every issue of the first verification on its
tested path, all checks are green, and Emm's suite is unchanged against
its baseline. It is not clean: the review of the fixes' own failure paths
found one High (A, a downgrade that can stick at the wider level with no
error) and four Medium issues (B, C, E, F), three of which are the same
pattern, a fix whose test builds only the input it was written for. F needs
the owner's decision before the third batch. Not ready to merge until A-E
and the F decision land, with tests that drive the failing path itself.
