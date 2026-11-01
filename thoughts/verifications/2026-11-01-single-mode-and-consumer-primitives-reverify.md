# Verification: One mode after the 3.16 upgrade, and the two consumer primitives (re-run)

**Date:** 2026-11-01
**Feature:** thoughts/features/2026-11-01-single-mode-and-consumer-primitives.md
**Plan:** thoughts/plans/2026-11-01-single-mode-and-consumer-primitives.md (all four phases, plus Iterations 1-15)
**Research:** thoughts/research/2026-11-01-single-mode-and-consumer-primitives.md
**Branch:** release/3.16.0-single-mode-and-consumer-primitives
**Commit:** `c3dba9e` plus the uncommitted iteration fixes (Iterations 1-15 in the plan)

A same-day re-run: `2026-11-01-single-mode-and-consumer-primitives.md` already holds this
date and slug, and a verification is not edited after it is written, so this one carries a
`-reverify` suffix. It verifies the whole plan on the tree as it stands after the iterations.

## Automated Check Results

- **Browser QA:** N/A. No phase touches a page; the SPA endpoints are JSON. The plan's manual
  demo and `curl` walks were not run; tests drive the same requests through both integrations.
- **Second opinion:** three rounds of the outside voice.
  - Round 1, on `2835d00..HEAD`: codex (`codex review --base`) and a fresh-context Claude.
  - Round 2, on the first fixes: fresh-context Claude only. Codex failed to start.
  - Round 3, on the second and third fixes: codex (`codex exec -s read-only`, sandbox off) and
    Claude.
  - The final round reported **no High or Medium findings** from either model.
- **Built-in code review (high, no `--fix`):** 10 findings. Their fate is in the Previous
  Verification table and in Issues Found.
- **Built-in security review:** nothing at the bar. Two notes fell below it: the backfill
  ownership order, and escaped excludes meaning less than before.
- **Scenario-to-test mapping** (codebase-analyzer): 12 promised tests were missing or partial.
  All were added in Iterations 2 and 8, or are recorded below as accepted deviations.
- ruff check, ruff format --check, pyright: 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: 51 groups documented.
- Full tier, DynamoDB (`pytest tests/ -n auto --dist loadgroup`), **the first run on an empty
  DynamoDB Local**: 5160 passed, 43 skipped, twice against one store.
- Full tier, PostgreSQL (after `alembic upgrade head`): 4967 passed, 236 skipped, twice.
- `sphinx-build -W`: pass.
- Environment: the OrbStack VM was still asleep (`docker ps` hung), so the runs used the same
  scratch DynamoDB Local 2.x (port 8002) and `pixeltable-pgserver` PostgreSQL (port 5434) as
  the previous verification. **Deduced, not confirmed:** these stand in for the compose
  containers. CI on the PR runs the real matrix.

## Phase Verification

### Phase 1: One reverse-lookup mechanism - VERIFIED (after Iterations 1-5, 9-11, 13, 15)

**Changes verified:**
- `actingweb/db/dynamodb/property.py`: D15 transaction as planned. The unchanged-value path
  now heals a missing lookup row. That is a decision change, Iteration 4. The heal is
  conditioned on the property value and on the actor row (Iterations 9 and 13).
- `actingweb/db/postgresql/property.py`: the unchanged-value insert runs in the same
  transaction (Iteration 4).
- `actingweb/maintenance/property_lookup.py`: report, backfill, mark-complete and unmark as
  planned. Collisions survive a resume (Iterations 2 and 10). The dry run predicts collisions
  on both backends and counts its read faults (Iterations 3, 10 and 15).
- `actingweb/interface/app.py`: `check_ready()` and the refusals. The refusal names the
  recorded set (Iterations 5 and 11).

**Tests verified:** every Failure Scenario has a test or the documented acceptance. Gaps
closed:
- marker and set write fault: `tests/test_property_lookup_readiness.py`,
  `test_a_marker_or_set_write_fault_says_it_could_not_be_checked`;
- shim prints and delegates: `tests/test_property_lookup_command.py`,
  `test_main_prints_the_new_command_and_delegates`;
- the re-run retries a faulted page: `test_a_write_fault_is_not_a_collision_and_marks_nothing`;
- empty-store fixture ordering: `tests/test_lookup_migration.py`,
  `tests/test_property_lookup_command.py`.

**Deviations from plan:** D15's "unchanged value skips the sync" became "unchanged value
heals a missing row" (recorded in Iteration 4). `--properties` is tested on `backfill` and
`report`, not on every subcommand (acceptable: one parser path).

### Phase 2: Creator uniqueness on by default - VERIFIED

**Changes verified:** as in the previous verification. `verify_tables` now takes
`unique_creator` as a keyword only (Iteration 6).

**Tests verified:** all Failure Scenarios covered (mapping table, Phase 2).

**Deviations from plan:** acceptable.
- The refusal tests go through `check_ready()` with the probe patched, not through
  `integrate_*`.
- The no-`DescribeTable` assertion lives in `tests/test_unique_creator_default.py`, not in
  `test_cold_start_budget.py`.
- `POST /` → 403 is covered in `tests/integration/test_unique_creator_http.py`.

### Phase 3: The two consumer primitives - VERIFIED (after Iterations 6, 7, 12, 14)

**Changes verified:**
- `create_attr_if_absent` as planned. The TTL buffer is now stated exactly (Iteration 7).
- The SPA codes as planned:
  - a non-object body, or a wrongly typed string field, gives 400 `invalid_request`
    (Iterations 6, 12 and 14);
  - fault bodies carry `code` (Iteration 6).

**Tests verified:** the missing ones were added.
- `refresh_token_reused` and past-window `invalid_grant`:
  `tests/test_oauth2_spa_refresh_rotation.py`.
- In `tests/test_spa_error_codes.py`:
  - wrong passphrase gives `invalid_grant`;
  - an allowlisted CORS origin reads the code;
  - the non-object and typed-field cases.

**Deviations from plan:** the store-fault 503 is covered in `tests/test_spa_error_codes.py`;
`test_spa_token_retry_after.py` was not extended (acceptable).

### Phase 4: The small minor-only items - VERIFIED (after Iteration 8)

**Changes verified:** as in the previous verification. The dead `_glob_to_regex` wrapper is
gone.

**Tests verified:** the missing ones were added.
- `tests/test_glob_matching.py`: the callbacks revoke path reads brackets literally and runs
  in linear time.
- `tests/test_trust_permissions_unit.py` uses `glob_match`.
- `tests/test_mcp_parse_error.py`:
  - an authenticated non-JSON body gives `-32700`;
  - a form body on a non-MCP route is not a JSON-RPC error;
  - no `WWW-Authenticate` is sent for an unparseable body.

## Success Measures

| Measure | Target | Observable? | Evidence | Status |
| --- | --- | --- | --- | --- |
| Deployments that start with a lookup or `creators` table that is not ready | Zero; `check_ready()` raises | Yes | `tests/test_property_lookup_readiness.py`, `tests/integration/test_property_lookup_readiness.py`, `tests/integration/test_unique_creator_default.py`; the refusal names the command and, for a mixed fleet, the recorded set | Met in tests; **post-ship** for real deployments (baseline: the 3.15 startup only logged) |
| Registry growth the consumer measured | Registrations expire | No | Deferred by the owner (D5) | Not met by design; todo `dcr-registrations-and-client-trust-rows-never-expire.md` |
| The consumer's 401 predicate | A 401 on refresh carries `X-ActingWeb-Error` | Yes | `tests/test_spa_error_codes.py` (Flask and FastAPI, CORS exposed, allowlisted origin), `tests/test_oauth2_spa_refresh_rotation.py` (`refresh_token_reused`) | Met in tests; **post-ship** for the consumer's gateway half |
| An atomic create the consumer can use for its unlock ask | `create_attr_if_absent` with a nonce gives one winner | Yes | `tests/test_create_attr_if_absent.py` on both backends; the 1-hour TTL buffer documented | Met |

**User experience walk-through:**
- **Main path:** an upgraded deployment with data refuses, the operator runs `report` and
  `backfill --apply`, and the next start passes. The integration test walks it.
- **Fresh deployment:** the lookup markers settle themselves. Uniqueness still refuses with
  "no actors yet" and `enable --apply` (owner decision, Phase 2).
- **Adding an indexed name in a rolling deploy:** documented in the configuration guide and
  the migration guide (Iterations 5 and 11). The refusal names the recorded set.
- **SPA client on a refresh 401:** reads `X-ActingWeb-Error` or the body `code`. A gateway
  that strips the header still leaves the body code.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-01-single-mode-and-consumer-primitives.md

That verification listed no Issues Found. Its Remaining Tasks, and this run's review findings
against the same tree:

| Issue then / found now | Status now | Evidence |
| --- | --- | --- |
| Consumer's halves (gateway headers, `isApi401`, unlock ask) follow the pin | Still open (consumer's repo) | — |
| Registration expiry design | Still open (deferred, D5) | `thoughts/todo/dcr-registrations-and-client-trust-rows-never-expire.md` |
| Filed todos: stale lookup owner and races; direct-`Config` creators table | Still open (filed) | `thoughts/todo/property-lookup-stale-owner-and-races.md`, `thoughts/todo/unique-creator-direct-config-auto-create.md` |
| The PR, then the release PR | Still open (not pushed; owner's call) | — |
| Backfill test fixtures assumed existing tables (empty-store failure) | Fixed | Iteration 1 |
| Resumed backfill marked a collided name | Fixed | Iterations 2, 10, 15 |
| Dry run did not predict collisions | Fixed | Iterations 3, 10, 15 |
| Collision loser never re-indexed | Fixed | Iterations 4, 9, 13 |
| D16 last-writer-wins across a mixed fleet | Fixed (docs and message); behaviour kept by design | Iterations 5, 11 |
| SPA non-object body and typed fields gave an uncoded 500 | Fixed | Iterations 6, 12, 14 |
| Fault body lacked `code` | Fixed | Iteration 6 |
| `verify_tables` positional argument reinterpreted | Fixed | Iteration 6 |
| `create_attr_if_absent` TTL buffer undocumented | Fixed (docs) | Iteration 7 |
| Missing type hints, dead glob wrapper | Fixed | Iteration 8 |
| Wrong-prefix pre-warm marks an empty store | Accepted as planned (Phase 1 Failure Scenarios, D4) | plan |
| Empty-store uniqueness refusal | Accepted (owner decision, Phase 2) | plan |
| PostgreSQL `VARCHAR(255)` property name | Accepted: predates the plan | Iterations, "Accepted" |

## Remaining Tasks

- [ ] Commit the iteration fixes on the branch. They are uncommitted: 27+ files, all on top of
  `c3dba9e`.
- [ ] Open the PR (the plan says it opens after Phase 4; CI then runs the real compose
  matrix), then the release PR.
- [ ] Consumer's halves after the pin (the `actingweb_mcp` repo).
- [ ] Registration expiry (deferred todo); the two filed todos.

## Issues Found

None open at High or Medium after the last review round. Two Low notes stay as they are:

### Dry-run double count on an actor read fault
**Severity:** Low
**Description:** when the actor read faults in a dry run, the row counts as a fault and is
also checked as would-write. The exit code is 1 anyway because of the fault.
**Location:** `actingweb/maintenance/property_lookup.py`, `_run_segment` dry-run branch.
**Recommendation:** none needed. The summary line is informational.

### A falsy non-string `prompt` is now rejected
**Severity:** Low
**Description:** `"prompt": false` used to fold to `""`, and it now answers 400
`invalid_request`. A string field holding a bool was never valid input.
**Location:** `actingweb/handlers/oauth2_spa.py`, `_STRING_PARAMS`.
**Recommendation:** none.

## Overall Assessment

The plan is complete and correct on the tree as it stands. All four phases are verified. The
re-verification found real defects that the first verification missed:
- a resumed backfill could certify a name that had collided;
- the dry run hid collisions and read faults;
- a value stored during a collision stayed unfindable for good, and the first fix for that
  had a race that a second fix closed;
- the SPA endpoints still answered uncoded 500s for malformed bodies;
- test fixtures depended on run order.

Each defect has a regression test that fails without its fix. The Full tier is green on both
backends from an empty store. The feature's Desired Outcome is delivered and observable in
tests: one reverse-lookup mechanism, a definite refusal naming the fix, and the two consumer
primitives. Whether real deployments start ready is a post-ship measure.

Before merging, commit the iteration fixes and open the PR, so CI runs the real container
matrix: these runs used scratch DynamoDB Local and PostgreSQL because the OrbStack VM was
asleep.
