# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4), second run

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (Iterations 45-51)

**Scope:** Phases 3-4 and Iterations 45-51. The run found one High
regression and a High in the command, so the plan keeps bare
`status: done` with no `verified:` link.

## Automated Check Results

The full tier ran on 2026-10-30 (`scratchpad/full15.sh`). It ran on the
code under review: nothing but the plan text changed afterwards.

- **Browser QA:** not run. `examples/demo/.env` is absent, and the demo
  also needs `enable --apply`. The factory form is checked over HTTP only.
- **Second opinion:** Codex (`codex exec -s read-only`, unsandboxed) plus a
  fresh-context Claude reviewer. Ten findings.
- **Built-in code review (high):** ten findings.
- **Security review:** covered by the attacker brief to the second opinion.
  The skill was not run separately.
- `ruff check`: pass.
- `ruff format --check`: pass (448 files).
- `pyright`: 0 errors, 0 warnings, 0 informations.
- Fast tier, unit tests: 3265 passed, 23 skipped. This includes
  `test_db_fault_guard`. That guard failed once, on two unmarked handlers,
  and passes since entry 51's markers.
- `verify_groups`: 51 documented.
- `make test-all-parallel`, DynamoDB: exit 0, 4346 passed, 37 skipped.
- `make test-all-parallel`, PostgreSQL: exit 0, 4225 passed, 158 skipped.
- `sphinx-build -W`: succeeded.
- **Regression tests:** the eight new backend, HTTP and adoption tests
  failed with their fixes disabled and pass with them. The new command
  tests were not run that way.

## Phase Verification

### Phase 3 - ISSUES FOUND

**Changes verified:**
- Iteration 47 is in place:
  - `creator_rules.py` `is_reserved` normalises first;
  - `is_refused_from_callers` covers the system creators;
  - `actor.py:481` refuses reserved values.
- Iteration 49 is in place: `dynamodb/actor.py` `_delete_as_stored` and
  `_release_record` normalise, and PostgreSQL raises the flag `ValueError`.
- Iteration 48 is in place in the command.

**Problems:**
- The normalisation in `_release_record` introduced a regression in
  `_modify_unique` (A8).
- The command's orphan detection and repair misfire against live flag-on
  traffic (B8, C8, D8, E8).

### Phase 4 - ISSUES FOUND

**Changes verified:**
- Iteration 45: `actor.py:371`, the mismatch check.
- Iteration 46: the rollback keeps the row, and `_replace_enforced`'s
  except branch.
- Iteration 50: `lookup_or_create` loads the race winner.
- Every caller of `get_from_creator` lets the mismatch `DbError` through to
  a 503: `oauth2.py:1027` and `:1064`, `actor_interface.py:251`,
  `oauth_email.py:470` and `:515`, `factory.py:270`, `oauth2_spa.py:976`
  and `:1156`.

**Problems:**
- The B7 except branch also runs on a `CreatorTaken` from the swap itself
  (F8).
- The force-email rewrite inside `get()` defeats or misfires the mismatch
  check (G8).

## Previous Verification

**Previous:** thoughts/verifications/2026-10-30-db-fault-semantics-and-creator-uniqueness.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A7 stale record redirects a sign-in | Fixed, with a gap | `actor.py:371`; G8 is the force-email interaction |
| B7 rollback after the swap | Fixed, with a gap | entry 46; F8 (concurrent swap) and H8 (strict=False recovery read) |
| C7 reserved check before lowercasing | Fixed for create, factory and trustee | entry 47; I8 (`ActorInterface.modify_creator`) still open |
| D7 enable from a lagging scan | Partly fixed | the re-read works; B8, C8, D8 |
| E7 disable leaves records | Fixed | entry 48; J8 (running processes, partial failure) |
| F7 release key | Fixed, with a regression | entry 49; A8 |
| G7 capitals | Fixed | entry 48 |
| H7 concurrent first sign-in | Fixed for the no-actor race | entry 50; F8 covers the squatter race |
| I7 system creators | Fixed | entry 47 |
| J7, K7, L7 docs | Fixed | entry 51; K8 revisits L7's decision |
| M7 lost commit answer | Documented | entry 51 |
| N7, O7, P7 | Fixed | entries 49 and 51 |

## Remaining Tasks

- [ ] Fix A8 and B8 (High) and the Medium items C8-K8, with regression tests.
- [ ] The owner decides K8 (fail-open startup probe) and the deletion status
  of the enforced replace branch.
- [ ] Browser QA once a demo `.env` exists.
- [ ] Re-verify, then `/commit` and open PR 2.

## Issues Found

### A8. A case-only rename deletes the record it just claimed (regression from entry 49)
**Severity:** High
**Location:** `actingweb/db/dynamodb/actor.py:248-249`:

```python
if not is_exempt(old_creator):
    self._release_record(old_creator, actor_id)
```

`_release_record` now normalises its key.

**Description:**
1. A legacy actor is stored as `Foo@X.com` and is modified to `foo@x.com`.
   Actor.get's force-email rewrite does this, and so does `resolve`'s
   lowercasing on a flag-on config.
2. The transaction puts the record `foo@x.com → actor`.
3. The release then normalises `Foo@X.com` to `foo@x.com` and deletes that
   same record.
4. The actor now holds its creator with no record, so a second create for
   the address succeeds.

**Recommendation:** skip the release when
`normalise_creator(old_creator) == new_creator`. Add a test.

### B8. `report` lists an actor created during the scan as a "missing" orphan, and `resolve --apply` deletes its live record
**Severity:** High
**Location:**
- `unique_creators.py` `collect`: `held = report.creators.get(actor_id)` /
  `if held is None: report.orphans.append((creator, actor_id, "missing"))`.
- `_repair_record`: `Creator(creator=creator).delete(condition=Creator.actor_id == actor_id)`.

**Description:**
1. The actors are scanned before the records.
2. A sign-up between the two scans has a record but no scanned row, so it
   is listed as a "missing" orphan.
3. `enable` now refuses on orphans (D7's fix), and the guide says to run
   `resolve --apply`.
4. `resolve --apply` deletes the live actor's record. The owner's next
   sign-in finds no holder and creates a second, empty actor.

**Recommendation:**
- Before listing an orphan, re-read the actor consistently. List it only
  if the actor is gone, or its normalised creator differs from the record.
- Do the same check in `_repair_record`.

### C8. A replacement in flight makes `enable` report a false `collision`
**Severity:** Medium
**Location:** `_enable_dynamodb`:
`if holder != actor_id: ... return "collision", written`.

**Description:**
1. After the swap, the squatter's row keeps creator `c` until its removal
   finishes, and stays that way for good if the removal faulted.
2. Step 5's `enable --apply` tries to record the squatter and finds the
   successor's record.
3. `enable` stops with exit 1.

**Recommendation:** when the recorded holder's row has creator `c`, skip
the pending actor as stale instead of reporting a collision.

### D8. `resolve` deletes the renamed actor's record instead of moving it to the kept actor
**Severity:** Medium
**Location:** `_rename`: `_repair_record(normalise_creator(old), actor_id)`.

**Description:**
1. `resolve` renames the actor the record named, and the record is deleted.
2. Until the next `enable`, `get_creator_holder(c)` is None.
3. A flag-on sign-in for `c` in that window creates yet another actor.
4. The next `enable` then collides again, and the loop repeats.

**Recommendation:** when the record names the renamed actor, move it to the
kept actor with a conditional update (`actor_id == renamed`).

### E8. `enable --creator X` refuses only on X, but backfills everything and writes the backfill-complete item
**Severity:** Low
**Location:** `_enable_dynamodb` builds `pending` from the unfiltered
`report.creators`, then runs `Creator(creator=BACKFILL_KEY).save()`.

**Recommendation:** reject `--creator` for `enable` and `disable`.

### F8. A concurrent swap's `CreatorTaken` makes the losing tab remove the squatter too
**Severity:** Medium
**Location:**
- `oauth2.py` `_replace_enforced`: `except Exception:`, then
  `if holder is not None and holder != actor_id:`.
- The comment there: "A CreatorTaken from the swap itself left it the
  holder: untouched".

**Description:**
1. Two tabs replace one squatter. Tab A's swap commits.
2. Tab B's swap raises `CreatorTaken`, and B reads A's successor as the
   holder.
3. B then runs `_remove_for_replacement` on the squatter alongside A, so
   `actor_deleted` fires twice and the two removals can fault each other.
4. B answers the owner with a 409.

**Recommendation:**
- Re-raise `CreatorTaken` before the generic branch.
- Then retry the lookup once and adopt the successor, as entry 50 does.

### G8. The force-email rewrite inside `get()` interferes with the mismatch check
**Severity:** Medium
**Location:** `actor.py:370-371`: `self.get(actor_id=holder)`, then
`if self.id and normalise_creator(self.creator) != lookup_creator:`.
`get()` runs the `force_email_prop_as_creator` rewrite (`actor.py:282-286`)
first.

**Description:** with `force_email_prop_as_creator` on, the rewrite can go
either way.
- **Misfire:** a healthy holder whose stored email differs is renamed to
  the email, and the check then raises 503 with a misleading "run resolve"
  error. The next sign-in creates a duplicate.
- **Defeat:** a mismatched holder whose email equals the lookup value is
  renamed back, so the check passes.

**Recommendation:** compare the creator as stored, before the rewrite (read
the row without the rewrite, or snapshot it). Decide whether the rewrite
should run inside a lookup at all under the flag.

### H8. The B7 recovery reads the holder with `strict=False`
**Severity:** Medium
**Location:** `oauth2.py` `_replace_enforced`:
`holder = get_actor(config).get_creator_holder(creator, strict=False)`.

**Description:** after the swap committed, a fault on this read reads as
"the swap did not happen". The squatter then keeps its tokens. This is
discoverable: an ERROR is logged and `report` lists the pair.

**Recommendation:** use a strict read, and on a fault log that the
squatter is still live.

### I8. `ActorInterface.modify_creator` never checks reserved or system values
**Severity:** Medium
**Location:** `actor_interface.py:428-431`:
`return self._core_actor.modify_creator_unvouched(new_creator)`. The
docstring says this path is for user input. `modify_creator_unvouched` has
no `is_reserved` call.

**Description:** a consumer route built on this API reopens C7 on
PostgreSQL.

**Recommendation:** check `is_refused_from_callers` in
`modify_creator_unvouched` and `is_reserved` in
`ActorInterface.modify_creator`. Leave the command's direct `Actor.modify`
exempt.

### J8. `disable --apply` deletes records while flag-on processes may still serve, and a partial failure leaves a subset
**Severity:** Medium
**Location:** `disable`: `Creator(creator=BACKFILL_KEY).delete()`, then the
`Creator.scan(...)` delete loop. The guide says "Turn the flag off, then
run ...".

**Description:**
- A flag-on process still serving during a rolling deploy finds no holder
  for every user and creates duplicates.
- A throttle partway through the loop leaves records behind, and the next
  `enable` refuses on them as orphans.

**Recommendation:**
- The guide should say "after every flag-on process has stopped".
- Make the loop resumable: re-running `disable --apply` should finish the
  delete even when the backfill-complete item is already gone.
- Confirm the table is empty at the end.

### K8. A startup probe fault fails open, and existing users then get duplicates
**Severity:** Medium (owner decision)
**Location:** `interface/app.py` `_check_unique_creator_ready`:
`except Exception as e:  # folds DbError: startup probe, logged`, then
`self._unique_creator_checked = True`.

**Description:** entry 51 documented L7, but its effect is worse than the
wording says.
1. On DynamoDB, prewarm has already created an empty `creators` table.
2. Under the flag, lookups read only that table.
3. Every existing user's next sign-in therefore creates a second, empty
   actor.

The plan's decision ("a fault in the probe logs a WARNING and continues")
was the owner's, made in evaluation.

**Recommendation:** fail closed on DynamoDB (raise, or leave the check
unset and re-probe), or keep the decision with this consequence spelled
out. This is for the owner to decide.

### L8. Smaller items
**Severity:** Low
- **No `actor_created` for a kept successor.** The successor kept after a
  failed create (entry 46) never fires `actor_created` and is never seeded
  (`created_at`, `email`). The next sign-in fires only `actor_adopted`.
- **A refused force-email rewrite is retried on every load.** Under the
  flag, `Actor.get`'s rewrite for an email held elsewhere runs on every
  load: a cancelled transaction, a read and a WARNING each time
  (`actor.py:282-286`).
- **The default-creator sweep runs on the create path.** It loads every
  `creator` actor on each default-creator create (`actor.py` `elif`
  branch).
- **PostgreSQL `modify` has no creator guard** (`WHERE id = %s`), while
  DynamoDB returns False for a stale handle.
- **Custom backends break even with the flag off.** `get_actor` always
  passes `unique_creator=`, so a custom `DbActor` with a no-argument
  `__init__` fails at construction (`db/__init__.py:138`). The CHANGELOG's
  Breaking entry already names it; passing the argument only when the flag
  is on would narrow it.
- **Inline copies of the normalisation remain:** `actor.py:358`, `:701`,
  `:739`, `:802` and `factory.py:256`.
- **Addresses starting with `#` are refused with the flag off too.**
  `#team@x.com` is a legal address and can no longer sign up, because
  `Actor.create` refuses reserved values either way. The CHANGELOG notes it.
- **A row with no `creator` attribute cannot be deleted under the flag**
  (`_delete_as_stored`). This is unlikely: `creator` is a GSI key.

## Overall Assessment

Iterations 45-51 close the previous run's three Highs at the points where
they were reported. The full tier is green on both backends: DynamoDB 4346
passed, PostgreSQL 4225 passed.

This run found the gaps around those fixes:
- one regression from entry 49, a case-only rename deleting its own new
  record (A8);
- the command treating live flag-on traffic as damage: a sign-up during
  the scan loses its record (B8), and an in-flight replacement reads as a
  collision (C8);
- `resolve` deleting a record instead of moving it to the kept actor (D8);
- a concurrent swap removing the squatter twice (F8);
- the force-email rewrite interfering with the mismatch check (G8).

A8 and B8 should be fixed before PR 2 opens. K8 needs the owner's call on
the startup check. The factory UI was not exercised in a browser.
