# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4), fifth run

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md,
thoughts/research/2026-10-30-creator-record-invariant-audit.md (both addendum parts)
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (Iterations 66-70)

**Scope:** Phases 3-4 and Iterations 66-70. Every finding of the fourth
run is fixed (C10 shown unreachable). Entry 66's marker-before-row write
introduced one regression (A11), and two Mediums remain in the marker
cleanup and in `resolve`'s outside-record path. The plan keeps bare
`status: done` with no `verified:` link.

## Automated Check Results

The full tier ran on 2026-10-30 (`scratchpad/full21.sh`), on the code
under review.

- **Browser QA:** not run. `examples/demo/.env` is absent and the demo
  also needs `enable --apply`.
- **Second opinion:** Codex (`codex exec -s read-only`, unsandboxed,
  stdin closed) plus a fresh-context Claude reviewer, briefed on 66-70.
  Ten findings, checked against the code below. On a first launch codex
  wrote a stray file named `$OUT` in the repository root; the reviewer
  deleted it, and `git status` shows nothing else new.
- **Built-in code review / security review:** not run separately; the
  attacker brief stands in for both.
- `ruff check`: pass.
- `ruff format --check`: pass (449 files).
- `pyright`: 0 errors, 0 warnings, 0 informations.
- Fast tier, unit tests: 3267 passed, 23 skipped (56 dependency
  deprecation warnings, unchanged).
- `verify_groups`: 51 documented.
- `make test-all-parallel`, DynamoDB: exit 0, 4378 passed, 37 skipped.
- `make test-all-parallel`, PostgreSQL: exit 0, 4237 passed, 178 skipped.
- `sphinx-build -W`: succeeded.
- **Regression tests:** every 66-70 test failed with its fix disabled and
  passes with it (`scratchpad/disable_check2.py`).

## Phase Verification

### Phase 3 - ISSUES FOUND

**Changes verified:**
- `actingweb/db/dynamodb/actor.py` `creator_is` - used by `modify`,
  `_modify_unique`, `_delete_as_stored` and `actor_as_read` (entry 68).
  Matches.
- `actingweb/maintenance/unique_creators.py` `_settle_record` (three
  outcomes) and `_record_lone_holder` (entry 67). Match the amended rules;
  see C11 and D11.

**Tests verified:** `TestResolveOutsideRecords` (two),
`TestCreatorValues::test_d10_*`. Both assert the record holder after the
run.

**Deviations from plan:** C10 was dropped as unreachable: DynamoDB
rejects an empty creator as the creator index key (the attempted test's
`ValidationException`). Acceptable.

### Phase 4 - ISSUES FOUND

**Changes verified:**
- `actingweb/actor.py:596-640` - the marker before the row for a generated
  id, `_drop_pre_marker` on a failed create (entry 66). Matches the plan
  entry; A11 and B11 are what it costs.
- `actingweb/oauth2.py:1652` - an unloaded store raises `DbError` (entry
  69). Matches.
- `actingweb/handlers/trust.py:306-318` - 409 for a lost race (entry 70).
  Matches; see F11.

**Tests verified:** `TestMarkerBeforeRow` (A10 two, E10),
`TestStaleHandle::test_f10_*`; the B7 test asserts the new outcome.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness-4.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A10 first lookup adopts an unmarked new actor | Fixed, with a regression | entry 66; `test_a10_*`; A11 and B11 |
| B10 `resolve` after an unsettled outside record | Fixed, with a window | entry 67; `TestResolveOutsideRecords`; C11 |
| C10 the empty creator | Unreachable on DynamoDB | entry 68 |
| D10 the missing creator | Fixed | entry 68; `test_d10_*` |
| E10 marker fault read as 409 | Fixed | entry 69; `test_e10_*` |
| F10 trustee lost race as 500 | Fixed | entry 70; `test_f10_*`; F11 is the lost-ack case |

## Remaining Tasks

- [ ] Fix A11, B11 and C11 (Medium), with regression tests; fix or file
  D11-F11.
- [ ] Browser QA once a demo `.env` exists.
- [ ] Re-verify, then `/commit` and open PR 2.

## Issues Found

### A11. A colliding generated id: the pre-marker write overwrites another actor's marker, and the cleanup deletes it
**Severity:** Medium
**Description:** generated ids are deterministic,
`actingweb/config.py:437` `return uuid.uuid5(uuid.NAMESPACE_URL,
str(seed)).hex`, seeded with the URL and a microsecond timestamp
(`actingweb/actor.py:524` `seed += now.strftime("%Y%m%dT%H%M%S%f")`), and
every `ActorInterface.create` passes `config.root` as the URL. Two creates
in the same microsecond in different processes get the same id. Entry 66
then writes the second create's marker into the first actor's bucket
without reading it (`actingweb/actor.py:600` `pre_marked.mark_empty()`),
the backend answers "id taken", and `_drop_pre_marker` deletes the
marker. The first actor is left unmarked and its owner's next sign-in
cleans it in place. Before 66 a collision only made the second create
return False.
**Location:** `actingweb/actor.py:596-660`, `actingweb/config.py:436-437`
**Recommendation:** make generated ids unguessable and collision-free
(random bytes in the seed, or `uuid4`); and in the id-taken branch never
touch the bucket. Alternatively write the pre-marker only if absent.

### B11. A `DbError` from a create that committed drops its marker
**Severity:** Medium
**Description:** `actingweb/actor.py:635-636` `except DbError:` /
`self._drop_pre_marker(pre_marked, self.id)`. A `DbError` can follow a
commit (a lost acknowledgement; the transaction helper's token makes a
retry idempotent, but the final answer can still be a fault). The row and
record then exist without a marker, which is exactly the state invariant M
excludes. Before 66 the outcome was the same (no marker was written), so
this is not a regression, but entry 66 claims M by construction and this
path breaks it.
**Recommendation:** keep the marker on `DbError`: a marker on an unused id
is an orphan bucket (`verify_orphans` lists it), a committed row without it
is wiped at the next sign-in.

### C11. `_settle_record` releases an outside stale record and writes the kept one in two transactions
**Severity:** Medium
**Description:** `actingweb/maintenance/unique_creators.py:551` `if not
release_stale_record(key, named):` and `:559` `if not
record_for_actor_as_read(key, kept_row, moving_from=named):`. Between the
two, no record exists for the key; a sign-in then creates a third actor,
and the second write fails (record present), so the group is counted as a
conflict with one more duplicate than before.
**Recommendation:** one transaction: update the record conditioned on
`actor_id == named`, a `condition_check` that `named` is gone or holds
another creator, and `actor_as_read(kept_row)`.

### D11. `_record_lone_holder` finds the holder through the lagging creator index
**Severity:** Low
**Description:** `actingweb/maintenance/unique_creators.py:699` `listed =
get_actor(config).get_by_creator(creator=key, consistent=True) or []`
re-reads only the rows the index returns. The orphan pass runs right
after the same run's lowercase and `#dup-` renames, so a holder renamed to
the key milliseconds earlier is missing and the record stays absent (the
state before entry 67, not worse). `:705` compares with `key` unnormalised;
no writer leaves such keys today.
**Recommendation:** when the key matches a rename in this run, use that
actor id; normalise `key`; report "record absent, holder not found" rather
than nothing.

### E11. `_winner_is_marked`'s docstring describes the old order
**Severity:** Low
**Description:** `actingweb/oauth2.py:1642` "``Actor.create`` commits the
row and the creator record before it writes the marker". After entry 66 an
unmarked winner is a fixed-id, legacy or old-process actor (or B11), so
"the next attempt finds it marked" no longer holds and the retry keeps
answering 409.
**Recommendation:** rewrite the docstring and log at error level.

### F11. The trustee handler answers 409 when the request's own rename landed
**Severity:** Low
**Description:** `actingweb/handlers/trust.py:312` `if row and
row.get("creator") != original:` also matches a rename of this request
whose acknowledgement was lost, and a concurrently deleted actor (`row`
None) still answers 500.
**Recommendation:** success when the stored creator equals the requested
one; 404 when the row is gone.

**Noted, not findings:** a non-`DbError` exception from `handle.create`
leaves the pre-marker and `self.id` set; both built-in backends wrap every
error in `DbError`, so only a custom backend can reach it. A false
`auth_method` creates an unmarked actor, as before 66; no in-tree caller
passes one.

## Overall Assessment

Iterations 66-70 close A10-F10, both backends are green, and the new tests
fail without their fixes. Entry 66 is the right direction (invariant M by
construction) but writes to a bucket it has not read and deletes from it
after a failure, which is safe only if a generated id cannot collide and a
`DbError` means nothing committed; neither holds (A11, B11). `resolve`'s
outside-record path opens a short window of its own (C11).

Before PR 2: A11 (a regression from 66), B11 and C11, with tests. The Lows
are small. The UI was not exercised in a browser.
