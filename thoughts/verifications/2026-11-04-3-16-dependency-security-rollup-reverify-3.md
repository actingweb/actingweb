# Verification: 3.16 dependency-security roll-up (fourth run)

**Date:** 2026-11-04
**Plan:** thoughts/plans/2026-11-04-3-16-dependency-security-rollup.md
**Research:** see the plan's `**Research:**` line
**Branch:** release/3.16.0-dependency-security
**Commit:** 3a3ce1b

Scope: the delta since the third verification, one commit (`3a3ce1b`,
Iterations 10-13), plus the fate of that verification's twelve issues. The
earlier phases were verified in the three previous runs and are unchanged
outside this delta.

## Automated Check Results

Full tier, run on the committed tree `3a3ce1b`:

- **Browser QA:** N/A (no phase touches a page a user sees).
- **Second opinion:** the outside-voice agent ran codex (`codex exec -s
  read-only`, outside the sandbox) plus a fresh-context Claude read of the
  delta. There are eight findings, below; I re-checked the three Medium ones
  by hand. The built-in code and security reviews were not re-run: the delta
  is docs, one log message and a 20-line loop (rule: scale reviews to the
  delta).
- `ruff check actingweb tests`: pass.
- `ruff format --check actingweb tests`: pass (518 files).
- `pyright actingweb tests`: 0 errors, 0 warnings.
- `tests/integration/verify_groups.py`: all 53 groups documented.
- `make test-all-parallel` (DynamoDB): **5634 passed**, 60 skipped, 1 xfailed.
- `make test-all-parallel` (PostgreSQL): **5433 passed**, 261 skipped, 1 xfailed.
- `sphinx-build -W`: pass.

There were no failures, so nothing needed a sequential re-run. Benchmarks
were not run, since the delta touches neither list storage nor the
attribute layer.

## Phase Verification

### Iteration 10: changelog accuracy - VERIFIED (one nit, Issue 8)

- `CHANGELOG.rst` chain-revocation entry: "Logout, ``/oauth/revoke`` and
  the SPA endpoint answer either with 503 and ``Retry-After``;
  ``/oauth/token`` answers 500 ``server_error``". Checked against the code:
  - An MCP-token logout raises `TokenStoreUnavailable` on a marker write
    fault (`token_manager.py:610-614`), and
    `oauth2_endpoints.py:1198,1237` answer it with 503.
  - `/oauth/token` maps the fault to `server_error` with a 500
    (`oauth2_server.py:499-501`).
- The `delete_expired` folds match the code: a WARNING at
  `oauth_session.py:1322` and `token_manager.py:1959`, and a `print` at
  `maintenance/deletions.py:299`.
- The client-deletion entry now describes hardening, which matches the
  cascade at `trust.py:136,166`.

### Iteration 11: deletion loop - VERIFIED (Issue 3 is about its caller)

- `client_registry.py:633-662`: when a delete answers False, the loop
  re-reads the relationships. `TrustManager.relationships`
  (`trust_manager.py:193-198`) builds a fresh `Trusts` on every access, and
  DynamoDB reads it consistently (`dynamodb/trust.py:492`).
- A fault on that re-read lands in `first_fault`, never in the INFO branch.
- The `# folds DbError:` marker satisfies `test_db_fault_guard.py`.
- `test_a_row_the_cascade_already_deleted_logs_no_failure` asserts that no
  WARNING is logged and an "already deleted" INFO is.
- `test_a_fault_on_one_row_still_deletes_the_others_then_raises` asserts
  `manager.deleted == [legacy.peerid]` and that `DbError` is raised.
- Both tests failed with the loop change stashed (checked during the
  iteration).

### Iteration 12: unguarded repair ERROR - ISSUES FOUND (Issue 1)

- The three creator-record repairs pass `guarded=False`
  (`dynamodb/actor.py:758,786,817`).
- `test_an_unguarded_record_repair_names_both_tables_neutrally` asserts
  that both table names appear and "most likely" does not.
- The default `guarded=True` also applies to five property-table
  transactions; see Issue 1.

### Iteration 13: docs - ISSUES FOUND (Issues 2, 5, 6, 7)

- The `callback` and `delete_expired` items in the custom-backend list
  match `protocols.py:1036-1092,1490-1510` and both backends.
- The exception in `security.rst` matches `deletion_finish.py:203-204`.
- The error strings in `mcp-applications.rst` match `handlers/mcp.py` and
  `async_mcp.py`.
- The `iter_rows` caller list, the exempt creators, the scope of the
  `check_ready()` sentence and the async Flask hook are below.

## Previous Verification

**Previous:** thoughts/verifications/2026-11-04-3-16-dependency-security-rollup-reverify-2.md

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. Changelog said 503 for marker faults on `/oauth/token` | Fixed | Iteration 10; the statuses are given per endpoint, write and read halves both |
| 2. `iter_rows` missing from the custom-backend list | Fixed, with an error | Iteration 13; the list wrongly includes verify-orphans (new Issue 2) |
| 3. Client-deletion entry overstated the bug | Fixed | Iteration 10; the Iteration 6 rationale has a correction note |
| 4. Missing-table ERROR wrong on unguarded paths | Fixed for the three repairs | Iteration 12; the property transactions are still mislabelled (new Issue 1) |
| 5. False "Failed to delete" WARNING | Fixed | Iteration 11, `test_a_row_the_cascade_already_deleted_logs_no_failure` |
| 6. `DbError` stops the remaining deletes | Fixed | Iteration 11, `test_a_fault_on_one_row_still_deletes_the_others_then_raises` |
| 7. Docs fence only "create" | Fixed | Iteration 13 (exempt creators: new Issue 5) |
| 8. Permanent misconfiguration answers 503 | Accepted, documented | `database-backends.rst` (scope: new Issue 6) |
| 9. Deletion fence documented as unconditional | Fixed | `security.rst` |
| 10. Flask and FastAPI error branches differ | Accepted, documented | `mcp-applications.rst` (async hook: new Issue 7) |
| 11. `str` result carries the decorator's MIME type | Accepted, documented | `mcp-applications.rst` |
| 12. Smaller points | 12a and 12e fixed; 12b documented in the changelog; 12c and 12d accepted | Iterations 10 and 13 |

## Remaining Tasks

- [ ] Issues 1-3 before the PR.
- [ ] Issues 4-8: fix, or accept in the plan with a sentence each.
- [ ] `thoughts/todo/`: unchanged since the last run (no todo files touched
  in `a445c99..3a3ce1b`). Nothing the plan named is outstanding, and the
  plan has no consumer message.

## Issues Found

### 1. `guarded=True` is the default for five property transactions that never touch creators
**Severity:** Medium
**Description:** `dynamodb/actor.py:580` "`guarded: bool = True`". These
transactions take the default:
- `property_lookup.py:261` ("property lookup takeover")
- `property.py:387` ("property lookup heal")
- `property.py:455` ("property set")
- `property.py:494`
- `property.py:552` ("property delete")

When a properties or lookup table is missing, they log "Creator uniqueness
is on but a table this write needs does not exist (most likely
<actors>…; else <creators>…) … Run `actingweb-unique-creators enable
--apply`". That names the wrong tables and the wrong fix, even under
`with_unique_creator(False)`. Codex found it; I re-checked it with a grep.
Before `3a3ce1b` they logged the same message, so the bug is older than
this delta. The new docstring, though, says only creator writes are
guarded, and it is wrong for these five.
**Location:** `actingweb/db/dynamodb/actor.py:575-660`; the five callers
**Recommendation:** make the context explicit. For example, use a
`creators: Literal["guarded", "unguarded", "none"]` argument (or make
`guarded` required), and log nothing creator-specific for `"none"`.

### 2. The custom-backend list names `actingweb-verify-orphans`, which never calls the backend's `iter_rows`
**Severity:** Medium
**Description:** `docs/migration/v3.16.rst` says "``actingweb-verify-orphans``
call it" and "one without ``iter_rows`` stops those four commands before
they scan". The code works differently:
- `verify_orphans.py:232-234` imports `actingweb.db.dynamodb.actor.DbActorList`
  directly.
- `:309-312` sends `postgresql` to a raw `SELECT` and every other backend
  to DynamoDB.

On a custom backend, verify-orphans scans DynamoDB (or fails to connect to
it) instead of stopping. I re-checked this by hand.
**Location:** `docs/migration/v3.16.rst` custom-backend list
**Recommendation:** name the three commands that call it, and say that
verify-orphans supports DynamoDB and PostgreSQL only.

### 3. The fault the loop raises asks for a retry that the client manager answers "not found"
**Severity:** Medium
**Description:** the loop raises `first_fault` after the client row and its
index are deleted (`client_registry.py:661-662`). The integrations answer
that with 503 and `Retry-After`. The retry then goes through
`OAuth2ClientManager.delete_client`, which does "`client_data =
self._registry._load_client(client_id)` / `if not client_data: … return
False`" (`interface/oauth_client_manager.py:166-170`). So the leftover
trust row keeps its permissions and client deletion cannot reach it.
`registry.delete_client(client_id, actor_id=…)` would find it. I re-checked
this by hand.

The ordering is older than the delta (the single-row version raised at the
same point). The new comment "a retry could not find the rows" is true of
this wrapper only, and a 503 tells the client to retry. Actor deletion
(`_delete_actor_clients`) passes `actor_id` and is not affected.
**Location:** `actingweb/interface/oauth_client_manager.py:166-170`;
`actingweb/oauth2_server/client_registry.py:633-662`
**Recommendation:** when the client row is gone, have the manager fall
through to `registry.delete_client(client_id, actor_id=self.actor_id)`.
Alternatively, delete the trust rows before the client row, so a retry
still finds the client.

### 4. The "first fault is raised after them" claim does not hold on the cascade path
**Severity:** Low
**Description:** `trust.py:174` "`except Exception as e:  # folds DbError:
after trust delete`" wraps the cascade's `registry.delete_client`. When a
deletion starts from the tagged trust row, the fault becomes one ERROR log
line.
**Recommendation:** qualify the sentence ("raised to the client-deletion
caller").

### 5. "Every actor create and creator change … raises" leaves out the exempt creators
**Severity:** Low
**Description:** this affects `v3.16.rst` (two passages) and
`configuration.rst:43`. `trustee`, `creator` and the empty creator are
never enforced (`dynamodb/actor.py:273,350`, and the PostgreSQL partial
index), so writes for them still succeed.
**Recommendation:** add "for a non-exempt creator".

### 6. "Only code that builds `Config()` directly meets it" is too strong
**Severity:** Low
**Description:** this is the new sentence in `database-backends.rst`. A
creators table or `ux_actors_creator` index removed after `check_ready()`
passed produces the same 503 in an integrated app. The delta's own
docstring names that case (`dynamodb/actor.py`, "deleted after this
process saw it backfilled").
**Recommendation:** "at startup; a table or index removed later answers the
same 503."

### 7. An async resource hook on Flask returns its coroutine's repr
**Severity:** Low
**Description:** the doc says "on Flask the hook must be synchronous". If
it isn't, `handlers/mcp.py:1945` calls it without awaiting, and
`format_resource_read_result` stringifies the coroutine (`mcp.py:650`).
The read answers successfully with `<coroutine object …>` and nothing
reports an error.
**Recommendation:** say what happens, or refuse a coroutine function at
registration or read time.

### 8. A garbled clause in the client-deletion changelog entry
**Severity:** Low
**Description:** "by the cascade deleting the tagged row runs".
**Recommendation:** "by the cascade that deleting the tagged row runs".

## Overall Assessment

The delta does what Iterations 10-13 say. The Full tier is green on both
backends: DynamoDB 5634 and PostgreSQL 5433 passed. Of the previous run's
twelve issues, nine are fixed and three are accepted with documentation.
The deletion loop is sound: the re-read is uncached and consistent, and a
fault on it is never reported as success.

Three Medium issues remain:
- The DynamoDB missing-table ERROR is still creator-flavoured for property
  writes. This is older than the delta, but the new docstring now claims
  otherwise.
- The custom-backend list wrongly names verify-orphans.
- A trust-row fault during client deletion is answered as retryable, but
  the retry through `OAuth2ClientManager` cannot reach the leftover row.

All three are small. One more `/iterate_plan` should close them and the
five low issues before the PR.
