---
status: active
---

# Implementation Plan: Make MCP `structuredContent` opt-in

**Date:** 2026-08-03
**Research:** `thoughts/research/2026-08-03-structuredcontent-promotion-drops-tool-text.md`
**Branch:** `master` (work on a feature branch; `master` is protected)

## Overview

ActingWeb promotes every unrecognised top-level key of a tool hook's return dict
into MCP `structuredContent` (`actingweb/handlers/mcp.py:166-171`). At least one
major client discards **all** text content blocks when `structuredContent` is
present, so adding a single scalar key to a hook's return value silently deletes
that tool's entire prose payload — with no error on either side.

This plan removes the promotion: `structuredContent` is emitted only when a hook
sets that key explicitly. It also closes an adjacent defect where an explicitly
set `isError` is silently discarded on the legacy-wrap path, adds two
author-error warnings, and rewrites every place the old contract is documented.

**Delivery:** a single PR that also carries the version bump to `3.13.0rc4`, per
`CLAUDE.md` (the bump and changelog rename ride in the release PR). The phases
below are sequenced implementation steps *within* that PR — each one leaves the
tree green and is independently testable, so a phase can be reverted without
unpicking the others.

## Decisions Made

- **Gate = explicit key only.** Delete the `else:` extras sweep; keep the
  explicit passthrough at `mcp.py:164-165`. Rationale: it is the only option that
  both removes the measured harm and matches what both reference server
  implementations do — the SDK's low-level server emits `structuredContent`
  implicitly only when `content` is its exact `json.dumps` serialization, and
  FastMCP emits it only for a declared return model. Neither ever promotes
  individual keys. It is also a **no-op for hooks that already set the key**, so
  downstreams migrate first and upgrade after, with no coordinated deploy.
- **No opt-out flag.** The correct answer differs per response *within* a single
  tool, which no app-level or per-tool flag can express — an explicit
  `structuredContent` key can. A flag would preserve a footgun that fails
  silently.
- **No log when extras are dropped.** Consistent with existing behaviour: extras
  are already dropped silently on `2025-03-26` and older. Discovery is via
  CHANGELOG, migration guide and a new troubleshooting entry.
- **Warn on author error, in two precise places.** (a) a non-dict
  `structuredContent`, which `mcp.py:164` drops silently; (b) a tool that
  declares `output_schema` and returns a non-error result with no
  `structuredContent`, which strict clients reject. Both are unambiguous
  mistakes, so neither has a false-positive cost.
- **`output_schema` warning fires at call time, not at `tools/list`.** Listing
  time cannot know what the hook returns, so it would warn correctly-written
  tools forever and train authors to ignore it. Call time fires exactly when a
  strict client would reject the result.
- **Honour `isError` on the legacy path — honour only, never infer.** Add the
  field when the hook's dict explicitly carries it. Do **not** derive it from an
  `"error"` key or any other heuristic: the known consumer's `MCPResponse.error()`
  returns `{"error": {...}}`, so inference would silently flip the shape of every
  app error path in rc4 — precisely the class of surprise this release exists to
  eliminate.
- **Do not touch the `str(result)` text serialization.** It must stay
  byte-identical. A consumer batch path currently relies on that wrap
  (`actingweb_mcp` `hooks/mcp/tools/delete.py:222-223`, filed there as
  `thoughts/todo/2026-08-03-memory-delete-batch-stringified.md`); changing the
  text shape would fold an unrelated contract change into this rollback unit.
- **Ship as `3.13.0rc4`.** The promotion is documented behaviour published on
  production PyPI in stable `v3.11.0` and `v3.12.0` (`v3.12.0` is current
  `latest`), so this is a breaking change to a released contract. `3.12.0 →
  3.13.0` is already a minor bump, so the version carries it legitimately, and
  the one known consumer is coordinating in the same train.
- **Full documentation sweep**, including two pre-existing corrections: the
  false "results always include `isError`" claims, and an annotation on the
  2026-05-26 plan whose superseded decision is cited from shipping code.

## What We're NOT Doing

- **Not gating on `output_schema`** (research option C). It would need real
  schema validation to avoid trading a silent text loss for a silent
  conformance violation of a spec **MUST**, and it inherits the `isError` gap.
  Phase 3 unblocks it; adopting it is a separate decision.
- **Not enforcing or validating `output_schema` at call time.** Phase 4 adds a
  *warning* only. The library still never validates `structuredContent` against
  a declared schema, and still never rejects a result.
- **Not inferring `isError` from result shape.** See guardrail above.
- **Not changing `str(result)` on the legacy path**, and not addressing its
  separate defects (it emits a Python `repr`, not JSON; it double-materializes
  large payloads). Both are pre-existing and belong in `thoughts/todo/`.
- **Not fixing the consumer.** `MCPResponse.error()` and the `memory_delete`
  batch path are `actingweb_mcp` work, already filed there.
- **Not adding an opt-out flag**, and not logging dropped extras.
- **Not adding protocol revision `2026-07-28`** support, though it makes
  schema-less `structuredContent` explicit.
- **Not touching the legacy path's full-dict text exposure.** A hook spreading
  `trust.to_dict()` or `properties.to_dict()` into a dict with no `content` key
  still stringifies secrets to the client. Pre-existing; out of scope.

---

## Phase 1: Make `structuredContent` opt-in

### Changes

- `actingweb/handlers/mcp.py:166-171` — delete the `else:` branch that sweeps
  extras into `structuredContent`. Keep the version gate at `:162`, the explicit
  passthrough at `:164-165`, and the `_meta` handling at `:158-160` exactly as
  they are.
- `actingweb/handlers/mcp.py:130-135` — delete `_CALL_TOOL_RESERVED_KEYS` and its
  explanatory comment. Its only consumer is the deleted comprehension at `:168`,
  so it drops to **zero references**. Ruff does not flag unused module-level
  constants, so this must be done deliberately or it rots in place describing
  behaviour that no longer exists.
- `actingweb/handlers/mcp.py:164` — add a warning branch for a non-dict
  `structuredContent`, which is currently dropped silently:

  ```python
  explicit_struct = result.get("structuredContent")
  if isinstance(explicit_struct, dict):
      out["structuredContent"] = explicit_struct
  elif explicit_struct is not None:
      logger.warning(
          "Tool result set 'structuredContent' to %s, but MCP requires a JSON "
          "object; the field was dropped.",
          type(explicit_struct).__name__,
      )
  ```

- `actingweb/handlers/mcp.py:138-152` — rewrite the docstring, which currently
  states *"otherwise any extra top-level keys are promoted into
  `structuredContent`"* as the contract. State the new contract, that
  `structuredContent` must be a JSON object, and that the version gate suppresses
  it — **including an explicit one** — below `2025-06-18`.

### New Tests, both unit and integration tests

Rewrite in `tests/test_mcp_tool_result_format.py` (module docstring at `:1-9`
also documents promotion and must change):

- `:28-38` `test_content_with_extras_promotes_structured_content` → invert:
  extras must **not** be promoted, and `content` must survive byte-for-byte.
- `:40-43` `test_latest_version_promotes_structured_content` → invert.
- `:66-75` `test_meta_is_preserved_not_swept` → rebuild on an explicit
  `structuredContent`, so it still proves `_meta` is not swept without depending
  on promotion to witness it.

Rewrite in `tests/integration/test_mcp_tools.py` (class docstring `:487-494` and
the promotion prose at `:500-502` also change):

- `:496-520` and `:522-542` → invert the `structuredContent` assertions; keep the
  `isError` and `content` assertions, which are unaffected.

New coverage:

- Extras **and** an explicit `structuredContent` → only the explicit one is
  emitted. Guards the deleted branch from returning.
- Extras, no explicit key → `structuredContent` absent **and** the text content
  identical to the input.
- A non-dict `structuredContent` (list, string) → key absent from the output
  **and** a warning emitted (`caplog`).
- An explicit `structuredContent` on `2025-03-26` → still suppressed by the gate.

Unchanged and must stay green: `:45` (old version), `:56` (explicit passthrough —
already the only test of the new contract), `:77`, `:83`, `:91`, `:97`.

### Verification

- [x] `poetry run pytest tests/test_mcp_tool_result_format.py -v` passes
- [x] `poetry run pytest tests/integration/test_mcp_tools.py -v` passes (32 passed)
- [x] `poetry run pyright actingweb tests` — 0 errors
- [x] `poetry run ruff check actingweb tests` passes
- [x] `grep -rn "_CALL_TOOL_RESERVED_KEYS" actingweb/ tests/` returns nothing

### Implementation Status: Complete

**Notes:**

- The non-dict `structuredContent` test is parametrized over list/str/int rather
  than the two cases the plan named; `caplog` is pinned to
  `logging.WARNING, logger="actingweb.handlers.mcp"` so the assertion does not
  depend on ambient logging config.
- Added `test_explicit_structured_content_still_emitted` to the integration
  regression class — the inverted tests there would otherwise leave that file
  with no positive assertion that explicit `structuredContent` survives.
- **Environment note (applies to every phase):** `make test-all-parallel` reports
  ~114 failures in this environment (`test_trust_flow`, `test_www_templates`,
  `test_devtest_attributes`, …) that cascade from `actor_url = None` — shared
  state across parallel workers, exactly the isolation issue CLAUDE.md warns
  about. The same suite run **sequentially** is fully green (2585 passed, 26
  skipped) on the unmodified branch point. Sequential is therefore the gate used
  between phases here; the parallel failures are pre-existing and unrelated.

---

## Phase 2: End-to-end wire-shape coverage

The bug reached production partly because **no test asserts the JSON that
actually leaves the handler**. The three tests in
`tests/integration/test_mcp_tools.py:487-556` are integration tests by placement
only — they import and call `format_call_tool_result` directly. The single test
that drives a real dispatch is `tests/test_mcp_tool_result_format.py:106-169`.

### Changes

- No production code changes. Test-only phase.

### New Tests, both unit and integration tests

New class in `tests/test_mcp_tool_result_format.py` (or a new
`tests/test_mcp_tools_call_wire_shape.py`), following the existing harness at
`:106-169` — `ActingWebApp` + `@mcp_tool` hooks, mocked actor, `RuntimeContext`
MCP context with a resolved `peer_id`, allow-everything permission evaluator,
driving both `MCPHandler.post` and `AsyncMCPHandler.post_async`:

- **Prose tool with extras** (`content` + a scalar key), header
  `MCP-Protocol-Version: 2025-11-25` → assert the full response dict: no
  `structuredContent` anywhere, text block present and unmodified.
- **Data tool with explicit `structuredContent`** → assert it is present and
  exact on the wire.
- **No `MCP-Protocol-Version` header** → negotiates `2025-03-26`, so no
  `structuredContent` even though the hook set it explicitly.
- Sync/async parity asserted on all of the above (`sync_result == async_result`).

Preserve the existing parity coverage at `:106-169` — whatever replaces its
`structuredContent` assertion must keep exercising both handlers.

### Verification

- [x] `poetry run pytest tests/test_mcp_tool_result_format.py -v` passes
- [x] Each wire-shape assertion names the pre-change value explicitly — i.e.
      `assert "structuredContent" not in out` against a fixture whose extras are
      **non-empty** — so restoring promotion fails the test by construction. Do
      not verify by temporarily editing `mcp.py`; the assertion should carry the
      guarantee on its own.
- [x] `poetry run pyright actingweb tests` — 0 errors

### Implementation Status: Complete

**Notes:**

- Landed as a new file, `tests/test_mcp_tools_call_wire_shape.py` (18 tests green
  together with the formatter module).
- The prose test asserts the **entire** JSON-RPC envelope by equality, on a hook
  whose extras (`run_id`, `cycle`) are non-empty, so a reinstated promotion fails
  by construction without any edit to `mcp.py`.
- **Coupling to Phase 5 resolved here, as the advisor flagged:** this module now
  owns the canonical hook shape as `canonical_weather_hook` /
  `CANONICAL_WEATHER_PAYLOAD` / `CANONICAL_WEATHER_SCHEMA`, modelled on the MCP
  spec's own worked example. Phase 5's rewritten
  `docs/guides/mcp-applications.rst` example is a copy of that hook, so the doc
  shape is *pinned by a test* rather than merely asserted in prose. The pin is
  `test_documented_shape_emits_structured_content_on_the_wire`.

---

## Phase 3: Honour an explicit `isError` on the legacy-wrap path

Today a hook that returns `{"isError": True, "error": "boom"}` — no `content`
key — reaches the wire as `{"content": [{"type": "text", "text": "{'isError':
True, ...}"}]}` with **no `isError` field**, so the error is reported to the
client as a success. Verified empirically against the current build.

### Changes

- `actingweb/handlers/mcp.py:174-177`:

  ```python
  # Legacy handling: wrap non-MCP results in a text content item.
  is_error = (
      result["isError"]
      if isinstance(result, dict) and "isError" in result
      else None
  )
  if not isinstance(result, dict):
      result = {"result": result}
  out: dict[str, Any] = {"content": [{"type": "text", "text": str(result)}]}
  if is_error is not None:
      out["isError"] = bool(is_error)
  return out
  ```

  Three constraints, all load-bearing:
  1. **`out: dict[str, Any]` is required.** Without the annotation pyright
     infers `dict[str, list[dict[str, str]]]` and `out["isError"] = bool(...)`
     fails with `reportArgumentType`. Verified: the unannotated form produces
     exactly one pyright error, the annotated form zero. This mirrors the
     existing annotation at `mcp.py:154`.
  2. **`str(result)` is unchanged.** `result` still carries `isError`, so the
     text is byte-identical to today's output. `isError` therefore appears twice
     in the response — once inside the frozen text, once as the field. That is a
     direct consequence of the constraint and should be stated in the docstring
     so it does not read as accidental.
  3. **Read `is_error` before the `if not isinstance(result, dict)` rebind.**
     (Reading after is equivalent, since the rebind produces a dict with no
     `isError` key, but the order above is the clearer expression of intent.)

- Docstring: note that the legacy branch honours exactly one wire field
  (`isError`) and, unlike the content branch, does **not** preserve `_meta` — an
  asymmetry that should be explicit rather than discovered.

### New Tests, both unit and integration tests

- `{"isError": True, "error": "boom"}` → output has `isError is True`, and the
  text is asserted as an **exact string** to pin the serialization.
- `{"isError": False, "status": "ok"}` → output has `isError is False`.
- `{"status": "deleted"}` (no `isError`) → `"isError" not in out`; text
  unchanged. This pins that existing hooks see no wire change.
- A bare non-dict value (`"hello"`) → still wrapped as `{"result": ...}`, no
  `isError`.
- A truthy non-bool `isError` (e.g. `"yes"`) → coerced to `True`, matching the
  content branch's `bool()` at `:156`.
- End-to-end: a legacy-shaped error hook through both handlers shows `isError`
  on the wire.

Existing `:91-100` legacy tests assert by subscript only and never assert
`"isError" not in out`, so they stay green.

### Verification

- [x] `poetry run pytest tests/test_mcp_tool_result_format.py -v` passes
- [x] `poetry run pyright actingweb tests` — 0 errors (specifically confirms the
      `dict[str, Any]` annotation)
- [x] The exact-string text assertion passes, proving `str(result)` unchanged
- [x] Full sequential suite green: 2604 passed, 26 skipped

### Implementation Status: Complete

**Notes:**

- **Deviation (harmless) from the plan's snippet:** no *second* `out: dict[str,
  Any]` annotation was needed on the legacy branch. `out` is already declared
  `dict[str, Any]` at the top of the content branch, and pyright applies a
  declared type across the whole function scope, so the later
  `out["isError"] = bool(...)` type-checks with 0 errors as written. The plan's
  constraint is satisfied — just by the existing annotation rather than a new
  one.
- Added `test_error_key_alone_does_not_infer_is_error`, which the plan did not
  list. It is the direct regression guard for the "honour, never infer"
  guardrail: without it nothing stops someone later reading `result["error"]` as
  a signal and silently reshaping every consumer error path.
- Also added a test pinning the documented `_meta` asymmetry, so that behaviour
  is covered rather than only described in the docstring.

---

## Phase 4: Warn when a declared `output_schema` yields no `structuredContent`

The library advertises `outputSchema` in `tools/list` (`mcp.py:719-721`) but
never consults it at call time. A tool declaring a schema and returning
content-only produces no `structuredContent`, which **both** reference clients
reject with `Tool X has an output schema but did not return structured content`.
This is broken today, independently of this change — and the shipped docs example
is exactly that shape, which Phase 5 fixes.

### Changes

- `actingweb/handlers/mcp.py:138` — extend the signature with two optional
  keyword parameters so every existing two-argument call (including all tests)
  keeps working:

  ```python
  def format_call_tool_result(
      result: Any,
      negotiated_version: str,
      output_schema: dict[str, Any] | None = None,
      tool_name: str | None = None,
  ) -> dict[str, Any]:
  ```

- Before returning from the content branch, and after the legacy branch builds
  `out`:

  ```python
  if (
      output_schema
      and supports_structured_content(negotiated_version)
      and not out.get("isError")
      and "structuredContent" not in out
  ):
      _warn_missing_structured_content_once(tool_name)
  ```

  **The version clause is load-bearing.** Without it, the gate at `mcp.py:162`
  suppresses `structuredContent` on every `< 2025-06-18` request, so a
  *correctly written* hook that sets the key explicitly would trip the warning
  on every call for every old client — reintroducing exactly the
  "trains authors to ignore it" failure that motivated moving the warning off
  `tools/list`. Below `2025-06-18` there is nothing the author can do and
  nothing the client will reject, so there is nothing to warn about.

- Module-level once-per-tool guard next to the existing module caches, following
  the `.copy()` discipline documented at `mcp.py:116-127`:

  ```python
  _output_schema_warned: set[str] = set()
  ```

  The warning names the tool and states the fix ("return an explicit
  `structuredContent` key").
- `actingweb/handlers/mcp.py:997-999` and `actingweb/handlers/async_mcp.py:194-196`
  — pass `metadata.get("output_schema")` and `tool_name`. `metadata` is already
  bound 14 lines earlier at `mcp.py:983` / `async_mcp.py:180`, so no plumbing is
  needed.

### New Tests, both unit and integration tests

- Declared schema + non-error result + no `structuredContent` → warning emitted
  naming the tool (`caplog`).
- Declared schema + explicit `structuredContent` → **no** warning. This is the
  false-positive guard that motivated call-time over `tools/list`.
- Declared schema + `isError: True` → no warning (clients skip validation on
  errors).
- No declared schema + no `structuredContent` → no warning.
- Called twice for the same tool → exactly one warning.
- Old negotiated version (`2025-03-26`) + declared schema + explicit
  `structuredContent` set by the hook → **no warning**. This is the regression
  guard for the version clause above; without it the warning fires on every call
  for every correctly-written hook talking to an old client.
- Old negotiated version + declared schema + no `structuredContent` → also no
  warning (nothing the author can fix, nothing the client will reject).
- Existing two-argument call sites still type-check and behave identically.

### Verification

- [x] `poetry run pytest tests/test_mcp_tool_result_format.py -v` passes
- [x] `poetry run pyright actingweb tests` — 0 errors
- [x] `poetry run ruff check actingweb tests` passes
- [x] Full sequential suite green: 2617 passed, 26 skipped

### Implementation Status: Complete

**Notes:**

- The predicate was factored into `_warn_if_output_schema_unsatisfied(...)`
  rather than inlined twice. Phase 3 had to land first, as the advisor noted:
  the legacy branch previously returned a literal, so there was no `out` to
  inspect until Phase 3 created one.
- **Test-isolation hazard fixed, per the advisor.** `_output_schema_warned` is
  module state that outlives a test, so "warns" and "warns only once" would pass
  or fail depending on execution order — a real flake under
  `make test-all-parallel`. Every test in `TestOutputSchemaWarning` uses a
  distinct tool name *and* an autouse fixture clears the set. `caplog` is pinned
  to `logging.WARNING, logger="actingweb.handlers.mcp"`.
- `tool_name` is `str | None`, so the guard keys on `tool_name or "<unknown>"` —
  `set[str].add(None)` would not type-check.
- Skipped the `.copy()` discipline the plan suggested: that pattern at
  `mcp.py:116-127` guards *iteration* under concurrent mutation, and a set
  membership test plus add never iterates.
- **Added two dispatch-level tests the plan did not list**, in
  `test_mcp_tools_call_wire_shape.py`. This matters: the decorator stores
  `output_schema` while `tools/list` emits `outputSchema`, and every unit test
  passes the schema to the formatter as an explicit kwarg — so all of them would
  still pass if the dispatch loop read the wrong key. Only a real dispatch
  proves the plumbing. (Key verified as `output_schema` at
  `actingweb/mcp/decorators.py:89`.)

---

## Phase 5: Documentation sweep

### Changes

**The contract, and the example that becomes spec-violating:**

- `docs/guides/mcp-applications.rst:356-363` — rewrite the three bullets that
  document promotion.
- `docs/guides/mcp-applications.rst:365-382` — **rewrite the worked example.**
  It declares `output_schema` *and* relies on promotion (comment at `:379`:
  "Promoted into structuredContent on >= 2025-06-18"). Copy-pasted after this
  change it produces a tool that advertises `outputSchema` and returns no
  `structuredContent` — rejected by strict clients. Replace with a hook that sets
  `structuredContent` explicitly and serializes the same object into `content`,
  per the spec's backwards-compatibility guidance.
- `docs/guides/mcp-applications.rst:403` — add a warning that an absent
  `MCP-Protocol-Version` header defaults to `2025-03-26` and therefore suppresses
  `structuredContent` **even when set explicitly**.

**Discovery surfaces:**

- `CHANGELOG.rst:5-6` — new `v3.13.0rc4` entry under the empty `Unreleased`,
  written as a migration note. Frame the rationale on correctness, **not payload
  size**: for the incident tool (≈135 KB of prose plus one `run_id`) removing the
  promotion saves essentially no bytes. Do note the hardening angle — a hook
  spreading `trust.to_dict()` (which carries `secret`,
  `interface/trust_manager.py:129-131`) or `properties.to_dict()` (which can carry
  `oauth_token` / `oauth_refresh_token`) into a `content`-bearing dict currently
  ships those keys to the model.
- `CHANGELOG.rst:745` — amend the v3.11.0 entry that documents promotion, rather
  than only appending a new one; that line is what a developer greps for.
- `docs/migration/v3.13.rst` — new top section mirroring the rc3 pattern at
  `:5-19` (version-scoped heading + `.. note::` scoping applicability). Include
  the two-step migration and the "text block is the only thing that always
  arrives" caveat.
- `docs/migration/v3.13.rst:9-19` **and** the following "Overview" note — both
  enumerate the document's sections ("read **both**"); adding rc4 makes those
  counts wrong.
- `docs/migration/index.rst:22-40` — the prose list starts at v3.11 and has **no
  v3.13 entry at all**, though v3.13 is in the toctree at `:15`. Add one; rc4 is
  the first code-level breaking change in the 3.13 line.
- `docs/guides/troubleshooting.rst` — new entry after `:65` in the established
  Symptom/Cause/Fix shape, covering both the vanished structured data and the
  strict-client rejection for schema-declaring tools.
- `docs/migration/v3.11.rst:164` — currently lists `structuredContent` as a new,
  no-action-required feature; add a forward pointer to the rc4 note.

**The `output_schema` ⇄ `structuredContent` confusion.** No document anywhere
states that `output_schema` does not cause `structuredContent` to be emitted;
`hooks-reference` even documents auto-deriving `output_schema` from a TypedDict
return annotation, which makes the implied link stronger. Add one clarifying
sentence to each:

- `actingweb/mcp/decorators.py:37` — and fix its two examples at `:70` and `:77`,
  neither of which has a `content` key (both hit the legacy path). This docstring
  is the most likely place a developer looks; give it the canonical return shape.
- `docs/reference/hooks-reference.rst:328`, `:351-372`, `:392`
- `docs/quickstart/configuration.rst:790`
- `actingweb/interface/hooks.py:1395`, `:1447` and
  `actingweb/interface/app.py:1094`, `:1125` — published via autodoc
  (`docs/reference/interface-api.rst:26`).

**Testing guidance.** `docs/guides/mcp-applications.rst:692-737` and
`docs/guides/mcp-quickstart.rst:133-135` tell developers to test tools via
`app.hooks.execute_action_hooks(...)`, which bypasses `format_call_tool_result`
entirely — so the documented approach is structurally blind to this change. Add
an example asserting on the formatter directly.

**Quickstart:** `docs/guides/mcp-quickstart.rst:118-124` — the `tools/call` curl
sends no `MCP-Protocol-Version` header, so a developer verifying a freshly
migrated hook sees no `structuredContent` and concludes their code is broken. Add
`-H 'MCP-Protocol-Version: 2025-06-18'`.

**Two pre-existing corrections:**

- `CHANGELOG.rst:812-814` and `docs/migration/v3.11.rst:125-127` both claim
  `tools/call` results "always include `isError`". Never true of the legacy
  branch, and still conditional after Phase 3. Correct both; the new rc4 entry
  must not restate "always".
- `thoughts/plans/2026-05-26-mcp-version-negotiation-structuredcontent.md`
  (`:86-89`, `:183-184`, `:202`, `:348`) records "MVP = promote all extras" as the
  resolved decision and open question O3. `actingweb/mcp/protocol.py:12` cites
  that file **from shipping code**, so the citation now leads to a reversed
  decision. Add a resolution note pointing at this plan. Two constraints, since
  that file is a dated snapshot: leave its `status:` alone (the plan was
  delivered; only one decision within it was later reversed), and confine the
  edit to a **single dated line near the top** — do not rewrite the O3 decision
  text at `:86-89` or `:348`. A future reader must still be able to see what was
  decided on 2026-05-26 and why, or the annotation destroys the record it exists
  to correct.

### New Tests, both unit and integration tests

- Docs build clean (Sphinx warnings are the failure signal for `.rst` edits).
- Any Python in the rewritten `mcp-applications.rst` example is exercised as a
  test hook in the Phase 2 wire-shape suite, so the documented shape is proven to
  produce `structuredContent` on the wire rather than merely asserted in prose.

### Verification

- [x] Docs build without new warnings — **baseline was 0 warnings, after is 0
      warnings.** (Sphinx root is the repo root, `conf.py` at top level, not
      `docs/conf.py`; build with `poetry run sphinx-build -b html . <out>`.)
- [x] `grep -rn "promoted into" docs/ actingweb/` returns nothing describing the
      removed behaviour (excluding `docs/_build/` and `thoughts/`). Four hits
      remain, all correct: three are past-tense ("used to be", "were", "no
      longer"), and `CHANGELOG.rst:814` is the historical v3.11.0 entry, which
      is amended with a `.. warning::` rather than rewritten — a changelog is a
      record of what shipped.
- [x] `grep -rn "always include" CHANGELOG.rst docs/migration/` — no surviving
      inaccurate `isError` claim (the two remaining hits are about trust
      timestamps and trust secrets, unrelated)
- [x] The rewritten guide example, pasted into a hook, emits `structuredContent`
      on the wire (covered by the Phase 2 test)
- [x] Full sequential suite green: 2617 passed, 26 skipped
- [x] pyright 0 errors, ruff check + format clean

### Implementation Status: Complete

**Notes:**

- **Skipped one plan target as a misidentification.**
  `docs/quickstart/configuration.rst:790` is the `CachedCapability` attribute
  list for *peer capability caching*, not MCP tool output. The plan reached it
  via a bare `output_schema` grep. Adding an MCP `structuredContent` note there
  would be actively misleading, so it was left alone.
- **Changelog conflict with Phase 6 resolved as the advisor directed:** Phase 5
  writes the rc4 **body** under the existing empty `Unreleased` heading and does
  not touch the heading. Phase 6 renames that heading and inserts a fresh empty
  `Unreleased` above it. Writing an `rc4` heading here would have produced two
  rc4 sections after Phase 6's rename, and nothing in CI would catch it.
- Added a `.. _mcp-structured-tool-output:` label to the guide so
  `hooks-reference.rst` can cross-reference it; the quickstart's testing tip
  points at a new `.. _testing-the-wire-shape:` section. Both resolve — the
  build is warning-free, which is the check that proves it.
- The guide example is a copy of `canonical_weather_hook` from
  `tests/test_mcp_tools_call_wire_shape.py`, **including the `output_schema=`
  decorator argument** — a doc example showing the return shape but dropping the
  decorator arg would teach half the contract, and no grep gate would notice.
- `actingweb/mcp/decorators.py` gained a "Return shape" docstring section; both
  of its examples previously returned dicts with no `content` key, i.e. the
  legacy text-wrap path, which is rarely what an author wants.
- The 2026-05-26 plan's annotation went into its existing **Update Log** as a
  single dated entry. Its `status:` is unchanged and the O3 decision text at
  `:86-89`/`:348` is untouched, so the record of what was decided on 2026-05-26
  survives intact.

---

## Phase 6: Release `3.13.0rc4`

Per `CLAUDE.md`: the version bump and changelog rename ride in this same PR;
`master` is protected, so only the tag is pushed afterwards.

### Changes

- `pyproject.toml:3` — `version = "3.13.0rc4"`
- `actingweb/__init__.py:1` — `__version__ = "3.13.0rc4"` (must match the tag
  exactly; CI validates)
- `CHANGELOG.rst` — rename `Unreleased` to `v3.13.0rc4: August 3, 2026`, add a
  fresh empty `Unreleased` above it
- Commit `Pre-release v3.13.0rc4`; merge; then `git pull` and
  `git tag v3.13.0rc4` on the merge commit; `git push --tags`

### New Tests, both unit and integration tests

None — release mechanics. The full suite is the gate.

### Verification

**Local (run before pushing):**

- [ ] `make test-all-parallel` — all tests pass (DynamoDB backend)
- [ ] PostgreSQL backend run: `docker compose -f docker-compose.test.yml up
      postgres-test -d`, then `DATABASE_BACKEND=postgresql PG_DB_HOST=localhost
      PG_DB_PORT=5433 PG_DB_NAME=actingweb_test PG_DB_USER=actingweb
      PG_DB_PASSWORD=testpassword make test-integration`
- [ ] `poetry run pyright actingweb tests` — 0 errors
- [ ] `poetry run ruff check actingweb tests` passes
- [ ] `poetry run ruff format --check actingweb tests` passes
- [ ] Both version files match `3.13.0rc4` exactly

**CI-only (cannot be satisfied locally — do not tag until these are green):**

- [ ] CI green on **both** database backends on the PR
- [ ] Tag-time version validation passes (CI checks the tag against both files)

**Post-tag (observed, not run):**

- [ ] CI publishes to **TestPyPI** (pre-release), GitHub Release marked
      pre-release

Note the local Postgres run is a *pre-check*, not a substitute for the CI
matrix — a locally green single-backend run is not evidence the merge gate is
satisfied.

### Implementation Status: Not Started

---

## Evaluation Notes

### Architecture

Two blockers found, both now folded into the plan:

1. **The proposed `isError` snippet fails pyright.** Reproduced: without an
   explicit annotation, `out` infers as `dict[str, list[dict[str, str]]]` and the
   `isError` assignment raises `reportArgumentType`. Given the repo's
   zero-tolerance policy this would be a build break. Fixed by `out: dict[str,
   Any]` (verified: 0 errors), mirroring `mcp.py:154`. → Phase 3.
2. **Seven existing tests pin the deleted behaviour**, plus three test docstrings
   documenting promotion as the contract. → Phases 1 and 2.

Also incorporated: `_CALL_TOOL_RESERVED_KEYS` becomes fully dead and ruff won't
flag it (Phase 1); the docs example needs rewriting rather than a prose tweak
(Phase 5); the legacy branch's `_meta` asymmetry should be documented (Phase 3).

Confirmed safe: `format_call_tool_result` is not exported from
`actingweb/__init__.py`, not autodoc'd, and has no call sites beyond the two
handlers and the tests. Both transports nest the returned dict verbatim under
`"result"` and never inspect it (`flask_integration.py:1441`,
`fastapi_integration.py:2380`), so a conditional `isError` is inert downstream.

### Security

**No objection to either edit; both are net-positive.**

Removing the sweep *closes* an exposure channel. The swept dict is entirely
hook-authored and the library never injects keys, but a hook doing
`return {"content": [...], **rel.to_dict()}` currently ships the trust row's
`secret` (`interface/trust_manager.py:129-131`, backed by `db/*/trust.py`) to the
model; `properties.to_dict()` can likewise carry `oauth_token` /
`oauth_refresh_token` (`handlers/oauth2_spa.py:891-899`). After the change only an
explicitly named `structuredContent` leaves the process. This framing is in the
CHANGELOG (Phase 5) — with the caveat that the **legacy** path's `str(result)`
still stringifies the whole dict, so the win is scoped to the content branch.

Nothing security-relevant stops reaching the client: every authorization denial
returns a JSON-RPC error object via `_create_jsonrpc_error` and never touches the
formatter. Honouring `isError` is itself an improvement — it closes a
false-success signal on in-hook denials.

Noted, not actioned: `bool()` on an exotic hook value can raise into the existing
`-32603` handler (pre-existing echo); the permission check fails open at
`mcp.py:973-975` but only *after* the fail-closed trust gate at `:948-951`, so it
cannot admit an untrusted client; the rc3 trust-cache fix is untouched, since the
formatter is a pure module-level function with no access to any cache.

### Scalability

**Nothing blocks — but the plan's *justification* was corrected.** The payload
argument is much weaker than it first appears: for the incident tool
(`agent_run`, ≈135 KB of prose plus a single `run_id`) removing the sweep saves
essentially **zero** bytes. The saving is bounded above by the serialized size of
the extras, which is hook-dependent and not observable from the library. The
CHANGELOG wording in Phase 5 therefore leads with correctness, not size.

Confirmed non-issues: the response is serialized exactly once per transport;
`extras` is a shallow comprehension over an already-materialized dict (O(top-level
keys), values referenced not copied); nothing caches or logs the formatted result;
`get_config()` is memoized so per-request handler construction is cheap.

Flagged as pre-existing and out of scope: `str(result)` double-materializes large
legacy-path payloads; `client_platform` derives from `User-Agent`
(`mcp.py:1944-1945`), so a client with a varying UA triggers a DB read+write per
call. Both are `thoughts/todo/` candidates.

### Usability

Drove the largest expansion of scope. The critical finding is **P0**: the shipped
guide example (`docs/guides/mcp-applications.rst:365-382`) declares `output_schema`
*and* relies on promotion, so after this change a copy-paste of the library's own
documentation produces a tool that advertises `outputSchema` in `tools/list` and
never returns `structuredContent` — moving from "works" to "client-side
validation error" with no warning from either side. Rewriting it is in the same
PR (Phase 5), and Phase 4's call-time warning targets exactly that population.

Two ergonomic traps became warnings rather than documentation: a non-dict
`structuredContent` (a list is the natural shape for a search tool) previously
fell through to promotion and now vanishes entirely; and the `output_schema`
mismatch above.

Two traps that documentation alone must cover: the documented **verification
procedure cannot see `structuredContent`** (the quickstart curl sends no
`MCP-Protocol-Version` header, so the gate suppresses it even when explicit), and
the documented **testing strategy bypasses the formatter** entirely
(`execute_action_hooks`), so a developer's suite stays green while their wire
output regresses.

The evaluator also observed that shipping *no* signal is this repo's outlier —
the DynamoDB migration in this same 3.13 line ships a per-hit deprecation warning
plus a startup tripwire, and the rc3 troubleshooting entry is built around a
warning existing. The resolution keeps dropped extras silent (they are a
deliberate migration, not an error) while warning on the two genuine author
errors.
