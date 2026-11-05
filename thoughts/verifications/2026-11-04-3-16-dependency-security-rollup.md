# Verification: 3.16 roll-up: dependency security upgrade and the small bounded follow-ups

**Date:** 2026-11-04
**Plan:** thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md
**Research:** none of its own (the plan's todos are its research)
**Branch:** release/3.16.0-dependency-security
**Commit:** a329c40 (diff range `8bbaa88..a329c40`, three commits)

First run; there is no previous verification and no feature document, so
there is no Success Measures table.

## Automated Check Results

- **Browser QA:** N/A. No phase touches anything a user sees (library code,
  JSON endpoints, operator commands).
- **Second opinion:** Codex (`codex review --base 8bbaa88`, outside the
  sandbox): no discrete actionable defects. Fresh-context Claude (outside
  voice): six findings, folded below. Built-in code review (`/code-review
  high`): ten findings, folded below. Built-in security review: no
  high-confidence vulnerabilities; it traced the marker ordering, the MCP
  logout branch, the resolver's permission check, `find_client_trust` on the
  auth path and the PostgreSQL probe, and found each sound.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (516 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: pass (53 groups).
- `make test-all-parallel` (DynamoDB): pass, 5616 passed, 60 skipped,
  1 xfailed.
- `make test-all-parallel` (PostgreSQL): pass, 5421 passed, 255 skipped,
  1 xfailed.
- `sphinx-build -W ...`: pass.
- Benchmarks: not run. The plan touches neither list storage nor the
  attribute layer's hot path (one more point read per refresh, measured by
  count in D4).

All counts come from the parallel runs above; nothing failed, so nothing
needed a sequential re-run.

## Phase Verification

### Phase 1: Dependencies and the fail-closed creators uniqueness - ISSUES FOUND

**Changes verified:**
- `pyproject.toml` (`pyjwt ^2.15`), `poetry.lock`, `docs/requirements.txt`,
  and the SECURITY entry with `python-discovery` and the 3.15.1 self-remedy:
  match D1.
- `actingweb/db/dynamodb/actor.py:607`: the constructor ensures only
  `Actor`. `:578` `_log_missing_creators_table`: the ERROR on
  `is_resource_not_found`, with no `DescribeTable` (deviation recorded in the
  plan).
- `actingweb/db/postgresql/actor.py:26` (`_index_seen_valid`, positive
  only, keyed by schema), `:65` `_require_creator_index`, and its calls at
  `:274` (create), `:323` (replace holder), `:428` (rename): match D2.
- `actingweb/maintenance/unique_creators.py:950-952` delegates to the db
  probe; `:340` `report` logs the missing table.
- `tests/conftest.py:104` `_creators_table`, `tests/_lookup_probe.py:111,129`
  stub and opt-out, `tests/integration/_isolated_store.py:155,182` resets:
  match D2, with the every-backend deviation recorded.
- Docs (`v3.16.rst`, `configuration.rst`) and the three changelog entries
  edited in place.

**Tests verified:**
- `tests/test_unique_creator_fail_closed.py:62` and `:86`: DynamoDB, an
  absent table name, `DbError` that is not `CreatorTaken` with the exact
  text, ERROR naming table and command, no table created (with `exists`
  raising too).
- `:201`-`:280`: PostgreSQL probe on a fake connection. Covers missing,
  present (cached once), INVALID, exempt and flag-off (no probe), fault and
  absent not cached, rename and replace guarded, and `missing_enforcement`
  through the db probe.
- `tests/integration/test_unique_creator_states.py:822`: both backends,
  `DbError` before `enable` and success after it; `:851`: `report` names the
  missing table.

**Failure scenarios:**
- Worker on a store where `enable` never ran: covered by the tests above,
  **but only when the creators table does not exist** (Issue 1).
- PostgreSQL cached "valid", then the index is dropped: recorded and
  accepted in the plan; the docstring overstates it (Issue 7).
- Unit run on a fresh DynamoDB Local: verified during implementation
  (`down -v`, up, unit tier green).

**Deviations from plan:** all four are recorded in the plan's Phase 1
notes and acceptable: `DbError(op)` text, no `DescribeTable`, the
schema-keyed cache, and the every-backend fixture.

### Phase 2: Logout - VERIFIED (with low findings)

**Changes verified:**
- `actingweb/constants.py:230` `CHAIN_REVOKED_MARKER_TTL = 300` with its
  invariant.
- `actingweb/single_use.py:291` `mark_chain_revoked`, `:326`
  `chain_revoked` (strict read, `StoreFault` on a fault).
- `actingweb/oauth_session.py:1108`: the marker is written inside the
  existing `try` before `revoke_chain_confirmed`; `:1319` adds the purge
  bucket.
- `actingweb/handlers/oauth2_spa.py:984`: the post-mint check, before the
  generation guard; `revoke_minted` is two `delete_confirmed` calls.
- `actingweb/oauth2_server/token_manager.py:797`: the marker before the
  first `_snapshot_bucket`; `:527` the post-mint check; `:994,:1016` the
  shared point removals; `:1990` the purge list.
- `actingweb/deletion_finish.py:200`: `session_generation.bump` before
  `_revoke_all_actor_tokens`.
- `actingweb/db/postgresql/attribute.py:777`: `delete_expired` raises. All
  callers fold it (`oauth_session.py`, `token_manager.py` ×2,
  `maintenance/deletions.py`).
- `actingweb/handlers/oauth2_endpoints.py:1138` (DEBUG line), `:1246`
  (`clear_cookies: []`); the docs at four sites in `spa-authentication.rst`,
  plus `security.rst` and `database-backends.rst`.

**The security property, demonstrated** (addendum rule):
- `tests/test_oauth2_spa_logout_revokes_chain.py:637`
  `test_a_logout_between_the_consume_and_the_mint_leaves_no_live_pair`
  asserts `status_code == 401`, `code == "invalid_grant"`, that
  `_chain_rows(env, chain) == []`, and that the marker row is present. With
  `chain_revoked` stubbed to `False` it fails (200 with a live pair),
  checked during implementation.
- `tests/test_mcp_refresh_rotation.py:829`, the MCP mirror, asserts that
  `refresh_access_token(...) is None`, that `_chain_rows(store, chain) == []`
  and that the marker is present. It also fails with the check stubbed.
- Marker before sweep: SPA `:652` asserts `order == ["marker", "sweep"]` and
  a TTL of 300. MCP `:854` asserts that the first snapshot sees the marker.
- Fail closed: `:680` and `:872` (a write fault means 503 or raise, nothing
  deleted); `:694` (`== before`) and `:884` (exact survivor) for a read
  fault.
- Finisher: `tests/test_deletion_finish.py:556` (order `["bump", "sweep"]`
  and the old stamp no longer matches), `:585` (a bump fault means no sweep
  and the lease is released).
- MCP logout: `tests/test_oauth2_logout_mcp_tokens.py:475` asserts
  `cleared_cookies == []`, no expiring cookie, the MCP chain gone, both SPA
  rows alive, and the DEBUG line.
- Reaper: `tests/test_db_fault_contract.py:196,205`;
  `tests/integration/test_spa_chain_revocation_backend.py:146` (TTL on
  DynamoDB, reaped by `delete_expired` after 300 + 3600 s on PostgreSQL).

**Failure scenarios:** every entry has a test above except two accepted
ones: a point-delete fault logs at ERROR (`oauth2_spa.py` `_delete_minted`,
`token_manager.py:1016`), and DynamoDB TTL not enabled (documented in
`database-backends.rst`).

**Deviations from plan:** the MCP race seam revokes through the consumed
refresh token, and the test placement differs. Both are recorded and
acceptable.

### Phase 3: Operator enumeration, hygiene, todo cleanup - ISSUES FOUND

**Changes verified:**
- `actingweb/db/protocols.py:229` `iter_rows`;
  `actingweb/db/dynamodb/actor.py:627` (`fetch` projected), `:641`
  `iter_rows`; `actingweb/db/postgresql/actor.py:22` (`_ITER_PAGE`), `:547`
  keyset pages with one connection per page.
- `actingweb/maintenance/mark_actors_vouched.py:159` (consistent, filters at
  collection), `:228` `--rate-limit`; `verify_property_lists.py:500,521`
  and `migrate_property_lists.py:507,529` (streamed, part-way fault
  message); `verify_orphans.py:234`.
- `actingweb/db/dynamodb/subscription.py:110,202` and
  `postgresql/subscription.py:131,223`: the guard runs first.
- `actingweb/mcp/uri.py:39` `resolve_resource`; `actingweb/handlers/mcp.py:636`
  `format_resource_read_result`, `:1940-1945`; `async_mcp.py:457-465`.
- `actingweb/oauth2_server/trust_lookup.py:19`; callers
  `handlers/mcp.py:2590` (default) and `client_registry.py:623`
  (`legacy_segment_match=True`).
- Docs: `mcp-applications.rst:499`, `v3.16.rst`, CHANGELOG ADDED (edited in
  place) and the FIXED entries.

**Tests verified:** `tests/test_db_fault_contract.py:154,163,446`
(`iter_rows` faults on both backends); `tests/test_actor_list_iter_rows.py`
(seeded ids exactly once, `id`/`creator` only, PostgreSQL in sorted order,
scan options passed through, no pooled connection held across yields);
`tests/test_mark_actors_vouched.py:70` (`--rate-limit` reaches a consistent
scan, filters at collection, sorted order); `TestMidSweepFault` in both
property-list script files (checkpoint kept, exit 2);
`tests/test_subscription_callback_type.py` (`TypeError` naming `str`,
never the value, no I/O, `None` accepted);
`tests/integration/test_subscription_callback_backend.py` (both flags round
trip); `tests/test_mcp_resource_read_permissions.py:238-305` (whole
`result` equal across handlers for five resource shapes);
`tests/test_client_trust_lookup.py` (decoy kept, exact row only, real-email
`oauth2_client:` legacy row deleted and never authorises, resolver inputs
unchanged).

**Verification commands:** `actingweb-mark-actors-vouched --dry-run
--rate-limit 50` against the DynamoDB test store printed its progress and
summary lines (`scanned=455 ... errors=0`), run during implementation.

**Todos (addendum rule):** the four files D9 names are deleted with their
`INDEX.md` rows. Sections 4 and 7 of `mcp-cache-lifecycle-and-revocation.md`
and item 4 of `dynamodb-known-next.md` are removed. Every `todo/` file has a
row and no row dangles. Each deferral under "What We're NOT Doing" points at
an existing todo or is a recorded rejection.

**Deviations from plan:** recorded in the plan's Phase 3 notes and
acceptable. Issues 2, 3 and 4 below are defects, not deviations.

**Consumer message:** the plan has none.

## Remaining Tasks

- [ ] Issues 1 and 2 go to `/iterate_plan`, inside this plan, per the
  owner's rule that verification findings are addressed in the plan and not
  filed as todos.
- [ ] The low issues: fix, or accept in the plan with a sentence each.

## Issues Found

### 1. DynamoDB fail-closed check sees "table exists", not "enforced"; the documented first start leaves an empty table
**Severity:** High
**Description:** The per-write check on DynamoDB fires only when the
`creators` table is missing. `check_ready()` runs
`_prewarm_dynamodb_tables()` before it refuses (`actingweb/interface/app.py:1580`),
and the prewarm creates `creators` empty (`required_models(unique_creator=True)`,
`app.py:1541`). After an existing fleet's first `integrate_*` start, which
refuses with `UniqueCreatorNotReady`, a worker that builds `Config()`
directly claims creators against the empty, unbackfilled table and lands a
second actor for an existing address. This is the scenario of the deleted
todo `unique-creator-direct-config-auto-create.md`. The new docs sentence,
"with uniqueness on and `enable --apply` not yet run, every actor create ...
raises `DbError` ... on both backends" (`docs/quickstart/configuration.rst`,
`docs/migration/v3.16.rst`, CHANGELOG), is false on DynamoDB in that state.
PostgreSQL's probe checks index validity, which does mean "enforced", so
the two backends are not symmetric. Found by both the outside voice and the
code review; confirmed against `app.py:1580`.
**Location:** `actingweb/db/dynamodb/actor.py:578` (the only DynamoDB
detection) and `actingweb/interface/app.py:1580`.
**Recommendation:** on DynamoDB, have an enforced write check the
backfill-complete item once per process, cached positive only (the
`_index_seen_valid` shape), and raise `DbError(op)` with the remedy ERROR
when it is absent. Or stop the prewarm from creating `creators` until
`enable` has run, which the plan rejected because the first-start sequence
depends on it, so that would need the owner. At the least, the docs
sentence must say "does not exist" until this is fixed.

### 2. Client deletion no longer removes real-email legacy rows with a source other than `oauth2_client`
**Severity:** Medium
**Description:** `TrustManager.create_or_update_oauth_trust` writes
`f"{source}:{normalized_email}:{normalized_client}"` with
`source = established_via or "oauth2"` (`actingweb/interface/trust_manager.py:465,485`),
so legacy rows include `oauth2:<email>:<client>`. The old deletion's
`peer_id.endswith(client_id)` removed them. Arm 3 accepts only
`peer_id.startswith("oauth2_client:")` (`actingweb/oauth2_server/trust_lookup.py:66`),
so such a row survives its client's deletion with its permissions. The
changelog's "legacy rows are still deleted" is false for them.
**Location:** `actingweb/oauth2_server/trust_lookup.py:62-70`.
**Recommendation:** accept every OAuth2-family source in arm 3 (`oauth2:`,
`oauth2_client:`, and any other `source` the creation path writes), gated
on `established_via` as arm 2 is (which also answers Issue 9). Last segment
must equal the client id, with no `oauth_client_id`. Add the `oauth2:` case
to `tests/test_client_trust_lookup.py`.

### 3. A template variable can override a request param, `uri` included, now on Flask too
**Severity:** Low
**Description:** `{**params, **variables}` (`actingweb/handlers/mcp.py:1945`,
`actingweb/handlers/async_mcp.py:465`) lets a template such as
`notes://{uri}` replace `uri`. Flask previously passed `params` only, so
this is a Flask-side change the changelog does not name, and its promise
that "a hook sees `uri` in its arguments again" is not true for such a
template. A FastAPI hook that splats its arguments into a fixed signature
now receives `uri` and raises `TypeError`. Permissions are evaluated on the
full request `uri` first, so this does not escalate access.
**Recommendation:** merge as `{**variables, **params}` (the request wins) or
reserve `uri`. State the Flask change and the splat risk in the changelog.

### 4. The changelog omits FastAPI's old `content`-key unwrap
**Severity:** Low
**Description:** The removed async code sent `str(result.get("content", result))`.
A FastAPI hook returning `{"content": "<markdown>"}` used to send the bare
string and now sends a JSON object labelled `application/json`. The FIXED
entry says only "sent a `dict` result as `str()`".
**Location:** `actingweb/handlers/mcp.py:636` and the D7 CHANGELOG entry.
**Recommendation:** name the `content` key in the **Behavior change**
sentence. Restoring the unwrap would diverge from Flask.

### 5. The finisher's fence does not hold for unstamped tokens once the actor wipe removes `_internal`
**Severity:** Low
**Description:** `session_generation.matches` compares
`str(stamped) if stamped else None` with `current()`
(`actingweb/session_generation.py:110-112`). After `actor.delete()` wipes
the buckets, `current()` is `None`, so a never-adopted (unstamped) SPA
refresh whose consume preceded the sweep and whose guard runs after the
wipe passes and leaves a pair for the deleted id. The window is narrow (the
mint must straddle the client sweep and the wipe), and the pair works only
if the id is re-created.
**Location:** `actingweb/deletion_finish.py:196-213`.
**Recommendation:** treat a deleted actor (tombstone present, or no actor
row) as a mismatch in the guard, or accept and record it in D4.

### 6. A resumed finish leaves an orphan `_internal/session_generation` row
**Severity:** Low
**Description:** On a resume where the actor row is already gone,
`bump()` (`actingweb/deletion_finish.py:200`) writes a fresh generation row
with no TTL, and `actor.delete()` returns True without reaching
`Buckets.delete()`, so nothing reaps the row.
**Recommendation:** skip the bump when the actor row is gone (there is
nothing to refresh), or delete the row after the wipe.

### 7. The PostgreSQL probe docstring overstates the guarantee
**Severity:** Low
**Description:** Only the process that runs `disable` resets its cache, so
other long-running workers keep writing without the index after an
operator drops it or a REINDEX leaves it INVALID. The plan accepts this
(Phase 1 failure scenario), but the `DbActor.__init__` docstring says "a
process that skipped the check cannot land a duplicate".
**Location:** `actingweb/db/postgresql/actor.py:52` and the constructor
docstring.
**Recommendation:** add "until the index is dropped while the process
runs" to the docstring.

### 8. The DynamoDB missing-table ERROR always blames `creators`
**Severity:** Low
**Description:** Any `ResourceNotFound` from a transaction logs "the
DynamoDB table `<prefix>_creators` does not exist" and names `enable
--apply`, including when the actor table is the one missing (deleted out of
band after `ensure_table` memoised it, or prefix drift).
**Location:** `actingweb/db/dynamodb/actor.py:585`.
**Recommendation:** "a table in this transaction (`<prefix>_creators` or
`<prefix>_actors`) does not exist", with the creators remedy as the likely
one.

### 9. Arm 3 of `find_client_trust` does not check `established_via`
**Severity:** Low
**Description:** Arm 2 and the resolver comment rely on the
`established_via` gate. Arm 3 (deletion only) checks only the prefix and the
last segment (`actingweb/oauth2_server/trust_lookup.py:62-70`), so a
peer-protocol row of that shape on the same actor could be deleted in place
of the client's real row. Only one row goes per call, so the real one would
stay.
**Recommendation:** fold into the fix for Issue 2.

### 10. New test functions lack type hints
**Severity:** Low
**Description:** CLAUDE.md requires type hints on all functions. In
`tests/integration/test_subscription_callback_backend.py:17,36,48`, the
fixtures and the test are unannotated. So are `_only_this_actor` and
`iter_rows` in both property-list script tests
(`test_migrate_property_lists_script.py:294,309`,
`test_verify_property_lists_script.py:361,376`).
**Recommendation:** annotate them.

### 11. Hygiene: duplicated normalisation and test helper, and a no-op reset
**Severity:** Low
**Description:** `trust_lookup._normalized` (`:14`) is a third copy of the
client-id normalisation in `trust_manager.py:479-485`, so creation and
lookup can drift. The `_only_this_actor` stub is duplicated across the two
script tests. The `reset_index_probe()` after `enable` builds the index
(`unique_creators.py` near `:986`) is a no-op because the cache is positive
only.
**Recommendation:** share one normaliser from `trust_lookup` with the
creation path, move the stub to a shared helper, and drop or comment the
no-op reset.

## Overall Assessment

The plan landed as written. All three phases are complete. The Full tier
is green on both backends (DynamoDB 5616 passed, PostgreSQL 5421 passed),
along with the docs build, and the security properties the plan claims are
demonstrated by tests that fail without the fix: the logout race on both
ladders, marker-before-sweep, fail closed on marker faults, the finisher
fence and the MCP logout's cookies. Codex and the security review found
nothing.

Two findings need attention before the PR. **On DynamoDB, creator
uniqueness still fails open** after the documented first start (Issue 1):
the prewarm leaves an empty `creators` table, the per-write check only
notices a missing table, and the new docs promise a `DbError` that does
not happen. That is the hole the deleted todo described, so D2 is
incomplete on that backend. **Client deletion regressed** for real-email
legacy rows whose source prefix is not `oauth2_client:` (Issue 2). The low
findings are changelog accuracy (3, 4), narrow lifecycle gaps (5, 6),
wording (7, 8) and hygiene (9, 10, 11). Next step: `/iterate_plan` for
Issues 1 and 2, with the low ones fixed or accepted in the plan, then
re-verify before opening the PR.
