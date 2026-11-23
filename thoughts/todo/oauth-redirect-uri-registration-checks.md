# Client registration accepts redirect URIs it should refuse

**Filed:** 2026-11-23, by the security evaluation of
`thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md` (Low).
Checked against the plan's branch.

Registration rejects a redirect URI only for userinfo
(`oauth2_server/client_registry.py:121`) and stores `redirect_uris` as
given (`:133`). Two gaps:

- **A fragment.** RFC 6749 §3.1.2 says a redirect URI must not include
  one. The redirect helper now keeps a fragment after the query, so the
  code reaches the client's server either way, but the registration should
  refuse it.
- **A value that is not a list of strings.** `validate_redirect_uri`
  answers `redirect_uri in registered_uris` (`:296`), which is a substring
  test when a client registered a string.

Both are refusals at registration, so they change what a registration
accepts: decide with the connector conformance follow-ups
(`mcp-oauth-connector-conformance-followups.md`). A test of a string
`redirect_uris` first; no layer above the registry was checked for it.
