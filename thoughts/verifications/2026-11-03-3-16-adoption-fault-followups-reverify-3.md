# Verification: 3.16 adoption, deletion and fault-contract follow-ups (fourth run)

**Date:** 2026-11-03
**Plan:** thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md
**Research:** the todos named in the plan's **Research:** line (deleted; no research document)
**Branch:** `release/3.16.0-adoption-fault-followups`
**Commit:** `04332d0` plus the uncommitted working tree (Iterations entries 16–38)

This is the fourth run. It checks Iterations entries 29–38 against the third
run's issues V1–V10. There is no feature document, so there are no success
measures, and the plan has no consumer message to re-check.

## Automated Check Results

The Full tier ran on the working tree, unsandboxed, one run at a time.

- **ruff check:** pass
- **ruff format --check:** pass (509 files)
- **pyright:** pass (0 errors, 0 warnings)
- **verify_groups.py:** pass (53 groups)
- **DynamoDB, `make test-all-parallel`:** pass. 5,534 passed, 59 skipped, 1 xfailed, 9 subtests passed.
- **PostgreSQL, `make test-all-parallel`:** pass. 5,344 passed, 249 skipped, 1 xfailed, 9 subtests passed.
- **sphinx-build -W:** pass
- **Benchmarks:** not rerun. Entries 29–38 do not touch list storage or the attribute layer: entry 33 changes only which keywords `update_tombstone` passes.
- **Browser QA:** not rerun this round. Entries 29–38's pages (the expired-session page, the code page and its Start over link, the malformed-challenge page) were walked during the iteration with gstack headless Chromium on `localhost:5055`, at desktop and 375 px. Every check passed; the two lows found then became entry 38. Entry 38's spacer and `maxlength` were confirmed in the served HTML with curl only.
- **Second opinion (outside voice):** codex (`codex exec -s read-only`, unsandboxed, completed), then a fresh-context Claude, on entries 29–38. 12 findings and 2 unverified notes; folded in below.
- **Built-in code review (high):** 10 candidates.
  - Confirmed: 7.
  - Refuted: 1, the stale legacy refresh cookie, for the second time. Both integrations build the handler's cookie dict from the raw `Cookie` header, so the last value wins (`actingweb/interface/integrations/flask_integration.py:646-653`).
  - Accepted: 2.
- **Built-in security review:** nothing at confidence 8 or higher in entries 29–38.
  - It confirmed that the offer refusal holds for a sibling subdomain.
  - A cross-site `format=json` offer creates only an unbound challenge, which a browser redemption refuses (`actingweb/email_sign_in.py:275-276`).
  - `start_over_url` comes from trusted config and is escaped.
  - Outside the diff, it pointed at the address form's completion, which has no cross-site check. That is W1.

## Security properties the plan claims

- **A cross-site code offer is refused before mailing (V1/V5): holds for the offer.** `tests/test_email_sign_in_code.py:521` `test_an_offer_another_site_started_is_refused_before_mailing[cross-site|same-site]`: 403, nothing mailed, no binding cookie, window count still 1.
- **Login CSRF through the email form as a whole: does not hold (W1).** The same `POST /oauth/email` still completes a sign-up for a cross-site submission and sets `oauth_token` in the submitting browser. This is older than this branch: `master` has no cross-site refusal in this handler. Entry 29 placed the guard inside the offer only, after the OAuth session is claimed.
- **The hourly limit cannot be driven past by a failing hook (V3): holds.** `:564` `test_the_challenge_is_withdrawn_and_the_slot_kept` (five 503s, then 429).

## Phase Verification

### Iterations entries 29–38 - ISSUES FOUND

**Changes verified:**
- **29 (V1, V5):** `actingweb/handlers/oauth_email.py:266` `if self._refuse_cross_site():`. Matches, but sits after the claim (W1).
- **30 (V3):** `actingweb/email_sign_in.py:189` `cancel_challenge` deletes only; `:361` `if not sent:`. Matches. The single-handler case is W6.
- **31 (V9):** docstring and changelog wording. Matches.
- **32 (V2):**
  - `actingweb/oauth2.py:2609` `_read_pending_adoption`, `:2636` `_claim_pending_adoption`, `:2665` `_fire_pending_adoption`.
  - `:2829` the read, and `:3171` the announcement.
  - Matches the entry, but the earlier record lives only in memory (W2).
- **33 (V4):** `actingweb/deletion.py:342` `extra: dict[str, Any] = {"clear_ttl": True} if clear_ttl else {}`. Matches.
- **34 (V6):** `oauth_email.py:168` `_start_over_url`, and the template link. Matches. The form `action` beside it is still root-relative (W5).
- **35 (V7):** `oauth_email.py:157` `_session_refused`, at five sites. Matches with the bundled template. Without the template, the fallback drops the link (W4).
- **36 (V8):** `actingweb/deletion_finish.py:131-132` `on_lease`, and `actingweb/maintenance/deletions.py:235`. Matches.
- **37 (V10):** `deletion_finish.py:185` `keep_lease()`. Matches.
- **38:** template spacer and `maxlength="6"`. Matches.

**Tests verified** (each was confirmed during the iteration to fail without its fix):
- `tests/test_email_sign_in_code.py`: `:521`, `:564`, `:583`, `:454-456`, `:653`, `:672`.
- `tests/test_adoption_summary_and_handoff.py:200`.
- `tests/test_deletion_finish.py:556`, `:703`.
- `tests/test_deletions_command.py:239`, `:260`.
- `tests/test_email_verification_legacy_route.py:190`.

The replaced and hand-off branches of entry 32 have no test (W8).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-03-3-16-adoption-fault-followups-reverify-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| V1 held binding reused for a cross-site offer | Fixed for the offer; the form's other branches remain open | entry 29; W1 |
| V2 pending adoption never announced | Fixed for the clean path; can still be lost or doubled | entry 32; W2 |
| V3 slot given back / sent code withdrawn | Fixed (multi-handler); single-handler `DbError` remains | entry 30; W6 |
| V4 `clear_ttl` always passed | Fixed | entry 33 |
| V5 cross-site offer mails a dead code | Fixed for browser forms | entry 29 |
| V6 Start over hardcodes `/` | Fixed; the form action is not (W5) | entry 34 |
| V7 expired session loops | Fixed with the bundled template; the fallback has no link (W4) | entry 35 |
| V8 taken-over lease reported failed | Fixed | entry 36 |
| V9 refusal wording | Fixed | entry 31 |
| V10 no renewal after the client sweep | Fixed | entry 37 |

## Remaining Tasks

These are fixed inside this plan through `/iterate_plan`:

- [ ] W1: refuse a cross-site browser `POST /oauth/email` before anything is claimed, and set no `oauth_token` cookie on a cross-site request
- [ ] W2: keep an earlier pending adoption inside the rewritten record, claimed when it is announced
- [ ] W3: resume a finished tombstone whose actor id is live again as a new deletion
- [ ] W4: Continue link on error pages in both fallbacks
- [ ] W5: the code and address forms post under the app's base path
- [ ] W6: document a hook's `DbError` as "not sent", and log the exception
- [ ] W7: use `LEGACY_REFRESH_COOKIE_PATH` everywhere
- [ ] W8: changelog wording and a test for the replaced branch
- [ ] W9: stale comment in `_offer_sign_in_code`
- [ ] W10: a separate binding length constant

## Issues Found

### W1. The email form still allows login CSRF on every branch except the code offer
**Severity:** High (older than this branch; the same class as V1)
**Description:** `POST /oauth/email` checks the request's site nowhere except inside `_offer_sign_in_code`:
- `actingweb/handlers/oauth_email.py:266`: `if self._refuse_cross_site():`. This runs only after `try_claim_session` at `:849`, and only for an address that already has an actor.
- `:892`: `actor_instance = session_manager.complete_claimed_session(` completes the sign-up.
- `:1066-1077` sets `oauth_token` with `self.response.set_cookie(` before the JSON branch, so a cross-site form that adds `format=json` gets the cookie too.

The attack: the attacker completes a provider login that needs the email form, keeps the session id, and has another site auto-post `session=<theirs>&email=<an address>` from the victim's browser. The victim is then signed in to the attacker's actor.

The late placement also means a refused offer has already used up the OAuth session. And for a request with a forged `Origin` (curl), the 403 reveals that the address has a vouched actor, where an unforged request gets a 409 or a create.
**Location:** `actingweb/handlers/oauth_email.py:849`, `:892`, `:1066-1077`, `:266`
**Recommendation:** At the top of `post()`, refuse a cross-site non-JSON request (403) before any branch: verify, redeem, claim. Set the `oauth_token` cookie only when the request is not cross-site; a JSON client gets the token in the body. Test: a cross-site form post, with and without `format=json`, sets no `oauth_token` and leaves the session unclaimed.

### W2. An earlier pending adoption lives only in memory, so a failure after the rewrite loses it, and the unclaimed fire can double it
**Severity:** Medium
**Description:**
- `actingweb/oauth2.py:2829` reads `earlier = (carried or {}).get("earlier_pending") or _read_pending_adoption(`.
- `_record_pending_adoption` then overwrites the stored record with this sign-in's victim (`:2890`, and `:2307` in `_replace_enforced`). Any fail-closed return after that loses the earlier replacement for good: `if removed is None: return None` (`:2900`), `if swept is None: return None` (`:2906`), the successor reads (`:2943`, `:2960`), the enforced path's `return None, ...` (`:2355`), and a hand-off's inner returns.
- `_read_pending_adoption` folds a read fault into "none" (`:2625`). Its caller runs before anything is removed, where a fault should fail closed.
- On the replaced and hand-off branches, `:3172-3176` fires the earlier record from the read without a claim. A concurrent announcer can fire it too.
**Location:** `actingweb/oauth2.py:2561` (`_record_pending_adoption`), `:2609-2690`, `:2829`, `:3171-3180`
**Recommendation:** Have `_record_pending_adoption` read the current record strictly, carry an unannounced earlier entry inside the new one (`earlier: [...]`), and write it conditionally on the row as read. Let every announcer claim the record, then fire each earlier entry plus the main one, skipping the ids its own event reports. Write the record before the SPA token revoke, so a read fault fails the sign-in with nothing removed. Test the replaced branch (a factory actor created meanwhile) and a failure after the rewrite.

### W3. A finished tombstone whose actor id is live again is resumed with its stale finish
**Severity:** Medium
**Description:** The scan reports a finished tombstone over a live row as legacy, so review it (`actingweb/maintenance/deletions.py:150-153`), and `resume ACTOR_ID --apply` runs it.
- `actingweb/deletion_finish.py:134`: `if not deletion.is_resumable(data):` resets `finished_at`, `hook_fired` and the TTL for a legacy tombstone only. A finished resumable one keeps all three.
- The wipe then runs under a TTL counting down from the earlier finish.
- `mark_finished` returns False because `finished_at` is already set (`actingweb/deletion.py`, `if current.get("finished_at"): return False`), so `_confirm_finished` sees the stale `finished_at` and reports success.
- `actor_deleted_complete` never fires for the re-created actor.
**Location:** `actingweb/deletion_finish.py:134`
**Recommendation:** Treat a tombstone with `finished_at` set like a legacy one: `if not deletion.is_resumable(data) or data.get("finished_at"):`. Test: resume a finished tombstone over a live row; afterwards it is finished again with a fresh TTL.

### W4. The fallback result page drops the Continue link on errors
**Severity:** Low
**Description:** `actingweb/interface/integrations/flask_integration.py:1346-1348` (`if ok and actor_id`), and the same check in `fastapi_integration.py:2179-2183`. Without an `aw-verify-email.html` template, the expired-session page, the 503 "could not be sent" and every verification error are dead ends again. That contradicts the changelog's "with its Continue link".
**Location:** as above
**Recommendation:** Render `redirect_url` whenever it is set. Tell overriding `aw-verify-email.html` templates in `docs/migration/v3.16.rst` that error states carry `redirect_url`.

### W5. The code and address forms post to `/oauth/email` outside a base path
**Severity:** Low
**Description:** Under a base path, Sign in and Continue post outside the app, next to a Start over link that stays inside it:
- `actingweb/handlers/oauth_email.py:327`: `"action": "/oauth/email",` (and the other template values);
- `code_page_html`: `<form method="POST" action="/oauth/email">`.
**Location:** as above
**Recommendation:** Build the action from the app's root.

### W6. A single hook's `DbError` after sending withdraws a mailed code; the later-handler log drops the exception
**Severity:** Low
**Description:**
- `actingweb/email_sign_in.py:361` (`if not sent: raise`) and `oauth_email.py:291-293` (`except DbError: email_sign_in.cancel_challenge(...)`): a hook that sends and then faults on its own store write leaves the user with a dead code and a 503.
- `logger.error(f"Error in {HOOK} hook after the code was sent")` omits the error.
**Location:** as above
**Recommendation:** Document in the hooks reference that any exception from the only handler, a `DbError` included, counts as "not sent". Log the exception.

### W7. The legacy refresh-cookie path is hardcoded twice beside the new constant
**Severity:** Low
**Description:** `actingweb/handlers/oauth2_spa.py:1949` (`_clear_token_cookies`) and `actingweb/handlers/oauth2_endpoints.py:51` repeat `"/oauth/spa/token"`, while `LEGACY_REFRESH_COOKIE_PATH` exists.
**Recommendation:** Use the constant.

### W8. The changelog names a path the email form's actor never takes; the replaced branch is untested
**Severity:** Low
**Description:**
- `actingweb/oauth2.py:1791`: `REPLACE_AUTH_METHODS = frozenset({"factory"})`. The email form's actor is cleaned, never replaced.
- `CHANGELOG.rst` says "one that later cleans or replaces the actor the email form created meanwhile".
- The replaced branch runs only for a factory actor created in the meantime, and no test covers it.
**Recommendation:** Reword the changelog and the hooks reference ("cleans the email form's actor, or replaces a factory actor created meanwhile"), and add the test (with W2).

### W9. A stale comment in `_offer_sign_in_code`
**Severity:** Low
**Description:** `actingweb/handlers/oauth_email.py:256-262` says a cross-site offer "is refused before anything is created or mailed". That holds for the browser branch only, and after W1 it belongs at the top of `post()`.
**Recommendation:** Rewrite it with W1.

### W10. `is_binding` checks against the challenge id's length
**Severity:** Low
**Description:** `actingweb/email_sign_in.py:348` `is_binding` uses `_CHALLENGE_ID_LENGTH`. If either value's size changes, every held binding fails the check and offers void each other again.
**Recommendation:** A separate `_BINDING_LENGTH`.

### Accepted (not findings)

- **A browser that sends none of `Sec-Fetch-Site`, `Origin` and `Referer`** passes the cross-site check (`actingweb/cross_site.py`, `return require_evidence and session_cookie`). Every current browser sends `Origin` on a cross-origin POST, and the attack would still need the victim's challenge id, which it cannot read.
- **A correct code refused by `may_sign_in` shows the wrong-code page and costs a try.** This is documented (entry 31), and a separate message would be an oracle on the code.
- **An actor vouched by `actingweb-mark-actors-vouched`** does not announce a waiting pending adoption, because the vouched branch reads no record. The record expires after 7 days. To be documented with W8.
- **`send_code` uses the registry's private API:** accepted in entry 37.

## Overall Assessment

Entries 29–38 do what they say, each with a test confirmed to fail without
it, and the Full tier is green on both backends. But entry 29 put the
cross-site guard inside the offer, after the OAuth session is claimed. The
form's other branches still let another site sign a browser in to an
attacker's actor (W1). That is older than this branch, but it is the same
login-CSRF class this plan exists to close. Entry 32 fixes the common case
of the lost `actor_adopted`, but keeps the earlier record only in memory
(W2), and a finished tombstone over a live row resumes with a stale finish
(W3). Fix W1–W3 before merging; W4–W10 are small. The plan stays
`status: done`, and `verified:` moves to this document.
