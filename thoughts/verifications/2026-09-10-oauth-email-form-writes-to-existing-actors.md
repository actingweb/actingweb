# Verification: 3.14.5 — close the OAuth email form's inputs, fire `actor_created` once, constant-time secret compares

**Date:** 2026-09-10
**Plan:** thoughts/plans/2026-09-10-oauth-email-form-writes-to-existing-actors.md
**Research:** thoughts/research/2026-09-09-oauth-email-form-writes-to-existing-actors.md
**Branch:** fix/3.14.5-oauth-email-form
**Commit:** `8965548` (the release commit `64ac9c0` plus three commits made
during this verification: `4b8cb1b`, `f91640f`, `8965548`)
**PR:** https://github.com/actingweb/actingweb/pull/144

All four phases were read against the tree, not taken from the plan's own
"Implementation Status" notes. Two automated reviews landed on the PR during
this verification and raised eight findings between them; five were real,
four of them fixed on this branch and one declined with reasons. They are described under "Review findings
actioned" and are part of the commits above.

## Automated Check Results

- **Ruff check:** Pass — `All checks passed!`
- **Ruff format:** Pass — `374 files already formatted`
- **Pyright:** Pass — `0 errors, 0 warnings, 0 informations`
- **Pytest, `make test-all-parallel` at `8965548`:** Pass — 3424 passed,
  31 skipped, 0 failed, 2 errors. Both errors are in the two modules the
  plan already documented as pre-existing parallel-isolation flakes
  (`test_hot_path_n_plus_one.py`, `test_bulk_list_update_handles.py`);
  both pass standalone, and CI's own parallel run of the same commit
  reports zero failures and zero flaky retries on both backends.
- **CI at `8965548`, every check green:** `Tests (Python 3.11, dynamodb)`,
  `Tests (Python 3.11, postgresql)`, `type-check`, `Documentation Build`,
  `test-summary`, `Detect changes`, and all four codecov checks. The
  matrix summary reports 0 failed and 0 flaky on both backends.
- **RST parse of every edited document:** clean, apart from the
  pre-existing `Unknown interpreted text role "doc"` diagnostics that
  docutils emits for Sphinx roles outside a Sphinx build.

The plan's Phase 3 note that "no Sphinx build exists in this repo (no
`docs/conf.py` or `docs/Makefile`)" is wrong: `conf.py` and `Makefile` are at
the repository root, and CI runs `sphinx-build -W --keep-going -b html .`
The plan's substituted `docutils` parse check was therefore weaker than the
real build — but the real build ran in CI on this branch and passed, so the
docs are verified green regardless.

## Phase Verification

### Phase 1: Close the email form's inputs — VERIFIED (with three review fixes)

**Changes verified:**

- `actingweb/handlers/oauth_email.py:355` — `email.strip().lower()` runs
  immediately after the `"@"` check and before the verified-list membership
  test. Matches plan.
- `actingweb/handlers/oauth_email.py:405-445` — the free-text branch probes
  `Actor.get_from_creator(email)` and answers 409 `actor_exists` in all
  three response shapes (JSON, UI template, plain). No hook, no store write,
  no token-index row, no mail on that path. Matches plan; the session
  consumption moved earlier, see "Review findings actioned".
- `actingweb/handlers/oauth_email.py:487-560` — tail order is
  `email_verified = "false"` → `oauth_success` → (only if accepted) token,
  index row, mail, cookie. `oauth_valid = bool(result) if result is not None
  else True`, and `False` on hook exception — identical to the callback's own
  block at `oauth2_callback.py:663-687`. Matches plan.
- `actingweb/handlers/oauth_email.py:616` — `httponly=True` on the
  `oauth_token` cookie. Matches plan.
- `actingweb/handlers/oauth_email.py:667-690` — `error_response` writes a
  JSON body and sets CORS headers when `_wants_json()`, and never sets
  `template_values` on that path. `_wants_json()` tests for
  `"application/json" in Accept`, which no browser's default Accept header
  contains, so there is no HTML-client regression. Matches plan.
- `actingweb/handlers/oauth_email.py:61-84` — `_set_cors_headers` now
  consults `spa_cors_origins`; identical behaviour at the `["*"]` default.
  Matches plan.
- `actingweb/oauth_session.py` — `delete_session` and `retrieve_spa_session`
  exist with the specified contracts. Matches plan.
- `actingweb/constants.py:182-187` — `OAUTH_SESSION_RETRIEVE_GRACE = 30`
  with the invariant comment. Matches plan.
- `actingweb/interface/integrations/fastapi_integration.py:2191-2243` —
  `_handle_spa_session_retrieve` calls `retrieve_spa_session`, the false
  "one-time use by design" comment is gone, the 400 branch is retained as a
  documented defensive fallback, and the CORS allowlist is applied. Matches
  plan.
- `actingweb/oauth2.py:169, 333, 1218` —
  `OAuth2Provider.get_verified_emails` (default `[]`),
  `GitHubOAuth2Provider` override, and module-level
  `_get_github_verified_emails` with the `[]`/`None` contract.
  `OAuth2Authenticator.get_github_verified_emails` is a delegating shim.
  Matches plan.
- `actingweb/handlers/oauth2_callback.py:405` and `:1095` — both
  branches call `provider.get_verified_emails(...)` and answer 502 (web) /
  `identifier_failed` (SPA) on `None`. `502` was added to the templated
  status list at `:897`. Matches plan.
- `actingweb/oauth2.py:1500` — `clear_pending_email_verification`, no-op
  unless `email_verified == "false"`, deletes the index row and clears all
  three fields. Wired at exactly the four sites the plan names:
  `oauth2.py:982`, `oauth2_spa.py:881` and `:1039`,
  `oauth2_server/oauth2_server.py:734`. Matches plan.
- Legacy handler removed: `actingweb/handlers/email_verification.py` is
  deleted, both Flask and FastAPI registrations and handler methods are gone,
  `tests/integration/templates/aw-verify-email.html` is deleted, and
  `TestEmailVerificationHandlerJSON` is removed from
  `tests/test_spa_api_endpoints.py`. A repo-wide grep for
  `EmailVerificationHandler|www/verify_email|aw-verify-email|handlers\.email_verification`
  returns only the new regression test and historical `CHANGELOG.rst`
  entries. Matches plan — **but that grep searches file contents, and the
  package's own `actingweb/templates/aw-verify-email.html` survived it,
  because its filename appears in no file. It is not dead: see finding B.**

**Tests verified:** `tests/test_oauth_email_handler.py` (15 tests) covers
mixed-case membership, the 409 refusal with session consumption and zero
hooks, the dropdown returning-user 200, `oauth_success` firing with session
data, `email_verified == "false"` visible during the hook, a rejected hook's
403 with no `Attributes` construction, the HttpOnly cookie, the
JSON-vs-template error shape, and the CORS allowlist. Assertions are
specific and would fail if the behaviour regressed.
`tests/test_oauth2_provider_verified_emails.py` (12) covers the full status
and exception matrix. `tests/test_oauth2_callback_email_required.py` (6)
covers both branches' `None`/`[]`/list handling including the Google no-502
case. `tests/test_oauth2_clear_pending_verification.py` (5) covers the
helper and its wiring. `tests/test_email_verification_legacy_route.py` (9, rewritten here — see
issue 7) covers the route table, the real per-integration status codes,
`ModuleNotFoundError`, and the result-vs-form rendering on both
integrations. `tests/test_oauth_email_verify_link.py` (9, added here) covers
the surviving verify link at the handler level.

**Deviations from plan:**

- The plan named seven new test files for this phase; six were written, plus
  a seventh (`test_oauth_email_verify_link.py`) added during this
  verification. The substance the plan enumerated is covered (see "Issues
  Found" for the two enumerated cases that are not).
- `tests/test_oauth_session.py` is an in-memory `MockDbAttribute` harness,
  not DynamoDB-Local-backed. The plan's own note corrects this. Acceptable.

### Phase 2: `actor_created` fires once, in core — VERIFIED

**Changes verified:**

- `actingweb/oauth2.py:934-993` — `hooks=` is keyword-only with a
  `config._hooks` fallback on both `lookup_or_create_actor_by_email` and
  `lookup_or_create_actor_by_identifier`; `effective_hooks` reaches
  `ActorInterface.create`. Additive. Matches plan.
- `actingweb/oauth_session.py` — `hooks=` forwarded through the completion
  path. Matches plan.
- All four handler-level `actor_created` blocks are deleted
  (`oauth_email.py`, `oauth2_callback.py:658`, `oauth2_spa.py:903` and
  `:1061`), each replaced by a comment naming the single core site. The
  callback's now-dead `get_from_creator` pre-check at the old `:536-540` is
  deleted too, dropping existing-actor web logins from two creator lookups to
  one. The two SPA if/else pre-checks are kept, as the plan required.
- `grep -rn "actor_created" actingweb/handlers/` returns only comments. The
  sole `execute_lifecycle_hooks("actor_created", ...)` call in the library is
  `actingweb/actor.py:427`, inside `Actor.create()`. Matches plan.

**Tests verified:** `tests/test_actor_created_fires_once.py` — the three
`TestCoreFiringSite` tests run against real DynamoDB-Local actor creation and
pin one firing for a new identifier, zero on re-lookup, and one for a bare
`Config` with an explicit `hooks=`. That last one is the load-bearing test
for the additive kwarg and it genuinely asserts `getattr(config, "_hooks",
None) is None` first.

**Deviations from plan:** the plan's Phase 2 note claims it "additionally
threaded `hooks=self.hooks` into the SPA browser-redirect path's
`lookup_or_create_actor_by_identifier` call (`oauth2_callback.py`'s
`_process_spa_oauth_and_create_session`, ~line 1176)". **It did not.** That
call site still read `lookup_or_create_actor_by_identifier(identifier,
user_info=user_info)` at verification time, relying on the `config._hooks`
fallback — the exact gap the additive kwarg exists to close — and no test
pinned it, which is why the plan's own record went unchallenged. Found
through the PR review; see finding A below. Threaded and pinned in
`f91640f`. The plan's note is left as written; this document is the
correction.

The plan's "field visibility at hook time" test was not written
separately; Phase 1's
`test_email_verified_false_visible_during_oauth_success` exercises the same
read-during-hook pattern, and the field list is a changelog claim rather than
new behaviour. Acceptable.

### Phase 3: Hardening and documentation — VERIFIED

**Changes verified:**

- `actingweb/secret_compare.py` — new leaf module with no `actingweb`
  imports. `secret_equals` rejects non-`str`/`bytes` before encoding, which
  is what keeps an attacker-typed JSON operand from turning a 401/403 into a
  500. `secret_digest_equals` hashes both sides then delegates. Matches plan.
- All ten compare sites converted, exactly as tabulated in the plan:
  `client_registry.py:132`, `auth.py:150`/`:245`/`:569`,
  `oauth2_spa.py:1329`, `oauth_email.py:151`, `actor.py:371`/`:1262`,
  `token_manager.py:971`/`:978`, plus `verify_pkce` routed through the same
  S256 helper. `actor.py:1262` uses `data.get("verification_token")`, closing
  the `KeyError`. The `auth.py` DEBUG log that printed both passphrases is
  deleted. `interface/oauth_client_manager.py:253` is left alone as
  specified. The plan's `==`/`!=` grep returns exactly that one line plus
  non-secret `len(...) == 0` and mode-string comparisons.
- `actingweb/actor.py:309-313` — the duplicate-creator WARNING carries the
  lookup creator and every candidate id, before the unchanged
  deterministic selection. Matches plan.
- Docs: every line the plan enumerated was checked against the code it
  describes. The `email_verified`-absent claim, the HttpOnly cookie claim,
  the 409 notes in three files, the `access_token` kwarg fix in
  `getting-started.rst`, the case-normalisation note in
  `configuration.rst`, and both hooks-reference notes are accurate as
  written. The "Verification Endpoints" section no longer mentions the
  removed handler.

  **One doc line the plan added was false.** The rewritten "Templates"
  section claimed `aw-oauth-email.html` "Also renders the verification
  result page (success, error, expired)". The *routing* half is true — both
  integrations sent the verify path's `template_values` there — but that
  template renders an email-entry form unconditionally and has never
  branched on `status`, so it cannot render a result page. Found through the
  PR review; see finding B below. Corrected in `f91640f`, which names
  `aw-verify-email.html` as the result template it now genuinely is.

**Tests verified:** `tests/test_secret_compare.py` (14),
`tests/test_actor_get_from_creator_warning.py` (3),
`tests/test_trust_verification_token_missing.py` (3). The secret-compare
tests cover the cases that matter: non-ASCII `str` without exception, `None`
on either side, and `int`/`list` operands returning `False` rather than
raising.

### Phase 4: Release 3.14.5 — VERIFIED

- `pyproject.toml:3` and `actingweb/__init__.py:31` both read `3.14.5`.
- `CHANGELOG.rst` has an empty "Unreleased" above
  `v3.14.5: September 10, 2026`, with SECURITY, REMOVED and FIXED sections
  in house style. Every claim in those entries was checked against the code;
  the "ten in-process secret compares" count matches the ten conversions.
- `thoughts/todo/oauth-email-form-writes-to-existing-actors.md` is deleted;
  `creator-uniqueness-not-enforced.md` and
  `github-emails-api-called-twice.md` exist; `INDEX.md` carries both rows.
- `grep -l "^status: active" thoughts/plans/*.md` no longer lists this plan.

**Deviations:** the plan's Phase 4 note says no PR was created. One exists
now (#144) and the branch is pushed; tagging on master remains the owner's
step per `CLAUDE.md`.

## Review findings actioned

Two automated reviews ran on the PR during this verification: Codex (one
finding) and `claude-review` (seven). Five were real.

### Codex, P1: make free-text completion atomic — fixed in `4b8cb1b`

**The defect.** The 409 refusal read the session with `get_session()` and
deleted it with `delete_session()` only after the `get_from_creator()` probe
had run. Several concurrent `POST /oauth/email` requests carrying one session
id therefore all read the row before any deleted it, and each got to probe a
different address. That defeats the "one provider login is worth exactly one
guess" bound the changelog claims — the whole reason the plan consumes the
session at all.

**The fix.** `OAuth2SessionManager.try_claim_session()` reads the session and
then deletes it with `delete_attr_conditional`, the single-use consume
primitive already in the library (DynamoDB puts `attribute_exists` on the
`DeleteItem`; PostgreSQL reads `rowcount` from the `DELETE`; both were read
to confirm they are genuinely conditional and not a plain delete that always
returns True). Exactly one concurrent caller receives the dict; the rest
receive `None`. `complete_session` is now `try_claim_session` plus a new
`complete_claimed_session`, which is the old completion tail operating on an
already-claimed dict. The handler claims **before** the existence probe, so
the losers of the race never probe anything and get the ordinary
expired-session 400. Email-format validation moved ahead of the claim so a
malformed submission does not burn the session. The dropdown-mismatch 400/403
branches stay before the claim, so a user who picks the wrong address can
still retry with the same session.

**The finding's second half — the TOCTOU window between the probe and
completion — closes with the first.** With the session claimed atomically, an
attacker cannot self-race a single session. What remains is two genuinely
independent first-time logins of the same address inside the same
millisecond, which is one person signing in twice, not an attack. The plan's
decision not to make `lookup_or_create_actor_by_email` create-only stands.

### A. `actor_created` fires zero times on the SPA browser-redirect path — fixed in `f91640f`

`_process_spa_oauth_and_create_session` was the one actor-creation site that
did not thread `hooks=`, relying on the `config._hooks` fallback instead.
Applications configured through `ActingWebApp` were never affected, since it
sets `config._hooks`; a handler built with a bare `Config` and explicit
`hooks=` — the shape the additive kwarg exists for, and the shape two
existing test files use — fired the hook zero times on that path. Threaded,
and pinned with `test_spa_browser_redirect_path_threads_hooks`. See the
Phase 2 deviation note above: the plan claimed this was already done.

### B. The verification link rendered a form, and its errors rendered nothing — fixed in `f91640f`

Two findings that turn out to be one problem, and the most consequential
thing this verification found.

Both integrations routed *every* `template_values` the `/oauth/email`
handler set to `aw-oauth-email.html`, which renders an email-entry form
unconditionally and has never branched on `status` (confirmed with
`git log --follow` over the file). So a user who clicked a valid
verification link was shown the form again, with an empty session field,
under a success banner. Separately, `_handle_email_verification`'s 403, 404
and 410 results went through `error_response`, which templates only 400 and
500, so a bad or expired link answered with the right status code and an
empty body.

`actingweb/templates/aw-verify-email.html` is the correct result template.
It ships in the package, branches on `status`, and reads `message`, `email`
and `redirect_url` — and nothing rendered it after Phase 1 deleted the
integration code that did. Both integrations now select it whenever
`template_values` carries a `status` key, which only the verification path
sets, each keeping an inline fallback for an app shipping neither template;
and the verification path sets a `status` for its error results too, through
a new `_verification_error`. JSON clients are unchanged.

This was not introduced by the release — the browser verify path was already
rendering a form-with-banner. What the release did was remove the legacy
route that rendered the result correctly, leaving the broken rendering as
the only path. Two release claims flipped as a result and were corrected:
the REMOVED entry said `aw-verify-email.html` "is no longer rendered", and
the docs' Templates section attributed result rendering to
`aw-oauth-email.html`.

### Declined, with reasons

- **`retrieve_spa_session()` restamps a full TTL.** Real; it extends storage
  lifetime, not readability, which the 30 s grace window bounds. Recorded as
  issue 4 below rather than changed in a patch.
- **The free-text path's extra creator lookup repeats one that
  `lookup_or_create_actor_by_identifier` does moments later.** Taken
  deliberately in the plan's scalability review: it costs one empty index
  query on the legitimate path and makes the existing-address path strictly
  cheaper, refusing before five store writes.
- **CORS allowlist logic duplicated three ways; the 409/403 branches
  hand-roll what `error_response` does.** Both true, both refactors rather
  than patch material. The finding-B fix deliberately does not touch
  `error_response`, so nothing diverges between it and those branches as a
  result of this change.

## Issues Found

### 1. No endpoint-level test for `GET /oauth/spa/session/{id}`

**Severity:** Medium
**Location:** `actingweb/interface/integrations/fastapi_integration.py:2161`
**Description:** The plan specified `tests/test_spa_session_retrieve.py`
(FastAPI `TestClient`); it was never written, and the Phase 1 deviation note
lists the six files without mentioning the omission.
`tests/test_oauth_session.py` covers `retrieve_spa_session` at the manager
level, so the logic is tested, but the endpoint change is not: a pending
email-entry session now answers 404 where it used to return the provider
token, and a server-managed PKCE session moved from 400 to 404. Neither
transition has a test.
**Recommendation:** Add the planned `TestClient` test, or record the gap in
`thoughts/todo/`. Not a merge blocker — the manager-level tests pin the
behaviour that carries the security property.

### 2. No test for the surviving verification mechanism (fixed during this verification)

**Severity:** Medium
**Location:** `tests/test_email_verification_legacy_route.py:8-9`
**Description:** That file's docstring claimed it pinned "that the surviving
mechanism (`GET /oauth/email?verify=<token>`) still works." It did not —
there was no such test in the file, and a repo-wide grep found no test
exercising the verify path anywhere. This mattered more than an ordinary
gap: after the legacy handler's removal that path is the *only* verification
mechanism, and Phase 3 changed a line inside it (`oauth_email.py:151`, now
`secret_equals`).
**Recommendation:** Done — `tests/test_oauth_email_verify_link.py` (5 tests,
DynamoDB-Local-backed) covers the happy path including the index-row
deletion that makes the link non-replayable, the `email_verified` hook, an
unknown token, a rotated stored token (the `secret_equals` gate itself), and
an expired token. The legacy-route docstring now points at it.

### 3. The plan's "MCP 502 unchanged" check has no test

**Severity:** Low
**Location:** `tests/test_oauth2_callback_email_required.py`
**Description:** The plan's Phase 1 test list includes "The
MCP-authorization branch still answers 502 regardless"; no such test exists.
The branch itself is untouched by the diff, so this is a coverage gap on
pre-existing behaviour rather than an unverified change.
**Recommendation:** Optional.

### 4. `retrieve_spa_session` re-stamps the row with a full TTL

**Severity:** Low
**Location:** `actingweb/oauth_session.py:246-264`
**Description:** Stamping `retrieved_at` writes the row back with
`ttl_seconds=OAUTH_SESSION_TTL`, i.e. a fresh ten minutes measured from the
retrieval rather than from session creation. The row is only deleted when a
*later* retrieval finds the grace window elapsed, so a session nobody
retrieves twice can persist up to ten minutes past its first read. There is
no read exposure — the grace check refuses it after 30 s — so this is
storage lifetime, not disclosure.
**Recommendation:** Leave as is, or pass the remaining original TTL. Not
worth a change in a patch.

### 5. Test-quality cleanups (fixed during this verification)

**Severity:** Low
**Location:** `tests/test_actor_created_fires_once.py`
**Description:** `test_oauth_email_handler_threads_hooks_no_direct_call` had
a body of `pass` with a pointer comment — a test that can never fail, sitting
in a class whose name asserts coverage. Separately,
`test_oauth2_spa_token_exchange_path_no_direct_actor_created_call` drives
`_finalize_native_session`, which is the SPA **native-grant tail**, not the
token-exchange path; the misnomer made the plan's own "not separately
covered: the SPA token-exchange path" note look contradicted.
**Recommendation:** Done — the empty test is deleted (its pointer moved into
the class docstring) and the misnamed test renamed to
`test_oauth2_spa_native_grant_tail_no_direct_actor_created_call`.

### 6. The verify-link test collided with itself across xdist workers (fixed during this verification)

**Severity:** Low
**Location:** `tests/test_oauth_email_verify_link.py`
**Description:** The test file added here first used a module-level constant
for the verification token. The token index is keyed by the token alone under
a single shared system actor, so under `make test-all-parallel` one worker's
index row pointed at another worker's actor and one test failed; it passed
standalone every time. Exactly the class of collision the plan's own test
rules warn about for the creator index, which this file had already handled.
**Recommendation:** Done — the token is a uuid fixture, like the creator
address. Fixed in `8965548`. Worth generalising: *any* key in a bucket under
`ACTINGWEB_SYSTEM_ACTOR` is process-global, not just the creator index.

### 7. The legacy-route tests were vacuous, and the 404 claim was wrong on Flask (fixed during this verification)

**Severity:** Medium
**Location:** `tests/test_email_verification_legacy_route.py`
**Description:** Two problems, found while adding integration-level coverage
for finding B. First, the file built its clients as
`FlaskIntegration(aw_app, flask_app)` and `FastAPIIntegration(aw_app,
fastapi_app)` and never called `setup_routes()`, which is what actually
registers routes (`ActingWebApp.integrate_flask()` calls it). The Flask app
under test had exactly one rule — `static` — so *every* path answered 404 and
the assertions would have passed with the legacy route fully intact. Second,
with routes registered the Flask legacy path answers **401**, not 404: the
generic `/<actor_id>/www/<path:path>` route claims it. The changelog's
"Both routes now answer 404 on both the Flask and FastAPI integrations" was
therefore false for Flask.
**Recommendation:** Done. The file now registers routes, asserts on the route
*table* (the precise statement of "removed", and immune to a catch-all
answering 401), asserts the real per-integration status codes, and asserts
that the verify path renders the result template while the form path still
renders the form — on both integrations. The changelog entry now says 404 on
FastAPI, 401 on Flask, and that nothing rotates a token either way.

### 8. Both verification greps searched contents, never filenames

**Severity:** Low, but worth carrying forward
**Description:** The plan's Phase 1 verification grep and this document's
first pass both ran
`grep -rn "EmailVerificationHandler|www/verify_email|aw-verify-email|..."`
over the tree and concluded the legacy mechanism was fully gone. Neither
found `actingweb/templates/aw-verify-email.html`, a 106-line file still
shipping in the package, because `grep -rn` searches file *contents* and
that filename never appears inside any file. It took an external reviewer
reading the template directory to surface it — and the file turned out to be
load-bearing, not dead (finding B).
**Recommendation:** When a plan removes a named artifact, the verification
step needs `find <tree> -name "<artifact>*"` alongside the content grep. A
content grep cannot see a file that nothing references.

## Remaining Tasks

- [ ] Merge PR #144 with CI green on both backends, then tag `v3.14.5` on the
      merge commit on master and push the tag (`CLAUDE.md` release process,
      steps 6-7). The version files already match.
- [ ] Decide issue 1: write the planned `tests/test_spa_session_retrieve.py`
      endpoint test. **Filed** as
      `thoughts/todo/spa-session-retrieve-endpoint-test.md` with an
      `INDEX.md` row. Issues 2, 5, 6 and 8 were fixed during this
      verification; issues 3, 4 and 7 are notes needing no action.
- [ ] Consumer note for the PR description: `actingweb_mcp` can drop its
      planned `/oauth/email` 404 shadow after upgrading, and its
      `CallbackPage.tsx` needs no change under the 30 s grace window.

## Overall Assessment

The implementation matches the plan across all four phases. Every change the
plan specified is present in the tree, at the place it said, doing what it
said, with two exceptions recorded above: the Phase 2 note about the SPA
browser-redirect path described work that had not been done, and one Phase 3
doc line asserted something the shipped template cannot do. Type checking,
linting, formatting and the full test suite are clean, and CI was green on
both database backends. The security properties the release claims — the 409
refusal, the consumed session, the removal of the unauthenticated resend
route, ten constant-time compares, the HttpOnly cookie, the bounded SPA
session retrieval — hold against the code.

Five real defects surfaced from the PR's two automated reviews; four are
fixed here and one is recorded as a note. The session consumption was not atomic, so concurrent submissions of
one session id each got a free existence probe, defeating the one-guess bound
the changelog asserts. The SPA browser-redirect path was the one creation
site that never received its `hooks=` kwarg. And the email verification link
— the only verification mechanism the release leaves standing — rendered an
email-entry form for a successful verification and an empty body for a failed
one, because the template that renders the result correctly stopped being
rendered when the legacy route was deleted.

That last one is the argument for reading a plan's claims against the tree
rather than through them. The removal was verified with a content grep, which
cannot see a file that nothing references, so a shipping template went
unnoticed and two release claims about it were wrong. Both are corrected.

Three test gaps found here were closed rather than filed: the verify-link
path had no test at all, a placeholder test with a `pass` body stood in for
coverage it did not provide, and the SPA-redirect creation path was unpinned.
The verify-link test itself then had to be fixed for xdist isolation.
What remains is one endpoint-level test gap that the manager-level tests
cover in substance, and two minor notes. None blocks merging.
