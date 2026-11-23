# Spec: OAuth client registration

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-23 by thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md
**ID prefix:** OCR

## Summary

An MCP or OAuth2 client registers (`POST /oauth/register`, anonymously on the
OAuth2 system actor, or `OAuth2ClientManager.create_client` for an actor's
owner) and gets credentials, backed by a trust row through which it is
authorized. This partial spec covers only what happens when that trust row
cannot be created.

## Registering

- **OCR-1** — When a registration cannot create the client's trust row (the
  actor is missing, the trust is refused, or an unexpected error occurs), it
  fails (500 `server_error` with fixed text naming no client and no actor on
  `POST /oauth/register`, `ClientRegistrationError` from `create_client`),
  returns no credentials and stores nothing. [plan+test]
  `tests/test_client_registration_trust.py::test_a_registration_without_its_trust_row_is_a_server_error`,
  `::test_the_server_error_names_no_client_and_no_actor`,
  `tests/integration/test_oauth2_flows.py::TestActingWebOAuth2Server::test_a_failed_registration_stores_nothing`,
  `tests/test_oauth2_public_clients.py::TestClientManager::test_create_client_raises_when_the_trust_row_cannot_be_created` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-5, AC-6, AC-8, AC-19)
- **OCR-2** — When a storage fault interrupts a registration after its trust
  row was written, the trust row is removed and the fault answers 503; a
  client row already written stays. [plan+test]
  `tests/test_client_registration_trust.py::test_a_fault_on_the_client_writes_raises_and_removes_the_trust_row`,
  `::test_a_fault_inside_trust_creation_after_its_row_removes_the_row` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-7)

## Deciding the level

- **OCR-3** — When an application calls one of the OAuth2 server's entry
  points (`complete_client_authorization()`, `handle_confirmation()`,
  `handle_oauth_callback()`) without `decide_trust`, the application's
  `oauth2_trust_requested` hooks decide: a hook that declines, or names
  another level than the one the user approved, sends the client back with
  `access_denied`; with no hook the requested level is granted if the
  client list accepts it. [plan+test]
  `tests/integration/test_oauth2_trust_binding.py::test_the_helper_asks_the_applications_decision_hook`,
  `::test_a_confirmation_called_directly_asks_the_applications_decision_hook` (plans/2026-11-15-3-16-release-validation.md)
- **OCR-4** — When a sign-in through `/oauth/callback` names `trust_type`
  in its state, the application's `oauth2_trust_requested` hooks decide
  (`confirmed=False`, no client id or name); a decline, an exception or
  another type than the one requested creates no trust, and the user is
  still signed in (a storage fault in a hook fails the sign-in). [plan+test]
  `tests/test_spa_trust_type.py::test_a_sign_in_naming_a_trust_type_asks_the_decision_hook`,
  `::test_another_type_declines_and_no_hook_keeps_the_request`,
  `::test_the_callback_asks_the_hook_before_it_writes_the_trust` (through
  `get()`) (plans/2026-11-15-3-16-release-validation.md; owner's decisions
  2026-11-18; iterations entry 2)

## Authorising

- **OCR-5** — When an authorisation request, a callback state or a code has
  no `code_challenge`, it is refused for every client unless
  `require_pkce=False`, which restores rc1's behaviour: a public client is
  refused at authorise only, and the callback and exchange accept a code
  without a challenge. [plan+test] `tests/test_oauth2_pkce_binding.py`
  (`test_a_confidential_client_without_a_challenge_gets_400`, the opt-out
  tests, `test_the_callback_refuses_a_state_without_a_challenge`,
  `test_the_exchange_refuses_a_code_without_a_challenge`) (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-37, AC-38, AC-49)
- **OCR-6** — When the authorise form is posted without the challenge it was
  shown with, the refusal is logged with what a custom form must carry.
  [plan+test] `tests/test_oauth2_pkce_binding.py::test_a_form_post_without_a_challenge_warns_about_the_form` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-52)

- **OCR-8** — When an authorization completes or is denied, the redirect
  keeps the registered redirect URI byte for byte and appends its
  parameters to the URI's query, before any fragment. [plan+test]
  `tests/test_oauth2_authorization_redirect.py`, `tests/integration/test_oauth2_trust_binding.py::test_the_helper_keeps_a_redirect_uris_own_query` (plans/2026-11-23-emm-4-0-rc2-production-observations.md, AC-12, AC-13, AC-26)

## Discovery

- **OCR-7** — When the server document is read, `client_credentials` is not
  offered; an owner-created client can still use it. [plan+test]
  `tests/test_oauth2_public_clients.py::test_discovery_does_not_offer_client_credentials`,
  `::test_an_owner_created_client_still_uses_the_grant` (plans/2026-11-19-emm-4-0-adoption-findings.md, AC-36)

## Decisions in force

- **OCR-D1** — The trust row is written before the client row, so a client
  that exists always had a trust row created for it. (plans/2026-11-17-3-16-pre-rc1-fixes.md)

- **OCR-D2** — `require_pkce=False` means the rc1 behaviour exactly, so an
  application can upgrade with it and change no sign-in, then enforce in a
  later change. (plans/2026-11-19-emm-4-0-adoption-findings.md)
- **OCR-D3** — The challenge travels through the authorise form's hidden
  fields; an application's own form, its own sign-in route calling
  `complete_client_authorization` (refused without a challenge before any
  hook or write), and any code it creates itself with
  `create_authorization_code`, must pass it on. (plans/2026-11-19-emm-4-0-adoption-findings.md)

## Untested

- OCR-3 through `handle_oauth_callback()` directly (it needs a provider's
  code); it decides through the same `_decided_type`.
- `complete_client_authorization` accepts a `plain` challenge method from
  the application's own route (rc1 behaviour; accepted 2026-11-20).
