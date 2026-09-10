# Research: OAuth email-entry form writes to existing actors, plus adjacent auth hardening

**Date:** 2026-09-09
**Branch:** master
**Commit:** efc10a5 (3.14.4)

## Research Question

Triage of the inbound report `thoughts/inbound/oauth-email-form-writes-to-existing-actors.md`:
eight claims about the OAuth email-entry flow (`/oauth/email`) and adjacent
authentication code. Which claims hold against the tree, what did the check
change, and what has to be decided before a plan is written?

## Provenance (carried from the deleted inbound report)

- **Filed by:** Greger Wedel (with Claude), from the `actingweb_mcp` repo, 2026-09-09.
- **Came out of:** the staff review of the "share an output document" proposal,
  `actingweb_mcp/thoughts/research/2026-09-08-share-output-document.md`
  (finding 14, the "Prerequisite" section, staff review S1–S2), and the todo
  `actingweb_mcp/thoughts/todo/self-asserted-email-registration-path.md`.
- **Checked by the reporter against:** this checkout at `efc10a5`. Items 1–2
  were traced end to end; items 3–8 were read but not exercised.
- **Consumer status at triage:** `actingweb_mcp` intends to shadow
  `GET`/`POST /oauth/email` with a 404 in its own routes. At triage time no
  such shadow exists in the consumer tree (grep for `oauth/email` in its `.py`
  files returns nothing).

## Method

- Every cited line was re-read at `efc10a5`. Three sub-agents covered items
  3–5, items 6–8, and the external references.
- Items 1, 2, 4 and 5 were **exercised** against DynamoDB Local (port 8001,
  `test` table prefix) with a probe script that drove
  `OAuth2EmailHandler.post()` directly with a stored `OAuth2SessionManager`
  session and a counting `actor_created` hook, then deleted the actor. The
  probe leaves TTL'd session rows and two verification-token index rows for a
  deleted actor in the `test`-prefixed tables; both expire on their own.
- Items 3, 6, 7 and 8 were read, not exercised. Where a claim is inferred
  from code rather than run, the text says so.

## Summary

Seven of the eight claims are confirmed on substance; the eighth (item 6,
"the only non-constant-time compare") is confirmed for the cited line but the
"only" is wrong by a factor of eleven. The core defect (item 1) reproduces
exactly as filed: a second `POST /oauth/email` with a throwaway session and an
address that already has an actor returns that actor, overwrites its stored
provider tokens, marks it unverified with a fresh verification token, and runs
the consumer's `actor_created` hook against it. The caller still gets no
usable session for the actor.

The check changed three things the report did not say. First, **`actor_created`
fires twice for every new actor created through any OAuth path** — once inside
`Actor.create()` via `config._hooks` and once at handler level — and has done
so since the `config._hooks` wiring landed in v3.5.1 (2025-12-01). No test
asserts the call count. Second, the SPA branch the report wants rejected at
source (item 2) is a mirror of the **web-UI branch that stores the identical
session**; that branch is the designed feature, documented in three guides and
in the v3.10 plan, so "reject at source" is a product decision about the
self-asserted email flow as a whole, not a one-branch fix. Third, the pending
session stores the provider's access token, and `GET /oauth/spa/session/<id>`
echoes `token_data.access_token` for any session in the bucket, so a pending
email session is readable through the SPA session endpoint (read, not
exercised). A fourth delta reshapes the first decision: GitHub documents that
it refuses to authorise an OAuth app for an account without a verified
primary email, so the report's precondition is closed for ordinary accounts,
while a failed `GET /user/emails` call sends a fully verified GitHub user to
the free-text form instead (item 1, "Reaching it").

Adjacent hardening items 3, 7 and 8 are real but each carries a scope delta:
`email_verified` is read only by the two verification handlers themselves and
the library never writes `"true"` for a provider-verified address despite the
docs saying it does; the check-then-create race lives in the OAuth callers,
not in the `unique_creator` branch the report cites (that branch is off by
default); and the two case rules only diverge for `email` *properties* an
application writes itself, since the library's own sign-in paths all use the
lowercasing creator lookup.

## Detailed Findings

### 1. `POST /oauth/email` re-runs `actor_created` on an existing actor — CONFIRMED, exercised

**The path.** `OAuth2EmailHandler.post()` (`actingweb/handlers/oauth_email.py:270-513`)
validates `"@" in email` (`:303`), loads the session (`:318-324`), and if the
session carries no `verified_emails` accepts any address (`:355-359`). It then
calls `complete_session` (`:362`), which normalises the address
(`actingweb/oauth_session.py:193`) and calls
`lookup_or_create_actor_by_email` → `lookup_or_create_actor_by_identifier`
(`actingweb/oauth2.py:939-978`). That function returns the **existing** actor
when the creator lookup hits (`:971-978`) and, as a side effect, rewrites
`store.oauth_provider` on it (`:975-977`). Back in `complete_session`, the
caller's provider tokens are written to the actor (`oauth_session.py:211-218`)
and the session is deleted (`:220-229`).

**The hook.** `oauth_email.py:379-390` fires `actor_created` unconditionally;
the comment "if this is a new actor" is not implemented. The other three
sites gate on a local `is_new_actor` flag computed by a `get_from_creator`
pre-check: `actingweb/handlers/oauth2_callback.py:533-540` and `:653-665`,
`actingweb/handlers/oauth2_spa.py:872-883` and `:901-912`, and `:1042-1050`
and `:1068-1078`.

**Verification-state writes.** When no `verified_emails` were in the session,
`:393-425` sets `store.email_verified = "false"`, a new
`email_verification_token`, `email_verification_created_at`, and a
token→actor row in the `EMAIL_VERIFY_TOKEN_INDEX_BUCKET` under the system
actor with a 24 h TTL (`actingweb/constants.py:165-167`).

**Probe result** (DynamoDB Local, `Accept: application/json`, provider `github`,
no `verified_emails`):

| Step | Result |
| --- | --- |
| First POST, `probe.existing@example.com` | 200, actor created, `actor_created` fired **2×**, `oauth_token=tokA`, `email_verified="false"` |
| Second POST, new session, `Probe.Existing@Example.com` | 200, **same actor id**, `actor_created` fired 1× more, `oauth_token=tokB`, `oauth_refresh_token=tokB-r`, `oauth_provider=github`, `email_verified="false"`, new verification token |

**What the caller gets.** The JSON body includes `actor_id` and
`access_token = store.oauth_token` (`oauth_email.py:492-494`), i.e. the
caller's own provider token; the browser path sets it as an `oauth_token`
cookie (`:454-465`). Presenting that token as Bearer against the actor goes
through `_check_oauth2_token` (`actingweb/auth.py:290-370`) or its async twin
(`:475-540`), both of which fetch userinfo from the provider, require an email
(`:313-315`, `:503-504`) and require it to equal `actor.creator` (`:322-326`,
`:507-511`). A provider that returned no email at the callback returns none
here either, so the token is refused. The pending session is deleted on
completion, and `/oauth/spa/session/<id>` only echoes stored data
(`actingweb/interface/integrations/fastapi_integration.py:2264-2298`). The
report's "no session for that actor" holds.

**Blast radius of the overwritten tokens.** In the library, `store.oauth_token`
is only read by the logout paths that null it
(`actingweb/handlers/oauth2_endpoints.py:1007-1013`,
`actingweb/handlers/oauth2_spa.py:1724-1730`); nothing calls the provider on
the user's behalf with it. The consumer reads `oauth_refresh_token` on
`actor_deleted` to revoke at the provider
(`actingweb_mcp/hooks/actingweb/lifecycle_hooks.py:283`) and forwards the
`oauth_token` cookie as a Bearer header in its template helper
(`actingweb_mcp/helpers/template_helpers.py:145-146`). The practical impact of
the token overwrite is therefore that the victim's stored provider credential
is replaced by the caller's, which the victim's next login overwrites again.
The `actor_created` re-run is the impact that matters, and it is entirely
consumer-defined: the consumer's hook
(`actingweb_mcp/hooks/actingweb/lifecycle_hooks.py:191-262`) sets
`service_status="active"`, re-grants the trial, resets onboarding and review
watermarks, forces `agent_os="true"`, zeroes `mcp_usage_count`, reseeds
instruction templates and default memory types.

**Two hooks the email path does not fire.** The callback and SPA paths fire
`oauth_success` and treat a falsy return as a 403
(`oauth2_callback.py:667-696`, `oauth2_spa.py:914-940`). `oauth_email.py`
fires `actor_created` and `email_verification_required` only. A consumer's
`oauth_success` rejection or profile-sync logic — the consumer registers one
at `actingweb_mcp/hooks/actingweb/lifecycle_hooks.py:418` — does not run on
the self-asserted path.

**A third party can be sent mail.** `email_verification_required` fires with
`email=<caller-supplied address>` and a live verification URL
(`oauth_email.py:442-448`). Any consumer that registers it sends a
verification email to whatever address the caller typed. `actingweb_mcp`
does not register it; other `require_email` consumers may.

**Reaching it.** The form is reachable only from a session stored by one of
the two `require_email`-and-no-identifier branches (item 2). Identifier
extraction (`oauth2.py:824-878`) takes `user_info["email"]` first, then, for
GitHub, the module-level `_get_github_primary_email` (`:1164-1210`), which
requires `primary` and `verified`, falls back to any `verified` entry, and
returns `None` on any non-200 or exception (`:1187-1189`, `:1209-1210`).
`get_github_verified_emails` (`:887-937`) has the same non-200 → `None`
shape. Two routes therefore reach the no-identifier branch:

1. **A GitHub account with no verified address.** The reporter's premise.
   GitHub's own documentation says an OAuth app cannot be authorised without
   a verified primary email; the token exchange returns
   `unverified_user_email` (External References, GitHub). Neither the
   reporter nor this triage tested it, but the documented behaviour makes
   this route closed for ordinary accounts. Enterprise Managed Users, whose
   addresses are a placeholder and unverified until confirmed (GitHub
   changelog, 2025-02-13), are the documented exception, and GitHub un-verifies
   an address that bounces.
2. **A transient failure of `GET /user/emails`.** Any non-200 (rate limit,
   outage, a token whose `user:email` scope was not granted — the community
   thread in External References shows a 404 in that case) makes both helpers
   return `None`, so a GitHub user with a perfectly verified address lands on
   the **free-text** form with no `verified_emails` list, and any address they
   type is accepted. This route was read, not exercised; it does not depend on
   the account's state and is available to any GitHub login while the API
   call fails.

Google always returns `email` with the `email` scope. For Apple the library
takes `user_info` from the validated id_token claims
(`oauth2.py:420-426`) and merges the one-time `user` JSON (name/email,
first sign-in only, `oauth2_callback.py:152-155`, `:863-880`) on top; whether
Apple's id_token carries `email` on every re-login was not verified here. If
it does not, an Apple re-login under `require_email` would also reach the
form, for the user's **own** existing actor. With that caveat the branch is
GitHub-shaped in practice unless a consumer adds a provider with an optional
email claim.

### 1a. `actor_created` fires twice for every new OAuth actor — NEW, exercised on one path

`lookup_or_create_actor_by_identifier` calls `ActorInterface.create(...,
hooks=getattr(self.config, "_hooks", None))` (`oauth2.py:984-988`), which
passes `hooks` into `Actor.create()`; that method fires `actor_created` itself
(`actingweb/actor.py:413-425`). `config._hooks` is set to the app's registry
whenever `get_config()` runs (`actingweb/interface/app.py:1320`, `:1327`). The
three OAuth handlers then fire `actor_created` again at handler level
(`oauth_email.py:388`, `oauth2_callback.py:663`, `oauth2_spa.py:910`, `:1076`).

- Probe: `lookup_or_create_actor_by_identifier` alone → 1 call; the email
  handler end to end → 2 calls for a new actor. The callback and SPA handler
  paths are the same shape by code reading, not exercised.
- History: handler-level firing dates from #17 (`613cc27`, 2025-10-04); the
  `config._hooks` wiring that made the core-level fire live is #29
  (`bc7107e`, v3.5.1, 2025-12-01, CHANGELOG line 2743 "config._hooks was
  never set"). Every OAuth-created actor has fired twice since v3.5.1.
- The factory path (`actingweb/handlers/factory.py:247-252`) passes
  `hooks=self.hooks` into `create()` and has no second call: single-fire.
- No test asserts the call count. `tests/test_oauth2_lifecycle_hooks.py`
  checks that `config._hooks` is attached and says it cannot exercise
  creation (`:117-119`). Grep of `tests/` for `actor_created` next to
  `len(`, `call_count` or `assert_called_once` finds nothing.
- Consumer effect: the consumer's hook is not idempotent (see item 1), so a
  fresh sign-up runs the seeding twice. Whether that is observable depends on
  each write being a set rather than an append; `_initialize_default_memory_types`
  and `_apply_install_unchecked` are the two to check on the consumer side.

### 2. SPA callback stores a pending session when the provider returns no email — CONFIRMED, with a scope delta

`_process_spa_oauth_and_create_session` (`oauth2_callback.py:1088-1142`)
stores the provider `token_data` in `OAUTH_SESSION_BUCKET` via `store_session`
and 302s to `{origin}/callback?email_required=true&session=<id>`. The MCP
authorization branch of the web callback hard-rejects the same case with a
502 (`:415-422`).

**Delta.** The web-UI branch of the same callback stores the identical session
and 302s to `/oauth/email?session=<id>` (`oauth2_callback.py:425-445`). That
is the original feature: the email form and verification flow were added in
v3.4 (CHANGELOG 2914-2926), and the SPA branch was added in v3.10 explicitly
"to match the Web UI flow behavior"
(`thoughts/plans/2026-02-24-github-auth-actingweb-library.md:273-283`,
CHANGELOG 2101-2109). It is documented in `docs/guides/authentication.rst:940-1000`,
`docs/guides/spa-authentication.rst:350-425` and `:1324-1392`, and
`docs/guides/oauth-login-flow.rst:94-116`. Rejecting only the SPA branch
leaves the web-UI branch storing the same session for the same form.

**Also stored: the provider access token.** The pending session's `token_data`
is the provider's token response. The SPA success path stores its session in
the same bucket through the same `store_session`
(`oauth2_callback.py:1269-1300`), and `_handle_spa_session_retrieve`
(`fastapi_integration.py:2238-2298`) returns `token_data.get("access_token")`
for any session id it finds, with `actor_id` and `email` as `None` for a
pending-email session. Probe confirmed the stored value is the raw provider
token; the endpoint itself was read, not exercised.

**Correction (2026-09-10, Phase 3 review):** the claim above that the Flask
integration "registers the same route" is wrong. `flask_integration.py:259`
registers `/oauth/spa/session` (the session-*check* compat route, no `<id>`
path segment), not a `/oauth/spa/session/<id>` retrieval route. Flask has no
equivalent of FastAPI's `_handle_spa_session_retrieve`; the finding above is
FastAPI-only. See the Code References line below for the same correction.

**Documentation claims that do not match the code.** `oauth-login-flow.rst:336`
says the HTML flow of `POST /oauth/email` sets an "HttpOnly cookie" (it does
not, item 5); `authentication.rst:953` and `:1331` say `email_verified` is
`"true"` when the provider verified the address (never written, item 3).

### 3. Nothing reads `email_verified` — CONFIRMED on substance

Inventory across `actingweb/` (sub-agent, full grep):

| Kind | Sites |
| --- | --- |
| Writers | `oauth_email.py:148` (`"true"`), `:408` (`"false"`), `handlers/email_verification.py:147` (`"true"`) |
| Readers | `oauth_email.py:109`, `email_verification.py:102`, `:222` — all "already verified?" short-circuits inside the verification handlers |
| Auth/permission readers | none in `auth.py`, `oauth2_spa*.py`, `permission_*.py`, `aw_proxy.py`, `actor.py`, `interface/**`, `handlers/base_handler.py`, `www.py`, `root.py`, `factory.py` |

`is_private_email` appears nowhere in `actingweb/`, `tests/` or `docs/`.
`get_email_from_user_info` (`oauth2.py:824-878`) reads only `user_info["email"]`;
`GoogleOAuth2Provider` (`:175-252`) and `AppleOAuth2Provider` (`:322-445`)
never consult `email_verified`. Apple and Google mock claims carrying
`email_verified` in `tests/test_oauth2_callback_apple.py:139` and
`tests/test_apple_provider.py:81` are ignored by the code under test.

**Delta.** `verified_emails` is populated only for GitHub
(`oauth2_callback.py:406-409`, `:1100-1103`). No library path writes
`email_verified = "true"` for a provider-verified address: the dropdown path
skips the `:393` block and Google/Apple never reach the form. So the field has
three states in practice — absent (provider gave an email, or user chose from
the GitHub dropdown), `"false"` (self-asserted, pending), `"true"` (link
clicked) — and any future gate has to treat absent as verified.

**Two verification mechanisms coexist.** The legacy
`/{actor_id}/www/verify_email` GET/POST (`handlers/email_verification.py`,
registered at `fastapi_integration.py:702-708` and `flask_integration.py:203-205`)
validates against the same store fields, does not delete the token-index row
on success (the new handler does, `oauth_email.py:154`), and its POST resend
emits the new `/oauth/email?verify=` URL format (`:253-255`).

### 4. Verified-membership check runs on the raw submission — CONFIRMED, exercised

`oauth_email.py:331-333` tests `email not in verified_emails` on the raw
string; `strip().lower()` happens at `oauth_session.py:193`, after the check;
the list was lowercased at `oauth2.py:927`. Probe: `Probe.Existing@Example.com`
against `["probe.existing@example.com"]` → 403; the lowercase form → 200.

**Wire behaviour.** The branch discriminator at `:337` is `config.ui`, not
`Accept`:

| `config.ui` | Handler | On the wire |
| --- | --- | --- |
| True | `set_status(400)` + `template_values` (`:338-348`) | Flask `:1063` and FastAPI `:1895` render the template **without** passing the status → 200 HTML with the error text |
| False | `error_response(403)` (`:350-353`); no body written, 403 is outside the `[400, 500]` template branch (`:519`) | 403 with an empty body on both integrations; the returned dict is discarded (`flask_integration.py:1052`, `fastapi_integration.py:1883`) |

**Who hits it.** The GET form and JSON both return the lowercased list
(`:246`, `:263`), and the sample template renders `<option value=...>` from it
(`tests/integration/templates/aw-oauth-email.html:87-101`), so an app-supplied
dropdown always submits lowercase. The library's own fallback forms
(`flask_integration.py:1099-1105`, `fastapi_integration.py:1931-1937`) render a
free-text `<input type="email">` even when `verified_emails` is populated, so
a consumer without `aw-oauth-email.html` exposes hand-typed input to this.

### 5. `oauth_token` cookie without `httponly` — CONFIRMED, exercised

`oauth_email.py:458-464` passes `secure=True` only; `AWResponse.set_cookie`
defaults `httponly=False, samesite="Lax"` (`actingweb/aw_web_request.py:65-85`).
Probe: cookie recorded as `('oauth_token', httponly=False, secure=True, 'Lax')`.
Neither integration adds `httponly` (`flask_integration.py:639-648`,
`fastapi_integration.py:1412-1419`; the FastAPI generic path also drops
`path` and `samesite`, so Starlette defaults apply).

Every other credential cookie in the library is HttpOnly: `oauth2_callback.py:817`
(`oauth_token`, an ActingWeb token minted by `config.new_token()`, 1 h),
`:756` and `:1288` (`refresh_token`, Strict, path-scoped), `oauth2_spa.py:1639-1668`
(`access_token`, `oauth_token`, `refresh_token`). The email-form cookie is the
one site that stores the **provider's** access token rather than an ActingWeb
token, and the one without HttpOnly. `docs/guides/authentication.rst:56-62`
describes the HttpOnly variant.

### 6. Client secret compared with `!=` — CONFIRMED for the line, "only" is WRONG

`actingweb/oauth2_server/client_registry.py:131` is `if stored_secret != client_secret:`,
called from the token, refresh and revoke endpoints
(`oauth2_server/oauth2_server.py:489`, `:538`, `:572`) and
`interface/oauth_client_manager.py:198`. `hmac` is not imported anywhere in
the package.

In-process `==`/`!=` on a secret (sub-agent inventory):

| # | Site | Compares |
| --- | --- | --- |
| 1 | `oauth2_server/client_registry.py:131` | MCP client secret |
| 2 | `auth.py:149` | Basic-auth passphrase |
| 3 | `auth.py:250` | Bearer token vs trustee passphrase (sync) |
| 4 | `auth.py:574` | same, async |
| 5 | `handlers/oauth2_spa.py:1345` | SPA passphrase grant (devtest only) |
| 6 | `handlers/oauth_email.py:138` | email verification token |
| 7 | `handlers/email_verification.py:135` | same, legacy handler |
| 8 | `actor.py:364` | `unique_creator` passphrase adoption |
| 9 | `actor.py:1255` | trust `verification_token` echoed by peer |
| 10 | `oauth2_server/token_manager.py:970` | PKCE `plain` |
| 11 | `oauth2_server/token_manager.py:977` | PKCE `S256` challenge strings |

Constant-time today: `oauth2_id_token.py:139`, `:142` (id_token nonce) and
`handlers/oauth2_spa.py:120` (`verify_pkce`, which has no in-package callers).
Trust secrets, MCP access/refresh tokens, authorization codes, SPA tokens,
state nonces and mobile tickets are all looked up **by** the secret as a
database key, so no in-process compare exists for them.

There is no in-process CSRF/state comparison: the web callback discards the
csrf element of the decoded state (`oauth2_callback.py:267`), and the MCP
state path is Fernet-decrypt plus timestamp (`oauth2_server/state_manager.py:97-104`);
the `csrf_token` written at `:61` is never read back.

### 7. Actor uniqueness is check-then-create — CONFIRMED, cited location is the non-default branch

`actor.py:341-370` runs only under `config.unique_creator`, which defaults to
`False` (`actingweb/config.py:80`, `interface/app.py:69`). In the default
configuration `Actor.create()` does no creator lookup and goes straight to an
unconditional write with a fresh id (`:378-385`). The check-then-create
pattern lives in the callers, none atomic with the write:

- `oauth2.py:971-989` (`lookup_or_create_actor_by_identifier`)
- `oauth2_spa.py:872-883`, `:1042-1050` and `oauth2_callback.py:538-545` — each
  a `get_from_creator` pre-check **in front of** the one above, so two check
  layers before one create
- `oauth2_server/oauth2_server.py:730-737`
- `handlers/factory.py:233-253`

Backends: DynamoDB `create()` is a consistent point read on `id` then
`Actor(...).save()` with no `condition=` (`db/dynamodb/actor.py:143-147`);
`creator_index` is a plain GSI with no consistency option (`:21-30`, `:103`).
PostgreSQL `create()` is `SELECT ... WHERE id` then a plain `INSERT`
(`db/postgresql/actor.py:140-153`); `ix_actors_creator` is `unique=False`
(`db/postgresql/migrations/versions/3307e3616c5e_initial_postgresql_schema.py:25-33`,
`db/postgresql/schema.py:40`); no later migration touches `actors`.

Duplicate selection: `actor.py:306` sorts candidates by id and takes the first
that loads; the docstring at `:277-280` states this. Both backends log
multiple matches at DEBUG only. `thoughts/todo/dynamodb-known-next.md` item 6
covers trust-secret uniqueness on the `secret-index` GSI, not creator
uniqueness; nothing in `todo/` covers creator uniqueness.

### 8. Two email lookups, two case rules — CONFIRMED, divergence is app-property only

Creator path lowercases when `@` is present, at every layer:
`actor.py:290`, `db/dynamodb/actor.py:101-102` / `:139-140` / `:119-120`,
`db/postgresql/actor.py:75-76` / `:133-134` / `:194-195`, `factory.py:227-230`,
`oauth_session.py:193`, `oauth2.py:851` / `:859`. Probe: `get_from_creator`
with `Probe.Existing@Example.com` found the actor created as lowercase.
Identifiers without `@` (`github:123`, `apple:sub`) rely on the provider
having lowercased them (`oauth2.py:159`, `:311`).

Indexed-property path is verbatim on both backends, read and write:
`db/dynamodb/property_lookup.py:12-13`, `:49-54`, `:126-127`, `:179`;
`db/postgresql/property_lookup.py:40-47`, `:87-105`; writers
`db/dynamodb/property.py:411`, `:441`, `db/postgresql/property.py:379`. The
read chain `ActorInterface.get_by_property` → `Actor.get_from_property` →
`get_actor_id_from_property` has no normalisation step.

**Delta.** The library never writes an `email` *property*. Its own email
storage is `store.email` in the `_internal` attribute bucket
(`oauth2.py:1004`, `:1015`), which the lookup table does not index. Every
built-in sign-in path uses the creator lookup. The divergence is observable
only for `email` values an application stores via `properties.email = ...`
(the consumer's `actor_created` hook does exactly that,
`actingweb_mcp/hooks/actingweb/lifecycle_hooks.py:198`) and then queries via
`get_by_property`.

## Decisions Needed

### Decision 1: Does the self-asserted email flow survive, and in which branches?

The report's fix for item 2 rejects the SPA branch only. The web-UI branch
stores the same session for the same form and is the documented feature.

**Options:**

1. **Remove the self-asserted flow in both branches.** Both no-identifier
   branches take the `identifier_failed` / 502 exit the MCP branch already
   uses. Closes items 1, 2, 4, 5 and the verification-email-to-a-third-party
   finding at once. Costs: the v3.4/v3.10 feature and three guides' worth of
   documentation, the `email_verification_required` / `email_verified` hooks
   lose their only trigger (the legacy resend endpoint still fires the first),
   and a GitHub user with no verified address has no recovery path. Against
   that: GitHub documents that such a user cannot authorise the app in the
   first place, so the feature's stated purpose targets a case the provider
   already blocks, and what the branch actually catches today is the
   `/user/emails` failure route. The consumer already wants this outcome for
   itself.
2. **Keep both branches; make the flow safe.** Gate `actor_created` on actual
   creation (see Decision 2), fire `oauth_success` on the email path so a
   consumer's rejection hook runs, and either refuse to complete when the
   address already has an actor or make `email_verified` gate something
   (Decision 3). Keeps the feature; each of items 1, 3, 4, 5 becomes its own
   small change.
3. **The report's asymmetric fix.** Reject in the SPA branch, leave the web-UI
   branch. Cheapest; leaves the same form reachable by any consumer with
   `with_web_ui(True)` and a GitHub login, which is every consumer the report
   says is exposed.

### Decision 2: Where does `actor_created` fire — core or handler?

One of the two sites has to go. **Core** (`Actor.create()` with `hooks=`)
fires only on actual creation and already covers the factory path; keeping it
means deleting the three handler-level calls and their `is_new_actor`
pre-checks, and the email handler's unconditional call disappears with them.
**Handler** means removing the `hooks=` argument from
`lookup_or_create_actor_by_identifier` (`oauth2.py:988`), keeping the
`is_new_actor` flags, and fixing `oauth_email.py` to gate. Either way the
change is user-visible for every consumer with a non-idempotent hook, and
none of it is tested today. A test that counts calls belongs with whichever
option is chosen.

### Decision 3: What does `email_verified` gate, if anything?

Today it gates nothing and has three states (absent, `"false"`, `"true"`),
with absent meaning "provider-verified or dropdown". Options: (a) gate the
provider-token auth paths (`auth.py:290`, `:475`) and SPA token issuance on
`!= "false"`; (b) document that consumers must check it themselves and fix
the two doc lines that claim `"true"` is written for provider-verified
addresses; (c) both. A Google/Apple `email_verified` claim check is a separate
question — those providers never reach the form, and the claim is currently
dropped at `oauth2.py:849-851`.

### Decision 4: Constant-time compares — the one line or the eleven?

Item 6 as filed is a one-line change. The inventory shows eleven sites of the
same shape; the highest-traffic are the Basic-auth passphrase (`auth.py:149`)
and the trustee-passphrase Bearer path (`:250`, `:574`). A sweep is mechanical
(`hmac.compare_digest` on `.encode()`d strings, guarding `None`) and could ride
in the same PR or its own.

### Decision 5: Creator uniqueness — data-model change or accept the race?

The race needs a conditional write keyed on the creator (DynamoDB: a second
item `creator#<value>` written with `attribute_not_exists` in a
`TransactWriteItems`; PostgreSQL: a unique index, on `lower(creator)` if the
non-`@` identifiers are to be covered too) plus a migration and a backfill
decision for existing duplicates, which `actor.py:306` currently resolves by
lowest id. It touches both backends and is the only item with a schema
change. The alternative is to leave it and log duplicate matches at WARNING
instead of DEBUG so an operator can see them.

### Decision 6: One case rule for property lookups?

Lowercasing values in the lookup table changes what an existing backslash
or mixed-case row matches and would need a backfill; the alternative is a
documented rule that `email`-shaped indexed properties are stored lowercased
by the application, and a note in the consumer's `manage_actors.py`.
Any change here is a minor, not a patch.

## Code References

- `actingweb/handlers/oauth_email.py:270-513` — `POST /oauth/email`; `:303` `@`-only validation; `:331-333` raw membership check; `:362` `complete_session`; `:379-390` unconditional `actor_created`; `:393-425` verification state and token index; `:442-448` `email_verification_required` with caller-supplied address; `:458-464` cookie without HttpOnly; `:492-494` provider token in JSON body
- `actingweb/oauth_session.py:57-118` — `store_session`, one bucket for pending-email, PKCE and SPA-success sessions; `:161-233` `complete_session`, normalise at `:193`, token overwrite `:211-218`, delete `:220-229`
- `actingweb/oauth2.py:939-978` — `lookup_or_create_actor_by_email` → `lookup_or_create_actor_by_identifier`, returns existing actor and rewrites `oauth_provider`; `:984-988` passes `hooks=config._hooks` into create
- `actingweb/actor.py:413-425` — core-level `actor_created`; `:274-316` `get_from_creator`, lowercase at `:290`, lowest-id selection at `:306`; `:341-370` `unique_creator` branch; `:378-385` unconditional create path
- `actingweb/handlers/oauth2_callback.py:415-422` — MCP 502; `:425-445` web-UI pending session; `:533-540`, `:653-665` `is_new_actor` gate; `:667-696` `oauth_success`; `:1088-1142` SPA pending session; `:1148-1160` `identifier_failed` exit; `:1269-1300` SPA success session in the same bucket
- `actingweb/handlers/oauth2_spa.py:872-883`, `:901-912`, `:1042-1050`, `:1068-1078` — SPA `is_new_actor` gates; `:1639-1668` HttpOnly cookies; `:1724-1730` logout nulls `oauth_token`
- `actingweb/auth.py:290-370`, `:475-540` — provider-token auth requires provider email equal to creator; `:149`, `:250`, `:574` non-constant-time compares
- `actingweb/interface/app.py:1320`, `:1327` — `config._hooks` wiring
- `actingweb/interface/integrations/fastapi_integration.py:693-698` — `/oauth/email` routes; `:2238-2298` `/oauth/spa/session/<id>` echoes `token_data.access_token`; `:1412-1419` cookie translation drops `path`/`samesite`; `:1895` template rendered without status
- `actingweb/interface/integrations/flask_integration.py:198` — `/oauth/email`; `:259` `/oauth/spa/session` check route (not a `<id>` retrieval route — see correction above; Flask has no equivalent of FastAPI's `_handle_spa_session_retrieve`); `:639-648` cookie translation; `:1063`, `:1099-1105` template and free-text fallback form
- `actingweb/handlers/email_verification.py` — legacy `/{actor_id}/www/verify_email`; `:135` compare; `:147` writes `"true"`; no index-row delete
- `actingweb/oauth2_server/client_registry.py:131` — `!=` on client secret; `actingweb/oauth2_server/token_manager.py:970`, `:977` PKCE compares
- `actingweb/db/dynamodb/actor.py:21-30`, `:101-103`, `:139-147` — plain GSI, lowercase on `@`, unconditional `save()`
- `actingweb/db/postgresql/actor.py:75-88`, `:133-153` — unconstrained SELECT, lowercase on `@`, plain INSERT; `db/postgresql/migrations/versions/3307e3616c5e_initial_postgresql_schema.py:25-33` non-unique creator index
- `actingweb/db/dynamodb/property_lookup.py:12-13`, `:49-54`; `actingweb/db/postgresql/property_lookup.py:40-47` — verbatim lookup
- `actingweb/constants.py:165-167`, `:181` — verification token length/TTL, session TTL
- `tests/test_oauth2_lifecycle_hooks.py:117-119` — states creation is not exercised; `tests/test_oauth_session.py:208-290` — `complete_session` with a mocked authenticator; no test of the existing-actor case or of hook counts
- `docs/guides/authentication.rst:940-1000`, `:953`, `:1331`; `docs/guides/spa-authentication.rst:350-425`, `:1361-1392`; `docs/guides/oauth-login-flow.rst:94-116`, `:336` — documented contract, including the two claims the code does not implement
- `thoughts/plans/2026-02-24-github-auth-actingweb-library.md:273-283`, `:355-379` — design intent for the SPA branch
- `actingweb_mcp/hooks/actingweb/lifecycle_hooks.py:191-262`, `:283`, `:418` — consumer's `actor_created`, `actor_deleted` token read, `oauth_success`
- `actingweb_mcp/thoughts/todo/self-asserted-email-registration-path.md` — the consumer-side record

## External References

**GitHub OAuth and the verified-email precondition (items 1–2)**

- https://docs.github.com/en/apps/oauth-apps/using-oauth-apps/authorizing-oauth-apps — "You must verify your email address before you can authorize an OAuth app."
- https://docs.github.com/en/enterprise-cloud@latest/apps/oauth-apps/maintaining-oauth-apps/troubleshooting-oauth-app-access-token-request-errors — the `unverified_user_email` token-exchange error: "The user must have a verified primary email."
- https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app — same error for GitHub Apps.
- https://docs.github.com/en/rest/users/emails — `GET /user/emails` schema: per-entry `primary`, `verified`, `visibility`; scope `user:email`.
- https://docs.github.com/en/account-and-profile/concepts/email-addresses — "If an email address is undeliverable or bouncing, it will be unverified."
- https://github.blog/changelog/2025-02-13-verify-email-address-to-secure-enterprise-managed-user-accounts/ — EMU addresses are a placeholder and unverified until confirmed; "Some GitHub Apps and OAuth apps may not handle this placeholder email properly."
- https://github.com/orgs/community/discussions/46257 — `/user/emails` returning 404 when the `user:email` scope was not granted.

**The mutable-email-claim class (item 3)**

- https://www.descope.com/blog/post/noauth — nOAuth (June 2023): Entra ID `email` claim "is both mutable and unverified so it should never be trusted or used as an identifier"; mitigation is keying on `sub`.
- https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims-reference — `email`: "never use it for authorization or to save data for a user"; `xms_edov` domain-verified flag; `oid` as the database key.
- https://www.semperis.com/blog/noauth-abuse-alert-full-account-takeover/ and https://www.semperis.com/blog/noauth-abuse-update-pivot-into-microsoft-365/ — 2025 follow-ups: 9 of 104 and later 11 of 142 Entra gallery apps still vulnerable.
- https://openid.net/specs/openid-connect-basic-1_0.html — `email_verified` semantics; `sub` is the only claim that "MUST be locally unique and never reassigned".
- https://developers.google.com/identity/openid-connect/openid-connect — `email_verified` claim; "Always use the `sub` field" as the identifier.
- https://developer.apple.com/forums/thread/746352 and https://developer.apple.com/forums/thread/808659 — Apple staff quoting the reference: `email_verified` and `is_private_email` may be the JSON **strings** `"true"`/`"false"` (a truthy `"false"` in Python), and `email_verified` is `"false"` for Work & School users.

**Normalisation-ordering in auth paths (item 4)**

- https://github.com/advisories/GHSA-7rqj-j65f-68wh and https://nvd.nist.gov/vuln/detail/CVE-2026-73420 — the reporter's citation exists: Auth.js, July 2026, CVSS 9.1, "Email normalizer validates the address before Unicode normalization". Different mechanism (homoglyph `@` under NFKC), same class: validation on one form, use on another.
- https://github.com/advisories/GHSA-g38m-r43w-p2q7 — CVE-2026-53516, Better Auth: OAuth auto-link to an unverified pre-registered local account; the closest published match to "self-asserted address selects an existing account".
- https://github.com/nextauthjs/next-auth/security/advisories/GHSA-xv97-c62v-4587 — CVE-2022-35924, the Auth.js fix that introduced `normalizeIdentifier` and normalise-before-use.
- https://www.djangoproject.com/weblog/2019/dec/18/security-releases/ — CVE-2019-19844: case-insensitive lookup plus mail to the *submitted* address; the fix compares with a Unicode-aware equivalence and sends to the **stored** address. The reference pattern for the `email_verification_required` payload.
- https://dev.to/jagracey/hacking-github-s-auth-with-unicode-s-turkish-dotless-i-460n — GitHub's 2019 password-reset collision, same fix.

**Constant-time comparison (item 6)**

- https://www.rfc-editor.org/rfc/rfc6749.html, https://www.rfc-editor.org/rfc/rfc6819.html, https://www.rfc-editor.org/rfc/rfc9700.html — none mentions timing; RFC 9700 §2.5 recommends asymmetric client authentication instead.
- https://cwe.mitre.org/data/definitions/208.html — Observable Timing Discrepancy; "the comparison of the entire string should be done all at once".
- https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html — compare "in constant time, to protect against timing attacks".
- https://docs.python.org/3/library/hmac.html — `hmac.compare_digest`: same-type operands, ASCII-only for `str`; differing lengths still leak length. Argues for comparing digests of both sides rather than raw secrets.

**Uniqueness constraints (item 7)**

- https://aws.amazon.com/blogs/database/simulating-amazon-dynamodb-unique-constraints-using-transactions/ — the marker-item pattern: `creator#<value>` item with `attribute_not_exists` in the same `TransactWriteItems`.
- https://www.postgresql.org/docs/current/indexes-expressional.html — `CREATE UNIQUE INDEX ... ON t (lower(col))` "can be used to enforce constraints that are not definable as simple unique constraints"; must be an index, not a table constraint.
- https://www.postgresql.org/docs/current/indexes-partial.html — partial unique index for exempting placeholder rows.

**Email case rules (item 8)**

- https://www.rfc-editor.org/rfc/rfc5321.txt §2.4 — local part "MUST BE treated as case sensitive" but "exploiting the case sensitivity of mailbox local-parts impedes interoperability and is discouraged"; domains are case-insensitive.
- https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html — lowercase the domain always; fold the local part only under an explicit, documented policy applied "consistently across registration, login, password reset, account recovery, and account linking"; store original and canonical.
- https://github.com/portier/portier.github.io/blob/master/specs/Email-Normalization.md — an identity broker that lowercases the whole address for matching.

## Recommendations (added the same day, at the owner's request, under a no-breaking-changes constraint)

"Breaking" here means: a public signature, a registered route, a documented
response shape, a hook's kwargs, or a schema migration that can fail on
existing data. Behaviour that only a bug depends on is not protected.

### Decision 1 → keep the flow, close its inputs (option 2, narrowed)

Keep both branches and the `/oauth/email` routes, hooks and docs. Three
changes close the exposure without touching any of them:

1. **Distinguish API failure from "no verified emails".** Today
   `_get_github_primary_email` and `get_github_verified_emails` both return
   `None` for a non-200 and for an empty list. Return `[]` for "GitHub
   answered, nothing verified" and `None` for "GitHub did not answer", and
   have both callback branches treat `None` as the existing
   `identifier_failed` / 502 exit. The genuinely-no-verified-email case still
   reaches the form, exactly as documented. This alone removes the one
   realistic route in (item 1, "Reaching it", route 2). Note the dropdown
   branch is reachable only if the first API call fails and the second, made
   milliseconds later, succeeds: with this change it becomes honest dead code
   and can stay.
2. **Refuse to complete the form for an address that already has an actor.**
   `complete_session` (or the handler before it) does a `get_from_creator`
   and returns a distinct failure; the handler renders the form with an
   error in UI mode and a 409 JSON in SPA mode. No hook runs, nothing is
   written, no mail is sent. The only legitimate user this affects is one who
   already has an actor and reaches the form, and their remedy is to sign in
   with the provider that verified the address, which is what the error says.
3. **Fire `oauth_success` on the email path** with the same kwargs the
   callback passes (`email`, `access_token`, `token_data`, `user_info`), and
   honour a falsy return as 403. Additive for consumers: the hook is
   documented as firing on OAuth login, and today it silently does not here.

Also in this bucket, both non-breaking: `_handle_spa_session_retrieve`
returns 404 for a session without `actor_id` in its `token_data` (a pending
email session was never meant to be readable there); and `_get_github_*`
treat a 404 from `/user/emails` as failure, not as empty.

### Decision 2 → core fires, handlers stop

Remove the four handler-level `actor_created` calls
(`oauth_email.py:379-390`, `oauth2_callback.py:653-665`,
`oauth2_spa.py:901-912`, `:1068-1078`) and keep `Actor.create()`'s. Core is
already the only firing site for the factory path and for the MCP OAuth
server's `_get_or_create_actor_for_email`
(`oauth2_server/oauth2_server.py:736-742`), so it is the established
convention and the handler calls are the outliers. The `is_new_actor`
pre-checks can go with them (the SPA one also saves a DB read; keep that
part).

One semantic shift to name in the plan: the core call runs inside `create()`,
**before** the handler stores `oauth_token` on the actor, whereas the
handler-level call ran after. A consumer hook that reads
`store.oauth_token` inside `actor_created` saw a value on the second call
and will now see none. The consumer's hook does not; `oauth_success` is the
hook that carries tokens. Add a test that counts exactly one call per new
actor on each of the four paths, and zero on the existing-actor form POST.

### Decision 3 → no auth gate; fix the docs; opt-in claim check later

Do not gate `auth.py` on `email_verified`. It would lock out every actor
that came through the form and never clicked the link, and with Decision 1
in place the field protects nothing reachable: a self-asserted address that
differs from the provider's can never pass the provider-token check
(`auth.py:322-326`), and the form never mints an ActingWeb token, so a
fake-address actor is an orphan row, not an access path. Fix
`authentication.rst:953` and `:1331` to say absent means provider-verified
and `"true"` means link-clicked. Reading Google's and Apple's
`email_verified` claim is a separate, opt-in item: Google Workspace
accounts on non-Google-hosted domains and Apple Work & School users carry
`false`, so a default-on check is a login regression for them. If added,
gate it behind a per-provider flag defaulting off, and handle Apple's string
`"false"`.

### Decision 4 → all eleven, one helper, same PR

Purely internal. A `_secret_equals(a, b)` that encodes both sides, handles
`None`, and calls `hmac.compare_digest`; apply at the eleven sites. The
PKCE `S256` compare and the trust `verification_token` compare are the two
where the operands can be different lengths, which `compare_digest` handles
but leaks length; compare SHA-256 digests of both sides there.

### Decision 5 → log now, constrain later, separate plan

Enforcing creator uniqueness is a schema change on PostgreSQL (a unique
index on `lower(creator)` fails to build if duplicates exist) and a
transactional-write change on DynamoDB (marker items, plus deletion-path
cleanup), and `unique_creator=False` is the documented default that
*permits* duplicates. Not this plan. What fits now: `get_from_creator` logs
at WARNING with the candidate ids when it finds more than one, so operators
can see whether the race has ever fired. Leave the todo open for the
constraint.

### Decision 6 → document, do not change the lookup table

Lowercasing values in the lookup table changes what existing rows match and
needs a backfill. Document that the creator lookup lowercases on `@` and the
indexed-property lookup is verbatim, and that applications storing an email
property should store it lowercased. The consumer's `manage_actors.py` fix
is on their side.

### Items 4 and 5 → straight fixes

Normalise (`strip().lower()`) at the top of `post()` before the membership
check. Add `httponly=True` to the cookie at `oauth_email.py:458`; the value
is only ever read server-side and every other credential cookie in the
library is already HttpOnly.

### What a consumer sees after all of it

No route, hook name, kwarg, response field or config option changes. Two
behaviours change, both only where a bug was: a form POST for an address
that already has an actor fails instead of rewriting it, and `actor_created`
fires once instead of twice. Both belong in the changelog under FIXED, not
CHANGED, with the token-timing note for the hook.

### Suggested phase order for the plan

1. Decisions 1.1–1.3, item 4, item 5, the session-endpoint 404, and the
   existing-actor refusal, with the three consumer acceptance tests from the
   report (form POST touches nothing; no-email sign-in ends on an error with
   no actor row; MCP 502 unchanged).
2. Decision 2, with the call-count test.
3. Decision 4 sweep.
4. Docs: Decision 3 and 6 corrections, changelog.
5. Decision 5 WARNING log. The constraint itself stays in `todo/`.
