# The OAuth sign-in takes the provider's `email` without its `email_verified` claim

**Status:** Open. Found 2026-11-02 by the security evaluation of
`thoughts/plans/2026-11-02-3-16-owner-decided-followups.md`; older than 3.16
and not widened by that plan.
**Filed by:** Greger Wedel (with Claude).

## The gap

`OAuth2Authenticator.get_email_from_user_info` (`actingweb/oauth2.py`, "Always
try to get email first") returns `user_info["email"]` lowercased whenever it
is present. It never reads the OpenID `email_verified` claim. The address
becomes the creator a sign-in resolves (and, for a provider-id creator, the
`store.email` the create and the 3.16 seeding write). A provider that hands
out an unverified address in `email` would let its user claim that address's
actor.

Google and Apple verify the addresses they return; GitHub's `/user/emails`
path already requires `verified`. The exposure is a generic OIDC provider
configured through `with_oauth` that returns unverified addresses.

## Fix shape (not decided)

- Refuse an `email` whose `email_verified` is present and false, falling
  through to the provider-id identifier or the email form.
- Decide what an absent claim means per provider (Google always sends it;
  some providers never do).
