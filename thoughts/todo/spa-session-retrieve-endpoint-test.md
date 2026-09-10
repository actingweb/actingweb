# `GET /oauth/spa/session/{id}` has no endpoint-level test

3.14.5 changed what that endpoint returns, and only the layer beneath it is
tested.

**What changed.** `OAuth2SessionManager.retrieve_spa_session()` replaced a
bare `get_session()` in `FastAPIIntegration._handle_spa_session_retrieve`
(`actingweb/interface/integrations/fastapi_integration.py:2191`). Two
transitions came with it:

- A pending email-entry session (raw provider token response, no `actor_id`
  in `token_data`) used to be echoed back with the provider's token. It now
  answers 404.
- A server-managed PKCE session (`token_data={}`, `oauth2_spa.py:467`) moved
  from the 400 "Invalid session data" branch to the same 404. The 400 branch
  survives only as a defensive fallback.
- A success session is readable once freely and again inside
  `OAUTH_SESSION_RETRIEVE_GRACE` (30 s); past that the row is deleted and the
  answer is 404.

**What is tested.** `tests/test_oauth_session.py` covers
`retrieve_spa_session` at the manager level: pending session → `None`,
success session → dict with `retrieved_at` stamped, second call inside the
window → dict, call outside the window → `None` and the row deleted. That is
the logic that carries the security property, so this is a coverage gap, not
a correctness risk.

**What is missing.** Nothing drives the endpoint. The plan named
`tests/test_spa_session_retrieve.py` (FastAPI `TestClient`: pending → 404,
success → 200 with the token, second GET inside the window → 200, a session
stamped outside the window → 404) and it was never written. Neither is the
CORS allowlist on that endpoint's `cors_headers` covered.

**Shape of the fix.** One file, FastAPI `TestClient`, the four cases above
plus one origin-outside-`spa_cors_origins` case. `tests/test_spa_api_endpoints.py`
has the client setup to copy; note that `FastAPIIntegration.__init__`
registers nothing, so the fixture must call `setup_routes()` (see
`tests/test_email_verification_legacy_route.py`, which had that bug).

**Provenance.** Filed from
`thoughts/verifications/2026-09-10-oauth-email-form-writes-to-existing-actors.md`
(issue 1), verifying
`thoughts/plans/2026-09-10-oauth-email-form-writes-to-existing-actors.md`.
