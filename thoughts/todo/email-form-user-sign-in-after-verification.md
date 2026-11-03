# A user whose provider has no verified address cannot sign in again after verifying

**Status:** Open. Recorded 2026-11-03 by
`thoughts/plans/2026-11-02-3-16-adoption-fault-followups.md` (BG, BG3).
**Filed by:** Greger Wedel (with Claude).

## The gap

A user whose provider supplies no verified address (GitHub with every
address private, a Google account with an unverified one) reaches the email
form, types an address and gets a verification email. Confirming it
verifies the actor (and, since 3.16, issues no session at the click). The
next sign-in with the same provider account again finds no verified address,
reaches the form again, and the form answers 409 because the address now has
an actor (`oauth_email.py`, the free-text branch's `create_only`).

The credential the form hands out at submission is the provider's own token
(`store.oauth_token`), which authenticates as the provider identity, not the
typed address (`auth.py`, `_check_oauth2_token`), so it does not sign the
user in to the actor either.

## What was tried and not taken

- **Keep the submitter's session through the click** (BG3 point 2): the
  session the form issues does not authenticate as the actor (above).
- **Link the provider account at the confirm** (BG3 point 3): an attacker
  signs in with their own provider account, types a victim's address, and
  gets the victim's verified actor once the victim confirms the unsolicited
  mail. Dropped by the owner (2026-11-03).
- **Bind the link to the submitting browser** (a cookie set at submission):
  offered, not taken.

## Shapes still open

- The form issues an ActingWeb session token bound to the actor id (as the
  OAuth callback does), and the confirm keeps exactly that token while it
  revokes the others; the original tab keeps working. Cross-device confirm
  still leaves the user to sign in through a provider that supplies the
  address.
- An emailed one-time code typed into the original page, which completes the
  sign-in there.
