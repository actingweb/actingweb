---
status: done
verified: thoughts/verifications/2026-09-27-refresh-grace-setting-3.md
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
  ceiling its only use is tightening. [Implemented 2026-09-27.]
  **[Updated 2026-09-27, Iterations 1–2]** `0` means no grace: a reuse in
  the same second is theft too (`grace > 0 and age <= grace`). The bound is
  enforced by `Config(...)` as well as the builder, and the ladders clamp a
  value assigned afterwards.
  **[Updated 2026-09-27, Iterations 8–9]** The attribute is a validating
  property on `Config`: every write raises for a bad value. Grace 0's
  promise is stated exactly: every reuse is answered as theft, but a
  request still being answered when the chain is revoked keeps its new
  tokens (owner: document, don't close the race).
- **The cost is stated, not hidden.** Inside the grace period a reuse
  rotates again in the same chain: the reuser gets a second, independent
  branch. Reuse detection only sees a branch that reuses its *own* consumed
  token past the grace period, so a copied token presented inside the
  grace window yields a branch detection never sees. That is today's
  behaviour for 60 s; a longer grace widens the window. The docs say so
  next to the setting. At the 60 s ceiling the fork window is today's.
- **The SPA 10 s tier stays a log distinction.** It becomes
  `min(10, grace)` so a grace of 0 has no tier below it.
  **[Updated 2026-09-27, Iteration 3]** The tiers are decided once by
  `single_use.classify_reuse`; inside the grace verdict the 10 s constant
  only picks the log line.
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

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Full tier before the commit (both backends)

### Implementation Status: Complete

Notes (2026-09-27):

- **New config option: a minor.** `with_refresh_token_grace()` and
  `Config.refresh_token_grace_period` are new public surface; 3.15.0 is
  already a minor, so the changelog places them under ADDED in Phase 2.
- The builder also refuses a `bool`, a `float` and a string (`ValueError`),
  not only out-of-range integers: `True` would otherwise pass as 1.
- The default is wired both ways: as a `Config(...)` kwarg in `get_config()`
  and unconditionally in `_apply_runtime_changes_to_config`, because
  `__init__` builds the Config eagerly and a later builder call only reaches
  it through the second path. Tests cover a call before and after the first
  `get_config()`, and a later unrelated builder call keeping the value.
- `constants._validate_ttl_constants` gained two invariants: the default
  grace lies in `[0, REFRESH_TOKEN_GRACE_MAX]`, and the ceiling is below both
  reuse windows.
- The ladder tests are one parametrized test per ladder
  (`test_the_configured_grace_decides_rotation_or_theft`, five cases: the
  plan's four, with the default split into 30 s and 90 s). They set the
  attribute on the Config directly, which also shows the ladders read the
  attribute and not the module constant.
- **Unrelated fix, found by the full tier:** on PostgreSQL,
  `tests/performance/test_backend_performance.py`'s two subscription
  benchmarks passed `callback="https://callback.example.com"` where both
  backends declare `callback: bool`. DynamoDB stores the string; the
  PostgreSQL boolean column refuses it, so both tests failed. Changed to
  `callback=True`. The full tier's `make test-all-parallel` runs
  `tests/performance/` (CI excludes benchmarks), which is why CI never saw
  it.
- Full tier: DynamoDB 3710 passed; PostgreSQL 3601 passed (after the
  benchmark fix; before it, 2 failed); sphinx `-W` clean. The DynamoDB run
  predates the one-line benchmark fix, which only narrows an argument
  DynamoDB already accepted.

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
  3. **Keep the old token on an ambiguous failure, but do not count on
     retrying it.** A retry inside the grace period (at most 60 s) rotates
     again; a retry after a sleep is the reuse the server answers as theft.
     Prevention (rules 1 and 2) is the fix, not the retry. [Corrected
     2026-09-27 from the consumer's feedback: the earlier "retry it at once
     on wake" prevents none of the observed lockouts.]
  4. **One refresh in flight per token** (single-flight across tabs or
     windows: a lock or `BroadcastChannel`), and **store the new pair
     before using it; a failed store is a failed refresh.** A client that
     adopts the new tokens but fails to persist the new refresh token keeps
     the consumed one as its stored token, and its next refresh is theft.
  4a. **Give the refresh request a timeout**, so a request parked across a
     sleep fails on the client instead of hanging; together with rule 1 it
     lets the client start over cleanly after wake.
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

- [x] Run the contract's `### Checks` full tier verbatim (both backends)
- [x] The grep above, by hand

### Implementation Status: Complete

Notes (2026-09-27):

- The client guidance is numbered 1–7 in the SPA guide
  (`spa-refresh-reliably`): the plan's rule 4 is split into
  single-flight (4) and "store before use; a failed store is a failed
  refresh" (5), and 4a became 6. Content unchanged.
- Two explicit labels, `spa-refresh-grace` ("Choosing the grace period",
  under "Token Refresh with Rotation") and `spa-refresh-reliably`, carry the
  cross-document links from the MCP, OAuth2-setup, troubleshooting,
  security, configuration and migration pages.
- `docs/guides/mcp-applications.rst` had no refresh-token text; it gains a
  "Refresh Tokens" subsection under "OAuth2 Integration".
- `docs/guides/troubleshooting.rst` gains a separate entry, "Native or
  mobile client asks to log in again after the device slept", rather than
  folding the cause into the one-hour MCP entry, whose cause (a client never
  storing the new token) differs; that entry names the setting.
- CHANGELOG: a new `ADDED` section in Unreleased (there was none), between
  `CHANGED` and `FIXED`; the MCP rotation `SECURITY` entry names the
  setting. The FIXED expiry-before-used entry was already in.
- Grep review: the remaining fixed "60 seconds" mentions are either
  qualified as the default nearby (`docs/migration/v3.15.rst` lines 70/83,
  followed by the new paragraph) or history (`docs/migration/v3.11.rst`, old
  changelog entries), left as they are.
- The consumer message in the 3.15.0 plan's Phase 4 gains the pin bump, the
  setting and the #109 guidance.
- Full tier on the final tree: ruff, ruff format, pyright clean; DynamoDB
  3710 passed, 31 skipped (962 integration passed); PostgreSQL 3601
  passed, 140 skipped (954 integration passed, including
  `tests/integration/test_mcp_refresh_rotation_backend.py`); sphinx `-W`
  clean. The PostgreSQL skips are backend-specific by design (DynamoDB GSI,
  cost and partition unit tests, and `tests/integration/test_ttl_cleanup.py`);
  its 38 s wall time against DynamoDB's 8.5 min is DynamoDB Local's speed.

---

## Evaluation Notes

Not run through the five-evaluator pass: this plan narrows a reviewed plan
to a configuration knob, and the owner asked for the standard route. The
design question it answers was reviewed in the conversation of 2026-09-27.
Run `/verify_implementation` with its adversarial pass as usual.

### Consumer feedback (actingweb_mcp, 2026-09-27)

- The client fixes are feasible, about 4–6 days: the JS part (refresh
  timeout, failed persist is a failed refresh, gate the resume refresh on a
  sleeping flag) and a small Capacitor plugin (sleep/wake observers and a
  power assertion on Mac, `beginBackgroundTask` on iOS). Two things need a
  spike on their side: whether a dark wake delivers an app-active event at
  all, and whether a power assertion from a Designed-for-iPad process holds
  through a dark wake.
- The 60 s ceiling is accepted; no value at or under 60 s covers a 336 s
  gap, so they need no grace change.
- Their client already has single-flight refresh, a final 401 and keep-on-
  ambiguous-failure. Its gaps are a missing fetch timeout, a persist that
  can fail silently, and no sleep/wake handling.
- Whether each of the four events was a lost response or a failed Keychain
  write is unknown until their dormant-Mac capture (#65) lands; the
  persist rule covers the second case.
- They asked that the SPA expiry-before-used fix be kept (committed,
  `c280bcf`).

### Unverified notes

- Which MCP clients (Claude Code, Codex, ChatGPT) retry a refresh after a
  lost response, and how quickly; the report's four events came from the
  consumer's own Mac client.

## Implementation Summary

**Completed:** 2026-09-27
**All phases:** Complete
**Test status:** All passing (DynamoDB 3710 passed, PostgreSQL 3601 passed,
ruff/pyright/sphinx `-W` clean)

### Deviations from Plan

- The builder refuses non-integers (`bool`, `float`, `str`) as well as
  out-of-range values.
- Two extra invariants in `_validate_ttl_constants` (the default lies in
  `[0, REFRESH_TOKEN_GRACE_MAX]`; the ceiling is below both reuse windows).
- One-line fix outside the plan's scope:
  `tests/performance/test_backend_performance.py` passed a URL as the
  boolean `callback` flag, which failed both subscription benchmarks on
  PostgreSQL in the local full tier.
- Client guidance renumbered 1–7 (see Phase 2 notes).
- After verification (Iterations 1–7): grace 0 is no grace; `Config`
  validates and the ladders clamp; one shared `classify_reuse` and one
  `REFRESH_TOKEN_GRACE_DEFAULT`; the builder writes the grace only when
  given one; the expiry-first exception is documented.

### Learnings

- The local full tier (`make test-all-parallel`) runs `tests/performance/`
  under `-n auto`, although `CLAUDE.md` says benchmarks never run in
  parallel and CI excludes them, so a benchmark that is broken on one
  backend surfaces only locally. Left as is; `CLAUDE.md`'s wording or the
  Makefile target is the owner's call.
- `ActingWebApp.__init__` builds the Config eagerly, so a new builder
  setting must be applied in `_apply_runtime_changes_to_config`, not only
  passed as a `Config(...)` kwarg.


## Iterations

### 2026-09-27, after verification thoughts/verifications/2026-09-27-refresh-grace-setting.md

The owner chose to fix all seven of the verification's issues in this batch.

#### 1. Grace 0 is no grace: a same-second reuse is theft

**Category**: Verification fix (Issue 1)

**What changed**: Both ladders rotate a reuse only when `grace > 0 and age
<= grace`. Before, the inclusive `age <= grace` on whole-second ages let a
reuse in the same second (age 0, or negative from clock skew) rotate under
grace 0. The docs promised "every reuse is theft, including two tabs
refreshing at the same moment". New cases `grace0-same-second` in both
ladder parametrizations failed before the change and pass now.

**Files affected**:
- `actingweb/single_use.py` — `classify_reuse(age, grace, reuse_window)`
- `actingweb/handlers/oauth2_spa.py`, `actingweb/oauth2_server/token_manager.py` — use it
- `tests/test_oauth2_spa_refresh_rotation.py`, `tests/test_mcp_refresh_rotation.py` — `(0, 0, False)`
- `tests/test_refresh_grace_setting.py` — `test_classify_reuse`

**Rationale**: the docs' wording was right and the boundary was wrong; the
code fix is smaller than qualifying six claims.

#### 2. The 0–60 bound holds outside the builder too

**Category**: Verification fix (Issue 2)

**What changed**:
- `Config.__init__` validates `refresh_token_grace_period` after its kwargs
  loop (`ValueError`, like the builder). Both use one
  `single_use.validate_refresh_token_grace()`.
- The ladders read the value through `single_use.refresh_token_grace(config)`,
  which clamps an assigned value to `[0, 60]` and falls back to 60 (with a
  WARNING) for a non-integer, so neither a huge value (reuse detection off)
  nor a string (a 500 on the reuse branch) reaches a request.
- The unreachable `getattr` fallbacks in the ladders are gone.
- New tests: `test_config_refuses_a_bad_value_at_construction` (five
  values), `test_the_ladders_read_a_clamped_value`, and the
  `assigned-3600-clamped-90s` ladder cases; all failed before.

**Files affected**:
- `actingweb/single_use.py`, `actingweb/config.py`, `actingweb/interface/app.py`, both ladders
- `tests/test_refresh_grace_setting.py`, both ladder test files

**Rationale**: the changelog and the plan promised refusal at configuration
time; configuration is trusted, but a misconfiguration must not silently
disable theft detection. The plan's failure scenario "a config built without
the builder lacks the attribute" is superseded by this one: the attribute
always exists, and its value is what needs checking.

#### 3. One reuse classifier and one default constant

**Category**: Verification fix (Issue 3)

**What changed**: the grace → theft → expired ladder lives once, in
`single_use.classify_reuse`, next to the shared consume. The SPA handler
keeps its two log lines inside the grace verdict (`GRACE_PERIOD_IMMEDIATE`
now only picks the line). `constants.REFRESH_TOKEN_GRACE_DEFAULT` is the one
default; `MCP_REFRESH_TOKEN_GRACE_PERIOD` and the SPA module's
`GRACE_PERIOD_EXTENDED` remain as aliases of it, since tests and possibly
consumers import them.

**Files affected**: `actingweb/constants.py`, `actingweb/single_use.py`, both ladders

**Rationale**: Issue 1 existed identically in two copies.

#### 4. The builder writes the grace only when it was given one

**Category**: Verification fix (Issue 4)

**What changed**: `ActingWebApp._refresh_token_grace_period` starts as
`None`; `get_config()` and `_apply_runtime_changes_to_config` write it to
the Config only after `with_refresh_token_grace()`, the way the
indexed-property settings already do. A value assigned on the Config then
survives the per-request `get_config()` calls of the integrations.
`configuration.rst` says the builder is the way to set it. Test:
`test_a_direct_assignment_survives_get_config` (failed before).

**Files affected**: `actingweb/interface/app.py`, `docs/quickstart/configuration.rst`,
`tests/test_refresh_grace_setting.py`

**Rationale**: `configuration.rst` lists the attribute as a setting; the
unconditional write reset it to 60 on the next request.

#### 5. The expiry-before-grace order is documented

**Category**: Verification fix (Issue 5)

**What changed**: the SPA guide's "Choosing the grace period" says a
consumed token presented after its own `expires_at` is refused as expired
even inside the grace period, and when that matters. No code change: both
stores check expiry first, and the owner chose to document it.

**Files affected**: `docs/guides/spa-authentication.rst`

**Rationale**: the grace contract had an undocumented exception.

#### 6. The benchmark todo is narrowed to its open question

**Category**: Verification fix (Issue 6)

**What changed**: the todo file (kept at its path) and its `INDEX.md` row
now describe only the open DynamoDB question (reject or coerce a non-bool
`callback`); the test half landed in Phase 1.

**Files affected**: `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`,
`thoughts/todo/INDEX.md`

**Rationale**: `todo/` holds only what is not done.

#### 7. Changelog rewrap and wording

**Category**: Verification fix (Issue 7)

**What changed**: the 101-character line in the MCP rotation SECURITY entry
is rewrapped. The ADDED entry now says `Config(...)` raises too, that an
assigned value is clamped, and that grace 0 makes a same-second duplicate
theft. `security.rst` names both places that raise.

**Files affected**: `CHANGELOG.rst`, `docs/reference/security.rst`

**Rationale**: exactly-true guarantee wording, per the project's changelog rule.

#### Checks after Iterations 1–7

- Fast tier: ruff, ruff format and pyright clean; unit tests 2756 passed.
- Full tier:
  - DynamoDB: 3735 passed, 31 skipped, and 1 error. The error was a
    teardown `TimeoutError` (a DynamoDB Local HTTP read) in
    `tests/test_bulk_list_update_handles.py::TestNoConcurrentWriterEverythingApplies::test_k10_update_and_k10_delete_all_apply_and_none_is_reported_raced`,
    which is list storage and untouched here. Re-run alone, the file gives
    20 passed: a parallel isolation flake, per the contract.
  - PostgreSQL: 3626 passed, 140 skipped, and 954 integration tests passed.
  - sphinx `-W`: build succeeded.
- Re-run `/verify_implementation` to move the plan's `verified:` link.

### 2026-09-27, after verification thoughts/verifications/2026-09-27-refresh-grace-setting-2.md

The owner chose: N1 is settled by rewording the docs, not with code (the
plan's "stay on standard mechanisms"); N3 by a validating property. The
rest (N2, N4–N9) are cleanups in the same batch.

#### 8. `Config.refresh_token_grace_period` is a validating property

**Category**: Verification fix (N3)

**What changed**:
- The attribute is a property on `Config`. Its setter runs
  `validate_refresh_token_grace`, so every write raises `ValueError` for a
  value that is not an integer from 0 to 60: the default in `__init__`, the
  kwargs loop, a later assignment, and the builder.
- The post-kwargs re-validation in `__init__` is gone, since the property
  covers it.
- The ladders keep `refresh_token_grace()` as a defensive clamp, which now
  only matters for a duck-typed config object.
- Tests: `test_assigning_a_bad_value_raises` (eight values, including
  `0.0`, `"0"` and `False`) failed before and passes now. The clamp test
  uses a `SimpleNamespace`. The `assigned-3600-clamped-90s` ladder cases
  are removed, because such an assignment now raises.

**Files affected**:
- `actingweb/config.py`: the property and setter.
- `tests/test_refresh_grace_setting.py` and both ladder test files.

**Rationale**: with three rules for a bad value (raise, raise, clamp or
default), an operator who assigned `0.0` or `"0"` silently got the widest
grace. Now there is one rule, and it fails where the value is set.

#### 9. What grace 0 promises is stated exactly

**Category**: Decision changed (N1, N2)

**What changed**: Every place that described `0` now says the same three
things:
- every reuse of a consumed token is answered as theft and its chain
  revoked;
- that also signs out a client's own concurrent duplicate and a client
  retrying after a refresh failed on a storage fault (N2);
- a request still being answered when the chain is revoked keeps the
  tokens it is issued, so `0` stops a later replay, not a simultaneous one
  (N1).

No code change.

**Files affected**:
- `actingweb/interface/app.py` (builder docstring)
- `CHANGELOG.rst` (ADDED)
- `docs/guides/spa-authentication.rst` ("Choosing the grace period")
- `docs/reference/security.rst`
- `docs/quickstart/configuration.rst`
- `docs/guides/mcp-applications.rst`

**Rationale**: the owner chose to reword rather than close the
concurrent-mint race in code, to stay on standard rotation mechanisms. The
race is not a regression: at the default grace a simultaneous pair both
rotate, as at HEAD. Grace 0 only adds the theft answer to the loser.

#### 10. "Never flagged" corrected; the builder-wins rule stated

**Category**: Verification fix (N4, N5)

**What changed**:
- The changelog, `security.rst` and the builder docstring now use the SPA
  guide's wording: a grace branch is flagged only if it later replays one
  of its own consumed tokens.
- The comment at `app.py` and `configuration.rst` say that after a builder
  call the builder's value wins over a direct assignment.
- The `single_use.refresh_token_grace` docstring now describes the clamp as
  defence in depth for non-`Config` objects.

**Files affected**:
- `CHANGELOG.rst`
- `docs/reference/security.rst`
- `actingweb/interface/app.py`
- `docs/quickstart/configuration.rst`
- `actingweb/single_use.py`

**Rationale**: the documents contradicted each other on a security
property.

#### 11. Old constant names say they are not read; a redundant assert is gone

**Category**: Verification fix (N6, N7)

**What changed**:
- `MCP_REFRESH_TOKEN_GRACE_PERIOD` and the SPA `GRACE_PERIOD_EXTENDED` are
  commented as the default's old names, which the ladders do not read.
- The `MCP_REFRESH_TOKEN_GRACE_PERIOD < MCP_REFRESH_TOKEN_REUSE_WINDOW`
  assert is removed; `REFRESH_TOKEN_GRACE_MAX < min(both windows)` covers
  it.

**Files affected**: `actingweb/constants.py`, `actingweb/handlers/oauth2_spa.py`

**Rationale**: "compat alias" suggested that patching them still took
effect.

#### 12. Older ladder tests seed ages from the config; the todo holds only what is open

**Category**: Verification fix (N8, N9)

**What changed**:
- The SPA rotation tests and the MCP cleanup test seed ages from
  `config.refresh_token_grace_period` instead of the old constant names.
- The benchmark todo and its `INDEX.md` row no longer record the half that
  landed. Iteration 6 and this plan are the record of it.

**Files affected**:
- `tests/test_oauth2_spa_refresh_rotation.py`, `tests/test_mcp_refresh_rotation.py`
- `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`, `thoughts/todo/INDEX.md`

**Rationale**: the tests silently assumed the fixture's grace equals the
default. `CLAUDE.md` says `todo/` holds only what is not done.

N10, the expiry-first order not tripping theft detection, is accepted as
designed (`c280bcf`, kept at the consumer's request). The SPA guide already
states that the expiry check comes first.

#### Checks after Iterations 8–12

- Fast tier:
  - ruff check and pyright are clean.
  - ruff format flagged one test file I edited; formatted, then clean.
  - Unit tests: 2763 passed.
- Full tier:
  - DynamoDB: 3742 passed, 31 skipped, including 962 integration tests.
  - PostgreSQL: 3633 passed, 140 skipped, including 954 integration tests.
  - sphinx `-W`: build succeeded.
  - No errors or flakes in this run.
- Re-run `/verify_implementation` to move the plan's `verified:` link.

### 2026-09-27, after verification thoughts/verifications/2026-09-27-refresh-grace-setting-3.md

The owner scoped this batch to P1–P6, all documentation wording, and set
aside P7 (the clock-skew bound, which predates this change), P8 (the clamp's
logging) and the DynamoDB Local teardown flake. Nothing was filed for them.

#### 13. Grace-0 and grace-branch wording made exact

**Category**: Verification fix (P1–P6)

**What changed**:
- **P1**: the in-flight request "may keep" its new tokens. They survive if
  created after the other request revoked the chain, and are revoked with
  it if created before, so `0` "stops a later replay, not reliably a
  simultaneous one". The caveat is now also in `mcp-applications.rst` and
  `configuration.rst`, which lacked it.
- **P5**: "every reuse ... inside the two-day reuse window". The SPA guide
  adds that a reuse after the window or after the token's own expiry is
  answered as expired, and that a pre-chain token revokes only itself.
- **P3**: the circular sentence in the SPA guide now states the cost: a
  thief and the legitimate client both hold working branches, and neither
  is flagged unless one later replays its own consumed token.
- **P2**: `oauth2-setup.rst` uses the same wording in place of "neither
  branch is flagged afterwards".
- **P4**: the builder's `Raises:` reads "not an integer from 0 to 60 (a
  `bool` is refused)".
- **P6**: the migration guide's two "60 seconds" now read "(the default
  grace period)" and "inside the grace period".

**Files affected**:
- `actingweb/interface/app.py` (docstring only)
- `CHANGELOG.rst`
- `docs/guides/spa-authentication.rst`, `docs/guides/oauth2-setup.rst`,
  `docs/guides/mcp-applications.rst`
- `docs/reference/security.rst`, `docs/quickstart/configuration.rst`,
  `docs/migration/v3.15.rst`

**Rationale**: these describe a security property, and the project's rule is
exactly-true guarantee wording. No code behaviour changed.

#### Checks after Iteration 13

- Fast tier: ruff, ruff format and pyright clean; unit tests 2763 passed.
- Full tier:
  - DynamoDB: 3742 passed, 31 skipped, and 1 teardown error. It is the
    known DynamoDB Local timeout, this time in
    `tests/test_bulk_list_update_handles.py`, which passes when run alone.
  - PostgreSQL: 3633 passed, 140 skipped.
  - sphinx `-W`: build succeeded.
