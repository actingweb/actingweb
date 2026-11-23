---
status: active
approved: 2026-11-23 by Greger Wedel
iterations: thoughts/plans/2026-11-23-emm-4-0-rc2-production-observations.iterations.md
---

# Implementation Plan: 4.0.0rc3 — a failing tool answers the model, and a consumer's rc2 findings

**Date:** 2026-11-23
**Research:** thoughts/research/2026-11-22-emm-4-0-rc2-production-observations.md
**Branch:** `fix/4.0.0-rc3-consumer-fixes` (to be created from `master` at `bee0eb5`, which is `v4.0.0rc2`)

## Overview

A consumer ran 4.0.0rc2 in production and reported eleven asks and two
observations. This plan is what 4.0.0rc3 takes for them: every triaged item
that an rc can carry, meaning no new upgrade step, no stored data rc2 cannot
read, and no documented name removed.

- **Phase 1.** A tool that fails answers the model: `tools/call` returns a
  result with `isError: true` and fixed text where it returned a JSON-RPC
  error (HTTP 503 for a store fault). The classification behind it becomes a
  public name, and a key collision stops answering as an outage.
- **Phase 2.** Two small fixes and one documentation gap: the authorization
  redirect for a redirect URI with a query, two list readers that hide a
  programming error, and `actor.store.loaded` where hook authors read.
- **Phase 3.** Two additive public names: a strict mode for
  `conditional_update_attr` and a query for the MCP token cache. (A third,
  a deletion record, was dropped after the evaluation.)

Three wire answers change: `tools/call` for a failing tool, the message of
the other MCP error answers (no exception text), and the status of an
attribute-key collision. There is no operator step.

## Decisions Made

- **Scope is every triaged item an rc can carry** (owner 2026-11-23).
- **Any exception from a tool hook is a tool result** (owner 2026-11-23):
  HTTP 200, `isError: true`, fixed text; the exception's own text goes to
  the log only. This covers a store fault and every other exception.
- **`actingweb.mcp.ToolError` is how a tool tells the model what is wrong**
  (owner 2026-11-23, after the evaluation): its message is the result's
  text, as written. A hook's own `isError: true` result is unchanged. The
  docs' tool example is rewritten to use it.
- **The fixed texts** (owner 2026-11-23, revised after the evaluation):

  | Class | Raised as | Text |
  | --- | --- | --- |
  | retryable | `DbError` (transient), `DeletionInProgress`, `TokenStoreUnavailable`, `single_use.StoreFault` | `The service is temporarily unavailable. Try again shortly.` |
  | stored | `DbErrorAfterWrite` | `A change was saved, but the tool did not finish. Check the current state before calling it again.` |
  | permanent | `DbError` with a permanent backend cause, `AttributeKeyCollision` | `The request could not be stored. Trying again will not help.` |
  | conflict | `CreatorTaken` | `That address already belongs to another account. Use a different one.` |
  | failed | any other exception, `ListItemNewerFormatError` included | `The tool failed. The error was logged.` |

- **The other MCP error answers carry no exception text** (owner
  2026-11-23, after the evaluation). A failing `prompts/get` or
  `resources/read` hook and the handlers' outer catches stay JSON-RPC
  `-32603` with the same HTTP status, and a fixed message (`Prompt
  generation failed`, `Resource read failed`, `Internal error`). A hook
  that wrapped a store fault gets the fault's answer.
- **One log line per tool failure**, written by the tool path itself (the
  shared fault line names an HTTP status that is not sent): ERROR for a
  fault and any other exception, WARNING for a deletion wait and a creator
  conflict, INFO for a `ToolError`.
- **Classifier order is behaviour**: `CreatorTaken`, `DeletionInProgress`,
  `DbErrorAfterWrite`, `AttributeKeyCollision`, a permanent cause, then
  transient. `is_permanent()` is unchanged and does not know a collision
  (the subscription resync branches on it).
- **Only the hook call changes.** A fault in authentication, in the
  permission evaluation before the hook, and in every other method
  (`initialize`, `tools/list`, `prompts/get`, `resources/read`) keeps
  today's JSON-RPC error and HTTP status.
- **The classifier is public as `actingweb.faults`** (this plan):
  `classify_fault(exc)` returns the class and the retry delay. The HTTP
  mapping in `interface/integrations/_errors.py` is rebuilt on it, so the
  two cannot disagree. `_errors` stays private.
- **`AttributeKeyCollision` is the permanent class**: HTTP 500 without
  `Retry-After` (it was 503 with `Retry-After: 5`). No new error code.
- **`conditional_update_attr` gains keyword-only `strict=False`** (owner
  2026-11-23). D10 of `plans/2026-11-01-single-mode-and-consumer-primitives.md`
  stands: the default still answers `False` on a fault and no library call
  site changes. Strict is done in the backends, which raise `DbError` from
  their own exception; a backend is passed the keyword only when a caller
  asks for it. (It was first moved into the `Attributes` wrapper on the
  outside voice's advice; the first verification showed a re-read cannot
  know what the backend knew, iteration 1.) The default is the opposite of
  the reads' `strict=True`, and the docs say so.
- **`ToolError` is honoured on the REST `/actions` route too** (iteration
  2, from the first verification): 400 with `{"error": "<message>"}`, and
  no later hook runs for the call.
- **The redirect helper appends to the query component** (`urlsplit`), so a
  fragment or an existing parameter is not corrupted (evaluation).
- **The deletion record is dropped from this plan** (owner 2026-11-23,
  after the outside voice): the design described the tombstone, not the
  actor. It first chose "a new public method, not a documented
  `read_tombstone`"; that choice stands for the later design, and the
  findings are in `todo/deletion-cleanup-across-processes.md`.
- **The MCP token cache gets a read-only query** (this plan). It answers
  whether the library would answer this token from its cache, by the
  handler's own rule. It is advisory: true means a fresh entry exists in
  this process (the handler will skip token-store validation and still
  load the actor and its trust); false is normal on a cold instance and
  never means invalid. It grants nothing and exposes no entry.
- **Changelog and guide.** 4.0.0 is not final, so
  `docs/migration/v4.0.rst` is amended in place and the entries go under
  `Unreleased`. The version bump belongs to `/release`.

## Decisions Deferred

- **Whether `GET /mcp` is still polled** — waits on the reporting consumer
  (`todo/mcp-get-polled-after-the-405.md`). It blocks nothing here. If the
  loop is confirmed on rc2, its fix is a wire change and must be planned
  before 4.0.0.

## What We're NOT Doing

- A field `actor_deleted` writes and `actor_deleted_complete` receives
  (item 7) — owner 2026-11-23: the only consumer that asked would keep its
  own record anyway; it needs a design for the operator command first.
- Raising from `conditional_update_attr` by default — D10 stands.
- `ActorInterface.get_deletion_record()` (item 10) — dropped after the
  evaluation, see Decisions Made; `todo/deletion-cleanup-across-processes.md`.
- A strict mode for `delete_attr_conditional` — nobody asked; same shape,
  can follow.
- A strict mode for `actor.store` — the fold is a decision in force
  (`plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md`);
  `loaded` is the signal.
- An `isError` result for a failing `prompts/get` or `resources/read` hook
  — MCP has none there; they stay JSON-RPC errors (with fixed text).
- Rejecting a redirect URI with a fragment, or a `redirect_uris` that is
  not a list, at registration — found by the security evaluator (Low);
  `todo/` at the end of Phase 2.
- Masking the row name in the conditional-update fault log lines
  (`db/*/attribute.py`), where a refresh token is the name — found by the
  security evaluator (Low); pre-existing, `todo/`.
- A machine-readable class in the tool result (`_meta`) — the reporter
  asked for text; a field can be added later without a wire break.
- The subscriber's `Gap timeout exceeded` log lines — unverified; a
  comparison with 3.15.1 comes first (`todo/`).
- The version bump and the `Unreleased` rename — `/release`.

## What Already Exists

- `interface/integrations/_errors.py` `db_error_answer`, `is_permanent`,
  `find_db_error`, `log_db_error` — the classification and the log line.
  Reused: the classes move to `actingweb/faults.py`, `_errors` calls it.
- `handlers/mcp.py` `format_call_tool_result` — already forwards a hook's
  `isError` and skips the output-schema warning for one. Reused to build the
  failure result.
- `handlers/mcp.py:1843` and `handlers/async_mcp.py` `_handle_tool_call_async`
  — the two `except` pairs around the hook call. The change is inside them.
- `oauth2_server/oauth2_server.py:1070` `_denied` — picks the separator.
  Reused as one shared helper.
- The strict re-read after a `False` that eleven library call sites make
  (`peer_permissions.py:373`, `callback_processor.py:248`, …). Reused:
  `strict=True` is that re-read, in the wrapper.
- `handlers/mcp.py:2398` — the cache-hit rule (fresh, and `config` is the
  application's object). The query calls the same predicate.
- `docs/reference/database-backends.rst:593` — one sentence on
  `InternalStore.loaded`. Kept; the hooks reference gains the pattern.

## Acceptance Criteria

- **AC-1** (tool, retryable) — When a tool hook raises a transient
  `DbError` or `DeletionInProgress`, `tools/call` answers HTTP 200 with a
  result whose `isError` is true and whose only content is the retryable
  text; no `Retry-After` header; the fault's own text is nowhere in the
  response. Sync and async handlers.
- **AC-2** (tool, stored) — When a tool hook raises `DbErrorAfterWrite`,
  the result is `isError: true` with the stored text.
- **AC-3** (tool, permanent) — When a tool hook raises a `DbError` with a
  permanent backend cause or `AttributeKeyCollision`, the result is
  `isError: true` with the permanent text.
- **AC-4** (tool, conflict) — When a tool hook raises `CreatorTaken`, the
  result is `isError: true` with the conflict text.
- **AC-5** (tool, any other exception) — When a tool hook raises any other
  exception, the result is `isError: true` with the failed text; the
  exception's text is in the log and not in the response.
- **AC-6** (edge: fault outside the hook) — When the store faults in
  authentication, in the permission evaluation of `tools/call`, or in
  `tools/list`, `prompts/get` or `resources/read`, the answer is the
  JSON-RPC error and HTTP status rc2 gives.
- **AC-7** (edge: the hook's own error) — When a tool hook returns its own
  `isError: true` result, it reaches the client unchanged.
- **AC-8** (edge: a log line per failure) — When a tool hook raises, one
  ERROR line names the tool and the exception; for a store fault it is the
  shared fault line with the backend cause.
- **AC-9** (HTTP, collision) — When `AttributeKeyCollision` reaches an
  integration from a route, the answer is 500 with the `internal_error`
  body and no `Retry-After`.
- **AC-10** (classifier) — `actingweb.faults.classify_fault(exc)` returns
  the class and retry delay for each of the four fault classes, follows the
  `__cause__` chain as the integrations do, and returns `None` for an
  exception that is not a store fault.
- **AC-11** (edge: HTTP unchanged) — For every `DbError` class other than
  `AttributeKeyCollision`, an integration's status, headers and body are
  what rc2 answers.
- **AC-12** (redirect, query) — When an authorization completes for a
  client whose redirect URI has a query, the redirect keeps that query and
  adds `code` and `state` with `&`.
- **AC-13** (edge: redirect, no query) — A redirect URI without a query
  gets `?code=…` as before.
- **AC-14** (lists) — When `PropertyListStore.exists()` or `list_all()`
  meets an exception that is not a `DbError`, it propagates.
- **AC-15** (docs) — The hooks reference shows, under `actor_deleted`, how
  to tell "not set" from "could not read" with `actor.store.loaded`.
- **AC-16** (strict, fault) — When `conditional_update_attr(strict=True)`
  meets a store fault, it raises `DbError`, on both backends.
- **AC-17** (edge: strict, lost condition) — With `strict=True`, a row that
  does not match, or no row, answers `False`.
- **AC-18** (edge: default) — Without `strict`, a fault answers `False` as
  in rc2, and the backend is never passed the keyword.
- **AC-19** (cache query, hit) — When the token cache holds a fresh entry
  for the token under the application's `Config`,
  `actingweb.mcp.is_token_cached(token, config)` is true and reads no
  store.
- **AC-20** (edge: cache query, miss) — For an unknown token, an entry
  older than the TTL, or an entry of another `Config`, it is false.
- ~~**AC-21**~~ — dropped: the deletion record left the plan (owner
  2026-11-23, after the outside voice).
- ~~**AC-22**~~ — dropped with AC-21.

- **AC-23** (added in plan: `ToolError`, owner after evaluation) — When a
  tool hook raises `ToolError("…")`, the result is `isError: true` with
  that message as its text.
- **AC-24** (added in plan: owner after evaluation) — When a `prompts/get`
  or `resources/read` hook raises, the answer is JSON-RPC `-32603` with a
  fixed message and none of the exception's text; a hook that wrapped a
  store fault answers the fault's 503.
- **AC-25** (added in plan: evaluation) — When a tool hook raises
  `TokenStoreUnavailable` or `single_use.StoreFault`, the result carries
  the retryable text; `ListItemNewerFormatError` carries the failed text.
- **AC-26** (added in plan: evaluation) — When a redirect URI carries a
  fragment or its own `code` parameter, the appended `code` and `state` are
  in the query component.

- ~~**AC-27**~~ — dropped (iteration 1): answering `True` for a row that
  holds `new_data` tells two writers of the same value that both won.
- **AC-28** (added in iteration 1) — With `strict=True`, a caller whose
  condition lost to another writer of the same `new_data` gets `False`.
- **AC-29** (added in iteration 1) — The `DbError` a strict fault raises is
  chained to the backend's exception.
- **AC-30** (added in iteration 2) — When an action hook raises `ToolError`
  on `GET`, `POST`, `PUT` or `DELETE /<actor>/actions/<name>`, the answer is
  400 with `{"error": "<message>"}` and the wildcard hook does not run.
- **AC-31** (added in iteration 3, widened in iteration 8) — When a
  `ToolError` is raised from, or while handling, a store fault, its text is
  the answer and one line that starts `Tool '<name>' failed with a store
  fault` (or `Action '<name>' …` on the REST route) is logged, at ERROR for
  an outage and WARNING for a deletion wait or a creator conflict.
- **AC-32** (added in iteration 4) — When a tool's result cannot be
  formatted, the answer is JSON-RPC `-32603` `Internal error`, not a tool
  failure.

- **AC-33** (added in iteration 9) — With `strict=True`, a value the
  backend cannot compare raises `TypeError` or `ValueError`, or answers
  `False`; it never raises `DbError`.

## Traceability

| AC | Phase | Test | Status |
| --- | --- | --- | --- |
| AC-1 | 1 | `tests/test_mcp_tool_failure_results.py::test_a_failing_tool_is_a_tool_result` (ids `transient`, `deleting`; sync and async; the response object's status and headers) | Passing |
| AC-2 | 1 | same test, ids `stored`, `stored_permanent_cause` | Passing |
| AC-3 | 1 | same test, ids `permanent`, `collision` | Passing |
| AC-4 | 1 | same test, id `conflict` | Passing |
| AC-5 | 1 | same test, ids `other`, `other_base`; `tests/test_async_mcp_handler.py` (the `failing_tool` test, rewritten) | Passing |
| AC-6 | 1 | `tests/test_mcp_tool_failure_results.py::test_a_fault_in_the_permission_check_keeps_the_protocol_error`, `::test_a_fault_in_another_method_keeps_the_protocol_error`, `::test_an_unknown_tool_is_still_a_protocol_error`; `tests/test_db_fault_third_pass.py` (`tools/list`, existing) | Passing |
| AC-7 | 1 | `tests/test_mcp_tool_failure_results.py::test_a_hooks_own_is_error_result_is_untouched`; `tests/test_mcp_tools_call_wire_shape.py::test_legacy_shaped_error_hook_reports_is_error_on_the_wire` (existing) | Passing |
| AC-8 | 1 | `tests/test_mcp_tool_failure_results.py::test_each_failure_is_logged_once_with_its_cause` (seven classes: one line, its level, no HTTP status) | Passing |
| AC-9 | 1 | `tests/test_db_fault_http.py::TestFlask::test_a_key_collision_answers_500_without_retry_after`, `::TestFastAPI::…` | Passing |
| AC-10 | 1 | `tests/test_public_fault_classifier.py::TestClassifyFault`, `::TestPrecedence` | Passing |
| AC-11 | 1 | `tests/test_public_fault_classifier.py::TestHttpMapping::test_the_http_mapping_is_unchanged_from_rc2` (literal rc2 answers; green before and after); `tests/test_db_fault_http.py` (existing) | Passing |
| AC-12 | 2 | `tests/test_oauth2_authorization_redirect.py::test_a_redirect_uri_with_a_query_keeps_it`; `tests/integration/test_oauth2_trust_binding.py::test_the_helper_keeps_a_redirect_uris_own_query` | Passing |
| AC-13 | 2 | `tests/test_oauth2_authorization_redirect.py::test_a_redirect_uri_without_a_query_is_unchanged` (the exact rc2 string); wire row `WG16` (existing) | Passing |
| AC-14 | 2 | `tests/test_db_fault_callers.py::TestListStoreLookups::test_an_unexpected_exception_propagates` (`exists`, `list_all`), `::test_the_ordinary_answers_are_unchanged` | Passing |
| AC-15 | 2 | manual: read `docs/reference/hooks-reference.rst`, `actor_deleted` ("Reading `actor.store` here"), and the docs build with `-W` — a documentation statement | Done |
| AC-16 | 3 | `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_strict_raises_on_a_fault` (`seam_fault` at the read and at the write; the file runs on each Full-tier backend) | Passing |
| AC-17 | 3 | `…::TestStrictConditionalUpdate::test_strict_answers_false_for_a_lost_condition`, `::test_strict_answers_false_for_no_row` | Passing |
| AC-18 | 3 | `…::TestStrictConditionalUpdate::test_the_default_still_answers_false_on_a_fault`, `::test_the_backend_is_passed_the_keyword_only_when_asked` | Passing |
| AC-19 | 3 | `tests/test_mcp_token_cache_query.py::test_a_fresh_entry_is_cached_and_reads_no_store` | Passing |
| AC-20 | 3 | `tests/test_mcp_token_cache_query.py::test_a_miss` (unknown, expired, other config, no `cached_at`), `::test_an_evicted_token_is_not_cached`, `::test_the_handler_and_the_query_agree` | Passing |
| ~~AC-21~~ | — | dropped | — |
| ~~AC-22~~ | — | dropped | — |

| AC-23 | 1 | `tests/test_mcp_tool_failure_results.py::test_a_tool_error_reaches_the_model_as_written`, `::test_a_tool_error_without_a_message_takes_the_fixed_text` | Passing |
| AC-24 | 1 | `tests/test_mcp_tool_failure_results.py::test_a_failing_prompt_or_resource_hook_answers_fixed_text` | Passing |
| AC-25 | 1 | `tests/test_mcp_tool_failure_results.py::test_a_failing_tool_is_a_tool_result` (ids `token_store`, `single_use`, `newer_format`) | Passing |
| ~~AC-27~~ | — | dropped (iteration 1) | — |
| AC-28 | 3 | `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_strict_does_not_claim_another_writers_identical_value` | Passing |
| AC-29 | 3 | `…::TestStrictConditionalUpdate::test_a_strict_fault_keeps_its_cause` | Passing |
| AC-30 | 1 | `tests/test_tool_error_on_actions_route.py::test_the_actions_route_answers_400_with_the_message` (four verbs, sync and async), `::test_a_tool_error_leaves_the_hook_runner` | Passing |
| AC-31 | 1 | `tests/test_mcp_tool_failure_results.py::test_a_tool_error_raised_for_a_store_fault_still_alarms`, `::test_a_tool_error_over_an_expected_fault_does_not_alarm`; `tests/test_tool_error_on_actions_route.py::test_a_tool_error_for_a_store_fault_still_alarms_over_rest` | Passing |
| AC-33 | 3 | `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate::test_a_value_that_cannot_be_compared_is_not_an_outage` | Passing |
| AC-32 | 1 | `tests/test_mcp_tool_failure_results.py::test_a_result_that_cannot_be_formatted_is_not_a_tool_failure` | Passing |
| AC-26 | 2 | `tests/test_oauth2_authorization_redirect.py::test_a_fragment_and_an_existing_parameter_are_not_corrupted`, `::test_a_fragment_does_not_swallow_the_code`, `::test_a_denial_keeps_the_query` | Passing |

## Spec Delta

### `thoughts/specs/mcp-server.md`

- **ADDED** (Tool calls) — When a tool hook raises a store fault,
  `tools/call` answers HTTP 200 with a result whose `isError` is true and
  whose text is fixed by the fault's class (retryable, stored, permanent,
  conflict); the fault's text is never in the response. (AC-1 to AC-4)
- **ADDED** (Tool calls) — When a tool hook raises any other exception, the
  result is `isError: true` with a fixed text; the exception's text goes to
  the log. (AC-5)
- **ADDED** (Tool calls) — When a tool hook raises `ToolError`, its message
  is the text of the `isError` result. (AC-23)
- **ADDED** (Tool calls) — When an action hook raises `ToolError` on the
  REST `/actions` route, the answer is 400 with `{"error": "<message>"}`
  and no later hook runs for the call. (AC-30)
- **ADDED** (Tool calls) — A `ToolError` raised for a store fault is sent
  as written and still logs the fault, on the MCP and the REST route, in a
  line that starts `Tool '<name>' failed with a store fault` or `Action
  '<name>' failed with a store fault`. (AC-31)
- **ADDED** (Tool calls) — A tool result that cannot be formatted answers
  JSON-RPC `-32603` `Internal error`. (AC-32)
- **ADDED** (Tool calls) — A failing `prompts/get` or `resources/read`
  hook, and an unexpected handler error, answer JSON-RPC `-32603` with a
  fixed message and no exception text. (AC-24)
- **ADDED** (Tool calls) — A store fault outside the hook call
  (authentication, the permission evaluation, every other method) answers a
  JSON-RPC error with the HTTP status of the shared fault mapping. (AC-6)
- **ADDED** (Authorization) — `actingweb.mcp.is_token_cached(token, config)`
  answers whether this process holds a fresh cache entry for the token
  under this `Config`; it reads no store, changes no entry and grants
  nothing. (AC-19, AC-20)
- **DECISION** — The fixed tool-failure texts are read by models and by
  consumers' instructions to them; changing one is a consumer-visible
  change.
- **DECISION** — The token and trust caches stay internal; the query is the
  only supported view of them.

### `thoughts/specs/oauth-client-registration.md`

- **ADDED** (Authorization) — When an authorization completes or is denied,
  the redirect keeps the registered redirect URI byte for byte and appends
  its parameters to the URI's query, before any fragment.
  (AC-12, AC-13, AC-26)

### `thoughts/specs/property-lists.md`

- **MODIFIED PLS-1** — "When the store faults under `exists()`,
  `list_all()` or `list_all_with_rows()`, on either store, `DbError` is
  raised." → the same, plus: "Any other exception propagates unchanged."
  (AC-14)

### `thoughts/specs/store-faults.md` (new spec, `partial`)

- **ADDED** (Classification) — `actingweb.faults.classify_fault()` names a
  store fault's class (retryable, stored, permanent, conflict) and retry
  delay; the integrations' HTTP answers are derived from it. (AC-10, AC-11)
- **ADDED** (Classification) — `AttributeKeyCollision` is permanent: HTTP
  500 without `Retry-After`. (AC-9)
- **ADDED** (Conditional writes) — `conditional_update_attr` answers `False`
  on a fault by default. With `strict=True` a store fault raises `DbError`
  chained to the backend's exception, and `False` means the condition did
  not hold: the row holds something other than `old_data` (the same value
  another writer wrote included), there is no row, or another bucket holds
  the key. In neither mode does `False` prove the write did not land. A
  value the backend cannot compare is the caller's `TypeError` or
  `ValueError`, never a `DbError`. (AC-16 to AC-18, AC-28, AC-29, AC-33)
- **DECISION** — Strict is the backends' to decide, not a re-read above
  them: only the backend knows why its write did not happen.
- **DECISION** — The default of `conditional_update_attr` does not raise
  (D10, `plans/2026-11-01-single-mode-and-consumer-primitives.md`).
- **DECISION** — `actor.store` folds a failed read; `loaded` is its signal
  (`plans/2026-10-28-db-fault-semantics-and-creator-uniqueness.md`).

## Phase 1: A failing tool answers the model

### Changes

- `actingweb/faults.py` (new) — the public classification:

  ```python
  class FaultClass(StrEnum):
      RETRYABLE = "retryable"
      STORED = "stored"
      PERMANENT = "permanent"
      CONFLICT = "conflict"

  @dataclass(frozen=True)
  class Fault:
      kind: FaultClass
      retry_after: int | None   # seconds; None when a retry is not advised
      error: DbError            # the fault found on the __cause__ chain; for the log

  def classify_fault(exc: BaseException) -> Fault | None: ...
  ```

  `__all__` is those three names. `is_permanent` and `find_db_error` move
  here unchanged and stay the library's own.
- `actingweb/interface/integrations/_errors.py` — `db_error_answer` derives
  its status, headers and body from `classify_fault` and still raises
  `TypeError` for anything that is not itself a `DbError`; it re-exports
  `is_permanent` and `find_db_error` for the tests that import them there.
- `actingweb/actor.py` — the resync loop imports `is_permanent` from
  `actingweb.faults`.
- `actingweb/mcp/errors.py` (new), exported from `actingweb/mcp/__init__.py`
  — `class ToolError(Exception)`.
- `actingweb/handlers/mcp.py` — `TOOL_FAULT_TEXTS`, `TOOL_FAILURE_TEXT`;
  `_tool_failure_result(request_id, tool_name, exc)` builds the result and
  writes the one log line; `_failure_response(request_id, label, exc)`
  answers the other hooks and the outer catches with fixed text (a wrapped
  fault goes to `_db_fault_response`). The broad `except` around the hook
  call carries the `# folds DbError:` marker `tests/test_db_fault_guard.py`
  requires.
- `actingweb/handlers/async_mcp.py` — the same call sites use the same two
  helpers.
- `actingweb/mcp/decorators.py` — the `@mcp_tool` docstring names
  `ToolError`.
- `docs/guides/mcp-applications.rst` — "When a Tool Fails": the table, the
  log line to alert on, the repeat-safety rule; the `fetch_url` example
  raises `ToolError`.
- `docs/reference/database-backends.rst`, `docs/migration/v4.0.rst`
  (`v40-fault-contract`, new `v40-mcp-a-failing-tool` with the consumer
  checks) — the classifier, the collision's 500, the tool answer.
- `CHANGELOG.rst` — three `CHANGED` (**Breaking**) and two `ADDED` entries.

### New Tests (written first: `/implement_plan` sees them fail before coding)

- `tests/test_mcp_tool_failure_results.py` — AC-1 to AC-8, AC-23 to AC-25,
  sync and async. Every test asserts a marker placed in the exception is
  absent from the whole response.
- `tests/test_async_mcp_handler.py` — the `failing_tool` test asserts the
  result, not the error (AC-5).
- `tests/test_public_fault_classifier.py` — AC-10, AC-11.
- `tests/test_db_fault_http.py` — AC-9, both integrations.

### Failure Scenarios

- The hook wrote, then faulted with a plain `DbError`; the model reads "try
  again" and repeats the write — not preventable by the library (a plain
  `DbError` means "nothing was written, or the caller cannot tell");
  documented as a rule for tool authors in "When a Tool Fails" and the
  changelog.
- A throttle that only a tool meets no longer shows as a 5xx — the ERROR
  line is the signal; documented, and AC-8 pins the line.
- The helper itself raises — it would reach the outer catch, which answers
  `Internal error` with no exception text (AC-24's code path).
- A classifier reorder turns a stored fault with a permanent cause into
  "will not help" — `TestPrecedence` and the `stored_permanent_cause` case.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] `grep -n "str(e)" actingweb/handlers/mcp.py actingweb/handlers/async_mcp.py` finds nothing
- [x] Docs build with `-W`

### Implementation Status: Complete

Notes:

- Red first: 18 of the first 21 tests failed on the behaviour (an `error`
  where a `result` was asserted); the three AC-6 tests passed from the
  start, as regression guards for behaviour that must not move. AC-11's
  table is a baseline by design and was green throughout. The three
  collision tests were seen failing against the rc2 mapping.
- The plan was approved and Phase 1 begun before the evaluators returned;
  their findings changed four decisions (texts, `ToolError`, the other
  error answers, strict in the wrapper), each put to the owner or recorded
  above.
- The sync handler does not await an `async def` tool hook (it returns the
  coroutine as the result); that is rc2 behaviour and out of scope. The
  async-tool tests run through the async handler only.
- Release note for `/changelog`: this phase changes response text and one
  status, and adds two public names; under the addendum's rule that makes
  a minor, which 4.0.0 (a major, not final) absorbs.

---

## Phase 2: The redirect, two list readers, and `store.loaded`

### Changes

- `actingweb/oauth2_server/oauth2_server.py` — one private helper appends
  parameters to a redirect URI's query component (`urlsplit`, keeping a
  fragment after it); `_complete` (`:1198`, reached from the provider
  callback, `handle_confirmation` and `complete_client_authorization`) and
  `_denied` (`:1070`) both use it.
- `actingweb/property.py` — `PropertyListStore.exists` and `list_all` lose
  their `except Exception` branches (and with them the `except DbError:
  raise` that only existed to get past them).
- `docs/reference/hooks-reference.rst` — under `actor_deleted`: reading a
  value from `actor.store` to act on, checking `actor.store.loaded` first,
  and what to do when it is false.
- `docs/sdk/attributes-buckets.rst` — one paragraph on `actor.store` and
  `loaded`, pointing at the hooks reference.
- `CHANGELOG.rst` — two `FIXED` entries.

### New Tests (written first)

- `tests/test_oauth2_authorization_redirect.py` — AC-12, AC-13, AC-26,
  asserting on the parsed query, and `::test_a_denial_keeps_the_query`.
- `tests/test_db_fault_callers.py::TestListStoreLookups` — AC-14, with the
  no-config, absent and ordinary answers pinned so the edit cannot move
  them.

### Failure Scenarios

- A registered URI that ends in `?` or `&` — the helper adds no second
  separator (covered by the helper's branches; the custom-scheme and
  loopback cases pin byte preservation).
- Removing the `try` moves an ordinary answer (no config, no list) —
  `test_the_ordinary_answers_are_unchanged`.
- An unexpected exception under `exists()` now answers 500 on the property
  routes where the list read as absent — intended; changelog **Behavior
  change**.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [x] Build the docs with the Full tier's `sphinx-build` line and read the
      `actor_deleted` section (AC-15)

### Implementation Status: Complete

Notes:

- Red first: the helper was added with rc2's bare `?` so the six redirect
  tests failed on the URL, not on an import; the two `propagates` cases
  failed on the folded answer. `test_the_ordinary_answers_are_unchanged`
  and the no-query test are baselines and were green throughout.
- The join is in `_complete`, not `complete_client_authorization`; one
  helper (`redirect_with_params`) serves it and `_denied`. It splits the
  string by hand, not with `urlsplit`/`urlunsplit`, so nothing of the
  registered URI is normalised.
- Two Low findings of the security evaluation became todos:
  `oauth-redirect-uri-registration-checks.md`,
  `conditional-update-fault-log-names-the-row.md`.

---

## Phase 3: Two additive names

### Changes

- `actingweb/attribute.py` — `Attributes.conditional_update_attr` gains
  keyword-only `strict: bool = False`. After a `False` from the backend,
  strict re-reads the row with `get_attr_strict`: unchanged raises
  `DbError`, `new_data` answers `True`, anything else is the lost
  condition. No backend and no protocol change.
- `actingweb/handlers/mcp.py` — `_token_cache_entry_is_fresh(entry, config,
  now)`: the cache-hit rule as one pure predicate, used by the handler.
- `actingweb/mcp/token_cache.py` (new), exported from
  `actingweb/mcp/__init__.py`:

  ```python
  def is_token_cached(token: str, config: Config) -> bool: ...
  ```

- `docs/sdk/attributes-buckets.rst`, `docs/reference/database-backends.rst`
  — `strict=`, its default and what to do after the `DbError`.
- `docs/guides/caching.rst`, `docs/migration/v4.0.rst`
  (`v40-mcp-actors-are-built-per-request`) — the cache query, what true
  and false mean; `validate_access_token` stays the answer for validity.
- `CHANGELOG.rst` — two `ADDED` entries.
- `thoughts/todo/` — the four files this plan closes are deleted with their
  `INDEX.md` rows; `deletion-cleanup-across-processes.md` keeps item 7 and
  the deletion record with the evaluation's findings; three todos added.

### New Tests (written first)

- `tests/test_conditional_update_attr.py::TestStrictConditionalUpdate` —
  AC-16 to AC-18, AC-27.
- `tests/test_mcp_token_cache_query.py` — AC-19, AC-20.

### Failure Scenarios

- The backend answers `False` for a write that landed (a lost answer, or an
  SDK retry that meets its own first attempt) — strict answers `True`
  (AC-27); the default keeps rc2's `False`.
- The strict re-read itself faults — `DbError`; the docstring says the row
  may hold either value.
- The query is asked on a cold instance — `False`; the docs say it is not
  "invalid" and that the handler validates once.
- A caller treats `True` as authorization — the docstring's first bold
  line; the handler's own checks are unchanged.

### Verification

- [x] Run the contract's `### Checks` fast tier verbatim
- [ ] The Full tier, both backends, and the docs build

### Implementation Status: Complete

Notes:

- Red first: stubs (`strict` accepted and ignored, the query answering
  `False`) so six tests failed on the behaviour; the default-mode and miss
  cases are baselines.
- `strict` in the wrapper costs one extra strict read, on the `False`
  branch only.
- The module-level instance cache of `Attributes` is updated only on a
  `True`, as before; after a strict `DbError` the caller is told to read
  again.

---

## Evaluation Notes

**Outside voice:** codex (gpt-5.6-sol) and a fresh-context Claude reviewer.

| # | From | Finding (`file:line` quoted) | Disposition |
| --- | --- | --- | --- |
| 1 | Tests | `tests/test_db_fault_guard.py:109` flags a broad handler with no `# folds DbError:` marker — the new `except` around the hook | Folded into Phase 1 |
| 2 | Architecture, Tests, Scalability | `_errors.py:302` "Database fault answered {status}" — the shared line names a status the tool path does not send and is INFO for two classes | Folded: the tool path writes its own line, a level per class (AC-8) |
| 3 | Architecture, Tests | `_errors.py:143` tests `DbErrorAfterWrite` before `:152` `is_permanent`; `actor.py:4869` branches on `is_permanent` | Folded: order recorded as a decision, `is_permanent` unchanged, `TestPrecedence` |
| 4 | Architecture, Tests | `list_core.py:246` `ListItemNewerFormatError(Exception)`, `token_manager.py:38`, `single_use.py:89` — store faults that are not `DbError` | Folded: AC-25 |
| 5 | Security (Medium) | `handlers/mcp.py:1973` `f"Prompt generation failed: {str(e)}"` and five siblings | User decided: fixed text, same shape (AC-24) |
| 6 | Usability | `docs/guides/mcp-applications.rst:176` `return {"error": "Missing url"}` — the docs teach an error that is reported as a success, and the fixed text removes the raised message | User decided: `ToolError` (AC-23) |
| 7 | Usability, Scalability, Security | `db/exceptions.py:28` "A repeat of a plain set is safe" against "Do not repeat the call"; `constants.py:264` `DELETION_LEASE = 120` against "a few seconds" | User decided: revised texts |
| 8 | Scalability, Security | `db/exceptions.py:31` "nothing was written, or that the caller cannot tell" — the model is told to try again | Folded: tool-author rule in the guide and changelog; Failure Scenarios |
| 9 | Outside voice | `actingweb/faults.py:36` `__all__` held six names; `is_permanent(collision)` is False while the classifier says permanent | Folded: three public names; the difference is pinned by a test |
| 10 | Outside voice, Usability, Architecture | research, item 11: "Eleven of the twelve library call sites follow a `False` with their own check"; `db/dynamodb/attribute.py:385` a third `False` | Folded into Phase 3: strict in the wrapper, no backend or protocol change |
| 11 | Tests | `tests/test_conditional_update_attr.py:18` already runs on the real backend; `tests/_adoption_helpers.py:147` `seam_fault` | Folded: no new integration file |
| 12 | Security, Tests | `oauth2_server.py:1070` `sep = "&" if "?" in redirect_uri else "?"` is a substring test (fragment); the join is in `_complete`, three entry points | Folded into Phase 2 (AC-26) |
| 13 | Tests, Outside voice | `tests/test_property_list_fault_reads.py:87` patches `get_property` only; `property.py:90` `if self._config:` falls through | Folded: AC-14 retargeted, ordinary answers pinned |
| 14 | Security, Architecture, Scalability, Tests | `handlers/mcp.py:2410` a hit still loads the actor and may drop the entry; `:2404` the stats bump; `docs/guides/caching.rst:93` prints the private predicate | Folded into Phase 3: wording, a pure predicate, `caching.rst` in the sweep |
| 15 | Architecture, Outside voice, Usability | `deletion.py:619` finishes a reason-less row; `deletion.py:596` folds a fault and returns True; `oauth2.py:2494` a live actor can carry a reason-less tombstone | User decided: the deletion record is dropped; findings in `todo/deletion-cleanup-across-processes.md` |
| 16 | Outside voice (high) | research: "The pin waits on items 1 and 5 only"; "After 4.0.0 (additive): items 6, 7 and 10" — Phase 3 freezes three contracts no pin waits on | User decided: `strict=` and the cache query stay, the deletion record goes |
| 19 | Scalability, Outside voice | `db/dynamodb/attribute.py:36` a failed condition after an SDK retry of a write that landed answers False | Folded: strict answers True for a row holding `new_data` (AC-27) |
| 17 | Security (Low) | `client_registry.py:296` `return redirect_uri in registered_uris`; `db/postgresql/attribute.py:667` logs the row name | Not doing: todos at the end of Phase 2 |
| 18 | Usability | `actingweb/attribute.py:307` `def get_bucket(self, strict: bool = True)` — the opposite default | Folded: kept `strict` (the meaning is the same), the docs state the default |

**Unverified notes** (concerns that could not cite a line):
- Whether an MCP client that validates `structuredContent` against a declared `outputSchema` skips the check for `isError: true`.
- Whether a peer's callback sender treats this actor's 500 for a key collision differently from a 503.
- A tool built on an authenticated view logs ERROR with a traceback per `PermissionError`, which a peer can trigger at will.
