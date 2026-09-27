---
status: proposed
---

# Implementation Plan: a configurable refresh-token grace period, and client guidance for lost responses

**Date:** 2026-09-27
**Research:** thoughts/research/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md
(the triage of the dropped-rotation report; its "Release decision" assumed
a server-side successor rule, which this plan replaces)
**Supersedes:** thoughts/plans/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md
**Branch:** `release/3.15.0-refresh-grace`, cut from `master` at `fc13f81`.
Lands before `3.15.0rc1`.

## Overview

A native client that sends a refresh and never receives the response (a
laptop going to sleep mid-request) presents its old refresh token minutes
later; both token stores read that as theft and revoke the chain. The
superseded plan answered this with a server-side successor replay. Its
Phase 2 showed that design disables theft detection, and the patch that
closed the hole was a second invented mechanism. The owner chose, on
2026-09-27, to stay on standard mechanisms:

1. **Server:** the grace period both ladders already have (a reuse
   interval, in vendor terms) becomes a deployment setting instead of a
   hard-coded 60 s, with a documented ceiling and a documented cost.
2. **Client:** the root cause is a client starting a refresh it cannot see
   answered. The library documents how a client refreshes reliably, and the
   consumer's own fixes (their #109) follow that guidance.

## Standards and vendor practice

Checked 2026-09-27 against the primary sources (a research agent quoting
the documents; links below).

- **RFC 9700 §4.14.2** requires, for public clients, either
  sender-constrained refresh tokens (RFC 8705 / RFC 9449) or rotation with
  reuse detection. It says nothing about grace periods or lost responses;
  do not cite it for either.
- **Okta** offers a grace period of **0 to 60 s** (default 30), because
  "new tokens issued by Okta might not reach the client app". What a reuse
  inside it returns is not documented.
- **Auth0** offers a reuse interval with no documented maximum. Inside it
  "breach detection features don't apply and a new rotating refresh token
  is issued" (a fork, like ours), but "only the previous token can be
  reused; if the second-to-last one is exchanged, breach detection will be
  triggered". Auth0 advises "the shortest amount of time to afford
  protection from replay attacks".
- **Keycloak** has "Revoke Refresh Token" with a reuse *count*, not a time
  window.
- **No IETF or vendor guidance** was found on client handling of a lost
  refresh response.

What follows for this plan:

- Our 60 s default already equals Okta's maximum. No vendor treats a
  minutes-long gap (a sleeping laptop: 336 s to 2950 s) as a server
  concern; it is the client's to avoid.
- A longer grace is a recognised vendor option (Auth0), but one its vendor
  advises keeping short. It is an escape hatch, not the fix.
- **A gap with Auth0:** our grace applies to any consumed token younger
  than the grace, not only the chain's most recent one. At the 60 s
  ceiling that needs two rotations inside a minute; noted, not changed.

Sources: <https://www.rfc-editor.org/rfc/rfc9700.txt>,
<https://developer.okta.com/docs/guides/refresh-tokens/main/>,
<https://auth0.com/docs/secure/tokens/refresh-tokens/configure-refresh-token-rotation>,
<https://auth0.com/blog/securing-single-page-applications-with-refresh-token-rotation/>,
the Keycloak server-admin guide (`sessions/timeouts.adoc`).

## Decisions Made

- **No server-side successor replay.** Owner, 2026-09-27. Rotation with
  reuse detection stays exactly the RFC 9700 §4.14.2 mechanism; the
  superseded plan records why.
- **One setting for both ladders.** `ActingWebApp.with_refresh_token_grace(seconds)`
  sets `Config.refresh_token_grace_period`, read by the SPA ladder
  (`handlers/oauth2_spa.py`, the `GRACE_PERIOD_EXTENDED` tier) and the MCP
  ladder (`oauth2_server/token_manager.py`, `MCP_REFRESH_TOKEN_GRACE_PERIOD`).
  The two ladders already share the 60 s value and its meaning; a deployment
  runs one kind of client population per app. Default 60, unchanged.
- **Bounds: 0 to 60 seconds.** Owner, 2026-09-27: Okta's maximum. The
  setting can only tighten (0 turns the grace off: every reuse past the
  concurrent-request tier is theft). `ValueError` outside the range, at
  configuration time. The lockout from a minutes-long gap is therefore the
  client's to prevent; the library documents how. Options not taken: 1800 s
  and 3600 s as a temporary escape hatch (Auth0-style); both widen the
  window a copied token is honoured in, and a grace near the rotation
  interval makes Auth0's "second-to-last token" gap routine. The owner may
  still drop the setting entirely before implementation; with a 60 s
  ceiling its only use is tightening.
- **The cost is stated, not hidden.** Inside the grace period a reuse
  rotates again in the same chain: the reuser gets a second, independent
  branch. Reuse detection only sees a branch that reuses its *own* consumed
  token past the grace period, so a copied token presented inside the
  grace window yields a branch detection never sees. That is today's
  behaviour for 60 s; a longer grace widens the window. The docs say so
  next to the setting. At the 60 s ceiling the fork window is today's.
- **The SPA 10 s tier stays a log distinction.** It becomes
  `min(10, grace)` so a grace of 0 has no tier below it.
- **The SPA store checks expiry before `used`** (kept from the superseded
  plan, already on the branch): a used row past its own `expires_at` reads
  as expired and never reaches the reuse ladder, where it would be answered
  as theft and revoke the chain. The MCP store already checks in this order.
- **Client guidance goes in the product docs**, not only in the consumer
  message: every native client of the library meets the same problem.
- **Release: 3.15.0, before rc1.** A new builder method and config
  attribute; 3.15.0 is already a minor with a migration guide.

## What We're NOT Doing

- **Successor replay or any other new reuse rule** — the owner's decision;
  RFC 9700's two options are rotation or sender-constraining, and we do the
  first as specified.
- **Replaying the same successor inside the grace period** (answering a
  grace reuse with the pair already issued instead of a new branch) — it
  would remove the fork cost, but it is again our own mechanism, and it
  needs the successor stamp the owner just dropped.
- **Separate SPA and MCP grace settings** — no deployment is known to need
  them apart; adding the second later is additive.
- **Changing the 2-day reuse window** — unrelated to the lost response.
- **DPoP** (sender-constrained refresh tokens, RFC 9449) — owner,
  2026-09-27: not planned as of today. It would remove the lockout only if
  bound refresh tokens stopped rotating, and it needs proof validation, a
  cross-worker replay cache and server nonces; no todo is filed.
- **The SPA store's fault contract** — filed as
  `thoughts/todo/token-store-fault-contract-gaps.md`; this plan touches only
  the grace comparison.
- **Client code** — the consumer's #109 owns it; this plan documents what a
  client should do.

## What Already Exists

- `actingweb/handlers/oauth2_spa.py:53-54` `GRACE_PERIOD_IMMEDIATE`,
  `GRACE_PERIOD_EXTENDED` and the ladder at `:663-716` — the SPA grace.
- `actingweb/constants.py:208` `MCP_REFRESH_TOKEN_GRACE_PERIOD` and
  `_validate_ttl_constants` (`:260`) — the MCP grace and its invariant.
- `actingweb/oauth2_server/token_manager.py:434` — the MCP grace comparison.
- `actingweb/interface/app.py` builder methods and
  `_apply_runtime_changes_to_config` (`:203`) — the pattern for a setting
  that reaches `Config` (`with_sync_callbacks`).
- `tests/test_oauth2_spa_refresh_rotation.py` (on `tests/mcp_token_double.py`
  since this branch) and `tests/test_mcp_refresh_rotation.py` — the ladder
  tests both phases extend.

## Phase 1: The grace setting

### Changes

- `actingweb/config.py`: `self.refresh_token_grace_period: int` from
  kwargs, default `MCP_REFRESH_TOKEN_GRACE_PERIOD` (60).
- `actingweb/interface/app.py`: `with_refresh_token_grace(seconds: int)`
  validates `0 <= seconds <= REFRESH_TOKEN_GRACE_MAX`, stores it, and
  applies it to `Config` like `with_sync_callbacks`; the constructor passes
  it through.
- `actingweb/constants.py`: `REFRESH_TOKEN_GRACE_MAX = 60` (the owner's
  ceiling), with the
  invariant `REFRESH_TOKEN_GRACE_MAX < min(both reuse windows)` in
  `_validate_ttl_constants`. The existing constant stays the default.
- `actingweb/handlers/oauth2_spa.py`: the ladder reads
  `self.config.refresh_token_grace_period` (via `getattr` with the constant
  as fallback, for configs built without the builder); the immediate tier
  is `min(GRACE_PERIOD_IMMEDIATE, grace)`. The module constants stay for
  backward compatibility and are documented as defaults.
- `actingweb/oauth2_server/token_manager.py`: the grace comparison reads the
  config value the same way; the docstring at `:315` names the setting.
- `actingweb/oauth_session.py`: the expiry-before-used order. **Done and
  committed 2026-09-27** with its test and changelog entry, ahead of this
  plan's approval, on the owner's instruction.

### New Tests, both unit and integration tests

- `tests/test_refresh_grace_setting.py`: the builder accepts 0, 60 and the
  ceiling, rejects -1 and ceiling + 1 with `ValueError`, and the value reaches `Config`.
- SPA ladder (`tests/test_oauth2_spa_refresh_rotation.py`):
  - grace 20: a reuse 15 s after use rotates in the same chain;
  - grace 20: a reuse 40 s after use is theft (chain revoked);
  - grace 0: a reuse 5 s after use is theft;
  - default config: 30 s rotates, 90 s is theft (today's pins, unchanged).
- MCP ladder (`tests/test_mcp_refresh_rotation.py`): the same four cases on
  `refresh_access_token`.
- `test_a_used_token_past_its_expiry_is_expired_not_theft` (already on the
  branch; fails on `master`).
- Integration: none new; the backend rotation test runs at the default.

### Failure Scenarios

- A config built without the builder (tests, direct `Config()` use) lacks
  the attribute — the `getattr` fallback gives 60 — covered by the
  default-config cases.
- A deployment sets the grace above 60 s — refused at configuration time,
  never at request time — the builder test.
- Grace 0 with a genuine concurrent duplicate (two tabs refreshing at once)
  — the second is theft and the chain is revoked; stated in the docs as
  the cost of 0 — the grace-0 test pins it.

### Verification

- [ ] Run the contract's `### Checks` fast tier verbatim
- [ ] Full tier before the commit (both backends)

### Implementation Status: Not Started

---

## Phase 2: Docs, changelog and client guidance

### Changes

- `docs/guides/spa-authentication.rst`: a section "Refreshing reliably on
  native and mobile clients" with the guidance below, and the grace
  setting with its cost where the 60 s grace is described (`:686-693`,
  `:1480-1486`, `:1516-1519`).
- `docs/guides/oauth2-setup.rst` (`:336-341`) and
  `docs/guides/mcp-applications.rst`: the same setting for MCP clients.
- `docs/guides/troubleshooting.rst` (`:107-122`): "asks me to log in again"
  gains the lost-response cause, the client fixes, and the setting.
- `docs/reference/security.rst` (`:55-56`): the setting, its bounds and the
  fork cost.
- `docs/quickstart/configuration.rst`: the builder method.
- `CHANGELOG.rst`, Unreleased: ADDED `with_refresh_token_grace()`; the
  rotation SECURITY entry names the setting. (The FIXED entry for the SPA
  expiry-before-used order is already in.)
- `docs/migration/v3.15.rst`: the setting in the rotation section.
- The client guidance (the docs section, and the consumer message's
  paragraph for their #109):
  1. **Never start a refresh the device may not see answered.** On macOS,
     do not refresh during a dark wake, and stop starting refreshes once
     the app is told the system will sleep; on iOS/Android, not while the
     app is being suspended.
  2. **Hold the device awake for an in-flight refresh** (macOS
     `ProcessInfo.beginActivity` / an IOKit power assertion; iOS
     `beginBackgroundTask`), so the response arrives before sleep.
  3. **Keep the old token on an ambiguous failure and retry it at once on
     wake or reconnect.** Inside the grace period the server rotates
     again; past it, the reuse is theft.
  4. **One refresh in flight per token** (single-flight across tabs or
     windows: a lock or `BroadcastChannel`), and **store the new pair
     before using it.**
  5. **Treat a 401 on refresh as final**: clear the session and sign in
     again; do not retry the same token.
- `thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md`:
  its Phase 4 consumer message gains the pin bump, the grace setting and
  the client guidance for #109.

### New Tests, both unit and integration tests

- None; `sphinx-build -W` is the check.

### Failure Scenarios

- A guide still says the grace is fixed at 60 s —
  `grep -rn "60 s\|60 seconds\|grace" docs/` reviewed by hand.

### Verification

- [ ] Run the contract's `### Checks` full tier verbatim (both backends)
- [ ] The grep above, by hand

### Implementation Status: Not Started

---

## Evaluation Notes

Not run through the five-evaluator pass: this plan narrows a reviewed plan
to a configuration knob, and the owner asked for the standard route. The
design question it answers was reviewed in the conversation of 2026-09-27.
Run `/verify_implementation` with its adversarial pass as usual.

### Unverified notes

- Which MCP clients (Claude Code, Codex, ChatGPT) retry a refresh after a
  lost response, and how quickly; the report's four events came from the
  consumer's own Mac client.
