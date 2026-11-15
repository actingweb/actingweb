# Verification: "creator equals stored email" enforced where the email is written

**Date:** 2026-11-15
**Plan:** thoughts/plans/2026-11-06-email-as-creator-at-write-time.md
**Research:** thoughts/research/2026-11-06-actor-load-cost-and-email-as-creator.md
**Branch:** release/3.16.0-email-as-creator-at-write-time (not pushed)
**Commit:** `769a7c1` (code as of `844695a`; `769a7c1` changes only docs and
the changelog)

No feature document; no phase touches a page.

## Automated Check Results

- **Browser QA:** N/A (no UI phases).
- **Second opinion**, on the whole range `6f4a7a4..844695a`:
  - **Outside voice:** codex (`codex exec -s read-only`, outside the
    sandbox) and a fresh-context reviewer. 2 codex findings (one already
    recorded in the plan), 5 fresh-context findings. See Issues Found.
  - **Built-in code review** (high): 9 findings; two rejected on evidence
    (below), the rest under Issues Found.
  - **Built-in security review:** no vulnerability at the reporting
    threshold. Every library path that writes an `_internal` email writes
    a proven address or the creator itself; no anonymous or peer path
    chooses the value; no SQL is built from input (`only_expired` is a
    constant).
- **Full tier, on `844695a`** (the code this verification covers):
  - ruff, ruff format, pyright: clean. `verify_groups.py`: pass.
  - `make test-all-parallel`, **DynamoDB:** 7,593 passed, 211 skipped,
    2 xfailed.
  - `make test-all-parallel`, **PostgreSQL:** 7,364 passed, 440 skipped,
    2 xfailed.
  - Docs build (`sphinx-build -W`): pass, on `844695a` and again on
    `769a7c1`.
- Benchmarks: not run; the plan touches no list storage.
- **Emm's suite on `844695a`** (gate 2; environment 9; the library
  worktree checked out at `844695a`):
  - Before the run, `actingweb-unique-creators creator-to-email` on
    environment 9's database: 1 actor scanned, nothing to move; then
    `--apply` wrote the marker. The preview server then started past all
    four start-up checks. This is the documented operator step; no Emm
    code was changed.
  - **PostgreSQL:** 3 failed, 7,405 passed, 14 skipped, 179 deselected.
    **DynamoDB lane** (`scripts/test-backends.sh 9`): 3 failed, 54 passed.
  - Both are the `a98690a` baseline's failures by name, nothing new
    (`comm` of the sorted FAILED lines: no difference either way). Logs:
    `../actingweb_mcp/.claude/worktrees/emm9-{pg,dyn}-844695a.log`.
  - Emm's `test_dynamodb_iam_coverage` failure (a baseline one) has the
    same message as before. Emm's role (`serverless.yml`) grants its
    actions on every table under its prefix, so the attributes table is
    covered, but it grants no `dynamodb:ConditionCheckItem` at all, which
    creator uniqueness already needed and the rename's marker check needs
    too; that test does not look for it. A note for Emm's adoption work,
    not a library change.

## Phase Verification

### Phase 1: one atomic rename on both backends - VERIFIED

- `actingweb/db/creator_rename.py` (types, `validate_rename_writes`),
  `actingweb/db/dynamodb/actor.py` (`rename_creator`, `_rename_outcome`,
  `_run_transaction_reasons`), `actingweb/db/postgresql/actor.py`
  (`rename_creator`, `_rename_once`), `actingweb/db/protocols.py`,
  `docs/migration/v3.16.rst` "Custom database backends": as the plan's
  2026-11-15 refresh and the phase notes describe.
- Tests: `tests/integration/test_rename_creator.py` (both backends: applied,
  every refusal, collisions, the precedence of row and marker over a
  collision, faults, crossing renames, a bucket delete race, the absent-key
  race on PostgreSQL), `tests/test_rename_creator_dynamodb.py` (positions
  by kind, the request PynamoDB builds, retries with one token).
- Deviations: recorded in the phase notes (types module, `equals` takes a
  string, conditions in SQL, lock order shared with the bucket deletes).

### Phase 2: the writers, the rename and the load - ISSUES FOUND

- `actingweb/creator_sync.py`, `actingweb/attribute.py`, `actingweb/actor.py`
  (`get()` one read), `actingweb/interface/actor_interface.py`
  (`_rename_vouched`), `actingweb/handlers/mcp.py`: as planned, with the
  recorded deviation that every email write the link applies to is
  conditional.
- Tests: `tests/test_creator_follows_email.py` (47), the rewritten adoption,
  MCP and uniqueness tests. `grep -rn "rewrite_email\|_email_held_elsewhere\|_rename_pinned\|_restore_email" actingweb`:
  nothing.
- Issues: the write path's vouch check, the mixed-case creator side effect,
  and the SDK rename's read-back (Issues Found 2, 4, 6).

### Phase 3: the sweep, the marker and the start-up check - ISSUES FOUND

- `actingweb/maintenance/email_as_creator.py`, `unique_creators.py`
  (`creator-to-email`), `interface/app.py` (`EmailAsCreatorNotReady`, the
  fourth check), `mark_actors_vouched.py` (`--email-as-creator`), the test
  seam in `tests/_lookup_probe.py`.
- Tests: `tests/integration/test_email_as_creator_sweep.py` (24, both
  backends), `tests/test_email_as_creator_check.py`,
  `tests/test_mark_actors_vouched.py::TestEmailAsCreator`. Both `--help`
  commands exit 0.
- Issues: a dry run releases stale records; `_holder` has no return type
  (Issues Found 5, 8).

### Phase 4: documentation, changelog and records - ISSUES FOUND

- The changelog, the guide's item 25, warning box and section "The creator
  follows the stored email", configuration, getting-started, authentication
  and deployment: written. The vouched-rename todo is deleted with its row;
  every todo file has a row and every row a file.
- After the owner's note (2026-11-15) the unreleased guide and changelog
  name no consumer (`769a7c1`).
- Issues: four claims are not exactly true (Issues Found 3).

## Security properties claimed by the plan

- **A sign-in seed loses to a rename** (the seed's `absent` condition):
  `tests/test_creator_follows_email.py::TestOutcomes::test_set_if_absent_loses_to_a_stored_email`
  asserts `late.set_if_absent("email", old) is False` and the creator stays
  `new`; on PostgreSQL with the key written after the lock,
  `tests/integration/test_rename_creator.py::TestConcurrency::test_an_absent_key_written_after_the_lock_is_a_lost_condition`
  asserts `ATTR_CONDITION` and the seed's value kept.
- **An unvouch between the read and the commit wins:**
  `test_a_changed_or_missing_marker_changes_nothing` (both backends)
  asserts `MARKER_CHANGED` and an unchanged snapshot.
- **An anonymous squat cannot keep a flag-on application from starting:**
  `tests/integration/test_email_as_creator_sweep.py::TestTheSweep::test_a_mixed_store`
  asserts `squatted == 2` (a `factory` and an `email_unverified` holder) and
  the marker written once only the vouched holder is cleared.

## Rejected findings

- **A provider-id sign-in under the flag raising `CreatorTaken` after the
  create** (`oauth2.py:1941-1945`, code review 1 and 2): under the flag every
  caller passes `require_email` (`handlers/oauth2_callback.py:393-397`,
  `handlers/oauth2_spa.py:1158`, `:1496`, `:1595`,
  `oauth2_server/oauth2_server.py:479`), and with it the identifier is an
  address (`oauth2.py:1031-1040`), so the `":" in identifier` branch is not
  taken; without the flag no link runs.

## Issues Found

### 1. A persistent trustee handoff can be blocked for good by an anonymous factory create
**Severity:** Medium (anonymous-reachable)
**Description:** Phase 2 makes `PUT trust/trustee {"creator": "trustee"}`
persist under the flag (before, the next load undid it). The rename to the
exempt `trustee` releases the owner's creator record
(`db/dynamodb/actor.py:322-323`; PostgreSQL's index stops holding the
address the same way). While the actor is handed off, an anonymous
`POST /` with the stored email creates a `factory` actor holding that
address; the trustee's handback then answers 409, and the owner's next
sign-in replaces the squat with a new empty actor, leaving the data actor
with the trustee and the handback failing for good. The sweep skips
`trustee` actors, so nothing reports it. The plan's failure scenario names
only the owner's own sign-in.
**Location:** `actingweb/db/dynamodb/actor.py:322-323`,
`actingweb/actor.py` (`modify_creator_unvouched`, the handoff),
`docs/migration/v3.16.rst` "A handoff to the trustee persists".
**Recommendation:** an owner decision (asked 2026-11-15).

### 2. The write path's vouch check is the marker-only form; the sweep's is bound to the creator
**Severity:** Medium (application-reachable; the docs' claim is not exactly true)
**Description:** After a deliberate `Actor.modify(creator=X)`, any later
email write through the library (an application re-saving the unchanged
address included) moves the creator back to the email and rewrites
`vouched_creator`, while the sweep leaves such an actor alone. The changelog
and the guide say a direct creator change "is no longer undone". The plan's
Decision chose the marker-only form ("deduced, confirm at approval"), and
Phase 2's notes accepted it.
**Location:** `actingweb/creator_sync.py:130-131`
(`is_vouched_store(fresh)`) vs `actingweb/maintenance/email_as_creator.py:142`.
**Recommendation:** bind the write path's check to the current creator
(`is_vouched_store(fresh, current)`), as the sweep does; an owner decision,
since it changes a recorded one (asked 2026-11-15).

### 3. Four claims in the guide and the changelog are not exactly true
**Severity:** Medium (docs)
- "moves its uniqueness record … as one atomic backend operation": the new
  record is claimed in the operation; the old one is released after it, and
  a fault there is logged (`db/dynamodb/actor.py:464-470`).
- "An address another actor holds raises `CreatorTaken`": only with
  `with_unique_creator()` (`db/dynamodb/actor.py:353-357`); without it the
  write renames onto a held address.
- The write methods: `store.email = …` and `set_if_absent` raise;
  `set_confirmed` (unless `raise_on_fault`) and `replace_if_equal` answer
  False, logged (`attribute.py:109`, `:169`, `:268`).
- "`Actor.modify(creator=…)` is not undone": see 2.
**Location:** `docs/migration/v3.16.rst:1150-1176`, `CHANGELOG.rst:929-972`.
**Recommendation:** reword after 1 and 2 are decided.

### 4. An email write that keeps the creator lowercases a legacy mixed-case creator, and can claim a record
**Severity:** Low
**Description:** `rename_creator` normalises `creator` and compares it with
the raw `expected`, so a same-creator call for `Foo@X.com` claims
`foo@x.com` under uniqueness (a `CreatorTaken` when another actor holds it)
and rewrites the row in lower case, as a side effect of an email write.
**Location:** `actingweb/db/dynamodb/actor.py:352-357`,
`actingweb/db/postgresql/actor.py:504`, `actingweb/creator_sync.py:136-137`.
**Recommendation:** when `creator` normalises to `expected`'s normal form,
keep `expected` unchanged and claim nothing, on both backends.

### 5. A dry run of the sweep releases stale creator records
**Severity:** Low (operator tool; a stale record is safe to release)
**Location:** `actingweb/maintenance/email_as_creator.py:170`
(`release_stale_creator` in `_holder`, whatever `apply` says).
**Recommendation:** release only under `--apply`.

### 6. The SDK rename's read-back after a fault checks only the creator
**Severity:** Low
**Description:** `modify_creator(current_creator)` that faults before its
commit reads back a creator equal to the target and answers True although
the email and vouch were not written. `creator_sync._landed` checks the
email too.
**Location:** `actingweb/interface/actor_interface.py:550`.
**Recommendation:** reuse `_landed` (creator and email) when the operation
wrote the email.

### 7. Accepted, recorded in the plan
- `marker=None` for an actor with no `auth_method` is "no check", not
  "still absent" (Phase 2 notes).
- A linked write costs a fresh row read, a second bucket read and a
  transaction (Evaluation Notes, Scalability); code review rated it Low.

### 8. `_holder` has no return annotation
**Severity:** Low (the project's rule: type hints on every function)
**Location:** `actingweb/maintenance/email_as_creator.py:151`.

## Remaining Tasks

- [ ] Owner decisions on Issues 1 and 2.
- [ ] `/iterate_plan`: Issues 2 to 6 and 8, then a narrow re-verification.
- [ ] Note for Emm's adoption work: its role needs
      `dynamodb:ConditionCheckItem`.
- [ ] Open the PR once the re-verification is clean.

## Overall Assessment

The four phases are implemented as planned with recorded deviations, the
Full tier is green on both backends, Emm's suite shows only its baseline,
and the security review found nothing exploitable. One finding is
reachable without authentication: a trustee handoff, which Phase 2 makes
persistent, can be stranded by an anonymous factory create (Issue 1). One
recorded decision makes a documented guarantee untrue (Issue 2). By the
stop rule this run is not clean; both need the owner before
`/iterate_plan` fixes them and the rest.
