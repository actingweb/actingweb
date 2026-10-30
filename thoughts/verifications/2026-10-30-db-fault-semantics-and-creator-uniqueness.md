# Verification: Opt-in creator uniqueness (PR 2, Phases 3-4)

**Date:** 2026-10-30
**Plan:** thoughts/plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Research:** thoughts/research/2026-10-28-db-fault-semantics-and-creator-uniqueness.md
**Branch:** release/3.16.0-creator-uniqueness
**Commit:** c7cef70 plus uncommitted work (PR 2 is not yet committed)

**Scope:** this verification covers Phases 3 and 4 only. Phases 1-2 (PR 1,
#160, merged as `c7cef70`) were verified six times on 2026-10-29. Because
this run found High issues, the plan keeps bare `status: done` with no
`verified:` link.

## Automated Check Results

The full tier was run on 2026-10-30 (`scratchpad/full13.sh`), on the tree
under review.

- **Browser QA:** Not run.
  - `examples/demo/.env` does not exist, and the contract needs a real
    OAuth2 client before the demo can start.
  - The demo also runs the flag on, so it now refuses to start until
    `actingweb-unique-creators enable --apply` has run against its store.
  - The one UI change, the factory form redirecting an existing creator to
    `/login`, was checked over HTTP only
    (`test_unique_creator_http.py::TestFactory::test_the_form_redirects_an_existing_creator_to_login`).
  - The 400 "Creator is reserved" page was never loaded in a browser.
- **Second opinion:** provider Codex (`codex exec -s read-only`, run
  unsandboxed), plus a fresh-context Claude reviewer. Seven findings, folded
  in below.
- **Built-in code review (high, no `--fix`):** ten findings, folded in below.
- **Security review:** the second opinion was briefed as an attacker and
  covered it; A7 and C7 come from that pass. The built-in security-review
  skill was not run separately.
- `ruff check actingweb tests`: pass.
- `ruff format --check`: pass (448 files).
- `pyright actingweb tests`: 0 errors, 0 warnings, 0 informations.
- Fast tier, unit tests: 3265 passed, 23 skipped.
- `verify_groups.py`: all 51 groups documented.
- `make test-all-parallel`, DynamoDB: exit 0, 4324 passed, 37 skipped.
- `make test-all-parallel`, PostgreSQL: exit 0, 4210 passed, 151 skipped.
- `sphinx-build -W`: build succeeded.
- Benchmarks: not re-run. The plan records the 2026-10-29 numbers (Phase 4
  Verification). No list storage was touched.

## Phase Verification

### Phase 3: Opt-in uniqueness, the command and the startup check - ISSUES FOUND

**Changes verified:**
- `actingweb/db/creator_rules.py`: the exempt, reserved and `#dup-` rules
  live in one module and both backends import it. The reserved check is
  case-sensitive and the trustee path calls it on the raw value (C7).
- `actingweb/db/dynamodb/actor.py`: matches the plan.
  - `create` is one transaction.
  - `_modify_unique` claims the new record in a transaction and releases
    the old one separately.
  - `delete` releases the record with a conditional delete, and so does
    `_run_transaction` (three attempts, same token).
  - `replace_creator_holder` and `get_creator_holder` are as planned.
  - The release uses the handle's raw creator, not the stored normalised
    value (F7).
- `actingweb/db/postgresql/actor.py`: matches the plan.
  - `_is_creator_violation` is checked whatever the flag says.
  - `replace_creator_holder` renames the old holder and inserts the new
    actor in one transaction.
- `actingweb/db/postgresql/schema.py` / `migrations/env.py`:
  `include_object` is passed by both `configure` calls. The test
  `test_autogenerate_does_not_propose_dropping_the_index` shows that the
  filter is what hides the index.
- The three fixed-id creates (`system_actor.py`, `trust_type_registry.py`,
  `handlers/mcp.py`) catch `CreatorTaken` and load the actor instead.
- `handlers/trust.py`: answers 409 with a JSON body, and 400 for a reserved
  value (C7).
- `handlers/factory.py`: answers 403 on `CreatorTaken` and 400 for a
  reserved value; the form redirects to `/login`.
- `actingweb/actor.py`:
  - the passphrase match is removed;
  - `delete=True` loads each actor before deleting it (N7);
  - `replace_holder` is threaded through to the backend.
- `actingweb/maintenance/unique_creators.py`: `report`, `resolve`, `enable`
  and `disable` exist with dry run by default and exit codes 0, 1 and 2
  (D7, E7, G7).
- `actingweb/interface/app.py`: `check_ready` and `UniqueCreatorNotReady`
  exist, the check runs once per process, and a probe fault logs a WARNING
  (L7).
- `db/verify_tables.py`: has `--unique-creator`.

**Tests verified:** all planned tests exist and pass on both backends.
- **Backend:** creates, changes, pre-enable duplicates, the swap, and the
  PostgreSQL flag-off behaviour
  (`tests/integration/test_unique_creator_backend.py`).
- **Command:** 18 tests (`test_unique_creators_command.py`).
- **HTTP, fixed-id races and startup:** `test_unique_creator_http.py`.
- **Transaction retry, mocked:** `tests/test_unique_creator_transactions.py`.
- **Default pinned off:** `tests/test_unique_creator_default.py`.
- **Weak spot:** the case-only `resolve` test keeps the actor that is
  already lowercase, so the path where the kept actor is the mixed-case one
  is not exercised (G7).

**Failure scenarios:**
- **Orphaned record:** `report` lists it and exits 1
  (`test_orphaned_records_exit_one`).
- **Actors created during `enable`:** they appear under `unrecorded`
  (`test_an_actor_without_its_record_after_enable_exits_one`).
- **INVALID index:** dropped and rebuilt
  (`test_an_invalid_index_is_dropped_and_rebuilt`), and refused at startup
  (`test_an_invalid_index_refuses`).
- **Transaction conflict storm:** retried, then `DbError`
  (`test_conflicts_past_two_retries_raise_db_error`).
- **Flag rolled back with the index in place:**
  `TestPostgresIndexWithFlagOff`.

**Deviations from plan:** all are recorded under Phase 3 "Deviations" and
all are acceptable. The one this run reverses is the assumption behind
them, "an orphaned record blocks its address": a mismatched record
redirects a sign-in instead (A7).

### Phase 4: The enforced adoption branch, docs and release notes - ISSUES FOUND

**Changes verified:**
- `oauth2.py` `_replace_enforced` and the enforced branch in `_adopt_actor`
  match the plan, except that DELETED status is finished by the swap. That
  deviation is still waiting on the owner.
  - The successor's creator comes from `existing.creator`, not from the
    proven identifier (A7).
- `Actor.get_from_creator` reads the holder through `get_creator_holder`.
  It does not check that the loaded actor still has that creator (A7).
- `CHANGELOG.rst`: has the Breaking entries the plan lists (enforcement,
  `/login` redirect, reserved values, the custom-backend constructor), the
  command, `check_ready`, and the reworded known limitation.
- `docs/migration/v3.16.rst`: has Step 0 (six steps), the keep rule,
  rollback, `restore_actor.py` and the custom-backend checklist.
  - It does not mention the IAM policy (J7).
  - Its atomicity sentence overclaims (K7).
- Boundary hygiene:
  - `creator-uniqueness-not-enforced.md` is deleted and its INDEX row
    removed.
  - `unique-creator-default-on-next-major.md` exists with its INDEX row.
  - BK and BL are qualified as flag-off only.
  - Both in-code references to the deleted todo now point at the migration
    guide.
  - The two remaining mentions are in released CHANGELOG sections (lines
    1411, 1561) and stay as history.

**Tests verified:** `tests/integration/test_unique_creator_adoption.py`
covers:
- the factory squatter;
- hook order;
- a factory POST and a rename in the gap;
- DELETED, UNKNOWN, and a vouched actor with a tombstone;
- cleaning in place and a first sign-in;
- a read fault, a removal fault after the swap, and an orphaned record.

Missing tests:
- nothing covers a mismatched record, where the record names an actor
  whose creator changed (A7);
- nothing covers a create rollback after the swap (B7).

**Failure scenarios:**
- **Removal faults after the swap:**
  `test_a_removal_fault_after_the_swap_leaves_the_successor`.
- **The `creators` read faults:**
  `test_a_creators_read_fault_answers_503_and_creates_nothing`.

**Deviations from plan:** "DELETED/UNKNOWN → 503" became "UNKNOWN → 503,
DELETED → the swap". It is deduced, not confirmed, and still needs the
owner.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-29-db-fault-semantics-and-creator-uniqueness-6.md (PR 1)

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A6-C6 (resume path) | Fixed | Iteration 42; merged in #160 |
| D6-H6 (cookies, B5 test, wording, filings) | Fixed or filed | Iteration 43; merged in #160 |
| Remaining: commit, open PR 1, cut this branch | Done | `c7cef70`; this branch |

## Remaining Tasks

- [ ] Fix A7-C7 (High) before PR 2 opens, each with a regression test.
- [ ] Fix or file D7-I7 (Medium); fix J7 and K7 in the docs.
- [ ] The owner decides on the deletion status of the enforced replace
  branch (Decisions Made, deduced).
- [ ] Browser QA of the factory form once a demo `.env` exists, with
  `enable --apply` run against the demo store.
- [ ] Re-run `/verify_implementation`, then `/commit` and open PR 2.
- [ ] The demo deployment and `actingweb_mcp` run Step 0 before deploying
  3.16.

## Issues Found

### A7. A record whose actor changed creator signs a user into that actor, or hands them its new address
**Severity:** High (security)
**Location:**
- `actingweb/actor.py:366-371`:

  ```python
  holder = db.get_creator_holder(lookup_creator)
  ...
  self.get(actor_id=holder)
  return bool(self.id)
  ```
- `actingweb/oauth2.py` `_replace_enforced`:

  ```python
  creator = existing.creator or ""
  ...
  _create_actor_for_identifier(config, provider, creator, user_info, hooks, replace_holder=actor_id)
  ```

**Description:** the enforced lookup loads whatever actor the record names
and never checks that the actor still has that creator.

Suppose a record says `a → X` while X's creator is now `b`. Several paths
leave that state:
- a release fault after a rename (logged only);
- `resolve --apply`, which runs with the flag off and so never moves the
  record, renaming the actor the record names;
- `enable` racing a rename (D7);
- a re-enable after `disable` (E7).

The outcome depends on X:
- **X is vouched:** whoever proves `a` signs into X.
- **X is a `factory` actor:** the swap creates the successor with X's
  creator `b`, and moves the record for `b` to it. The person who proved
  `a` then holds `b`'s address.

**Recommendation:** in the enforced branch of `get_from_creator`, fail
closed on a mismatch: an ERROR log and 503, or a refusal. The check is
`normalise_creator(self.creator) != lookup_creator`. `_replace_enforced`
should create the successor with the identifier the provider proved, not
`existing.creator`. Add a test with a mismatched record on DynamoDB.

### B7. A create rollback after the swap leaves the creator held by nobody, and the squatter alive
**Severity:** High
**Location:**
- `actingweb/actor.py:571`: `rolled_back = bool(self.handle and self.handle.delete())`
- `actingweb/actor.py:607`: `self.handle.delete()`, the trustee_root rollback.

**Description:** with `replace_holder` set, the transaction has already
moved the record (DynamoDB) or renamed the squatter (PostgreSQL). If the
marker write then faults, the rollback deletes the successor row.
- **DynamoDB:** the delete releases the record, which now names the
  successor. The squatter still has creator X but no record, so the next
  sign-in finds no holder and creates a second actor for X.
- **PostgreSQL:** the squatter is left as `X#dup-…` with its trusts and
  tokens intact.
- **Both:** `_remove_for_replacement` never runs, so the squatter's tokens
  are not revoked.

**Recommendation:** when `replace_holder` is set, either let the removal
run anyway (`_replace_enforced` catches the failure and removes the
squatter), or move the creator back in the rollback. Add a test where the
marker write faults on the enforced replace.

### C7. Uppercase `#DUP-` gets past the reserved check; on PostgreSQL it blocks the owner's sign-in for good
**Severity:** High (PostgreSQL); Low (DynamoDB)
**Location:**
- `actingweb/handlers/trust.py:284`:
  `if not isinstance(creator, str) or is_reserved(creator):`
- `creator_rules.py` `is_reserved`: `DUP_MARKER in value`.

**Description:** the check runs on the raw value, and the backend
lowercases `@` values afterwards. A squatter holding `victim@x.com` with
factory actor S knows S's id from the 201. With a second actor it sets the
creator to `victim@x.com#DUP-<sha256(S)[:8]>`, which is stored lowercased.
That is exactly the value the PostgreSQL swap renames S to, so every
sign-in by the owner fails with `CreatorTaken`.

The factory lowercases before it checks, so it is not affected. No check
exists in `Actor.create`/`Actor.modify`, so `ActorInterface`, OAuth and MCP
inputs are not checked at all.

**Recommendation:** check `is_reserved(normalise_creator(value))`, and
enforce it in `Actor.create` and `Actor.modify` (the command excepted).
Consider a `#dup-` value that cannot collide, for example one salted with
a random suffix, checked as free in the same transaction.

### D7. DynamoDB `enable` marks the store complete from an eventually consistent scan
**Severity:** Medium
**Location:**
- `actingweb/maintenance/unique_creators.py:620`:
  `if report.exact or report.case_only:` (the only refusal)
- `:610`: `Creator(creator=BACKFILL_KEY).save()`

**Description:** step 5 of the rollout runs against live traffic. A rename
or delete between the scan and the put makes `enable` itself write a
mismatched or orphaned record, and it then writes the backfill-complete
item anyway. `enable` also does not refuse while `orphans` or `unrecorded`
are non-empty.

**Recommendation:**
- re-read each actor consistently before its put;
- force consistent scans in `enable`;
- refuse to write the backfill-complete item while orphans remain.

### E7. `disable` leaves the records, and a later `enable` trusts the stale ones
**Severity:** Medium
**Location:** `unique_creators.py:667`:
`Creator(creator=BACKFILL_KEY).delete()`, with the records left in place.

**Description:** with the flag off, deletes and renames never touch the
records. Re-enabling keeps the stale records (the A7 mismatch, and orphans
that lock an address) and writes the backfill-complete item. PostgreSQL's
`DROP INDEX` leaves nothing behind, so the backends differ.

**Recommendation:** have `disable --apply` empty the table, or have
`enable` reconcile every existing record before it writes the
backfill-complete item.

### F7. DynamoDB releases records under the handle's raw creator
**Severity:** Medium
**Location:**
- `actingweb/db/dynamodb/actor.py:392`: `creator = self.handle.creator`,
  then `self._release_record(creator, actor_id)`.
- `:172`: `old_creator = self.handle.creator` in `modify`.

**Description:**
- **A stale handle:** another process renamed the actor after this handle
  was loaded. The delete releases the old key and leaves the new record
  naming a deleted actor.
- **A legacy mixed-case row:** a row stored as `A@x.com` releases key
  `A@x.com`, while `enable` recorded `a@x.com`. The conditional delete
  fails silently, and the address is blocked until `resolve` runs.

**Recommendation:** release `normalise_creator(...)`. Take the creator from
the deleted item (`ALL_OLD`), or put a condition on the actor delete.

### G7. Mixed-case addresses outside a duplicate group are never lowercased, and `resolve` lowercases in the wrong order
**Severity:** Medium (not reproduced; read from the code)
**Location:**
- `unique_creators.py:460`:
  `if apply and kept_creator != normalise_creator(kept_creator):`
  runs before the losers are renamed.
- `:190`: `HAVING count(DISTINCT creator) > 1`.
- `postgresql/actor.py`: `SELECT id FROM actors WHERE creator = %s`.

**Description:** when the kept actor of a case-only group is the
mixed-case one, `_rename` to the lowercase value refuses, because a loser
still holds it ("taken; skipped"). A mixed-case address in no group is
never reported. On PostgreSQL its owner's sign-in then creates a second
actor without an error. On DynamoDB it leads to F7.

**Recommendation:** rename the losers first. Have `report` list every
non-normalised `@` value and `enable` refuse while any remain. Add a test
that keeps the mixed-case actor.

### H7. A concurrent first sign-in for one identifier answers 409
**Severity:** Medium
**Location:** `actingweb/oauth2.py:1049`: `return _create_actor_for_identifier(...)`,
then `except DbError: raise`.

**Description:** with the flag on, two tabs or an SPA retry both see no
actor. The second create raises `CreatorTaken`, and the user gets a 409
for their own account. `handlers/mcp.py` handles the same race with
`_race_winner`.

**Recommendation:** catch `CreatorTaken` there and call `get_from_creator`
once more, which loads the winner.

### I7. The open factory can take `system` and `oauth2-system`
**Severity:** Medium
**Location:** `actingweb/handlers/factory.py:259`, the reserved check
(which does not cover them); `creator_rules.py` `EXEMPT_CREATORS`.

**Description:** with the open factory and the flag on, `POST /` with
`creator=system` before the system actor exists makes every later
bootstrap get `CreatorTaken`. No actor then exists at the fixed id, so
trust types or the OAuth2 server stop working. The old flag-on
check-then-insert had the same exposure, but in 3.16 it is enforced.

**Recommendation:** reserve `system` and `oauth2-system` at the factory
and `PUT /trust/trustee`.

### J7. The migration guide does not mention the IAM policy for the new table
**Severity:** Medium (docs)
**Location:** `docs/migration/v3.16.rst`, Creator uniqueness;
`docs/quickstart/configuration.rst:221`, which lists least-privilege
actions per table.

**Description:** a runtime role scoped to named tables gets AccessDenied
on `<prefix>_creators`. The startup probe treats that as a fault, so the
app starts, and every create then answers 503. The v3.13 guide carried the
same note for `property_lookup`.

**Recommendation:** add a sentence to Step 0 and to `configuration.rst`.

### K7. The migration guide claims the delete is transactional
**Severity:** Low (docs)
**Location:** `docs/migration/v3.16.rst:459`: "written in the same
`TransactWriteItems` as the actor create, creator change and delete".

**Description:** the delete, and the release after a rename, are separate
conditional deletes, and a fault there is only logged.

**Recommendation:** state exactly what is atomic, and say that `report`
lists what a failed release leaves behind.

### L7. "Writes still enforce" after a probe fault is not quite true on DynamoDB
**Severity:** Low
**Location:**
- `actingweb/interface/app.py` `check_ready` docstring: "writes still
  enforce, or fail closed".
- `docs/migration/v3.16.rst`, the same sentence.

**Description:** with table auto-creation on, `DbActor.__init__`
(`ensure_table(Creator)`) creates an empty `creators` table. Enforcement
then covers only actors created from then on.

**Recommendation:** reword, or skip `ensure_table(Creator)` and fail
closed when the table is missing.

### M7. A lost answer to a committed transaction reads as a fault
**Severity:** Low
**Location:** `dynamodb/actor.py` `_run_transaction`:
`except Exception as e: raise DbError(op) from e`.

**Description:** the factory answers 503 although the actor exists. A
retry then gets 403, and the caller never learns the id. botocore's own
retries do reuse the token, so this needs a failure after those retries
run out.

**Recommendation:** document it, or retry transport errors with the same
token.

### N7. `create(delete=True)` finds the actors to delete through the lagging index
**Severity:** Low
**Location:** `actingweb/actor.py:470`:
`existing = get_actor(self.config).get_by_creator(creator=self.creator, consistent=True)`.

**Description:** an actor created moments ago can be missed, and the
create then raises `CreatorTaken`.

**Recommendation:** use `get_creator_holder` under the flag.

### O7. The default-creator rewrite loop runs on the create path
**Severity:** Low
**Location:** `actingweb/actor.py:484`:
`Actor(actor_id=c["id"], config=self.config).get()`.

**Description:** with the flag and `force_email_prop_as_creator` on, every
create with `DEFAULT_CREATOR` lists and loads every actor that shares it.
The constructor already loads each one, so the extra `.get()` loads it a
second time.

**Recommendation:** drop the extra `.get()`, and consider moving the
rewrite to the command.

### P7. PostgreSQL parity
**Severity:** Low
**Location:** `actingweb/db/postgresql/actor.py`, where modify raises
`CreatorTaken(creator)` with the value before normalisation.

**Description:** on PostgreSQL, `replace_creator_holder` and
`get_creator_holder` do not check the flag. DynamoDB raises `ValueError`
when it is off.

**Recommendation:** align the behaviour and raise with the normalised
value.

### Notes
- `DbActor._connection` is cached at class level. Its fork safety under a
  preloading server was not checked.
- An app that calls neither integration nor `check_ready()` runs without
  the startup check, as documented.

## Overall Assessment

Phases 3-4 are implemented as planned, and every planned test exists. The
full tier is green on both backends: DynamoDB 4324 passed, PostgreSQL 4210
passed.

The review found a gap in the design's central assumption. A stale
`creators` record was taken to only block its address. Nothing checks it
against the actor row, so a mismatched record redirects a sign-in, and on
the swap path it hands over another address (A7). Several paths here,
`resolve` and `enable` among them, can produce such a record. B7 and C7
break the one-holder invariant through a rollback and a reserved-check
bypass.

The three High issues are local fixes: one check and one argument in the
lookup and the swap, the rollback branch, and normalising before the
reserved check. They should land, with regression tests, before PR 2
opens. The Medium items can be fixed in the same iteration or filed. The
factory form's UI was not exercised in a browser.
