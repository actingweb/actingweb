# Verification: vouched actors, clean-slate adoption, a closable factory, SPA `prompt` (fifth run)

**Date:** 2026-10-27
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; all work uncommitted)

Scope: the plan's Iterations entries 22-30, which followed the fourth
verification, plus the release-notes correction for MCP-created accounts made
after it. Phases 1-3 and entries 1-21 were verified by the earlier runs; the
full tier below re-checks all of them.

## Automated Check Results

- **Browser QA:** N/A. Entries 22-30 change no page. Entry 28 removes the
  `_method=POST` override from the factory GET, and
  `tests/test_factory_open_switch.py::test_get_with_method_override_never_creates`
  pins that at the handler.
- **Second opinion:** the outside-voice agent ran two reviewers: Codex
  (`codex exec -s read-only`, run outside the sandbox) and a fresh-context
  Claude. Findings are folded in below, and one Codex "High" was downgraded
  to Low after checking the mechanism. `/code-review high` produced 10
  findings, also folded in. The security review found nothing at confidence 8
  or above; its dropped candidates are under Notes.
- `ruff check actingweb tests`: pass.
- `ruff format --check`: pass (421 files).
- `pyright actingweb tests`: 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: pass (50 groups).
- **DynamoDB** `make test-all-parallel`: **4034 passed, 31 skipped**, no
  failures (parallel run).
- **PostgreSQL** `make test-all-parallel`: **3925 passed, 140 skipped**, no
  failures (parallel run).
- `sphinx-build -W`, with `.claude/**` excluded locally: build succeeded.
- **Benchmarks** (`tests/performance -m benchmark`, run alone after a warm-up
  run of `tests/test_adoption_write_faults.py`): 17 passed. Medians: attribute
  read 0.78 ms, attribute write 0.98 ms, actor read 1.00 ms, actor create
  6.38 ms, actor delete 3.62 ms, trust list 1.10 ms, bulk property read 93 ms.
  They are in line with the fourth run: create 6.13 ms then, 6.38 ms now.

## Phase Verification

### Entry 22: sibling factory actors (Y) - ISSUES FOUND

**Changes verified:**
- `actor.py:305-318` `_candidate_vouched` reads `InternalStore` and treats an
  unreadable store as unvouched. `actor.py:359-362` sorts vouched candidates
  first, and the sort is stable, so the lowest id still wins within each group.
- `oauth2.py:1601` `is_vouched_store`; `is_vouched_actor` delegates to it.
- `oauth2.py:1717-1758` `_remove_for_replacement` and `:1761-1791`
  `_factory_siblings`. `:1909-1923` removes every `factory` sibling, and
  `:1929-1944` then reuses a vouched actor or creates the successor.
- The owner's rule holds. Only `REPLACE_AUTH_METHODS` siblings are deleted
  (`:1789`). Actors from before 3.16 (no marker) and `--include-factory`
  re-marked actors are never swept. The victim is excluded from its own
  sibling list (`exclude=actor_id`).

**Tests verified:**
- `tests/test_adoption_fourth_iteration.py::TestFactorySiblings`: two
  sign-ins give one id, and one actor remains for the creator. The lookup
  prefers a vouched actor over a lower-id unvouched one.
- `tests/test_oauth2_adoption.py::test_concurrent_successor_is_reused_not_duplicated`
  now expects the inert factory sibling to remain.

**Deviations:** none from the decision. Issues AN, AP and AQ are below.

### Entry 23: the emailed link confirms `email_verified` (Z) - VERIFIED

`oauth_email.py`: `set_confirmed("email_verified", "true")` runs before the
token is cleared, and a failure answers 500. Pinned by
`TestEmailedLink` in `tests/test_adoption_fourth_iteration.py`.

### Entry 24: clean in place clears provider tokens and sets `store.email` (AA, AH) - VERIFIED (partial by design)

`oauth2.py:1980-1991`. The four `oauth_token*` fields are cleared on every
clean, and `store.email` is set to the lowercased creator. These writes use
plain `setattr`, not `set_confirmed`, so a write fault is not detected;
see AV. The load-time rewrite under `force_email_prop_as_creator` is filed in
`thoughts/todo/adoption-fault-and-hygiene-followups.md`. Pinned by
`TestCleanInPlace`.

### Entry 25: `Actor.create` on a taken id (AB, AD, AE) - VERIFIED

- `actor.py:477-481`: returns False when `created` is False, with no marker,
  no `trustee_root` and no hook.
- `:485-504`: the marker is written first; a rollback removes only the row,
  and an exception during it is logged.
- `ActorInterface.create` raises (`actor_interface.py:147`).
- `system_actor.py:58-73` and `trust_type_registry.py:126-139` load the
  winner when they lose the race.
- Every in-tree caller handles False. `mcp.py:2429` fails the request; see AR.
- Pinned by `TestCreateOnATakenId` (3 tests).
- CHANGELOG has a CHANGED entry with **Behavior change:** and **Check:**.
  Migration item 4 states it.

### Entry 26: `modify_creator_unvouched` (AC, AF, AJ, AL) - VERIFIED

- `actor.py:530-595`. `original` is captured before `modify`, and the old
  marker is restored only when a fresh `get_actor(config).get()` shows the
  original creator. `previous_marker or None` turns an empty marker into a
  delete.
- `trust.py` `_change_creator` keeps the unloaded-store 500 and the pin 400,
  then calls the method. The code review notes the duplicated normalisation
  (AV).
- `ActorInterface.modify_creator(new, *, unvouch=False)` is in the docs
  recipe.
- Pinned by `TestCreatorChangeAck`, including the lost-ack case.

### Entry 27: backend `modify` on a failed save (AK) - VERIFIED, NO TEST

PostgreSQL `DbActor.modify` sets the handle after the commit. DynamoDB
restores creator and passphrase if `save()` raises. There is no test; this is
filed in the follow-ups todo.

### Entry 28: factory GET ignores `_method=POST` (AG) - VERIFIED

`factory.py:145-147`. Pinned by `test_get_with_method_override_never_creates`.
A stale comment at `flask_integration.py:804` still says `get()` honours the
override (AV).

### Entry 29: backfill progress line (AI) - ISSUES FOUND

`mark_actors_vouched.py:123-132` prints a line every 100 actors, but before
that actor is processed. See AO.

### Entry 30: factory-form OAuth login (AM) - VERIFIED

Migration item 2 documents `actor_created` firing twice and
`actor_deleted` once.

### After entry 30: MCP-created accounts in the release notes

A note from the actingweb_mcp session reported that Emm AI prod had 12 real
accounts the MCP OAuth server created in 3.15.1 with no `auth_method`. They
have now been marked `operator` there. In this tree:
- `oauth2_server.py:820-835` delegates to
  `lookup_or_create_actor_by_identifier`, with the provider from the token
  exchange (`:378`).
- New actors get `f"{provider.name}_oauth2"` (`oauth2.py:1630`).

The old wording, "created … without a provider sign-in", was wrong for those
accounts. Migration item 1 (consumer message, as it now reads):

> **An actor created before 3.16 with no marker is cleaned at its first
> sign-in after the upgrade.** … **An application whose users signed up
> through an MCP connector must run it:** the MCP OAuth server proved those
> addresses through the provider but never wrote a marker, so they are real
> accounts that would otherwise be cleaned.

The CHANGELOG Unreleased entry and the two-populations table say the same.
The docs build passes.

## Security property demonstrated

A squatter's `factory` actors never receive the owner's sign-in, and they are
all removed by it:
`TestFactorySiblings::test_one_sign_in_replaces_every_factory_sibling`
asserts that two sign-ins return the same id and that `get_by_creator`
then lists only that id. The earlier runs' properties (rotation, strict
revoke, purge re-read, marker confirmation) are still pinned by the tests
named in the fourth verification, and the full tier passes them on both
backends.

## Thoughts bookkeeping

- The plan's two source todos (`oauth-adoption-of-unvouched-actors-and-open-factory.md`,
  `spa-authorize-prompt.md`) are deleted, and they have no `INDEX.md` rows.
- Every deferral has a file. `adoption-fault-and-hygiene-followups.md` (with
  its INDEX row) covers H-L, the load-time rewrite and the AK test.
  `spanned-list-items.md` and `creator-uniqueness-not-enforced.md` exist.
- Research note for entries 22 and 25:
  `thoughts/research/2026-10-27-sibling-squats-and-create-on-taken-id.md`.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-4.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| Y: sibling factory squats split the account | Fixed (owner's rule: factory siblings only) | Entry 22; `oauth2.py:1909-1923`, `actor.py:359-362` |
| Z: emailed link's flag unconfirmed | Fixed | Entry 23 |
| AA: clean keeps provider tokens | Fixed | Entry 24, `oauth2.py:1980-1986` |
| AB: phantom successor | Fixed | Entry 25, `actor.py:477-481` |
| AC: lost ack restores marker | Fixed | Entry 26, `actor.py:578-594` |
| AD: rollback runs a full delete | Fixed | Entry 25, `actor.py:494-498` |
| AE: `trustee_root` written on a refused create | Fixed | Entry 25 |
| AF: docs recipe reintroduces M | Fixed | Entry 26, `modify_creator(..., unvouch=True)` |
| AG: FastAPI GET honours `_method=POST` | Fixed | Entry 28 |
| AH: clean doesn't refresh `store.email` | Fixed at the clean; the load-time rewrite is filed | Entry 24; follow-ups todo |
| AI: no resume hint | Fixed, but the hint is off by one | Entry 29; AO |
| AJ: rename branches untested | Fixed | `TestCreatorChangeAck` |
| AK: PostgreSQL `modify` mutates the handle first | Fixed, no test (filed) | Entry 27 |
| AL: dead call, false log on `""` | Fixed | Entry 26 |
| AM: factory-form login creates and replaces | Documented | Entry 30, migration item 2 |

## Remaining Tasks

- [ ] AN, AO and AP before the release; the rest can go to the follow-ups todo.
- [ ] Release PR: the version bump, the `Unreleased` rename and the
  `.. note::` pointing at the migration guide (decide the major vs 3.16
  numbering there).
- [ ] Emm AI prod: one unmarked actor, `2f4c5bea…` (creator `cr…@creator`,
  empty `_internal`, created 2026-10-18). It looks like a factory actor. The
  owner decides whether to leave, mark or delete it.

## Issues Found

### AN. The successor step strands an owner's unvouched, non-factory actor
**Severity:** Medium
**Description:** After the factory actors are removed, the successor check
reuses a remaining actor only if it is vouched:
`oauth2.py:1930-1934`, "`successor.get_from_creator(creator) and … is_vouched_actor(successor)`".
An owner's actor from before 3.16 (no marker, not yet backfilled), or one
marked `email_unverified` or `creator_changed`, is unvouched but not
`factory`. So a new actor is created beside it. From then on
`get_from_creator` prefers the new vouched actor, and the owner's actor,
with all its data, is never resolved again.
**Scenario:** Alice owns legacy actor `b…`. A squatter POSTs `/` with her
address and gets `a…`. Neither is vouched, so the lower id `a…` is picked and
replaced, and Alice lands in an empty new actor. Whether it happens depends
only on the id order, so it is about a coin flip for every un-backfilled
account. The owner chose "other unvouched siblings are cleaned in place if a
sign-in picks them", and this path picks none.
**Location:** `actingweb/oauth2.py:1929-1944`, `actingweb/actor.py:359-362`
**Recommendation:** either order `factory` candidates last in
`get_from_creator` (vouched, then other unvouched, then `factory`), so the
owner's actor is the one cleaned; or, in the successor step, clean a
remaining non-factory unvouched actor in place instead of creating one. The
first is one sort key and also fixes the `factory.py:260` redirect.

### AO. The backfill's resume hint skips one actor
**Severity:** Medium
**Description:** `mark_actors_vouched.py:123-132` prints "resume with
`--start-after {actor_id}`" before that actor is read and marked. `:113`
skips ids `<= start_after`. A run killed while marking the 100th actor
resumes past it, and that real account stays unmarked, so its owner's next
sign-in cleans it.
**Location:** `actingweb/maintenance/mark_actors_vouched.py:123-132`
**Recommendation:** print the line after the actor is handled, or name the
previous id. Add a test that resumes from the printed id and checks that the
actor is marked.

### AP. The sibling sweep reads faults as "no sibling", and runs after the victim is gone
**Severity:** Medium
**Description:**
- PostgreSQL `get_by_creator` answers a fault with None
  (`db/postgresql/actor.py:105-107`), which `oauth2.py:1775` reads as no
  siblings.
- Both backends' `get()` answer a fault with None, which `:1780-1781`
  ("`if not sibling.id: continue  # gone since the index listed it`") reads
  as already deleted.
- The scan also runs only after the victim was removed (`:1900-1911`). A
  marker read that fails closed leaves the owner with no actor until the
  fault clears.

Under a database blip, a factory sibling survives. It is inert, because a
vouched successor exists and wins the lookup, but the CHANGELOG promises
that every factory sibling is deleted.
**Location:** `actingweb/oauth2.py:1761-1791`, `:1900-1911`
**Recommendation:** run `_factory_siblings` before any removal. Treat a None
list (strict read) or a listed id that does not load as a fault, and return
None. The victim's tombstone already lets the next sign-in resume.

### AQ. The migration guide contradicts itself on siblings
**Severity:** Low
**Description:** `docs/migration/v3.16.rst:301`, "Sibling actors that share a
creator … are not touched", contradicts item 2, "deletes every other
`factory` actor with the same creator".
**Recommendation:** limit `:301` to non-`factory` siblings, as CHANGELOG.rst
does.

### AR. The MCP bridge fails a request that lost the create race
**Severity:** Low
**Description:** `handlers/mcp.py:2429-2443` returns None when `create`
answers False. Since entry 25 that includes "another request created this id
first". The two system-actor callers reload the winner in that case; this one
fails the request.
**Recommendation:** reload `Actor(actor_id)` on False, as `system_actor.py:67`
does.

### AS. A clean in place keeps `trustee_root`
**Severity:** Low
**Description:** The clean clears the provider tokens (`oauth2.py:1980-1986`)
but not `trustee_root`, which the previous creator set through the factory
body or `PUT /<id>/trust/trustee`. After adoption the actor still publishes
that URL as its trustee root.
**Recommendation:** clear `trustee_root` with the `oauth_*` fields.

### AT. A vouched actor that is mid-deletion is returned without a tombstone check
**Severity:** Low
**Description:** The vouched branch (`oauth2.py:1855-1861`) and the successor
reuse (`:1929-1936`) skip `get_deletion_status`. `Actor.delete` wipes
`_internal` second to last (`actor.py:665`), so a DELETE that stalls on peer
calls leaves a vouched marker. Because the lookup now sorts vouched actors
first, that actor wins it. The vouched branch behaved this way before 3.16;
the reuse is new.
**Recommendation:** skip, or finish, a DELETED candidate in both places.

### AU. `create` returning False leaves the object bound to the other actor
**Severity:** Low
**Description:** `actor.py:445-475` binds `id`, `store` and `property` to the
caller's id before `:477` returns False. On PostgreSQL the handle still
points at the existing row, while DynamoDB clears it. No in-tree caller keeps
the object. In addition, `:469-471` `mark_empty()` runs for a fixed id that
can own older buckets.
**Recommendation:** reset `id`, `store` and `handle` before returning False,
and skip `mark_empty()` when `actor_id` was supplied.

### AV. Small leftovers
**Severity:** Low
- `flask_integration.py:804`: a stale comment ("get() would honour
  `_method=POST`").
- `oauth2.py:1980-1991`: the token clears and `store.email` are plain
  `setattr`, unlike the marker, so a write fault goes undetected.
- `trust.py` `_change_creator` repeats the normalisation and own-email check
  that `modify_creator_unvouched` does.
- `actor_adopted` and the adoption log record only the victim's id, not the
  swept siblings (`oauth2.py:1944`).
- `system_actor.py:70-88` returns the id after a failed create that nobody
  else won. `trust_type_registry.py` returns None in the same case.
- The sweep does not re-read each sibling's marker just before deleting it.
  The only window is running the backfill with `--include-factory` while
  serving, so the guide should say not to do that. This is Codex's "High",
  downgraded after checking the mechanism.

### Notes (not findings)

- **Hooks receiving `reason=`:** the code review flags that a hook written as
  `def on_deleted(actor):` raises TypeError. The migration guide
  (`v3.16.rst:233-240`) already tells consumers to accept `**kwargs`.
  Accepted.
- **The emailed link cleans an `email_unverified` actor,** and a mail scanner
  can prefetch it. That is by design: the CHANGELOG says the link ends the
  sessions of the actor it verifies, and a prefetch gives an attacker nothing
  a click wouldn't.
- **FastAPI renders a factory 400 as 200:** older than 3.16, unchanged.
- **Already filed, not repeated:** the duplicate tombstone write in the
  replace path and the missing type hints (follow-ups todo).
- **Security review, dropped at confidence 4:** an `email_unverified` actor
  renamed to a victim's address and then verified through the attacker's own
  link. This is blocked by default, because the email form needs
  `force_email_prop_as_creator`, and the pin refuses that rename. Cheap
  hardening: clear `email_verification_token` in `modify_creator_unvouched`.

## Overall Assessment

Entries 22-30 do what they claim. Every issue from the fourth run is fixed or
documented, each fix has a test that failed without it (AK excepted, filed),
and the full tier is green on both backends. The security review found
nothing at confidence 8 or above. The release notes now tell an application
with MCP sign-ups to backfill before deploying. That instruction came from a
production census.

Three issues should land before the release:
- **AN** lets a single `POST /` strand a pre-3.16 owner's data, about half
  the time, for every account not yet backfilled. The backfill avoids it,
  but the rule should not depend on it.
- **AO** makes the backfill's own resume hint skip an actor.
- **AP** breaks the "every factory sibling" promise under a read fault.

AN and AO are each a few lines. The Low items can go into the follow-ups
todo if the release cannot wait.
