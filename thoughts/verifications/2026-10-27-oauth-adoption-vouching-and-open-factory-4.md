# Verification: vouched actors, clean-slate adoption on OAuth login, a closable factory, and SPA `prompt` (fourth run)

**Date:** 2026-10-27
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md (Part 1); thoughts/research/2026-10-27-creator-rename-and-create-rollback-leave-wrong-vouch.md (this batch's bug record)
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; all of the work is uncommitted in the working tree)

This run checks the plan's third Iterations batch (entries 14-21, "after
verification ...-3.md") against the code. The earlier runs' findings are not
repeated unless this batch changed them.

## Automated Check Results

- **Browser QA:** not re-run. The batch changed no rendered page:
  - the rename is an API;
  - the Flask change is to a JSON response, covered by
    `test_json_get_never_creates_an_actor`;
  - the rest is library code and docs.

  The first run's walk of the demo still stands for the HTML pages.
- **Second opinion:**
  - **outside-voice:** Codex (`codex exec -s read-only`, unsandboxed; the
    first attempt hung on stdin, the second finished) plus a fresh-context
    Claude. Nine findings and four unverified notes.
  - **`/code-review high`:** ten findings. Two are already in the
    follow-ups todo (duplicate `actor_deleted`, type hints). The rest are
    folded in below.
  - **Security review (built-in):** no findings above the confidence bar.
    Its nearest miss, the stored-email exemption resting on an unverified
    provider email, is under Notes.
  - I re-read the code for every High and Medium finding, and each one held.
- `ruff check actingweb tests`: pass, "All checks passed!"
- `ruff format --check actingweb tests`: pass, 420 files already formatted.
- `pyright actingweb tests`: pass, 0 errors, 0 warnings, 0 informations.
- `tests/integration/verify_groups.py`: pass, all 50 groups documented.
- **DynamoDB suite** (`make test-all-parallel`): pass, 4021 passed, 31 skipped.
- **PostgreSQL suite** (`make test-all-parallel` with the Full tier's PG
  environment): pass, 3912 passed, 140 skipped.
- **Docs build** (`sphinx-build -W`, `.claude/**` excluded locally): pass,
  "build succeeded".
- **Benchmarks:** not re-run. Nothing changed since the iteration's run (17
  passed; medians in the plan's batch note), and that run already followed
  the last code change.

## Phase Verification

### Entry 14: the creator rename (M, N, O, T) - ISSUES FOUND

**Changes verified:**
- `actingweb/handlers/trust.py`:
  - `put` calls `_change_creator` before it writes `trustee_root`, and
    returns when the helper returns False. Matches.
  - The helper answers 500 when `store.loaded` is False. Matches.
  - `previous_marker not in REPLACE_AUTH_METHODS` keeps `factory`. Matches.
  - `modify` is wrapped in try/except; on failure the marker is restored
    with `set_confirmed`, a failed restore is logged, and the response is
    500. Matches.
- The restore trusts a failed `modify` to mean "not written". A lost ack
  breaks that assumption (Issue AC).

**Tests verified:** `TestRenameFaults`, five tests.
- Each failed with the pre-fix `trust.py` and passes now.
- Not covered:
  - the 500 half of T;
  - a legacy actor's restore (`previous_marker=None`);
  - a restore that fails;
  - a write that commits and then raises (Issue AJ).

### Entry 15: `set_confirmed` (V) - VERIFIED

- `actingweb/attribute.py`:
  - `None` deletes and then confirms the row is gone with a strict read;
  - a `set_attr` that answers False fails;
  - `_ensure_loaded` sits inside the try.
- **Tests:** two, each failing without the fix. Also exercised through the Q test.
- **Edge:** a restore with `previous_marker == ""` takes the write branch,
  the backend treats `""` as a delete, and the read-back finds no row. That
  logs a false ERROR and nothing else (Issue AL).

### Entry 16: conditional DynamoDB insert (P) - ISSUES FOUND

- `actingweb/db/dynamodb/actor.py`: `save(condition=Actor.id.does_not_exist())`.
  `ConditionalCheckFailedException` answers False; anything else is
  re-raised. It reuses the pattern in `db/dynamodb/property.py:587`. Matches.
- `actingweb/actor.py`: a failed rollback delete is logged. Matches.
- **Test:** `test_create_over_a_live_actor_whose_read_faults_leaves_it_intact`
  failed with the pre-fix backend and passes now.
- **CHANGELOG:** "the live row and its `_internal` bucket stay untouched" is
  not quite true, because `trustee_root` is still written to that bucket
  (Issue AE).
- **Callers:** none relies on the old overwrite.
  `ensure_oauth2_system_actor` now logs "Failed to create" when two
  processes race to create it first, where it used to overwrite the
  passphrase silently (Note).

### Entry 17: the clean confirms the `email_verified` clear (Q) - ISSUES FOUND

- `actingweb/oauth2.py`:
  - `clear_pending_email_verification` returns bool and deletes the flag
    last, with `set_confirmed`;
  - the clean path returns None when that fails.
- Matches. The same class of write remains on the emailed-link path
  (Issue Z).
- **Tests:** the fault test failed without the fix; the mock tests were
  updated and one was added.

### Entry 18: backfill (R) - VERIFIED (doc gap)

- `mark_actors_vouched.py`:
  - a `fetch()` exception raises `ActorListUnavailable`;
  - after errors, the closing line says to re-run without `--start-after`.
- Matches. Both tests failed without the fix.
- The docs promise a resume value "when a run is interrupted", but an
  interrupted run never reaches the closing line (Issue AI).

### Entry 19: docs (S, W) - ISSUES FOUND

- The pre-3.16 wording, the 400 qualifier, the 500 cases and the
  `modify_creator` docstring are in `CHANGELOG.rst`,
  `docs/migration/v3.16.rst`, `docs/guides/authentication.rst`,
  `actor_interface.py` and the tool docstring. Docs build clean.
- The `modify_creator` recipe added for W brings back Issue M for
  consumers (Issue AF).

### Entry 20: Flask JSON GET (U) - VERIFIED (Flask only)

- `flask_integration.py` calls `_get_json_config()` directly. The CORS
  headers are set inside `_get_json_config` (`factory.py:135-141`), so
  nothing is lost. Matches.
- FastAPI still runs `handler.get` (`fastapi_integration.py:1630`), and that
  honours `_method=POST` (Issue AG).

### Entry 21: env-example test (X) - VERIFIED

- `tests/test_demo_example.py`: `test_demo_env_example_sets_open_factory`.

## Security property demonstrated

The claim: every write that decides a vouch is confirmed. It is pinned for
the rename by these tests:
- `TestRenameFaults::test_failed_modify_answers_500_and_restores_the_marker[raises|false]`
  asserts 500, `row.creator == owner` and
  `auth_method == "google_oauth2"`;
- `test_unreadable_internal_bucket_answers_500` makes the same three
  assertions;
- `test_factory_actor_keeps_its_marker` asserts `auth_method == "factory"`.

For the clean, `test_clean_fails_when_the_pending_flag_is_not_cleared`
asserts that the sign-in returns None and that `email_verified` is still
`"false"`.

The claim does not yet hold for two writes:
- the emailed link's `email_verified = "true"` (Issue Z);
- a rename whose write commits but whose ack is lost (Issue AC).

## Thoughts bookkeeping

- The follow-ups todo gained this batch's two deferrals: `Actor.create`
  answering True when nothing was created, and the benchmark tables. The
  `INDEX.md` row is unchanged and still describes the file.
- The plan's Decisions entry for the rename carries `[Updated 2026-10-27]`.
- **Consumer message:** the plan has none.

## Previous Verification

**Previous:** thoughts/verifications/2026-10-27-oauth-adoption-vouching-and-open-factory-3.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| M. `factory` downgraded by a rename | Fixed at the endpoint; the docs recipe reintroduces it for consumers | `trust.py` `_change_creator`; Issue AF |
| N. Failed `modify` leaves `creator_changed` / answers 204 | Fixed, except a lost ack | `TestRenameFaults`; Issue AC |
| O. Rename on an unloaded bucket | Fixed | `test_unreadable_internal_bucket_answers_500` |
| P. Create rollback can wipe a live actor (DynamoDB) | Fixed (conditional insert); the `trustee_root` write and full-delete rollback remain | entry 16; Issues AD, AE |
| Q. `email_verified` clear unconfirmed on the clean | Fixed on the clean; open on the emailed link | entry 17; Issue Z |
| R. Backfill hint, DynamoDB list fault, exit 2 | Fixed; the interrupted-run hint is still promised but missing | entry 18; Issue AI |
| S. Doc claims | Fixed | entry 19 |
| T. `trustee_root` before a refusal | Fixed (400 tested; 500 untested) | entry 14; Issue AJ |
| U. Flask JSON GET honours `_method=POST` | Fixed on Flask; FastAPI unchanged | entry 20; Issue AG |
| V. `set_confirmed` edges | Fixed | entry 15 |
| W. `modify_creator` undocumented | Documented; the recipe needs the M rule | Issue AF |
| X. Env-example test | Fixed | entry 21 |

The previous run's Remaining Tasks:
- M-X were all taken (the owner chose all of them).
- The release-PR bump is still open.
- The triage outputs are still uncommitted.

## Remaining Tasks

- [ ] Decide on Issues Y-AC (`/iterate_plan`). Y changes how the lookup
      chooses among duplicate creators, which is a design question for the
      owner. Z, AA and AC are the remaining "unconfirmed write decides a vouch"
      shapes. AB is the filed todo item, now with a concrete consequence on
      the replace path.
- [ ] Issues AD-AM are Low: take them in the same iteration or add them to
      `thoughts/todo/adoption-fault-and-hygiene-followups.md`.
- [ ] Release PR:
  - the version bump in `pyproject.toml` and `actingweb/__init__.py`;
  - the `Unreleased` rename;
  - a `.. note::` pointing at `docs/migration/v3.16.rst`.

  The release number is still open: 3.16.0 in the tree, a major release per
  the owner.
- [ ] Commit the triage outputs with this work.

## Issues Found

### Y. Several factory actors for one victim split the victim's account across actors
**Severity:** Medium
**Description:** `unique_creator` is off by default and the factory is open
by default, so a squatter can `POST /` with `creator=victim@x` several times
(F1, F2, F3).
- `Actor.get_from_creator` picks the lowest id
  (`actor.py:337` `candidates.sort(key=lambda item: item.get("id", ""))`).
- The victim's first sign-in replaces F1. The successor check
  (`oauth2.py:1851` `successor.get_from_creator(creator) ... and is_vouched_actor(successor)`)
  lands on F2, which is unvouched, so a new V1 is created.
- The next sign-in picks the lowest of F2, F3 and V1. If that is F2, it is
  replaced and V2 is created.

The victim's sessions and data end up spread over V1, V2 and later actors.
Nothing is exposed to the squatter, but the account is fragmented with no
error, for as long as factory siblings remain.
**Location:** `actingweb/oauth2.py:1846-1858`; `actingweb/actor.py:337`
**Recommendation:** the owner decides:
- the lookup prefers a vouched candidate among duplicates;
- the replace path replaces every unvouched sibling with the same creator,
  then creates one successor.

This relates to `thoughts/todo/creator-uniqueness-not-enforced.md`, but it
is a separate, reachable path.

### Z. The emailed link's `email_verified = "true"` is not confirmed
**Severity:** Medium
**Description:** `actingweb/handlers/oauth_email.py:232`
`actor.store.email_verified = "true"` is a plain write. The token fields
and the index row are cleared right after it, at `:233-238`.

If PostgreSQL rejects the write, the user is told the address is verified,
but the actor stays `email_verified == "false"`, which is unvouched, and
the only retry link is gone. Their next provider sign-in cleans the actor
again, and does so on every sign-in after that. This is the class Issue Q
fixed on the clean path.
**Location:** `actingweb/handlers/oauth_email.py:231-238`
**Recommendation:** `if not actor.store.set_confirmed("email_verified", "true"): return self._verification_error(500, "Internal error")`
before the token and index are cleared.

### AA. A clean after a provider sign-in keeps the previous creator's provider tokens
**Severity:** Medium
**Description:** `actingweb/oauth2.py:1895` `if provider_name is None:`
clears `oauth_token`, `oauth_refresh_token`, `oauth_token_expiry` and
`oauth_token_timestamp` only on the emailed-link path. On a provider
sign-in the callback overwrites the access token when it has one, and the
refresh token only when a new one was issued.

Take a squatter who renamed their own Google-signed actor to the victim.
The victim's Google sign-in often returns no refresh token, and the native
JWT-bearer grant writes no access token at all. So the cleaned actor keeps
the squatter's refresh token, and application code calling the provider for
the victim reaches the squatter's account.
**Location:** `actingweb/oauth2.py:1894-1904`
**Recommendation:** clear the four fields on every clean. The caller writes
the new tokens afterwards.

### AB. On the replace path, a successor whose insert failed is returned as an actor
**Severity:** Medium
**Description:** this is the filed todo item ("`Actor.create` answers True
when nothing was created", `actor.py:499` `return True`), with a concrete
consequence:
- On PostgreSQL, a caught fault on the successor's INSERT makes
  `DbActor.create` return False.
- `Actor.create` skips the marker and returns True, and
  `ActorInterface.create` does not raise.
- `_adopt_actor` has already deleted the old actor. It returns the phantom
  successor and fires `actor_adopted`, and the callback issues tokens for an
  id with no row.
**Location:** `actingweb/actor.py:497-499`; `actingweb/oauth2.py:1856`
**Recommendation:** fix the todo item now: return False when `created` is
False, and skip the hook. The replace path then fails closed, and the
tombstone makes the next sign-in resume.

### AC. A rename whose write commits but whose ack is lost restores the vouched marker
**Severity:** Medium
**Description:** `actingweb/handlers/trust.py` `changed = myself.modify(creator=creator)`,
followed by `if unvouch and not store.set_confirmed("auth_method", previous_marker):`.
The restore runs on any exception or False. A DynamoDB `save()` that times
out after committing raises, and a PostgreSQL commit error after the server
committed returns False.

Storage then holds the new, unproven creator under the old vouching marker:
the Issue 11 squat. The client gets a 500 and may retry. This needs a lost
ack, which is rare.
**Location:** `actingweb/handlers/trust.py` (`_change_creator`, the restore after `modify`)
**Recommendation:** before restoring, re-read the actor row strictly
(`get_actor(config).get(actor_id)`). Restore only when the stored creator is
confirmed unchanged; otherwise leave `creator_changed`.

### AD. The create rollback deletes everything under the id, not just the new row
**Severity:** Low
**Description:** `actingweb/actor.py:478` `if not self.delete(notify_peers=False):`
runs the full delete: buckets, trusts, properties and a tombstone. For a
fixed id whose buckets exist before its row (the OAuth2 system actor
`oauth2_system_actor`, `system_actor.py:58-62`), a marker fault right after
the row insert would wipe the global OAuth2 state. Nobody showed that a
system actor can exist with buckets but no row, so this stays Low.
**Location:** `actingweb/actor.py:470-483`
**Recommendation:** roll back only the row (`self.handle.delete()`) and the
marker, not the actor's data.

### AE. A refused create still writes `trustee_root` into the live actor
**Severity:** Low
**Description:** `actingweb/actor.py:459-465` `self.store.trustee_root = trustee_root`
has no `created` guard. On a taken id the store is the live actor's. This
contradicts the new CHANGELOG sentence "the live row and its `_internal`
bucket stay untouched" (`CHANGELOG.rst`, the FIXED entry). No library
caller passes both `actor_id` and `trustee_root`.
**Location:** `actingweb/actor.py:458-465`
**Recommendation:** guard the write with `created`.

### AF. The `modify_creator` recipe in the docs reintroduces Issue M
**Severity:** Low
**Description:** `docs/migration/v3.16.rst:263-265`, the CHANGELOG sentence,
and the `modify_creator` docstring ("as `PUT /<id>/trust/trustee` does")
tell consumers to write `creator_changed` before `modify_creator`. That
skips the `REPLACE_AUTH_METHODS` rule, so a `factory` actor is downgraded,
and it skips the restore on failure.
**Location:** `docs/migration/v3.16.rst:258-266`; `actingweb/interface/actor_interface.py:398-402`; `CHANGELOG.rst` (the rename entry)
**Recommendation:** offer one library call that does what the endpoint does
(for example `ActorInterface.modify_creator(new, *, unvouch=True)`, sharing
`_change_creator`'s rules), or add the `factory` check and the restore to
the recipe.

### AG. FastAPI's factory GET still honours `_method=POST`
**Severity:** Low
**Description:** `actingweb/handlers/factory.py:146`
`if self.request.get("_method") == "POST": self.post()` is reached from
FastAPI's GET (`fastapi_integration.py:1630`). So an `<img>` can create a
`factory` actor on an open factory. The behaviour is old, the actor is
replaced at the victim's sign-in, and an anonymous POST works anyway.
Entry 20 calls FastAPI's behaviour the reference, but FastAPI is the side
that still has the problem.
**Location:** `actingweb/handlers/factory.py:145-148`
**Recommendation:** check `_wants_json()` before `_method` in `get()`, or
drop `_method` on GET.

### AH. A clean in place never refreshes `store.email`
**Severity:** Low
**Description:** `actingweb/oauth2.py:1905-1917` writes the marker and the
`adopted_*` fields, but never `email`. `Actor.get` copies `store.email` into
the creator when `force_email_prop_as_creator` is on (`actor.py:275-277`).
If a squatter renamed with the pin off and the pin is turned on later,
every load hands the victim's cleaned actor back to the squatter's address.
That needs a config change between the two events.
**Location:** `actingweb/oauth2.py:1905-1917`
**Recommendation:** on a clean, set `store.email` from the proven identifier
when it is an address, or delete it.

### AI. The resume hint for an interrupted backfill is never printed
**Severity:** Low
**Description:** `docs/migration/v3.16.rst:161-162` says the closing line
"gives the value for `--start-after` when a run is interrupted". The line
is only printed when the run finishes (`mark_actors_vouched.py:142-150`).
Skipped actors log nothing, so the last logged id can trail the real
position. Re-running is idempotent, so the harm is confusion, not data.
**Location:** `actingweb/maintenance/mark_actors_vouched.py:142-150`; `docs/migration/v3.16.rst:161`
**Recommendation:** log the cursor every N actors, or tell operators to
re-run without `--start-after` after an interruption.

### AJ. Rename failure branches without a test
**Severity:** Low
**Description:** `tests/test_trust_creator_rename.py` covers the 400 for
`trustee_root` (`test_refused_rename_does_not_write_trustee_root`), but not:
- the 500 causes;
- a legacy actor's restore (`previous_marker=None`, the delete branch of
  `set_confirmed`);
- a restore that fails.
**Location:** `tests/test_trust_creator_rename.py:175-190`
**Recommendation:** parametrize the `trustee_root` test over the 500 causes;
add a legacy-actor restore case.

### AK. PostgreSQL `modify` changes the in-memory handle before the UPDATE
**Severity:** Low
**Description:** `actingweb/db/postgresql/actor.py:198`
`self.handle["creator"] = creator`, and `:204` for the passphrase, run
before the UPDATE. A `rowcount != 1` rollback then returns False with the
handle already changed, which contradicts `Actor.modify`'s docstring that
in-memory values change only after success. DynamoDB sets the model
attribute before `save()` raises, too.
**Location:** `actingweb/db/postgresql/actor.py:193-205`
**Recommendation:** set the handle after the commit succeeds.

### AL. Small leftovers
**Severity:** Low
**Description:**
- `actingweb/oauth2.py:1778`: the `clear_pending_email_verification` call in
  the vouched branch can never act, because `is_vouched_actor` already
  requires `email_verified != "false"`. It is dead code.
- A restore with `previous_marker == ""` logs a false ERROR (entry 15 edge).
**Location:** `actingweb/oauth2.py:1776-1779`; `actingweb/handlers/trust.py` (the restore)
**Recommendation:** drop the dead call; treat `""` as None in the restore.

### AM. The factory form's OAuth login creates an actor that is replaced at once
**Severity:** Low
**Description:** with `www_auth="oauth"`, typing an email into the factory
form creates a `factory` actor (`factory.py:280` `auth_method="factory"`).
The OAuth callback then replaces it straight away. Every first login of
this kind fires `actor_created` twice and `actor_deleted` once.

This follows from the plan's rule, so it is not a regression. But a
consumer's provisioning in `actor_created` runs twice, and the migration
guide does not say so.
**Location:** `actingweb/handlers/factory.py:268-283`
**Recommendation:** document it in `docs/migration/v3.16.rst`, or send that
form straight to OAuth with a login hint instead of creating an actor.

### Notes (not findings)

- **The stored-email exemption** trusts `store.email`, which a provider can
  write from an unverified claim (`oauth2.py:1633`). This is the known,
  out-of-scope weakness (email claims without `email_verified`). With the
  pin on, `Actor.get` already copies that email into the creator, so the
  exemption does not widen it. The security review could not chain it into
  an attack under either config.
- **The OAuth2 system actor:** two processes racing to create it now log
  ERROR "Failed to create" instead of silently overwriting the passphrase.
  That is harmless; DEBUG would be enough.
- **`test_json_get_never_creates_an_actor`** proves absence through
  DynamoDB's eventually consistent creator index. That is fine on DynamoDB
  Local, but weak as a negative check.
- **Deferred, unchanged:** the duplicate `actor_deleted` on a resumed
  replacement and the missing type hints. Both are in the follow-ups todo.
- **Not shown reachable:** an `email_unverified` actor renamed to another
  address is cleaned rather than replaced. That was decided earlier: the
  email form requires a provider session.

## Overall Assessment

Entries 14-21 do what they claim. Every issue from the third run is fixed at
the place it was reported: the rename, the attribute layer, DynamoDB's
create, the clean, the backfill, Flask and the docs. Each fix has a test that
failed without it. The full tier is green on both backends, and the security
review found nothing.

Each fix also exposed a neighbouring case of the same shape. These are not
regressions, but they are what is left before the release:
- the emailed link's flag (Z);
- provider tokens on a clean (AA);
- the phantom successor (AB);
- a lost ack on the rename (AC);
- the sibling-squat split (Y), a design question for the owner.

None lets a squatter into a victim's account without a backend fault,
except Y, which splits the victim's data rather than exposing it, and AA,
which leaves the squatter's provider token in the victim's actor. I
recommend taking Z, AA and AB in one more iteration. Y needs the owner's
choice of rule. AC and the Low items can go into the follow-ups todo if the
release cannot wait.
