# Spec: Web UI

**Status:** partial (covers: behaviour changed since 2026-11-17)
**Reviewed:** 2026-11-17 by Greger Wedel (with the plan)
**Last changed:** 2026-11-18 by thoughts/plans/2026-11-17-3-16-pre-rc1-fixes.iterations.md (entry 3)
**ID prefix:** WUI

## Summary

`/<actor_id>/www` is the actor's server-rendered web UI, on the Flask and
the FastAPI integration. This partial spec covers only signing in to it.

## Signing in

- **WUI-1** — When no OAuth provider is configured, an unauthenticated
  request for an actor's web UI is answered 401 with a `Basic` challenge in
  the application's realm, on both integrations, and the creator and
  passphrase sign in; with a provider configured it is redirected to
  sign-in, and a provider whose redirect cannot be built gets no `Basic`
  challenge. [plan+test] `tests/test_web_ui_basic_challenge.py` (Flask,
  FastAPI, configured provider, failing redirect, sign-in); manual browser
  walk 2026-11-17 (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-13 to AC-16, AC-20, AC-21)
- **WUI-2** — When a wrong creator or passphrase is sent to an actor's web
  UI, the answer is 403 with a text body saying to close the browser to try
  again; a 403 of another cause (an actor with no passphrase) does not say
  so. [plan+test] `tests/test_web_ui_basic_challenge.py::test_the_creator_signs_in_and_a_wrong_passphrase_is_refused`,
  `::test_a_403_that_is_not_a_wrong_passphrase_gets_no_retry_text` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-22, AC-24; iterations entry 3)
- **WUI-3** — When no provider is configured, a web UI request for an actor
  that does not exist is answered 404, on both integrations. [plan+test]
  `tests/test_email_verification_legacy_route.py::TestLegacyRouteNoLongerRegistered` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-23)

## Decisions in force

- **WUI-D1** — Only the web UI routes challenge with `Basic`; the actor root
  and `/properties*` do not, so a script's request opens no credential
  dialog. [test] `tests/test_web_ui_basic_challenge.py::test_flask_properties_keeps_its_bearer_401` (plans/2026-11-17-3-16-pre-rc1-fixes.md, AC-18)

## Not supported

- Signing out of a `Basic` session: "Logout" leaves the browser signed in
  until it is closed (walk of 2026-11-17).

## Untested

- None known.
