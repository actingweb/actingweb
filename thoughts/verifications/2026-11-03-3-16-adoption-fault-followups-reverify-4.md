# Verification: 3.16 adoption, deletion and fault-contract follow-ups (fifth run)

**Date:** 2026-11-03
**Plan:** thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md
**Research:** the todos named in the plan's **Research:** line (deleted; no research document)
**Branch:** `release/3.16.0-adoption-fault-followups`
**Commit:** `04332d0` plus the uncommitted working tree (Iterations entries 16–44)

This run checks entries 39–44 against the fourth run's W1–W10. There is no
feature document and no consumer message.

## Automated Check Results

- **ruff check / ruff format --check / pyright:** pass after the formatting and typing fix in two test files, which was found by the first Full tier run of this round.
- **verify_groups.py:** pass (53 groups)
- **DynamoDB, `make test-all-parallel`:** pass, 5,544 passed, 59 skipped, 1 xfailed
- **PostgreSQL, `make test-all-parallel`:** pass, 5,354 passed, 249 skipped, 1 xfailed
- **sphinx-build -W:** pass
- **Audit scope (sized to the delta, per the owner):**
  - The outside voice ran on entries 39–41 only: auth, storage and deletion.
  - The built-in code review and security review did not rerun. Entry 39 is the guard both had already traced, and entries 42–44 are fallbacks, docs and hygiene.
- **Browser QA:** gstack headless Chromium on `localhost:5055`, short walk, no findings.
  - The code page posts to `http://localhost:5055/oauth/email`, and a resubmit stays on the origin with a 401.
  - Start over sits 14 px below the button.
  - `GET /oauth/email` answers 400 with Continue.
  - A real `file://` page auto-posting the form gets 403 "Cross-site request refused".
  - Both pages work at 375 px.
- **Second opinion (outside voice):** codex (`codex exec -s read-only`, unsandboxed, completed), then a fresh-context Claude. 13 findings; folded in below.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-03-3-16-adoption-fault-followups-reverify-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| W1 login CSRF through the email form | Fixed | entry 39; `tests/test_oauth_email_handler.py` `TestCrossSiteSubmissionSignsNobodyIn`; browser walk |
| W2 earlier pending adoption only in memory | Partly fixed; new edges (X2–X5) | entry 40 |
| W3 finished tombstone over a live row | Fixed, but regressed the DELETE-retry race (X1) | entry 41 |
| W4 fallback drops Continue | Fixed | entry 42 |
| W5 forms post outside a base path | Fixed for the forms; the callback and the link that lead there are not (X6) | entry 43 |
| W6 a hook's `DbError` after sending | Documented and logged | entry 44 |
| W7 legacy path literals | Fixed | entry 44 |
| W8 changelog wording and replaced-branch test | Fixed | entry 40 |
| W9 stale comment | Rewritten, still overstated for JSON (X7) | entry 39 |
| W10 binding length | Fixed | entry 44 |

## Issues Found

### X1. Entry 41 restarts a deletion that just finished, firing its completion twice
**Severity:** Medium (a regression from entry 41)
**Description:** `actingweb/deletion_finish.py:134` reads `if not deletion.is_resumable(data) or data.get("finished_at"):`. A second finisher that loaded the actor before the first removed its row (a DELETE retry, a sibling swept by two sign-ins, a sign-in racing a DELETE) claims the lease the first one released.
- It resets the finished tombstone, writing `"finished_at": None` (`:154`) and its own `reason` and `hook_kwargs`.
- `Actor.delete` answers True on the missing row.
- `mark_finished` then announces `actor_deleted_complete` a second time.

Before entry 41, the finished tombstone made `mark_finished` refuse.
**Recommendation:** In that branch, read the actor row strictly. If the row is gone, the deletion is done: change nothing, fire nothing, return 0. Keep the reset for a live row (W3).

### X2. A first pending-adoption write is unconditional
**Severity:** Medium
**Description:** `actingweb/oauth2.py:2616` calls `db.set_attr(` when no row was read. Two concurrent replacements both write, and the later one drops the earlier victim. The docstring claims a conditional write.
**Recommendation:** `create_attr_if_absent`; on a conflict raise `DbError` (nothing has been removed yet).

### X3. The announcer's delete can remove a newer record
**Severity:** Medium
**Description:** `actingweb/oauth2.py:2662` calls `db.delete_attr(` after the claim. A writer that read the announced row (and so carries nothing earlier) and rewrote it is then deleted by the announcer.
**Recommendation:** Drop the delete. `_record_pending_adoption` already replaces an announced row, and the TTL reaps it.

### X4. Failures after a successor's create commits land on the vouched branch, which never announces
**Severity:** Medium
**Description:** `actingweb/oauth2.py:2743` `if is_vouched_actor(existing):` returns at `:2789` without reading the record. The enforced path's store writes after the create (`:1938-1951`), the plain create's adopted-from writes (`:2991-2994`) and a raced hand-off all leave a vouched successor and an unannounced record, which then expires after seven days.
**Recommendation:** One best-effort `_announce_pending(..., skip=set())` on the vouched branch.

### X5. Delivery edges of the pending announcement
**Severity:** Low
**Description:**
- Concurrent sign-ins for one creator can both announce the same victim, the create path (`:1238`) beside a replacement's own event (`:3169`).
- The claim happens before the hooks fire, so a crash between them loses the event.
- A claim that faults is silent (`:2654-2661`).
- Swept siblings are not carried in the record (`:2899`).
**Recommendation:** Log a claim fault, and document the contract as the library's other lifecycle events do: announced once in the common case, possibly twice under concurrent sign-ins (handlers are idempotent), lost on a crash between the claim and the hook. Do not add an in-progress marker.

### X6. The callback redirect and the verification link ignore the base path
**Severity:** Low (older than this branch)
**Description:**
- `actingweb/handlers/oauth2_callback.py:458`: `email_form_url = f"/oauth/email?session={session_id}"`.
- `actingweb/handlers/oauth_email.py:1054-1056` builds the link from `proto` and `fqdn`, followed by `/oauth/email?verify=`.
- Under a base path neither reaches the forms entry 43 fixed.
**Recommendation:** Build both from `config.root`. Leave the JSON `form_action`.

### X7. The `post()` comment overstates what a cross-site request is spared
**Severity:** Low
**Description:** `actingweb/handlers/oauth_email.py:752-753` reads "nothing is claimed, created or mailed for it", but that holds for browser forms only. A cross-site `format=json` request still runs, though it gets no cookie.
**Recommendation:** Reword.

### Notes
- **Sibling-subdomain browser posts:** an application that posts the form from a sibling subdomain as a browser form now gets 403. The SPA guide sends JSON, and the changelog's **Behavior change:** covers it.
- **Unchanged before this branch:** a vouched live actor under a finished tombstone is still wiped at sign-in (`_finish_stalled_vouched`).

## Remaining Tasks

These are fixed inside this plan through `/iterate_plan`:

- [ ] X1–X7

## Overall Assessment

W1, W4, W5 (forms), W6, W7, W8 and W10 hold, and the browser walk is clean.
Entry 41 regressed a race (X1), which must be fixed. The pending-adoption
record has turned up a new race on every round. It is to be closed with
three small fixes (X2–X4) and a documented at-least-once contract (X5),
matching `actor_deleted`, rather than more machinery. X6 and X7 are small.
`verified:` moves to this document.
