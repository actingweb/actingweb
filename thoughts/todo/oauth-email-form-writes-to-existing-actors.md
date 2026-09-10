# TODO: `POST /oauth/email` selects and rewrites existing actors; `actor_created` fires twice

**Status:** Open. Triaged 2026-09-09 from an inbound consumer report.
**Filed by:** Greger Wedel (with Claude), from `actingweb_mcp`, 2026-09-09, out
of the staff review of its "share an output document" proposal
(`actingweb_mcp/thoughts/research/2026-09-08-share-output-document.md`,
finding 14) and its todo `self-asserted-email-registration-path.md`.
**Record:** `thoughts/research/2026-09-09-oauth-email-form-writes-to-existing-actors.md`
holds the verification of all eight claims, the probe results, the deltas,
and the six decisions. This file says only what is still owed.
**Severity:** Medium. The form path yields no session for the selected
actor; the damage is whatever a consumer's `actor_created` hook does when
re-run, plus overwritten provider tokens and an unverified flag. The
consumer's hook un-suspends and re-grants a trial. The double-fire affects
every OAuth consumer with a non-idempotent hook, on every fresh sign-up.

## What is wrong

- `actingweb/handlers/oauth_email.py:379-390` fires `actor_created`
  unconditionally, and `complete_session` returns the existing actor when
  the typed address already has one, overwriting `oauth_token`,
  `oauth_refresh_token`, `oauth_provider`, and writing
  `email_verified="false"` plus a fresh verification token. Exercised.
- `actor_created` fires **twice** for every new actor on the callback, SPA
  and email paths: once in `Actor.create()` via `config._hooks`
  (`actingweb/oauth2.py:984-988` → `actingweb/actor.py:413-425`) and once at
  handler level. Since v3.5.1. No test counts calls. Exercised on the email
  path, read on the others.
- Both `require_email`-and-no-identifier branches of the callback
  (`oauth2_callback.py:425-445` web UI, `:1088-1142` SPA) store the
  provider's token response in the shared session bucket, which
  `/oauth/spa/session/<id>` echoes. The branch is reached by a GitHub
  `/user/emails` failure as well as by the no-verified-address case GitHub
  itself blocks.
- The email path skips `oauth_success`, so a consumer's rejection hook does
  not run; `email_verification_required` is fired with the caller-typed
  address.
- `email_verified` gates nothing and is never written `"true"` for a
  provider-verified address, contrary to `docs/guides/authentication.rst:953`
  and `:1331`.
- Membership check against `verified_emails` runs on the raw submission
  (`oauth_email.py:331-333`); the `oauth_token` cookie set at `:458-464` is
  the provider token and not HttpOnly, contrary to
  `docs/guides/oauth-login-flow.rst:336`.
- Eleven in-process `==`/`!=` secret compares, `client_registry.py:131`
  among them; `hmac` is not imported anywhere.
- Creator uniqueness is check-then-create in the OAuth callers, with an
  unconditional put on DynamoDB and a non-unique index on PostgreSQL;
  duplicates resolve silently to the lowest id at DEBUG.
- Creator lookup lowercases on `@`; the indexed-property lookup is verbatim.
  Diverges only for `email` properties an application writes itself.

## What has to be decided first

The six decisions are laid out in the research document. The ones that
block a plan:

1. **Does the self-asserted email flow survive, and in which branches?**
   Removing it closes items 1, 2, 4, 5 and the third-party-mail finding at
   once but deletes a documented v3.4/v3.10 feature; keeping it means gating
   the hook, firing `oauth_success`, and giving `email_verified` a reader.
2. **Where does `actor_created` fire, core or handler?** One site must go.
   Either choice is visible to every consumer with a non-idempotent hook.
3. Whether the constant-time sweep is one line or eleven, and whether
   creator uniqueness gets a schema change or a WARNING log, are separable
   and can trail.

## Constraints the plan inherits

- The MCP-authorization 502 for the no-email case (`oauth2_callback.py:415-422`)
  must stay.
- Any `email_verified` gate must treat *absent* as verified: the field is
  absent for every provider-verified and dropdown-selected actor today.
- A test that counts `actor_created` calls belongs with whichever hook
  option is chosen; none exists.
- The consumer verifies closure by creator lookup, not UI: a `POST
  /oauth/email` with any session id creates nothing and touches no existing
  actor; a no-email GitHub sign-in ends on a visible error with no actor row.
