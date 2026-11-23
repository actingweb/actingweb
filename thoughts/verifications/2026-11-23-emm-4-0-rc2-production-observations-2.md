# Verification: 4.0.0rc3 — a failing tool answers the model, and a consumer's rc2 findings (second run)

**Date:** 2026-11-23
**Plan:** thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md
**Research:** thoughts/research/2026-11-22-emm-4-0-rc2-production-observations.md
**Branch:** fix/4.0.0-rc3-consumer-fixes
**Commit:** c1f08ce

## Automated Check Results

- **Browser QA:** N/A (no phase touches anything a user sees in a browser).
- **Second opinion:** provider: codex CLI (unsandboxed, read-only) and a
  fresh-context Claude reviewer, through the outside-voice agent, run twice
  on the fix deltas and scaled to them:
  - on `9e47157..1a7d000` (iterations 1 to 6): seven findings, three
    Medium, four Low, none High. All fixed in `cf52f9d` (iterations 7 to
    10).
  - on `1a7d000..cf52f9d` (iterations 7 to 10): five findings, three
    Medium, two Low. All fixed in `c1f08ce` (iterations 11 and 12).
  - `cf52f9d..c1f08ce` was not sent out again: it is the fix the second
    review prescribed (the caller's values checked before the store call,
    the type test removed) and two wording changes, each pinned by a test
    or read against the code below.
- **Built-in code review and security review:** run on `9e47157` (first
  verification); not re-run on the deltas, which the second opinion
  covered.
- `poetry run ruff check actingweb tests`: pass (on `c1f08ce`).
- `poetry run ruff format --check actingweb tests`: pass (on `c1f08ce`).
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings (on `c1f08ce`).
- `poetry run python tests/integration/verify_groups.py`: pass (on `cf52f9d`).
- `make test-all-parallel` (DynamoDB): pass, 8635 passed, 217 skipped, 2
  xfailed, on `cf52f9d` (the parallel run; no failure to re-run).
- `DATABASE_BACKEND=postgresql … make test-all-parallel` (PostgreSQL):
  pass, 8386 passed, 466 skipped, 2 xfailed, on `cf52f9d` (the parallel
  run).
- `poetry run sphinx-build -W …`: pass, on `cf52f9d` and again on `c1f08ce`.
- **On `c1f08ce` itself** (two backend methods, one test file, three
  wording changes after `cf52f9d`): the fast tier, 6705 passed, 191
  skipped, 2 xfailed (DynamoDB Local); `tests/test_conditional_update_attr.py`
  on PostgreSQL, 30 passed. The Full tier was not repeated for it; the
  pull request's CI runs both backends on this commit.
- Benchmarks: not re-run; no iteration touched a list or attribute storage
  path beyond the strict branch, which the default path does not enter.

## Phase Verification

### Phase 1: A failing tool answers the model - VERIFIED

**Changes verified:**
- `actingweb/handlers/mcp.py` `_tool_failure_result` - the `try` now ends
  after the hook call in both handlers; the result is formatted outside it.
- `actingweb/mcp/errors.py` - `ToolError`, `fault_behind`, `fault_log_level`;
  the MCP path and the REST route use the same two helpers.
- `actingweb/interface/hooks.py` - `ToolError` leaves all four loops;
  `actingweb/handlers/actions.py`, `async_actions.py` - the four verbs
  answer it with 400 and the message.
- `actingweb/handlers/mcp.py` - the quiet branch tests
  `interface.authenticated_views.PermissionError`, not the builtin.

**Tests verified:**
- `tests/test_mcp_tool_failure_results.py` (55 cases),
  `tests/test_tool_error_on_actions_route.py` (14 cases).

**Deviations from plan:**
- None left. The plan's Decisions, ACs and Spec Delta were amended by
  iterations 2 to 8 and match the code.

### Phase 2: The redirect, two list readers, and `store.loaded` - VERIFIED

Unchanged since the first verification except the changelog's **Behavior
change** sentence, which is there.

### Phase 3: Two additive names - VERIFIED

**Changes verified:**
- `actingweb/attribute.py` - the wrapper passes `strict` to the backend
  only when asked; `_confirm_conditional_update` is gone.
- `actingweb/db/dynamodb/attribute.py`, `db/postgresql/attribute.py` - with
  `strict`, the caller's values are checked before the store call
  (`normalize_json`; `json.dumps(…, sort_keys=True)`), a missing row or a
  failed condition answers `False`, and anything else inside the `try`
  raises `DbError` from the backend's exception.
- `actingweb/db/protocols.py` - the keyword and its contract.
- `actingweb/mcp/token_cache.py` - the docstring matches
  `authenticate_and_get_actor_cached`.

**Tests verified:**
- `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate` (14
  cases), on both backends.

**Security property demonstrated (addendum):** the plan claims that a
conditional update answers `True` only to the call that changed the row.
`tests/test_conditional_update_attr.py:829`
`test_strict_does_not_claim_another_writers_identical_value` writes
`{"v": 2}` over `{"v": 1}` through the backend, then asks the wrapper for
the same change with `strict=True`, and asserts
`self.attrs.conditional_update_attr(…, strict=True) is False`. The plan
also claims that no exception text reaches an MCP client: every case of
`tests/test_mcp_tool_failure_results.py:191` and `:497` places a marker in
the raised exception and asserts `SECRET not in repr(envelope)`.

**Todos (addendum):** unchanged since the first verification and still
consistent: 38 files, 38 `INDEX.md` rows; the four closed todos are
deleted; each deferral has a file.

**Consumer message:** the plan has no message phase. What the reporting
consumer should be told, checked against `c1f08ce`:

> rc3 answers a store fault raised by a tool hook as HTTP 200 with
> `isError: true` and one of four fixed texts ("The service is temporarily
> unavailable. Try again shortly."; "A change was saved, but the tool did
> not finish. Check the current state before calling it again."; "The
> request could not be stored. Trying again will not help."; "That address
> already belongs to another account. Use a different one."), and any
> other exception as "The tool failed. The error was logged.".
> `initialize`, `tools/list` and a fault before the hook runs are
> unchanged. `raise ToolError("…")` (`actingweb.mcp`) sends your own text;
> on the REST `/actions` route it answers 400 with `{"error": "…"}`.
> `complete_client_authorization` appends to a redirect URI's own query.
> `Attributes.conditional_update_attr(strict=True)` raises `DbError` on a
> fault; `actingweb.mcp.is_token_cached(token, config)` replaces reading
> `_token_cache`; `actingweb.faults.classify_fault(exc)` replaces importing
> `_errors`. A deletion record is not in rc3.

## Acceptance Criteria

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-1 to AC-5, AC-25 | `tests/test_mcp_tool_failure_results.py:191` - `assert result["content"] == [{"type": "text", "text": text}]`, `assert response.status_code == 200`, `assert SECRET not in repr(envelope)` | Yes | Pass |
| AC-6 | `:444`, `:458`, `:539` | Yes | Pass |
| AC-7 | `:424` - `assert envelope["result"] == own` | Yes | Pass |
| AC-8 | `:235` - one line, its level, no status | Yes | Pass |
| AC-9 | `tests/test_db_fault_http.py:103`, `:180` | Yes | Pass |
| AC-10, AC-11 | `tests/test_public_fault_classifier.py:95`, `:104`, `:126`, `:165` | Yes | Pass |
| AC-12, AC-13, AC-26 | `tests/test_oauth2_authorization_redirect.py:25`, `:40`, `:55`, `:63`, `:86`; `tests/integration/test_oauth2_trust_binding.py:539` | Yes | Pass |
| AC-14 | `tests/test_db_fault_callers.py:404`, `:425` | Yes | Pass |
| AC-15 | manual: `docs/reference/hooks-reference.rst`, `actor_deleted` | n/a | Pass |
| AC-16 | `tests/test_conditional_update_attr.py:772` | Yes | Pass (both backends) |
| AC-17 | `:800`, `:810` | Yes | Pass |
| AC-18 | `:787`, `:918` - `assert "strict" not in seen[0]`, `assert seen[1]["strict"] is True` | Yes | Pass |
| AC-19, AC-20 | `tests/test_mcp_token_cache_query.py:41`, `:63`, `:78`, `:87` | Yes | Pass |
| ~~AC-21~~, ~~AC-22~~, ~~AC-27~~ | dropped with reasons; `get_deletion_record` and `_confirm_conditional_update` are not in the tree | - | - |
| AC-23 | `tests/test_mcp_tool_failure_results.py:255`, `:418` | Yes | Pass |
| AC-24 | `:497` - `assert envelope["error"]["message"] == (message or expected)`, and the log names the prompt or URI | Yes | Pass |
| AC-28 | `tests/test_conditional_update_attr.py:829` - `is False` | Yes | Pass (both backends) |
| AC-29 | `:849` - `assert isinstance(raised.value.__cause__, RuntimeError)` | Yes | Pass |
| AC-30 | `tests/test_tool_error_on_actions_route.py:88` (four verbs, sync and async) - `assert json.loads(handler.response.body) == {"error": "A note needs a title."}`; `:50` - `assert calls == ["named"]` | Yes | Pass |
| AC-31 | `tests/test_mcp_tool_failure_results.py:282` - `startswith("Tool 'failing' failed with a store fault (retryable)")`; `:335`; `tests/test_tool_error_on_actions_route.py:127` | Yes | Pass |
| AC-32 | `tests/test_mcp_tool_failure_results.py:395` - `assert envelope["error"] == {"code": -32603, "message": "Internal error"}` | Yes | Pass |
| AC-33 | `tests/test_conditional_update_attr.py:879` - `pytest.raises((TypeError, ValueError))` for `old_data` and `new_data`, row present and absent; `:894` - `pytest.raises(DbError)` with a `ValueError` cause | Yes | Pass (both backends) |

## Previous Verification

**Previous:** thoughts/verifications/2026-11-23-emm-4-0-rc2-production-observations.md
**Iterations since:** entries 1 to 12 of the iterations log

| Issue then | Status now | Evidence |
| --- | --- | --- |
| 1. `strict=True` can tell two callers they both won, and three other cases (High) | Fixed | iterations 1, 9, 11; `tests/test_conditional_update_attr.py:829`, `:849`, `:864`, `:879`, `:894` |
| 2. The guide's advice hides a store outage (Medium) | Fixed | iterations 3, 8; `actingweb/mcp/errors.py` `fault_behind`; `tests/test_mcp_tool_failure_results.py:282` |
| 3. `ToolError` swallowed on REST (Medium) | Fixed | iterations 2, 8; `tests/test_tool_error_on_actions_route.py` |
| 4. Caller-influenced text logged unescaped (Low) | Fixed | iteration 5; `tests/test_mcp_tool_failure_results.py:346` |
| 5. `False` when the answer was lost and the row moved on (Low) | Accepted as-is, documented | `actingweb/attribute.py` (Returns), `docs/sdk/attributes-buckets.rst`; `todo/conditional-write-ambiguous-after-sdk-retry.md` |
| 6. Python equality in the confirm step (Low) | Fixed (the step is gone) | iteration 1; `:864` |
| 7. The `try` covers result formatting (Low) | Fixed | iteration 4; `tests/test_mcp_tool_failure_results.py:395` |
| 8. `_failure_response` names nothing; `PermissionError` noise (Low) | Fixed | iterations 5, 7; `:497`, `:365` |
| 9. `classify_fault` depth (Low) | Fixed (documented) | iteration 6; `actingweb/faults.py` docstring |
| 10. `is_token_cached` misdescribes a hit (Low) | Fixed | iteration 6; `actingweb/mcp/token_cache.py` |
| 11. The strict `DbError` cannot be classified (Medium) | Fixed | iteration 1; `tests/test_conditional_update_attr.py:849` |
| 12. Two documentation defects (Low) | Fixed | iteration 6; `docs/guides/mcp-applications.rst` (resources), `CHANGELOG.rst` (FIXED, first entry) |

## Remaining Tasks

- [ ] None from the plan. The deferrals are todos:
  `deletion-cleanup-across-processes.md`,
  `oauth-redirect-uri-registration-checks.md`,
  `conditional-update-fault-log-names-the-row.md`,
  `sync-mcp-handler-does-not-await-async-tool-hooks.md`,
  `mcp-get-polled-after-the-405.md` (waits on the reporter; needs its
  answer before 4.0.0).

## Issues Found

### Issue 1: A subclass that overrides an action verb loses the `ToolError` answer
**Severity:** Low
**Description:** `answers_tool_error` decorates the four verb methods of
`ActionsHandler`. A consumer subclass that overrides one without the
decorator lets a `ToolError` reach the integration, which answers 500. No
such subclass is in the tree, and the handlers are not a documented
extension point. Owner-only (it needs the application's own subclass).
**Location:** `actingweb/handlers/actions.py:103`
**Recommendation:** None now; accepted.

### Issue 2: Unverified notes of the second opinion
**Severity:** Low
**Description:** Two things were not traced and are recorded as such: a
bad `AWS_DB_HOST` may surface as a bare `ValueError` from botocore (under
strict it now becomes a `DbError`, as it arises inside the store call),
and an MCP client that validates `structuredContent` against a declared
`outputSchema` may not skip the check for `isError: true`.
**Location:** n/a
**Recommendation:** None; neither is a behaviour this plan can pin with a
test in this repository.

## Spec Merge

- `thoughts/specs/mcp-server.md` - merged: 10 added (MCP-12 to MCP-21), 2
  decisions (MCP-D4, MCP-D5).
- `thoughts/specs/oauth-client-registration.md` - merged: 1 added (OCR-8).
- `thoughts/specs/property-lists.md` - merged: 1 modified (PLS-1).
- `thoughts/specs/store-faults.md` - created (partial): 4 statements
  (SFT-1 to SFT-4), 3 decisions; row added to `thoughts/specs/README.md`.
- `thoughts/specs/actor-deletion.md` - not created: the deletion record
  left the plan.
- The merge includes what iterations 1 to 12 changed (strict in the
  backends, `ToolError` on REST, the fault line for a wrapped fault, the
  unformattable result).

## Overall Assessment

The plan is implemented and its three phases hold. The first verification's
twelve issues are fixed, as are the twelve points the two second opinions
raised against the fixes; no finding at Medium or above is open, and the
two Low items left are owner-only or not testable here. Both backends were
green on the Full tier one commit before the tip (`cf52f9d`: DynamoDB 8635
passed, PostgreSQL 8386 passed); the tip adds a narrow change to the two
backend methods of strict mode, which the fast tier and the PostgreSQL run
of its test file cover, and CI runs the full matrix on it.

What deserves the owner's eye is scope, not correctness. The verification
loop added behaviour the approved plan did not have, each recorded in the
iterations log: `ToolError` is honoured on the REST `/actions` route (400
with the message, and no fall-through to the wildcard hook), and
`HookRegistry.execute_action_hooks()` now raises it. Strict mode went back
to the backends after the wrapper design the outside voice recommended
proved wrong, so a custom attribute backend must accept `strict` to serve
a caller that asks for it. The `GET /mcp` question is still with the
reporter and needs an answer before 4.0.0.
