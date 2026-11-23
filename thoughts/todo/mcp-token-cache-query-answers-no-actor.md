# The token-cache query says yes or no; middleware needs the actor

**Filed:** 2026-11-23, from a consumer's review of the rc3 work
(`thoughts/research/2026-11-23-emm-review-of-rc3.md`). Checked against
`fix/4.0.0-rc3-consumer-fixes` at `61f2167`. Additive, small.

`actingweb.mcp.is_token_cached(token, config)` returns `bool`. The
consumer that asked for a cache query has a guard in front of `/mcp` that
refuses a suspended account. When `validate_access_token` answers
"invalid", or the token store faults, and the library would still serve
the token from its cache, the guard must read the status of the account
the entry belongs to. With a yes alone it can only let the request through
unchecked or refuse it, so it keeps reading `_token_cache` and
`_cache_ttl`.

What would serve: the same predicate answering the entry's `actor_id`, or
`None` for a miss. It exposes one field the caller gets from a successful
`validate_access_token` anyway, to a caller that holds the token.

To decide: a second function (`cached_token_actor_id(token, config)`)
beside `is_token_cached`, or replacing it before 4.0.0 is final, while
that costs nothing. `is_token_cached` has had no release yet. The spec
statement is MCP-21; MCP-D5 ("the query is the only supported view") holds
either way.

Related: `mcp-cache-lifecycle-and-revocation.md` (a token revoked in
another process stays cached; this guard is one consumer working around
it).
