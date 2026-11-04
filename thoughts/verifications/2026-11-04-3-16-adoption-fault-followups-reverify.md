# Verification: 3.16 adoption, deletion and fault-contract follow-ups (seventh run)

**Date:** 2026-11-04
**Plan:** thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md
**Research:** the todos named in the plan's **Research:** line (deleted; no research document)
**Branch:** `release/3.16.0-adoption-fault-followups`
**Commit:** `04332d0` plus the uncommitted working tree (Iterations entries 16–48)

This run checks entry 48 against the sixth run's Y1–Y4. There is no feature
document and no consumer message.

## Automated Check Results

- **ruff check:** pass
- **ruff format --check:** pass
- **pyright:** pass (0 errors, 0 warnings)
- **verify_groups.py:** pass (53 groups)
- **DynamoDB, `make test-all-parallel`:** pass, 5,551 passed, 59 skipped, 1 xfailed, 9 subtests passed
- **PostgreSQL, `make test-all-parallel`:** pass, 5,361 passed, 249 skipped, 1 xfailed, 9 subtests passed
- **sphinx-build -W:** pass
- **Audit scope (sized to the delta):** the delta is two guard lines in `_announce_pending`, one check moved ahead of the pre-reads in `finish_deletion`, one docs sentence, and three tests. I read the changed lines myself. The outside voice, code review, security review and browser walk were not rerun: no auth path, storage write or page changed, and the sixth run's targeted read already covered this code.

## Security properties the plan claims

- **No login CSRF through `POST /oauth/email`:**
  - `tests/test_oauth_email_handler.py:492` `TestCrossSiteSubmissionSignsNobodyIn`:
    - a foreign `Origin` and `Sec-Fetch-Site: same-site` each answer 403 with `try_claim_session` never called and no `oauth_token` cookie;
    - a cross-site JSON request gets its token in the body and no cookie;
    - a same-origin form keeps its cookie.
  - `tests/test_email_sign_in_code.py:521` `test_an_offer_another_site_started_is_refused_before_mailing[cross-site|same-site]` goes through the unpatched route: 403, nothing mailed, no binding cookie, window count unchanged.
- **The code binding holds:**
  - `:253` `test_a_json_challenge_cannot_be_redeemed_by_a_browser`;
  - `:425` `test_another_browser_gets_401_and_the_code_page_again` (401, no `oauth_token`).
- **The hourly cap cannot be driven past by a failing hook:** `:567` `test_the_challenge_is_withdrawn_and_the_slot_kept` (five 503s, then 429).
- **R3 on the SDK path:** `tests/test_session_generation.py:160` `TestClientManagerToken`. A refresh token from before the clean mints nothing.
- **One refresh-cookie path:** `tests/test_refresh_cookie_path.py:33`. One live cookie on `/` and the legacy path expired.
- **Todos:** nothing under `thoughts/todo/` changed since the third run, no todo the plan closes remains, and `INDEX.md` is unchanged.

## Phase Verification

### Iterations entry 48 - VERIFIED

**Changes verified:**
- **Y1:** `actingweb/oauth2.py:2646` `if hooks is None:` returns before the record is read, so nothing is claimed without a listener.
- **Y2:** `actingweb/oauth2.py:2694` `if not old_id or old_id in skip or old_id == actor.id:`.
- **Y3:** `docs/reference/hooks-reference.rst`: the deletion table's "once, by the request that finishes" now states the crash window.
- **Y4:** `actingweb/deletion_finish.py:112-124`. The finished-and-row-gone check sits inside the `try` ahead of `_pre_read`, so a fault in the strict row read still releases the lease (`except BaseException`).

**Tests verified** (each confirmed to fail without its fix):
- `tests/test_adoption_summary_and_handoff.py`:
  - `test_without_hooks_the_record_is_left_for_a_sign_in_that_has_them`: the record stays unannounced with no hooks, and is announced once hooks exist.
  - `test_an_actor_is_never_announced_as_having_replaced_itself`.
- `tests/test_deletion_finish.py`:
  - `test_a_finished_deletion_reads_nothing_else_first`: a faulting `_pre_read` and a finished deletion answer 0, not `DbError`.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-04-3-16-adoption-fault-followups.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| Y1 claim with no hooks | Fixed | entry 48; `oauth2.py:2646` |
| Y2 "replaced itself" | Fixed | entry 48; `oauth2.py:2694` |
| Y3 completion crash window undocumented | Fixed | entry 48; hooks reference |
| Y4 503 for a finished deletion | Fixed | entry 48; `deletion_finish.py:112` |

## The loop, for the record

| Run | Document | Findings | Fixed in entries |
| --- | --- | --- | --- |
| 3 | `…-reverify-2.md` | V1–V10 | 29–38 |
| 4 | `…-reverify-3.md` | W1–W10 | 39–44 |
| 5 | `…-reverify-4.md` | X1–X7 | 45–47 |
| 6 | `2026-11-04-…md` | Y1–Y4 (low) | 48 |
| 7 | this document | none | — |

Each run's audit was sized to its delta, as the owner asked. The pending
`actor_adopted` announcement is closed at a documented contract, the same
one `actor_deleted` carries (entry 46), not exactly once.

## Remaining Tasks

None for this plan. Committing is the owner's call. The one-PR-per-plan
rule applies, and the Full tier above is current for the working tree.

## Issues Found

None.

## Overall Assessment

The plan's follow-ups and every finding of the six earlier runs are fixed,
refuted, or accepted with a recorded reason, each fix with a regression test
confirmed to fail without it. The Full tier is green on both backends, and
the pages users see were walked in a browser in runs 3–5 with no open
finding. Two points worth the owner's attention:
- The pending-adoption announcement now costs one keyed read per lookup that
  resolves a vouched actor.
- `POST /oauth/email` now refuses cross-site browser forms (a SECURITY
  entry with a **Behavior change:**).

The plan stays `status: done`, and `verified:` points here.
