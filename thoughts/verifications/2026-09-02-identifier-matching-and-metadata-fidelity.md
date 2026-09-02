# Verification: identifier matching, attribute contracts, MCP metadata fidelity (v3.14.4)

**Date:** 2026-09-02
**Plan:** thoughts/plans/2026-09-02-identifier-matching-and-metadata-fidelity.md
**Research:** none — four todo files (rows 21, 23, 24, 25) plus the plan's four reviews
**Branch:** `release/3.14.4-identifier-matching`
**PR:** #141, "Release v3.14.4"
**Merge commit:** `5f0c626`
**Tag:** `v3.14.4` on that commit; workflow run 33662890157 — validate, publish-pypi, github-release all success; TestPyPI skipped (stable)

Scope: all four phases of the plan, the two Codex P2s and the Claude review
on PR #141.

## Automated Check Results

- **Ruff check / format:** Pass (`poetry run ruff check actingweb tests`; `ruff format --check`, 364 files already formatted)
- **Pyright:** Pass (0 errors, 0 warnings, 0 informations)
- **Sphinx** (CI invocation, `-W --keep-going`): Pass, locally and in CI
- **`make test-all-parallel`, DynamoDB Local:**
  - after Phase 1: 3310 passed, 31 skipped (7:52)
  - after Phase 3: 3332 passed, 2 failed, 1 error (7:51) — all three re-run
    sequentially: `test_pg_delete_diagnostics` was real (the DELETE statement
    gained `AND bucket = %s`; expectation updated in the release commit), the
    other two (`test_hot_path_n_plus_one`, `test_bulk_list_update_handles`)
    passed sequentially and are the documented parallel-isolation class
- **PostgreSQL integration, sequential** (`tests/integration`, `DATABASE_BACKEND=postgresql` against the port-5433 container): 916 passed, 16 skipped (0:31)
- **CI on PR #141** (both commits `77e2b29` and `c695f4f`): Tests (dynamodb) 3317 passed, Tests (postgresql) 3210 passed, no flaky retries; Documentation Build, type-check, test-summary, claude-review all pass

Note: the unit suite cannot run inside the Claude Code sandbox
(`pytest-rerunfailures` binds a localhost socket at configure time). It ran
outside the sandbox.

## The security finding, re-verified live

The plan's manual step was a `curl` of `PUT …/properties/private/%0Asecret`.
That form does not reach a handler: Starlette's `{name:path}` and Werkzeug's
`<path:name>` both stop at a newline and answer 404. The reachable form is the
JSON body of `POST /{actor}/properties`. Against the harness with `actingweb/`
stashed at `e8eddf1` (the pre-fix tree), a `friend` peer:

| key | before | after |
| --- | --- | --- |
| `{"private/x": "v"}` | 403 | 403 |
| `{"private/\nx": "v"}` | **201**, row in owner's listing | 400 |
| `{"_internal/\nx": "v"}` | **201** | 400 |
| `{"secret\tx": "v"}` | 201 (not excluded; ordinary write) | 400 |

Recorded as a correction note in the plan's Phase 1 and pinned by
`tests/integration/test_property_path_control_chars.py` on both backends.

## Phase-by-phase

- **Phase 1** — `2a6f23a`. `\Z` + DOTALL, bounded pattern cache,
  control-character guard (moved ahead of the permission-map lookup in
  `c695f4f` after Codex), six other validators, `uri_pattern` fullmatch, six
  MCP checks fail closed, write-time rejection. New:
  `tests/test_permission_pattern_matching.py` (16),
  `tests/test_mcp_uri_template.py`, `tests/test_oauth2_state_classification.py`,
  `tests/integration/test_property_path_control_chars.py` (9, both backends);
  `TestFailOpenPreservedOnEvaluatorErrors` became
  `TestFailClosedOnEvaluatorErrors` (6 cases, both transports).
- **Phase 2** — `fb7a128`. PostgreSQL `get_bucket()` `{}`; upsert rewrites
  `bucket`/`name`; exact bucket compare on five point paths per backend.
  `test_db_attribute_buckets.py` flips the `_bucket_loaded` assertion to
  `is True` on both backends and asserts last-writer-wins plus point-read
  isolation.
- **Phase 3** — `629935c`. `build_mcp_info()`, lifted registry helpers,
  `GET /mcp` derivations, `get_oauth_discovery_metadata()` deleted, `fqdn` /
  `proto` validation. `tests/test_mcp_info.py`,
  `tests/integration/test_mcp_info_route.py` (both frameworks, both
  backends), `TestHostSettingValidation` in `tests/test_config.py`. The
  `/mcp/info` route test lives under integration because the FastAPI request
  path ensures DynamoDB tables.
- **Phase 4** — `77e2b29` + `c695f4f`. Changelog under `SECURITY` / `FIXED`
  / `CHANGED` / `REMOVED`; versions `3.14.4`; four todos deleted, INDEX rows
  21/23/24/25 removed, rows 27–31 filed.

## Observed while implementing, not in the plan

- `tests/test_mcp_server_name.py::TestWithMcpBuilderPropagation` takes
  ~25 s per test because `ActingWebApp.get_config()` reaches for the default
  DynamoDB endpoint without the test environment set. Pre-existing (timed at
  the pre-Phase-3 tree: 26.8 s), not touched.
- The MCP `*/list` filters remain fail-open; folded into
  `thoughts/todo/permission-uri-prefix-branch.md` (row 29).

## Post-release

- Consumer check from `../actingweb_mcp`, done 2026-09-02 after PyPI listed
  3.14.4 (upload 17:44:42Z): pin bumped to `=3.14.4`, `poetry update
  actingweb`, `poetry run pytest` — **3788 passed, 7 skipped, 150
  deselected (5:24)** against its PostgreSQL container. `GET /mcp/info`
  through its FastAPI app: 200, `server_name: "emm"`, `description:
  "ActingWeb app: urn:actingweb:actingweb.io:actingweb-ai-memory"`,
  `supported_features: ["tools", "resources", "prompts"]`, none of
  `tools_count`/`prompts_count`/`actor_lookup`/`version` present. The
  trust-relationships surface there is a websocket handler covered by that
  suite (`tests/test_trust_utils.py`), not curl-able; nothing else owed. The
  pin bump is left **uncommitted** in the consumer for its owner.
