# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4), third run

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md,
thoughts/research/2026-10-30-creator-record-invariant-audit.md
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (Iterations 52-58)

**Scope:** Phases 3-4 and Iterations 52-58, the audit's rules 1-7. Every
finding of the second run is fixed or filed. This run finds a High in a
writer the audit did not list (the passphrase-only `modify` on DynamoDB)
and two Mediums, so the plan keeps bare `status: done` with no
`verified:` link.

## Automated Check Results

The full tier ran on 2026-10-30 (`scratchpad/full17.sh`), on the code
under review; only plan text changed afterwards.

- **Browser QA:** not run. `examples/demo/.env` is absent and the demo
  also needs `enable --apply`; the factory form is covered over HTTP only.
- **Second opinion:** Codex (`codex exec -s read-only`, unsandboxed) plus
  a fresh-context Claude reviewer, with an attacker and chaos brief. Eight
  findings, each checked against the code below.
- **Built-in code review / security review:** not run separately this
  time; the attacker brief to the second opinion stands in for both.
- `ruff check`: pass.
- `ruff format --check`: pass (449 files).
- `pyright`: 0 errors, 0 warnings, 0 informations.
- Fast tier, unit tests: 3265 passed, 23 skipped (56 pytest warnings, the
  same count as earlier runs on this branch).
- `verify_groups`: 51 documented.
- `make test-all-parallel`, DynamoDB: exit 0, 4363 passed, 37 skipped.
- `make test-all-parallel`, PostgreSQL: exit 0, 4231 passed, 169 skipped.
- `sphinx-build -W`: succeeded.
- **Regression tests:** Iterations 52-58's tests failed with their fixes
  disabled and pass with them, except the H8 test, which checks a log
  line only (recorded in the plan).

## Phase Verification

### Phase 3 - ISSUES FOUND

**Changes verified:**
- `actingweb/actor.py:375-403` - the enforced lookup reads the holder, then
  the row as stored, and repairs a stale record through
  `release_stale_creator` before the create (entry 52). Matches.
- `actingweb/db/dynamodb/actor.py:585-608` `release_stale_record` - a
  consistent actor read, then a delete conditioned on `actor_id`. Matches;
  see Issue E9 for the window between the two.
- `actingweb/db/dynamodb/actor.py:250` - `if not is_exempt(old_creator) and
  normalise_creator(old_creator) != new_creator:` keeps a case-only
  rename's record (entry 53, A8). Matches.
- `actingweb/maintenance/unique_creators.py` - consistent confirmation
  before listing, `_settle_record` (`:520-545`), `enable` collisions,
  `--creator` refused (entry 54); `disable` resumable (entry 55). Matches;
  Issues B9, F9, G9.
- `actingweb/interface/app.py:1540-1552` - a probe fault raises
  `UniqueCreatorNotReady` (entry 56, K8, owner decision). Matches.
- PostgreSQL `modify` guard `AND creator IS NOT DISTINCT FROM %s`
  (entry 58), with the CHANGELOG and migration-guide notes. Matches.

**Tests verified:** `tests/integration/test_unique_creator_states.py`
(`TestLookup`, `TestReportAndResolveUnderLiveTraffic`, `TestEnable`,
`TestWriters`, `TestSwapRaces`, `TestReservedThroughTheSdk`,
`TestStaleHandleRename`) pins each state the audit names. No test covers
a passphrase-only modify under the flag (A9) or the retry meeting an
unmarked winner (C9).

**Deviations from plan:** entry 52 replaces entry 45's fail-closed with a
repair (Decisions Made, deduced). Acceptable, and it closes the lock-out.

### Phase 4 - ISSUES FOUND

**Changes verified:**
- `actingweb/oauth2.py:1045-1063` - a `CreatorTaken` from `adopt_actor`
  looks up once more and adopts a different winner (entry 57, F8).
- `actingweb/oauth2.py:1077-1096` - the create race loads the winner
  (H7). See Issue C9: the winner can be read before its marker exists.
- `_replace_enforced`: `CreatorTaken` re-raised ahead of the generic
  branch; the recovery read is strict (H8). Matches.
- `ActorInterface.modify_creator` refuses reserved values;
  `modify_creator_unvouched` refuses system values (I8). Matches.

**Deviations from plan:** the deletion status on the replace branch
(UNKNOWN 503, DELETED finished by the swap) was confirmed by the owner on
2026-10-30, "keep the squatter mid-deletion fix as now"; the plan's
Decisions Made and Phase 4 Deviations now say so.

**Consumer instructions (Step 0)** in `docs/migration/v3.16.rst:478` still
match the plan (`report`, `resolve`/`resolve --apply`, `enable --apply`,
deploy, `enable --apply`, `report`), but the claim at `:517` that
`resolve --apply` is safe against live traffic is not true yet (B9).

## Previous Verification

**Previous:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A8 case-only rename deletes its record | Fixed | entry 53; `dynamodb/actor.py:250`; `TestWriters::test_a8_…` |
| B8 report lists a live actor as orphan | Fixed | entry 54; `TestReportAndResolveUnderLiveTraffic::test_an_actor_created_between_the_two_scans_is_not_an_orphan` |
| C8 false collision during a swap | Fixed | entry 54; `TestEnable::test_g2_is_listed_and_the_run_goes_on_without_the_marker` |
| D8 resolve deletes the renamed actor's record | Fixed, with a gap | entry 54, `_settle_record`; B9 (ordering against live sign-ins) |
| E8 `enable --creator` | Fixed | entry 54; `test_creator_is_refused_for_enable_and_disable` |
| F8 concurrent swap removes twice | Fixed | entry 57; `TestSwapRaces::test_f8_…` |
| G8 force-email rewrite in the lookup | Fixed | entry 52 (`rewrite_email=False`); `test_the_force_email_rewrite_does_not_run_inside_the_lookup` |
| H8 non-strict recovery read | Fixed | entry 57; `test_h8_…` (log only) |
| I8 `modify_creator` reserved values | Fixed | entry 57; `TestReservedThroughTheSdk` |
| J8 `disable` against live processes | Documented and resumable | entry 55; `test_disable_finishes_a_partial_run` |
| K8 startup probe fails open | Fixed (owner: fail closed) | entry 56 |
| L8 lows | Deferred | `thoughts/todo/unique-creator-small-followups.md`, INDEX row present |

## Remaining Tasks

- [ ] Fix A9 (High), B9 and C9 (Medium), with regression tests; decide
  D9-J9.
- [ ] Owner decisions still marked deduced: PostgreSQL fail-closed at
  startup, the one-retry relaxation, repair at sign-in.
- [ ] Browser QA once a demo `.env` exists.
- [ ] Re-verify, then `/commit` and open PR 2.

## Issues Found

### A9. A passphrase-only `modify` on DynamoDB rewrites the whole row and can undo a concurrent rename
**Severity:** High
**Description:** under the flag only a creator change takes the
transactional path; `actingweb/db/dynamodb/actor.py:174` `if
self.unique_creator and new_creator != old_creator:`. A passphrase-only
call falls to `:182` `self.handle.save()`, a full PutItem that writes the
handle's (possibly stale) `creator` back. The clean-in-place adoption
calls it: `actingweb/oauth2.py:2413` `if not
existing.modify(passphrase=new_passphrase):`. If a rename (X→Y, record
Y→A, X released) commits between the load and the save, the row returns
to X with no record and a dangling Y record. The next sign-in for X finds
no holder and creates a second actor; nothing logs it. An attacker who
still holds the squatter's passphrase controls the timing. PostgreSQL is
unaffected (its UPDATE sets only the passphrase). The audit's writer list
(W1-W11) does not include this path.
**Location:** `actingweb/db/dynamodb/actor.py:174-182`
**Recommendation:** under the flag (or always), rotate with
`update(actions=[Actor.passphrase.set(...)], condition=Actor.creator ==
old_creator)` and answer False on a failed condition; add the writer to
the audit's list and a test that renames between load and rotate.

### B9. `resolve --apply` renames the losers before it settles the record
**Severity:** Medium
**Description:** `actingweb/maintenance/unique_creators.py:588` `if
_rename(config, actor_id, target):` runs for every loser before `:607`
`_settle_record(key, kept, ids)`. In between, the record still names the
renamed loser; a live sign-in sees the mismatch (`actor.py:394`
`repaired = db.release_stale_creator(...)`), removes it and creates a new
actor N. `_settle_record` then returns at `:529` `if named == kept or
named not in ids: return`, and the kept actor and N both hold the
address. This contradicts `docs/migration/v3.16.rst:517` ("safe to run
against live traffic").
**Location:** `actingweb/maintenance/unique_creators.py:577-610`
**Recommendation:** move the record to the kept actor first (conditioned
on the loser), then rename; or narrow the doc's claim.

### C9. The create-race retry can adopt the winner before its `auth_method` marker exists
**Severity:** Medium
**Description:** `Actor.create` commits the row and record, then writes
the marker (`actingweb/actor.py:606-609` `self.store.set_confirmed(
"auth_method", ...)`). The retry at `actingweb/oauth2.py:1084` `if not
winner.get_from_creator(identifier):` reads the winner consistently and
`adopt_actor` treats a missing marker as unvouched, so the losing tab
cleans the brand-new actor in place (rotate, revoke, purge). If its own
marker write lands first, the winning tab's `set_confirmed` fails and it
rolls the row back, leaving the losing tab on a deleted actor.
**Location:** `actingweb/oauth2.py:1077-1096`
**Recommendation:** treat an unmarked winner in the retry as in flight:
re-read the marker after a short backoff, or answer 409/503 rather than
adopt.

### D9. The lookup's second read is not checked against the creator
**Severity:** Low
**Description:** `actingweb/actor.py:402` `self.get(actor_id=holder,
rewrite_email=False)` follows the check on the first read. A rename that
commits in between hands the sign-in an actor that now belongs to another
creator. Only the previous owner of that actor can be hit, which keeps the
impact low.
**Location:** `actingweb/actor.py:402-403`
**Recommendation:** compare `normalise_creator(self.creator)` with
`lookup_creator` after the load and answer False on a mismatch.

### E9. `release_stale_record` reads and deletes in two steps
**Severity:** Low
**Description:** after the consistent read, `actingweb/db/dynamodb/actor.py:601`
`Creator(creator=creator).delete(condition=Creator.actor_id == actor_id)`
also deletes a record that the actor reclaimed by renaming back in
between. That leaves the actor holding the creator with no record.
**Recommendation:** delete in a `TransactWrite` with a `condition_check`
on the actor row (`creator <> X` or the row absent).

### F9. `_settle_record` moves the record without conditioning on the kept row
**Severity:** Low
**Description:** `actingweb/maintenance/unique_creators.py:537`
`record.update(actions=[Creator.actor_id.set(kept)], condition=Creator.actor_id
== named)`. A rename of the kept actor after the check leaves a stale
record. The sign-in repair contains it.
**Recommendation:** a transaction with a `condition_check` on the kept row.

### G9. `enable` saves records without a transaction against the actor row
**Severity:** Low
**Description:** `actingweb/maintenance/unique_creators.py:741`
`Creator(creator=creator, actor_id=actor_id).save(` follows the re-read.
The backfill-complete item is written even if a rename or delete in
between left a stale record. The sign-in repair contains it.
**Recommendation:** as F9.

### H9. A transaction cancelled for both a conflict and a failed condition ends as a 503
**Severity:** Low
**Description:** `actingweb/db/dynamodb/actor.py:537` `if not conflict and
"ConditionalCheckFailed" in codes:`. On the last attempt a real
`CreatorTaken` is reported as `DbError`. It fails closed.
**Recommendation:** classify by `ConditionalCheckFailed` whenever present
on the final attempt.

### I9. The custom-backend checklist omits `release_stale_creator`
**Severity:** Medium
**Description:** entry 52 added `release_stale_creator` to the protocol
(`actingweb/db/protocols.py:180` `def release_stale_creator(self,
creator: str, actor_id: str) -> bool:`). The flag-on lookup calls it on
every backend (`actor.py:394`). The checklists name only
`replace_creator_holder` and `get_creator_holder`:
`docs/migration/v3.16.rst:444-447`, `CHANGELOG.rst:236`,
`docs/reference/database-backends.rst:579`. A custom backend without it
raises `AttributeError` at sign-in on a stale record.
**Recommendation:** add it to the three lists (PostgreSQL's answer,
`False`, is a valid implementation for a backend whose constraint lives
on the row).

### J9. A stale comment in the lookup
**Severity:** Low
**Description:** `actingweb/actor.py:379-380` "A record whose actor is
gone answers False, and a create for the address then raises
CreatorTaken (report lists the record)." Since entry 52 the record is
repaired and the create succeeds.
**Recommendation:** reword to the repair.

**Noted, not findings:** the DynamoDB swap's docstring says the squatter
"stays without the creator" while its row keeps the value (only the
record moves); `report` lists the pair if the removal faults. The
readiness check is cached per process and `disable` cannot exclude
flag-on processes (J8, documented). `#DUP-` in a provider id is accepted;
nothing treats it as bookkeeping.

## Overall Assessment

Iterations 52-58 implement the audit's rules and close every finding of
the second run; both backends are green, the docs build, and the new
state tests pin the audit's gaps. Owner decisions K8 (fail closed) and the
deletion status on the replace branch are now in the plan.

The audit's writer list was not complete. On DynamoDB the passphrase-only
`modify` still writes the whole row, and under a concurrent rename it can
break invariant I with no error (A9, High). `resolve --apply` is not yet
safe against live traffic as the migration guide says (B9), and the
create-race retry can adopt a winner before its marker exists (C9). I9 is a
documentation gap for custom backends. A9, B9 and C9 need fixes and
regression tests before PR 2; the Lows can be fixed or filed. The UI was
not exercised in a browser.
