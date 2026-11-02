# TODO: GitHub's `/user/emails` API is called twice on the identifier-extraction failure path

**Status:** Open. Split out 2026-09-10 from
`thoughts/plans/2026-09-10-oauth-email-form-writes-to-existing-actors.md`
(Phase 1 scalability review, "What We're NOT Doing").
**Filed by:** Greger Wedel (with Claude), during 3.14.5.
**Severity:** Low probability, high cost when it hits. Only reachable on the
GitHub `require_email` no-public-email path, which is itself an edge case;
the cost is a request-thread stall, not incorrect behavior.

## The gap

`OAuth2Provider.get_primary_email()` and `OAuth2Provider.get_verified_emails()`
are independent methods with independent HTTP calls to GitHub's
`https://api.github.com/user/emails`, each with its own `(5, 10)` second
`(connect, read)` timeout. On the `require_email`-and-no-public-email path,
the callback (`actingweb/handlers/oauth2_callback.py`) can call both in
sequence for the same access token: `get_email_from_user_info()` tries
`get_primary_email()` first (up to 15s worst case), and only on failure does
the caller reach `get_verified_emails()` (another 15s worst case). Layered on
top of the ~10s worst case for the userinfo call that precedes both, the
worst-case wall time for this path is close to 45 seconds — past API Gateway's
30-second integration timeout on a Lambda deployment (`.with_sync_callbacks()`
deployments per `docs/quickstart/deployment.rst`).

## Fix shape (not decided)

Two options, not evaluated against each other yet:

1. **Per-token cache on the authenticator.** Cache the raw
   `https://api.github.com/user/emails` response (or its parsed email list)
   keyed by access token for the lifetime of the request/authenticator
   instance, so `get_primary_email()` and `get_verified_emails()` share one
   HTTP call when both are invoked for the same token.
2. **Contract change:** make `get_primary_email()` derive its answer from
   `get_verified_emails()` (call the list method once, pick the primary
   verified entry) instead of hitting the API independently. Changes the
   base-class contract for every provider, not just GitHub.

## Where a cache can live (found 2026-11-02)

The outside-voice review of `thoughts/plans/2026-11-02-3-16-small-followups.md`
traced the callers:
- The only path that calls both methods for one token builds its authenticator
  per request (`handlers/oauth2_callback.py:153,280,1416`, and the SPA path at
  `:1083-1101`).
- The one long-lived authenticator (`oauth2_server/oauth2_server.py:65`) calls
  only `get_primary_email` (`:373`).

So a request-local fix works: memoise on the per-request authenticator, or
fetch once at the two callback sites and derive both answers there. A
provider-level cache with a TTL would straddle requests. Still to decide:
where the memo lives, and whether a failed fetch is reused.

## Constraints inherited from the 3.14.5 plan

- This path only exists because of the GitHub-failure discriminator added in
  that plan (`get_verified_emails()` returning `None` on API failure); before
  it, a `get_primary_email()` failure fell through silently to the free-text
  form without a second call. Don't remove the discriminator to "fix" this —
  the loud failure is the point ("FIXED" entry, `CHANGELOG.rst`); the second
  call's latency is the actual problem.
- Whatever caching is added must not straddle requests — GitHub access
  tokens are per-login, and the authenticator is already constructed fresh
  per request via `create_oauth2_authenticator()`.
