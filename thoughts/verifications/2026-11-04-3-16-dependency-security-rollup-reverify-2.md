# Verification: 3.16 roll-up: dependency security upgrade and the small bounded follow-ups (third run)

**Date:** 2026-11-04
**Plan:** thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md
**Research:** none (the plan's todo files are its research)
**Branch:** release/3.16.0-dependency-security
**Commit:** e5337af

Scope: the whole plan, with the review weighted to the iteration commit
`e5337af` (Iterations 6-9). New in this run, at the owner's request: the
branch's behaviour checked against the specification and reference in
`docs/` (the protocol spec, `docs/reference/`, `docs/guides/`, the
configuration and v3.16 migration pages) and against the concrete claims of
the `Unreleased` changelog.

## Automated Check Results

- **Browser QA:** N/A. No phase touches a page; the MCP-logout response
  change is JSON plus headers and is covered by tests.
- **Second opinion:** outside-voice agent, codex (`codex exec -s read-only`)
  plus a fresh-context read of `f112753..e5337af`. Findings folded into
  Issues 3-6 and 12.
- **Spec conformance:** a separate agent read every behaviour change on the
  branch (`8bbaa88..e5337af`) against `docs/`. Findings folded into Issues
  1, 2 and 7-12. The two Medium ones were re-checked by hand (below).
- **Code review / security review:** not re-run. The delta is one commit of
  lookup and logging changes; the outside voice covered it (scale reviews to
  the delta).
- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass (518 files).
- `pyright actingweb tests`: 0 errors, 0 warnings, 0 informations.
- `tests/integration/verify_groups.py`: all 53 groups documented.
- `make test-all-parallel`, DynamoDB: 5631 passed, 60 skipped, 1 xfailed.
- `make test-all-parallel`, PostgreSQL: 5431 passed, 260 skipped, 1 xfailed.
- `sphinx-build -W …`: pass.

All on the committed tree `e5337af`, one run at a time.

## Phase Verification

Phases 1-3 and Iterations 1-5 were verified in the two earlier runs; this
run re-read only what `e5337af` touched, plus the spec sweep over all of
them.

### Iteration 6: client deletion removes every row - VERIFIED, claim overstated

**Changes verified:**
- `actingweb/oauth2_server/trust_lookup.py`: `find_client_trust` answers
  exactly as before (arm 1, then arm 2 with the same `established_via` set
  and candidates); confirmed by the outside voice against
  `git show f112753:…/trust_lookup.py` and pinned by
  `test_the_default_matches_the_resolver`.
- `client_trusts_for_deletion` returns arm 1, 2 or 3 matches. It cannot
  return another client's tagged row (`_untagged` gate) or a peer-protocol
  row (`_oauth2_origin`).
- `client_registry.py` deletes each match; `DbError` propagates.

**Tests verified:**
- `test_a_tagged_row_and_a_legacy_row_of_one_client_are_both_deleted`:
  asserts `find_client_trust(...) is tagged` and both peer ids deleted. Its
  `_DeletingTrustManager` does not model the `Trust.delete` cascade (Issue 3).
- `test_the_segment_arm_needs_exactly_three_segments`.

### Iteration 7: probe fault logged, one read per refusal - VERIFIED

- `_require_creators_backfill` reads `cached_backfill_state()` once and logs
  an ERROR naming the table, the fault and `dynamodb:GetItem` on a fault.
- `test_a_probe_read_fault_is_refused_with_a_logged_reason` asserts the
  message holds the table name, `AccessDeniedException` and
  `dynamodb:GetItem`.
- `test_a_refusal_reads_the_marker_once_and_check_ready_seeds_the_cache`
  asserts one read per refusal and zero reads on the first write after
  `missing_enforcement` saw "complete".
- The seeding cannot let a CLI claim against an emptied table: the CLI's
  transactions (`release_stale_record`, `record_for_actor_as_read`,
  `move_stale_record`) never call the guard. It widens the accepted
  positive-cache window to workers that have only started.

### Iteration 8: docstrings - ISSUES FOUND (Issue 4)

The constructor caveat is right. The `_log_missing_creators_table` docstring
"Every enforced transaction passes `_require_creators_backfill` first" is
false for three unguarded paths.

### Iteration 9: doc accuracy and hints - VERIFIED

Cross-reference fixed; the pattern-resource sentence in
`mcp-applications.rst` and `resource_arguments` is true; hooks annotated.

## Spec conformance

Checked and consistent (passages the agent read, code it traced):

- **Subscription `callback` must be a bool.** The spec's subscription POST
  body is `target`, `subtarget`, `resource`, `granularity`
  (`actingweb-spec.rst:2370-2422`); it has no `callback` field (the
  `"callback": "uri"` at `:1249` belongs to `/sessions`).
  `handlers/subscription.py:199-262` reads only those four fields, and
  `Actor.create_subscription` defaults `callback=False`
  (`actor.py:2319-2333`); the outbound path passes `True`. No
  spec-conformant peer request reaches the `TypeError`; the changelog's "No
  request can reach it" holds.
- **Chain revocation and the deletion fence:** `spa-authentication.rst:996-1001`,
  `security.rst:99`, `database-backends.rst:262,272-274` match the code,
  apart from Issues 1 and 9.
- **MCP logout:** `spa-authentication.rst:994,1633,1650-1656` match
  (`cleared_cookies: []`, no `Set-Cookie`, DEBUG for ignored SPA tokens).
- **PostgreSQL `delete_expired`:** raises `DbError`;
  `database-maintenance.rst` describes the wrapper, which still folds to 0.
- **`resources/read` success path:** `mcp-applications.rst:499-509`
  matches, apart from Issues 10 and 11.
- **Client lookup:** `v3.13.rst:620-637` matches.
- **Operator sweeps:** `v3.16.rst:218-226` matches.
- **Creator enforcement:** `v3.16.rst:272-274,838-960`,
  `database-backends.rst:583-600`, `configuration.rst:238`, `security.rst:92`
  match, apart from Issues 7 and 8.
- **PyJWT:** `^2.15`, `docs/requirements.txt` regenerated.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-04-3-16-dependency-security-rollup-reverify.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Client deletion removes one row | Fixed, but the finding was overstated (Issue 3) | `client_registry.py:633`; `trust.py:136,166` already cascaded for `mcp_` ids |
| 2. Probe fault logs no reason | Fixed | `dynamodb/actor.py:50-63`, `test_a_probe_read_fault_is_refused_with_a_logged_reason` |
| 3. Double read; `check_ready` does not seed | Fixed | `_backfill_probe.py:48,52-57` |
| 4. DynamoDB constructor caveat | Fixed | `DbActor.__init__` docstring |
| 5. ERROR names the less likely table | Fixed for the guarded paths; wrong for three others (Issue 4) | `dynamodb/actor.py:616-640` |
| 6. Arm-3 docstring claims arm 2's gate | Fixed | `client_trusts_for_deletion` docstring |
| 7. Arm 3 matches client-less rows | Fixed (exactly three segments); side effect Issue 12 | `trust_lookup.py:68` |
| 8. Doc accuracy | Fixed; the `uri` registration warning not added (recorded in the plan) | Iteration 9 |
| 9. Type hints | Fixed | `tests/test_mcp_resource_read_permissions.py` |

## Remaining Tasks

- [ ] Issues 1-4 before the PR (changelog and docs accuracy, one docstring).
- [ ] Issues 5-12: fix, or accept in the plan with a sentence each.
- [ ] `thoughts/todo/`: unchanged since the last run; nothing the plan named
  is outstanding.

## Issues Found

### 1. The changelog says a marker fault answers 503; on `/oauth/token` it answers 500
**Severity:** Medium
**Description:** `CHANGELOG.rst:49-52`: "a marker that cannot be written
answers 503 with ``Retry-After`` … a marker that cannot be read during a
refresh deletes what was minted and answers 503." On the MCP ladder
`token_manager.py:530-531` raises `TokenStoreUnavailable`, a plain
`Exception` (`token_manager.py:37`); `oauth2_server.py:499-501` turns it
into `server_error`, which `oauth2_endpoints.py:469-472` answers with 500
and no `Retry-After`. The SPA endpoint and MCP logout do answer 503.
(Re-checked by hand.) The 500 matches what `v3.15.rst:88-91,245` documents
for `/oauth/token` store faults, so the code is consistent and the entry is
not.
**Location:** `CHANGELOG.rst:49-52`
**Recommendation:** qualify the statuses per endpoint, as the
`invalid_grant` sentence already does ("503 on the SPA endpoint and logout,
500 `server_error` on `/oauth/token`").

### 2. `DbActorList.iter_rows` is a new backend requirement no doc names
**Severity:** Medium
**Description:** `db/protocols.py` adds `iter_rows`, and three operator
commands call it unconditionally (`mark_actors_vouched.py:159`,
`migrate_property_lists.py:507`, `verify_property_lists.py:500`). The v3.16
"Custom database backends" section (`docs/migration/v3.16.rst:697` on) lists
what a backend must add and does not name it; there are no `iter_rows` hits
in `docs/` or `CHANGELOG.rst`. A custom backend built to that list runs
`actingweb-mark-actors-vouched` (a step the guide puts before the first
sign-in) and exits 2 with "the actor list could not be read", the
`AttributeError` folded away. The same list also omits PostgreSQL-style
`delete_expired` raising on a fault and the bool `callback` check.
**Location:** `docs/migration/v3.16.rst:697-760`
**Recommendation:** add the three contract items to that list.

### 3. Iteration 6's changelog claim describes a failure production did not have for generated ids
**Severity:** Medium
**Description:** `CHANGELOG.rst` (client-deletion entry): "a second row of
the same client … kept its permissions" and "**Behavior change:** a client
with both a tagged and a legacy row loses both". Before `e5337af`, deleting
the tagged `oauth2_client:…:mcp_x` row ran `Trust.delete`, which calls
`registry.delete_client(oauth2_client_id, actor_id=…)` (`trust.py:136,166`);
`delete_confirmed` answers True for an already-gone row
(`single_use.py:213`), so the nested call reached
`_delete_client_trust_relationship` and deleted the legacy row. Confirmed by
hand. The re-verification's Issue 1 missed this cascade, and the new test's
`_DeletingTrustManager` does not model it. Iteration 6 still covers what the
cascade cannot: client ids that `_extract_client_id_from_peerid` returns
None for (not `mcp_`-prefixed), and deletion paths not entered through a
tagged `oauth2_client:` row first.
**Location:** `CHANGELOG.rst` client-deletion FIXED entry;
`tests/test_client_trust_lookup.py:38-40`
**Recommendation:** reword as hardening (the cascade already removed the
legacy row for generated `mcp_` ids; deletion no longer depends on it), and
correct the plan's Iteration 6 rationale. Optionally one test through the
real `Trust.delete` cascade.

### 4. `_log_missing_creators_table` claims every transaction is guarded; three are not
**Severity:** Medium
**Description:** `dynamodb/actor.py` docstring: "Every enforced transaction
passes :func:`_require_creators_backfill` first … so a missing table here
is most likely the actor table". `release_stale_record`,
`record_for_actor_as_read` and `move_stale_record` call `_run_transaction`
with no guard; the CLI (`unique_creators.py:592,616-617`) and
`actor.py:514` reach them. `resolve --apply` against a missing creators
table logs "most likely <actors>, check AWS_DB_PREFIX; else <creators>,
deleted since this process saw it backfilled", which sends the operator to
the wrong table.
**Location:** `actingweb/db/dynamodb/actor.py:616-640`
**Recommendation:** pass the caller's context (guarded or not) into the
log, or name both tables neutrally on the unguarded paths.

### 5. A two-row deletion logs a false "Failed to delete" WARNING
**Severity:** Low
**Description:** `client_registry.py:633` iterates a list read before the
deletes. When the tagged row comes first, its cascade (Issue 3) deletes the
legacy row; the loop then calls `delete_relationship(legacy)`, which finds
no rows and returns False, and `:641` logs "Failed to delete trust
relationship …" for a deletion that worked. A False return is therefore
not a reliable failure signal either (codex suggested treating it as one;
do not, as is).
**Recommendation:** re-read before each delete, or treat "no such row" as
done.

### 6. A `DbError` part-way through the loop stops the remaining deletes
**Severity:** Low
**Description:** `client_registry.py:644-645` `except DbError: raise`
inside `for trust in trusts:`. The client row and index are already gone
by then, so a retry without `actor_id` cannot find the client. Codex rated
it High; downgraded: the single-row code before the loop had the same
ordering, and a cascade's own `DbError` is folded at `trust.py:173`.
**Recommendation:** try every row, then raise the first `DbError`.

### 7. The docs fence only "create"; the code fences renames and holder replacement too
**Severity:** Low
**Description:** `v3.16.rst:274` "the first enforced create checks for
``ux_actors_creator``", `:275`, `:869` and `configuration.rst:43` "every
actor create … raises ``DbError``". Both backends also refuse creator
renames and holder replacement (`dynamodb/actor.py:287,405`,
`postgresql/actor.py:325,429-430`). The changelog already says "creates and
creator changes".
**Recommendation:** say "create or creator change" in those passages.

### 8. A permanent misconfiguration answers 503 with `Retry-After`
**Severity:** Low
**Description:** `actingweb-spec.rst:587-590`: "Temporary problems … SHOULD
result in a 503 … Other server errors SHOULD result in the 500";
`database-backends.rst:571-572`: "A backend error a retry cannot fix …
answers **500** without ``Retry-After``". The enforcement refusal is a plain
`DbError(op)` (503 + `Retry-After`), and `configuration.rst:43` /
`v3.16.rst:275` say "retrying does not clear it". Exposure is narrow:
`check_ready()` stops an integrated app at startup first.
**Recommendation:** owner's call: a non-retryable `DbError` subclass
answered with 500, or a sentence in `database-backends.rst` naming the
exception.

### 9. The deletion fence is documented as unconditional
**Severity:** Low
**Description:** `security.rst:99` "actor deletion bumps the session
generation before it sweeps"; `deletion_finish.py:203-204` skips it on a
resume whose actor row is already gone (Iteration 4, deliberate).
**Recommendation:** name the exception, or say why no mint can race it.

### 10. Flask and FastAPI differ on `resources/read` errors
**Severity:** Low
**Description:** `mcp-applications.rst:509` "Flask and FastAPI answer
identically". A raising hook answers "Resource execution failed" on Flask
(`handlers/mcp.py:1957-1964`) and "Resource read failed" on FastAPI
(`async_mcp.py:478-484`); a raising resolver answers -32603 on Flask and
-32601 "Resource not found" on FastAPI; a coroutine hook is not awaited on
Flask. The success path is identical.
**Recommendation:** align the error branches, or narrow the sentence to
successful reads.

### 11. A `str` result carries the decorator's MIME type
**Severity:** Low
**Description:** `mcp-applications.rst:499-501` "a ``str`` is sent as it
is"; `handlers/mcp.py:659` labels it with
`metadata.get("mime_type", "application/json")`, so plain text from an
undeclared resource arrives as `application/json`.
**Recommendation:** say so in the doc, or default a `str` to `text/plain`
(a behaviour change).

### 12. Smaller accuracy points
**Severity:** Low
- `CHANGELOG.rst:46`-area and `postgresql/attribute.py:775` say callers fold
  the `delete_expired` fault "with a WARNING"; `maintenance/deletions.py:294-299`
  uses `print()`.
- Client deletion no longer matches the old two-segment
  `oauth2_client:<client_id>` shape; such rows, if any exist, now survive
  deletion (the resolver already ignored them).
- `len(parts) == 3` (`trust_lookup.py:68`) skips a real-email row whose
  email contains `:` (`trust_manager.py:479` does not escape it): very rare.
- The new fault log writes the raw exception (`dynamodb/actor.py:57`),
  which can include the role ARN; consistent with existing logs.
- `docs/sdk/attributes-buckets.rst:364` "OAuth2 client trust deleted"
  (singular).

## Overall Assessment

The code is correct and the Full tier is green on both backends (DynamoDB
5631, PostgreSQL 5431). Every issue from the previous run is fixed. The
spec sweep found no spec-conformant request that the branch now mishandles:
in particular the bool `callback` rule cannot be reached by a peer, since
the spec's subscription body has no `callback` field.

What remains is accuracy. Two public statements are wrong in ways a
consumer would act on: the changelog's 503 for marker faults on
`/oauth/token` (it is 500), and the v3.16 custom-backend list missing
`iter_rows`. The client-deletion entry overstates what was broken (the
`Trust.delete` cascade already removed the legacy row for generated ids),
and one new docstring and its ERROR are wrong for three unguarded paths.
These four are small, docs-heavy edits for one more `/iterate_plan` before
the PR; the low issues can be fixed or accepted there.
