# Verification: 3.16 adoption, deletion and fault-contract follow-ups

**Date:** 2026-11-03
**Plan:** thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md
**Research:** the todos named in the plan's **Research:** line (deleted; no research document)
**Branch:** `release/3.16.0-adoption-fault-followups`
**Commit:** `9e8b2a0` (range `b7c5c94..9e8b2a0`, 7 commits, 84 files, +6546/-810)

First run; no previous verification. No feature document, so no success measures. The plan has no consumer message to re-check.

## Automated Check Results

All runs are from the Full tier script at `9e8b2a0`. Each command ran once, unsandboxed, one test run at a time.

- **ruff check:** pass ("All checks passed!")
- **ruff format --check:** pass (508 files already formatted)
- **pyright:** pass (0 errors, 0 warnings, 0 informations)
- **verify_groups.py:** pass (all 53 groups documented)
- **DynamoDB, `make test-all-parallel`:** pass. 5,466 passed, 59 skipped, 1 xfailed, 9 subtests passed, 53.4 s. No failures, so no sequential re-run was needed.
- **PostgreSQL, `make test-all-parallel`:** pass. 5,273 passed, 252 skipped, 1 xfailed, 9 subtests passed, 57.7 s.
- **sphinx-build -W:** pass (rc=0)
- **Benchmarks:** not run. The plan touched no list storage. It changed the attribute layer only by adding `list_all(strict=)` and `list_all_lists(strict=)` flags, and the default path is unchanged.
- **Browser QA:** ran, provider gstack browse (headless Chromium), against the demo in local QA mode on `localhost:5055`. OAuth is off in that mode, so only the provider-free pages were reachable: the verification Confirm page (GET and POST) and the sign-in-code POST. The code *offer* page, which needs a claimed OAuth session, was not exercised in a browser. Findings, by severity:
  - **Medium:** an over-long `verify` or `code_challenge` (about 1,005 characters or more) answers 500 "The request could not be stored", as raw JSON.
  - **Medium:** a wrong sign-in code answers a blank 401 page with an empty body.
  - **Low:** `?verify=` with an empty value shows the email form with "Missing session parameter".

  The HTML-injection token is escaped, and no page leaves anything in the console beyond the expected non-2xx lines. Both pages fit a 375 px width. No `oauth_token` cookie was set on any path. Screenshots are in `/tmp/claude-501/qa-adoption-fault/`.
- **Second opinion (outside voice):** codex (`codex exec -s read-only`, unsandboxed, finished) plus a fresh-context Claude: 11 findings, folded below.
- **Built-in code review (high):** 10 findings, folded below.
- **Built-in security review:** one finding at confidence 8 or higher (the login CSRF, issue 1), plus the functional cookie bug (issue 2). The E1 forging, escaping, confirm-page CSRF and session-generation candidates were checked and refuted.

## Security properties the plan claims

Each claimed property, with the test that pins it:

- **E1, an unverified provider address is never an identity:** holds.
  - `tests/test_oauth2_email_verified_claim.py:51` (Google) and `:64` (Apple) cover `"yes"`, false and absent → unverified. `:82` covers a failing GitHub list → unverified.
  - `:120` pins that an unverified address is not the identity; `:150`, `:165` and `:178` that it is not seeded and not stored.
  - `:190` pins that the Apple form_post address is never verified.
  - The security review traced every `user_info` build site and found no way to forge the mark.
- **R3, a pre-clean credential mints nothing:** holds for the stamped grants.
  - `tests/test_session_generation.py:87` (code), `:110` (straddling refresh), `:145` (client registration) and `:161` (SPA refresh) each assert that the grant fails and what it wrote is revoked.
  - `:130` pins that a read fault revokes and answers unavailable.
  - Issue 6 is a window this does not cover.
- **The MCP bridge never recreates a deleted id:** holds (`tests/test_deletion_in_progress_answers.py:47` `test_a_deleted_id_is_not_recreated`).
- **The sign-in code binding (login CSRF):** **does not hold.**
  - `tests/test_email_sign_in_code.py:153` `test_a_bound_challenge_needs_its_browser` asserts only that a challenge created *with* a binding needs it. A challenge created over JSON has no binding and passes any redemption (issue 1).
  - The binding cookie never reaches a browser either (issue 2), so the property is untested end to end.

## Phase Verification

### Phase 1: Resumable deletion, AW, the session generation - ISSUES FOUND

**Changes verified (match the plan or a recorded deviation):**
- `actingweb/deletion.py`:
  - `mark_actor_deleted` with T1's fields (`:104`)
  - `read_tombstone` (`:242`)
  - `claim_lease` (`:351`), `create_leased_tombstone` (`:388`), `release_lease` (`:437`)
  - `restamp` (`:466`), `mark_finished` (`:527`)
  - `clear_actor_tombstone(strict=)` (`:186`)
- `actingweb/deletion_finish.py:48`, `finish_deletion`
- `actingweb/db/exceptions.py:37`, `DeletionInProgress`; `actingweb/constants.py:252`, `DELETION_LEASE = 120`
- `actingweb/actor.py:1055`, `Actor.delete(_pre_reads=)`, restamp at `:1115`
- AW1's strict clear for a fixed id (`actingweb/actor.py:762-785`)
- `actingweb/handlers/mcp.py:2521-2534` (the bridge refusal) and `:2465-2482` (`_race_winner` strict)
- `actingweb/handlers/root.py:125-136` (`finish_deletion`; an unconfirmed removal answers 503)
- `actingweb/oauth2.py`:
  - `_finish_stalled_vouched` (`:2462-2508`)
  - `_remove_for_replacement` (`:2056`)
  - the sweep skipping a leased sibling (`:2261-2264`)
  - `lookup_or_create_actor_by_identifier(finish_stalled_deletion=, existing=)` (`:1121`)
  - the clean bumping the generation before the passphrase (`:2967`)
- `actingweb/session_generation.py` (`current` `:53`, `bump` `:71`, `guard` `:115`)
- The stamps: `token_manager.py:133` and `:916-919`, `client_registry.py:113`, `oauth_session.py:618-678`
- The checks: `token_manager.py:260`, `:508`, `:1534`; `oauth2_spa.py:941`
- `actingweb/maintenance/deletions.py` (`report`, `resume`, `clear`, exit codes) and its entry point at `pyproject.toml:42`

**Deviations not recorded in the plan:**
- The plan names `mark_hook_fired`, `renew_lease` and `set_tombstone_ttl`. None exists under those names; the work is done by `_update(...)` in `deletion_finish.py:129,139,143` and by `mark_finished`. The behaviour is equivalent. Acceptable.
- K4's create rollback: the generated-id `_internal` delete is only in the `trustee_root` rollback (`actor.py:889-894`), not in the marker rollback (`:847-853`). The fixed-id rule ("only if this create wrote it") has no code. Low (issue 14).
- The handlers that write their own 503 still send `Retry-After: 5` (`oauth2_spa.py:1977`, `mcp.py:2906`). Those are token-store answers that `DeletionInProgress` does not reach. `_db_fault_response` (`mcp.py:2912`) uses the shared mapping. Acceptable.
- `actingweb-deletions` builds its `Config` from `DATABASE_BACKEND` and `--no-unique-creator` only, and loads actors without `rewrite_email=False` (`maintenance/deletions.py:79`, `:186`). Acceptable: the commit `922156b` docstring says it runs with `force_email_prop_as_creator` off.

**Tests verified:** `tests/test_deletion_finish.py` covers:
- the resume, the re-call and the index rows after the buckets
- not fetching `_pre_reads` again
- T1's kwargs and `notify_peers`
- T2's live, lapsed, fenced and announce-once cases, and no TTL until finished
- `TestRestamp` and `TestClearOnCreate`

Also verified:
- `tests/test_adoption_tombstoned_vouched.py` (finish, lease, UNKNOWN, R4 for vouched and unvouched, per-request lookup, BL skip)
- `tests/test_session_generation.py` (above)
- `tests/test_deletions_command.py`
- `tests/test_deletion_in_progress_answers.py`
- `tests/integration/test_deletion_resume_http.py` (a DELETE retry, a lease retry, re-sign-up under `unique_creator`, the command against a real store; both backends)

**Planned tests that are missing (not recorded):**
- the resume after a `clear_all_state_for_peer` fault
- `replace_holder` keeping the row, and the `_internal` rollback cases
- over HTTP: the root-`DELETE` hook counts, UNKNOWN, a falsy id and the token revoke
- a reasoned tombstone on an unvouched actor; the flag-off double create
- the callback's state-selected redirect after a finish
- the "`actor_deleted` once" assertions in `tests/test_oauth2_adoption.py:519` and `tests/integration/test_unique_creator_adoption.py:165`
- `delete_client(actor_deleted=True)` touching only the index row
- `DeletionInProgress` at each sign-in entry point
- two concurrent bumps
- `report`'s leftover index rows and the PostgreSQL purge
- a hook creating a trust after the pre-read

BQ is pinned only by a source-text count (`tests/test_oauth2_adoption.py:427`), which the plan's summary records. Medium in total (issue 13).

### Phase 2: Sign-in and adoption - VERIFIED (one stale note)

**Changes verified:**
- E1:
  - `drop_unverified_email` and `verified_email_of` (`oauth2.py:82-110`)
  - `email_is_verified` per provider (`:252`, `:345`, `:426`, `:590`)
  - the module-level GitHub memo (`:77-79`, `:446-464`)
  - every build site (`oauth2.py:921`, `:981`; `oauth2_callback.py:374`, `:1071`, Apple `:908`; `oauth2_spa.py:1416`, `:1511`; `oauth2_server.py:369`)
  - the dead Google validator removed
- BG3 as the owner shrank it: the Confirm page (`oauth_email.py:341-352`) and the POST verify (`:359`); no session, no provider link.
- O2c (`oauth2_callback.py:632`, `:1283`; `oauth2_spa.py:1149`, `:1313`; `oauth_email.py:768`)
- The load rewrite for a vouched actor only (`actor.py:406-414`)
- `row_holds_creator` (BK) at its three sites
- BP, one SPA scan (`oauth2.py:2833-2848`)
- `_pending_adoptions` (`:2569-2653`)
- the `None` summaries (`:2305`, `:2543-2556`, `:2975-2986`)

**Deviation note that is now stale:** Phase 2's notes still say "`email_verification_required` gains `provider` and `provider_account`". Phase 4 removed those kwargs, and the hook call at `oauth_email.py:920-926` passes `email`, `verification_url` and `token` only. The Decisions section (BG3 point 5) is correct. Low (issue 15).

**Missing planned tests:**
- the bearer-authentication case on its own
- the clean's `resets["email"]`
- `oauth_success` receiving `unverified_email`
- the E1 WARNING
- two concurrent confirms
- `purge_relationships` counted reads
- the HTTP-level E1/BG3 tests (recorded as not done)

Low.

### Phase 3: Fault contract and subscriptions - ISSUES FOUND

**Changes verified:**
- the revocation runs before `store_permissions` (`callbacks.py:264-274`) and lists strictly (`:1092`)
- `clear_all_state_for_peer` reads strictly (`callback_processor.py:770`)
- `register_diffs` reads strictly (`actor.py:3856`) and the wrappers re-raise (`property_store.py:82-83`, `:104`, `:341`)
- `is_suspended()` raises on both backends (`actor.py:2930-2956`, `db/dynamodb/subscription_suspension.py:56-68`, `db/postgresql/subscription_suspension.py:43-45`)
- the DynamoDB `modify` is an `UpdateItem` (`db/dynamodb/subscription.py:109-140`)
- the resync record (`actor.py:3050-3078`, `:3173-3220`)
- the per-process breaker comments (`fanout.py:6`, `:206`)

**Deviation that does not hold:** the Phase 3 note says "a non-`DbError` failure deleting revoked data now propagates too". The inner `except Exception: ... raise` at `callbacks.py:1105-1113` re-raises, but the outer `except Exception as e: logger.error(...)` at `:1125-1126` swallows it, so the permissions are stored anyway (issue 4).

**Missing planned tests:**
- a PostgreSQL `DbSubscription.modify` twin (planned under `tests/integration/`)
- the trust deletion answering 503 after `clear_all_state_for_peer` raises
- the handler-level `PUT` answering 503
- the resync `DbError`-subscriber variant and "after the marker is gone"
- the `resync_pending` write fault
- the permission retry after a partial delete

Low to medium.

### Phase 4: Docs, changelog, migration guide, todos - VERIFIED

- The docs build is clean.
- The four todos are deleted with their `INDEX.md` rows: `adoption-fault-and-hygiene-followups.md`, `resumable-actor-deletion.md`, `oauth-email-verified-claim-unchecked.md` and `email-form-user-sign-in-after-verification.md`. `grep` finds no row left in `thoughts/todo/INDEX.md`.
- The plan named no deferral that needs a todo; the not-taken items are owner decisions recorded in the plan.
- Changelog exactness: the ADDED entry for the sign-in code says "a browser page is bound to its browser by a cookie". As built, that is not true (issues 1 and 2) and must be corrected with the fix.

### Iterations entry 1 (emailed sign-in code) - ISSUES FOUND

Issues 1, 2, 3, 7, 8, 9 and 10 are in this entry's code. It is the newest code and has had one review round.

## Remaining Tasks

These are for `/iterate_plan` on this plan. Per the owner's rule, they are not filed as todos.

- [ ] Issues 1–5 before the PR (high).
- [ ] Issues 6–12 (medium): fix, or accept with a line in the plan.
- [ ] Issues 13–17 (low).
- [ ] Re-run `/verify_implementation` afterwards.

## Issues Found

### 1. The sign-in code binding is bypassed by a challenge created over JSON (login CSRF)
**Severity:** High
**Found by:** security review, codex and Claude outside voice, code review
**Description:** `_offer_sign_in_code` stores no binding when the request that creates the challenge is JSON, and `redeem` treats a missing binding as satisfied. The redemption decides separately, from its own request, whether to set the `oauth_token` cookie. An attacker asks for a challenge for their own verified address with `Accept: application/json`, reads the code in their own mailbox, and has a victim's browser auto-submit `code_challenge` and `code` cross-site as a form. The victim's browser is then signed in to the attacker's actor. A top-level navigation response stores the Lax cookie.
**Location:** `actingweb/handlers/oauth_email.py:211` (`binding = None if self._wants_json() else secrets.token_urlsafe(24)`), `actingweb/email_sign_in.py:187` (`bound_ok = not expected_binding or (`), `actingweb/handlers/oauth_email.py:278-279`, `:314-323`
**Recommendation:** record how a challenge was created, and have a cookie-issuing (non-JSON) redemption refuse a challenge that has no binding. Add a test: a JSON-created challenge redeemed through the form answers 401 and sets no cookie. Fix the changelog sentence with it. Name the cookie `__Host-aw_sign_in_binding` with `path=/` (outside voice, low) so a sibling subdomain cannot plant it.

### 2. The binding cookie never reaches the browser, so a legitimate web code sign-in always fails
**Severity:** High
**Found by:** security review; confirmed by reading both integrations
**Description:** `_offer_sign_in_code` sets the binding cookie on `webobj.response`. The Flask and FastAPI `/oauth/email` handlers render the code page as a fresh `Response(render_template(...))` / `TemplateResponse(...)` (or the `code_page_html` fallback) and do not copy `webobj.response.cookies` onto it. The redemption then reads no cookie, and the stored binding refuses it with 401. The handler-level test checks `webobj.response.cookies` (`tests/test_email_sign_in_code.py:194`) and cannot see this. As built, the web flow works only for an unbound challenge, which is issue 1.
**Location:** `actingweb/interface/integrations/flask_integration.py:1199-1222`, `actingweb/interface/integrations/fastapi_integration.py:2037-2057`
**Recommendation:** copy the handler's cookies onto every rendered `/oauth/email` response. Add an integration test through the Flask and FastAPI test clients: offer, then redeem in the same client, ends signed in; a different client gets 401.

### 3. The hourly cap and the single live challenge do not hold under concurrent starts
**Severity:** High
**Found by:** codex and Claude outside voice, code review
**Description:** `start_challenge` reads the meta row, deletes `current`, creates the challenge, and then writes the meta row back with an unconditional `set_attr` whose result is ignored. N concurrent provider sessions that each type the victim's address all read `count=0` and each create a live challenge with five tries. Only the last is recorded as `current`, so the others stay redeemable. The cap on guesses at a code the attacker never sees is then 5×N per burst, not 5 per challenge with at most 5 an hour. A failed meta write leaves `current` unrecorded too.
**Location:** `actingweb/email_sign_in.py:99-139`
**Recommendation:** claim the meta row with `create_attr_if_absent` / `conditional_update_attr` on the row as read, retry a lost race, and refuse when the write cannot land. Consider capping tries per actor per hour as well. Add a test with two concurrent starts.

### 4. A non-`DbError` failure deleting revoked peer data is still swallowed, and the permissions are stored
**Severity:** High
**Found by:** code review; contradicts the Phase 3 note
**Description:** the inner handler re-raises every exception, but the outer `except Exception as e: logger.error(f"Error during revoked peer data deletion: {e}")` folds anything that is not a `DbError`. The callback then continues to `store_permissions`, and the retry no longer sees the revocation. This is the outcome the reorder was meant to prevent, and the plan records it as fixed.
**Location:** `actingweb/handlers/callbacks.py:1125-1126`
**Recommendation:** re-raise there (or drop the outer fold) and test it with a list delete that raises `ValueError`.

### 5. A programmatic `Actor.delete()` leaves a tombstone that never expires
**Severity:** High
**Found by:** code review; confirmed
**Description:** with no tombstone, `restamp` writes a resumable one (`reason="deleted"`, `hook_fired=True`). A reasoned tombstone is written with no TTL (`deletion.py:162`), and only `finish_deletion` and the operator command call `mark_finished`. Every `ActorInterface.delete()`, `Actor.create(delete=True)` victim and application `Actor.delete()` therefore leaves a permanent row in the tombstone bucket, with no `finished_at`. `actingweb-deletions report` lists it as `unfinished` and exits 1 until someone runs `resume --apply`. This is a new storage leak and a noisy operator command.
**Location:** `actingweb/deletion.py:484-491`, `actingweb/actor.py:1133-1138`
**Recommendation:** have `Actor.delete` call `mark_finished` (or set the TTL) once its row delete is confirmed, when it wrote the tombstone itself or the tombstone is not leased. Test that a programmatic delete leaves a tombstone with a TTL that `report` does not list.

### 6. Credentials issued between the generation bump and the end of the clean carry the new generation
**Severity:** Medium (plausible)
**Found by:** Claude outside voice
**Description:** the clean bumps before its revokes, and the client ids are read before the bump (`oauth2.py:2777`). An authorization code or client registration created during the clean is stamped with the new generation and passes `guard` later. The revokes touch only the token and refresh buckets (`token_manager.py:1625-1627`), not authorization codes. Exploiting it needs the previous holder to complete an authorize or register step inside the clean's window.
**Location:** `actingweb/oauth2.py:2967`, `actingweb/oauth2_server/token_manager.py:133`
**Recommendation:** bump again after the second revoke, or delete the actor's codes and re-list the clients after the purge; or accept it and state the window in the changelog's R3 entry.

### 7. The 120 s deletion lease is not renewed during `Actor.delete`'s peer notifications
**Severity:** Medium
**Found by:** outside voice, code review
**Description:** the lease is last renewed before `actor.delete(...)`, which sends one synchronous peer DELETE per trust (each request can take up to 5 s to connect and 20 s to read, `aw_proxy.py:36`). An actor with many or slow peers outlives the lease. A `DELETE` retry, which the 503's `Retry-After` invites, then takes the lease over and runs a second wipe alongside the first, and peers get duplicate DELETEs.
**Location:** `actingweb/deletion_finish.py:143`, `:150`; `actingweb/constants.py:252`
**Recommendation:** renew and fence the lease between `Actor.delete`'s steps (a callback or a hook point), or size the lease from the trust count; or document the limit beside `DELETION_LEASE`.

### 8. A resync record from an earlier resume blocks a later suspension's resume
**Severity:** Medium
**Found by:** code review; confirmed
**Description:** when `_resync_pending` holds a record, `resume_subscriptions` re-sends to those subscribers and returns before `db.resume()`. A suspension written after the earlier partial resume (a second bulk import) is never removed by this call, so its subscribers get no resync and diffs stay suppressed.
**Location:** `actingweb/actor.py:3050-3060`
**Recommendation:** handle the pending record and then fall through to `db.resume()` (combining both resync sets); test suspend → partial resume → suspend → resume.

### 9. Anyone can lock a verified user out of code sign-in and void their live code
**Severity:** Medium
**Found by:** Claude outside voice
**Description:** the cap and the single-live rule are keyed only on the target actor. Five submissions of the victim's address (each from an attacker provider session) answer the real user 429 for an hour, and each deletes the challenge the user is typing.
**Location:** `actingweb/email_sign_in.py:105-110`
**Recommendation:** decide with the owner; fold it into issue 3's redesign (for example, scope the replacement to the binding or requester), or accept and document it.

### 10. Wrong-code and over-long input answers in the browser
**Severity:** Medium
**Found by:** browser QA
**Description:**
- A wrong or empty sign-in code answers 401 with an empty HTML body, so the user sees a blank page.
- A `verify` or `code_challenge` longer than about 1,005 characters answers 500 "The request could not be stored", as JSON, to a browser. The attribute key is too long for the store.
- `?verify=` with an empty value shows the email form with "Missing session parameter" (low).
**Location:** `actingweb/handlers/oauth_email.py:282`, `:285` (`error_response(401, ...)` on the HTML path); the token lookups in `_handle_email_verification` and `email_sign_in.redeem`
**Recommendation:**
- Render the code page again with the error, for HTML.
- Reject a token or challenge longer than the generated length (both are `token_urlsafe` values of fixed size) as invalid before any store access.
- Treat an empty `verify` as an invalid link.

### 11. When `mark_finished` faults, the tombstone stays unfinished, and `resume` prints "finished" anyway
**Severity:** Medium
**Found by:** codex
**Description:** `mark_finished` folds a fault and answers True (announce), and the operator command ignores its result. The tombstone then has no TTL and comes back as `unfinished` in every report. Nothing announces twice.
**Location:** `actingweb/deletion.py:565-570`, `actingweb/maintenance/deletions.py:184`
**Recommendation:** check the result in `_finish_one`, and log the tombstone as left unfinished on the request path.

### 12. A pending-adoption record leaks after a hand-off ends "cleaned"
**Severity:** Medium (plausible)
**Found by:** code review
**Description:** the non-enforced replacement writes a `_pending_adoptions` record. When it hands off to the owner's unvouched actor and the inner `_adopt_actor` ends in `mode == "cleaned"`, the record is cleared only for `"replaced"`. Within its seven-day TTL, a later create for that creator fires a spurious `actor_adopted` naming the long-gone squatter.
**Location:** `actingweb/oauth2.py:2834`, `:2921`, `:3104`
**Recommendation:** clear the record on every successful completion of the outer adoption; test the hand-off-then-clean path.

### 13. Planned tests missing from Phases 1–3
**Severity:** Medium
**Description:** see each phase's list above. Most important:
- the end-to-end binding test (issues 1 and 2)
- the PostgreSQL `modify` twin
- `DeletionInProgress` at each sign-in entry point
- `delete_client(actor_deleted=True)`
- the root-`DELETE` hook counts over HTTP
- a behavioural BQ test in place of the source-text count
**Recommendation:** add them with the fixes, or record in the plan which ones are dropped and why.

### 14. A K4 create-rollback item is only partly implemented
**Severity:** Low
**Description:** the marker rollback does not delete a generated id's `_internal` bucket; only the `trustee_root` rollback does. The fixed-id "only if this create wrote it" rule has no code.
**Location:** `actingweb/actor.py:847-853`, `:889-894`
**Recommendation:** add the delete to the marker rollback, or record that a lost marker leaves no `_internal` worth removing.

### 15. Stale notes in the plan
**Severity:** Low
**Description:**
- Phase 2's notes still say `email_verification_required` gains `provider` and `provider_account`. Phase 4 removed them.
- Phase 3's note claims a non-`DbError` revocation failure propagates (issue 4).
- Phase 1 names functions that do not exist (`mark_hook_fired`, `renew_lease`, `set_tombstone_ttl`).
**Location:** `thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md:307`, `:361`, `:144-148`
**Recommendation:** correct them in the iteration that fixes issue 4.

### 16. A legacy tombstone suppresses `actor_deleted` on a genuine first `DELETE`
**Severity:** Low
**Found by:** code review
**Description:** `finish_deletion` counts a reason-less tombstone as `hook_fired` (a recorded deviation). A live actor that carries a stray legacy tombstone, such as one left by a pre-3.16 create whose clear faulted, then loses the application's `actor_deleted` cleanup when its user really sends `DELETE`.
**Location:** `actingweb/deletion_finish.py:125-129`
**Recommendation:** on `origin="delete"`, fire `actor_deleted` for a legacy tombstone, or accept it and say so in the migration guide's "Stalled deletions".

### 17. Smaller robustness and efficiency items
**Severity:** Low
**Description:**
- `report` lists expired legacy rows that `read_tombstone` hides (`maintenance/deletions.py:136-139`).
- DynamoDB's `conditional_update_attr` and `delete_attr_conditional` fold faults without a log line (`db/dynamodb/attribute.py`), so a throttled code consume reads as a wrong code.
- A failed revoke after a generation mismatch skips the remaining revokes (`session_generation.py:143-145`).
- A code redemption signs in to an actor whose deletion is stalled, with no deletion-status read (`oauth_email.py:283`).
- `get_from_creator` reads the single-match row twice (`actor.py:547`).
- `finish_deletion` re-reads `client_ids` that its caller just passed (`deletion_finish.py:109`).
**Recommendation:** fix with the batch, or accept each one in the plan.

## Overall Assessment

The four phases landed as planned or as the owner changed them. The Full tier is green on both backends (DynamoDB 5,466, PostgreSQL 5,273) and the docs build is clean. Resumable deletion, the lease, the session generation, E1 and the fault-contract changes are in place, and the security properties they claim are pinned by tests: E1's strip, R3's straddle and stamped grants, and the bridge refusal. The todos the plan said it would close are gone.

It is not ready for a PR. The newest code, the emailed sign-in code (Iterations entry 1), is not safe as built:
- its binding against login CSRF is bypassed by a JSON-created challenge (issue 1);
- the binding cookie never reaches a real browser, so the legitimate web flow always fails (issue 2);
- its cap does not hold under concurrency (issue 3);
- its ADDED changelog entry states a guarantee the code does not give.

Two Phase 1 and Phase 3 defects also need fixing first: the revocation fold the plan records as fixed (issue 4) and the permanent tombstone a programmatic delete leaves (issue 5). The browser walk covered only the provider-free pages; the code offer page was not loaded in a browser. Next: `/iterate_plan` on issues 1–5 (and the medium items the owner wants), then verify again.
