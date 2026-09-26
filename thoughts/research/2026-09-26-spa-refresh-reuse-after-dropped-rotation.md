# Research: a dropped SPA refresh rotation reads as theft and locks the device out (inbound triage)

**Date:** 2026-09-26
**Triaged from:** `thoughts/inbound/spa-refresh-reuse-after-dropped-rotation-revokes-the-chain.md`
(deleted with this note), filed 2026-09-26 by Greger Wedel
(greger@ttwedel.no) from the `actingweb_mcp` deployment at `ai.actingweb.io`.
The consumer's own side of it is `../actingweb_mcp/thoughts/todo/` #109.
**Tree checked:** `02fe4f7` on `release/3.15.0-mcp-oauth-hardening`
(the report's line numbers were from `7e9c0b9`; nothing on this path moved).
**Verdict:** the finding is real, the library is the right place to fix it,
and it belongs in **3.15.0**, as its own plan, before `3.15.0rc1`. Reasons
under "Release decision".

## What the check changed

The report was written carefully and nearly everything held. What the
triage confirmed, corrected or added:

| Claim | Result |
| --- | --- |
| `GRACE_PERIOD_IMMEDIATE = 10`, `GRACE_PERIOD_EXTENDED = 60` (`oauth2_spa.py:52-53`) | Confirmed. |
| `SPA_REFRESH_TOKEN_REUSE_WINDOW` = 2 days; the reuse ladder at `oauth2_spa.py:637-716`, theft tier calls `revoke_token_chain` (`:701`) | Confirmed (`constants.py:195`, `oauth2_spa.py:668-701`). |
| The consumed row keeps its data with `used=True, used_at=now`, TTL re-stamped to the reuse window | Confirmed, with one update: since Iteration 16 of the 3.15 plan the TTL is set by the compare-and-swap itself (`consume_once(consumed_ttl=)`), not by a second write. Same effect. |
| Nothing links a consumed token to its successor | Confirmed. The SPA record (`oauth_session.py:586-591`) has `actor_id, identifier, created_at, expires_at, used, chain_id`; the MCP record (`token_manager.py:866-877`) adds `access_token`, `client_id`, `google_token_key`. Neither has `successor` or `predecessor`; `grep successor actingweb/` finds only a list-storage comment and an unrelated docstring word. |
| `consume_once` takes `stamp=` | Confirmed (`single_use.py:43`, `:90`); the MCP path already uses it to stamp a chain id atomically with the consume, which is exactly the mechanism a successor stamp needs. |
| Server code on this path unchanged since June (`8a742c7`) | Confirmed by `git log -L` over the ladder: `8a742c7` is the last commit that touched it. |
| Existing tier tests at `test_oauth2_spa_refresh_rotation.py:129-226` | Confirmed, four tests with the names given. |
| The MCP plan "lists closing the grace-window divergence as an open item" | **Corrected.** The plan lists it under *What We're NOT Doing* (line 303) as an accepted trade, and its evaluation notes record it as folded. So the 3.15 MCP ladder deliberately ships the same 60 s policy. That strengthens, not weakens, the case for fixing both ladders now, before that contract is documented in a release. |
| Consumer references: the 09-03/09-04 research, todo #65 | Confirmed to exist. The consumer has since filed #109 for its side. |
| Production evidence (four events, queries) | Not checkable from this repository. Accepted from the reporter, who is the deployment's operator and this repository's owner. |
| Vendor comparison (Okta 0–60 s, Auth0 reuse interval) | Not re-verified; it does not carry the decision. |

**One gap in the proposal, found by the triage.** The report says an orphaned
successor, "marked `used` (with `orphaned=True`)", trips the wire when
presented because "its own successor is absent". That is only true past the
grace tiers: the ladder reads `used_at`, and an orphaned token presented
within 60 s of being orphaned lands in the ≤10 s / ≤60 s tiers
(`oauth2_spa.py:662-672`) and rotates. A thief holding the successor who
retries promptly would be honoured. The rule must make `orphaned=True`
bypass the grace tiers: an orphan presented at any age is theft. The plan
must carry that.

**Second note.** The report's optional access-token revocation on a benign
re-issue is what bounds the "theft after use, victim idle" window to the
victim's next API call rather than the next refresh. It is cheap on the SPA
side (`revoke_token_chain` walks both buckets; it needs a bucket scope) and on
the MCP side (`_revoke_chain` snapshots both buckets already). Recommended,
not optional.

## Why this is the library's problem

The client cannot tell a lost response from a rejected one, and keeping the
stored token on an ambiguous failure is the right client behaviour: the
alternative wipes a valid session on every flaky network. The only party
that knows whether the successor was ever used is the server. So the fix
has to be here, and the consumer needs nothing but a pin bump.

The property the rule adds is structural, not temporal: **a reused token
whose direct successor was never presented is a dropped rotation**. A thief
who copied the token after the legitimate client used it cannot produce
that signature once that client has refreshed even once more. The 60 s grace
stays for fast duplicates; the successor check handles the sleeping laptop,
whose gap is unbounded (336 s to 2950 s observed; a closed lid can be hours).

## Both ladders, one layer

The MCP token manager is a port of the SPA ladder (60 s, 2 days, chain
revocation). It has not shown this failure because its current clients
refresh from servers that do not sleep, but a desktop MCP client on a laptop
(Codex, Claude Code) will. The successor rule therefore goes into the shared
single-use layer, or a shared helper both ladders call, so both get it in
one change with one set of tests. The 3.15 plan's "What We're NOT Doing"
entry is superseded by this.

## Release decision

**3.15.0, as a new plan, implemented before `3.15.0rc1`.**

- It is a user-facing lockout with verified production frequency (four in
  22 days for one active user; every native client that sleeps is exposed).
- 3.15.0 is a minor with a migration guide, and it introduces the MCP
  rotation ladder. Shipping that ladder with the successor rule from the
  start means its documented contract is written once. Adding the rule in
  3.16 would change a contract the 3.15 rc connector pass had just
  validated, and force a second pass.
- The rc mechanism is the safety net: the connector pass and the demo
  deployment exercise rotation on real clients, which is where a rule about
  lost responses wants to be exercised.
- A 3.14.8 patch carrying the SPA half alone was considered and rejected:
  the reuse case's answer changes from 401-and-revoke to 200-and-reissue,
  which is a behaviour change the changelog and migration guide should
  carry, and it would leave the MCP half for later.
- It is not an iteration of the MCP plan: it is a new design element with
  its own decisions (orphan semantics, the access-token revocation, the
  horizon), so `/create_plan` from this note, per the iterate rule that
  substantial new work is a new plan. The MCP plan's Phase 4 then runs on
  the combined branch.

## What the plan must decide

1. **Where the successor is recorded.** Preferably in the consume's `stamp=`
   (generate the new token string before the CAS, stamp it, then store the
   new record), so the link is atomic with the consume. Both stores generate
   the token inside their `create_refresh_token`; that needs a small split.
2. **Orphan semantics.** `orphaned=True` bypasses every grace tier; an
   orphan presented at any age revokes the chain.
3. **Re-stamp on re-issue.** The consumed row gets the new successor and
   `used_at=now`, so a repeated drop stays benign and a fast duplicate lands
   in the grace tiers (the report's own point; it is load-bearing).
4. **Access-token revocation on re-issue.** Recommended; needs a bucket scope
   on `revoke_token_chain` and the MCP equivalent.
5. **Horizon.** Key on successor state alone within the existing 2-day reuse
   window; no new constant unless the rc pass shows a reason.
6. **Absent successor** (expired, purged, or a legacy row) is "used": the
   benign path must not open on absence.
7. **The eight tests the report lists**, plus the grace-bypass test for
   orphans, on the in-memory doubles for both stores and on both backends
   for the rotation itself.

## Consumer follow-ups (theirs, from the report)

Pin bump once released; the dark-wake refresh decision (#65's dormant-Mac
capture); annotate the 09-03/09-04 research as true only up to 2026-09-04.
Tracked as their #109.
