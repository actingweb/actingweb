# Verification: 3.16 adoption, deletion and fault-contract follow-ups (re-run)

**Date:** 2026-11-03
**Plan:** thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md
**Research:** the todos named in the plan's **Research:** line (deleted; no research document)
**Branch:** `release/3.16.0-adoption-fault-followups`
**Commit:** `04332d0` (fixes in `9e8b2a0..e5069ad`; whole range `b7c5c94..04332d0`)

This is the second run. It checks Iterations entries 2–15 against the 17 issues in the first verification. There is no feature document, so there are no success measures, and the plan has no consumer message to re-check.

## Automated Check Results

The Full tier from `CLAUDE.md` ran at `04332d0`, unsandboxed, one test run at a time.

- **ruff check:** pass ("All checks passed!")
- **ruff format --check:** pass (508 files already formatted)
- **pyright:** pass (0 errors, 0 warnings, 0 informations)
- **verify_groups.py:** pass (all 53 groups documented)
- **DynamoDB, `make test-all-parallel`:** pass. 5,497 passed, 59 skipped, 1 xfailed, 9 subtests passed, 46.2 s. Nothing failed, so no sequential re-run was needed.
- **PostgreSQL, `make test-all-parallel`:** pass. 5,307 passed, 249 skipped, 1 xfailed, 9 subtests passed, 46.1 s.
- **sphinx-build -W:** pass (rc=0)
- **Benchmarks:** not run. The fixes do not touch list storage or the attribute layer's read paths. The DynamoDB change only adds WARNING logs to two conditional writes.
- **Browser QA:** ran with gstack browse (headless Chromium) against the demo in local QA mode on `localhost:5055` (fresh `AWS_DB_PREFIX`; no actor was created). The code *offer* page needs a claimed provider session, and OAuth is off in this mode, so the offer page was again not loaded in a browser. The flow through the real Flask and FastAPI routes is covered by `tests/test_email_sign_in_code.py::TestThroughTheIntegrations`, which patches the form submission to its offer.
  - **Passed:**
    - An empty `?verify=` answers the invalid-link page (403).
    - An unknown or 2,000-character token reaches the Confirm page, and confirming it answers 403 as HTML, not a 500.
    - A wrong code with a 32-character challenge re-renders the code page with the error (401). Empty, letter, 5,000-digit and script/img inputs are refused, and none is echoed back: the DOM held 0 injected elements.
    - The JSON 401 body is correct.
    - All pages fit at 375 px, and the console shows only the expected status lines.
  - **Low (B1):** a `code_challenge` that is not exactly 32 characters, including the 2,000-character case, still answers an empty 401 HTML page. `_sign_in_code_refused` sends any id that is not a valid challenge id to `error_response`, which renders an empty body for a browser (`actingweb/handlers/oauth_email.py:363`, `if self._wants_json() or not email_sign_in.is_challenge_id(challenge_id):`).
  - **Low (B2):** the library template's heading is always "Enter your email" (`actingweb/templates/aw-oauth-email.html:5`, `<h1>Enter your email</h1>`), including on the code page and the code offer.
  - Screenshots: `/tmp/qa-adoption-fault-2/`.
- **Second opinion (outside voice):** codex (`codex exec`, unsandboxed, exit 0), then a fresh-context Claude, on `9e8b2a0..e5069ad`. 11 findings and 4 unverified notes; they are folded in below.
- **Built-in code review (high), whole branch against `master`:** 10 candidates. I confirmed the top two by reading the code; the rest are folded in below with a verdict.
- **Built-in security review:** none at confidence 7 or higher, so nothing went to the false-positive filter. It traced and refuted these:
  - the `format=json` path around the login-CSRF binding: a JSON redemption sets no cookie;
  - XSS in `code_page_html`, the confirm page and the templates;
  - cookie copying (SameSite never falls back to None);
  - the session generation stamps;
  - E1 forging.

## Security properties the plan claims

- **The sign-in code binding (login CSRF) now holds.** Last run it did not.
  - `tests/test_email_sign_in_code.py:173` `test_a_json_challenge_cannot_be_redeemed_by_a_browser` asserts that `redeem(..., browser=True)` is `None` for an unbound challenge, with or without a cookie, and that the JSON path still redeems it.
  - `:368` `test_a_json_challenge_posted_by_a_cross_site_form_is_refused` goes through the Flask route: a JSON-created challenge posted as a form from another client answers 401 with no `oauth_token` in `Set-Cookie`.
  - `:298` `test_offer_then_redeem_in_one_browser_signs_in[flask|fastapi]` asserts that the binding cookie reaches the wire with `samesite=strict`, and that the same client ends with a 302 and `oauth_token=`.
  - `:342` asserts that another client gets 401 and the code page again.
  - Not covered: the binding cookie is one per browser. A second offer in the same browser replaces it (issue N4), which defeats the plan's claim that "a new challenge does not void the previous one" for browsers.
- **The hourly cap under concurrency holds.**
  - `:188` `test_concurrent_starts_stay_within_the_cap` asserts `results.count("ok") <= 5` for 12 concurrent starts against the real store.
  - Weakness: the test also passes when every start faults. It does not assert that at least one start succeeds.
- **R3, a credential issued during the clean mints nothing, holds.**
  - `tests/test_session_generation.py:241` `test_a_stamp_taken_during_the_clean_mints_nothing_after_it`.
  - The code bumps a second time before the second revoke (`actingweb/oauth2.py:3008`).
- **R3 breaks a legitimate path, though.** `ActorInterface.oauth_clients.generate_access_token` passes no stamp, so it fails for every actor that has been cleaned (issue N1).
- **E1 and the MCP bridge refusal:** unchanged since the last run. Their tests still pass.

## Phase Verification

The phases themselves were verified in the first run. This run checks the iteration entries that changed them.

### Iterations entries 2–15 - ISSUES FOUND

Every entry's code is present and matches its description. Each regression test named in the plan exists:

| Entry | Test |
| --- | --- |
| 2 | `tests/test_email_sign_in_code.py:173`, `:368` |
| 3 | `:298`, `:342` |
| 4 | `:162`, `:188` |
| 5 | `tests/test_fault_contract_followups.py:56` |
| 6 | `tests/test_deletions_command.py:146` |
| 7 | `tests/test_fault_contract_followups.py:174` |
| 8 | `tests/test_deletion_finish.py:492` |
| 9 | `tests/test_session_generation.py:241` |
| 10 | `tests/test_deletions_command.py:170` |
| 11 | `tests/test_adoption_summary_and_handoff.py:183` |
| 12 | `tests/test_deletion_finish.py:553` |
| 13 | `tests/test_email_verification_legacy_route.py:185`; `tests/test_email_sign_in_code.py:206`, `:241` |
| 14 | `tests/test_session_generation.py:280`; `tests/test_fault_contract_followups.py:224` |
| 15 | `tests/test_deletion_in_progress_answers.py:93`; `tests/test_deletion_finish.py:574` |

The four todos the plan closes (`adoption-fault-and-hygiene-followups`, `resumable-actor-deletion`, `oauth-email-verified-claim-unchecked`, `email-form-user-sign-in-after-verification`) are still gone, with no `INDEX.md` row. The plan names no deferral that needs a todo.

**Deviations and scope:**
- Entry 3 changes FastAPI's general cookie copy (`fastapi_integration.py:97-111`) for every handler, not only `/oauth/email`. That is broader than the issue it fixes, and it has a consumer-visible effect (issue N3) that is in no changelog entry.
- Entry 3 also passes the handler's status to every `aw-oauth-email.html` render. The address form's 409 and 400 pages used to answer 200 and now answer their real status. That is not in the changelog either (issue N9).

## Previous Verification

**Previous:** thoughts/verifications/2026-11-03-3-16-adoption-fault-followups.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. A JSON challenge bypasses the binding (login CSRF) | Fixed | `email_sign_in.py:239` `if browser and not expected_binding:`; tests above |
| 2. The binding cookie never reached the browser | Fixed | `flask_integration.py:33` `_with_cookies`, `fastapi_integration.py:97` `_apply_cookies`; `test_offer_then_redeem_in_one_browser_signs_in` |
| 3. The cap did not hold under concurrency | Fixed | `email_sign_in.py:87` `_claim_slot` (conditional writes, a nonce, three retries, then `DbError`) |
| 4. A non-`DbError` revocation failure was swallowed | Fixed | `callbacks.py:1132` `raise`; `test_a_non_db_error_delete_failure_raises`. The side effect is issue N10. |
| 5. A programmatic delete left a tombstone with no TTL | Fixed, with a new race | `actor.py:1154` `deletion.finish_unleased(...)`; `TestProgrammaticDelete`. See issue N5. |
| 6. Credentials issued during the clean carried the new generation | Fixed | `oauth2.py:2998-3008`; `test_a_stamp_taken_during_the_clean_mints_nothing_after_it` |
| 7. The lease was not renewed during the wipe | Fixed, one gap | `deletion_finish.py:240` `_lease_keeper`; `TestLeaseKeeper`. The keeper's clock starts late (issue N6). |
| 8. A pending resync record blocked a later suspension | Fixed | `actor.py:3064-3100`; `test_a_later_suspension_is_still_lifted` |
| 9. Anyone could void the owner's live code | Fixed in the store, still open in the browser | Challenges no longer delete each other, but the single binding cookie does it in a browser (issue N4) |
| 10. Wrong-code and over-long input answers | Mostly fixed | The blank page, the 500 and the empty `verify` are fixed (browser QA). A wrong-length challenge still gets an empty 401 (B1). |
| 11. `resume` printed "finished" after a failed `mark_finished` | Fixed | `maintenance/deletions.py:214` `_confirm_finished`; `TestCommandRobustness`. Side effect: issue N12. |
| 12. A pending-adoption record leaked after a hand-off | Fixed | `oauth2.py:3114` `if result is not None and (mode == "replaced" or carried):` |
| 13. Planned tests were missing | Partly added, rest accepted | Iterations entry 15 lists what was added and gives a reason for each item not added. Accepted. |
| 14. The K4 rollback was partial | Accepted as-is | Entry 15: a marker that did not land means nothing was written to `_internal` |
| 15. Stale notes in the plan | Fixed | Entry 15 |
| 16. A legacy tombstone suppressed `actor_deleted` | Fixed, one gap | `deletion_finish.py:135-148`; `TestLegacyTombstoneOnDelete`. The rewritten tombstone keeps its old TTL (issue N7). |
| 17. Smaller items | Fixed or accepted | Entry 14 (WARNING logs, `guard` with several removals, PostgreSQL `modify`); two items accepted with a reason. The consume fault reading as a wrong code is still open (issue N8). |

The three loose ends recorded in the plan's "Where this stands" are still open:
- the hook raising after the code is counted (the code review found it again, `oauth_email.py:262`);
- the invalid-link dead end (browser QA confirmed it: the page has no link or form);
- the `Secure` cookie over plain HTTP.

## Remaining Tasks

These are for `/iterate_plan` on this plan. Per the owner's rule, they are not filed as todos.

- [ ] N1 (high) and N2–N4 (medium) before the PR.
- [ ] N5–N10: fix, or accept with a line in the plan.
- [ ] N11–N14, B1, B2 (low).
- [ ] The three loose ends from "Where this stands": a fix or an owner acceptance for each.
- [ ] Verify again afterwards.

## Issues Found

### N1. `generate_access_token` mints nothing for any actor that was ever cleaned
**Severity:** High
**Found by:** code review; confirmed by reading the code
**Description:** R3's guard compares the client's stamp with the actor's current generation. `matches()` treats a missing stamp as `None` (`session_generation.py:111`, `stamp = str(stamped) if stamped else None`). Once a clean has written a generation, `None` never equals it. `ActorInterface.oauth_clients.generate_access_token()` calls `create_access_token` without `client_generation`, so every call for that actor writes a token, revokes it, and returns `None`. Clients registered after the clean, which carry the right stamp, fail too. The OAuth2 server path passes the stamp (`oauth2_server.py:681`, `client_generation=client_data.get("session_generation"),`); this public SDK path does not. No test covers it.
**Location:** `actingweb/interface/oauth_client_manager.py:384-390` (`token_response = token_manager.create_access_token(` ... `grant_type="client_credentials",` `)`)
**Recommendation:** pass `client_generation=client_data.get("session_generation")`. Add a test: adopt in place, register a client, `generate_access_token` returns a token; a client registered before the clean gets `None`.

### N2. A correct code is spent before the session is written; a token-store fault answers 500
**Severity:** Medium
**Found by:** code review and outside voice (separately); confirmed
**Description:** `redeem` deletes the challenge, and only then does the handler check the tombstone and write the tokens. `store_access_token` / `create_refresh_token` raise `TokenStoreUnavailable` (`oauth_session.py:525-527`), which is not a `DbError`. The integrations' `DbError` mapping therefore does not catch it, and the user gets a 500 with the code already spent and an hourly slot used. Every other token-issuing handler maps this exception to 503.
**Location:** `actingweb/handlers/oauth_email.py:302-340`
**Recommendation:** check the tombstone before `redeem`, and map `TokenStoreUnavailable` to 503 here as the other handlers do. Consider writing the session before consuming the challenge, or accept that a store fault spends the code and say so.

### N3. FastAPI now scopes the hybrid `refresh_token` cookie to `/oauth/spa/token`
**Severity:** Medium
**Found by:** outside voice; confirmed
**Description:** `_apply_cookies` keeps `path` (`fastapi_integration.py:107`, `path=cookie.get("path") or "/",`). The callback sets the hybrid refresh cookie with `path="/oauth/spa/token"` (`oauth2_callback.py:772`). Before this change, FastAPI dropped the path and stored the cookie at `/`. Now:
- `/oauth/logout` no longer receives it (`oauth2_endpoints.py:1104`, `add(self.request.cookies.get("refresh_token"))`), so a logout before the first refresh leaves the refresh token valid on the server;
- the first rotation writes a second cookie at `/` (`oauth2_spa.py`, `path="/"`), and two `refresh_token` cookies then reach `/oauth/spa/token`.

Flask already behaved this way, so FastAPI now matches Flask, problem included. The changelog does not mention the FastAPI change.
**Location:** `actingweb/interface/integrations/fastapi_integration.py:97-111`; `actingweb/handlers/oauth2_callback.py:766-775`
**Recommendation:** make the hybrid refresh cookie use one path in every setter (callback and rotation), and make logout able to see it. Add a hybrid login → refresh → logout test on both integrations. Add a **Behavior change:** sentence for FastAPI cookie attributes.

### N4. One browser holds one binding cookie, so a second offer voids the first code
**Severity:** Medium
**Found by:** outside voice
**Description:** every offer sets `__Host-aw_sign_in_binding` with a fresh value (`oauth_email.py:242-250`). A second offer in the same browser therefore replaces the binding the first challenge needs: a double submit, a second tab, or a cross-site top-level POST of an attacker's own claimed session with the victim's address. The first code then answers 401 and burns a try on each attempt. This contradicts `start_challenge`'s docstring ("A new challenge does not cancel an earlier one"). The tests do not use a cookie jar across two offers.
**Location:** `actingweb/handlers/oauth_email.py:233`, `:242-250`
**Recommendation:** reuse the existing binding cookie's value when the request carries one, or keep a set of bindings in the cookie. Add a test with two offers, then redeeming the first code, in one client.

### N5. `finish_unleased` can mark a tombstone finished under a lease claimed a moment later
**Severity:** Medium (plausible)
**Found by:** outside voice (codex), with a related code-review finding at the operator command
**Description:** `finish_unleased` checks `lease_remaining`, then calls `mark_finished(actor_id, config, None)`. With `lease_id` `None`, the ownership check `if lease_id and current.get("lease_id") not in (lease_id, None):` (`deletion.py:563`) never applies. A finisher that claims the lease between the two reads has its lease cleared and `finished_at` set under it. Its own `mark_finished` then returns False, and `actor_deleted_complete` is lost with no log. `actingweb-deletions resume`'s unfinished branch (`maintenance/deletions.py:194`) has the same shape with no lease check at all, and it fits the plan's own "the operator command races a request" scenario.
**Location:** `actingweb/deletion.py:606`, `:563`; `actingweb/maintenance/deletions.py:194`
**Recommendation:** in `mark_finished`, refuse when `lease_id` is `None` and the fresh row holds a live lease. Have the command report such a row as in progress.

### N6. The lease keeper's clock starts after the token and client sweeps
**Severity:** Medium
**Found by:** outside voice (codex); confirmed
**Description:** the lease is renewed at `deletion_finish.py:164` (`data = _update(actor_id, config, data, deletion.lease_fields())`). Then come `_revoke_all_actor_tokens` and `_delete_actor_clients`, and only then is the keeper built, with `last = [time.monotonic()]` (`:249`). When the sweeps take long, the keeper waits another 40 s before its first renewal, and the lease can lapse. Entry 8 closes the main window but not this one.
**Location:** `actingweb/deletion_finish.py:164-177`, `:249`
**Recommendation:** build the keeper right after the renewal at `:164` and pass it in, or call it once before the revoke.

### N7. A legacy tombstone turned resumable keeps its old retention TTL
**Severity:** Medium
**Found by:** outside voice and code review (separately)
**Description:** entry 12 rewrites a reason-less tombstone with a reason and `hook_fired=False` through `_update`, which passes no TTL. `update_tombstone` keeps the existing TTL when the data is resumable (`deletion.py:501`, `ttl_seconds=None if is_resumable(data) else DELETION_TOMBSTONE_TTL`). If this wipe stalls, the record that should carry no TTL until it is finished expires on the old 30-day deadline. The actor then drops out of `report` and loses its late-write suppression.
**Location:** `actingweb/deletion_finish.py:135-148`; `actingweb/deletion.py:501`
**Recommendation:** clear the TTL, and any `finished_at`, in that rewrite. Add a case to `TestLegacyTombstoneOnDelete`.

### N8. A store fault while counting or consuming a code reads as a wrong code
**Severity:** Medium
**Found by:** outside voice (codex)
**Description:** on DynamoDB, `delete_attr_conditional` and `conditional_update_attr` now log a fault and return `False`, the same as a lost condition. `redeem` reads that as "attempt not counted; refused" (`email_sign_in.py:236`) or "already consumed" (`:257`). During a throttle, a user typing the right code gets 401 "Invalid or expired sign-in code" and burns a try, not a 503.
**Location:** `actingweb/email_sign_in.py:236`, `:257`
**Recommendation:** after a `False`, read the row strictly; if it is unchanged, raise `DbError`.

### N9. The address form's error pages now answer their real status
**Severity:** Low
**Found by:** outside voice
**Description:** both integrations now pass `webobj.response.status_code` to every `aw-oauth-email.html` render. The 409 "actor exists" page (`oauth_email.py:195`) and the invalid-email 400 used to answer 200. A template front end that checks `response.ok`, or a monitor, sees the change.
**Recommendation:** add a **Behavior change:** sentence to the changelog. The new statuses are correct and should stay.

### N10. A permanent non-database failure in the revocation delete blocks a peer's permission callbacks
**Severity:** Low
**Found by:** outside voice
**Description:** with entry 5's `raise` (`callbacks.py:1132`), a `KeyError` from a malformed stored list answers 500 on every retry, and the new permissions, grants included, are never stored. This is the fail-closed choice entry 5 made. It is worth an owner acceptance line.
**Recommendation:** accept and record it, or re-raise only for transient faults.

### N11. `actor_adopted` can announce a pending adoption on an unvouched create
**Severity:** Low (plausible)
**Found by:** code review
**Description:** `_announce_pending_adoption` runs after every create in `lookup_or_create_actor_by_identifier` (`oauth2.py:1238`), including the email form's `create_only` create with `auth_method="email_unverified"`. A pending record left by a failed successor create would then be announced on an actor that proved nothing. That needs a failed successor create inside the seven-day window and then a free-text create for the same address.
**Recommendation:** announce only on a vouched create; add a test.

### N12. `resume --apply` can report a deletion that another finisher is completing as failed
**Severity:** Low
**Found by:** outside voice
**Description:** `_confirm_finished` raises when `finished_at` is missing, and that includes the case where another finisher holds the lease and finishes moments later (`maintenance/deletions.py:214-222`). The command then exits 2 for a deletion that does finish.
**Recommendation:** report a live lease held by someone else as in progress. Fix it together with N5.

### N13. A legacy tombstone resumed by the operator command keeps no record
**Severity:** Low
**Found by:** code review
**Description:** on any origin other than `delete`, the legacy branch writes only `hook_fired=True` (`deletion_finish.py:148`). `reason`, `notify_peers` and `client_ids` stay unrecorded, and `effective_peers` is True for a legacy row. A `resume <id> --apply` of a pre-3.16 replacement victim therefore notifies peers by default. If it stalls again, the row is still "legacy, review".
**Recommendation:** record `client_ids` and the chosen `notify_peers` on that branch too, or document that a legacy resume notifies peers unless `--no-notify-peers` is given.

### N14. Smaller items
**Severity:** Low
- `is_challenge_id` accepts non-ASCII letters and digits (`email_sign_in.py:270-271`, `c.isalnum() or c in "-_"`); use `c.isascii() and c.isalnum()`.
- `test_concurrent_starts_stay_within_the_cap` also passes when every start faults; assert at least one `"ok"`.
- `exchange_authorization_code`: a generation-read fault after the code is consumed answers 503, and the retry is then refused as "already used" (`token_manager.py:260`). Accept it, or say so in the R3 changelog entry.
- The code review flagged two more, plausible and unconfirmed:
  - the changelog's "default-creator actors are still moved when next loaded" against the vouched-only load rewrite (`actor.py:412`);
  - `redeem` not re-checking that the actor's creator is still the address the code was sent to (`email_sign_in.py:268`).

  Check both against the changelog wording and the rename paths in the iteration.

## Overall Assessment

The fixes for the first verification landed. The Full tier is green on both backends (DynamoDB 5,497, PostgreSQL 5,307), and ruff, pyright, the groups check and the docs build are clean. All 17 earlier issues are fixed or accepted with a reason in the plan. The login-CSRF binding now holds end to end, and tests through the real Flask and FastAPI routes pin it. Browser QA confirms that the blank page, the 500 and the empty-`verify` page are gone.

It is not ready for a PR. One high regression from Phase 1 went unnoticed in both rounds: R3's guard makes `ActorInterface.oauth_clients.generate_access_token()` fail permanently for any actor that was ever cleaned (N1), and no test covers that path. Three medium issues should go with it:
- a token-store fault after a correct code answers 500 with the code spent (N2);
- FastAPI's refresh cookie changes scope without a changelog line, and logout can miss it (N3);
- a second offer in one browser voids the first code (N4).

The deletion items (N5–N7) are narrow races or TTL gaps around the new finisher, and each has a one-line fix. The code offer page itself has still not been loaded in a browser, because the demo's QA mode has no provider. Next: `/iterate_plan` on N1–N4 and whichever of the rest the owner wants, then verify again.
