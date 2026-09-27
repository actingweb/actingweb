# Verification: a configurable refresh-token grace period, and client guidance for lost responses (re-run after Iterations 1–7)

**Date:** 2026-09-27
**Plan:** thoughts/plans/2026-09-27-refresh-grace-setting.md
**Research:** thoughts/research/2026-09-26-spa-refresh-reuse-after-dropped-rotation.md
**Branch:** release/3.15.0-refresh-grace
**Commit:** a25b64a, plus the uncommitted working tree: both phases and
Iterations 1–7. Nothing is committed yet; this verifies the working tree.

This is the second verification today. It gets the `-2` suffix because the
first run holds the plain slug.

## Automated Check Results

All checks ran sequentially, one run at a time, unsandboxed, on the working
tree as it stands after Iterations 1–7.

- **Browser QA:** N/A. No phase touches anything a user sees.
- **Second opinion:** four reviewers. Their findings are folded into Issues
  Found below.
  - Outside-voice agent, with providers codex (`codex exec -s read-only`,
    unsandboxed) and a fresh-context Claude.
  - The built-in `/code-review high`.
  - The built-in security review. The diff touches auth. It found no
    vulnerability at confidence 8 or above, and compared each ladder branch
    against HEAD: identical at the default grace, stricter below it.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (398 files).
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `make test-all-parallel`, DynamoDB: 3735 passed, 31 skipped, and
  **1 error**. 962 integration tests passed.
  - The error is a teardown `PutError` from DynamoDB Local, "This action
    timed out because it too long waiting for a lock. This request will
    succeed in actual DynamoDB API", in
    `tests/test_hot_path_n_plus_one.py::TestPropertyStoreBulkReads::test_items_and_values_are_bulk_reads`.
    That is property storage, untouched here.
  - Re-run alone, the file gives 11 passed. This is a parallel isolation
    flake, per the contract.
  - The run after Iterations 1–7 had a different single teardown timeout,
    in `tests/test_bulk_list_update_handles.py`, which passed alone.
- `make test-all-parallel`, PostgreSQL: pass. 3626 passed, 140 skipped
  (backend-specific), including 954 integration tests.
- `sphinx-build -W --keep-going ...`: build succeeded.

## Phase Verification

### Phase 1: The grace setting - ISSUES FOUND

**Changes verified:**
- `actingweb/constants.py:208-214` has `REFRESH_TOKEN_GRACE_DEFAULT = 60`
  and `REFRESH_TOKEN_GRACE_MAX = 60`.
  - `MCP_REFRESH_TOKEN_GRACE_PERIOD` is an alias of the default.
  - The invariants are at `:266-276`, one of them now redundant (Issue N7).
- `actingweb/single_use.py:26-83` holds the three shared helpers:
  - `validate_refresh_token_grace()` raises `ValueError` for anything that
    is not an integer from 0 to 60, and refuses a bool.
  - `refresh_token_grace(config)` clamps an integer to 0–60 and returns 60
    for a non-integer, with a WARNING (Issue N3).
  - `classify_reuse()` returns grace when `grace > 0 and age <= grace`,
    theft when `age <= reuse_window`, and expired otherwise.
- `actingweb/config.py:157` sets the default; `:291` validates the value
  after the kwargs loop. This matches Iteration 2.
- `actingweb/interface/app.py`:
  - `:78` starts the builder value at `None`.
  - `:213` and `:1347` write it to the Config only when the builder was
    given one.
  - `:589` validates through the shared helper.
  - This matches Iteration 4. The comment at `:212` overstates it
    (Issue N4).
- `actingweb/handlers/oauth2_spa.py:663-718` and
  `actingweb/oauth2_server/token_manager.py:430-470` both use
  `classify_reuse`.
  - The security review compared them branch by branch with HEAD: no
    change at the default grace, and grace 0 only makes them stricter.
  - The theft bodies (chain revocation, a legacy chain-less token revoked
    alone) are unchanged, and so are the refusals for a missing `used_at`
    and a vanished row.
- There is no import cycle: `single_use` imports `config` only under
  `TYPE_CHECKING`.
- No `Config(...)` caller in `actingweb/`, `examples/` or `tests/` passes a
  value that now raises.

**Tests verified:**
- `tests/test_refresh_grace_setting.py` covers:
  - the builder bounds and types;
  - `test_config_refuses_a_bad_value_at_construction` (five values);
  - `test_a_direct_assignment_survives_get_config`;
  - `test_the_ladders_read_a_clamped_value`;
  - `test_classify_reuse` (eight cases, including age 0 and negative ages
    at grace 0).
  - All pass. The Iterations say each new behaviour test failed before its
    fix; those outputs are recorded in this session.
- `test_the_configured_grace_decides_rotation_or_theft`, in both ladder
  files, now has seven cases, including `grace0-same-second` and
  `assigned-3600-clamped-90s`. All pass.
- Not covered: two requests presenting the same token concurrently under
  grace 0 (Issue N1). The older tests seed ages from the alias constants
  (Issue N8).

**Failure scenarios:**
- *A bad value is refused at configuration time.* This now holds for the
  builder (`app.py:589`) and `Config(...)` (`config.py:291`); tested.
- *A value assigned after construction.* It is clamped when a refresh reads
  it (tested), but a non-integer becomes 60 (Issue N3).
- *Grace 0 and a concurrent duplicate.* The duplicate is answered as theft,
  including within the same second (tested). The chain revocation can miss
  the winner's successor, which is still being minted (Issue N1).

**Deviations from plan:** Iterations 1–4 are recorded in the plan. All are
acceptable.

### Phase 2: Docs, changelog and client guidance - ISSUES FOUND

**Changes verified:**
- The SPA guide now has the expiry sentence under "Choosing the grace
  period" (Iteration 5).
- The changelog ADDED entry now names `Config(...)`, the clamp, and the
  same-second case.
- The long line in the SECURITY entry is split. `CHANGELOG.rst:83` is now a
  short line, which is valid RST.
- `security.rst:56` and `configuration.rst:47` are updated.
- The docs build passes.

**Still inexact:**
- The grace-0 wording (Issue N1).
- The store-fault retry under grace 0 (Issue N2).
- "never flags" in two places (Issue N5).

**Consumer message:** unchanged since the first verification, which
quoted it. It is still accurate: the consumer keeps the default grace, and
at the default every ladder branch behaves as it does at HEAD.

## Todo check

- The benchmark todo is narrowed to the open DynamoDB question, and its
  `INDEX.md` row is updated. The file still names what landed (Issue N9).
- `token-store-fault-contract-gaps.md`, which the plan defers, is present
  with its row.
- The plan closes no other todo.

## Previous Verification

**Previous:** thoughts/verifications/2026-09-27-refresh-grace-setting.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Grace 0 does not make every reuse theft (same-second) | Fixed. Residual: concurrent-mint race, N1 | `single_use.py:78` `if grace > 0 and age <= grace:`; `grace0-same-second` cases pass on both ladders |
| 2. The bound is enforced only by the builder | Fixed. Residual: non-integer falls back to 60, N3 | `config.py:291`; `test_config_refuses_a_bad_value_at_construction`; clamp in `single_use.py:46-62` |
| 3. The reuse ladder is written twice | Fixed | `classify_reuse` used at `oauth2_spa.py:666` and `token_manager.py:433` |
| 4. `get_config()` overwrites a direct assignment | Fixed when the builder was not called. Residual: comment overstates, N4 | `app.py:213`; `test_a_direct_assignment_survives_get_config` |
| 5. The grace does not cover a token near its expiry | Accepted and documented | `docs/guides/spa-authentication.rst`, "A token's own expiry comes first" |
| 6. The benchmark todo was not closed | Fixed. Residual: provenance note, N9 | the todo file and `INDEX.md` row |
| 7. Unwrapped changelog line | Fixed | `CHANGELOG.rst:77-83` |

## Remaining Tasks

- [ ] Decide what grace 0 promises about concurrent presentations. Then
      either close the race or qualify the wording (Issue N1).
- [ ] Document that grace 0 also removes the retry-after-store-fault
      recovery (Issue N2).
- [ ] Decide the non-integer fallback: 60, 0, or a validating property on
      `Config` (Issue N3).
- [ ] Low-severity cleanups N4–N9.
- [ ] Optional: say in `security.rst` that a replay after the token's own
      expiry is not treated as theft (Issue N10).

These are for another `/iterate_plan` on this plan before committing. None
is deferred, so no todo is filed.

## Issues Found

### N1. Under grace 0, the theft revocation races the winning request's mint

**Severity:** Medium

**Description:**
- Two requests present the same refresh token at the same moment.
- One wins the consume (`oauth2_spa.py:629`, `token_manager.py:371`). The
  other now gets a "theft" verdict and revokes the chain (`oauth2_spa.py:713`
  `revoked = session_manager.revoke_token_chain(actor_id, chain_id)`,
  `token_manager.py:448`).
- The winner mints its successor only afterwards (`oauth2_spa.py:738`
  `new_refresh_token = session_manager.create_refresh_token(`,
  `token_manager.py:474`), so the successor can be created after the chain
  was revoked and survive it. On MCP, the winner first removes its old
  access token (`:403`), which widens the window.
- Whoever won keeps a working session, and nothing flags it. If the winner
  was a thief, the victim is logged out and the thief is not.
- This is no regression. At HEAD, and at the default grace, the same pair
  both rotate and nothing is revoked.
- But the docs say grace 0 makes every reuse theft, "including two tabs
  refreshing the same token at the same moment" (`app.py:577`,
  `CHANGELOG.rst:224`, `spa-authentication.rst:742`, `security.rst:56`).
  That reads as "the chain is revoked", and for the in-flight successor it
  is not.
- Found by the fresh-context Claude reviewer and the code review
  independently. Not reproduced: it is timing-dependent. The code order
  above is the evidence.

**Location:** `actingweb/handlers/oauth2_spa.py:629,713,738`;
`actingweb/oauth2_server/token_manager.py:371,448,474`

**Recommendation:** decide the promise.
- Option 1: close the race. The winner re-checks that its chain still
  exists after minting and revokes what it minted if not; or the loser's
  revocation is re-applied after a short delay.
- Option 2: qualify the docs to "a reuse is answered as theft; a request
  still in flight when the chain is revoked may keep its new tokens".
- Option 2 matches this plan's "stay on standard mechanisms" decision.

### N2. Grace 0 also removes the retry-after-store-fault recovery

**Severity:** Low

**Description:**
- The MCP docstring (`token_manager.py:327`) says the grace period is the
  recovery contract when minting fails after the consume: "a retry within
  the grace period rotates". The SPA grant behaves the same way.
- Under grace 0 that retry is theft. A transient backend fault then logs
  the user out.
- The builder docstring and the ADDED entry warn only about concurrent
  duplicates.

**Location:** `actingweb/interface/app.py:559-590`; `CHANGELOG.rst:207-227`

**Recommendation:** name this second cost of `0` wherever the first is
named.

### N3. A non-integer assigned after construction falls back to the widest grace

**Severity:** Low

**Description:**
- `refresh_token_grace()` returns 60 for `False`, `0.0` or `"0"`
  (`single_use.py:56-61`), and the test pins `(True, 60)`.
- An operator who meant "off" gets the maximum. The only signal is a
  WARNING on each reuse.
- A bad value is handled three ways: the builder raises, `Config(...)`
  raises, and a later assignment is clamped or replaced by the default.
- Configuration is trusted, and 60 is the shipped default, so this is not
  an exploit.

**Location:** `actingweb/single_use.py:46-62`

**Recommendation:** the owner decides.
- Either make `refresh_token_grace_period` a validating property on
  `Config`, so every write raises (one rule),
- or fall back to 0 (fail closed),
- or keep 60 and say so in the changelog. `CHANGELOG.rst:221-222` says
  only "clamped".

### N4. The comment says a direct assignment survives, but a builder call still wins

**Severity:** Low

**Description:**
- After `with_refresh_token_grace(30)`, assigning 5 on the Config is reset
  to 30 by the next `get_config()`.
- This is the intended precedence (builder over direct), the same as the
  indexed-property settings. But the comment at `app.py:212`, "so a value
  assigned on the Config survives", and `configuration.rst:47` do not say
  that the builder wins.

**Location:** `actingweb/interface/app.py:212`

**Recommendation:** reword to "survives unless the builder was also
called".

### N5. The docs contradict each other on whether a grace branch is "never" flagged

**Severity:** Low

**Description:**
- `CHANGELOG.rst:223` and `security.rst:56` say a branch made inside the
  grace is one "reuse detection never flags".
- The SPA guide says such a branch is flagged if it later replays one of
  its *own* consumed tokens.
- "every reuse is theft" also does not cover a malformed row without
  `used_at` (SPA: expired; MCP: refused).

**Location:** `CHANGELOG.rst:223`; `docs/reference/security.rst:56`

**Recommendation:** use the SPA guide's wording in both places.

### N6. The alias constants no longer control anything

**Severity:** Low

**Description:**
- `GRACE_PERIOD_EXTENDED` (`oauth2_spa.py:56`) and
  `MCP_REFRESH_TOKEN_GRACE_PERIOD` (`constants.py:214`) are labelled
  "compat alias" but are not read by either ladder.
- Code that reads them to learn the effective grace, or patches them to
  change it, gets the default.
- `actingweb_mcp` does not reference them, per the outside-voice agent.

**Location:** `actingweb/handlers/oauth2_spa.py:56`;
`actingweb/constants.py:214`

**Recommendation:** comment them as "the default; not read by the ladders;
use `single_use.refresh_token_grace(config)`".

### N7. The old constant invariant is redundant

**Severity:** Low

**Description:** `constants.py:266`
`assert MCP_REFRESH_TOKEN_GRACE_PERIOD < MCP_REFRESH_TOKEN_REUSE_WINDOW`
checks the alias of the default. The new `REFRESH_TOKEN_GRACE_MAX < min(...)`
assertion covers it.

**Location:** `actingweb/constants.py:266`

**Recommendation:** remove it.

### N8. The older ladder tests seed ages from the alias constants

**Severity:** Low

**Description:**
- `test_reuse_within_grace_window_issues_full_rotation` and others seed
  `GRACE_PERIOD_EXTENDED ± n`.
- They silently assume the fixture's grace equals that default.

**Location:** `tests/test_oauth2_spa_refresh_rotation.py:76` and following;
`tests/test_mcp_refresh_rotation.py`

**Recommendation:** seed from `refresh_token_grace(config)`.

### N9. The narrowed todo still records what landed

**Severity:** Low

**Description:**
- The file opens with "Narrowed on 2026-09-27: the test half landed ...",
  and the `INDEX.md` row says the same.
- `CLAUDE.md`: "todo/ holds only what is NOT done ... the plan and the
  verification are the record."

**Location:** `thoughts/todo/benchmark-subscription-tests-pass-url-to-boolean-callback.md:5`;
`thoughts/todo/INDEX.md`

**Recommendation:** drop the landed half from both; the plan's Iteration 6
records it.

### N10. With expiry checked first, a replay after the token's own expiry does not trip theft detection

**Severity:** Low (accepted design)

**Description:**
- A thief who consumes a token shortly before its `expires_at` keeps the
  branch when the victim later replays the expired token: the replay reads
  as expired, and the chain is not revoked.
- This is the intended effect of `c280bcf`, which the consumer asked to
  keep. It matches the MCP store's order, and HEAD already missed a victim
  returning more than two days later.
- The security review rated it a hardening question, not an exploit.

**Location:** `actingweb/oauth_session.py:716-726`

**Recommendation:** accept. Optionally say it in `security.rst`.

## Overall Assessment

Both phases and Iterations 1–7 are implemented. The full tier is green on
PostgreSQL, and green on DynamoDB apart from one isolation flake that passes
when re-run alone. Every issue from the first verification is fixed or
accepted, and each fix has a test that failed before it. The security review
found no vulnerability. At the default grace, both ladders behave as they
do at HEAD, so the consumer and every deployment that does not call the
method are unaffected.

What is left concerns the new grace-0 option only. The docs promise more
than it delivers under concurrency: N1, where the revocation races the
winner's mint, and N2, where the store-fault retry becomes theft. The
non-integer fallback (N3) is a choice worth making explicitly. N4–N9 are
wording and hygiene. None blocks the default path, but the changelog's
guarantee wording should be exactly true before this is committed. The next
step is one more `/iterate_plan` to settle N1–N3 and clean up N4–N9.
