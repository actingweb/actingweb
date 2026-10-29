# Research: three inbound reports — open JSON factory and OAuth adoption, list items over one row, SPA `prompt`

**Date:** 2026-10-26
**Branch:** master
**Commit:** 52abce6 (3.15.1 plus the LICENSE change; none of the code paths cited here changed after the v3.15.1 tag)

## Research Question

Triage of three reports, all filed from the Emm AI consumer project
(`actingweb_mcp`) and all read against ActingWeb 3.15.1:

1. `thoughts/inbound/json-factory-creates-actors-for-any-creator.md`, filed
   2026-10-23 by Greger Wedel with Claude, out of the share-a-document
   verification (local review round 5 on `feat/share-output-document`) and a
   trace of the library. Reproduced against a local preview server in the
   production configuration.
2. `thoughts/inbound/large-list-item-values.md`, filed 2026-10-18 from the
   Emm AI project while planning read-only HTML output documents
   (`actingweb_mcp/thoughts/plans/2026-10-18-read-only-html-output-documents.md`).
   Read, not exercised, by the reporter.
3. `thoughts/inbound/spa-authorize-prompt-select-account.md`, filed
   2026-10-17 by Greger Wedel with Claude, out of
   `actingweb_mcp/thoughts/plans/2026-10-17-share-output-document.md`.
   Not blocking the consumer.

Which claims hold against the tree, what did the check change, and what has
to be decided before anything is filed?

## Method

Every cited line was re-read at 52abce6. Nothing was exercised: report 1 was
reproduced by the reporter against a running server and the code path it
describes is short enough to confirm by reading; reports 2 and 3 are about
code shape, not runtime behaviour. Where a statement below is inferred rather
than read, it says so. The consumer's tree (`../actingweb_mcp`) was grepped
for how it configures the library and how its tests create actors.

## Summary

All three reports are confirmed on substance. The checks changed the shape of
each:

- **Report 1** is confirmed in every cited location and is wider than filed:
  the Flask integration has the same open route, the MCP OAuth server adopts
  existing actors through its own copy of the lookup, and the actors the MCP
  server creates carry no `auth_method` either. The deeper finding is that
  the ActingWeb protocol **requires** the JSON factory, and the vulnerability
  is a namespace collision between the spec's self-asserted `creator` username
  and OAuth's provider-verified email. The 2026-09-10 plan's Decision 1
  ("a provider-verified login of an existing actor is safe adoption") assumed
  the existing actor was legitimately created; this report shows the attacker
  can create it. The adoption hardening is therefore the fix; the switch the
  report leads with is defence in depth.
- **Report 2** is confirmed on all four claims. It is the same design space as
  the out-of-band payload requirement the next-major key-prefix todo already
  carries from the same consumer, and belongs there. Two small items are
  worth doing now: a typed too-large error and a documentation correction.
- **Report 3** is confirmed. `prompt=consent` and `access_type=offline` are
  hard-coded for every provider and both flows, not only the SPA. Google
  accepts a space-separated `prompt`, so the design is "always `consent`,
  additively accept `select_account` or `login`", not "replace the default".

## Report 1: the JSON factory creates an actor for any unclaimed creator

### Claims checked

| Claim | Where | Result |
| --- | --- | --- |
| Any JSON `POST /` reaches the factory with no auth check and no config gate | `interface/integrations/fastapi_integration.py:650-664` | **Confirmed.** Also true of Flask: `flask_integration.py:142-157` routes the same way. The report cites only FastAPI. |
| The handler takes `creator` and an optional caller-chosen `passphrase` from the body; `ui`/`www_auth` only change the response shape; `unique_creator` only refuses an address that already has an actor | `handlers/factory.py:199-298`, `actor.py:381-384` | **Confirmed.** One addition: with `unique_creator` on, `Actor.create()` returns the *existing* actor when the supplied passphrase matches (`actor.py:373-378`), so the factory doubles as a basic-auth login. Not a defect, but any gate has to decide whether that path stays. |
| Basic auth as the creator makes the caller the owner on every owner-guarded route | `auth.py:145-160` | **Confirmed.** Stronger than filed: `handlers/base_handler.py:163-166` selects the `basic` auth type for every path except `www`, regardless of `www_auth`. Setting `www_auth="oauth"` never disables creator basic auth on API routes. |
| `lookup_or_create_actor_by_identifier` adopts the squatted actor, sets `oauth_provider`, clears pending verification, does not rotate the passphrase, does not check how the actor was created | `oauth2.py:948-1003` | **Confirmed.** |
| `auth_method` is written only when OAuth creates the actor | `oauth2.py:1019-1023` | **Confirmed, and incomplete.** The MCP OAuth server has its own lookup-then-adopt (`oauth2_server/oauth2_server.py:826-832`), also without a marker check, and its create path (`:837-844`) writes **no** `auth_method` at all. The web factory-cookie path (`fastapi_integration.py:1499`, `flask_integration.py:685`), `oauth_session.py:351` and the SPA callback (`handlers/oauth2_spa.py:953`, `:1121`) all go through the `oauth2.py` lookup. Two adoption implementations, one marker writer. |
| No builder option or runtime switch turns JSON creation off | `interface/app.py` `with_*` methods, `config.py:80-90`, `docs/quickstart/configuration.rst:37-47` | **Confirmed.** |
| The changelog's `@app.actor_factory` decorator does not exist | `CHANGELOG.rst:4210` (v3.1 section, July 2025) | **Confirmed.** Nothing in `actingweb/`, `docs/` or `examples/` defines or mentions it. Stale changelog line; nothing to do but not repeat it. |

### What the check changed

1. **The factory is mandated by the protocol.** `docs/protocol/actingweb-spec.rst:560-566`:
   actors on a web server MUST implement dynamic instantiation by `POST` to
   the factory URI with optional JSON `creator`, `passphrase`, `trustee_root`.
   `creator` there is a self-asserted username. OAuth login reuses the same
   column as a provider-verified email identity. The vulnerability is that
   collision: an unverified claim on the name later satisfies a lookup that
   assumes the name was verified. Turning the factory off is a documented
   spec deviation for OAuth deployments, which is a legitimate choice, but it
   treats the symptom. The fix that respects both the spec and OAuth is
   "adopt only actors a provider vouched for; otherwise close the old door".
2. **This is the premise of a decision already made, not a new hole beside
   it.** `thoughts/plans/2026-09-10-oauth-email-form-writes-to-existing-actors.md`
   (status done) closed the sibling: a free-text `POST /oauth/email` can no
   longer adopt an existing actor (`create_only=True`). Its Decision 1 kept
   adoption for provider-verified logins and Phase 1 added clearing of
   "squatted pending-verification state" on adoption. Both assume the actor
   being adopted was created legitimately. The factory report shows the
   attacker creates the actor itself, with a passphrase of their choosing.
3. **A switch has to live in the handler, not the route.** The web-form branch
   falls back to `RootFactoryHandler.post()` directly when OAuth is not
   configured or its setup raises (`flask_integration.py:868-882`,
   `_handle_factory_post_without_oauth` in both integrations). Gating only
   the JSON branch of the route would leave that bypass.
4. **There is no pre-create hook.** `LifecycleEvent` (`interface/hooks.py:219-231`)
   has `actor_created` (after the row exists) and nothing before it, so a
   consumer cannot veto creation today. A veto hook is an alternative to a
   boolean switch; the boolean is simpler and what the report asks for.
5. **Both test suites depend on the JSON factory.** This repo's
   `tests/integration/conftest.py:712-745` (`actor_factory.create`) and the
   consumer's e2e and MCP integration tests (`tests/e2e/conftest.py:314`,
   `tests/integration/mcp/test_*.py`) all `POST /` with
   `json={"creator": ...}`. Any switch defaults on. The consumer runs
   `with_devtest(enable=...)` from `DEVTEST_MODE` and `with_unique_creator(True)`
   (`../actingweb_mcp/application.py:521`, `:561`).
6. **`oauth_provider` is not a substitute marker.** It is written on every
   OAuth sign-in including adoption (`oauth2.py:998-1001`,
   `oauth_session.py:372`), so after the victim signs in the squatted actor
   carries it too.

### The rotate-versus-refuse decision, with the residual

When an OAuth login adopts an actor that no provider created (no
`auth_method`, or, once the factory writes one, `auth_method="factory"`):

- **Rotate the passphrase, log a WARNING, then write `auth_method` to the
  provider value.** Closes the credential the squatter holds. Compatible
  with legacy actors created through the factory before OAuth creation
  existed (v3.4/v3.10) and with the factory-then-OAuth mixed case: the
  legitimate owner can read the new passphrase from `GET /<actor_id>` with
  their SPA session Bearer token: `auth.py:374-409` resolves a session token
  to `relationship="creator"`, and `handlers/root.py:62-66` returns the
  passphrase to the creator. Writing the marker after rotation makes it fire
  once.
  **Residual:** trust relationships and subscriptions the squatter created
  with basic auth before adoption survive; a peer secret in a trust row is a
  live credential. They are visible to the owner at `/<id>/trust`, but
  nothing removes them.
- **Refuse adoption.** Closes everything, including the trust-row residual.
  Locks out every legacy factory-created actor and every actor the MCP OAuth
  server created until that path writes a marker (it never has, so every
  MCP-created actor in every deployment is unvouched today). Could be a
  strict opt-in once the markers are complete.
- Either way the rule has to be applied at **both** adoption
  implementations, or the lookup consolidated into one. There are two, not
  three: `oauth_session.py:351` calls the deprecated
  `lookup_or_create_actor_by_email` wrapper, which returns
  `lookup_or_create_actor_by_identifier` (`oauth2.py:931-946`), so every
  web, SPA and email-form path funnels into `oauth2.py`; only the MCP OAuth
  server (`oauth2_server.py:826-832`) has its own copy.

Owner's call. Rotate-plus-WARNING is the compatible default; refuse is the
complete one.

### Not confirmed or not applicable

Nothing in the report was found wrong. The "Consumer side, meanwhile" options
are the consumer's; the second one (accept a share only from an actor with
`auth_method` set) would reject every MCP-created actor for the reason above.

## Report 2: a list item cannot be larger than one storage row

### Claims checked

| Claim | Where | Result |
| --- | --- | --- |
| `chunk_size` is written as `1` and never read; "chunked storage" means one item per row | `property_list.py:600`, `:676`, `:1165`, `:1194`; `docs/quickstart/configuration.rst:590` | **Confirmed.** `property_list.py:5` also says the module bypasses the 400 KB limit; it does so per list, not per item. |
| Update and delete are compare-and-swap on the whole raw string | `property_list.py:2537-2561`, `db/dynamodb/property.py:620-648` | **Confirmed.** `ListItemHandle` is one rank and one raw value (`:255-279`). |
| Nothing uses `TransactWriteItems` | `actingweb/`, `scripts/` | **Confirmed.** No occurrence in either. |
| PostgreSQL stores `TEXT`; its tests never hit the limit | PostgreSQL backend | **Confirmed** by reading; not exercised. |

### What the check changed

1. **How the limit surfaces.** An oversized item fails inside
   `Property.save()` and is re-raised as `DbError("property write", actor_id)`
   (`db/dynamodb/property.py:401-404`) wrapping the SDK's
   `ValidationException`. Nothing distinguishes "too large" from any other
   write fault, which is why the consumer had to invent a 380,000-byte cap
   of its own. A serialised-size pre-check (DynamoDB counts attribute names
   plus values; about 390 KB leaves headroom for the `id`/`name` keys) and a
   typed error are cheap and backend-neutral.
2. **It is already filed, from the other side.**
   `thoughts/todo/prop-list-key-prefix-scheme.md` carries "A second
   requirement: out-of-band per-item payload" from the same consumer
   (`thoughts/research/2026-08-29-bulk-list-reads-from-a-consumer.md`): large
   per-item bodies must be readable without paying for them on range reads.
   This report is the same requirement arriving from the limit side rather
   than the cost side, with five concrete constraints (atomic or
   generation-stamped commit, cheap first-row reads, cascade on delete and
   rank move, one item for diffs and `/properties`, a DynamoDB test path).
   A multi-row item needs `TransactWriteItems` (25 items per transaction on
   older SDK limits, 100 and 4 MB on current ones) and a row class the key
   shape can exclude, which is a storage-layout change with a migration, so
   it is next-major for the reasons that todo already gives.
3. **Two dead designs apply.** `thoughts/todo/whole-list-rewrite-atomicity.md`
   records what "changing where a list's rows live" gets wrong without a
   crash-recovery discipline; any multi-row design has to read them first.
4. **The consumer's fallback is the supported path today.** A body sidecar
   list keyed by output id, optionally compressed. The 2026-08-29 research
   (§6) found that a sidecar in the same partition still costs on a
   whole-partition dump but is excluded by the scoped bulk reads
   (`list_prefix_with_rows`) that 3.14 added, so the consumer's lists and
   previews need not pay for bodies.

## Report 3: let the SPA authorize flow ask the provider for account selection

### Claims checked

| Claim | Where | Result |
| --- | --- | --- |
| `prompt=consent` is fixed in the authorization URL | `oauth2.py:548-551` | **Confirmed.** `access_type=offline` is fixed beside it. Both go to every provider, including GitHub and Apple, which define neither and ignore them. |
| `POST /oauth/spa/authorize` reads a fixed set of fields | `handlers/oauth2_spa.py:416-424` | **Confirmed:** `provider`, `trust_type`, `redirect_uri`, `pkce`, `token_delivery`, `return_path`, plus `code_challenge`/`code_challenge_method` under `pkce=client`. |
| The consumer cannot work around it | — | **Confirmed.** The URL is built from `create_authorization_url(...)` (`oauth2.py:498-507`), which has no parameter for it. |

### What the check changed

1. **Google takes a space-separated `prompt`.** `prompt=select_account consent`
   shows the chooser and still returns a refresh token, so the design is not
   "keep `consent` as the default" but "always include `consent`, additively
   accept `select_account` or `login`". Nothing else should be accepted
   (`none` would break the flow); unknown values answer 400, as the report
   asks.
2. **The seam exists.** `OAuth2Provider.authorize_extra_params()`
   (`oauth2.py:122`, Google at `:230`, Apple at `:425`) is where per-provider
   authorize parameters already live. A `prompt` request maps through it:
   Google appends the value; GitHub and Apple drop it (GitHub has no such
   parameter; Apple re-prompts on its own after the user revokes the app).
3. **Both flows are affected, not only the SPA.** The web factory form's
   redirect (`flask_integration.py:858-865`) builds the same URL. The report
   asks only for the SPA field; the web flow has no client to pass a choice,
   so leaving it alone is fine, but the parameter belongs on
   `create_authorization_url`, not on the SPA handler.
4. **Tests exist to extend.** `tests/test_oauth2_spa.py:574-700` already
   covers `/oauth/spa/authorize` request validation.

## Open decisions

1. Rotate or refuse on adoption of an unvouched actor (above). Whether
   refuse becomes a strict opt-in later.
2. Whether `Actor.create()`'s "existing actor, matching passphrase" return
   (`actor.py:373-378`) survives when the factory is closed. It is a login,
   not a creation, and only reachable with `unique_creator` on.
3. Release shape: a builder option and config flag make a **minor** under the
   release rules; the adoption hardening and the `auth_method` marker change
   behaviour but no API shape and can ship as a **patch** with a SECURITY
   entry and a **Behavior change** line. Either one 3.16.0 carrying all of
   report 1 and report 3, or 3.15.2 (hardening, markers, typed size error,
   doc corrections) followed by 3.16.0 (the switch, SPA `prompt`).
4. **Who vouches for app-created actors.** The unvouched set is larger than
   "factory-created". Actors created by consumer code through
   `ActorInterface.create()` (the report lists this as a legitimate path),
   by `trustee_root` instantiation through the factory, and by the
   system-actor bootstrap carry no marker either. Under a rotate rule, a
   consumer that creates an actor for a user's address and keeps the
   passphrase for API use loses it on that user's first OAuth login; under a
   refuse rule those users are locked out. Either an `auth_method` argument
   on `ActorInterface.create()` (default `"app"`, treated as vouched) or a
   documented rule that the app writes the marker itself. Phase (a) below
   has to cover this, not only the two library creation paths.
5. Report 2: decline multi-row items now and fold the constraints into the
   key-prefix todo, or open a separate next-major todo that the key-prefix
   todo links to.

## Proposed disposition

- **Report 1** → a plan (not a todo: the owner reproduced it and the consumer
  is waiting). Phases, roughly: (a) `auth_method` written on every creation
  path (`"factory"` in `handlers/factory.py`, the provider value in
  `oauth2_server.py`, and the app-created answer from decision 4);
  (b) adoption rule at both implementations, or one consolidated lookup,
  rotate or refuse per decision 1, WARNING either way; (c) `with_open_factory(enable)`
  / `config.open_factory`, gated in `RootFactoryHandler.post()` so the
  no-OAuth form fallback is covered: 403 for JSON, and the HTML form, which
  already only starts OAuth when OAuth is configured, also answers 403 on its
  no-OAuth fallback (nothing else could create there); (d) docs: Runtime
  Switches, `docs/reference/security.rst` (new row under "OAuth2"), the spec
  deviation named, including that closing the factory also closes
  `trustee_root` instantiation (one actor creating another through the
  factory, which the spec describes), and a migration-guide note. The release gating is the
  consumer's `DEVTEST_MODE`, not a library tie between `devtest` and the
  factory: the report suggests the tie, but coupling two switches hides one.
- **Report 2** → amend `thoughts/todo/prop-list-key-prefix-scheme.md` with a
  fourth requirement carrying the five constraints and this provenance;
  one new small todo for the typed too-large error and the two wording fixes
  (`configuration.rst:590`, `property_list.py:5`); reply to the consumer
  that the sidecar is the supported path.
- **Report 3** → a todo (`spa-authorize-prompt.md`) sized at one parameter,
  one provider-seam method, one handler field, tests; schedule it with the
  report 1 minor.
- Delete the three inbound files once the owner confirms the dispositions.
