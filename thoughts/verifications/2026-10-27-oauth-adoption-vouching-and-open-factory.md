# Verification: vouched actors, clean-slate adoption on OAuth login, a closable factory, and SPA `prompt`

**Date:** 2026-10-27
**Plan:** thoughts/plans/2026-10-26-oauth-adoption-vouching-and-open-factory.md
**Research:** thoughts/research/2026-10-26-v3.16-scope-oauth-adoption-vouching-and-spanned-list-items.md (Part 1); thoughts/research/2026-10-26-inbound-triage-factory-squat-list-item-size-spa-prompt.md
**Branch:** release/3.16.0-oauth-adoption-vouching
**Commit:** 52abce6 (base; every change is uncommitted in the working tree)

No feature document; the Success Measures section is omitted. First
verification of this plan.

## Automated Check Results

- **Browser QA:** Ran, provider: gstack browse (headless Chromium), against
  the demo app started with `OPEN_FACTORY=false` and no OAuth (no
  `examples/demo/.env` exists, so no login). Findings: one high that turned
  out to be pre-existing and outside this plan (`GET /?format=json` on Flask
  renders HTML, Issue 12), one low (the error page's "Possible Causes" list
  is generic, Issue 13). Main and edge paths below.
- **Second opinion:** outside-voice agent, providers codex (`codex exec -s
  read-only`, unsandboxed) and a fresh-context Claude; built-in
  `/code-review high` (forked); built-in security review (sub-task plus a
  false-positive filter). Findings folded into Issues Found with their
  provider named.
- `ruff check actingweb tests`: pass, "All checks passed!"
- `ruff format --check actingweb tests`: pass, 416 files already formatted
- `pyright actingweb tests`: pass, 0 errors, 0 warnings, 0 informations
- `tests/integration/verify_groups.py`: pass, all 50 groups documented
- Full suite, DynamoDB (`pytest tests/ -n auto --dist loadgroup -p
  no:rerunfailures`, parallel run, DynamoDB Local `:8001`): **3977 passed,
  31 skipped**, 0 failed
- Full suite, PostgreSQL (same command with `DATABASE_BACKEND=postgresql
  PG_DB_PORT=5433 ...`, parallel run): **3868 passed, 140 skipped**, 0 failed
- `sphinx-build -W --keep-going ...` verbatim: fails locally with 2467
  "duplicate object description" warnings, all from sibling worktrees under
  `.claude/worktrees/` (not this change; CI has none). With
  `-D exclude_patterns=...,.claude/**` added: **exit 0**, no warnings.
- Phase 2's manual check, run now: demo app with `OPEN_FACTORY=false`,
  `curl -X POST -H 'Content-Type: application/json' -d
  '{"creator":"x@example.com"}' http://localhost:5000/` answered **403**
  with `{"error": true, "status_code": 403, "message": "Actor creation is
  disabled on this server (with_open_factory); sign in through OAuth
  instead"}`; a form post answered 403.
- Benchmarks: not run; the plan does not touch list storage or the attribute
  layer's read path.

## Phase Verification

### Phase 1: markers, the adoption rule, the backfill script - ISSUES FOUND

**Changes verified:**
- `actingweb/actor.py:432-438`: `auth_method` written only when `created`,
  before `actor_created` fires. Matches plan.
- `actingweb/actor.py:456-483`: `modify` returns the backend result and
  changes memory only after success. Matches plan.
- `actingweb/actor.py:485-524`: `delete(notify_peers=...)`, tombstone first,
  row last. Matches plan (see Issue 5 for what "row last" means on a retry).
- `actingweb/actor.py:1549-1607`: `purge_relationships` reads subscriptions
  first, removes trusts, subscriptions and peer trustees, re-reads both
  lists for `confirmed`, never returns a secret. Matches plan.
- `actingweb/oauth2.py:1573-1597`: `UNVOUCHED_AUTH_METHODS`,
  `REPLACE_AUTH_METHODS`, `is_vouched_actor`. Matches plan.
- `actingweb/oauth2.py:1672-1851`: `adopt_actor` / `_adopt_actor`. Replace
  path (`:1746-1792`) and clean path (`:1793-1828`) as planned; `provider=`
  instead of `provider_name=` (recorded deviation, acceptable).
- Adoption call sites: `handlers/oauth2_spa.py:975-977` and `:1148-1150`,
  `handlers/oauth2_callback.py:541-543`, `handlers/oauth_email.py:219-221`,
  `oauth2.py` lookup paths; `oauth2_server/oauth2_server.py` delegates to the
  authenticator. Pinned by
  `test_handlers_holding_an_existing_actor_call_adopt_actor`
  (`tests/test_oauth2_adoption.py:427`).
- `actingweb/handlers/oauth_email.py:493-501`: free-text branch is
  `create_only` with `auth_method="email_unverified"`. Matches plan.
- `actingweb/oauth2_server/token_manager.py:1507-1520`:
  `revoke_actor_tokens` shares `_revoke_matching_tokens`. Matches plan.
- `actingweb/db/postgresql/actor.py`: `modify` returns False on
  `rowcount != 1`; pinned by `test_postgres_zero_rows_is_failure`
  (`tests/test_actor_auth_method_marker.py:187`).
- `scripts/mark_actors_vouched.py:70-93`: flags as planned (see Issue 8).
- `actingweb/handlers/devtest.py:198-205`: timestamp guard. Not in the plan's
  Changes; recorded in its Implementation Notes with root cause (eight
  integration tests 500'd once every actor had an `_internal` bucket).
  Acceptable, the change is forced by the marker.

**Tests verified:** every file named under the phase's New Tests exists:
`tests/test_actor_auth_method_marker.py`, `tests/test_actor_purge_relationships.py`,
`tests/test_oauth2_adoption.py`, `tests/test_mark_actors_vouched.py`,
`tests/integration/test_factory_squat_adoption.py`. All pass on both backends.

**Security property demonstrated** (per the workflow addendum). Claimed: a
squatter's passphrase, planted `admin` trust secret and sessions stop working
at the owner's first login.
- `tests/integration/test_factory_squat_adoption.py:45`
  `test_login_replaces_the_squatted_actor`, against a real server. First it
  proves the exploit precondition: the planted secret as Bearer opens
  `/properties` (`assert before.status_code == 200, "the exploit
  precondition must be real"`). After the adoption:
  - `new_id != old_id`;
  - the squatter's basic auth gets 403/404 on the old id and 401/403 on the
    new id;
  - `Bearer PLANTED_SECRET` gets `status_code in (401, 403, 404)` on both
    ids;
  - `/trust` on the new actor is `[]`;
  - `auth_method_adopted_from == "factory"` and the new marker is
    `"google_oauth2"`.
- `tests/test_oauth2_adoption.py:169`
  `test_legacy_actor_keeps_id_and_data_loses_relationships`. It asserts:
  - `requests_mock.delete.assert_not_called()`;
  - `adopted.passphrase != "squatter-passphrase"`;
  - `not Trusts(...).fetch()`;
  - `not _spa_valid(config, token)`;
  - the prefilled property survives and is named in `property_names`.
- These pin the property on the **happy path, both backends**. They do not
  pin it under a backend fault: on PostgreSQL a caught read fault defeats it
  (Issues 1-3).

**Failure Scenarios (plan :487-511):**
- Rotation write fails, raise or False: `test_rotation_failure_changes_nothing`,
  `tests/test_oauth2_adoption.py:294` (parametrized over both shapes). Present.
- `Actor.delete` raises mid-wipe:
  `test_delete_failure_fails_closed_then_next_login_completes`, `:155`.
  Present, but it patches `Actor.delete` to raise **before** anything is
  removed, so it does not model a failure mid-wipe (Issue 5).
- In-place wipe unconfirmed:
  `test_unconfirmed_wipe_leaves_actor_unvouched_but_rotated`, `:309`. Present
  for a surviving row. Not covered: a re-read fault that returns `[]`
  (Issue 2).
- Two concurrent first logins: documented, no test, as the plan says. The
  `unique_creator` off case creates two successors (Issue 6).
- `new_token()` empty: `test_empty_token_aborts_before_any_write`, `:325`.
  Present.
- Peer unreachable, never contacted:
  `test_removes_everything_locally_without_network`
  (`tests/test_actor_purge_relationships.py:31`) and the
  `assert_not_called` above. Present.
- Hook raises: `test_a_raising_hook_undoes_nothing`, `:335`. Present.
- Devtest marker write: documented in `docs/reference/security.rst`, no test
  (as planned).

**Deviations from plan:**
- `provider=` in place of `provider_name=`. Acceptable, recorded.
- `ActorInterface.get_or_create` does not exist. Acceptable, recorded.
- The plan's line "the next proof event finds it and re-runs" holds only for
  a failure before `buckets.delete()`. After it, the retry takes the
  clean-in-place path (Issue 5). Concerning.

### Phase 2: `with_open_factory` and SPA `prompt` - VERIFIED (minor issues)

**Changes verified:**
- `actingweb/config.py`: `open_factory = True`.
- `actingweb/interface/app.py`: `_open_factory` and `with_open_factory`,
  stamped in both places.
- `actingweb/handlers/factory.py:215-233`: gate is the first statement of
  `post()` and runs before the body is parsed.
- `actingweb/handlers/factory.py:200-213`: shared `_refuse`.
- `actingweb/handlers/factory.py:294-307`: the duplicate-creator 403 uses
  `_refuse`.
- `flask_integration.py` and `fastapi_integration.py`: render
  `aw-root-failed.html` on 403.
- `oauth2.py`: `authorize_prompt_params` (Google override) and
  `create_authorization_url(prompt=...)`.
- `oauth2_spa.py:49`: `SPA_PROMPT_VALUES`, 400 on any other value, and
  `prompt_values` / `prompt_supported` in the config.
- `factory.py:103`: `prompt_values`.

**Tests verified:**
- `tests/test_factory_open_switch.py` (the builder tests live here, under
  `TestBuilder` at `:125`, not in `tests/test_actingweb_app.py`; acceptable).
- `tests/test_flask_factory_fallback.py:31`.
- `TestClosedFactoryFormFallback` in `tests/test_fastapi_template_response.py`.
- `TestSpaAuthorizePrompt` in `tests/test_oauth2_spa.py`.
- `tests/test_oauth2_authorization_url_prompt.py:24-37`.
- `tests/integration/test_factory_open_switch.py:7-30`, which runs on its own
  port fixture `closed_factory_app`.

**Failure Scenarios:**
- Form post with no OAuth gets a 403 page: `test_closed_factory_form_post_renders_error_page_with_403`.
- `prompt` to a provider that drops it: `test_github_drops_the_addition` and
  `test_apple_drops_the_addition`.
- Config without the attribute: `test_config_without_the_attribute_is_open`
  (`tests/test_factory_open_switch.py:101`).

All three are present.

**Manual verification:** the curl above, run during this verification. Pass.

**Deviations:** none concerning. Two small ones, Issues 9 and 10.

### Phase 3: documentation, changelog, migration guide - ISSUES FOUND

**Changes verified:**
- `CHANGELOG.rst` `Unreleased` has SECURITY, CHANGED and ADDED in the
  contract's order. `scripts/mark_actors_vouched.py` is named at
  `CHANGELOG.rst:44` and `:165`.
- `docs/migration/v3.16.rst` exists, has an index row, and gives the backfill
  commands at `:103-105`.
- The docs build is clean with `.claude/**` excluded.
- Demo `OPEN_FACTORY` (`examples/demo/application.py:81`) is pinned by
  `test_demo_example_open_factory_follows_env`.

**`thoughts/todo/` against the plan:**
- Both todos the plan closes, `oauth-adoption-of-unvouched-actors-and-open-factory.md`
  and `spa-authorize-prompt.md`, are deleted along with their `INDEX.md` rows.
- The plan has no Decisions Deferred, so no todo is owed.
- `spanned-list-items.md` is new (from the triage, for the second 3.16
  plan).
- `prop-list-key-prefix-scheme.md` gained a triage section. Both came from
  the triage research, not this plan's phases, and share the working tree
  (see Remaining Tasks).

**Consumer message:** the plan has none. Its Phase 3 is documentation only.
Nothing to quote.

**Issues:**
- `docs/reference/hooks-reference.rst:159` still gives `actor_deleted` as
  `func(actor: ActorInterface) -> None` although the replacement passes
  keyword arguments (Issue 4).
- `docs/reference/hooks-reference.rst:209` still says
  `actor_deleted_complete` "Fires only on the HTTP `DELETE /<actor_id>`
  path", which is no longer true.

## Remaining Tasks

- [ ] Fix Issues 1-3 before release: each is a PostgreSQL fault read as an
      empty answer on the security path (`/iterate_plan`).
- [ ] Decide on Issues 4-8. Fix them in the same iteration or file todos.
- [ ] Release PR: version bump in `pyproject.toml` and `actingweb/__init__.py`,
      the `Unreleased` rename, and a `.. note::` pointing at
      `docs/migration/v3.16.rst` (contract `### Release`).
- [ ] Commit the triage outputs (`thoughts/research/2026-10-26-inbound-triage-*.md`,
      `thoughts/todo/spanned-list-items.md`, the
      `prop-list-key-prefix-scheme.md` section) with or beside this work. They
      sit in the same uncommitted tree.
- [x] Filed the two pre-existing findings that nobody is picking up now, each
      with an `INDEX.md` row: `thoughts/todo/creator-rename-keeps-vouch.md`
      (Issue 11) and `thoughts/todo/flask-factory-json-config.md` (Issue 12).
- Note: Issues 1 and 3 are new instances of the class that
  `thoughts/todo/db-layer-get-bucket-or-empty.md` tracks, a fault read as
  "empty". Fixing them in the iteration should update that todo's site list.

## Issues Found

### 1. On PostgreSQL, a read fault makes a vouched actor look unvouched, and the login wipes it
**Severity:** High
**Description:**
- `is_vouched_actor` reads `store.auth_method`. `InternalStore._ensure_loaded`
  sets `_loaded = True` before the read (`actingweb/attribute.py:33-34`).
- `Attributes` turns a caught fault into an empty bucket:
  `actingweb/attribute.py:113-114` `if fetched_data is None: self.data = {}`.
- The PostgreSQL backend returns that `None` on any exception:
  `actingweb/db/postgresql/attribute.py:235-236`
  `logger.error(f"Error retrieving bucket {actor_id}/{bucket}: {e}")` /
  `return None`.
- So a blip during a vouched user's ordinary login makes `auth_method` read
  `None`. Then `previous` becomes `"legacy"` (`actingweb/oauth2.py:1740`) and
  the clean path rotates the passphrase and deletes every trust,
  subscription and token of a legitimate user.
- DynamoDB raises in this case and fails closed. This is new with this plan:
  before it, no login path destroyed state based on this read.

(outside-voice, fresh-context; confirmed by reading the code)

**Location:** `actingweb/oauth2.py:1580-1597`, `actingweb/oauth2.py:1725`
**Recommendation:** decide vouching only from a load the backend answered
(check `store._db` loaded / `_bucket_loaded`). On an unanswered load, return
`None` from `adopt_actor` so the login fails closed and retries. Add a test
with a backend `get_bucket` that returns `None`.

### 2. On PostgreSQL, `confirmed` is true when the trust or subscription re-read fails
**Severity:** High
**Description:**
- `actingweb/db/postgresql/trust.py:774-775`
  `logger.error(f"Error fetching trusts for actor {actor_id}: {e}")` /
  `return []`, and `actingweb/db/postgresql/subscription.py:392-393`
  `return []`.
- `actingweb/actor.py:1606` `"confirmed": not trusts_left and not subs_left`
  therefore reads a fault as "empty".
- With a fault on both the first fetch and the re-read, nothing is deleted,
  the actor is marked vouched (`oauth2.py:1817-1822`), and the squatter's
  trusts survive. The next login does not retry, because the actor is now
  vouched.
- The plan's "re-reads both lists and marks only when empty" holds on
  DynamoDB only.

(outside-voice, fresh-context; confirmed)

**Location:** `actingweb/actor.py:1599-1607`
**Recommendation:** make the purge's re-read tell a fault apart from empty.
Use a strict fetch that raises or returns `None`, and treat a fault as
unconfirmed. Test with a fetch that raises inside the PostgreSQL backend.

### 3. The SPA half of the token revoke cannot fail, so sessions can survive an adoption logged as complete
**Severity:** High
**Description:**
- `_revoke_all_actor_tokens` is documented "Raises if one cannot be"
  (`actingweb/oauth2.py:1643`).
- But `revoke_all_tokens` reads `access_bucket.get_bucket()`
  (`actingweb/oauth_session.py:892`). That call yields `{}` on a caught fault
  (Issue 1's path), and the method discards the results of `delete_attr`
  (`:900`, `:915`).
- So on PostgreSQL a squatter's SPA and www-cookie sessions can survive an
  adoption that logs success. The MCP half (`_revoke_matching_tokens`)
  checks `loaded` and raises `TokenStoreUnavailable`; this half does not.

(outside-voice, fresh-context; confirmed)

**Location:** `actingweb/oauth_session.py:887-916`
**Recommendation:** an adoption-grade revoke that checks the bucket loaded,
confirms each delete and raises, built the same way as `_revoke_matching_tokens`.

### 4. `actor_deleted` hooks written to the documented signature silently skip replacements
**Severity:** Medium
**Description:**
- The replacement fires `_fire_lifecycle(hooks, "actor_deleted", existing,
  config, **reason)` (`actingweb/oauth2.py:1780`), with `reason` and
  `replaced_by_identifier`.
- `docs/reference/hooks-reference.rst:159` still gives the signature as
  `func(actor: ActorInterface) -> None`, and `docs/guides/apple-sign-in.rst:216`
  shows `def on_actor_deleted(actor):`.
- A hook written that way raises `TypeError`, which
  `execute_lifecycle_hooks` swallows. The app's cleanup (billing, mail)
  never runs for a replaced actor.
- `hooks-reference.rst:209` also still says `actor_deleted_complete` fires
  only on HTTP DELETE.

(code-review)

**Location:** `actingweb/oauth2.py:1780-1784`, `docs/reference/hooks-reference.rst:159`, `:209`
**Recommendation:** update both signature lines to `**kwargs`, fix the
Apple guide example, and add a `CHANGELOG` **Behavior change:** sentence for
hooks without `**kwargs`. Alternatively, pass the reason only to hooks that
accept it.

### 5. A replacement that fails after `buckets.delete()` comes back as a clean-in-place with a tombstone on a live actor
**Severity:** Medium
**Description:**
- `Actor.delete` removes the attribute buckets, including the `factory`
  marker, before the row: `actingweb/actor.py:522-524`
  `buckets.delete()` / `self.handle.delete()`.
- On PostgreSQL a failed row delete returns False and is ignored
  (`actingweb/db/postgresql/actor.py:266-268`; the result is not read at
  `oauth2.py:1781`).
- After a fault at that point the next login reads no marker
  (`"legacy"`) and cleans the half-deleted actor in place instead of
  replacing it. `deletion.mark_actor_deleted` (`oauth2.py:1779`) stays, so
  `get_deletion_status` reports a live, vouched actor as deleted for the
  retention window.
- With `unique_creator` off, the PostgreSQL row-delete failure also lets the
  successor be created beside a surviving old row that keeps the
  squatter's passphrase. The row is empty of relationships, but it still
  resolves by creator.
- The plan's test (`tests/test_oauth2_adoption.py:155`) patches `delete`
  to raise before any work, so it does not cover this.

(outside-voice, codex and fresh-context; confirmed by reading)

**Location:** `actingweb/oauth2.py:1779-1787`, `actingweb/actor.py:522-524`
**Recommendation:**
- After `existing.delete()`, re-read the old id and refuse to create the
  successor while it resolves.
- On the in-place path, clear a tombstone left by an earlier replacement.
- Correct the plan's failure-scenario line.

### 6. The replace path can create two successors, or fail on a DynamoDB GSI read
**Severity:** Medium
**Description:**
- Two concurrent first logins over one `factory` actor both reach
  `_create_actor_for_identifier(config, provider, creator, ...)`
  (`actingweb/oauth2.py:1785`) with no re-check. With the default
  `unique_creator=False` that leaves two vouched actors for one creator.
- With `unique_creator=True` on real DynamoDB, `Actor.create`'s uniqueness
  query goes through the eventually consistent creator GSI. That GSI can
  still list the just-deleted id. `get_by_creator` then appends
  `self.get(...)`, which is `None` for the gone row
  (`actingweb/db/dynamodb/actor.py:103-108`). Then
  `secret_equals(c["passphrase"], ...)` (`actingweb/actor.py:382`) raises
  `TypeError`, and the login fails after the old actor is already gone.
- Both cases fail toward data loss or a retry, never toward squatter
  access. DynamoDB Local does not reproduce the GSI lag, so the suite cannot
  catch it.

(code-review; outside-voice fresh-context)

**Location:** `actingweb/oauth2.py:1785-1787`
**Recommendation:** before creating, run `get_from_creator(creator)` again
and reuse a vouched hit. Skip `None` entries in the `unique_creator` loop.

### 7. Clean-in-place leaves the actor's registered OAuth2 clients
**Severity:** Medium
**Description:**
- `purge_relationships` covers trusts, subscriptions and peer trustees only
  (`actingweb/actor.py:1550`). The actor's `mcp_clients` bucket
  (`actingweb/oauth2_server/client_registry.py:43`) and the system actor's
  client index survive.
- A client the squatter made through `OAuth2ClientManager.create_client` can
  still mint tokens via `client_credentials`
  (`actingweb/oauth2_server/oauth2_server.py:644-662`, no trust check).
- Today the MCP handler refuses a token whose client trust is gone (the
  trust was purged), so the minted token reaches nothing. Only one guard
  stands between it and access.
- Reach depends on the application exposing `create_client` to the creator.
  The replace path removes the bucket (`buckets.delete()`) but not the
  system-actor index row.

(code-review; outside-voice codex, downgraded after checking the MCP trust
gate)

**Location:** `actingweb/actor.py:1549-1607`, `actingweb/oauth2.py:1807-1808`
**Recommendation:** delete the actor's clients and their index rows in the
adoption, through the client registry's delete, and count them in the
`actor_adopted` payload.

### 8. The backfill script can vouch a factory actor on a read fault and counts unconfirmed writes
**Severity:** Medium
**Description:**
- In `scripts/mark_actors_vouched.py:78-90`, `current = store.auth_method`
  reads `None` on a PostgreSQL fault (Issue 1). `qualifies = not current`
  then lets `store.auth_method = marker` overwrite a real `factory` marker,
  which vouches a squat.
- `counts["marked"] += 1` runs without confirming the write.
- The docstring (`:10-11`) also promises that marked actors are left alone,
  but `is_vouched_actor` keeps `email_verified == "false"` actors unvouched
  whatever the marker says (`actingweb/oauth2.py:1597`).

(outside-voice, fresh-context; confirmed)

**Location:** `scripts/mark_actors_vouched.py:78-90`
**Recommendation:**
- Skip actors whose bucket did not load, and count them as errors.
- Read the marker back before counting it.
- Report `email_verified="false"` actors separately, and correct the
  docstring.

### 9. A closed factory answers a form post with JSON `Accept` with an empty 403
**Severity:** Low
**Description:**
- The gate picks JSON from `Content-Type` only (`actingweb/handlers/factory.py:219-231`).
- The Flask route sends `Accept: application/json` requests down a path that
  renders the template only on 400.
- Reproduced in this verification: `curl -X POST -H 'Accept:
  application/json' -d 'creator=x@example.com' http://localhost:5000/`
  answered 403 with an empty body.

(code-review; reproduced)

**Location:** `actingweb/handlers/factory.py:219-232`
**Recommendation:** `as_json="application/json" in content_type or
self._wants_json()`, matching the duplicate-creator branch.

### 10. Small duplications introduced by the diff
**Severity:** Low
**Description:**
- `factory.py:219-226` hand-rolls a header scan that `AWRequest.get_header()`
  provides.
- The accepted `prompt` values are defined twice:
  `factory.py:103` `"prompt_values": ["select_account"]` and
  `oauth2_spa.py:49` `SPA_PROMPT_VALUES`.
- The replace branch rebuilds the trust/subscription summary that
  `purge_relationships` builds (`oauth2.py:1749-1772`).
- Both SPA paths call `get_from_creator` and then `adopt_actor`, then
  `lookup_or_create_actor_by_identifier`, which repeats the same lookup
  (`oauth2_spa.py:969`, `:1147`).
- `Actor.create` writes InternalStore's private `__dict__["_loaded"]`
  (`actor.py:437`).

(code-review; outside-voice)

**Recommendation:** import `SPA_PROMPT_VALUES` in `factory.py` and use
`get_header`. Extract the summary helper. The rest is optional cleanup.

### 11. Pre-existing: renaming a vouched actor's creator bypasses the squat fix
**Severity:** Medium (pre-existing; not introduced by this diff)
**Description:**
- `PUT /<id>/trust/trustee` lets an authenticated creator set any `creator`
  (`actingweb/handlers/trust.py:221-266` calls `myself.modify(creator=creator)`;
  the access rule is `("creator", "trust", "", "a")` at `config.py:274`).
  Nothing checks for proof or uniqueness.
- An attacker's own OAuth actor stays vouched after being renamed to the
  victim's address. The victim's first login then finds it, and
  `adopt_actor` leaves it untouched (`actingweb/oauth2.py:1725-1732`).
- It worked the same way on `master`, so this diff does not make it worse.
  It does leave the squat class open, and the new vouching model assumes
  "vouched" stays tied to the address.

(security review; the false-positive filter rated it 8/10 real and 9/10
pre-existing)

**Location:** `actingweb/handlers/trust.py:247-266`, `actingweb/actor.py:456-483`
**Recommendation:** in `Actor.modify(creator=...)`, reset `auth_method` to an
unvouched marker. Alternatively, refuse `creator` in `PUT /trust/trustee` on
a vouched actor. File as a todo if it is not fixed in this release.

### 12. Pre-existing: Flask serves HTML for `GET /?format=json`
**Severity:** Low here (pre-existing, outside the plan)
**Description:**
- The Flask factory route renders the template for every successful GET, so
  the handler's JSON config (and its new `prompt_values`) never reaches a
  Flask client.
- Reproduced by browser QA and by curl with `Accept: application/json`.
- SPAs read `prompt_values` from `/oauth/spa/config`, which is unaffected.

**Location:** `actingweb/interface/integrations/flask_integration.py` (the
`request.method == "GET" and webobj.response.status_code == 200` render)
**Recommendation:** todo, outside this plan.

### 13. The closed-factory error page lists unrelated "Possible Causes"
**Severity:** Low (cosmetic, browser QA)
**Description:** the demo's `aw-root-failed.html` shows network and OAuth
causes under the closed-factory message.
**Recommendation:** optional, in the demo template.

**Browser walk (headless, demo app, factory closed, no OAuth):**
- **Main path:** a valid email on `/` gets a 403 error page with the escaped
  closed-factory message.
- **Edge inputs:**
  - An empty submit is blocked client-side; posted server-side anyway, it
    shows the form with "Email is required" (200).
  - An invalid address gets a 403 with the message.
  - A 300-character address gets a 403, with no layout overflow.
  - `<script>…</script>@x.com` gets a 403; the address is not echoed, so
    there is no XSS.
- **Other pages:** `/login` answers 200. The factory and error pages fit at
  375 px.
- **Console:** only Chromium's expected "403 (FORBIDDEN)" resource line.
- **Not exercised:** the OAuth login itself, because no `.env` with a real
  client exists.

## Overall Assessment

The plan is implemented as written. All three phases match their Changes
lists, with recorded and acceptable deviations, and every listed test exists
and passes. The full tier is green on DynamoDB (3977) and PostgreSQL (3868).
Lint, types and groups are clean, and the docs build is clean once the local
worktree artefact is excluded. The squat exploit is demonstrated closed end
to end against a real server, and the closed factory works in the browser
and over curl.

It should not ship as is. The security property holds on the happy path, but
not under a PostgreSQL fault, because that backend returns empty for a
caught read error. The vouching decision (Issue 1), the wipe confirmation
(Issue 2) and the SPA revoke (Issue 3) all read that empty as a real answer.
The worst case is not a squatter keeping a foothold but a database blip
wiping a legitimate user's trusts and sessions at login. Issues 1-3 need an
`/iterate_plan` pass with fault-injection tests on the PostgreSQL backend.
Issues 4-8 are worth folding into the same pass, the hook-signature
compatibility (4) and the backfill script's fault handling (8) most of all.
The rest can be todos. The creator-rename bypass (11) predates this work but
undercuts the release's headline claim, so the CHANGELOG should either name
it as a limitation or the release should close it. Because the plan landed
as written, its `verified:` link is set to this document. The findings
belong to the next iteration, not to an unfinished plan.
