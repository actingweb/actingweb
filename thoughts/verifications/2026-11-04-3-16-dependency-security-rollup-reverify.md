# Verification: 3.16 roll-up, re-verification after the first iteration

**Date:** 2026-11-04
**Plan:** thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md
**Research:** none of its own (the plan's todos are its research)
**Branch:** release/3.16.0-dependency-security
**Commit:** 5080b7c (the iteration is `168d061..5080b7c`; the whole plan is `8bbaa88..5080b7c`)

This re-run covers the plan's Iterations 1-5 and the issue accepted
alongside them. The reviews were scaled to the delta (the owner's rule):
the Full tier ran on the whole tree, and the outside voice and code review
ran on the iteration commit. The phases verified on 2026-11-04 are
unchanged outside the iteration's files.

## Automated Check Results

- **Browser QA:** N/A (no phase touches anything a user sees).
- **Second opinion:**
  - **Codex** (`codex review --base 168d061`, outside the sandbox): no
    actionable defects.
  - **Fresh-context Claude** (outside voice, briefed as the security
    reviewer for the delta too): eight findings, folded below. It
    confirmed the guard placement, that no pre-backfill write path is
    blocked, the fixture override order, and the resume path's fault
    handling.
  - **Built-in code review** (`/code-review high 168d061..5080b7c`): ten
    findings, folded below.
  - **Built-in security review:** not re-run as a separate pass (scaled to
    the delta). The outside voice carried the security brief, and the
    first run's review of the whole diff found nothing.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass (518 files).
- `poetry run pyright actingweb tests`: 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: pass (53 groups).
- `make test-all-parallel` (DynamoDB): pass, 5627 passed, 60 skipped,
  1 xfailed.
- `make test-all-parallel` (PostgreSQL): pass, 5429 passed, 258 skipped,
  1 xfailed.
- `sphinx-build -W ...`: pass.

## Phase Verification

### Iteration 1: DynamoDB requires a backfilled creators table - VERIFIED (low findings)

- **Guard placement:** `actingweb/db/dynamodb/actor.py:342` (create),
  `:278` (non-exempt rename), `:396` (replace holder).
- **Probe module:** `actingweb/db/dynamodb/_backfill_probe.py:14,17,40` (a
  positive cache keyed by table name).
- **Maintenance:** `unique_creators.py:1110` (`disable` resets the probe).
  `enable`'s backfill writes through `Creator(...).save()` or
  `record_for_actor_as_read`, not `DbActor`. The command runs with
  `unique_creator=False` (`unique_creators.py:179-181`), and
  `move_default_creator` enforces only once `backfill_complete()` is true.
  So no pre-backfill path is blocked (checked by the outside voice and
  here).
- **Tests:**
  - `tests/test_unique_creator_fail_closed.py:108`: an empty table refuses
    create and replace with nothing written and the ERROR naming it. Once
    the marker exists, the create claims with one probe read.
  - `:160`: a rename is refused and an exempt rename is not probed.
  - `tests/integration/test_unique_creator_states.py:824`: the prewarmed
    empty table refuses, with `_record(creator) is None`.
- **Fixture:** `tests/_lookup_probe.py` `_stub_dynamodb_backfill_probe` is
  function-scoped. Pytest runs autouse fixtures before requested ones and
  monkeypatch undoes in reverse, so `real_dynamodb_backfill_probe`
  overrides it reliably.

### Iteration 2: client deletion covers every OAuth2 source - ISSUES FOUND

- **Arm 3:** `actingweb/oauth2_server/trust_lookup.py:15,25,88` (sources,
  origin gate, segment rule). The creation path shares
  `normalize_client_id` (`interface/trust_manager.py:480-482`).
- **Tests:** `tests/test_client_trust_lookup.py:144` (four sources) and
  `:155` (a peer-protocol lookalike is skipped). They pass, but Issue 1
  below is a gap they do not cover.

### Iteration 3: resource hook arguments - VERIFIED (low findings)

- **Code:** `actingweb/mcp/uri.py:85-96`, called at `handlers/mcp.py:1947`
  and `handlers/async_mcp.py:465`.
- **Test:** `tests/test_mcp_resource_read_permissions.py:311`, both
  handlers `{"uri": request uri, "id": "7"}` against a client `id=999`.
- **Docs:** the changelog and `mcp-applications.rst` name the
  Flask-side change, the `content` unwrap, the splat risk and the reserved
  `uri`.

### Iteration 4: resume without the actor row - VERIFIED

- **Code:** `actingweb/deletion_finish.py:203`.
- **Test:** `tests/test_deletion_finish.py:585` (`bump.assert_not_called()`,
  no generation left).
- **The code review's concern does not hold:** it said skipping the bump
  leaves stamped tokens unfenced. `Actor.delete()` wipes the buckets,
  `_internal` included, before the row (`actor.py:1144-1148`). So when the
  row is gone, `current()` is `None`, and a stamped credential's guard
  refuses it. The unstamped case is the accepted previous Issue 5.

### Iteration 5: test hygiene - VERIFIED (one low finding)

- `tests/integration/_actor_list_stub.py:19` is used by both script tests;
  the annotations are added.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-04-3-16-dependency-security-rollup.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. DynamoDB checks "table exists", not "enforced" (High) | Fixed | `db/dynamodb/actor.py:278,342,396`; `_backfill_probe.py:40`; `tests/test_unique_creator_fail_closed.py:108`; `tests/integration/test_unique_creator_states.py:824` |
| 2. Legacy rows of other OAuth2 sources not deleted (Medium) | Partly fixed | Arm 3 covers every source (`trust_lookup.py:88`), but deletion still removes one row: Issue 1 below |
| 3. A template variable could override `uri` (Low) | Fixed | `mcp/uri.py:96`; `tests/test_mcp_resource_read_permissions.py:311` |
| 4. Changelog omitted the `content` unwrap (Low) | Fixed | the D7 FIXED entry in `CHANGELOG.rst` |
| 5. Finisher fence and unstamped tokens (Low) | Accepted as-is | Plan, "Accepted, not changed: the finisher fence and unstamped tokens" |
| 6. Orphan generation row on a resumed finish (Low) | Fixed | `deletion_finish.py:203`; `tests/test_deletion_finish.py:585` |
| 7. PostgreSQL probe docstring overstated (Low) | Fixed on PostgreSQL; the same overstatement exists on DynamoDB | `db/postgresql/actor.py:108-111`; Issue 4 below |
| 8. Missing-table ERROR always blamed `creators` (Low) | Fixed, but the wording now points the wrong way | `db/dynamodb/actor.py:621`; Issue 5 below |
| 9. Arm 3 had no `established_via` gate (Low) | Fixed | `trust_lookup.py:25` `_oauth2_origin`; `tests/test_client_trust_lookup.py:155` |
| 10. Missing type hints on new test functions (Low) | Fixed for those; the new `shadow` hook and helpers lack them | Issue 9 below |
| 11. Duplicated normaliser and stub, no-op reset (Low) | Fixed | `trust_lookup.py:18`, `trust_manager.py:480`; `_actor_list_stub.py:19`; the reset is gone from `_enable_postgresql` |

## Remaining Tasks

- [ ] Issues 1 and 2 go to `/iterate_plan` if they are to land before the
  PR; they stay in this plan (the owner's rule: findings are addressed in
  the plan, not filed as todos).
- [ ] The low issues: fix, or accept in the plan with a sentence each.

## Issues Found

### 1. Client deletion removes one row; a legacy row survives beside a tagged one
**Severity:** Medium
**Description:** `find_client_trust` returns the first match, and arm 1
wins: `trust_lookup.py:57-59` returns `trust` when
`getattr(trust, "oauth_client_id", None) == client_id`.
`client_registry.py:621-631` deletes only that row. An upgraded actor can
hold both `oauth2:alice_at_x_dot_com:mcp_x` (legacy, no `oauth_client_id`)
and `oauth2_client:alice_at_x_dot_com:mcp_x` (tagged, written by
`trust_manager.py:529`). They have different peer ids, so both exist.
Deleting the client removes the tagged row, and the legacy row keeps its
permissions. This predates the diff: master also stopped after its first
delete (`client_registry.py` at `8bbaa88`, `break` after a successful
delete). But master's pick depended on row order, while now the tagged row
always wins. So the case Iteration 2 set out to fix still fails whenever a
tagged row exists. Raised by both the outside voice and the code review.
**Location:** `actingweb/oauth2_server/trust_lookup.py:57-91`,
`actingweb/oauth2_server/client_registry.py:621-631`.
**Recommendation:** add a deletion form that returns every arm-1 and
arm-3 match, and delete each one. Keep the resolver's single-row answer.
Add a test with a tagged and a legacy row for one client.

### 2. A probe read fault refuses every enforced write and logs no reason
**Severity:** Medium
**Description:** `actingweb/db/dynamodb/actor.py:51-55` has
`except Exception as e: raise DbError(op) from e`. The not-backfilled
branch logs the remedy; the fault branch logs nothing. Take a runtime role
that can write the table but lacks `GetItem` on `<prefix>_creators` (the
changelog's IAM note). Every create and rename becomes a 503 that retries
never clear, and the only trace is "database error during actor create".
**Recommendation:** log at ERROR, with the table name, the fault and the
IAM hint, before raising.

### 3. A refused write reads the marker twice, and the two reads can disagree
**Severity:** Low
**Description:** `actor.py:51-53` calls `creators_backfilled()` and then
`creators_backfill_state()`. That is two consistent GetItems per refusal.
If `enable` writes the marker between them, the write is refused and
logged "is not backfilled" although the second read said "complete".
Separately, `check_ready()` reads the same marker through
`missing_enforcement` and never fills `_seen`, so each process pays one
more read on its first enforced write. That is the cost class
`tests/test_cold_start_budget.py` guards.
**Recommendation:** read once and branch on the one state. Fill `_seen`
when `missing_enforcement` sees "complete".

### 4. The DynamoDB constructor docstring overstates the cache's guarantee
**Severity:** Low
**Description:** `actor.py:634-637` says the write "raises `DbError`
while the table is missing or not backfilled". But a worker that cached
"backfilled" keeps claiming after `disable --apply` empties the table, and
then `Creator.creator.does_not_exist()` passes for an address an actor
holds. PostgreSQL's docstring now says this; DynamoDB's does not. The
consequence on DynamoDB is worse: a silent duplicate, not just writing
without the index.
**Recommendation:** add the same caveat to the DynamoDB constructor
docstring. `disable` already says to turn the application flag off first.

### 5. The transaction-time ERROR now points at the less likely table
**Severity:** Low
**Description:** `actor.py:621` says "most likely `<prefix>_creators`".
But every enforced transaction now passes the backfill probe first, and
the probe reports a missing creators table itself. So a `ResourceNotFound`
there is more likely the actor table (prefix drift, a deleted table).
**Recommendation:** name the actor table first, and keep `AWS_DB_PREFIX`.

### 6. The arm-3 docstring claims arm 2's gate; the gates differ
**Severity:** Low
**Description:** `trust_lookup.py:47` reads "(as arm 2 judges it)". Arm 2
checks `via in ("oauth2", "oauth2_client")` (`:69`), while
`_oauth2_origin` also accepts `oauth2_interactive`. The difference is
deliberate (the resolver does not authorise interactive real-email
rows). Unstated, though, it invites an edit that widens authorisation.
**Recommendation:** say that arm 3's gate is wider on purpose, and why.

### 7. Arm 3 can match a client-less `oauth2:<identifier>` row
**Severity:** Low
**Description:** Legacy client-less peer ids are
`identifier.replace("@", "_at_").replace(".", "_dot_")`
(`trust_manager.py:389`, no `_colon_`). Arm 3 matches any OAuth2-source
row whose last `:` segment equals the client id (`trust_lookup.py:86-89`).
An identifier containing `:` and ending in a client id would match. Client
ids are `mcp_` plus 32 hex characters from `secrets.token_hex(16)`
(`client_registry.py:93`), so this is very unlikely to happen.
**Recommendation:** require exactly three segments, or reconstruct the
row's full peer id.

### 8. Doc accuracy: the probe module's rationale, a dangling cross-reference, pattern resources
**Severity:** Low
**Description:**
- `_backfill_probe.py:3-5` says the module lets a test stub without
  importing the models. That is false: the package `__init__` imports every
  model. The fixture works because it is function-scoped.
- `unique_creators.py:299`'s `:func:` reference names
  `actingweb.db.dynamodb.actor.creators_backfill_state`, which no longer
  exists.
- A hand-written `uri_pattern` resource gets no variables
  (`mcp/uri.py:76` returns `{}`). So "a client param never replaces a
  variable the permission check judged" (`mcp-applications.rst`) holds for
  templates only.
- `resource_arguments` drops a template variable named `uri` silently. The
  docs say so, but registration does not warn.
**Recommendation:** correct the two docstrings. For a pattern match, return
`re.fullmatch(...).groupdict()`, or narrow the doc sentence to templates.
Optionally warn at registration on a variable named `uri`.

### 9. Type hints missing on the new test hook and helpers
**Severity:** Low
**Description:** In `tests/test_mcp_resource_read_permissions.py`, the
hook `def shadow(actor, method_name, params):` is unannotated, `handler_cls`
in `_read` is untyped, and `_read` and `_both` have no return types.
CLAUDE.md requires type hints on all functions.
**Recommendation:** annotate them.

## Overall Assessment

The iteration closed the High finding. A DynamoDB process that skipped
`check_ready()` now refuses enforced writes against a missing or
unbackfilled creators table. A test reproduces the empty table that a
refused first start leaves, so both backends now mean "enforced" and the
docs sentence is true. The Full tier is green on both backends (DynamoDB
5627, PostgreSQL 5429), and Codex found nothing in the delta.

Two Medium findings remain.
- **Client deletion still removes one row** (Issue 1). This predates the
  roll-up, but the case Iteration 2 targeted still fails when a tagged row
  sits beside the legacy one.
- **The probe's fault branch is silent** (Issue 2). It refuses writes
  without naming the cause.

Neither weakens the security fixes, which the first verification
demonstrated. Both are small: one more short `/iterate_plan` with a
regression test each, and the low issues fixed or accepted, makes the PR
ready. The plan's `verified:` link points here. The verification covers
the whole plan as it stands; its remaining issues are listed above.
