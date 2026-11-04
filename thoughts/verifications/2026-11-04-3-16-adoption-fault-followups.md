# Verification: 3.16 adoption, deletion and fault-contract follow-ups (sixth run)

**Date:** 2026-11-04
**Plan:** thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md
**Research:** the todos named in the plan's **Research:** line (deleted; no research document)
**Branch:** `release/3.16.0-adoption-fault-followups`
**Commit:** `04332d0` plus the uncommitted working tree (Iterations entries 16–47)

This run checks entries 45–47 against the fifth run's X1–X7.

## Automated Check Results

- **ruff check / ruff format --check / pyright:** pass
- **verify_groups.py:** pass (53 groups)
- **DynamoDB, `make test-all-parallel`:** pass, 5,548 passed, 59 skipped, 1 xfailed
- **PostgreSQL, `make test-all-parallel`:** pass, 5,358 passed, 249 skipped, 1 xfailed
- **sphinx-build -W:** pass
- **Audit scope (sized to the delta):**
  - One outside-voice read of entries 45–47 ran: codex (unsandboxed, re-run with stdin closed after its first run hung), then a fresh-context Claude. Its brief was the documented delivery contract.
  - The code review, the security review and the browser walk were skipped. The delta has no new auth path, and its only change a user sees is the callback's redirect target, which a unit test covers.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-03-3-16-adoption-fault-followups-reverify-4.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| X1 a late finisher re-records a finished deletion | Fixed | entry 45; `tests/test_deletion_finish.py` `test_a_late_finisher_after_the_finish_changes_nothing` |
| X2 unconditional first write | Fixed | entry 46; `test_a_first_write_that_loses_to_another_fails_closed` |
| X3 the announcer deletes a newer record | Fixed (delete dropped) | entry 46 |
| X4 the vouched branch never announces | Fixed | entry 46; `test_a_vouched_sign_in_announces_what_a_failed_replacement_left` |
| X5 delivery edges | Documented as the contract | entry 46; `CHANGELOG.rst`, `docs/reference/hooks-reference.rst` |
| X6 callback redirect and link ignore the base path | Redirect fixed; link refuted (`fqdn` carries the path) | entry 47 |
| X7 `post()` comment | Fixed | entry 47 |

## Issues Found

### Y1. With no hooks registered, `_announce_pending` claims the record and fires nothing
**Severity:** Low
**Description:** The claim at `actingweb/oauth2.py:2662` (`if not db.conditional_update_attr(`) runs whatever `hooks` is, and `_fire_lifecycle` returns at `:2036` (`if hooks is None:`). A provider-token request to a vouched actor (`:1313`, falling back to `config._hooks`, which is `None` on a bare `Config`) now reaches the vouched-branch call and marks the record announced, so the event is lost outside the documented crash window.
**Recommendation:** Return before reading the record when `hooks is None`.

### Y2. A record that names the announcing actor announces it as having replaced itself
**Severity:** Low
**Description:** `actingweb/oauth2.py:2688` (`if not old_id or old_id in skip:`): the vouched branch passes `skip=set()`. If a replacement recorded V and then failed before removing it, and V is later cleaned in place or vouched, V is announced with `previous_actor_id == V`.
**Recommendation:** Also skip `old_id == actor.id`.

### Y3. The deletion hooks table does not state the completion's crash window
**Severity:** Low (older than entry 41)
**Description:** `docs/reference/hooks-reference.rst:270` says `- once, by the request that finishes`. A crash between `mark_finished` and `actor_deleted_complete` loses the event, and a retry now returns 0 (entry 45).
**Recommendation:** State the window, as the pending-adoption contract does.

### Y4. An already finished deletion can still answer 503
**Severity:** Low
**Description:** `actingweb/deletion_finish.py:113` (`pre_reads = _pre_read(actor_id, config)`) runs before the finished-and-row-gone check, so a transient fault reading trusts gives a retry 503 for an actor that is gone.
**Recommendation:** Move the check ahead of `_pre_read`.

## Remaining Tasks

These are fixed inside this plan through `/iterate_plan`:

- [ ] Y1–Y4

## Overall Assessment

X1–X7 are fixed, refuted or documented as the contract, and both backends
are green. The four remaining items are low-severity one-line fixes and a
docs sentence, all inside entries 45–46's own code. No new class of problem
appeared: the outside voice confirmed the lease handling, the TTL retention
and the redirect. `verified:` moves to this document.
