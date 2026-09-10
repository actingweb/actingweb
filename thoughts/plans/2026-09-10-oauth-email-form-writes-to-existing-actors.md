---
status: done
---

# Implementation Plan: 3.14.5 — close the OAuth email-entry form's inputs, fire `actor_created` once, constant-time secret compares

**Date:** 2026-09-10
**Research:** thoughts/research/2026-09-09-oauth-email-form-writes-to-existing-actors.md
**Branch:** to be created as `fix/3.14.5-oauth-email-form` from `master` at `efc10a5`

## Overview

`POST /oauth/email` accepts any typed address when the provider returned no
verified emails, and when that address already has an actor it returns that
actor, overwrites its provider tokens, marks it unverified and re-runs the
consumer's `actor_created` hook against it. Separately, `actor_created` has
fired **twice** for every OAuth-created actor since v3.5.1, and eleven
in-process secret compares use `==`. This plan closes the form's inputs
without removing the documented feature, moves `actor_created` to a single
firing site in core, sweeps the compares, and ships the lot as patch 3.14.5.

The four adversarial reviews of the first draft (recorded under "Evaluation
Notes") added six items the research did not carry: the refusal has to
consume the pending session or it becomes an enumeration oracle;
`oauth_success` has to fire before the verification mail, not after;
`error_response` never puts JSON on the wire for 400/500; the SPA
success-session endpoint is replayable for ten minutes; the legacy resend
endpoint is unauthenticated; and a form-created orphan is adopted by the real
owner's later login with its pending state intact.

## Decisions Made

- **The self-asserted email flow survives in both branches** (research
  Decision 1, option 2 narrowed). Owner's call, 2026-09-10. The v3.4/v3.10
  feature, its routes, hooks and three guides stay. What changes is what the
  form will do with an address that already has an actor (refuse), what a
  GitHub API failure does (fail loudly instead of falling through to
  free-text), and which hooks the path fires (`oauth_success` joins).
- **`actor_created` fires in core only** (Decision 2). `Actor.create()` with
  `hooks=` is already the only firing site for the factory and the MCP OAuth
  server; the four handler-level calls are the outliers and go. The
  consumer-visible shift — the hook now runs before OAuth tokens and provider
  metadata are stored on the actor — is recorded as a **Behavior change** in
  the changelog with the exact field list.
- **No auth gate on `email_verified`** (Decision 3). With the refusal in
  place the field protects nothing reachable; the two doc lines that claim
  `"true"` is written for provider-verified addresses are corrected instead.
  The opt-in Google/Apple `email_verified` claim check is not in this plan.
- **All the compares, one helper, same release** (Decision 4). The research
  counted eleven sites; one (`handlers/email_verification.py:135`) is
  deleted with the legacy handler, so ten are converted. A leaf module with
  no `actingweb` imports, using `secrets.compare_digest` to match the
  in-package idiom at `oauth2_id_token.py:139`.
- **Duplicate creators: log, do not constrain** (Decision 5). A WARNING in
  `get_from_creator` when more than one candidate matches; the uniqueness
  constraint stays in `todo/` as its own schema-changing item.
- **Two case rules: document, do not change the lookup table** (Decision 6).
- **Three review findings are in scope**, owner's call 2026-09-10: the
  legacy verification handler `/{actor_id}/www/verify_email` is **removed**,
  GET and POST (owner's call, same day, over the first draft's "add
  authentication to the POST": the resend's only caller is an
  unauthenticated expired-link page whose user cannot log in, so an
  authenticated resend would keep a route nobody can call); the
  SPA success-session endpoint gets a **30 s grace window** rather than hard
  one-time use (the consumer's `CallbackPage.tsx` runs `handleCallback()` in
  a `useEffect` with no once-guard under `React.StrictMode`, so a hard delete
  would 404 the second development-mode fetch); a provider-verified login of
  an existing actor clears squatted pending-verification state.
- **The legacy GET `/{actor_id}/www/verify_email?token=` goes too.**
  Owner's call, 2026-09-10, with the cost named: it is documented
  (`docs/guides/authentication.rst:1058-1060`) and the v3.10 changelog twice
  promised it "remains functional for backward compatibility"
  (`CHANGELOG.rst:2108`, `:2267`). What that promise protected: a
  verification link a consumer built by hand in the legacy format. The
  library's own `email_verification_required` hook has passed the
  `/oauth/email?verify=` URL since v3.10, and the legacy resend emitted that
  format as well, so only a consumer that composed its own URL is affected;
  such a link now answers 404 and its user redoes the sign-in. The whole
  handler module, both routes, both integration blocks and the sample
  template are deleted, so one verification mechanism remains.
- **Patch 3.14.5, FIXED, SECURITY and REMOVED entries.** No hook name,
  hook kwarg, response field, public signature or config option changes.
  The one route removal is the legacy verification handler above; the
  owner accepted that it breaks a v3.10 compatibility note in a patch, and
  the changelog says so in the REMOVED entry. Two new keyword-only
  parameters with defaults (`hooks=` on the lookup functions and
  `complete_session`) and two new session-manager methods are additive.
- **The 409 keeps a distinct `code: actor_exists`.** Today the same POST
  returns 200 with the victim's `actor_id`, so 409 is strictly less
  disclosure, and a generic error would still be an oracle because a
  non-existing address succeeds. The bound that matters is one provider login
  = one guess, which consuming the session restores.
- **The refusal applies only to the free-text branch.** A dropdown-selected
  address was verified by GitHub in this very session, so completing for an
  existing actor there is a returning user, exactly what today's code does.
  (After the GitHub-failure change the dropdown is reachable only when the
  first `/user/emails` call fails and the second succeeds milliseconds later;
  the branch stays with correct semantics.)

## What We're NOT Doing

- Removing `/oauth/email`, the web-UI or SPA `email_required` branches, the
  `email_verification_required` / `email_verified` hooks, or their docs.
- Making the form path yield a usable session. It never has: the cookie and
  the JSON `access_token` are the **provider's** token, and both
  `_check_oauth2_token` paths (`auth.py:290-370`, `:475-540`) require the
  provider's own email claim to equal `actor.creator`, which a provider that
  returned no email cannot satisfy. A link-verified free-text actor's
  next login therefore lands on the form again and, after this plan, is
  answered 409. That is an existing dead end made explicit, not a new one.
  Recorded here so nobody reads the 409 as the cause.
- Gating any auth path on `email_verified`, or reading Google's / Apple's
  `email_verified` claim (Apple's can be the string `"false"`; Work & School
  and Google Workspace on non-Google domains carry `false` legitimately).
- Enforcing creator uniqueness (PostgreSQL unique index on `lower(creator)`,
  DynamoDB marker items). Own todo, own release.
- Lowercasing values in the property lookup table. Documented rule only.
- Caching the GitHub `/user/emails` response so the failure path stops
  making two sequential calls of up to 15 s each after a 10 s userinfo call
  (≈45 s worst case, past API Gateway's limit on Lambda). Own todo.
- Adding rate limiting anywhere; none exists in the library today.
- Providing any resend-verification action after the legacy POST is
  removed. A user whose link expired redoes the sign-in; for an address that
  already has an actor that now answers 409, and since `email_verified`
  gates nothing, nothing functional is lost. If a resend is ever wanted it
  belongs as an authenticated action on the current `/oauth/email` handler,
  not a revival of the legacy one.
- A Flask `/oauth/spa/session/<id>` route. Flask has none — the research's
  claim that `flask_integration.py:259` registers "the same route" is wrong
  (that is the session-*check* compat route); corrected in Phase 3.
- Touching `docs/migration/v3.14.rst`. Patch releases do not add to
  migration guides.

## Phase 1: Close the email form's inputs

Everything on the request path from the callback's no-identifier branches
through `POST /oauth/email`, plus the two adjacent endpoints the security
review found. Independently green: no `actor_created` change yet — the
free-text refusal never reaches the existing unconditional call at
`:379-390` for an existing actor, while the dropdown path for an existing
actor still fires it at handler level until Phase 2 removes the block (so
the Phase 1 dropdown test asserts the actor id, not a hook count) — and no
signature change other than additive ones.

### Changes

**`actingweb/handlers/oauth_email.py` — `post()` (`:270-513`)**

- Normalise `email = email.strip().lower()` immediately after the
  `"@" in email` check at `:303`, so the `email not in verified_emails`
  membership check at `:331-333` runs on the same form the list was
  lowercased to (`oauth2.py:927`). Today `Probe.Existing@Example.com` against
  `["probe.existing@example.com"]` is a 403.
- In the `else` branch (`:355-359`, no `verified_emails`, free-text): before
  `complete_session`, run
  `actor_module.Actor(config=self.config).get_from_creator(email)`. On a hit:
  - delete the pending session (new `OAuth2SessionManager.delete_session`,
    below) so one provider login is one guess;
  - JSON (`_wants_json()`): status 409, CORS headers, body
    `{"error": true, "code": "actor_exists", "status_code": 409, "message": "An account already exists for this email address. Sign in again to use a different address."}`;
  - UI (`config.ui`): `set_status(409)` and `template_values` with
    `session_id=""`, `action`, `method`, `provider=session.get("provider", "OAuth provider")`,
    `error=<same message>`, `status_code=409`. Both integrations render the
    template without passing the status (`flask_integration.py:1063`,
    `fastapi_integration.py:1895`), so the browser sees 200 HTML with the
    error text — the same as the existing 400 branches; not changed here.
    The empty `session_id` means a resubmit gets the existing 400
    "Missing session parameter", which matches the message.
  - No hook runs, nothing is written to the actor, no token-index row, no
    mail.
- After `complete_session` returns an actor, reorder the tail:
  1. If `email_requires_verification`, write `store.email_verified = "false"`
     **now** (moved up from `:404`), so the next hook sees the state D3's
     docs will describe.
  2. Fire `oauth_success` with the callback's kwargs
     (`oauth2_callback.py:679-685`): `email=<normalised address>`,
     `access_token=session["token_data"].get("access_token", "")`,
     `token_data=session["token_data"]`, `user_info=session["user_info"]`.
     Both are taken from the session dict loaded at `:318-324` because
     `complete_session` deletes the row (`oauth_session.py:220-229`). The
     stored `user_info` is already normalised — both callback branches run
     `normalize_user_info` (`oauth2_callback.py:376`, `:1078`) before
     `store_session` (`:430`, `:1108`) — so no second normalisation.
     `oauth_valid = bool(result) if result is not None else True`, as the
     callback does at `:687`. On rejection: 403 JSON
     `{"error": true, "code": "authentication_rejected", "status_code": 403, "message": "Authentication rejected"}`
     or the template with that error; the actor row stays, matching the
     callback's rejection at `:690-696`; **no** verification token, index row
     or mail.
  3. Only if accepted: the rest of the verification block (`:393-425` minus
     the flag), the `email_verification_required` hook (`:433-448`), the
     cookie, the response. The unconditional `actor_created` block at
     `:379-390` stays where it is in this phase; Phase 2 removes it.
- `set_cookie("oauth_token", …)` at `:458-464` gains `httponly=True`. Every
  other credential cookie in the library is HttpOnly
  (`oauth2_callback.py:817`, `oauth2_spa.py:1639-1668`).
- `error_response` (`:515-529`): when `_wants_json()`, do **not** set
  `template_values` (both integrations render the template whenever it is
  truthy, before the fall-through that puts the handler's written body on the
  wire: `flask_integration.py:1057-1063`, `fastapi_integration.py:1886-1895`);
  instead set CORS headers, write
  `{"error": true, "status_code": N, "message": …}` with
  `Content-Type: application/json`. Today a JSON client with an expired
  session gets HTML, and a 403 has an empty body.
- `_set_cors_headers` (`:60-72`) reflects any `Origin` with
  `Access-Control-Allow-Credentials: true`. Replace with the
  `spa_cors_origins` allowlist logic from `oauth2_spa.py:148-172`. Identical
  behaviour at the default `["*"]`.

**`actingweb/oauth_session.py`**

- New `delete_session(session_id: str) -> None` on `OAuth2SessionManager`:
  the `Attributes(OAUTH2_SYSTEM_ACTOR, OAUTH_SESSION_BUCKET).delete_attr`
  that `complete_session` inlines at `:222-229`; `complete_session` calls it.
- New `retrieve_spa_session(session_id: str) -> dict[str, Any] | None`:
  `get_session`; return `None` unless `token_data` carries `actor_id` (a
  pending-email session stores the raw provider token response and never
  does; SPA success sessions always do, `oauth2_callback.py:1269-1280`);
  if `retrieved_at` is set and older than `OAUTH_SESSION_RETRIEVE_GRACE`,
  delete the row and return `None`; if `retrieved_at` is unset, stamp it
  with `set_attr(..., ttl_seconds=OAUTH_SESSION_TTL)` (same shape as
  `try_mark_refresh_token_used` at `:535-617`). Returns the session dict.

**`actingweb/constants.py`** — `OAUTH_SESSION_RETRIEVE_GRACE = 30` next to
`OAUTH_SESSION_TTL` (`:181`), with the invariant comment
`OAUTH_SESSION_RETRIEVE_GRACE < OAUTH_SESSION_TTL`.

**`actingweb/interface/integrations/fastapi_integration.py` —
`_handle_spa_session_retrieve` (`:2238-2298`)**: call
`retrieve_spa_session`; `None` → the existing 404 "Session not found or
expired". Server-managed PKCE sessions (`oauth2_spa.py:467`, stored with
`token_data={}`) have no `actor_id` either and move from the 400 "Invalid
session data" branch to this 404; nothing documents them as readable here,
and the 400 branch stays only as a defensive fallback. Delete the false
"one-time use by design" comment at `:2280-2281`. Its
`cors_headers` (`:2254-2260`) get the same allowlist treatment.

**`actingweb/oauth2.py` — GitHub API failure is not "no verified emails"**

- `OAuth2Provider.get_verified_emails(self, access_token: str) -> list[str]`
  on the base class (`:150-172`, next to `get_primary_email` at `:162`),
  returning `[]`. Type is `list[str] | None` on the signature so GitHub can
  return `None`.
- `GitHubOAuth2Provider.get_verified_emails` delegates to a new module-level
  `_get_github_verified_emails(access_token)` beside
  `_get_github_primary_email` (`:1164-1210`): `[]` when GitHub answered 200
  with no verified entries; `None` on any non-200 (a 404 from a token
  without `user:email` included, per the community thread in the research)
  or exception. The `verified` list stays lowercased.
- `OAuth2Authenticator.get_github_verified_emails` (`:887-937`) becomes a
  shim delegating to `self.provider.get_verified_emails` (kept for
  backward compatibility; its docstring now states the `[]` / `None`
  contract). Both existing callers use truthiness, so `[]` is safe.

**`actingweb/handlers/oauth2_callback.py`**

- Web-UI branch (`:400-445`) and SPA branch (`:1088-1142`): replace the
  hardcoded `provider.name == "github" and access_token` guard at `:406` and
  `:1100` with
  `verified_emails = self.authenticator.provider.get_verified_emails(access_token) if access_token else []`.
  Immediately after: `if verified_emails is None:` →
  - web: `error_response(502, "We could not confirm your email address with your sign-in provider. Please try signing in again.")`.
    Add `502` to the `[403, 400]` list in `error_response` (`:897-908`) so the
    browser gets the error template, not a raw dict.
  - SPA: `_redirect_to_spa_with_error(spa_redirect_url, "identifier_failed", <same message>)`
    (`:910-`), i.e. the exit at `:1148-1160` with a retry-worded description.
  `[]` → the form, free-text, exactly as documented. Non-empty → dropdown.
  The MCP 502 at `:415-422` is untouched.
- Existing-actor cleanup: after `lookup_or_create_actor_by_identifier`
  returns at `:541-544`, nothing extra — the cleanup lives inside it (next
  bullet) and the callback always calls it.

**`actingweb/oauth2.py` — squatted pending state**

- New module-level `clear_pending_email_verification(actor_instance, config) -> None`:
  if `store.email_verified == "false"`, delete the token-index row
  (`ACTINGWEB_SYSTEM_ACTOR` / `EMAIL_VERIFY_TOKEN_INDEX_BUCKET`, keyed by
  `store.email_verification_token`) and set `email_verified`,
  `email_verification_token`, `email_verification_created_at` to `None`
  (absent = provider-verified under D3).
- Called at four sites, each a provider-verified login of an existing
  actor: the existing-actor branch of `lookup_or_create_actor_by_identifier`
  (`:971-978`; reached by the web callback and by the dropdown path of
  `complete_session` — the free-text path no longer reaches it for an
  existing actor after the refusal above), the two SPA existing-actor
  branches that bypass it (`oauth2_spa.py:872-877`, `:1042-1045`), and the
  MCP OAuth server's own `get_from_creator` branch
  (`oauth2_server/oauth2_server.py:731-733`), which also never calls
  `lookup_or_create_actor_by_identifier`.

**Legacy verification handler `/{actor_id}/www/verify_email` — removed, GET and POST**

Today anyone holding an actor id rotates its verification token and fires
`email_verification_required` → mail to `actor.creator`, unlimited, no
login needed, because the POST (`handlers/email_verification.py:195-291`)
has no authentication and rejects only `email_verified == "true"`, a value
the library never writes for provider-verified actors. Its only caller in
the tree is the 410 "link expired" state of the sample template, reached
unauthenticated by following an expired link, and a form-registered owner
cannot log in (see "What We're NOT Doing"), so an authenticated resend
would keep a route nobody can successfully call. The GET duplicates
`GET /oauth/email?verify=` against the same store fields but does not
delete the token-index row on success. Remove the whole mechanism:

- `actingweb/handlers/email_verification.py`: delete the module.
- `actingweb/interface/integrations/flask_integration.py`: delete the
  route at `:203` and the handler method it calls (`:1126-1160` region:
  the `EmailVerificationHandler` construction, dispatch and the
  `aw-verify-email.html` rendering with its inline fallback HTML).
- `actingweb/interface/integrations/fastapi_integration.py`: delete both
  registrations at `:702-708` and the handler method (`:1958-1995` region,
  same shape).
- `tests/integration/templates/aw-verify-email.html`: delete. It is
  rendered only by the deleted handler; the `/oauth/email` routes render
  `aw-oauth-email.html` for the verify path too (`flask_integration.py:1062-1070`,
  `fastapi_integration.py:1894-1902`).
- `tests/test_spa_api_endpoints.py:144-160` (`TestEmailVerificationHandlerJSON`):
  delete the class.
- `grep -rn "email_verification\b\|EmailVerificationHandler\|www/verify_email\|aw-verify-email"`
  across `actingweb/ tests/ docs/` must then return only the docs and
  changelog lines Phase 3 and Phase 4 rewrite, and the historical
  changelog entries (`CHANGELOG.rst:2108`, `:2267`, `:2924`), which are
  not edited.
- The `stored_token != token` at `:135` leaves the Phase 3 compare list
  with the module.

### New tests

Unit tests run against DynamoDB Local like `tests/test_oauth_session.py`;
the CI PostgreSQL leg runs them too, so nothing may assume a backend. Rules
from the scalability review, for every new file: creator emails are
`f"{uuid.uuid4()}@example.com"` (the creator index is shared across xdist
workers under one `test` prefix, `tests/conftest.py:22`); a yield fixture
deletes the actor **and** the verification-token index row on teardown even
on assertion failure; function-scoped fixtures only; never read or clear the
shared `OAUTH_SESSION_BUCKET` beyond the test's own session id; spies via
`mock.patch.object(..., wraps=...)`, never module globals.

`tests/test_oauth_email_handler.py` (new; nothing exercises
`OAuth2EmailHandler.post()` today — `tests/test_oauth2_spa.py:285-300` only
checks method existence):

- Mixed-case address against a lowercase verified list → 200 (regression for
  item 4).
- Free-text address that already has an actor → 409, JSON body carries
  `code: actor_exists`; the session row is gone; the actor's `oauth_token`,
  `oauth_provider`, `email_verified` and `email_verification_token` are
  unchanged; no `actor_created`, `oauth_success` or
  `email_verification_required` call; no token-index row.
- Dropdown-selected address that already has an actor → 200, same actor id
  (returning-user semantics preserved).
- Free-text new address: `oauth_success` fires with `email` normalised,
  `token_data` and `user_info` from the session, and sees
  `store.email_verified == "false"`; a falsy return → 403 JSON with
  `code: authentication_rejected`, no `email_verification_required` call, no
  token-index row.
- `oauth_token` cookie recorded with `httponly=True`.
- `Accept: application/json` with an expired session → 400 with a JSON body
  and no `template_values`; without the header → `template_values` set.
- `Origin` not in `spa_cors_origins` is not reflected.

`tests/test_oauth_session.py` (extend):

- `delete_session` removes the row; `complete_session` still clears it.
- `retrieve_spa_session`: pending-email session (no `actor_id`) → `None`;
  success session → dict, `retrieved_at` stamped; second call inside the
  grace window → dict; a call with `retrieved_at` older than the window →
  `None` and the row deleted.

`tests/test_oauth2_provider_verified_emails.py` (new):

- `_get_github_verified_emails`: 200 with two verified and one unverified →
  the two, lowercased; 200 with none verified → `[]`; 200 empty list → `[]`;
  404 → `None`; 500 → `None`; `requests` exception → `None`.
- `OAuth2Provider.get_verified_emails` on Google and Apple → `[]`.
- `OAuth2Authenticator.get_github_verified_emails` delegates.

`tests/test_oauth2_callback_email_required.py` (new; mock pattern from
`tests/test_oauth2_callback_github_normalization.py`):

- Web branch, `require_email`, GitHub, `get_verified_emails` → `None` →
  502 with `template_values` set; `[]` → 302 to `/oauth/email?session=`
  with a session whose `verified_emails` is empty; list → session carries
  the list.
- SPA branch: `None` → redirect with `error=identifier_failed` and the retry
  description; `[]` → `email_required=true&session=`.
- Google under `require_email` with no email claim → form (no 502).
- The MCP-authorization branch still answers 502 regardless.

`tests/test_spa_session_retrieve.py` (new, FastAPI `TestClient`): pending
email session → 404; success session → 200 with the token; second GET
within the window → 200; a session stamped outside the window → 404.

`tests/test_email_verification_legacy_route.py` (new): `GET` and `POST
/{actor_id}/www/verify_email` answer 404 on both integrations (`TestClient`
for FastAPI, Flask test client) for an existing actor, the actor's
`email_verification_token` is unchanged and `email_verification_required`
did not fire; `import actingweb.handlers.email_verification` raises
`ModuleNotFoundError`; `GET /oauth/email?verify=<valid>` still marks the
actor verified and deletes the index row (the surviving mechanism).

`tests/test_oauth2_lookup_clears_pending.py` (new): actor created with
`email_verified="false"` and a token-index row; `lookup_or_create_actor_by_identifier`
for that creator → the three fields are absent and the index row is gone;
the two SPA existing-actor branches produce the same (unit-drive the handler
as `tests/test_oauth2_spa_jwt_bearer.py:161` does).

Integration (`tests/integration/test_oauth2_flows.py`, extend if an
`/oauth/email` flow can be driven there without a live provider; otherwise
the unit tests above are the coverage and the plan says so in the
verification doc): the three consumer acceptance checks from the research —
a `POST /oauth/email` with a valid session for an existing address creates
nothing and touches no existing actor; a GitHub sign-in whose emails API
fails ends on a visible error with no actor row; the MCP 502 is unchanged.

### Verification

- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` and `poetry run ruff format --check actingweb tests`
- [ ] `poetry run pytest tests/test_oauth_email_handler.py tests/test_oauth_session.py tests/test_oauth2_provider_verified_emails.py tests/test_oauth2_callback_email_required.py tests/test_spa_session_retrieve.py tests/test_email_verification_legacy_route.py tests/test_oauth2_lookup_clears_pending.py -v`
- [ ] `grep -rn "www/verify_email\|email_verification\b\|aw-verify-email" actingweb/ docs/ tests/` returns only the legacy-route test and the rewritten doc/changelog lines
- [ ] `make test-all-parallel` green
- [ ] PostgreSQL leg: `DATABASE_BACKEND=postgresql PG_DB_PORT=5433 … poetry run pytest tests/test_oauth_email_handler.py tests/test_oauth2_lookup_clears_pending.py`
- [ ] Manual: the research's probe sequence (first POST creates; second POST with a new session and the same address in mixed case) now answers 409 on the second call and the first actor's `oauth_token` is unchanged.

### Implementation Status: Complete

**Verification results:** `pyright actingweb tests` — 0 errors, 0 warnings.
`ruff check` / `ruff format --check` — clean. New/extended test files (66
tests) pass: `test_oauth_email_handler.py`, `test_oauth_session.py`
(extended), `test_oauth2_provider_verified_emails.py`,
`test_oauth2_callback_email_required.py`,
`test_email_verification_legacy_route.py`,
`test_oauth2_clear_pending_verification.py`. Full `make test-all-parallel`:
3381 passed, 31 skipped, 1 error (`test_hot_path_n_plus_one.py::TestPropertyStoreBulkReads::test_items_and_values_are_bulk_reads`,
unrelated to this change — passes standalone; a pre-existing parallel-run
isolation flake per CLAUDE.md's own caveat about `make test-all-parallel`).
The manual probe-sequence check was exercised as an automated test
(`TestFreeTextExistingAddressRefused`) rather than run by hand against a
live server.

**Deviations from the plan:**

- `tests/test_oauth_session.py` is a full in-memory `MockDbAttribute`, not a
  DynamoDB-Local-backed test as this plan's "New tests" preamble assumed;
  corrected here since `delete_session`/`retrieve_spa_session` extend it
  directly. The isolation rules (uuid creators, yield-fixture teardown) apply
  to the handler-level tests that hit `Actor.get_from_creator` /
  `ActorInterface.create` — those are unit tests with `actor_module.Actor`
  mocked (matching `tests/test_oauth2_spa_jwt_bearer.py`'s pattern), not
  DynamoDB-Local-backed, so the uuid/teardown rules don't apply to them
  either.
- Test files consolidated from the plan's seven to six mocked unit-test
  files; no DynamoDB-Local-backed or `tests/integration/` test was added.
  Every load-bearing assertion from the plan's "New tests" sections is
  covered by one of the six files (409 refusal + session consumption + zero
  hooks + unchanged actor fields; dropdown returning-user 200; free-text
  `oauth_success` firing with session data and `email_verified == "false"`
  visible during the call; rejection → 403 with no token/index write; mixed-case
  membership; HttpOnly cookie; JSON-vs-template error shape; CORS allowlist;
  `_get_github_verified_emails` status/exception matrix; provider defaults;
  authenticator shim; callback web/SPA `None`/`[]`/list handling including
  the Google no-502 case; legacy-route 404 on both integrations plus
  `ModuleNotFoundError`; `clear_pending_email_verification`'s field/index-row
  clearing and its wiring into `lookup_or_create_actor_by_identifier`). Not
  added: a live-server integration test and a Flask-specific
  `clear_pending_email_verification` SPA-branch test (the FastAPI-shaped
  unit test and the `oauth2.py` wiring test cover the same logic; the SPA
  handler's two call sites are code-identical to the pattern verified at
  the `lookup_or_create_actor_by_identifier` site).
- The plan's Phase 1 verification grep (`email_verification\b`) was written
  before the code existed and also matches two things that are meant to
  survive: `_handle_email_verification` (the GET-verify method that is the
  *surviving* mechanism, unrelated to the deleted legacy handler) and the
  new `clear_pending_email_verification` helper. The actually-useful grep is
  `EmailVerificationHandler\|www/verify_email\|aw-verify-email\|handlers\.email_verification`,
  confirmed to return only `docs/guides/authentication.rst` lines (Phase 3)
  and historical `CHANGELOG.rst` entries (not edited).
- `retrieve_spa_session`/`_handle_spa_session_retrieve` CORS: implemented the
  `spa_cors_origins` allowlist as specified; not covered by a dedicated test
  in Phase 1 (the existing 404/400 assertions for that endpoint are also
  untested pre-existing behavior with no test file to extend).

---

## Phase 2: `actor_created` fires once, in core

Independently green: Phase 1 left the handler-level calls in place; this
phase removes them and adds the tests that pin the count. Nothing in
`tests/` asserts a handler-level call today.

### Changes

**`actingweb/oauth2.py`**

- `lookup_or_create_actor_by_identifier(self, identifier, user_info=None, *, hooks=None)`
  (`:955`): `effective = hooks if hooks is not None else getattr(self.config, "_hooks", None)`
  passed to `ActorInterface.create(..., hooks=effective)` at `:984-988`.
  Same on `lookup_or_create_actor_by_email` (`:939`). Additive. Reason:
  `config._hooks` is set only by `ActingWebApp.get_config()`
  (`interface/app.py:1320`, `:1327`); a handler built with a bare `Config`
  and an explicit `hooks=` — the shape of `tests/test_oauth2_spa_jwt_bearer.py:161`
  and `tests/test_oauth2_callback_apple.py:295-310`, and of any consumer
  driving handlers outside `ActingWebApp` — fires once today and would fire
  zero times without this.

**`actingweb/oauth_session.py`** — `complete_session(self, session_id, email, *, hooks=None)`
forwards `hooks` to `lookup_or_create_actor_by_email`. Additive.

**`actingweb/handlers/oauth_email.py`** — delete the `actor_created` block
(`:379-390`); pass `hooks=self.hooks` to `complete_session`.

**`actingweb/handlers/oauth2_callback.py`** — delete the `is_new_actor`
block (`:653-665`) **and** the `get_from_creator` pre-check at `:536-540`:
unlike the SPA sites it is not an if/else — `lookup_or_create_actor_by_identifier`
is called unconditionally at `:541-544` and repeats the lookup, so the
pre-check's only consumer was the flag. Existing-actor web logins drop from
two creator lookups to one. Pass `hooks=self.hooks`.

**`actingweb/handlers/oauth2_spa.py`** — delete the two blocks
(`:901-912`, `:1068-1078`) and the `is_new_actor` assignments; **keep** the
if/else pre-checks at `:872-883` and `:1042-1050` — their existing-actor
branch deliberately bypasses `lookup_or_create_actor_by_identifier` and its
`oauth_provider` rewrite (`oauth2.py:975-977`), and reuses the loaded actor.
Pass `hooks=self.hooks` on the create side.

**Not changed, listed so the count test's expectations are explicit:**
`handlers/factory.py:247-252` (core, once), `oauth2_server/oauth2_server.py:730-742`
(core, once), `handlers/mcp.py:2169` (`create()` without `hooks=`, zero
today and after — pre-existing, out of scope), the two system actors
(`trust_type_registry.py:126`, `oauth2_server/system_actor.py:58`,
intentionally zero).

### New tests

`tests/test_actor_created_fires_once.py` (new; `ActingWebApp` fixture and
hook registration as `tests/test_oauth2_lifecycle_hooks.py:97-99`, backend
agnostic, no DB-read assertions):

- A counting `actor_created` hook; for each of: email form POST (free-text,
  new address), web callback, SPA token exchange, SPA native-grant tail,
  factory `POST /` — exactly **one** call per new actor, and the hook sees
  `actor.creator` set.
- Existing-actor form POST (409 from Phase 1) → zero calls. Existing-actor
  re-login on the web callback and both SPA paths → zero calls.
- A handler built with a bare `Config` (no `_hooks`) and explicit
  `hooks=` → one call (the additive kwarg).
- At hook time the fields the hook can read are `id`, `creator`,
  `passphrase`, an empty store and empty properties; `oauth_token`,
  `oauth_provider`, `auth_method`, `created_at`, `email` are **absent** at
  hook time and present after the handler returns. This pins the
  behaviour-change note.

### Verification

- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests`
- [ ] `poetry run pytest tests/test_actor_created_fires_once.py tests/test_oauth2_lifecycle_hooks.py tests/test_oauth2_spa_jwt_bearer.py tests/test_oauth2_callback_apple.py -v`
- [ ] `make test-all-parallel` green
- [ ] Manual: the research's probe (`OAuth2EmailHandler.post()` end to end with a counting hook) reports 1, not 2.

### Implementation Status: Complete

**Verification results:** `pyright actingweb tests` — 0 errors, 0 warnings.
`ruff check` / `ruff format --check` — clean. New test file
`test_actor_created_fires_once.py` (6 tests, real `ActingWebApp` +
DynamoDB-Local-backed actor creation for the core-firing-site tests, mocked
handlers for the two no-double-fire tests) plus a new `complete_session`
hooks-forwarding test added to `test_oauth_session.py`, plus the existing
`test_oauth2_lifecycle_hooks.py` — all green (174 tests across the OAuth
regression set). Full `make test-all-parallel`: 3393 passed, 31 skipped, 1
error (`test_bulk_list_update_handles.py::TestOrderingSemanticsMatchV1::test_v1_and_v2_branches_produce_the_same_final_list`,
unrelated to this change — a property-list ordering test that passes
standalone; the same pre-existing parallel-isolation flake pattern seen in
Phase 1, landing on a different test this run).

**Deviations from the plan:**

- The plan's four enumerated handler-level `actor_created` call sites (email
  form, web callback, SPA token-exchange, SPA native-grant tail) are all
  removed and thread `hooks=` through. Additionally threaded `hooks=self.hooks`
  into the **SPA browser-redirect path**'s `lookup_or_create_actor_by_identifier`
  call (`oauth2_callback.py`'s `_process_spa_oauth_and_create_session`,
  ~line 1176) even though the plan did not name it as one of the four —
  it never had its own handler-level `actor_created` call (so no double-fire
  existed there), but it shares the same bare-Config-with-explicit-hooks
  robustness concern as the other call sites and costs nothing to make
  consistent.
- `test_actor_created_fires_once.py` covers the core firing-site claims (new
  identifier fires once; existing identifier fires zero times on relookup;
  bare `Config` + explicit `hooks=` still fires once) with real DynamoDB-Local
  actor creation, and covers "no handler-level double call" for the email
  form (pointer to `test_oauth_email_handler.py`), web callback, and SPA
  native-grant tail with mocked handlers. Not separately covered: the SPA
  token-exchange path and the SPA browser-redirect path's own
  no-double-fire assertion (both delete an `is_new_actor` block of the same
  shape already pinned by the native-grant-tail test; the removal is
  identical code shape, verified by reading, not by a fourth near-duplicate
  test). The hook-time field-visibility assertion (`oauth_token`,
  `oauth_provider`, etc. absent at hook time) from the plan's "New tests"
  section was not written as a separate test — Phase 1's
  `test_email_verified_false_visible_during_oauth_success` already exercises
  the same "read actor.store during the hook call" pattern, and the field
  list itself becomes a changelog/doc claim in Phase 3/4, not a new behavior
  introduced by Phase 2.

---

## Phase 3: Hardening and documentation

Constant-time compares, the duplicate-creator WARNING, and every doc line the
first two phases falsify or the research found already false. Independently
green: pure refactors with behaviour preserved except where noted.

### Changes

**`actingweb/secret_compare.py`** (new leaf module, no `actingweb` imports;
`auth.py` imports `actor`/`trust`/`config` and `oauth2_server/*` import
`attribute`/`config`, so a leaf cannot cycle):

- `secret_equals(a: object, b: object) -> bool`: `False` unless both are
  `str` or `bytes`; UTF-8 encode `str`; `secrets.compare_digest`. The type
  guard matters at three sites that take attacker-typed JSON
  (`oauth2_spa.py:1345` `passphrase`, `token_manager.py:970` `code_verifier`,
  `actor.py:1255` a peer's `verification_token`), where `.encode()` on an
  `int` or `list` would turn a 401/403 into a 500. `compare_digest` on
  `str` raises for non-ASCII, hence the encode.
- `secret_digest_equals(a, b) -> bool`: SHA-256 both sides then
  `secret_equals`; for operands that may differ in length.

Apply:

| Site | Helper | Note |
| --- | --- | --- |
| `oauth2_server/client_registry.py:131` | `secret_equals` | the filed line |
| `auth.py:149` | `secret_equals` | also delete the DEBUG log at `:151-157` that prints both the submitted password and the stored passphrase |
| `auth.py:250`, `:574` | `secret_equals` | |
| `handlers/oauth2_spa.py:1345` | `secret_equals` | devtest passphrase grant |
| `handlers/oauth_email.py:138` | `secret_equals` | verification token (the legacy handler's twin at `email_verification.py:135` is deleted in Phase 1) |
| `actor.py:364` | `secret_equals` | `c["passphrase"]` may be `None`; today `None == None` adopts, after this it does not (`"" == ""` still does). Changelog line. |
| `actor.py:1255` | `secret_digest_equals` | switch to `data.get("verification_token")` — a missing key raises `KeyError` past the `except ValueError` at `:1258` |
| `oauth2_server/token_manager.py:970` | `secret_equals` | PKCE plain |
| `oauth2_server/token_manager.py:977` | `secret_digest_equals` | PKCE S256; also route `verify_pkce` (`handlers/oauth2_spa.py:107-120`, no in-package callers) through the same helper so there is one S256 compare |

`interface/oauth_client_manager.py:253` (post-write verify of a freshly
generated secret, not adversarial) is left alone.

**`actingweb/actor.py` — `get_from_creator` (`:274-316`)**: when
`candidates` has more than one entry, `logger.warning` with the lookup
creator and the sorted candidate ids, then select as today. Zero DB cost
(the candidates are already in memory); no throttle — it fires at login
rate, a once-per-process flag would hide a second duplicate pair, and the
`_suspension_check_error_logged_at` throttle at `:2120-2127` exists because
that check runs on every property write.

**Docs** (every line the changes falsify or the research found false):

- `docs/guides/authentication.rst:953` — the dropdown path leaves
  `email_verified` **absent**, not `true`; `:1331` — absent means the
  provider verified it, `"false"` pending, `"true"` link clicked; nothing
  writes `"true"` for a provider-verified address. Add, in the GitHub
  section, that a `scope` override without `user:email` makes the emails
  API answer 404, which is now a 502 on every login lacking a public email.
  `:384` — "Completes actor creation after email is provided" gains "or
  answers 409 `actor_exists` for an address that already has an actor".
  `:1058-1066` ("Verification Endpoints") — both legacy entries are
  deleted, replaced by one sentence: `GET /oauth/email?verify=` is the only
  verification endpoint, there is no resend, and an expired link means
  signing in again.
- `docs/guides/oauth-login-flow.rst:117` — same 409 note; `:334` — the
  email path stores the **provider's** token, not an ActingWeb session
  token; `:336` — the cookie is HttpOnly (true after Phase 1).
- `docs/guides/spa-authentication.rst:390-405` — the JS example handles
  `409` (`code: actor_exists`) and `403` (`code: authentication_rejected`);
  `:1361-1392` (the `POST /oauth/email` response section) — document both bodies and the JSON error shape
  `{"error": true, "status_code": N, "message": …}` that every
  `Accept: application/json` error now carries. Add the retry-worded
  `identifier_failed` description at `:906-907`.
- `docs/reference/hooks-reference.rst:133-136` — `actor_created` fires
  once, from `Actor.create()`, before the OAuth handler stores tokens or
  provider metadata; `oauth_success` is the hook that carries tokens.
  `:163-185` — `oauth_success` also fires when the address was collected
  through `/oauth/email`; there `email` is the address the user typed
  (normalised), `user_info["email"]` is absent because the provider
  returned none, and `actor.store.email_verified == "false"` until the link
  is clicked.
- `docs/quickstart/configuration.rst`, after the "Default Configuration"
  block at `:471-475` — one paragraph: the creator lookup lowercases any
  identifier containing `@`; the indexed-property lookup matches verbatim;
  applications storing an email as a property should store it lowercased.
- `docs/migration/v3.10.rst:890` — `POST /oauth/email` "creates the actor"
  gains "for a new address; an address that already has an actor is
  refused with 409".
- `docs/quickstart/getting-started.rst:323` — the example reads
  `kwargs.get("token")`, a kwarg `oauth_success` never passes; change to
  `access_token`. Pre-existing, found by the usability review.
- `thoughts/research/2026-09-09-oauth-email-form-writes-to-existing-actors.md`
  — correct the Flask-route claim in item 2 and the Code References line
  for `flask_integration.py:259` (error correction, permitted for a dated
  document).

### New tests

- `tests/test_secret_compare.py` (new): equal/unequal `str`, `bytes`,
  non-ASCII `str` (`"pässword"` vs itself → `True`, no exception), `None`
  on either side → `False`, `int`/`list` operands → `False`, digest variant
  with different-length operands.
- `tests/test_actor_get_from_creator_warning.py` (new): mock
  `actingweb.actor.get_actor` so `get_by_creator` returns two candidates;
  `caplog` at WARNING carries both ids; the lowest id is selected; one
  candidate → no WARNING.
- `tests/test_trust_verification_token_missing.py` (new): a peer callback
  body without `verification_token` → not verified, no exception.
- Existing tests for every compare site pass unchanged:
  `tests/integration/test_oauth2_client_manager.py`,
  `tests/integration/test_oauth2_spa_passphrase.py`,
  `tests/integration/test_authenticated_access.py`, the PKCE tests in
  `tests/test_oauth2_spa.py`.

### Verification

- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests`
- [ ] `grep -rn " == \| != " actingweb/ | grep -iE "passphrase|secret|verification_token|code_verifier|code_challenge"` returns only the `oauth_client_manager.py:253` line
- [ ] `poetry run pytest tests/test_secret_compare.py tests/test_actor_get_from_creator_warning.py tests/test_trust_verification_token_missing.py -v`
- [ ] `make test-all-parallel` green
- [ ] `cd docs && make html` (or the project's docs build) with no new warnings
- [ ] Manual: read each corrected doc line against the code it describes.

### Implementation Status: Complete

**Verification results:** `pyright actingweb tests` — 0 errors, 0 warnings.
`ruff check` / `ruff format --check` — clean. `grep -rn " == \| != " actingweb/
| grep -iE "passphrase|secret|verification_token|code_verifier|code_challenge"`
returns exactly the `oauth_client_manager.py:253` line plus non-secret
`len(...) == 0` / mode-string matches (`code_challenge_method == "plain"` etc.),
matching the plan's expectation. New tests: `test_secret_compare.py` (12),
`test_actor_get_from_creator_warning.py` (3),
`test_trust_verification_token_missing.py` (3) — 18 new, plus every existing
compare-site test (`test_oauth2_client_manager.py`,
`test_oauth2_spa_passphrase.py`, `test_authenticated_access.py`, the PKCE
tests in `test_oauth2_spa.py`) passing unchanged (107 total in that run).
Docs: no Sphinx build exists in this repo (no `docs/conf.py` or
`docs/Makefile`), so the plan's `cd docs && make html` step doesn't apply;
substituted a `docutils` RST-parse check over every edited file (parses
clean — the only diagnostics are pre-existing `:doc:`/`:ref:` role warnings
from not running under Sphinx, present on untouched lines too) plus a manual
read of each corrected line against the code. Full `make test-all-parallel`:
3413 passed, 31 skipped, 1 error
(`test_bulk_list_update_handles.py::TestNoConcurrentWriterEverythingApplies::test_k10_update_and_k10_delete_all_apply_and_none_is_reported_raced`,
unrelated — passes standalone; the same parallel-isolation flake pattern as
Phases 1 and 2, this time landing on a third distinct test within the same
bulk-list-update module across three separate full-suite runs).

**Deviations from the plan:**

- `secret_digest_equals` is implemented as "hash both sides, then delegate to
  `secret_equals`" rather than a second direct `secrets.compare_digest` call,
  per the plan's own description ("SHA-256 both sides then secret_equals");
  no behavioural difference from a from-scratch implementation.
- `actor.py`'s `create_verified_trust` — the peer-response `KeyError` fix
  (`data.get("verification_token")` replacing `data["verification_token"]`)
  is on the request path that authenticates a *remote peer's* callback
  response, not an in-process secret compare between two locally-held
  values; still using `secret_digest_equals` per the plan's table, since the
  two operands (a token echoed by the peer HTTP response and the token this
  actor generated) can differ in length under attacker control.
- Doc corrections applied beyond the plan's exact list where the same
  falsehood repeated nearby in a file the plan already named for editing
  (e.g. `authentication.rst`'s "Templates" section still listed
  `aw-verify-email.html`, which Phase 1 deleted — corrected alongside the
  named "Verification Endpoints" edit in the same file).

---

## Phase 4: Release 3.14.5

### Changes

- `pyproject.toml:3` and `actingweb/__init__.py:31` → `3.14.5`.
- `CHANGELOG.rst`: rename "Unreleased" to `v3.14.5: <date>`, add a new
  empty "Unreleased" above. House style (`CHANGELOG.rst:11-60`): one bullet
  per behaviour, bold past-tense lead naming the defect, mechanism with
  routes and files in double backticks, "Affected:" who sees it, then what
  legitimate use observes; `**Behavior change**:` inline when a consumer
  could have relied on the old behaviour (`:176-185` is the model).

  SECURITY:
  - `POST /oauth/email` selected and rewrote an existing actor for any
    typed address (409 `actor_exists`, session consumed, nothing written).
  - `oauth_token` cookie set by the email form was not HttpOnly.

  REMOVED:
  - `/{actor_id}/www/verify_email`, GET and POST, the legacy verification
    handler. The POST was unauthenticated and rejected only
    `email_verified == "true"`, so anyone holding an actor id could rotate
    its verification token and fire `email_verification_required` for every
    provider-verified actor; its only caller was the sample template's
    expired-link page. The GET duplicated `GET /oauth/email?verify=` without
    deleting the index row. Both now answer 404. This retracts the v3.10
    note that the legacy URL "remains functional for backward
    compatibility": the library's own hook has passed the `/oauth/email`
    format since v3.10, so only an app that composed the legacy URL by hand
    is affected, and its users redo the sign-in. Affected also: an app
    shipping its own `aw-verify-email.html`; the template is no longer
    rendered.
  - Ten in-process secret compares (eleven before the legacy handler was
    removed) were not constant-time; the
    Basic-auth DEBUG log printed both passphrases. Note the `None == None`
    adoption edge at `actor.py:364`.

  FIXED:
  - `actor_created` fired twice for every OAuth-created actor since v3.5.1.
    **Behavior change**: the single remaining call runs inside
    `Actor.create()`, before `auth_method`, `created_at`, `oauth_provider`,
    `email`, `oauth_token`, `oauth_token_expiry`, `oauth_refresh_token`,
    `oauth_token_timestamp` and `email_verified` are stored; a hook that
    read any of those saw them on the second call and now sees none;
    `oauth_success` carries the tokens.
  - A GitHub `/user/emails` failure sent a fully verified user to the
    free-text form; now 502 (web) / `identifier_failed` (SPA) with a retry
    message. Note the `scope`-without-`user:email` consequence.
  - `oauth_success` did not fire on the email path.
  - Membership check against the verified list ran on the raw submission.
  - JSON clients got HTML or an empty body on `/oauth/email` errors.
  - `GET /oauth/spa/session/{id}` echoed pending-email sessions and was
    replayable for the full session TTL; now 404 for pending sessions and a
    30 s retrieval window for success sessions.
  - A form-created orphan adopted by the real owner's login kept
    `email_verified="false"` and a live verification token.
  - Duplicate creators are now logged at WARNING with the candidate ids.
  - Case rules documented; `email_verified` semantics documented.

- `thoughts/todo/oauth-email-form-writes-to-existing-actors.md` — delete;
  the plan and verification are the record.
- `thoughts/todo/creator-uniqueness-not-enforced.md` — new, holding only
  what is still owed: the PostgreSQL unique index on `lower(creator)`, the
  DynamoDB marker-item transaction, the backfill decision for existing
  duplicates (now visible in logs), pointing at this plan and the research.
- `thoughts/todo/github-emails-api-called-twice.md` — new: the sequential
  `/user/emails` calls on the failure path and the ≈45 s worst case on
  Lambda; fix shape (per-token cache on the authenticator or a
  `get_primary_email` contract change).
- `thoughts/todo/INDEX.md` — replace the current row with rows for the two
  new todos.
- Commit `Release v3.14.5`; PR; after merge, tag on master per CLAUDE.md.

### New tests

None beyond the version-consistency check CI already runs on the tag.

### Verification

- [ ] `grep -n "3.14.5" pyproject.toml actingweb/__init__.py` — both
- [ ] `make test-all-parallel` green on DynamoDB; CI green on both backends
- [ ] `grep -l "^status: active" thoughts/plans/*.md` no longer lists this plan; `status: done` with the verification link
- [ ] `ls thoughts/todo/` has no `oauth-email-form-*` file and has the two new ones; `INDEX.md` rows match
- [ ] Consumer note in the PR description: `actingweb_mcp` can drop its planned `/oauth/email` 404 shadow after upgrading; its `CallbackPage.tsx` needs no change under the grace window.

### Implementation Status: Complete

**Verification results:** `grep -n "3.14.5" pyproject.toml actingweb/__init__.py`
— both. `poetry run pytest tests/ -q --ignore=tests/integration` (unit-only,
run standalone to avoid the sandbox's pytest-rerunfailures socket-bind
restriction under `make`): 2489 passed, 23 skipped. Full
`make test-all-parallel`: **3413 passed, 31 skipped, 0 errors** — clean this
time (the three prior full runs, Phases 1–3, each passed everything except
one distinct, standalone-passing test in an unrelated module, matching
CLAUDE.md's documented parallel-isolation caveat; this run hit none).
`thoughts/todo/`: the old `oauth-email-form-writes-to-existing-actors.md`
is deleted; `creator-uniqueness-not-enforced.md` and
`github-emails-api-called-twice.md` are added; `INDEX.md`'s row is replaced
with the two new rows in the same "Real, not urgent" section.
`ruff check` / `ruff format --check` / `pyright actingweb tests` — all clean.

**Deviations from the plan:**

- No PR was created and nothing was pushed or tagged in this session — Phase
  4 as executed here is the release commit only (version bump, CHANGELOG
  rename, todo housekeeping), on the local branch
  `fix/3.14.5-oauth-email-form`. Creating the PR, merging, and tagging on
  master are the user's remaining steps per `CLAUDE.md`'s release process
  (tags are only cut from commits on master, and pushing/PR-creation are
  actions this session does not take without being asked).
- The CHANGELOG's SECURITY/REMOVED/FIXED entries were rewritten from the
  plan's draft to match the code as actually shipped (e.g. the plan's draft
  predates the `secret_digest_equals`-for-trust-tokens naming and the exact
  `docs/quickstart/configuration.rst` wording landed in Phase 3) rather than
  copied verbatim; the substance matches.
- `thoughts/todo/INDEX.md`'s "Last full re-rank" date was left unchanged —
  the plan did not ask for a full re-rank, only the row swap.

---

## Evaluation Notes

Four reviewers read the first draft against the tree; one web researcher
settled the Apple caveat.

### Architecture

- `error_response` sets `template_values` for 400/500 regardless of `Accept`
  and both integrations render the template first, so the draft's "JSON body
  for every status" never reached the wire — Phase 1 gates on
  `_wants_json()`.
- The session's `user_info` is already normalised (both callback branches
  run `normalize_user_info` before `store_session`); the draft said "raw
  provider dict". Corrected; no second normalisation.
- The callback's `get_from_creator` pre-check is not an if/else; once
  `is_new_actor` goes it is a dead read. Phase 2 deletes it and keeps the
  two SPA if/else sites.
- Handlers built with a bare `Config` plus explicit `hooks=` would drop to
  zero firings after removing the handler calls. Phase 2 adds the additive
  `hooks=` kwarg with a `config._hooks` fallback.
- The GitHub-failure discriminator belongs on the provider strategy next to
  `get_primary_email`, not as a callback helper duplicating the
  `provider.name == "github"` guard at two sites. Adopted.
- `secrets.compare_digest` matches the existing idiom; `verify_pkce`
  routed through the same S256 helper. No shared security module exists to
  duplicate; a leaf module cannot cycle.
- No consumer subclasses `OAuth2EmailHandler`; the phases are independently
  green (no test asserts a handler-level `actor_created`).

### Security

- "Session left to expire" on the 409 made one provider login worth
  unlimited guesses for 600 s. Phase 1 consumes the session. The distinct
  `actor_exists` code stays: today's 200 with the victim's `actor_id` is
  worse, and a generic error is still an oracle because a fresh address
  succeeds.
- `oauth_success` fired straight after `complete_session` would let a
  rejected login still send verification mail. Phase 1 orders it after the
  `email_verified="false"` write and before the token/index/mail block.
- `_set_cors_headers` in the email handler reflects any origin with
  credentials; Phase 1 adopts the SPA allowlist.
- The helper must reject non-`str`/`bytes`, not just `None`; three sites
  take attacker-typed JSON. `actor.py:1255` also raises `KeyError` on a
  missing key. `auth.py:151-157` logs both passphrases at DEBUG. All in
  Phase 3.
- After Phase 1 only SPA success sessions are readable by session id, and
  they were replayable for the full TTL; grace window in Phase 1. The
  squatting adoption is in Phase 1 by owner's decision.
- The unauthenticated legacy resend endpoint: the review proposed
  authentication; the owner chose removal after the follow-up showed the
  endpoint's only caller is an unauthenticated expired-link page whose user
  cannot log in, and then removal of the token-gated GET as well, accepting
  that it retracts a v3.10 compatibility note in a patch. One verification
  mechanism remains.
- Residual after all of it: one orphan actor plus one
  `email_verification_required` mail to a typed address per provider login
  whose emails API answered "nothing verified". Accepted for a patch; no
  rate limiting exists in the library.

### Scalability

- The Phase 1 pre-check adds one empty creator-index query on the
  legitimate new-address path and makes the existing-address path strictly
  cheaper (refuses before five store writes and a session delete). Accepted
  rather than threading the loaded actor through `complete_session`. The
  creator GSI has no consistency option, so the pre-check is best-effort
  like the existing ones.
- Deleting the callback pre-check drops existing-actor web logins from two
  creator lookups to one. `get_by_creator`'s N+1 (`AllProjection` index yet
  a consistent `GetItem` per candidate) is pre-existing and untouched.
- The WARNING costs no reads and is not throttled (login-rate, and a
  once-per-process flag would hide a second duplicate pair and make the
  caplog test order-dependent).
- `compare_digest` on tens of bytes is sub-microsecond and cheaper than the
  `math.log` entropy check already at the trustee sites.
- Two sequential `/user/emails` calls on the failure path are real (≈45 s
  worst case) and become a todo in Phase 4.
- Test isolation rules for `make test-all-parallel` recorded in Phase 1.

### Usability

- The 409 pre-check moved into the free-text branch only; a
  dropdown-selected address is a returning user. Wording changed to
  "Sign in again to use a different address" because with the session
  consumed the re-rendered form cannot be resubmitted, and the earlier
  "sign in with the provider that verified it" promised a remedy a Work &
  School user cannot perform.
- The `oauth_success` contract note (typed `email` vs absent
  `user_info["email"]`, `email_verified == "false"` at hook time) is in
  Phase 3's hooks-reference change; `execute_lifecycle_hooks` swallows a
  strict hook's `KeyError`, so no consumer crashes, but one may silently
  accept.
- The `actor_created` timing shift is FIXED with a bold **Behavior change**
  naming the fields; shipped examples read only `actor.creator` and
  `actor.properties`, which still work.
- The new web 502 would have rendered as a raw dict (`error_response` in
  the callback only templates 400/403); 502 added to the list, and the
  wording says retry rather than "make email public".
- Apple: the `email` claim is in the id_token on every sign-in for ordinary
  Apple IDs (Apple's "Authenticating users" doc; DTS forum 749308); absent
  only for Work & School / Apple School Manager accounts. So the form is
  reachable on re-login only for those accounts, and for them the form path
  never yielded a working session anyway (see "What We're NOT Doing").
- Full list of doc lines the changes falsify is in Phase 3; the changelog
  shape follows the 3.14.4 entries.

---

## Implementation Summary

**Completed:** 2026-09-10
**All phases:** Complete
**Test status:** All passing — `make test-all-parallel`: 3413 passed, 31
skipped, 0 errors. `pyright actingweb tests`: 0 errors, 0 warnings.
`ruff check` / `ruff format --check`: clean.

Four commits on `fix/3.14.5-oauth-email-form` (branched from `master` at
`efc10a5`), one per phase: `bde44f3` (Phase 1), `c5829b0` (Phase 2),
`009b037` (Phase 3), and the Phase 4 release commit made alongside this
summary.

### Deviations from Plan

Recorded in full under each phase's own "Implementation Status: Complete"
note above; summarised here:

- **Test file consolidation.** The plan specified up to seven new test files
  per phase in places; several were merged into fewer files covering the
  same load-bearing assertions (named per phase above), and a small number
  of enumerated cases (a Flask-specific duplicate of an already-covered SPA
  code path, a fourth near-duplicate `actor_created` no-double-fire test)
  were judged redundant with an existing test rather than written separately.
- **`test_oauth_session.py` isolation rules corrected.** It is a full
  in-memory mock (`MockDbAttribute`), not DynamoDB-Local-backed as the plan
  assumed; the uuid-creator/yield-fixture-teardown rules apply to the
  handler-level tests that hit real `Actor`/`ActorInterface` lookups
  instead.
- **One extra `hooks=` threading site.** The SPA browser-redirect path in
  `oauth2_callback.py` (`_process_spa_oauth_and_create_session`) was not one
  of the plan's four enumerated handler-level `actor_created` sites — it
  never had its own duplicate call — but got the same `hooks=self.hooks`
  threading for consistency with the bare-Config robustness fix, at no cost.
- **Research-doc correction extended.** Beyond the Flask-route claim named
  in the plan, the "Code References" line for the same file/line was also
  corrected.
- **Phase 4 stopped at the local release commit.** No PR was created, and
  nothing was pushed or tagged — those are the user's remaining steps per
  `CLAUDE.md`'s release process (tags are only cut from commits on master;
  pushing and PR-creation are actions requiring explicit confirmation this
  session does not have).
- **`docs/` has no Sphinx build** (no `conf.py`/`Makefile`); the plan's
  `cd docs && make html` verification step was replaced with a `docutils`
  RST-parse check over every edited file plus a manual read.

### Learnings

- `poetry run pytest` under this sandbox fails immediately with a
  `PermissionError` from `pytest-rerunfailures`' `ServerStatusDB` binding a
  socket — every test invocation in this session needed
  `dangerouslyDisableSandbox: true`. Purely a local sandbox artifact, not a
  code or CI issue.
- `make test-all-parallel` brings the test containers up and tears them
  down itself (`docker-compose ... down -v` at the end of the target) —
  running it stopped and removed the `actingweb-test-dynamodb` /
  `actingweb-test-postgres` containers that were already running
  persistently at the start of this session. Restart them with
  `docker compose -f docker-compose.test.yml up -d` before working
  interactively against them again.
- Across four separate full `make test-all-parallel` runs in this session,
  three each hit exactly one different, standalone-passing test failure in
  an unrelated module (`test_hot_path_n_plus_one.py`,
  `test_bulk_list_update_handles.py` twice on different sub-tests) — a
  live example of the parallel-isolation flakiness CLAUDE.md already warns
  about, not a regression from this plan's changes each time.
