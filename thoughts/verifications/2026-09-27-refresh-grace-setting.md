# Verification: a configurable refresh-token grace period, and client guidance for lost responses

**Date:** 2026-09-27
**Plan:** thoughts/plans/2026-09-27-refresh-grace-setting.md
**Research:** thoughts/research/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md
**Branch:** release/3.15.0-refresh-grace
**Commit:** a25b64a, plus the uncommitted working tree (18 modified files and
the untracked `tests/test_refresh_grace_setting.py`). Nothing from either
phase is committed yet; this verifies the working tree.

## Automated Check Results

All checks ran once, sequentially, on the final working tree (one run at a
time, unsandboxed).

- **Browser QA:** N/A. No phase touches anything a user sees; the change is
  a configuration setting, two server-side comparisons, and docs.
- **Second opinion:** the outside-voice agent, with providers codex
  (`codex exec -s read-only`, unsandboxed) and a fresh-context Claude. The
  built-in `/code-review high` and security review also ran; the security
  review applied because the diff touches auth. Their findings are folded
  into Issues Found below.
  - The security review reported no vulnerability at confidence 8 or above.
    Its notes were the grace-0 boundary (Issue 1) and the end-of-life hole
    in the expiry-first order (Issue 5).
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (398 files).
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `make test-all-parallel`, DynamoDB: pass. 3710 passed, 31 skipped,
  including 962 integration tests.
- `make test-all-parallel`, PostgreSQL: pass. 3601 passed, 140 skipped,
  including 954 integration tests.
  - `tests/integration/test_mcp_refresh_rotation_backend.py` passed on
    PostgreSQL.
  - The extra skips are backend-specific: DynamoDB GSI, cost and partition
    unit tests, and `tests/integration/test_ttl_cleanup.py`.
  - The run takes 38 s because PostgreSQL is fast, not because tests were
    skipped.
- `sphinx-build -W --keep-going ...`: build succeeded.
- Benchmarks were not run alone: the plan does not touch list storage or
  the attribute layer. `make test-all-parallel` does run
  `tests/performance/` in parallel, and it passes on both backends.
- A direct demonstration on the in-memory double (a snippet, not a test):
  - With `config.refresh_token_grace_period = 0`, an MCP refresh token
    replayed in the same second as its rotation **rotated again**. The log
    reads: "reused 0s after rotation ... (within grace) - rotating again in
    the same chain".
  - `Config(refresh_token_grace_period=2592000)` was **accepted** unchanged.
  - See Issues 1 and 2.

## Phase Verification

### Phase 1: The grace setting - ISSUES FOUND

**Changes verified:**
- `actingweb/constants.py:212` defines `REFRESH_TOKEN_GRACE_MAX = 60`.
  - `:268-273` adds two invariants: the default lies in the range, and the
    ceiling is below both reuse windows.
  - This matches the plan, plus one extra invariant (a recorded deviation).
- `actingweb/config.py:156` has `self.refresh_token_grace_period: int =
  MCP_REFRESH_TOKEN_GRACE_PERIOD`.
  - It is set before the kwargs loop (`:286-287`), so a kwarg overrides it.
  - It matches the plan, but the kwarg path is not validated (Issue 2).
- `actingweb/interface/app.py:559-596` adds `with_refresh_token_grace()`.
  - It checks the range and refuses `bool`/non-`int` with `ValueError`.
  - It applies the value through `_apply_runtime_changes_to_config`
    (`:210`) and the `Config(...)` kwarg (`:1340`).
  - This matches the plan. The unconditional write at `:210` is Issue 4.
- `actingweb/handlers/oauth2_spa.py:665-677` sets `grace = int(getattr(self.config,
  "refresh_token_grace_period", GRACE_PERIOD_EXTENDED))`.
  - The immediate tier is `min(GRACE_PERIOD_IMMEDIATE, grace)`, and the
    extended tier is `<= grace`.
  - This matches the plan. The inclusive `<=` is Issue 1.
- `actingweb/oauth2_server/token_manager.py:436-443` has the same
  `getattr`, then `if age <= grace:`.
  - The docstring at `:315-327` names the setting, and the recovery-contract
    paragraph no longer says "60 s".
  - This matches the plan. The inclusive `<=` is Issue 1.
- `actingweb/oauth_session.py` checks expiry before "used". It was already
  on the branch (`c280bcf`) and was out of this run's implementation scope.
  Issue 5 notes its interaction with the grace period.

**Tests verified:**
- `tests/test_refresh_grace_setting.py` covers:
  - the default reaching `Config` and `Config()`;
  - 0, 30 and 60 accepted;
  - -1, 61 and 3600 refused, with the value left at 60;
  - `True`, `30.0` and `"30"` refused;
  - a call after `get_config()` reaching the same `Config`;
  - a later builder call keeping the value.
  - These tests are meaningful. The parameter list `[0, 30, 60,
    REFRESH_TOKEN_GRACE_MAX]` tests 60 twice.
- `tests/test_oauth2_spa_refresh_rotation.py:239` and
  `tests/test_mcp_refresh_rotation.py:181` hold
  `test_the_configured_grace_decides_rotation_or_theft`, with five cases
  each (grace 20 at 15 s and 40 s, grace 0 at 5 s, default at 30 s and
  90 s). All pass.
  - Only grace 20 at 40 s and grace 0 at 5 s fail without the change. The
    default cases pin the old hard-coded value.
  - No case covers grace 0 at age 0, the boundary the docs make promises
    about (Issue 1).
- `test_a_used_token_past_its_expiry_is_expired_not_theft` is present and
  passes.

**Failure scenarios in the plan:**
- *"A config built without the builder lacks the attribute; the `getattr`
  fallback gives 60."*
  - This path can no longer happen: `config.py:156` always sets the
    attribute, so the fallback never fires.
  - The real risk for a `Config` built without the builder is an
    unvalidated value (Issue 2), and no test covers it.
- *"A deployment sets the grace above 60 s: refused at configuration time,
  never at request time."*
  - Holds for the builder: `tests/test_refresh_grace_setting.py:31-36`.
  - Does **not** hold for `Config(refresh_token_grace_period=...)` or for
    assigning the attribute directly. Demonstrated; Issue 2.
- *"Grace 0 with a genuine concurrent duplicate: the second is theft ...
  the grace-0 test pins it."*
  - **Not true.** A duplicate in the same second rotates on both ladders.
    Demonstrated on MCP; the SPA code has the same `<=` at
    `oauth2_spa.py:671` and `:677`.
  - The grace-0 test replays at 5 s (`:233`, `:175`), so it never exercises
    this. Issue 1.

**Deviations from plan:**
- The builder refuses non-integers: acceptable.
- Two extra invariants in `constants.py`: acceptable.
- `tests/performance/test_backend_performance.py:365,393` now pass
  `callback=True`. This is outside the plan's scope but is exactly the fix
  in `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`,
  and the plan records it. The todo was not updated: Issue 6.

### Phase 2: Docs, changelog and client guidance - ISSUES FOUND

**Changes verified:**
- `docs/guides/spa-authentication.rst`: the setting is described in the
  rotation list, and there are two new sections:
  - `spa-refresh-grace`, "Choosing the grace period", which covers the
    cost, the ceiling, and that no value covers a sleep;
  - `spa-refresh-reliably`, which gives rules 1–7. These match the plan's
    guidance, renumbered, including the corrected rule 3 and the
    persist-failure rule.
  - The ~1548 and ~1586 passages were updated.
- `docs/guides/oauth2-setup.rst:336-345` and
  `docs/guides/mcp-applications.rst` (new "Refresh Tokens" subsection):
  match the plan.
- `docs/guides/troubleshooting.rst`: the one-hour entry names the setting,
  and a new entry covers "log in again after the device slept". Matches.
- `docs/reference/security.rst:55-57` and
  `docs/quickstart/configuration.rst:47`: match the plan.
- `CHANGELOG.rst`: the ADDED entry is at `:207`, and the MCP rotation
  SECURITY entry names the setting (`:75-77`). This matches the plan, but
  `:77` is a 101-character unwrapped line (Issue 7).
- `docs/migration/v3.15.rst:95-102`: matches the plan.
- The hand grep review ran: the remaining fixed "60 seconds" mentions are
  qualified or historical.

**Tests verified:** `sphinx-build -W` passes.

**Deviations from plan:**
- The guidance is numbered 1–7, and troubleshooting has a separate
  sleep-related entry instead of an extended one-hour entry. Both are
  acceptable and recorded in the plan.
- **Concerning:** the docs promise that grace `0` makes "every reuse
  theft". The same promise appears in `actingweb/interface/app.py:573`,
  `CHANGELOG.rst:221`, `docs/guides/spa-authentication.rst:742`,
  `docs/guides/mcp-applications.rst:601` and
  `docs/reference/security.rst:56`. The code does not deliver it (Issue 1).
  The changelog also says a bad value "raises ``ValueError`` when the app
  is configured" (`CHANGELOG.rst:218`), which is true only through the
  builder (Issue 2).

**Consumer message** (the 3.15.0 plan's Phase 4,
`thoughts/plans/2026-09-25-mcp-oauth-hardening-and-credential-exposure.md:1137-1149`):

> Also: bump the pin to the rc; the refresh grace period is now
> `with_refresh_token_grace(seconds)` (0 to 60, default 60, both ladders),
> and the consumer needs no change to it (their feedback: no value up to
> 60 s covers a 336 s gap); the SPA store now reads a consumed token past
> its own `expires_at` as expired, not theft (`c280bcf`). For their #109,
> point at the SPA guide's "Refreshing reliably on native and mobile
> clients": no refresh started during a dark wake or once sleep is
> announced; a power assertion / `beginBackgroundTask` around an in-flight
> refresh; a timeout on the refresh request; a failed persist of the new
> refresh token is a failed refresh; keep single-flight, the final 401 and
> keep-on-ambiguous-failure, without counting on a retry after sleep.

This is still accurate after implementation. The consumer keeps the
default, so Issues 1 and 2 do not affect them.

## Todo check

- The plan closes no todo.
- The plan defers `thoughts/todo/token-store-fault-contract-gaps.md`, which
  exists with its `INDEX.md` row (`:44`).
- `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`
  and `INDEX.md:50` were **not** updated, although its test fix landed. See
  Issue 6.

## Remaining Tasks

- [ ] Fix the grace-0 boundary on both ladders, and add an age-0 case to
      both ladder tests (Issue 1).
- [ ] Validate or clamp the grace outside the builder (Issue 2), and rewrite
      the plan's "lacks the attribute" failure scenario.
- [ ] Decide whether `_apply_runtime_changes_to_config` should write the
      grace only when the builder set it (Issue 4).
- [ ] Narrow the benchmark todo to its open DynamoDB question, or delete it
      with its `INDEX.md` row (Issue 6).
- [ ] Rewrap `CHANGELOG.rst:77` (Issue 7).
- [ ] Decide whether to document the expiry-first hole in the grace period
      (Issue 5).

All of these are for `/iterate_plan` on this plan before the commit; none
is deferred, so no todo is filed.

## Issues Found

### 1. Grace 0 does not make every reuse theft: a same-second reuse still rotates

**Severity:** Medium

**Description:**
- Both ladders compare whole-second ages with an inclusive `<=`.
- `used_at` is `int(time.time())`, so a reuse within the same wall-clock
  second has age 0, and `0 <= 0` rotates.
- A negative age also rotates. That happens when another worker's clock
  ran ahead when it stamped `used_at`.
- The docs name this exact case, "two tabs or windows refreshing the same
  token at the same moment", as theft under grace 0.
- A deployment that picks 0 for a strict posture gets an unflagged branch
  in the one case it chose 0 to exclude.
- Demonstrated on the MCP ladder above.

**Location:**
- `actingweb/handlers/oauth2_spa.py:671` `if time_since_use <= min(GRACE_PERIOD_IMMEDIATE, grace):`
  and `:677` `elif time_since_use <= grace:`
- `actingweb/oauth2_server/token_manager.py:443` `if age <= grace:`
- Claims:
  - `actingweb/interface/app.py:573`
  - `CHANGELOG.rst:221`
  - `docs/guides/spa-authentication.rst:742`
  - `docs/guides/mcp-applications.rst:601`
  - `docs/reference/security.rst:56`
  - `docs/quickstart/configuration.rst:47`

**Recommendation:**
- Treat grace 0 as "no grace": rotate only when `grace > 0 and age <=
  grace`.
- Add `(0, 0, False)` to both parametrizations; it fails today.
- Alternatively, reword every claim to "a reuse after the same second". The
  project's changelog rule favours exactly-true wording, but the code fix
  is the smaller change.

### 2. The 0–60 bound is enforced only by the builder

**Severity:** Medium

**Description:**
- `Config.__init__` applies kwargs with `setattr` and no check.
- `Config(refresh_token_grace_period=2592000)` is accepted (demonstrated),
  and so is assigning the attribute directly.
- A grace at or above a reuse window turns off theft detection on that
  grant without any error. The grace tier is tested before the theft and
  expired tiers.
- A non-numeric value raises in `int(...)` on the reuse branch only, which
  is a 500 during concurrent refreshes in production, never at startup.
- The changelog (`CHANGELOG.rst:218`) and the plan promise refusal "at
  configuration time". The import-time assert in `constants.py:271` checks
  the constant, not the value the ladders read.
- Configuration is trusted, so this is not an attack path. It is a promise
  the code does not keep.

**Location:**
- `actingweb/config.py:286-287` `for k, v in kwargs.items(): self.__setattr__(k, v)`
- `actingweb/handlers/oauth2_spa.py:665`
- `actingweb/oauth2_server/token_manager.py:436`

**Recommendation:**
- Validate after the kwargs loop in `Config.__init__`, raising
  `ValueError`, like the builder.
- Also clamp to `[0, REFRESH_TOKEN_GRACE_MAX]` where the ladders read the
  value, which covers direct assignment.
- Read the attribute directly: the `getattr` fallback is unreachable.
- Test a bad kwarg.

### 3. The same reuse-age ladder is written twice

**Severity:** Low (maintainability)

**Description:**
- The grace → theft window → expired classification is implemented
  separately in the SPA handler and the MCP token manager.
- Each has its own `getattr`/`int` and its own default constant
  (`GRACE_PERIOD_EXTENDED` versus `MCP_REFRESH_TOKEN_GRACE_PERIOD`; the
  latter is now the default for both grants despite its name).
- Issue 1 exists identically in both copies.

**Location:**
- `actingweb/handlers/oauth2_spa.py:56`, `:663-683`
- `actingweb/oauth2_server/token_manager.py:436-452`

**Recommendation:**
- Consider one `classify_reuse(age, grace, window)` helper, for example in
  `actingweb/single_use.py`, which already holds the shared consume step.
- Consider one `REFRESH_TOKEN_GRACE_DEFAULT` constant.
- This is optional in this plan. Fixing Issue 1 in one place is the
  argument for it.

### 4. Every `get_config()` call writes the builder's value back over a direct `Config` assignment

**Severity:** Low

**Description:**
- `_apply_runtime_changes_to_config` writes the grace unconditionally.
- The FastAPI and Flask integrations call `self.aw_app.get_config()` per
  request (for example `fastapi_integration.py:632`), and each call runs it.
- A consumer who sets `app.get_config().refresh_token_grace_period = 10`,
  as `configuration.rst:47` lists the attribute, has it reset to the
  builder value (60) on the next request.
- The same function's comment about indexed properties records this
  hazard, and fixed it for those settings with a `None` sentinel.
- The other runtime switches (`ui`, `devtest`) behave the same way, so it
  is consistent, but the docs present the attribute as a setting.

**Location:** `actingweb/interface/app.py:210`
`self._config.refresh_token_grace_period = self._refresh_token_grace_period`

**Recommendation:**
- Either use a `None` sentinel and write only after
  `with_refresh_token_grace()`,
- or say in `configuration.rst` that the builder is the only supported way
  to set it.

### 5. With expiry checked first, the grace period does not cover a token consumed just before its expiry

**Severity:** Low

**Description:**
- A client refreshes one second before the token's 14-day `expires_at` and
  loses the response.
- Its retry 5 s later, inside the grace period, now meets the expiry check
  first. The row is deleted, and the client gets 401 "Invalid or expired
  refresh_token" instead of a rotation.
- The MCP store has the same order, so the two ladders agree.
- The window is small: only a lost response in the last grace period of a
  14-day life. The rotation sliding the expiry makes it rarer still.
- The docs describe the grace period with no such exception.

**Location:** `actingweb/oauth_session.py:716-726` (commit `c280bcf`)

**Recommendation:**
- Accept, and add one sentence where the grace is described.
- Alternatively, compare expiry against `used_at` for used rows.
- Owner's call; it is not a regression the consumer reported.

### 6. The benchmark todo was fixed but not closed

**Severity:** Low

**Description:**
- The `callback=True` fix is the todo's first half.
- Its second half, whether DynamoDB should reject or coerce a non-bool
  `callback`, is still open.
- The file and its `INDEX.md` row still describe both halves as open.
- `CLAUDE.md`: "`todo/` holds only what is NOT done."

**Location:**
- `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md`
- `thoughts/todo/INDEX.md:50`

**Recommendation:**
- Narrow the todo and its row to the DynamoDB question,
- or delete both if the owner drops that question.

### 7. An unwrapped line in the changelog SECURITY entry

**Severity:** Low

**Description:** The inserted sentence left a 101-character line in an
entry otherwise wrapped at 76 characters.

**Location:** `CHANGELOG.rst:77`

**Recommendation:** Rewrap the paragraph.

## Overall Assessment

Both phases are implemented as planned, and the full tier is green on both
backends. The default behaviour is unchanged, pinned by the default cases on
both ladders and by the passing integration rotation test, so a deployment
that never calls the method, including the consumer, sees no difference.
The client guidance, the troubleshooting entry and the consumer message are
accurate and complete.

The new setting does not yet keep two of its documented promises. Grace `0`
still rotates a reuse within the same second (Issue 1, demonstrated), and
the 0–60 bound is enforced only by the builder, not by `Config` (Issue 2,
demonstrated). Neither affects the default or the consumer, and neither is
an attack path, since configuration is trusted. But the changelog, the
builder docstring and four docs pages state them as guarantees, and the
project's rule is that exactly-true wording wins. Fix Issues 1 and 2 through
`/iterate_plan` before committing, with the age-0 and bad-kwarg tests that
would have caught them. Issues 3–7 are small and can go in the same pass or
be accepted.
