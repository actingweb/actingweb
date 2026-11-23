# Verification: 4.0.0rc3 — a failing tool answers the model, and a consumer's rc2 findings

**Date:** 2026-11-23
**Plan:** thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.md
**Research:** thoughts/research/2026-11-22-emm-4-0-rc2-production-observations.md
**Branch:** fix/4.0.0-rc3-consumer-fixes
**Commit:** 9e47157

## Automated Check Results

- **Browser QA:** N/A (no phase touches anything a user sees in a browser).
- **Second opinion:** provider: codex CLI (unsandboxed, read-only) and a
  fresh-context Claude reviewer, through the outside-voice agent. Seven
  findings: two Medium, five Low, none High, none reachable
  unauthenticated. Issues 2, 3, 5, 6, 7, 8 and 9 below.
- **Built-in code review (high):** seven findings, four "important" (all in
  `conditional_update_attr(strict=True)`), three nits. Issues 1, 10, 11
  and 12 below.
- **Built-in security review:** the skill received an empty diff (nothing
  was committed when it ran), so it was done by reading the diff in the
  calling context. No high-confidence vulnerability; the one finding with
  security weight is Issue 1.
- `poetry run ruff check actingweb tests`: pass.
- `poetry run ruff format --check actingweb tests`: pass.
- `poetry run pyright actingweb tests`: pass, 0 errors, 0 warnings.
- `poetry run python tests/integration/verify_groups.py`: pass.
- `make test-all-parallel` (DynamoDB): pass, 8610 passed, 217 skipped, 2
  xfailed (the parallel run; no failure to re-run).
- `DATABASE_BACKEND=postgresql … make test-all-parallel` (PostgreSQL):
  pass, 8361 passed, 466 skipped, 2 xfailed (the parallel run).
- `poetry run sphinx-build -W …`: pass, build succeeded.
- Benchmarks (`tests/performance -m benchmark`, run alone, DynamoDB Local;
  the plan touched the attribute layer): 26 passed. No list or attribute
  storage path changed; the default `conditional_update_attr` makes the
  same calls as before. No baseline was recorded to compare against.

All runs are on the tree committed as `9e47157`.

## Phase Verification

### Phase 1: A failing tool answers the model - ISSUES FOUND

**Changes verified:**
- `actingweb/faults.py` - matches the plan: `FaultClass`, `Fault`,
  `classify_fault`; `__all__` is those three; the order is `CreatorTaken`,
  `DeletionInProgress`, `DbErrorAfterWrite`, `AttributeKeyCollision`,
  permanent, transient.
- `actingweb/interface/integrations/_errors.py` - `db_error_answer` derives
  from `classify_fault` and still raises `TypeError` for a non-`DbError`.
- `actingweb/actor.py:4867` - imports `is_permanent` from `actingweb.faults`.
- `actingweb/handlers/mcp.py`, `async_mcp.py` - `_tool_failure_result`,
  `_failure_response`; no `str(e)` is left in either file.
- `actingweb/mcp/errors.py` - `ToolError`, exported.
- Docs and changelog - present; one stale sentence (Issue 12).

**Tests verified:**
- `tests/test_mcp_tool_failure_results.py` - 11 failure classes through
  both handlers; every case asserts a marker placed in the exception is
  absent from the response. Meaningful.
- `tests/test_public_fault_classifier.py` - the rc2 HTTP table is literal.

**Failure scenarios:**
- "the model repeats the write" - documented, `docs/guides/mcp-applications.rst` ("must be safe to repeat"). But the advice it gives creates Issue 2.
- "no 5xx for a tool fault" - the ERROR line is pinned by `tests/test_mcp_tool_failure_results.py:235`.
- "the helper itself raises" - the outer catch, `handlers/mcp.py:1140`.
- "a classifier reorder" - `tests/test_public_fault_classifier.py:51`.

**Deviations from plan:**
- The `try` around the hook also covers result formatting (Issue 7); the
  plan says only the hook call changes.

### Phase 2: The redirect, two list readers, and `store.loaded` - VERIFIED

**Changes verified:**
- `actingweb/oauth2_server/oauth2_server.py` `redirect_with_params` - used
  by `_complete` and `_denied`; the registered URI is kept byte for byte.
- `actingweb/property.py` - both broad handlers are gone.
- `docs/reference/hooks-reference.rst`, `docs/sdk/attributes-buckets.rst` -
  the `store.loaded` pattern is where the plan put it.

**Tests verified:**
- `tests/test_oauth2_authorization_redirect.py`, the integration test at
  `tests/integration/test_oauth2_trust_binding.py:539`,
  `tests/test_db_fault_callers.py:404` and `:425`. Meaningful.

**Deviations from plan:**
- The helper splits the string by hand where the plan said `urlsplit`:
  acceptable, it is what keeps the URI unnormalised, and the plan's notes
  say so.
- The changelog entry lacks its **Behavior change:** sentence (Issue 12).

### Phase 3: Two additive names - ISSUES FOUND

**Changes verified:**
- `actingweb/mcp/token_cache.py`, `handlers/mcp.py`
  `_token_cache_entry_is_fresh` - one pure predicate serves both. The
  docstring misdescribes a hit (Issue 11).
- `actingweb/attribute.py` `_confirm_conditional_update` - implemented as
  the plan (after the outside voice) describes, and wrong in four ways
  (Issue 1).

**Tests verified:**
- `tests/test_mcp_token_cache_query.py` - meaningful.
- `tests/test_conditional_update_attr.py:737` - the tests pass and pin the
  design; `:829` (`test_strict_counts_a_write_that_landed`) pins the
  defect.

**Todos (addendum):** the four files the plan closes are deleted with
their `INDEX.md` rows; item 7 and the deletion record are in
`todo/deletion-cleanup-across-processes.md`; the three deferrals each have
a file and a row. 38 files, 38 rows.

**Consumer message:** the plan has no separate message phase. What the
reporting consumer builds on (research, "The reporter's reply") was checked
against the tree: HTTP 200, `isError: true`, fixed text, no fault text,
through the sync and async handlers, `initialize` and `tools/list`
unchanged: holds. The texts differ from the ones the consumer saw in the
first triage (it saw none; the plan's first set was never sent). The
redirect for `complete_client_authorization`: holds.

## Acceptance Criteria

| AC | Test | Asserts the behaviour? | Result |
| --- | --- | --- | --- |
| AC-1 | `tests/test_mcp_tool_failure_results.py:191` ids `transient`, `deleting` - `assert result["content"] == [{"type": "text", "text": text}]`, `assert response.status_code == 200`, `assert "Retry-After" not in response.headers` | Yes | Pass |
| AC-2 | same, ids `stored`, `stored_permanent_cause` | Yes | Pass |
| AC-3 | same, ids `permanent`, `collision` | Yes | Pass |
| AC-4 | same, id `conflict` | Yes | Pass |
| AC-5 | same, ids `other`, `other_base` - `assert SECRET not in repr(envelope)` | Yes | Pass |
| AC-6 | `:295`, `:309`, `:381` - `assert response.status_code == 503`, `assert envelope["error"]["code"] == -32603` | Yes | Pass |
| AC-7 | `:275` - `assert envelope["result"] == own` | Yes | Pass |
| AC-8 | `:235` - `assert len(lines) == 1`, the level, `assert "503" not in …` | Yes | Pass |
| AC-9 | `tests/test_db_fault_http.py:103`, `:180` - `assert response.status_code == 500`, `assert "Retry-After" not in response.headers` | Yes | Pass |
| AC-10 | `tests/test_public_fault_classifier.py:95`, `:104`, `:126` | Yes | Pass |
| AC-11 | `:165` - literal `(status, headers, error)` tuples | Yes | Pass |
| AC-12 | `tests/test_oauth2_authorization_redirect.py:25`; `tests/integration/test_oauth2_trust_binding.py:539` - `assert done["url"].count("?") == 1`, `query["tenant"] == ["a"]` | Yes | Pass |
| AC-13 | `tests/test_oauth2_authorization_redirect.py:40` - the exact rc2 string | Yes | Pass |
| AC-14 | `tests/test_db_fault_callers.py:404` - `assert raised.value is bug` | Yes | Pass |
| AC-15 | manual: `docs/reference/hooks-reference.rst`, `actor_deleted`, "Reading `actor.store` here"; docs build | n/a | Pass - the paragraph and example are there |
| AC-16 | `tests/test_conditional_update_attr.py:772` - `pytest.raises(DbError)` at both seams | Yes | Pass (both backends) |
| AC-17 | `:800`, `:810` | Yes, but see Issue 1: `False` has meanings the AC does not name | Pass |
| AC-18 | `:787`, `:855` | Yes | Pass |
| AC-19 | `tests/test_mcp_token_cache_query.py:41` | Yes | Pass |
| AC-20 | `:63`, `:78`, `:87` | Yes | Pass |
| ~~AC-21~~, ~~AC-22~~ | dropped with a reason; no `get_deletion_record` in the tree | - | - |
| AC-23 | `tests/test_mcp_tool_failure_results.py:255`, `:269` | Yes | Pass |
| AC-24 | `:348` - `assert envelope["error"]["message"] == (message or expected)` | Yes | Pass |
| AC-25 | `:191` ids `token_store`, `single_use`, `newer_format` | Yes | Pass |
| AC-26 | `tests/test_oauth2_authorization_redirect.py:63`, `:55`, `:86` | Yes | Pass |
| AC-27 | `tests/test_conditional_update_attr.py:829` | Yes, and the behaviour it asserts is the defect of Issue 1 | Pass (the AC is wrong) |

No behaviour in the diff is without an AC except the two log-content
choices of `_failure_response` (Issue 8).

## Remaining Tasks

- [ ] Issues 1 to 12, through `/iterate_plan`.

## Issues Found

### Issue 1: `strict=True` can tell two callers they both won, and misreports three other cases
**Severity:** High
**Description:** `_confirm_conditional_update` decides from a re-read, and
the re-read cannot carry what the backend knew.
- A row that holds `new_data` answers `True`. Two callers that write the
  same value (a counter increment from the same base, a single-use consume
  without a nonce) are both told they won. The plan's AC-27 asks for this.
- The `DbError` it raises has no cause, so a write that can never succeed
  (an item over the size limit, a constraint) classifies as retryable.
- It compares Python values where the backends compare JSON: on
  PostgreSQL `True` and `1` differ in jsonb and are equal here (a lost
  condition raises); a tuple or an integer key never equals the re-read
  row (a fault answers `False`).
- `get_attr_strict` hides an expired row that the backends' update still
  matches, so a fault on one answers `False`.
- A write that landed, followed by another writer, answers `False`, and
  the documented counter example then increments twice.
**Location:** `actingweb/attribute.py:574-602`; `docs/sdk/attributes-buckets.rst` (the `visits` example)
**Recommendation:** Do strict in the backends, as the plan first said: a
missing row or a failed condition answers `False`, anything else raises
`DbError` from the backend's exception. Strike AC-27. Say in the docstring
and the docs that `False` can still be this call's own write after an SDK
retry (`todo/conditional-write-ambiguous-after-sdk-retry.md`), and replace
the counter example.

### Issue 2: The guide's advice hides a store outage inside a tool
**Severity:** Medium
**Description:** `ToolError` is tested before the fault branch and logged
at INFO. The guide tells authors to catch a fault after a first write and
raise `ToolError`, and tells operators to alert on the ERROR line. A fault
handled that way is an HTTP 200 and one INFO line.
**Location:** `actingweb/handlers/mcp.py:2998-3000`; `docs/guides/mcp-applications.rst` ("When a Tool Fails")
**Recommendation:** When a `ToolError` was raised from, or while handling,
a store fault, keep its text and write the store-fault line at ERROR.

### Issue 3: `ToolError` is swallowed on the REST `/actions` route
**Severity:** Medium
**Description:** The same hook is served at `/<actor>/actions/<name>`.
There every exception is logged and dropped, the wildcard hook runs next,
and the answer is 400 with no body. A hook written as the guide now
teaches loses its message over REST, logs ERROR per refusal, and lets the
wildcard hook act on input the named hook refused.
**Location:** `actingweb/interface/hooks.py:1063-1064`, `:1188-1190`; `actingweb/handlers/actions.py:194`
**Recommendation:** Let `ToolError` out of `execute_action_hooks` and its
async twin without the fall-through, and answer it over REST with 400 and
its message.

### Issue 4: Caller-influenced text is logged unescaped
**Severity:** Low
**Description:** `ToolError` text can carry a caller's argument (the
guide's own example does); a newline in it forges a log line.
**Location:** `actingweb/handlers/mcp.py:3000`
**Recommendation:** Log the `repr` of the text and of exception messages
on the tool-failure lines.

### Issue 5: `False` under strict when the answer was lost and the row moved on
**Severity:** Low
**Description:** Covered by Issue 1's last bullet; kept separate because
it survives the fix. It is the existing ambiguity of every conditional
write and has its todo.
**Location:** `actingweb/attribute.py:598-602`
**Recommendation:** State it in the docstring and the docs.

### Issue 6: Python equality in the confirm step
**Severity:** Low
**Description:** Covered by Issue 1's third bullet.
**Location:** `actingweb/attribute.py:595-600`
**Recommendation:** Gone with Issue 1's fix.

### Issue 7: The `try` covers result formatting
**Severity:** Low
**Description:** A formatter failure after the hook wrote tells the model
"The tool failed", and it calls again. The docstring says only the hook
call ends in the helper.
**Location:** `actingweb/handlers/mcp.py:1862-1882`; `actingweb/handlers/async_mcp.py:222-242`
**Recommendation:** End the `try` after the hook call.

### Issue 8: `_failure_response` no longer says which prompt or resource
**Severity:** Low
**Description:** The lines it replaced named the prompt or the URI; the
new line has the label and the exception only. Separately, a tool that
raises the library's `PermissionError` logs ERROR with a traceback per
call, which a peer can trigger.
**Location:** `actingweb/handlers/mcp.py:3031-3046`, `:3020-3024`
**Recommendation:** Pass what failed into the line; log a
`PermissionError` from a tool at WARNING without the traceback.

### Issue 9: `classify_fault` stops after five `__cause__` links
**Severity:** Low
**Description:** The loop moved verbatim from `_errors.py`; the changelog
now promises that it "follows `raise ... from` as the integrations do"
with no limit.
**Location:** `actingweb/faults.py:127`
**Recommendation:** Say the depth in the docstring.

### Issue 10: `is_token_cached` misdescribes a cache hit
**Severity:** Low
**Description:** The docstring says the handler "refuses the request when
either is gone". When the actor row is gone the handler drops the entry
and validates against the token store; a missing trust continues with an
empty peer id. The two docs pages repeat "skips token-store validation".
**Location:** `actingweb/mcp/token_cache.py:23`; `docs/guides/caching.rst`; `docs/migration/v4.0.rst`
**Recommendation:** Reword to what `authenticate_and_get_actor_cached` does.

### Issue 11: The strict `DbError` cannot be classified
**Severity:** Medium
**Description:** Issue 1's second bullet, kept separate because it is what
an operator would see: 503 with `Retry-After` in a loop for a write that
is permanently refused.
**Location:** `actingweb/attribute.py:601`
**Recommendation:** Gone with Issue 1's fix (the backend raises from its
exception).

### Issue 12: Two documentation defects
**Severity:** Low
**Description:** `docs/guides/mcp-applications.rst` (resources section)
still says a raising resource hook answers "Resource execution failed" on
Flask. The changelog's redirect entry has no **Behavior change:** sentence,
which `CLAUDE.md` requires.
**Location:** `docs/guides/mcp-applications.rst:571-573`; `CHANGELOG.rst` (FIXED, first entry)
**Recommendation:** Correct both.

## Spec Merge

- Not merged: Issue 1 is High. A later verification merges.

## Overall Assessment

Phases 1 and 2 do what the plan says and the suite is green on both
backends. The reporting consumer's two pinned behaviours hold. Phase 1 has
two Medium findings from the adversarial pass, both about `ToolError`,
which the plan added after its own evaluation and which therefore had the
least review: it can hide an outage from the only alarm left, and it is
not honoured on the REST route that serves the same hook.

Phase 3's strict mode is not fit to ship as built. The plan moved it from
the backends into the wrapper on the outside voice's advice, and the
wrapper cannot know what the backend knew; the result can report a lost
race as a win. It needs the backend implementation the plan first
described. The token-cache query is correct and its description is not.
Nothing here needs an owner decision: every recommendation is inside what
the plan already decided, except that Issue 3 adds a REST answer (400 with
the message) for `ToolError`.
