# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4), ninth run

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md,
thoughts/research/2026-10-30-creator-record-invariant-audit.md (all three addendum parts)
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (Iterations 44-82)

**Scope:** Phases 3-4 of the plan (PR 2) with all their iterations; Phases
1-2 (PR 1) were verified and merged earlier (#160). Every finding of the
eighth run is fixed; this run finds nothing of Medium or higher, and the
three Lows it found are filed. The plan gets `verified:` pointing here.

## Automated Check Results

- **Full tier** (`scratchpad/full25.sh`, after the last code change of
  80-82): ruff pass; ruff format pass (449 files); pyright 0 errors, 0
  warnings, 0 informations; fast tier 3275 passed, 23 skipped (56
  dependency deprecation warnings, unchanged across the branch);
  `verify_groups` 51 documented; `make test-all-parallel` DynamoDB exit 0,
  4393 passed, 37 skipped; PostgreSQL exit 0, 4248 passed, 182 skipped;
  `sphinx-build -W` succeeded.
- **Second opinion:** Codex (`codex exec -s read-only`, unsandboxed, stdin
  closed): "No concrete reachable defects found in iterations 80-82".
  Fresh-context Claude reviewer: one Low (the SDK rename's binding
  window), two notes; it checked and cleared the email link's single issue
  site and the pre-upgrade fallback, the compare-and-set on both backends
  (PostgreSQL `data = %s::jsonb`, DynamoDB `Attribute.data == item.data`),
  that no handler, integration or consumer passes user input to
  `ActorInterface.modify_creator`, and that every vouched-marker write
  records its address.
- **Built-in security review** (run in round 8 on the whole branch):
  nothing above its 0.8 confidence bar.
- **Regression tests:** every fix of Iterations 44-82 has a test that
  failed with the fix disabled (`scratchpad/disable_check*.py`; the H8 test
  checks a log line only).
- **Browser QA:** not run. `examples/demo/.env` (a real OAuth2 client) is
  absent, and the demo also needs `enable --apply`. The one page the
  phases touch, the factory form, is covered over HTTP
  (`tests/integration/test_unique_creator_http.py`).

## Phase Verification

### Phase 3: opt-in creator uniqueness, backends and command - VERIFIED
- The DynamoDB `creators` record is written in the actor's transaction
  (create, rename, swap), released after a delete, and every record write
  that depends on the actor row carries a `condition_check`
  (`actingweb/db/dynamodb/actor.py` `record_for_actor_as_read`,
  `move_stale_record`, `release_stale_record`). PostgreSQL uses the
  `ux_actors_creator` index and a stale-handle guard.
- The command (`actingweb/maintenance/unique_creators.py`): `report`
  confirms damage on the row, `resolve` settles the record before renaming,
  `enable` backfills with row checks and writes the backfill item only with
  no collisions, `disable` is resumable.
- Tests: `tests/integration/test_unique_creator_states.py` by state, plus
  the backend, command, HTTP and transaction suites.

### Phase 4: the sign-in path - VERIFIED
- The enforced lookup repairs a stale record and re-checks the creator
  after its load; the marker is written before the row for a generated id;
  race retries adopt only a marked winner; the startup check fails closed.
- Vouching: a vouch is bound to the address it proved (`vouched_creator`;
  `actingweb/oauth2.py` `is_vouched_store`), the restore after a failed
  creator change is a compare-and-set, and the emailed link proves only the
  address it was sent to.
- Tests: `tests/integration/test_unique_creator_adoption.py`,
  `TestVouchBoundToItsAddress`, `tests/test_trust_creator_rename.py`
  (`TestConcurrentRestore` in both orders and for a pre-3.16 actor,
  `TestApplicationRename`, `TestStaleHandle`),
  `tests/test_oauth_email_verify_link.py::TestLinkProvesOnlyItsAddress`.

**Security properties claimed in the CHANGELOG, and the test that pins
each:**
- a rename by the creator unvouches, whatever order concurrent writes land
  in: `TestConcurrentRestore::test_a12_a_restore_landing_after_the_rename`
  asserts `not is_vouched_actor(renamed)` with the old vouched marker
  stored;
- a rename during the first sign-in's clean does not vouch the new
  address: `TestVouchBoundToItsAddress` asserts `classify_marker(...,
  other) != "vouched"`;
- the emailed link proves only its address:
  `TestLinkProvesOnlyItsAddress` asserts 409 and `email_verified ==
  "false"` after a rename.

**Consumer instructions (Step 0)** in `docs/migration/v3.16.rst` are as
the plan states (report; resolve, `resolve --apply`; `enable --apply`;
deploy; `enable --apply`; report), with the IAM paragraph now naming
`ConditionCheckItem` on the actor table. actingweb_mcp and the demo must
run Step 0 and grant it before deploying with the flag on.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-8.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A14 emailed link vouches another address | Fixed | entry 80; `TestLinkProvesOnlyItsAddress` |
| B14 SDK rename reads unvouched | Fixed | entry 81; `TestApplicationRename` (a millisecond window filed) |
| C14 restore over a clean | Fixed | entry 82; `test_r8_*` |

## Remaining Tasks

- [ ] Browser QA once a demo `.env` exists (not blocking: the factory form
  is covered over HTTP).
- [ ] `/commit` and open PR 2.
- [x] The Lows of this run are filed in
  `thoughts/todo/unique-creator-small-followups.md` (INDEX row updated).

## Issues Found

### A15. The SDK rename's binding window
**Severity:** Low
**Description:** `actingweb/interface/actor_interface.py:439` `if not
self._core_actor.modify(creator=new_creator):` then `:441` `return
self._rebind_vouch(new_creator)`: between them a sign-in for the new
address reads the actor as unvouched and cleans it. Filed.

### Notes (filed)
- `clear_pending_email_verification` leaves `email_verification_address`.
- `_restore_marker` logs a fault as "changed since".

## Overall Assessment

Phases 3-4 are complete against the plan and its iterations. Both backends
are green, the docs build, each fix has a test that fails without it, the
security review found nothing above its bar, and two independent
reviewers found nothing of Medium or higher in the last batch. The design
changed substantially during iteration (the invariant audit and its three
addendum parts: a record write checks the actor row, the marker precedes
the row, a vouch is bound to its address), and those decisions are in the
plan, one of them deduced. The UI was not exercised in a browser. Ready
for `/commit` and PR 2.
