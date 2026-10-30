# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4), fourth run

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md,
thoughts/research/2026-10-30-creator-record-invariant-audit.md (with its addendum)
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (Iterations 59-65)

**Scope:** Phases 3-4 and Iterations 59-65: the addendum's rules 8-10 and
the amended rule 2. Every finding of the third run is fixed. This run
finds two Mediums where those rules were applied to fewer sites than they
cover (A10, B10), and four Lows, so the plan keeps bare `status: done`
with no `verified:` link.

## Automated Check Results

The full tier ran on 2026-10-30 (`scratchpad/full19.sh`), on the code
under review.

- **Browser QA:** not run. `examples/demo/.env` is absent and the demo
  also needs `enable --apply`.
- **Second opinion:** Codex (`codex exec -s read-only`, unsandboxed,
  stdin closed) plus a fresh-context Claude reviewer, briefed on 59-65 and
  on regressions to flag-off callers of `modify`. Eight findings; each
  checked against the code below. Two are already documented (codex's
  backfill-marker window, rollout steps 5-6) or out of 59-65's scope.
- **Built-in code review / security review:** not run separately; the
  attacker brief to the second opinion stands in for both.
- `ruff check`: pass.
- `ruff format --check`: pass (449 files).
- `pyright`: 0 errors, 0 warnings, 0 informations.
- Fast tier, unit tests: 3266 passed, 23 skipped (56 pytest warnings,
  deprecations from dependencies, the same count as earlier runs).
- `verify_groups`: 51 documented.
- `make test-all-parallel`, DynamoDB: exit 0, 4371 passed, 37 skipped.
- `make test-all-parallel`, PostgreSQL: exit 0, 4233 passed, 175 skipped.
- `sphinx-build -W`: succeeded.
- **Regression tests:** every 59-65 test failed with its fix disabled and
  passes with it (`scratchpad/disable_check.py`, which restores each file
  and checks its hash).

## Phase Verification

### Phase 3 - ISSUES FOUND

**Changes verified:**
- `actingweb/db/dynamodb/actor.py:174-200` - `modify` outside the
  transactional rename saves with `condition=Actor.creator == old_creator`
  (entry 59). Matches; see C10 for the empty creator.
- `actingweb/db/dynamodb/actor.py` `release_stale_record`,
  `record_for_actor_as_read`, `actor_as_read` - one transaction with a
  `condition_check` on the actor row (entry 60). Matches; see C10.
- `_run_transaction` - a classmethod; a failed condition on the last
  attempt returns the codes (entries 60, 64). Matches.
- `actingweb/actor.py` `get_from_creator` - compares again after the load
  (entry 61). Matches.
- `actingweb/maintenance/unique_creators.py` - `_settle_record` before the
  renames, `_release_losers_record` after an unsettled group, the backfill
  through `record_for_actor_as_read` (entries 60, 62). Matches the
  amended rule 2 for a record naming the group or no record; see B10 for a
  record naming an actor outside it.

**Tests verified:** `TestWriters::test_a9_*` (two),
`TestWritesCheckTheActorRow` (E9, F9/G9, D9), `TestResolveUnderSignIn`
(B9), `test_a_condition_failure_on_the_last_attempt_wins_over_a_conflict`
(H9). Each asserts the state after the race (row creator, record holder),
not only a return value.

**Deviations from plan:** entry 59 uses a conditional `PutItem` rather
than the addendum's `UpdateItem`, so flag-off deployments need no new
permission. Acceptable; rule 8's intent (no write through a stale handle)
holds.

### Phase 4 - ISSUES FOUND

**Changes verified:**
- `actingweb/oauth2.py:1639` `_winner_is_marked`, used by both retries
  (entry 63). Matches rule 10 as written; A10 is the same hazard on the
  first lookup.
- Docs (entry 65 and the IAM notes): `release_stale_creator` in the three
  custom-backend lists; `ConditionCheckItem` in `docs/migration/v3.16.rst`,
  `docs/quickstart/configuration.rst` and `CHANGELOG.rst`. Matches.

**Consumer instructions:** Step 0 (`docs/migration/v3.16.rst`) is
unchanged in order. The IAM paragraph now adds `ConditionCheckItem` on the
actor table; actingweb_mcp and the demo need it before they deploy with
the flag on.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A9 full-row save through a stale handle | Fixed | entry 59; `TestWriters::test_a9_*` |
| B9 `resolve` renames before settling | Fixed for records naming the group or none | entry 62; `TestResolveUnderSignIn`; B10 is the remaining case |
| C9 retry adopts an unmarked winner | Fixed in both retries | entry 63; `TestRetryAdoptsOnlyAMarkedWinner`; A10 is the first lookup |
| D9 the lookup's second read | Fixed | entry 61; `test_d9_*` |
| E9 stale-record delete in two steps | Fixed | entry 60; `test_e9_*` |
| F9 settle without a check on the kept row | Fixed | entry 60; `test_f9_g9_*` |
| G9 backfill without a check | Fixed | entry 60; `test_f9_g9_*` |
| H9 conflict and condition on the last attempt | Fixed | entry 64 |
| I9 custom-backend lists | Fixed | entry 65 |
| J9 stale comment | Fixed | entry 61 |

## Remaining Tasks

- [ ] Fix A10 and B10 (Medium), with regression tests; fix or file
  C10-F10.
- [ ] Owner decisions still marked deduced: PostgreSQL fail-closed at
  startup, the one-retry relaxation, repair at sign-in, the 409 for an
  unmarked winner, the `ConditionCheckItem` requirement.
- [ ] Browser QA once a demo `.env` exists.
- [ ] Re-verify, then `/commit` and open PR 2.

## Issues Found

### A10. The first sign-in lookup can adopt an actor whose marker is not written yet
**Severity:** Medium
**Description:** rule 10 was applied to the two retries only. The first
lookup has the same window: `actingweb/oauth2.py:1027` `if
existing_actor.get_from_creator(identifier):` reads through the record
consistently, and `Actor.create` writes the marker after the row and
record (`actingweb/actor.py:623` `if self.store and auth_method:`). A
second tab arriving in that window adopts tab one's brand-new actor as
legacy and cleans it in place: passphrase rotated, tokens revoked,
`trustee_root` and provider tokens cleared, with no error. With the
lagging index (flag off) the new actor was rarely visible this early;
the consistent read makes it reachable. Invariant M as stated ("an actor
a retry adopts") is narrower than it should be: any adoption under the
flag.
**Location:** `actingweb/oauth2.py:1025-1045`
**Recommendation:** under `unique_creator`, apply `_winner_is_marked` (or
the same check) to the first lookup's actor before `adopt_actor`, and
widen M in the audit addendum. A pre-3.16 actor with no marker must still
be adoptable: distinguish "no marker" from "created seconds ago" (for
example by the row's `created_at`, or a marker written in the create
transaction).

### B10. `resolve` renames the losers even when the record could not be settled, and does not count it
**Severity:** Medium
**Description:** `actingweb/maintenance/unique_creators.py:538`
`logger.error(f"the record of {key!r} names {named}, outside the group;
left")` returns False, and the caller (`:599` `settled =
_settle_record(key, kept, ids)`) goes on to rename without counting an
error. If that outside record is stale, the orphan loop (`:651`) then
removes it, leaving the kept actor holding the key with no record; the run
can exit 0 and the next sign-in creates a second actor. The migration
guide says `resolve` "points the record at the actor it keeps before it
renames the others".
**Location:** `actingweb/maintenance/unique_creators.py:530-545`, `:596-606`
**Recommendation:** when the outside record is stale, release it (rule 1's
helper) and write the record for the kept actor; when it names a live
holder of the key, count an error and skip the group. After the orphan
loop, write records for holders left unrecorded, or count them.

### C10. The empty creator in the new conditions
**Severity:** Low
**Description:** `actingweb/db/dynamodb/actor.py:186` `condition =
Actor.creator == old_creator if old_creator else Actor.id.exists()` treats
`""` like a missing creator, so a stale handle of an actor whose creator
is `""` still overwrites a rename (A9's case). `actor_as_read`
(`:664` `return Actor.id.exists() & Actor.creator.does_not_exist()`)
never matches a stored `""` (PynamoDB 6.1 stores it as `{"S": ""}`), so a
record naming such an actor is never released. `""` is exempt, so this
needs an actor renamed away from the empty creator.
**Recommendation:** branch on `is None` versus `== ""` in both.

### D10. A creator stored as missing blocks rename and delete under the flag
**Severity:** Low
**Description:** `actingweb/db/dynamodb/actor.py:224` `condition =
Actor.creator == old_creator` and `:447` `handle.delete(condition=
Actor.creator == creator)` render `None` as `{NULL: true}`, which never
matches an absent attribute: such an actor cannot be renamed (False) or
deleted (`DbError`) with the flag on. Predates 59-65 (entries 44-49).
**Recommendation:** `Actor.creator.does_not_exist()` when the value is
`None`, in all three conditions.

### E10. A store fault in `_winner_is_marked` answers 409, not 503
**Severity:** Low
**Description:** `actingweb/oauth2.py:1648` `method = winner.store.auth_method
if winner.store else None`. The store's lazy load folds a fault into an
empty bucket (`actingweb/attribute.py:38` "``actor.store.x`` never raises
on a fault"), so a throttle reads as "no marker" and the sign-in answers
"creator taken".
**Recommendation:** check `winner.store.loaded` and raise `DbError` when
it is False.

### F10. A concurrent rename now reaches `PUT /<id>/trust/trustee` as a 500
**Severity:** Low
**Description:** entry 59 makes a flag-off `modify` through a stale handle
return False (it used to overwrite). `actingweb/actor.py:796` `if
self.modify(creator=creator):` then falls through, and the handler answers
`actingweb/handlers/trust.py:317` `self.response.set_status(500,
"Internal error")`.
**Recommendation:** answer 409 when `modify` returned False and a re-read
shows another creator.

**Noted, not findings:** the backfill-complete item written while old
flag-off processes may still create duplicates (codex) is the documented
window of rollout steps 5-6. `_run_transaction` reuses one client request
token across conflict retries; this predates 59-65 and was reviewed in
entry 44.

## Overall Assessment

Iterations 59-65 fix A9-J9 as the addendum's rules describe, with tests
that fail without each fix, and both backends are green. The remaining
Mediums are the same rules applied to too few sites: the marker check
(rule 10) covers the retries but not the first lookup, which the flag's
consistent read makes reachable (A10); and the amended rule 2 settles the
record for the group's own records but lets `resolve` rename after an
unsettled outside record (B10). The Lows are value edge cases (`""`,
`None`) in the new conditions, a fault read as a conflict, and a 500 where
a 409 fits.

Before PR 2: A10 and B10 with regression tests, and the audit's M widened
to every adoption under the flag. The Lows are each a few lines and can go
in the same batch. The UI was not exercised in a browser.
