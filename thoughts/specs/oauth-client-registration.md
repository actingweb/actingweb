# Spec: OAuth client registration

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-18 by thoughts/plans/2026-11-15-3-16-release-validation.iterations.md (entry 2)
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

## Decisions in force

- **OCR-D1** — The trust row is written before the client row, so a client
  that exists always had a trust row created for it. (plans/2026-11-17-3-16-pre-rc1-fixes.md)

## Untested

- OCR-3 through `handle_oauth_callback()` directly (it needs a provider's
  code); it decides through the same `_decided_type`.
