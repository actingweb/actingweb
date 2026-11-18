# Spec: OAuth client registration

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-17 by thoughts/plans/2026-11-17-3-16-pre-rc1-fixes.md
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

## Decisions in force

- **OCR-D1** — The trust row is written before the client row, so a client
  that exists always had a trust row created for it. (plans/2026-11-17-3-16-pre-rc1-fixes.md)

## Untested

- None of the above.
