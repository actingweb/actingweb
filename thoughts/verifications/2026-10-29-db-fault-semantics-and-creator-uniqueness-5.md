# Verification: DB fault contract (Phases 1-2, PR 1), fifth run

**Date:** 2026-10-29
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Branch:** release/3.16.0-db-fault-semantics
**Commit:** 85a4deb (master after PR #159; all Phase 1-2 work uncommitted)

Scope: Phases 1-2 only, after Iterations entries 30-36. Phases 3-4 are not
started, so the plan keeps `status: active` and gets no `verified:` link.

## Automated Check Results

- **Browser QA:** N/A. No phase changed a page; the fault answers are JSON,
  covered over HTTP in both integrations.
- **Second opinion:** Codex (`codex exec -s read-only`, outside the sandbox,
  finished) plus a fresh-context Claude reviewer, through outside-voice.
  Findings A5, D5, E5, F5, G5 below.
- **Code review (built-in, high, no `--fix`):** eight findings, not verified
  by the skill; each was checked against the tree here. B5, C5, H5, I5, J5
  and K5 come from it; two were already filed (notes).
- **Security review (built-in):** no findings at confidence 8 or above. It
  checked the lazy store, the startup re-raise, the constructor folds, the
  `increment_seq` SQL, the reflected-origin CORS on `/`, and the post-commit
  folds.
- `ruff check`, `ruff format --check`, `pyright`: clean (436 files).
- Fast tier: 3236 passed, 23 skipped; the guard test reports 0 violations.
- `tests/integration/verify_groups.py`: 50 groups documented.
- Full tier, DynamoDB (`make test-all-parallel`): 4232 passed, 31 skipped,
  no failures or reruns.
- Full tier, PostgreSQL (`make test-all-parallel`): 4121 passed, 142 skipped,
  no failures or reruns.
- Docs (`sphinx-build -W`): build succeeded.

## Phase Verification

### Phases 1-2 - ISSUES FOUND

**Changes verified (entries 30-36):**
- A4: `permission_initialization.py` holds the first `DbError` and raises
  it after all three steps; `trust_permissions.py` `get_trust_permission_store`
  builds the store when missing. The evaluator constructor still raises a
  registry `DbError`, which `handlers/properties.py` re-raises ahead of its
  legacy fallback. The property is pinned by
  `tests/test_db_fault_fifth_pass.py::TestA4StartupFault::test_a_deny_still_denies_after_a_startup_fault`
  (`assert allowed is False` and `auth.check_authorisation.assert_not_called()`).
- B4: the three constructors swallow a fault and cache nothing;
  `TestB4ListWrappersFold` pins `fetch(strict=False)` folding and `fetch()`
  raising per wrapper, and `register_diffs` not raising.
- D4/G4: `increment_seq` on both backends (DynamoDB `ADD` with
  `Subscription.id.exists()`; PostgreSQL `RETURNING seqnr`). PynamoDB 6.1's
  `update` returns `ALL_NEW` and refreshes `item.seqnr` (checked by the
  outside voice). `TestG4AtomicSequence::test_concurrent_diffs_get_distinct_numbers`
  passes on both backends and fails against the old increment.
- C4/F4: comments corrected; one still overstates (J5).
- H4: the section is back, recovered from the transcript.
- I4: `map_db_error(..., cors)` at all four in-route callers;
  `TestI4FactoryFaultCors` covers `POST /` in both integrations.
- J4: `approve_relationship` and the two MCP writes fold;
  `TestJ4PostCommitFolds`.

**Deviations from plan:** entry 32 replaces entry 12's rollback (recorded in
Decisions Made). `decrease_seq` is removed from the public `Subscription`
class (G5).

## Previous Verification

**Previous:** thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-4.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A4 startup fault reaches the legacy grant | Fixed | entry 30; `TestA4StartupFault` fails with the fix stripped |
| B4 `strict=False` on the list wrappers never folds | Fixed, with a new consequence | entry 31; the resume path now folds too (A5) |
| C4 "publisher redelivers" premise | Fixed (comments, docs); behaviour filed | entry 33; `thoughts/todo/subscription-subscriber-fault-hardening.md`; one comment still overstates (J5) |
| D4 skip points leave no gap | Fixed where a write is possible | entry 32; `_leave_sequence_gap`; the list-read and increment faults documented as lost |
| E4 quiet subscription stalls | Filed | subscriber hardening todo |
| F4 false marker reasons | Fixed | entry 33 |
| G4 racing increments collide | Fixed on the counter; DynamoDB diff write still unconditional | entry 32; D5 |
| H4 deleted todo section | Fixed | entry 34 |
| I4 in-route fault answers lack CORS | Fixed | entry 35 |
| J4 post-commit re-raises | Fixed | entry 36 |
| K4 smaller items | B8 wording fixed; the rest filed | entry 36; follow-ups todo "K4 leftovers" |

## Remaining Tasks

- [ ] Fix A5-K5 below (owner asked for `/iterate_plan` next).
- [ ] Sixth verification after that iteration.
- [ ] `/commit`, open PR 1, cut `release/3.16.0-creator-uniqueness` for
  Phases 3-4.

## Issues Found

### A5. A fault while resuming suspended subscriptions loses every change made during the suspension
**Severity:** High (newly reachable through entry 31)
**Description:**
- `actor.py:2635` `if not db.resume(target, subtarget):` deletes the
  suspension row first, then `:2639`
  `return self._send_resync_callbacks(target, subtarget)` reads the
  subscriptions with `strict=False` (`:2656`, "Display-grade: a fault skips
  the resync").
- While suspended, `register_diffs` returns before its loop, so no diff is
  stored and no sequence moves. The resync is the only recovery.
- Before entry 31 the strict constructor raised (503). Now the fold answers
  `[]` and `resume` returns 0, the same as "was not suspended". A
  per-subscriber `DbError` (the trust read or the sequence increment inside
  `_callback_subscription_resync`) aborts the loop, so later subscribers get
  nothing. A retry answers 0 because the marker is gone. No subscriber sees
  a gap.
**Recommendation:** read the subscriptions strictly before `db.resume()`;
send each resync with its own fault handling; if any faulted, put the
suspension back and raise, so the retry resends.

### B5. A fault changing a vouched actor's creator leaves it marked `creator_changed`
**Severity:** Medium
**Description:** `actor.py:672-675`
`if self.modify(creator=creator): return True` / `except DbError: raise`
re-raises before the restore below it (`:678-697`) runs. Both backends now
raise `DbError` from `modify`, so the `except Exception` branch ("DynamoDB
raises on a failed save; PostgreSQL answers False") is unreachable. A
throttle during `PUT /trust/trustee` on a vouched actor leaves it unvouched
with its creator unchanged, and the owner's next sign-in cleans it in place
(passphrase rotated, tokens revoked). Fail-safe, but disruptive.
**Recommendation:** on `DbError`, run the guarded restore (re-read; restore
only when the stored creator is unchanged), then re-raise.

### C5. `map_db_error` keeps a redirect and cookies the handler set before the fault
**Severity:** Medium (no concrete path found)
**Description:** `_errors.py` `map_db_error` sets status, headers and body
only. `_create_fastapi_response` returns `RedirectResponse(...,
status_code=302)` whenever `webobj.response.redirect` is set, and Flask's
builder sends a 503 with `Location` and the redirect body. Cookies queued in
`webobj.response.cookies` are still sent, so a handler that set a session
cookie and then faulted would answer the fault with a live cookie. Neither
reviewer found such a path in the factory or the OAuth callback today.
**Recommendation:** clear `response.redirect` and `response.cookies` in
`map_db_error`.

### D5. DynamoDB still overwrites a diff whose number is taken
**Severity:** Medium
**Description:** `db/dynamodb/subscription_diff.py:109` `self.handle.save()`
is unconditional, while PostgreSQL now answers False on `UniqueViolation`.
During a rolling upgrade a 3.15 worker still writes `previous + 1` as a
whole item and can move the counter back; a 3.16 `ADD` then hands out a
delivered number, the diff is overwritten, and the subscriber drops it as a
duplicate. The migration guide does not say old and new workers must not
run together.
**Recommendation:** `condition=SubscriptionDiff.subid_seqnr.does_not_exist()`,
a condition failure answers False; add the rolling-upgrade sentence.

### E5. A future 409 on `/` would be readable cross-origin with credentials
**Severity:** Low now (nothing raises `CreatorTaken`); Medium once PR 2 lands
**Description:** `_errors.py` `error_cors_headers` for `/` reflects the
origin with `Access-Control-Allow-Credentials: true`; `db_error_answer`
answers `CreatorTaken` with 409 `CONFLICT_BODY`. The factory's own
`POST /` answers carry no CORS headers, so after PR 2 a cross-origin page
could learn whether an address already has an actor.
**Recommendation:** decide in PR 2; record it on the creator-uniqueness todo.

### F5. A fault can leave a gap for a subscriber that would have got no diff
**Severity:** Low
**Description:** `actor.py` `register_diffs` reads the subscription
(`get_subscription_obj`) before the resource checks that `continue` with
"no matching blob found in diff"; `_leave_sequence_gap` then increments for
a subscriber that needed nothing, and it resyncs needlessly.
**Recommendation:** accept and say so in the comment, or run the content
checks before the read.

### G5. The public API changes have no CHANGELOG lead
**Severity:** Low
**Description:** `Subscription.decrease_seq` (present at `85a4deb`) is
removed, and custom backends must add `increment_seq`; both appear only
inside the D4/G4 FIXED entry. The project's changelog rules want a
**Breaking:** lead under CHANGED and a REMOVED line.
**Recommendation:** add both.

### H5. DynamoDB lists diffs in key order, not sequence order
**Severity:** Low (older than 3.16)
**Description:** `db/dynamodb/subscription_diff.py` `DbSubscriptionDiffList.fetch`
returns rows in range-key order (`sub:1`, `sub:10`, `sub:2`); the old
`sorted(self.diffs, ...)` discarded its result, and this branch removed
that no-op line. PostgreSQL orders by `seqnr`. Our own subscriber sorts
(`subscription_manager.py:1036`, `:1908`); other implementations reading
`GET /subscriptions/...` may not.
**Recommendation:** sort in place by `sequence`.

### I5. The replacement's "nothing written" promise is false after the tombstone
**Severity:** Low
**Description:** `oauth2.py` `_remove_for_replacement` writes the tombstone,
then fires `actor_deleted`; `_fire_lifecycle` re-raises its `DbError`. The
order is deliberate (as in `handlers/root.py`, callbacks the hook triggers
must be suppressed), and the next sign-in finishes the replacement, but the
`_fire_lifecycle` docstring and the comment above the pre-reads say nothing
is written.
**Recommendation:** correct the wording.

### J5. A callback-processor comment overstates the hook folds
**Severity:** Low
**Description:** `callback_processor.py` (both twins) says "The application
hooks inside the handler fold their own errors". The consumer data hooks
fold (`handlers/callbacks.py` markers); the legacy callback hooks re-raise a
`DbError` through `hooks.py`, aborting the drain, which the subscriber todo
already covers.
**Recommendation:** say which hooks fold.

### K5. MCP labels a 409 "Service Unavailable"
**Severity:** Low (K4, filed)
**Description:** `handlers/mcp.py` `_db_fault_response` maps 500 to
"Internal Server Error" and everything else to "Service Unavailable";
`map_db_error` already has the right table.
**Recommendation:** share the table.

### Notes
- `callback_processor.py` `clear_all_state_for_peer` reads with
  `strict=False`: already filed (follow-ups todo, "Fault-contract
  follow-ups").
- Replacement read costs and the constructor re-read after a fault: filed
  (K4) and accepted in entry 31.
- `error_cors_headers` matches `path == "/"` exactly, so an app mounted
  under a base path gets no CORS on a factory fault.
- `_increment_subscription_sequence` returns 1 when the row is gone, so a
  resync can carry `sequence: 1` (older than 3.16).

## Overall Assessment

Entries 30-36 fix what verification 4 found: the startup fault no longer
reaches the legacy grant (demonstrated, not inferred), the list folds work,
and the publisher now meets the spec's "a sequence number for each change"
with an atomic counter, tested under a real two-thread race on both
backends. Both full-tier runs are green and the security review is clean.

Making the folds real exposed one path that depended on them failing: the
resume of suspended subscriptions (A5) now loses a suspension window
silently instead of answering 503. That and B5-D5 should be fixed before PR
1 opens; E5 belongs to PR 2, and F5-K5 are small. The plan stays `active`
without a `verified:` link, since Phases 3-4 have not started.
