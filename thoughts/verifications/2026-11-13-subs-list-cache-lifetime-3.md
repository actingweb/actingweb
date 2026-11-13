# Verification: per-request actors on the MCP path, and a subscription list that caches empty (third run, 2026-11-13, minimal)

**Date:** 2026-11-13
**Plan:** thoughts/plans/2026-11-06-subs-list-cache-lifetime.md
**Research:** thoughts/research/2026-11-05-subs-list-cache-lifetime.md
**Branch:** release/3.16.0-subs-list-cache-lifetime
**Commit:** 1d761cc plus the working tree (Iterations 8-19), committed with this document

Scope, set by the owner: a minimum run to validate the fixes for Issues
1, 2, 3, 5, 6 and 7 of
`thoughts/verifications/2026-11-13-subs-list-cache-lifetime-2.md`
(Iterations 14-19). Everything else is as the two earlier 2026-11-13 runs
verified it. Together the three cover the plan, so `verified:` moves here.

## Automated Check Results

- **Browser QA:** N/A (no phase touches anything a user sees).
- **Second opinion:** not run (owner: minimum verification; the change is
  messages, one finding swap, one helper and tests).
- `ruff check actingweb tests`: pass
- `ruff format --check actingweb tests`: pass
- `pyright actingweb tests`: 0 errors, 0 warnings
- `tests/integration/verify_groups.py`: pass
- `make test-all-parallel` (DynamoDB): 6,698 passed, 54 skipped, 1 xfailed
- `make test-all-parallel` (PostgreSQL): 6,493 passed, 259 skipped, 1 xfailed
- `sphinx-build -W …`: pass

## Previous Verification

**Previous:** thoughts/verifications/2026-11-13-subs-list-cache-lifetime-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. clean-up uses the stale finding's client ids | Fixed | `actingweb/maintenance/deletions.py` `_finish_one`: `finding = now[0]` after the re-scan; `test_the_clean_up_uses_the_tombstone_read_now` (fails on the previous code) |
| 2. "nothing left to finish" hides leftovers under a re-created id | Fixed (message); the leftovers themselves stay the accepted race, recorded in `thoughts/todo/verify-orphans-subscription-tables.md` | `IN_USE_AGAIN` read from the actor row; `test_an_id_created_again_since_the_scan_is_left_alone` asserts `id in use again`; changelog and maintenance guide |
| 3. "run report again" leads nowhere | Fixed | message names `actingweb-deletions report <id>`; `test_a_deletion_stalled_again_since_the_scan_exits_1` (exit 1) |
| 4. diffs outlive a failed delete or purge | Accepted as-is (owner) | plan, Iterations, "Accepted: Issue 4" |
| 5. two changelog phrases not exact | Fixed | `CHANGELOG.rst`: "a key-only query (paged)", "on DynamoDB when auto-creation is off" |
| 6. test precision | Fixed | split raw-store tests with the cause asserted; order-recording once-per-delete test; missing-table patch raises `QueryError` with `ResourceNotFoundException` (DynamoDB) and `UndefinedTable` from the statement (PostgreSQL); exit-1 resume test |
| 7. text-matching missing-table check | Fixed | `property_lookup.is_table_missing()` (code or type only), used by the diff and suspension clean-ups; `test_a_dynamodb_error_that_only_reads_like_a_missing_table_fails` |

The three resume tests fail on the code before Iterations 14-16 (run in
this session). The Issue 7 test guards against the text-matching version;
on the code before Iteration 10 it passes only because that code had no
missing-table answer at all.

## Remaining Tasks

- [ ] Emm's suite on this branch (the standing rule for a plan that changes
  library code; not run before this PR, see the PR description).
- [ ] The verify-orphans todo (existing; now also names the create-side
  case).

## Issues Found

None in the validated scope.

## Overall Assessment

Issues 1, 2, 3, 5, 6 and 7 of the second 2026-11-13 run are fixed, each
with a test where behaviour changed, and Issue 4 is accepted by the owner.
Both backends pass the full tier. Within this minimal scope the plan is
verified and ready for its PR; Emm's suite is the one gate not yet run.
