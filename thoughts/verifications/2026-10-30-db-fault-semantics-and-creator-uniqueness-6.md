# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4), sixth run

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md,
thoughts/research/2026-10-30-creator-record-invariant-audit.md (both addendum parts)
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (Iterations 71-75)

**Scope:** Phases 3-4 and Iterations 71-75. Every finding of the fifth
run is fixed, and 71-75 introduced no regression. The run finds one Medium
outside 71-75 that this branch makes exploitable (A12) and one Low, so the
plan keeps bare `status: done` with no `verified:` link.

## Automated Check Results

The full tier ran on 2026-10-30 (`scratchpad/full22.sh`) after the last
code change of 71-75; only plan text changed before this review.

- **Browser QA:** not run. `examples/demo/.env` is absent and the demo
  also needs `enable --apply`.
- **Second opinion:** Codex (`codex exec -s read-only`, unsandboxed,
  stdin closed; output kept in the scratchpad, `git status` clean) and a
  fresh-context Claude reviewer, told to report only concrete, reachable
  defects. Codex found no Medium or higher; it cleared `move_stale_record`
  (no duplicate items: `named == kept` returns first), the missing-creator
  condition, `_record_lone_holder`'s races, the trustee success path and
  the random seed. The Claude reviewer found A12 and B12.
- **Built-in code review / security review:** not run separately; the
  attacker brief stands in for both.
- `ruff check`: pass. `ruff format --check`: pass (449 files).
- `pyright`: 0 errors, 0 warnings, 0 informations.
- Fast tier, unit tests: 3269 passed, 23 skipped.
- `verify_groups`: 51 documented.
- `make test-all-parallel`, DynamoDB: exit 0, 4384 passed, 37 skipped.
- `make test-all-parallel`, PostgreSQL: exit 0, 4241 passed, 180 skipped.
- `sphinx-build -W`: succeeded.
- **Regression tests:** every 71-75 test failed with its fix disabled
  (`scratchpad/disable_check3.py`).

## Phase Verification

### Phase 3 - VERIFIED, one Low

- `actingweb/db/dynamodb/actor.py` `move_stale_record` - one transaction,
  record update plus two condition checks (entry 72). Matches.
- `actingweb/maintenance/unique_creators.py` `_settle_record`,
  `_record_lone_holder(config, key, report)` (entries 72-73). Match; B12.
- Tests: `test_c11_*` checks the record at every transaction; `test_d11_*`
  patches the index to lag.

### Phase 4 - ISSUES FOUND

- `actingweb/actor.py` - random bytes in the id seed; the marker removed
  only after `CreatorTaken` (entry 71). Matches; `test_a11_*`, `test_b11_*`.
- `actingweb/oauth2.py` `_winner_is_marked` docstring (entry 74). Matches.
- `actingweb/handlers/trust.py` - own lost answer succeeds, deleted is 404
  (entry 75). Matches; `test_f11_*`.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-5.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A11 colliding generated id | Fixed | entry 71; `test_a11_*` |
| B11 marker dropped after a committed create | Fixed | entry 71; `test_b11_*` |
| C11 outside record moved in two steps | Fixed | entry 72; `test_c11_*` |
| D11 lone holder through the lagging index | Fixed | entry 73; `test_d11_*` |
| E11 stale docstring | Fixed | entry 74 |
| F11 trustee lost answer / deleted actor | Fixed | entry 75; `test_f11_*` |

## Remaining Tasks

- [ ] Fix A12 (Medium) and B12 (Low), with regression tests.
- [ ] Browser QA once a demo `.env` exists.
- [ ] Re-verify, then `/commit` and open PR 2.

## Issues Found

### A12. A concurrent failed creator change can leave the actor vouched under an address nobody proved
**Severity:** Medium
**Description:** `Actor.modify_creator_unvouched` restores the previous
marker after a failed change once a re-read shows the old creator
(`actingweb/actor.py:871` `row = get_actor(self.config).get(actor_id=self.id)`,
then `:883` `elif not store.set_confirmed("auth_method", previous_marker or
None):`). The restore is an unconditional write (`actingweb/attribute.py:83`).
Two `PUT /<id>/trust/trustee` from the actor's own creator: A asks for an
address another actor holds (with the flag, `CreatorTaken` every time, after
A wrote `creator_changed`); B asks for the victim's address. If A re-reads,
then B's rename lands, then A restores, the actor holds the victim's address
with the old vouched marker, and the victim's first sign-in adopts it as is:
the attacker's actor, `trustee_root` and sessions included. Needs
`force_email_prop_as_creator` off or no stored email (the default pin
refuses otherwise). The restore predates this branch; the flag makes A's
failure available on demand.
**Recommendation:** after a change that landed and unvouched, write and
confirm `creator_changed` again, so the last write is always the unvouch.

### B12. A failed holder-record write after an orphan repair is logged as a failed removal
**Severity:** Low
**Description:** `actingweb/maintenance/unique_creators.py:684`
`_record_lone_holder(config, creator, report)` shares the `try` of the
repair, whose handler logs "could not be removed" for a record that was
removed.
**Recommendation:** its own `try` and message.

## Overall Assessment

Iterations 71-75 close A11-F11 without regressions; codex found nothing of
Medium or higher in them. The remaining Medium is in the marker restore of
a failed creator change, older than the branch but made exploitable on
demand by `CreatorTaken`; it is a small fix. The UI was not exercised in a
browser.
