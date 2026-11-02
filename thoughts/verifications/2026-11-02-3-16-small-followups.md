# Verification: 3.16 small follow-ups

**Date:** 2026-11-02
**Plan:** thoughts/plans/2026-11-02-3-16-small-followups.md (all four phases, plus Iterations 1-7)
**Research:** none; the plan names the todo files it came from
**Branch:** `release/3.16.0-small-followups`, merged as PR #167 (`4ac934f`, head `953efdf`); the review fixes landed after it on `release/3.16.0-owner-decided-followups` (`15d0320`)
**Commit:** `15d0320`

Written after the merge, from the evidence each phase and the review rounds recorded. It is not a
fresh run of `/verify_implementation`. Every check result below comes from a Full tier that ran
on the commit named.

## Automated Check Results

- **Browser QA:** N/A. No phase touches a page.
- **Second opinion:**
  - Outside voice on the branch diff, codex and a fresh-context Claude. Its seven findings are
    the plan's Iterations 1-7, all fixed in `71eeea6`.
  - The Claude PR review on #167: five non-blocking suggestions, all taken in `c626a13`.
    #167 merged at `953efdf`, before `c626a13` was pushed, so the fixes are not in `4ac934f`.
    They were cherry-picked as `15d0320`, which opens the next PR.
- **Full tier per phase** (ruff check, ruff format --check, pyright, `verify_groups.py`, both
  backends with `make test-all-parallel`, sphinx `-W`). Every run had 0 errors and 0 warnings
  from the linters, the type checker and the docs build.

  | Commit | DynamoDB passed | PostgreSQL passed | Groups |
  | --- | --- | --- | --- |
  | Phase 1 | 5,160 | 4,971 | 51 |
  | Phase 2 | 5,169 | 4,984 | 51 |
  | Phase 3 | 5,186 | 5,001 | 51 |
  | Phase 4 | 5,198 | 5,011 | 52 |
  | `71eeea6` (Iterations 1-7) | 5,200 | 5,016 | 52 |
  | `c626a13` / `15d0320` (PR review) | 5,201 | 5,017 | 52 |

- **CI on #167:** green on both backends, type-check and docs at `953efdf`.

## Phase Verification

### Phase 1: Test infrastructure - VERIFIED

- `tests/_pg_schema.py` and the root fixture `_postgresql_unit_schema` in `tests/conftest.py`:
  an advisory lock, a head check, `PG_DB_PREFIX` removed from the subprocess environment.
- **Regression:** a serial unit run on a fresh PostgreSQL database went from the todo's 44
  failures to 0 (3,862 passed).
- `tests/performance/conftest.py`: with it moved aside, both attribute benchmarks fail with the
  recorded `ResourceNotFoundException`; with it, they pass on a fresh container.
- **Deviation, accepted:** the helper lives in its own module so its test can import it.

### Phase 2: Small correctness fixes - VERIFIED

- PostgreSQL backfill: `ProgramLimitExceeded` falls back to `_pg_insert_rows_one_by_one`. The
  value is counted in `BackfillStats.unindexable`, logged as `UNINDEXABLE` and leaves the name
  unmarked, and the run exits 1 with "shorten or remove".
- `modify_trust_and_notify_async` delegates to the sync method through `asyncio.to_thread`.
- `_restore_marker` re-reads strictly before it logs.
- `clear_pending_email_verification` clears `email_verification_address`.
- **Regressions:** each was checked by stashing the fix. All four backfill tests, the async POST
  test and the address assertion fail without it.

### Phase 3: Hygiene - VERIFIED

- `actingweb/_bounded_cache.py` (`BoundedDict`, `CACHE_MAX_ENTRIES = 4096`, `lookup()`), used by
  the four permission and peer stores.
- `isEnabledFor` guards on the 17 `summarize_payload` sites. **Regression:** with the guards
  stashed, the two guard tests fail.
- `normalise_creator` replaces the inline copies, the type hints are in, and the three adoption
  test files are renamed by behaviour.

### Phase 4: Tests, docs, changelog, todos - VERIFIED

- New tests: the DynamoDB `DbActor.modify` fault test, `tests/test_property_list_fault_reads.py`,
  the interleaved-append test, and `tests/integration/test_list_diff_peer_replica.py` (group
  `list_diff_peer_replica`).
- Docs: the PostgreSQL size limit is stated in the configuration guide and CLAUDE.md, and the
  migration guide has the two DynamoDB notes.
- The CHANGELOG FIXED entries are in, and the todos named by the plan are deleted or trimmed.

## Remaining Tasks

- [ ] The DynamoDB trust, subscription and diff `fetch` return `None` for an empty `actor_id`
  (Phase 3 learning). The owner chose `[]`; it is in
  `thoughts/plans/2026-11-02-3-16-owner-decided-followups.md`.
- [ ] The rows that needed an owner decision are recorded in that plan.

## Issues Found

None open. The outside-voice findings (Iterations 1-7) and the PR review's five suggestions are
all fixed. The only process issue: the review fixes reached `master` one PR late (see above).

## Overall Assessment

The plan landed as written, with the deviations recorded under each phase. Every fixed defect
has a regression test that fails without the fix, and the Full tier ran green on both backends
after every phase and after both review rounds. The PR review's fixes ship with the next PR.
