# Verification: 3.16 adoption, deletion and fault-contract follow-ups (third run)

**Date:** 2026-11-03
**Plan:** thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md
**Research:** the todos named in the plan's **Research:** line (deleted; no research document)
**Branch:** `release/3.16.0-adoption-fault-followups`
**Commit:** `04332d0` plus the uncommitted working tree (Iterations entries 16–28)

This is the third run. It checks Iterations entries 16–28 against the issues
in the second run (N1–N14, B1, B2). The target is the uncommitted diff
against `04332d0` and the untracked `tests/test_refresh_cookie_path.py`.
There is no feature document, so there are no success measures, and the
plan has no consumer message to re-check.

## Automated Check Results

The Full tier from `CLAUDE.md` ran on the working tree, unsandboxed, one test
run at a time.

- **ruff check:** pass ("All checks passed!")
- **ruff format --check:** pass (509 files already formatted)
- **pyright:** pass (0 errors, 0 warnings, 0 informations)
- **verify_groups.py:** pass (all 53 groups documented)
- **DynamoDB, `make test-all-parallel`:** pass. 5,520 passed, 59 skipped, 1 xfailed, 9 subtests passed, 51.4 s. Nothing failed, so no sequential re-run was needed.
- **PostgreSQL, `make test-all-parallel`:** pass. 5,330 passed, 249 skipped, 1 xfailed, 9 subtests passed, 46.1 s.
- **sphinx-build -W:** pass (rc=0)
- **Benchmarks (DynamoDB, sequential, `tests/performance -m benchmark`):** 23 passed. They ran because entry 25 touched the attribute layer, although no benchmark exercises `conditional_update_attr`. Means:
  - attribute write 0.80 ms, attribute read 0.82 ms;
  - property write 1.05 ms, property read 0.73 ms;
  - actor delete 3.6 ms;
  - spanned list `to_list` 29.8 ms;
  - bulk property write 79.7 ms.
- **Browser QA:** ran with gstack browse (headless Chromium) against the demo in local QA mode on `localhost:5055` (fresh `AWS_DB_PREFIX=qa31857`; no actor was created). Screenshots are in `/tmp/qa-3-16-adoption-reverify2/`.
  - **Passed:**
    - A malformed `code_challenge` (non-ASCII `ü✓`, `<script>`, 10,000 characters) answers 401 with the error page, the message and a Continue link to `/`; it is no longer an empty page (B1). Continue lands on the demo's root with a clean console.
    - JSON clients (`Accept: application/json` or `format=json`) get the JSON 401 body.
    - Nothing is echoed back.
    - The pages fit at 375 px.
  - **Not a finding (F-001):** the agent's report of "unknown challenge gives the error page" came from my brief, whose example id was 14 characters, so the handler correctly treated it as malformed. Re-checked with a 32-character unknown id (`curl -H 'Accept: text/html'`, `code_challenge=abcdefghijABCDEFGHIJ0123456789_-`): 401, `<title>Enter your sign-in code - ActingWeb`, `<h1>Enter your sign-in code</h1>`, the error, and `<a href="/">No code, or it expired? Start over</a>` (B2 and entry 21).
  - **Low (F-002, older than this diff):** an expired or bogus email-form `session` answers 400 and redraws the address form with the dead session in a hidden field. Its only button resubmits that session, so the user loops. See V7.
  - The offer page itself (needs a claimed provider session) was again not loaded in a browser. OAuth is off in QA mode.
- **Second opinion (outside voice):** codex (`codex exec -s read-only`, unsandboxed, completed), then a fresh-context Claude, on the working-tree diff. 8 findings and 2 unverified notes. I checked each one against the code; they are folded in below.
- **Built-in code review (high), working-tree diff:** 10 candidates.
  - Confirmed: 7 (V1, V2, V4, V6, V8, V9, and the hygiene notes).
  - Refuted: 1 (the stale legacy refresh cookie, see below).
  - Kept as a note: 1 (the CAS mismatch).
- **Built-in security review:** nothing at confidence 8 or higher. It traced 16 candidates and rejected them, among them binding reuse. Its reason for that one was that "a cross-site POST never sends" the Strict cookie. That holds for cross-site requests but not for a same-site sibling subdomain, which V1 covers.

## Security properties the plan claims

- **The login-CSRF binding: only partly holds now (V1).**
  - What holds:
    - `tests/test_email_sign_in_code.py:477` `TestOneBindingPerBrowser`: a second offer in the same browser reuses the held binding, so the first code still redeems, and a cross-site offer sets no cookie.
    - The earlier cross-browser tests still pass. `:424` `test_another_browser_gets_401_and_the_code_page_again` asserts 401, the code page and the Start over link.
  - What does not hold: the changelog's "A request another site started gets no binding cookie, so its challenge can never sign a browser in" is not exactly true. A request from a sibling subdomain is same-site, so the browser sends the Strict cookie. When the browser already holds a binding, the offer binds to it without the cross-site check (V1).
- **A fault is never answered as a wrong code: holds.**
  - `:54` `test_an_attempt_that_cannot_be_counted_is_a_fault` and `:70` `test_a_consume_the_store_did_not_confirm_is_a_fault` both expect `DbError`.
  - `:214` `test_a_token_store_fault_answers_503_not_500` expects 503.
  - The outside voice asked whether a store fault inside `may_sign_in` reads as a wrong code. It does not: `Actor` loads strictly (`actingweb/actor.py:389` `self.actor = self.handle.get(actor_id=actor_id)`; PostgreSQL `actingweb/db/postgresql/actor.py:86-88` raises `DbError` when `strict`).
- **A correct code for a renamed or deleted actor signs nothing in: holds.** `:198` `test_a_renamed_actor_is_not_signed_in_and_the_code_stays` and `:84` `test_a_refused_check_does_not_spend_the_code`. The refusal still counts a try (V9).
- **R3 on the SDK path: holds.** `tests/test_session_generation.py:160` `TestClientManagerToken`:
  - `:165` a client registered after the clean gets a token;
  - `:180` a refresh token from before the clean mints nothing;
  - `:198` one from after the clean works.
- **One refresh cookie path: holds.**
  - `tests/test_refresh_cookie_path.py:33` asserts one live cookie on `/` and the legacy path expired (`max_age == -1`).
  - `:45` asserts FastAPI's `_apply_cookies` keeps both paths.
  - `:63` is a source check that both callback sites use the helper.
  - The code review claimed that a browser holding both cookies keeps sending the stale one. That is refuted: both integrations parse the raw `Cookie` header into a dict, so the last value wins (`actingweb/interface/integrations/flask_integration.py:647-653`, `fastapi_integration.py:1383-1385`). Browsers send the longer path first, so the `/` cookie is the one the grant reads, and its rotation expires the legacy one.

## Phase Verification

### Iterations entries 16–28 - ISSUES FOUND

**Changes verified** (each against the second run's issue):

- **16, N1:** `actingweb/interface/oauth_client_manager.py`, `generate_access_token` passes `client_generation=client_data.get("session_generation")`. Matches.
- **17, N2 and the N14 rename:**
  - `actingweb/handlers/oauth_email.py:329-340`: the `may_sign_in` closure checks that the actor exists, has no tombstone (`_deletion_blocks_sign_in`) and that its creator equals the normalised address.
  - `actingweb/email_sign_in.py:315-318` runs it before the consume.
  - Matches. The docstring wording is in V9.
- **18, N8:** `email_sign_in.py:283-292` raises when the row is unchanged after a count that did not land, and `:322-330` after a consume that did not land. Matches.
- **19, N4:** `oauth_email.py:244-251` reuses a held binding, and a fresh binding is set only when the offer is not cross-site. The reuse branch has no cross-site check (V1).
- **20, mailer failure:**
  - `email_sign_in.py:361-380` (`send_code`).
  - `oauth_email.py:262-279`: withdraw and 503.
  - Matches. Two edges are open: V3, and a binding set only after a send.
- **21, B1/B2/invalid link:**
  - `_sign_in_code_refused` at `oauth_email.py:411-432`.
  - `redirect_url` at `:171`.
  - Template heading and Start over link at `actingweb/templates/aw-oauth-email.html:18`.
  - Matches. The links hardcode `/` (V6).
- **22, N3:** `actingweb/handlers/oauth2_spa.py:240` `set_refresh_cookie`, and both callback sites. Matches.
- **23, N5/N12:**
  - `actingweb/deletion.py` `mark_finished` respects a live lease.
  - `actingweb/maintenance/deletions.py:230` reports `DeletionInProgress` only when `not holds_lease`.
  - Matches. The `holds_lease=True` edge is V8.
- **24, N6:** `actingweb/deletion_finish.py:171` creates the keeper at the renewal, and `:175` calls it after the token sweep. Matches. V10 remains.
- **25, N7:**
  - `clear_ttl` on both backends: DynamoDB `ttl_timestamp.remove()`, PostgreSQL `", ttl_timestamp = NULL"` (a constant, no interpolation), and the protocol.
  - `deletion_finish.py:138-153`.
  - Matches. The call shape is V4.
- **26, N11:** `actingweb/oauth2.py:2620` `if not is_vouched_actor(created): return`. It fixes N11 but loses an announcement (V2).
- **27, N13:** `deletion_finish.py:138-153` records reason, peers, kwargs and client ids on every origin. Matches.
- **28, docs:**
  - `CHANGELOG.rst`: the Breaking `clear_ttl` entry, the refresh-cookie path entry, the email pages' statuses, the rewritten sign-in code entry, and the creator rewrite's Behavior change.
  - `docs/reference/hooks-reference.rst:467` ("Raise to report a failed send").
  - `docs/guides/database-maintenance.rst`.
  - The changelog's sign-in code entry is not exact in two places (V1, V9).

**Tests verified:** all named in the plan's entries exist and pass on both
backends. The second run's weakness is fixed: the concurrency test now also
asserts that at least one start succeeds.

**Deviations from plan:** none beyond the findings below. The plan's earlier
loose end ("the hook raise answers 409") was wrong, as entry 20 records.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-03-3-16-adoption-fault-followups-reverify.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| N1 `generate_access_token` mints nothing after a clean | Fixed | entry 16; `tests/test_session_generation.py:160` |
| N2 code spent before the session; token-store fault 500 | Fixed | entry 17; `tests/test_email_sign_in_code.py:84`, `:214` |
| N3 FastAPI scopes the hybrid refresh cookie to `/oauth/spa/token` | Fixed | entry 22; `tests/test_refresh_cookie_path.py` |
| N4 one binding per browser voids the first code | Fixed, with a new gap | entry 19; `TestOneBindingPerBrowser`; V1 |
| N5 `finish_unleased` marks under a fresh lease | Fixed | entry 23; `tests/test_deletions_command.py:194` |
| N6 keeper clock starts after the sweeps | Fixed (the clock); V10 remains | entry 24; `tests/test_deletion_finish.py:528` |
| N7 legacy tombstone keeps its retention TTL | Fixed | entry 25; `tests/test_deletion_finish.py:625`, `TestClearTtl` `:646` |
| N8 store fault read as a wrong code | Fixed | entry 18; `tests/test_email_sign_in_code.py:54`, `:70` |
| N9 changelog: error pages' real status | Fixed | entry 28; `CHANGELOG.rst:797` |
| N10 permanent non-DB revocation failure blocks callbacks | Accepted as-is | entry 28 (fail closed) |
| N11 pending adoption announced on an unvouched create | Fixed, with a regression | entry 26; `tests/test_adoption_summary_and_handoff.py:164`; V2 |
| N12 resume reports a deletion in progress as failed | Fixed (unleased branch); V8 for the leased branch | entry 23; `tests/test_deletions_command.py:214` |
| N13 operator resume of a legacy tombstone keeps no record | Fixed | entry 27; `tests/test_deletion_finish.py:602` |
| N14 smaller items | Fixed or accepted | entries 17, 28 (the spent code on an exchange 503 is accepted) |
| B1 malformed challenge: empty 401 page | Fixed | browser walk above |
| B2 heading always "Enter your email" | Fixed | curl and template above |
| Loose end: the `Secure` binding cookie over HTTP | Accepted as-is | entry 28 |

## Remaining Tasks

These are verification findings for this plan, fixed inside it through
`/iterate_plan` (project rule: never filed as todos):

- [ ] V1: refuse or isolate a cross-site offer before `start_challenge` (this also fixes V5)
- [ ] V2: announce the pending adoption before a replacement or clean overwrites or clears it
- [ ] V3: keep the hourly slot when a hook raised; keep a code another handler already sent
- [ ] V4: pass `clear_ttl` only when it is true
- [ ] V6: Start over link from the app's root
- [ ] V7: an expired email-form session answers the error page with Continue
- [ ] V8: `_confirm_finished(holds_lease=True)` and a foreign lease
- [ ] V9: docstring and changelog wording on the try a refusal spends
- [ ] V10: lease keeper between the client sweep and `actor.delete`

## Issues Found

### V1. A held binding is reused for a cross-site offer, so a sibling subdomain can bind its challenge to the victim's browser
**Severity:** Medium
**Description:** The cross-site check applies only when a fresh binding is made.
- `actingweb/handlers/oauth_email.py:246-248`:
  ```python
  if held and email_sign_in.is_binding(held):
      binding = held
      set_binding = True
  ```
- `:251`: `set_binding = not self._cross_site_refused()` is in the `else` branch only.

A sibling subdomain is same-site, so the browser sends `SameSite=Strict` cookies on its requests, and `cross_site()` calls it cross-site only by its `Origin`. The redemption has no cross-site check. The attack:
1. A victim has had a code offer in the last 10 minutes (`max_age=CODE_TTL`), so the browser holds the binding.
2. The sibling page auto-posts the attacker's own session and address. The challenge binds to the victim's binding, and the cookie is set again.
3. The attacker reads the code from their own mailbox and auto-posts the redemption.

The victim's browser is then signed in to the attacker's actor (login CSRF). Elsewhere the changelog treats a sibling subdomain as another site (`CHANGELOG.rst:224`), and the sign-in code entry promises that "a request another site started gets no binding cookie, so its challenge can never sign a browser in" (`CHANGELOG.rst:1369`).
**Location:** `actingweb/handlers/oauth_email.py:244-251`
**Recommendation:** Decide the cross-site question first. Either refuse a cross-site offer before `start_challenge` (403, or the 409 page, which also fixes V5), or give it a fresh binding that is never sent whether or not one is held. Test: a held binding plus `Sec-Fetch-Site: same-site` yields a challenge that the held binding cannot redeem.

### V2. Skipping the pending-adoption announcement for an unvouched create loses the earlier replacement's `actor_adopted`
**Severity:** Medium (a lifecycle event the app relies on is lost with no error)
**Description:** `actingweb/oauth2.py:2620` reads `if not is_vouched_actor(created): return`. The pending record waits, as N11 intended. But nothing announces it later when the actor the email form created (U) is resolved by a vouched sign-in:
- **U is replaced:** `oauth2.py:2838` `_record_pending_adoption(config, creator, actor_id, existing)` overwrites the record with U's id, and `:3123` `_clear_pending_adoption(config, existing.creator or "")` removes it. The original victim X is never reported.
- **U is cleaned in place:** nothing reads the record, and it expires after `PENDING_ADOPTION_TTL`.

The sequence: a sign-in replaces X and its successor's create raises; the owner then signs up through the email form; a later provider sign-in resolves to U.
**Location:** `actingweb/oauth2.py:2620`, `:2838`, `:3123`
**Recommendation:** Before a replacement rewrites the record, and on the cleaned branch, announce a pending record that names another actor, with the same claimed conditional update `_announce_pending_adoption` uses. Test the sequence above: `actor_adopted` fires once with X's id.

### V3. A hook that raises after the mail left gives the hourly slot back; a later handler's `DbError` withdraws a code already sent
**Severity:** Medium
**Description:** `actingweb/email_sign_in.py:376-379` reads `except DbError: raise` / `except Exception as e:  # folds DbError: re-raised above; a mailer that failed`. `actingweb/handlers/oauth_email.py:276` then calls `email_sign_in.cancel_challenge(...)`, which decrements the window count. Two cases go wrong:
- **A hook that raises after the send** (an SMTP `quit()` error, or a bookkeeping write after the send): every request mails a real code, withdraws it and gives the slot back. Anyone who types an address can mail its owner without the five-per-hour limit, and each code is already dead.
- **Several handlers:** a `DbError` from a later handler, after an earlier one sent the code, cancels a code the user has.

The hooks reference does tell handlers to raise only on a failed send (`docs/reference/hooks-reference.rst:467`), but nothing enforces it.
**Location:** `actingweb/email_sign_in.py:361-380`, `actingweb/handlers/oauth_email.py:270-279`
**Recommendation:**
- When no handler succeeded, withdraw the challenge but keep the slot.
- Once one handler has sent, log a later handler's failure (including `DbError`) and carry on.
- Test a hook that raises after recording a send: the count stays.

### V4. `update_tombstone` passes `clear_ttl` on every write, so a backend without the keyword fails every deletion
**Severity:** Low (documented as **Breaking** in the changelog)
**Description:**
- `actingweb/deletion.py:347` `clear_ttl=clear_ttl,` passes the keyword on every lease claim, renewal, `hook_fired` and `mark_finished` write.
- That contradicts the guard the same diff keeps at `actingweb/attribute.py:435`: `# Only when asked for, so a backend (or test double) written before the keyword existed keeps working`.
- A custom backend that predates the keyword gets a `TypeError` on every deletion, not only on the legacy rewrite.
**Location:** `actingweb/deletion.py:340-348`
**Recommendation:** Pass `**({"clear_ttl": True} if clear_ttl else {})`, so that only the legacy rewrite needs the new keyword. The Breaking entry stays correct.

### V5. A cross-site offer still creates a challenge, mails a dead code and spends a slot
**Severity:** Low
**Description:** `actingweb/handlers/oauth_email.py:251` `set_binding = not self._cross_site_refused()`. The challenge is still created at `:253` and the code mailed, but it can never be redeemed in a browser. The victim gets a code that cannot work, and a slot is gone.
**Location:** `actingweb/handlers/oauth_email.py:249-256`
**Recommendation:** Covered by V1's first option: refuse a cross-site offer before `start_challenge`.

### V6. The "Start over" links hardcode `/`
**Severity:** Low
**Description:** An app mounted under a base path sends the user out of the app, while the new Continue link uses the root:
- `actingweb/templates/aw-oauth-email.html:18`: `<p class="aw-muted"><a href="/">No code, or it expired? Start over</a></p>`.
- `actingweb/handlers/oauth_email.py:67`: `<p><a href="/">No code, or it expired? Start over</a></p>`.
- The Continue link, by contrast: `oauth_email.py:171` `"redirect_url": getattr(self.config, "root", "") or "/"`.
**Location:** as above
**Recommendation:** Pass the root as a template value (`start_over_url`) and use it in both places.

### V7. An expired email-form session redraws the address form with the dead session, so the user loops
**Severity:** Low (older than this diff; browser F-002)
**Description:** A user who leaves the address form open longer than `_SESSION_TTL = 600` (`actingweb/oauth_session.py:36`) gets "Invalid or expired session" (400) from `actingweb/handlers/oauth_email.py:788` and `:827` (`return self.error_response(400, "Invalid or expired session")`). The template redraws the form with the same hidden `session`, so its only button submits the dead session again. Entry 21 gave the verification pages a way out, but not this one.
**Location:** `actingweb/handlers/oauth_email.py:788`, `:827` (and `:668` on GET)
**Recommendation:** For a browser, answer `_verification_error(400, "This sign-in expired; start again")`, whose Continue link goes to the root. Keep `error_response` for JSON.

### V8. With its own lease, `_confirm_finished` reports a lease another finisher took over as a failure
**Severity:** Low
**Description:** `actingweb/maintenance/deletions.py:230` `if remaining > 0 and not holds_lease:` and `:234` `raise DbError("tombstone not marked finished", actor_id)`. When the command's lease lapses during slow peer DELETEs and another finisher takes it, `mark_finished` refuses (wrong `lease_id`) and `finish_deletion` still returns a count. The command then prints an error and exits 2 for a deletion that is in progress.
**Location:** `actingweb/maintenance/deletions.py:226-234`
**Recommendation:** Compare the row's `lease_id` with the one this run held (have `finish_deletion` return it or expose it), and raise `DeletionInProgress` for a foreign live lease.

### V9. A refused `may_sign_in` counts a try; the docstring and changelog say only that it leaves the code unspent
**Severity:** Low
**Description:** The try is counted at `actingweb/email_sign_in.py:272-282` before `may_sign_in` runs at `:315`. That is safe (no oracle, and the refusal reads like a wrong code). But the wording is not exactly true by the changelog's own rule:
- the docstring at `:250-251`: "False refuses without spending the code";
- `CHANGELOG.rst:1375`: "such a refusal leaves the code unspent".

Five correct-code attempts against a renamed actor exhaust the challenge.
**Location:** `actingweb/email_sign_in.py:250-251`, `CHANGELOG.rst:1374-1375`
**Recommendation:** Say "leaves the code unconsumed; the attempt counts as a try" in both places.

### V10. No lease renewal between the client sweep and `actor.delete`
**Severity:** Low
**Description:** The keeper runs between the token sweep and the client sweep, then not until `actor.delete` calls `_between_steps`:
- `actingweb/deletion_finish.py:174-178`: `revoked = _revoke_all_actor_tokens(...)` / `keep_lease()` / `_delete_actor_clients(...)`.
- A single sweep longer than `DELETION_LEASE` (120 s) still lets a second finisher take over beside this one.
**Location:** `actingweb/deletion_finish.py:174-185`
**Recommendation:** Call `keep_lease()` after `_delete_actor_clients` too. Passing it into the sweeps' batch loops is optional.

### Notes (not findings)

- **Unchanged-row CAS mismatch** (`email_sign_in.py:283-290`): the code review's claim that a deterministic mismatch answers 503 for the whole TTL needs a stored row that never compares equal to itself as read. I found no such path. Unverified.
- **Check-then-issue window:** the session is issued after `may_sign_in` without a second tombstone read (`oauth_email.py:347`, `return self._issue_code_session(actor_id, signed_in)`). The window is milliseconds; accept it, or re-read the tombstone right before the token write.
- **Hygiene:**
  - `send_code` and `hook_registered` reach into the registry's private `_lifecycle_hooks` and `_execute_hook_in_sync_context` (`email_sign_in.py:357`, `:369`, `:374`).
  - `is_binding` is the same predicate as `is_challenge_id` (`:345`, `:348`).
  - `cancel_challenge` repeats `_claim_slot`'s read/CAS loop and ignores `window_start` (`:201-220`). A window reset between start and cancel would need the hour to roll over within one request.
- **FastAPI cookie copies:** the callback and SPA routes copy cookies with their own loops, not `_apply_cookies`. Both keep the path (`actingweb/interface/integrations/fastapi_integration.py:2318-2326` and `:2392-2400`, `path=cookie_data.get("path", "/")`). `tests/test_refresh_cookie_path.py:45` exercises only `_apply_cookies`, so these two loops have no direct test.
- **Todos:** this iteration touched nothing under `thoughts/todo/`. No todo the plan said it would close remains, and `INDEX.md` is unchanged since the second run. `logout-mcp-token-with-spa-refresh-cookie.md` is unaffected by N3 (it concerns the MCP logout branch).
- **Refuted:**
  - The stale legacy refresh cookie (see Security properties).
  - Browser F-001 (my brief's id was malformed).
  - A store fault in `may_sign_in` answered as a wrong code (`Actor` reads strictly).
  - The outside voice's "three FastAPI copies" note: two loops plus `_apply_cookies`, all keeping `path` (above).

## Overall Assessment

The fixes for the second run's issues land, and every one has a regression
test that passes on both backends: N1–N9, N11–N13, B1, B2, and the mailer
loose end. The Full tier is green: DynamoDB 5,520 passed, PostgreSQL 5,330.
The UI changes were loaded in a browser, and the code page's new heading and
Start over link were confirmed in the served HTML. The offer page itself
still was not, because OAuth is off in QA mode.

Two of the fixes opened new problems. Entry 19's binding reuse skips the
cross-site check that its own fresh-binding branch has. A same-site sibling
subdomain can therefore bind a challenge to a browser's held binding (V1),
which contradicts the changelog's guarantee. Entry 26's vouched check stops
N11 but can lose the earlier replacement's `actor_adopted` (V2). Entry 20's
slot give-back can be driven past the hourly limit by a hook that raises
after sending (V3). Fix these three before merging. V4–V10 are low and
small, and V7 is older than this diff. As before, the plan stays
`status: done`, its `verified:` link moves to this document, and the
findings go back through `/iterate_plan`.
