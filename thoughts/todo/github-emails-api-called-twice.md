# TODO: GitHub's `/user/emails` API is called twice on the identifier-extraction failure path

**Status:** Open, approach chosen 2026-11-02 (see "Approach" below);
`thoughts/plans/2026-11-02-3-16-owner-decided-followups.md` carries it. Split out 2026-09-10 from
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

## Approach (owner, 2026-11-02)

Fetch once at the two callback sites in `handlers/oauth2_callback.py`, web and
SPA. Each site calls `get_verified_emails()` once and derives the primary from
that list instead of calling `get_primary_email()` separately. A failed fetch
is reused for the second lookup in the same sign-in: one timeout, then the
existing 502. The base-class contract of `get_primary_email()` does not
change, and nothing is cached on the provider.

## Where a cache can live (found 2026-11-02)

The outside-voice review of `thoughts/plans/2026-11-02-3-16-small-followups.md`
traced the callers:
- The only path that calls both methods for one token builds its authenticator
  per request (`handlers/oauth2_callback.py:153,280,1416`, and the SPA path at
  `:1083-1101`).
- The one long-lived authenticator (`oauth2_server/oauth2_server.py:65`) calls
  only `get_primary_email` (`:373`).

So a request-local fix works, and fetching at the callback sites is the one
chosen. A provider-level cache with a TTL would straddle requests.

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
