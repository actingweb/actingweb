# Logout with an MCP token and an SPA refresh cookie revokes only the MCP chain

Found by the 3.15.1 code review; recorded in the verification
(`thoughts/verifications/2026-09-29-logout-does-not-revoke-refresh-chain.md`,
issue I10). Low; deferred by the owner.

`OAuth2EndpointsHandler._handle_provider_token_logout` returns
`_handle_mcp_token_logout(token)` as soon as the presented token has the MCP
prefix, and drops `refresh_tokens`. A request that carries an MCP Bearer token
and also an SPA `refresh_token` cookie (or a `refresh_token` in the body) gets
200 and every session cookie cleared, while the SPA chain the cookie named
stays live on the server; a copied cookie value keeps working. The request is
unusual (an MCP client does not hold SPA cookies), so the exposure is a
browser that is both at once.

Fix shapes, not evaluated: also route the presented refresh tokens through
`_handle_session_token_logout` when both are present, or leave the SPA cookies
unchanged on the MCP path so the response does not claim a logout it did not
perform. A route test with a real token manager on the double covers either.
