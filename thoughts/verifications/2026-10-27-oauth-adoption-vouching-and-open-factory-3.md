# Verification: vouched actors, clean-slate adoption on OAuth login, a closable factory, and SPA `prompt` (third run)

**Date:** 2026-10-27
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md (Part 1); thoughts/research/2026-10-27-adoption-writes-and-deletes-reported-done-on-fault.md (this batch's bug record)
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; all of the work is uncommitted in the working tree)

This run reads the plan's second Iterations batch (entries 8-13, "after
verification ...-2.md") against the code. The phases and the first batch
were verified in the two earlier runs; their findings are not repeated.

## Automated Check Results

- **Browser QA:** not re-run. The batch changed no rendered page: the rename
  is a JSON/204 API, the backfill is a CLI, and the `.env.example` change is
  covered by `tests/test_demo_example.py`. The first run's walk of the demo
  stands for the HTML pages.
- **Second opinion:**
  - **outside-voice:** Codex (`codex exec -s read-only`, unsandboxed) plus a
    fresh-context Claude. 16 findings plus 4 unverified notes. I re-read the
    code for each High and Medium; all held. Folded into Issues Found.
  - **`/code-review high`:** 10 findings. Two are new and folded in (M, U).
    Four repeat items already deferred to
    `thoughts/todo/adoption-fault-and-hygiene-followups.md` (duplicate
    tombstone, lost successor mapping, summary re-reads, type hints). Two
    question decisions already made in earlier runs (the SPA paths' own
    adoption call, declined in Iterations entry 5; adoption on the bearer
    path, a plan decision). They are listed under Notes.
  - **Security review (built-in):** no findings above the confidence bar.
    It checked `set_confirmed`, the create rollback, every sign-in path, the
    strict revoke, the rename exemptions and the 400, the factory gate and
    the backfill.
- `ruff check actingweb tests`: pass, "All checks passed!"
- `ruff format --check actingweb tests`: pass, 420 files already formatted.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings, 0 informations.
- `tests/integration/verify_groups.py`: pass, all 50 groups documented.
- **DynamoDB suite** (`make test-all-parallel`): pass, 4007 passed, 31
  skipped. The oss-scanner worktree's container was removed at the owner's
  request, so the target ran as written, containers included.
- **PostgreSQL suite** (`make test-all-parallel` with the Full tier's PG
  environment): pass, 3898 passed, 140 skipped.
- **Docs build** (`sphinx-build -W`, `.claude/**` excluded locally): pass,
  "build succeeded".
- **Benchmarks** (`tests/performance -m benchmark`, run alone, DynamoDB):
  17 passed. The batch touched the attribute layer, so they ran.
  - The first run against a fresh container failed 2 attribute benchmarks
    with `ResourceNotFoundException ... test_attributes`. The attribute
    tables did not exist yet, because the benchmarks do not create them.
    After one unit test created them, all 17 passed. This is an existing
    setup gap in the benchmarks, not a regression.
  - Medians (previous run in brackets): attribute read 0.80 ms (1.12),
    attribute write 1.07 ms (1.78), trust list 1.21 ms (4.18), actor create
    6.17 ms (2.96), actor delete 9.48 ms (3.16), bulk property read 131 ms
    (315).
  - Actor create roughly doubled. That fits the new strict read-back of
    the marker. Actor delete did not change in this batch, and the spread
    between runs is wide (trust list and bulk read moved the other way), so
    the delete figure is noise until a second run shows otherwise.

## Phase Verification

### Entry 8: strict revoke confirms each delete (Issue A) - VERIFIED

- `actingweb/oauth_session.py:892-898`: strict mode deletes through
  `delete_confirmed(self.config, OAUTH2_SYSTEM_ACTOR, name, token)`. The
  argument order matches `single_use.py:197`
  (`config, actor_id, bucket, name`). Non-strict mode still calls
  `bucket.delete_attr`. Matches.
- `TestSwallowedTokenDelete::test_unconfirmed_session_delete_fails_the_adoption`
  (`tests/test_adoption_write_faults.py:95`) makes the delete answer True
  without removing the row, and asserts the adoption fails. Meaningful.

### Entry 9: confirmed marker writes (Issue B) - ISSUES FOUND

- `actingweb/attribute.py:62-87` `set_confirmed`: write, strict read-back,
  then the in-memory value. Matches. Low edge cases are in Issue V.
- `actingweb/actor.py:450-452`: `mark_empty()` only when `created`. Matches.
- `actingweb/actor.py:470-479`: a marker that does not land deletes the new
  actor and returns False. Matches the plan, but the rollback can hit a live
  actor on DynamoDB and its result is not checked (Issue P).
- `actingweb/oauth2.py:1902`: the clean path's marker uses `set_confirmed`.
  Matches. The `email_verified` clear beside it is not confirmed (Issue Q).
- Tests: `TestMarkerWriteFault` (two tests). Meaningful; both inject the
  fault at the backend class, so they run on either backend.

### Entry 10: creator rename (Issue F, B's third site) - ISSUES FOUND

- `actingweb/handlers/trust.py:274-314`:
  - the exemptions for `trustee` and the stored email;
  - the 400 under `force_email_prop_as_creator`;
  - the marker confirmed before `modify`, and restored when `modify` fails.

  This matches the decision the owner made. Four problems remain: a
  `factory` marker is downgraded (Issue M); a failed `modify` (Issue N) and
  an unloaded bucket (Issue O) are mishandled; `trustee_root` is written
  before the refusal (Issue T).
- Tests: `tests/test_trust_creator_rename.py`, four tests covering the
  other address, the handoff and the way back, the marker fault and the
  pinned 400. Meaningful. Nothing tests a failing `modify`, an unloaded
  bucket, a mixed-case stored email, or a `factory` actor being renamed.

### Entry 11: the backfill ships in the wheel (Issues C, G) - ISSUES FOUND

- `pyproject.toml:26` `packages = [{ include = "actingweb" }]` and `:39`
  `actingweb-mark-actors-vouched = "actingweb.maintenance.mark_actors_vouched:main"`.
  The module is inside the package, so it ships. Matches.
- `actingweb/maintenance/mark_actors_vouched.py:91-93`: a list that is not a
  list raises `ActorListUnavailable`. Matches for PostgreSQL. A DynamoDB
  fault raises during iteration instead (Issue R).
- The marker refusal, `set_confirmed`, and the last-id log line are present.
  The resume hint is wrong after an error (Issue R).
- Tests: `TestBackfillListFault`. This mocks `fetch` to return False, so it
  does not exercise DynamoDB's lazy scan.

### Entry 12: demo `.env.example` (Issue D) - VERIFIED (weak test)

- `examples/demo/.env.example` sets `OPEN_FACTORY=true`. Matches.
- `tests/test_demo_example.py:209`, the `env-example` case. If the key were
  removed, `_env_example_value` would return None, the test would take the
  unset branch, and it would still pass (Issue X).

### Entry 13: docs (Issue E and the ranked items) - ISSUES FOUND

The items from the previous run's docs audit are present: the
verification-link sign-out, the 409, the backfill section with output and
exit codes, the MCP reconnect, the deletion docs, the SDK code block, the
marker table, the autodoc sections and the two **Breaking:** leads. The
docs build is clean. Three claims do not match the code (Issue S).

## Security property demonstrated

The plan claims that a write or delete that changes a vouching decision is
confirmed, not trusted. Pinned by:

- `TestMarkerWriteFault::test_actor_is_not_created_without_its_marker`:
  asserts `create` returns False and no actor row remains.
- `TestMarkerWriteFault::test_clean_in_place_fails_when_the_vouched_marker_does_not_land`:
  asserts the sign-in returns None.
- `TestSwallowedTokenDelete::test_unconfirmed_session_delete_fails_the_adoption`:
  asserts the sign-in fails while the token row survives.
- `TestUnpinnedCreator::test_marker_write_fault_refuses_the_rename`: asserts
  500, creator unchanged, marker unchanged.

The property holds for the writes it names. It does not yet hold for three
writes that also decide a vouch:
- the marker restore after a failed rename (Issue N);
- the `email_verified` clear (Issue Q);
- the create rollback's delete (Issue P).

## Thoughts bookkeeping

- The two todos the plan closes (`oauth-adoption-of-unvouched-actors-and-open-factory.md`,
  `spa-authorize-prompt.md`) are gone, and so are their `INDEX.md` rows.
  They were created and deleted inside this uncommitted work, so `git` shows
  no deletion.
- Each deferral has a todo with an `INDEX.md` row:
  - `adoption-fault-and-hygiene-followups.md`: Issues H-L;
  - `spanned-list-items.md`: the second 3.16 plan;
  - `creator-uniqueness-not-enforced.md`: the successor race.
- **Consumer message:** the plan has none. Nothing to quote.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| A. DynamoDB strict revoke cannot see a failed delete | Fixed | `oauth_session.py:892-898`; `TestSwallowedTokenDelete` |
| B. `_internal` writes never confirmed | Fixed at the three marker sites; one restore and the `email_verified` clear remain | `attribute.py:62`, `actor.py:471`, `oauth2.py:1902`, `trust.py:303`; Issues N, Q |
| C. Backfill reports success on an unreadable list | Fixed on PostgreSQL; on DynamoDB the fault exits 1 with a traceback | `mark_actors_vouched.py:92`; Issue R |
| D. `.env.example` closes the factory | Fixed | `examples/demo/.env.example`; test is weak (Issue X) |
| E. Verification link signs out; 409 | Fixed (docs, as decided) | `docs/guides/spa-authentication.rst`, `docs/migration/v3.16.rst` |
| F. `creator_changed` on the handoff and the revert | Fixed as decided; a `factory` marker is downgraded | `trust.py:275-298`; Issue M |
| G. Backfill not in the wheel | Fixed | `pyproject.toml:39` |
| H. `DELETE /<id>` ignores `delete() -> bool` | Deferred | `thoughts/todo/adoption-fault-and-hygiene-followups.md` |
| I. Replace-path client rows after a bucket fault | Deferred | same todo |
| J. Tokens issued between revoke and purge | Deferred | same todo |
| K. UNKNOWN tombstone read | Deferred | same todo |
| L. Low findings | Two folded in (entries 9, 11); rest deferred | same todo |

The previous run's Remaining Tasks:
- A-C, D-G and the docs items were addressed as tabled above.
- The owner made both decisions: F (exempt `trustee` and the own email, and
  refuse with 400 when pinned) and the **Breaking:** leads (added).
- The release-PR bump is still open.
- The triage outputs are still uncommitted with this work.

## Remaining Tasks

- [ ] Fix Issues M-O before release (`/iterate_plan`). Each can leave an
      actor with the wrong vouching state; M is reachable by a squatter
      without any fault.
- [ ] Fix Issues P-S in the same iteration, or file them in the follow-ups
      todo. Issues T-X are Low and can go there too.
- [ ] Release PR:
  - the version bump in `pyproject.toml` and `actingweb/__init__.py`;
  - the `Unreleased` rename;
  - a `.. note::` pointing at `docs/migration/v3.16.rst`.

  The release number is still to be set in that PR (3.16.0 in the tree, a
  major release per the owner).
- [ ] Commit the triage outputs with this work.

## Issues Found

### M. A rename downgrades a `factory` marker to `creator_changed`, so a squatter's actor is cleaned instead of replaced
**Severity:** High
**Description:**
- `actingweb/handlers/trust.py:302-303`: `if unvouch and (not store or not store.set_confirmed("auth_method", "creator_changed"))`
  writes `creator_changed` whatever the previous marker was.
- `REPLACE_AUTH_METHODS = frozenset({"factory"})` (`oauth2.py:1579`) does
  not include it.

A squatter does two things:
1. `POST /` with any creator. The new actor is marked `factory`, and the
   response returns its passphrase.
2. `PUT /<id>/trust/trustee {"creator": "victim@x"}` with that passphrase.
   `own_email` is empty, so the pin check does not apply, and the marker
   becomes `creator_changed`.

When the victim signs in, the actor is cleaned in place instead of replaced.
The victim's account then keeps the squatter's properties, lists, buckets
and `trustee_root`. This defeats the rule that an actor made from
unauthenticated input holds nothing legitimate. No fault is needed.
**Location:** `actingweb/handlers/trust.py:294-304`
**Recommendation:** leave the marker alone when `previous_marker` is in
`REPLACE_AUTH_METHODS` (it is already unvouched and stricter). Add a test
that renames a `factory` actor and asserts the victim's sign-in replaces it.

### N. A failed `modify` leaves the owner's actor `creator_changed` (DynamoDB) or answers 204 (PostgreSQL)
**Severity:** High
**Description:**
- `actingweb/handlers/trust.py:312-314`: `if not myself.modify(creator=creator) and unvouch and store: store.auth_method = previous_marker`.
- On DynamoDB, `modify` raises: `self.handle.save()` at
  `db/dynamodb/actor.py:124`, documented at `actor.py:500`. The restore
  never runs and the request ends in an exception. The creator is
  unchanged, but the marker stays `creator_changed`, so the owner's next
  sign-in cleans their own actor in place: new passphrase, and trusts,
  subscriptions, sessions and clients removed.
- The restore itself is a plain write, which PostgreSQL can fail without a
  word.
- On PostgreSQL, a `modify` that returns False falls through to
  `set_status(204)`, so the client is told a rename happened that did not.
**Location:** `actingweb/handlers/trust.py:312-316`
**Recommendation:**
- Wrap `modify` in try/except.
- On failure, restore with `set_confirmed` and answer 500.
- If the restore also fails, log at ERROR with the actor id.
- Add a test with `modify` raising and one with it returning False.

### O. The rename acts on an `_internal` bucket that did not load
**Severity:** High
**Description:**
- `actingweb/handlers/trust.py:276` `own_email = store.email if store else None`
  and `:299` `previous_marker = store.auth_method if store else None` read
  the bucket without checking `store.loaded`.
- Compare `actingweb/oauth2.py:1761`, which fails closed.

On a PostgreSQL bucket-read fault both values come back None:
- The pinned-creator 400 is skipped. The rename goes through, the next
  `Actor.get()` puts the stored email back as creator, and the marker stays
  `creator_changed`. That is the Issue F state entry 10 says it closed, and
  it costs the owner a clean at their next sign-in.
- If `modify` then fails too, the restore writes `auth_method = None`,
  which deletes a real vouching marker. The actor then reads as legacy, and
  its next sign-in cleans it.
**Location:** `actingweb/handlers/trust.py:274-299`
**Recommendation:** when a creator is sent and `store` is missing or
`store.loaded` is False, answer 500 before reading either value. Add a test
that injects a bucket-read fault.

### P. The create rollback is unchecked and can hit a live actor on DynamoDB
**Severity:** Medium
**Description:** `actingweb/actor.py:478` `self.delete(notify_peers=False)`
ignores the bool `delete()` returns:
- **PostgreSQL:** if the delete also faults, `create` returns False, an
  unmarked row remains, and its next sign-in cleans it.
- **DynamoDB:** `create` checks `if self.get(actor_id=actor_id)`
  (`db/dynamodb/actor.py:144`), but `get()` answers None on any fault
  (`:63-79`), and the put that follows is unconditional. The MCP bridge
  calls `create(..., actor_id=actor_id, auth_method="oauth2_bearer")`
  exactly when the actor load failed (`handlers/mcp.py:2429`).

The overwrite on DynamoDB is older than 3.16. What the 3.16 code adds:
- a marker that lands overwrites the live actor's own marker;
- a marker that is throttled by the same storm makes the rollback delete
  wipe the live actor's buckets, trusts and subscriptions.

It needs correlated faults.
**Location:** `actingweb/actor.py:470-479`; `actingweb/db/dynamodb/actor.py:144-148`
**Recommendation:**
- Log at ERROR when the rollback's `delete()` returns False.
- Skip the rollback delete when the caller supplied `actor_id`, or make
  the DynamoDB insert conditional (`attribute_not_exists(id)`). The latter
  is the real fix and may belong in its own todo.

### Q. The `email_verified` clear on the clean path is not confirmed
**Severity:** Medium
**Description:** `actingweb/oauth2.py:1916` calls
`clear_pending_email_verification`, which writes
`actor_instance.store.email_verified = None` (`:1562`), a plain write.
`is_vouched_actor` returns `store.email_verified != "false"` (`:1599`).
If that delete fails on PostgreSQL, the actor carries a vouching marker but
still reads as unvouched. Every later sign-in then cleans it again, with no
error logged. This is the class of fault entry 9 fixed.
**Location:** `actingweb/oauth2.py:1916`, `:1562`
**Recommendation:** confirm the clear with a strict read-back (absent or
not `"false"`) and fail the sign-in when it does not hold.

### R. Backfill: resume hint, DynamoDB list fault, overloaded exit 2
**Severity:** Medium
**Description:**
- **Resume hint:** `mark_actors_vouched.py:110` sets `last = actor_id`
  before the try, and `:143` prints `resume with --start-after {last}`.
  After a run with errors, following the hint skips the actors that errored.
  They stay unmarked and are cleaned at their first sign-in.
- **DynamoDB list fault:** `db/dynamodb/actor.py:175` `self.handle = Actor.scan()`
  is lazy and always truthy, so a fault raises during iteration. The tool
  then exits 1 with a traceback, not 2 as documented. The module docstring
  (`:82-83`) says both backends answer False.
- **Exit 2:** `parser.error` also exits 2 for a refused `--marker`, while
  `docs/migration/v3.16.rst:158` defines 2 as "the actor list itself could
  not be read".
**Location:** `actingweb/maintenance/mark_actors_vouched.py:91-143`, `:175`
**Recommendation:**
- When `errors > 0`, say to re-run without `--start-after`.
- Catch exceptions from `fetch()` and raise `ActorListUnavailable`.
- Document exit 2 for a bad argument, or use another code.

### S. Three doc claims do not match the code
**Severity:** Medium
**Description:**
- **Pre-3.16 markers:** `CHANGELOG.rst:50` says "every actor created before
  3.16 has no marker", and the module docstring (`mark_actors_vouched.py:5`)
  and `docs/migration/v3.16.rst:17` say the same. Pre-3.16 provider logins
  already wrote `<provider>_oauth2` (HEAD `oauth2.py:1019`), and the same
  docstring says so at line 10. Operators get the wrong picture of which
  actors are affected.
- **The 400:** `docs/migration/v3.16.rst:243-244` says "a `creator` other
  than those two answers 400". The code also requires a stored email
  (`trust.py:280-281`); Iterations entry 10 states the qualifier.
- **Exit 2:** see Issue R.
**Location:** `CHANGELOG.rst:50`; `docs/migration/v3.16.rst:17`, `:158`, `:243`; `actingweb/maintenance/mark_actors_vouched.py:5`
**Recommendation:** say actors without a marker, which are those created
outside a provider login before 3.16. Add "when the actor has a stored
email" to the 400 sentence.

### T. `trustee_root` is written before a refused or failed rename
**Severity:** Low
**Description:** `actingweb/handlers/trust.py:264` `actor_interface.trust.trustee_root = trustee_root`
runs before the 400 and 500 returns, so a rejected request is partly
applied.
**Location:** `actingweb/handlers/trust.py:263-264`
**Recommendation:** validate the creator, and write the marker, before
writing `trustee_root`.

### U. Flask's JSON factory GET honours `_method=POST`
**Severity:** Low
**Description:** `flask_integration.py:795-806` runs
`RootFactoryHandler.get()`, and `factory.py:146` `if self.request.get("_method") == "POST": self.post()`.
So `GET /?format=json&_method=POST&creator=x` creates a factory actor on an
open factory, which Flask's GET never did before. FastAPI already behaved
this way, and an unauthenticated POST is open anyway. The new part is that
a link prefetcher or an `<img>` can now do it through Flask.
**Location:** `actingweb/interface/integrations/flask_integration.py:795`
**Recommendation:** call `_get_json_config()` directly in the JSON branch,
or drop `_method` there.

### V. `set_confirmed` edge cases
**Severity:** Low
**Description:**
- `attribute.py:74` ignores what `set_attr` returns. When the same value
  was already stored, a failed write still reads back as a match. Harmless
  for the current callers.
- `:84` compares the read-back with the unsanitized input, so a marker the
  backend sanitizes reads as a mismatch.
- `:71` `_ensure_loaded()` sits outside the try, so a DynamoDB query fault
  raises despite the docstring's "never raises". All four callers have
  loaded or marked the store first, so this is latent.
**Location:** `actingweb/attribute.py:71-85`
**Recommendation:** move `_ensure_loaded` inside the try, and AND in the
write's result.

### W. `ActorInterface.modify_creator` does not unvouch, and the docs do not say so
**Severity:** Low
**Description:** `actingweb/interface/actor_interface.py:404` calls
`return self._core_actor.modify(creator=new_creator)`. A consumer route that
feeds user input into it keeps the vouch for an address nobody proved.
**Location:** `actingweb/interface/actor_interface.py:404`
**Recommendation:** document it as an application assertion, like
`auth_method="app"`, in the migration guide's "Changing the creator"
section.

### X. The `env-example` test passes if the key is deleted
**Severity:** Low
**Description:** `tests/test_demo_example.py:209`
`pytest.param(_env_example_value("OPEN_FACTORY"), True, id="env-example")`.
A missing key yields None, the test takes the unset branch, and it expects
True.
**Location:** `tests/test_demo_example.py:209`
**Recommendation:** assert that the value is not None in a separate check.

### Notes (not findings)

- Repeated from the deferred todo: the duplicate tombstone and the second
  `actor_deleted` on a resumed replacement (`oauth2.py:1820-1821`), the lost
  successor mapping (`:1855`), the summary re-reads (`:1810`, `:1875`) and
  the missing type hints (`actor.py:601`).
- Decisions already taken:
  - the SPA paths keep their own `adopt_actor` call (`oauth2_spa.py:969`,
    `:1147`), declined in Iterations entry 5;
  - provider-bearer API requests run adoption (`oauth2.py:1096`), per the
    plan's decision to put the rule in the shared lookup.
- Unverified (outside voice):
  - a rename racing a clean could end vouched under an unproven address,
    but only if the PUT was authenticated before the passphrase rotated;
  - a row-less OAuth2 system actor with data plus a marker fault would
    make the rollback wipe the global OAuth2 state.

  Neither was shown reachable.
- The benchmarks do not create the attribute tables on a fresh container
  (see Automated Check Results).

## Overall Assessment

The batch delivers what entries 8-13 claim. The strict revoke confirms
deletes on DynamoDB. The marker is confirmed at creation, at the clean, at
the rename and in the backfill. The backfill ships in the wheel, and the demo
and the docs now tell an upgrading operator what happens. Every check in the
Full tier is green on both backends, `make test-all-parallel` included, and
the security review found nothing.

It is not ready to release yet. The rename handler, which entry 10
rewrote, has three High defects:
- **M:** a squatter can downgrade `factory` to `creator_changed` and plant
  data in the victim's account. No fault is needed.
- **N:** a failed `modify` leaves the owner's actor marked for a clean.
- **O:** an unloaded bucket bypasses the pin and can delete the marker.

All three fit in one handler and its test file. P-S are worth taking in the
same iteration, especially the doc wording in S, which misstates which
actors the upgrade touches. T-X can join the deferred follow-ups todo.
