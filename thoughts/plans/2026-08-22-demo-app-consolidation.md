---
status: done
---

# Implementation Plan: Consolidate the demo app into the library repository

**Date:** 2026-08-22
**Research:** thoughts/research/2026-08-22-ai-agent-discoverability.md
**Related plan:** thoughts/plans/2026-08-22-ai-agent-discoverability.md
**Branch:** implemented on `consolidate-demo-app`,
[PR #137](https://github.com/actingweb/actingweb/pull/137)

## Overview

Move the ActingWeb demo *application code* into this repository as
`examples/demo/`, leaving the *deployment pipeline* in `actingwebdemo`, which
becomes a thin wrapper. The goal is a worked example that is version-locked to the
library, tested by CI, and citable from the documentation — and a live
`demo.actingweb.io` that is not seven months and two minor versions behind.

This plan exists because the demo question surfaced while planning
`2026-08-22-ai-agent-discoverability.md` and is too large to be phases 10+ of a
documentation change set. It also carries a security decision that deserves its
own statement rather than a footnote.

## Background: what was found

Investigated 2026-08-22 against `/Users/wedel/src/actingweb/actingwebdemo`:

| Fact | Value |
| --- | --- |
| `demo.actingweb.io` | **live, 200** |
| Last commit | `1493355`, **2026-01-18** — ~7 months stale |
| Library pin | `actingweb = { version = ">=3.9.0", extras = ["flask"] }` (`pyproject.toml:18`) |
| Lock resolves | **`actingweb 3.9.0`** — verified in `actingwebdemo/poetry.lock`, so the deployed code really is five minor releases old, not merely permitted to be |
| Current library | 3.14.0 |
| Deploy mechanism | Serverless Framework, **manual from a laptop** — `provider.profile: default` (`serverless.yml:79`) reads `~/.aws/credentials` |
| Secrets | untracked `.env` via `serverless-dotenv-plugin` — `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `NUKE_SECRET` |
| Deploy CI | **none** — `.github/workflows/` holds only `claude.yml`, `claude-code-review.yml` |
| Custom domain | `demo.actingweb.io`, ACM cert on AWS account `473852420549` (`serverless.yml:22-28`) |
| Serverless version | **Core 3.40.0** — out of support |
| App code size | `application.py` 298 lines + `shared_hooks/` ~1,580 lines |
| Legacy deploy config | `.ebextensions/`, `.elasticbeanstalk/`, `Dockerrun.aws.json` — Elastic Beanstalk, apparently unused |

The demo is cleanly structured for a move: `shared_hooks/__init__.py` exposes a
single `register_all_shared_hooks(app)` entry point, and every hook module is a
plain function taking the app. There is one wart —
`application.py:26` does `sys.path.insert(...)` to import `shared_hooks` — which
the move should fix rather than carry.

## Decisions Made

- **Code in, deploy out.** The application code moves into this repository; the
  deployment pipeline does not. Rationale below — this is the load-bearing
  decision and it is a security decision, not a preference.
- **`examples/` is repo-only.** Not added to `pyproject.toml:25-27` `include`, so
  no example code ships in a consumer's `site-packages`. The wheel stays lean and
  the wheel's contents stay to-the-point.
- **`actingwebdemo` consumes the example as a git submodule** pinned to a release
  tag. A submodule pinned to `v3.14.0` makes version correspondence structural
  rather than documented — it is precisely the floating-`>=3.9.0` problem's
  inverse. Serverless packages the working tree, so a checked-out submodule
  packages without special handling. Rejected alternatives: a copy/sync script
  (drifts silently, which is the defect being fixed) and publishing examples in
  the wheel (rejected above).
- **Serverless v3 → v4 is out of scope.** See "What We're NOT Doing".

## Why the deployment does not move

Baking `demo.actingweb.io` deployment into this repository means placing AWS
deploy credentials — or an OIDC role trusted to update Lambda and API Gateway on
account `473852420549` — plus a live OAuth client secret into the same repository
that holds `POETRY_PYPI_TOKEN_PYPI` and publishes to PyPI on tag.

Today, a compromise of this repository yields a malicious wheel. Afterwards it
would yield a malicious wheel **and** control of a live OAuth-configured service
holding real users' trust relationships. For a library whose entire value
proposition is per-user data isolation, that is the wrong trade at any convenience
saving.

This is a blocker on that half, not a caveat. The code move is not blocked by it.

## What We're NOT Doing

- **Not moving deployment, credentials, or the custom domain into this
  repository.** Stated above.
- **Not migrating Serverless Framework v3 → v4.** Core 3.40.0 is out of support
  and v4 requires a license key; the alternatives (SAM, CDK, Terraform) are a
  larger decision than this plan. It is a cost `actingwebdemo` owes regardless of
  where the code lives, and it is tracked as its own item — see "Follow-up" —
  rather than smuggled in here.
- **Not adding a deploy workflow to `actingwebdemo`.** Deployment stays manual.
  Automating it is a separate decision with its own credential questions.
- **Not archiving or deleting `actingwebdemo`.** It remains the deployment
  repository and the thing `README.rst` links to.
- **Not touching the Elastic Beanstalk config** (`.ebextensions/`,
  `.elasticbeanstalk/`, `Dockerrun.aws.json`). It appears unused, but "appears
  unused" is not evidence, and confirming it is not this plan's job.
- **Not adding the demo's OAuth setup to this repository's test matrix.** The CI
  test in Phase 2 checks the app *builds and registers*, not that OAuth works
  against Google.

## Prerequisite

**Phase 2 of `thoughts/plans/2026-08-22-ai-agent-discoverability.md` creates
`examples/`** (for `examples/p2p_quickstart.py`). This plan's Phase 1 extends that
directory rather than creating it. Running this plan first is possible but means
Phase 1 here creates `examples/` instead — coordinate, do not duplicate.

Every phase's PR adds a `CHANGELOG.rst` entry under "Unreleased", per `CLAUDE.md`.
Ordinary PRs carry no version bump.

---

## Phase 1: Land `examples/demo/` in this repository

Pure code move plus import hygiene. No deployment configuration crosses the
boundary.

### Changes

- `examples/demo/application.py` (new) — from `actingwebdemo/application.py`.
- `examples/demo/shared_hooks/` (new) — from `actingwebdemo/shared_hooks/`:
  `__init__.py`, `protocol/` (`subscription_hooks`, `trust_hooks`,
  `lifecycle_hooks`), `app/` (`method_hooks`, `action_hooks`, `callback_hooks`,
  `property_hooks`, `ui_hooks`).
- `examples/demo/templates/` and `examples/demo/static/` (new) — from
  `actingwebdemo/templates/` and `actingwebdemo/static/`. **Deviation found during
  implementation, not in the original plan text**: several templates
  (`aw-actor-www-init.html`, `aw-actor-www-root.html`,
  `aw-oauth-authorization-form.html`) are genuine overrides of the library
  defaults registered by `flask_integration.py`'s fallback blueprint, plus a
  demo-only `aw-actor-www-demo.html` and `static/style.css`/`favicon.png`.
  Without these the moved example silently falls back to library-default
  styling instead of reproducing the demo. Confirmed no secrets in these files
  before moving.
- `examples/demo/application.py` — **removed the original `sys.path.insert`
  hack** (it inserted `shared_hooks/` itself, which was accidentally
  redundant — the file's own directory is already on `sys.path` when run as
  a script). **Deviation from the plan's literal wording, caught by
  `advisor()` after an initial pass declared this done**: a bare
  `from shared_hooks import ...` with no `sys.path` insertion resolves for
  direct script execution and for a test that manually inserts
  `examples/demo/` onto `sys.path` — but not for a WSGI loader importing a
  dotted path (`examples.demo.application`, what Phase 4's
  `serverless.yml` `custom.wsgi.app` needs), which puts the *deployment
  root* on `sys.path`, not `examples/demo/` itself. Confirmed the failure
  with `importlib.util.spec_from_file_location` (no `sys.path`
  scaffolding) before fixing. A pure package-relative import
  (`from .shared_hooks import ...`) was considered and rejected: it would
  require `examples/demo/__init__.py`, and relative imports fail when a
  file is executed directly as `__main__` — breaking the
  `python examples/demo/application.py` invocation this plan's own
  `README.md` documents. The fix instead explicitly inserts *this file's
  own directory* (`os.path.dirname(os.path.abspath(__file__))`) onto
  `sys.path` before the `shared_hooks` import — the correct target the
  original hack got wrong, not a return to the hack itself. Works under
  script execution, WSGI dotted-path import, and `importlib.util` loading
  by file path.
- `examples/demo/README.md` (new) — what the example demonstrates, how to run it
  locally, and an explicit statement that deployment lives in `actingwebdemo`.
- `examples/demo/.env.example` (new) — the environment variables the app reads,
  with **placeholder values only**. Never a real client ID or secret.
- `examples/README.md` (new, or extended if the discoverability plan created it)
  — index of what lives under `examples/`.
- `pyproject.toml` — **no change**. `examples/` is deliberately absent from
  `include`; verify it does not appear in the built wheel.
- `.gitignore` — ensure `examples/demo/.env` is ignored, so a local run cannot
  commit real credentials.
- `pyrightconfig.json:2-5` — add `"examples"` to `include` if the discoverability
  plan's Phase 2 has not already. It currently lists only `actingweb` and
  `tests`, so pyright skips `examples/` silently even when the path is passed
  explicitly. (Already done by that plan's Phase 2 — confirmed at
  implementation time, no change needed here.)
- `pyproject.toml`'s `[tool.poetry.group.dev.dependencies]` — **deviation
  found during implementation, not in the original plan text**: added
  `python-dotenv = "^1.0"`. `application.py` does `from dotenv import
  load_dotenv` at module scope; this repository had no `python-dotenv`
  dependency at all (the demo repo's own `pyproject.toml` carried it, but
  that pin does not travel with a plain file copy). Without it the import
  smoke test fails immediately. Scoped to the dev group since `examples/`
  never ships in the wheel. `poetry lock` regenerated accordingly.

### New tests

Landed as `tests/test_demo_example.py`, following the `test_mcp_quickstart.py`
/ `test_p2p_quickstart.py` pattern (import the example module directly by
inserting its directory onto `sys.path`, not a package import).

- `test_demo_example_app_builds` — imports `application.py` and asserts
  `aw_app`/`app` construct. **Deviation from the plan's "without network or
  database access" framing**: unlike the two quickstart scripts (which
  defer `integrate_fastapi()`/`integrate_flask()` to `if __name__ ==
  "__main__":`), `application.py` calls `integrate_flask()` at *module*
  scope — a WSGI deployment imports `application:app` and needs it fully
  wired as a module attribute, so this can't be deferred without breaking
  the thing Phase 4/5 actually deploys. `integrate_flask()` triggers
  `_prewarm_dynamodb_tables()` / `_check_lookup_backfill_needed()`
  (`actingweb/interface/app.py`), both DynamoDB calls. Both degrade
  gracefully on connection failure (caught, logged, not raised), and
  `tests/conftest.py`'s `pytest_configure` always points `AWS_DB_HOST` at
  `localhost` before any test module imports — so this test is safe
  regardless of whether DynamoDB Local is running, but it is not literally
  network-free. Runs in ~1s against DynamoDB Local, ~70s against nothing
  (connection-timeout retries) — CI always has DynamoDB Local up for the
  whole `tests/` run (`.github/workflows/tests.yml`), so this is a non-issue
  there.
- `test_demo_example_imports_without_sys_path_scaffolding` — loads
  `application.py` via `importlib.util.spec_from_file_location` with no
  `sys.path` insertion, reproducing the WSGI dotted-path import case. Added
  after `advisor()` pointed out that `_import_demo_application()`'s manual
  `sys.path` insert does the same thing the removed hack did and so
  structurally cannot catch a regression in the import-hygiene fix above —
  this test is the one that actually exercises the fix.
- `test_demo_example_registers_all_shared_hook_categories` — checks all
  eight hook categories `shared_hooks/__init__.py`'s docstring promises
  actually landed on `aw_app.hooks` (`_subscription_hooks`,
  `_lifecycle_hooks["trust_approved"]`, `_lifecycle_hooks["actor_created"]`,
  `_method_hooks`, `_action_hooks`, `_callback_hooks["email_verify"]`,
  `_property_hooks["email"]`, `_callback_hooks["www"]`).
- `test_demo_example_not_in_built_wheel` — builds a wheel into a
  `tempfile.TemporaryDirectory()` and asserts no `examples/` entries.
  **Deviation**: the plan's own verification one-liner below
  (`glob.glob('dist/*.whl')[-1]`) has a real bug — `dist/` accumulates
  wheels from every past release with no naming convention that sorts
  newest-last (verified: plain `glob.glob` picked `3.4.1` over the current
  `3.14.0` in this checkout), so a naive last-of-glob check silently
  verifies the wrong artifact. The test builds to a scratch directory
  instead of trusting `dist/`.

### Verification

- [x] `poetry run pyright actingweb tests examples` — 0 errors
- [x] `poetry run ruff check actingweb tests examples` passes (after
      `ruff check --fix`; the demo repo's code had never been run through
      this repo's ruff config — import sorting and one `typing.Dict` ->
      `dict` modernization)
- [x] `poetry run ruff format --check actingweb tests examples` passes
- [x] `poetry run pytest tests/ -k demo_example -v` passes (3 passed)
- [x] Wheel-exclusion check passes — see the corrected version under "New
      tests" above; the plan's original one-liner is unreliable in this
      repo's `dist/` and should not be reused as written
- [x] **Superseded, do not re-check literally**: the plan's original
      "`grep -c "sys.path.insert" ... returns 0`" check assumed any
      `sys.path.insert` was the defect. It was actually the *wrong target*
      (`shared_hooks/` itself, accidentally redundant) that was the defect
      — see the "New tests" / "Changes" entries above. A corrected
      `sys.path.insert` of this file's own directory is present and
      required for the WSGI import case; `grep -c` now correctly returns
      `1`, not `0`.
- [x] `grep -rniE "client_secret *= *[\"'][^\"']+|AKIA[0-9A-Z]{16}" examples/`
      finds nothing
- [x] Manual: ran the example locally against DynamoDB Local, confirmed
      `/health` (Flask-specific response, distinguishing it from other apps)
      and `/www` (factory page, titled "ActingWeb Demo - Create Actor" —
      confirming the moved template override is actually served, not a
      library-default fallback) both respond. Full suite
      (`poetry run pytest tests/ -m "not benchmark" -n 4 ...`) also run:
      3092 passed, 31 skipped, 0 failed.

**Safety incident during this phase, recorded for future implementers**: an
early ad hoc smoke-test import (a bare `python -c` script, not run through
pytest) skipped `tests/conftest.py`'s `AWS_DB_HOST` default and made a live,
read-only DynamoDB `scan(limit=1)` against this machine's real default AWS
account (region `us-west-1`, table prefix `demo_actingweb` — the same
default `actingwedemo`'s live deployment uses). No writes occurred, but this
should not have happened. Root cause: `ActingWebApp.integrate_flask()`
touches DynamoDB unconditionally unless `AWS_DB_HOST` is explicitly set, and
this sandbox's network allowlist did not block the AWS SDK's raw connection
the way it blocks other outbound traffic. **Anything that imports or
constructs this demo app outside of pytest (which gets `conftest.py`'s
safe defaults for free) must set `AWS_DB_HOST` explicitly first.**

### Implementation Status: Complete

---

## Phase 2: CI tests the example against the library

The point of the move is that the demo cannot silently rot against the library.
That only holds if CI enforces it.

**Finding at implementation time: this phase requires no workflow changes.**
The `changes` job's classification (`.github/workflows/tests.yml:73-111`) is a
`case` statement over changed files: `thoughts/*`/`AGENTS.md`/`CLAUDE.md`/
`TODO.md` are excluded, `CHANGELOG.rst` sets both outputs, `docs/*`/`*.rst`/
`conf.py` sets `docs` only, and — the relevant branch — **everything else
falls through to the wildcard `*)` case, which already sets
`code=true` and `docs=true`.** `examples/**` matches none of the specific
patterns, so it was already landing in the wildcard before this plan existed.
`code=true` gates the `tests` job, which runs the entire `tests/` directory
in one `pytest tests/ ...` invocation (`:262`) — no per-path selection, so
`tests/test_demo_example.py` (Phase 1) was already wired in the moment it was
added to `tests/`, with no separate job and no filter edit. Placing the test
under top-level `tests/` rather than a dedicated `examples`-scoped location
is what makes this true; a differently-organized test would have needed the
filter change the original plan text describes.

### Changes

- None. See finding above. No new required check is introduced (no new job),
  so the `:8-22` unmergeable-docs-PR hazard the plan flagged does not apply
  here — that hazard is about a *new* check with no path to report success on
  a skipped run, and nothing new is being added.

### New tests

- No new test files — this phase would have wired Phase 1's tests into CI,
  but they were already wired the moment they landed under `tests/`.

### Verification

- [x] Traced statically (see finding above): a change under `examples/**`
      does not match any of the filter's specific `case` patterns, so it
      falls through to the wildcard and sets `code=true`, which runs the
      full `tests/` suite including `test_demo_example.py`.
- [x] A change under `docs/**` (or a bare `*.rst`) matches the `docs/*|*.rst
      |conf.py` branch, setting `docs=true` only — `code` stays whatever it
      already was, so a docs-only PR does not additionally gate on the demo
      tests, and no new required check exists to leave it unmergeable.
- [ ] Not exercised live: an actual PR touching only `examples/demo/`
      observed triggering the tests job, and a deliberately broken
      `examples/demo/application.py` observed failing CI. The static trace
      above is standing in for these; recommend a maintainer watch the first
      real PR against this change to confirm the trace holds before treating
      this box as checked.
- [x] `make test-all-parallel` passes locally (run in Phase 1 verification:
      3092 passed, 31 skipped, 0 failed).

### Implementation Status: Complete

---

## Phase 3: Wire the example into the documentation

The example is only worth moving if the documentation points at it, and the
discoverability plan has two places that currently make an ambiguous claim.

### Changes

- `README.rst` (the "Example application" bullet, now at `:325-330` — line
  numbers had drifted since the plan was written) — points at
  `examples/demo/` in this repository, states it is version-locked to the
  checked-out release, and describes `actingwebdemo` as the deployment
  pipeline rather than a second copy of the application.
- `AGENTS.md` (the "Building an application WITH ActingWeb" section) — same
  correction.
- `docs/guides/mcp-quickstart.rst` and `docs/guides/p2p-quickstart.rst` — a
  "Where to Go Next"/"Recommendations" pointer to `examples/demo/`. (The
  plan's citation of `mcp-applications.rst:954` as the pattern to mirror did
  not resolve to an actingwebdemo reference at that line when checked — the
  actual existing pattern was in `docs/quickstart/getting-started.rst`,
  addressed below instead.)
- `docs/quickstart/index.rst` — added a "Complete Example" bullet under
  "Next Steps" (the file has no section literally titled "Choose Your Path";
  "Next Steps" is that role here).
- **Not in the original plan text**: `docs/quickstart/getting-started.rst`
  had two more `actingwebdemo` references the plan's background research
  (scoped to `README.rst`/`AGENTS.md` only) missed — including one pointing
  at a dead URL, `http://acting-web-demo.readthedocs.io/`. Same class of
  stale claim this phase exists to fix, in the same docs tree, so fixed
  here rather than left for a future pass: both now point at
  `examples/demo/`.

### New tests

- No unit tests. The `-W` docs build is the gate for RST validity.

### Verification

- [x] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` — build succeeded, 0 errors
- [x] `grep -rn "actingwebdemo" README.rst AGENTS.md docs/` — widened past the
      plan's original scope (see finding above); the only remaining mentions
      correctly describe `actingwebdemo` as the deployment pipeline, none
      leave the tracked version ambiguous
- [x] Manual: read each new pointer in context; each lands on a passage that
      answers the question it promised (a complete, version-locked worked
      example)

### Implementation Status: Complete

---

## PR #137 review cycle (Phases 1-3, before merge)

Phases 1-3 landed as commits on `consolidate-demo-app`
([PR #137](https://github.com/actingweb/actingweb/pull/137)). CI's automated
Codex review flagged three issues in the moved demo code — all pre-existing
bugs inherited from `actingwebdemo`, not introduced by the move:

1. **`search` (a method hook) had `@mcp_tool` attached, but MCP tools are
   discovered from action hooks only** (`actingweb/handlers/mcp.py`) — so
   despite `/health` advertising `"mcp_tools": ["search"]`, no MCP client
   could ever see or call it. First fix attempt moved `search` to an action
   hook so MCP discovery would work. **Reverted after clarifying with the
   user**: `examples/demo/` is meant to be a pure ActingWeb protocol
   example, not an MCP one (`examples/mcp_quickstart.py` already covers
   MCP), and methods vs. actions are distinct spec primitives — a read-only
   search stays a method regardless of MCP wiring. Final fix: dropped
   `@mcp_tool` entirely, reverted `search` to `@app.method_hook`, and added
   an explicit `.with_mcp(enable=False)` — `ActingWebApp` enables MCP by
   default, so merely removing the earlier `.with_mcp(enable=True))` call
   left it silently still on (confirmed via `aw_app.get_config().mcp`
   before and after). Also removed the now-purposeless
   `AccessControlConfig`/`mcp_client` trust-type block and `/health`'s
   `mcp_enabled`/`mcp_tools` fields, and corrected every doc/README/
   CHANGELOG claim describing this demo as an MCP example.
2. **`devtest` was unconditionally enabled** — this is the code behind
   `demo.actingweb.io`; `CLAUDE.md` states `with_devtest(enable=False)`
   MUST be False in production. Fixed: gated behind `ENABLE_DEVTEST`
   (default false).
3. **The wildcard `"*"` property hook could not actually protect
   `auth_token`/`created_at`/`actor_type`** — it tried to identify them via
   `path[0]`, but `HookRegistry.execute_property_hooks` only ever passes
   the nested-subkey remainder as `path`, never the top-level property
   name, so the guard silently never fired for ordinary top-level access.
   Fixed: registered each as an exact-name property hook (the pattern
   already used for `email`), which doesn't need `path` to know what it's
   guarding. Removed the now-dead `PROP_HIDE`/`PROP_PROTECT` constants and
   the wildcard hook's broken protection logic.

Also fixed while addressing review feedback: `hmac.compare_digest` instead
of `==`/`!=` for the two secret comparisons (`/nuke`'s `NUKE_SECRET`,
`email_verify`'s token check), a `@pytest.mark.slow` on the wheel-build
test, and a CI-only failure in that same test — `poetry build --output
<dir>` fails outright under Poetry 1.7.0 (CI's pinned version), which has
no `--output`/`-o` flag at all (confirmed by installing 1.7.0 locally and
reading `poetry build --help`); fixed by building to the repo's own
`dist/` and locating the wheel by its exact, deterministic filename.

**Safety note**: while investigating the Poetry 1.7.0 issue, an ad hoc
verification command (`importlib.util.spec_from_file_location` loading
`application.py` directly) was run without setting `AWS_DB_HOST` and made
a second live, read-only DynamoDB scan against this machine's real default
AWS account — the same class of incident recorded under Phase 1, despite
having flagged it there. No writes occurred. Reinforces: anything that
constructs this app outside of pytest must set `AWS_DB_HOST` explicitly,
every time, with no exceptions for "just checking something quickly."

All fixes verified: full test suite green on both DynamoDB and PostgreSQL
backends in CI, docs build clean, `poetry run pytest tests/ -m "not
benchmark" ...` green locally (3095 passed, 31 skipped, 0 failed).

---

## Phase 4: `actingwebdemo` becomes the thin wrapper

Work in the `actingwebdemo` repository, not this one. Listed here because it is
the other half of the decision and would otherwise go missing.

### Changes (in `actingwebdemo`)

- Add `actingweb` as a **git submodule**, pinned to the release tag matching the
  dependency pin.

  **Name the trade before implementing.** Git cannot check out a single
  subdirectory of a submodule, so `actingwebdemo` carries the *entire* `actingweb`
  repository — `tests/`, `docs/`, and `thoughts/` (megabytes of plans) — purely to
  reach `examples/demo/`. Meanwhile `actingweb` itself is *also* installed from
  PyPI as a dependency, so the library is present twice in different forms. That
  is ugly, and it is the cost of making version correspondence structural rather
  than documented. It is checkout weight only, not deploy weight —
  `package.patterns` keeps it out of the Lambda artifact.

  If that reads badly on reflection, the alternative rejected above — a sync
  script plus a CI check asserting the vendored copy equals the pinned tag — trades
  the weight for a check that can be skipped. Decide before Phase 4 starts; do not
  discover this mid-implementation.
- Delete `application.py` and `shared_hooks/`; point `serverless.yml`'s
  `custom.wsgi.app` at the submodule's `examples/demo/application.py`.
- `pyproject.toml:18` — replace `actingweb = { version = ">=3.9.0" }` with an
  exact pin matching the submodule tag. The floating lower bound is the specific
  defect the research identified; replacing it with another floating bound would
  waste the move.
- `serverless.yml` `package.patterns` — include the submodule path and exclude
  everything under it that is not the example (`tests/`, `docs/`, `thoughts/`,
  `actingweb/` is installed from PyPI, not vendored).
- `README.rst` and `CLAUDE.md` — document the submodule workflow: how to update
  the pin, and that application changes are made in the `actingweb` repository.
- `AGENTS.md` (new, in `actingwebdemo`) — the demo has none. Copy the pattern from
  `actingweb_mcp/AGENTS.md`: a ~40-line pure pointer to `CLAUDE.md`. Verified
  during planning that this pattern does not drift — `actingweb_mcp/AGENTS.md` has
  been correct since 2026-05-29 precisely because it delegates.
- `pyproject.toml:34` — `"Repository"` declares
  `https://github.com/gregertw/actingwebdemo` while the library's `README.rst:303`
  sends readers to `https://github.com/actingweb/actingwebdemo`. Reconcile to the
  org URL.
- `.github/workflows/` — add `submodules: recursive` to any checkout that needs
  the example.

### New tests

- Not applicable — `actingwebdemo` has no test suite. The verification is a
  successful deploy to a non-production stage.

### Verification

- [x] `git submodule update --init --recursive` produces the example at
      `vendor/actingweb/examples/demo/` — `.gitmodules` in `actingwebdemo`,
      submodule status `0271d68 (v3.14.1)`
- [x] Packaging keeps the library repo out of the artifact:
      `serverless.yml` `package.patterns` excludes `vendor/actingweb/**` and
      re-includes only `vendor/actingweb/examples/demo/**` (minus
      `__pycache__`). Checked by reading the config; the artifact itself was
      not opened
- [x] Deploys succeed — the `Deploy to AWS Lambda` workflow in `actingwebdemo`
      is green on 2026-08-25 (#27) and 2026-08-27 (#28); there is no separate
      dev stage, the workflow deploys production from `master`
- [x] The deployed library version is structural, not a floating resolve:
      `pyproject.toml` installs `actingweb` from `path = "vendor/actingweb"`,
      so the version is whatever the submodule is at (3.14.x)

### Implementation Status: Complete — in `actingwebdemo`, 2026-08-25 to 08-27

Landed as `actingwebdemo` PRs #21–#28 (`bf51452` … `833745c`). **Closed on
2026-09-02** during the todo review, after the fact — the work had landed a week
earlier without this plan being updated, which is exactly the failure mode
`thoughts/README.md` warns about.

**What landed differently from the plan above**, so nobody re-derives it:

- **The library is installed from the submodule, not from PyPI.**
  `pyproject.toml:30` is `actingweb = { path = "vendor/actingweb", develop =
  false, extras = ["flask"] }`; the `>=3.9.0` line is commented out beneath it.
  The plan's "present twice in different forms" wart therefore does not exist
  — there is one copy — but the deploy workflow gates on the vendored version
  being **installable from PyPI** (or TestPyPI, by dispatch input), so an
  unreleased or typo'd version fails before packaging.
- **The submodule tracks `master` as a shallow snapshot**
  (`branch = master`, `shallow = true`), currently at the v3.14.1 commit,
  rather than being pinned to a release tag. The PyPI gate above is what makes
  that safe: the snapshot can only deploy if its version was released.
- **A deploy workflow was added after all** (`c388d33`), with a least-privilege
  IAM policy under `infra/` (`46164d5`) and the `profile: default` laptop
  dependency removed (`53edd47`). "What We're NOT Doing" declined this for the
  *library* repository on credential grounds; the demo repository does not
  publish to PyPI, which is the distinction the "Follow-up" section anticipated.
- **The Elastic Beanstalk configuration was removed** (`fd07be7`), closing the
  "Follow-up" item that asked whether it was dead.
- **No `AGENTS.md`** was added to `actingwebdemo`. Its `CLAUDE.md` and
  `README.md` were rewritten (`5f297bc`) for the submodule workflow.
- `pyproject.toml`'s `Repository` URL was reconciled to the org URL as planned.

---

## Phase 5: Bring `demo.actingweb.io` current

The live site runs 3.9.0-era code. This is where seven months of API change
actually surfaces, which is why it is last: everything before it is structural,
and this phase is the one that can genuinely break.

### Changes (in `actingwebdemo` and `examples/demo/`)

- Resolve any API drift between the 3.9.0-era demo code and 3.14.0. Consult the
  migration guides for every version crossed — `docs/migration/v3.10.rst`,
  `v3.11.rst`, `v3.13.rst`, `v3.14.rst` — and the prior consumer-friction report
  at `thoughts/research/2026-07-25-v3.13.0rc1-consumer-feedback.md`, which is a
  first-hand record of exactly this upgrade path.
- **Known drift, found during the 2026-08-22 research recovery**: the demo
  registers `@app.subscription_hook` at
  `shared_hooks/protocol/subscription_hooks.py:28`, and that decorator appears to
  be **dead API** — `execute_subscription_hooks` has zero call sites in
  `actingweb/`. If Phase 0 of
  `thoughts/plans/2026-08-22-ai-agent-discoverability.md` confirms it is dead,
  the live demo's subscription handling has not been running, which would make
  this the first phase to check rather than the last. Resolve that question
  before scheduling this phase.
- Fix whatever the dev-stage deploy surfaces.
- Deploy to production only after the dev stage is verified.

### New tests

- Any drift found here should produce a regression test in this repository's
  suite, not just a fix in the demo. A break that reached a consumer is evidence
  of a gap in library coverage.

### Verification

- [x] The deploy exercises the app — `actingwebdemo` #25 (`b77abff`) fixed
      Lambda 500s from a dependency-less package, #27 (`1166d78`) fixed a
      Google OAuth2 crash and `/nuke`'s `BatchWriteItem` gap. Both were found
      by deploying, which is the verification this phase asked for. There is
      no dev stage; see Phase 4
- [x] Regression tests in this repository — the drift that was found was in
      the *demo* (its OAuth handling and nuke endpoint), not in the library's
      API, so no library regression test was owed
- [x] Production deploy succeeds — `Deploy to AWS Lambda` green on 2026-08-27
- [x] `curl -s -o /dev/null -w "%{http_code}" https://demo.actingweb.io/`
      returns `200` (checked 2026-09-02) and the deployed library is the
      vendored 3.14.x, per Phase 4
- [ ] **Not verified by anyone recording it here:** one full OAuth login
      against the live site. #27's OAuth fix and #28's re-enabling of devtest
      on the live site imply it was exercised, but no record says so. Owed
      work does not live in a `done` plan, so it is filed as
      `thoughts/todo/demo-live-oauth-login-unverified.md` (INDEX row 26);
      tick this box when that todo is deleted

### Implementation Status: Complete — in `actingwebdemo`, 2026-08-25 to 08-27

See Phase 4's status note. The dead-`subscription_hook` question this phase
flagged was resolved by `thoughts/plans/2026-08-22-ai-agent-discoverability.md`
Phase 0 before Phase 5 ran.

---

## Follow-up (not phases of this plan)

- **Serverless Framework v3 → v4, or a move off Serverless.** Core 3.40.0 is out
  of support. v4 requires a license key; SAM, CDK and Terraform are the
  alternatives. Owed by `actingwebdemo` regardless of this plan. Should become a
  `thoughts/todo/` entry when this plan is agreed.
- **Whether the Elastic Beanstalk configuration is dead.** `.ebextensions/`,
  `.elasticbeanstalk/` and `Dockerrun.aws.json` appear unused; confirm and remove
  if so.
- **Automating deployment.** Currently manual from a laptop. Automating it raises
  the same credential questions this plan declined to answer for the library
  repository, but in a repository where the answer may be different — the demo
  repo does not publish to PyPI.

## Evaluation Notes

### Architecture

- The move is unusually clean because the demo already has the right shape:
  `register_all_shared_hooks(app)` is a single entry point and every hook module
  is a plain function over the app. The only structural wart is the
  `sys.path.insert` at `application.py:26`, which Phase 1 removes rather than
  carries.
- **The submodule is doing real work, not ceremony.** A copy/sync script would
  reintroduce exactly the drift this plan exists to remove; a submodule pinned to
  a tag makes the version correspondence checkable by `git`.
- `examples/` is created by the discoverability plan's Phase 2 and extended here.
  The dependency is noted under "Prerequisite" so the two plans do not both create
  it.

### Security

- **The central finding is the reason half this plan does not exist.** Moving
  deployment into a repository that publishes to PyPI on tag would let one
  compromise yield both a malicious wheel and a live OAuth-configured service.
  Declined.
- Phase 1 carries a credential-leak risk that a code move always carries: the
  demo repo has an untracked `.env` with a real `OAUTH_CLIENT_SECRET` and
  `NUKE_SECRET`. The move must take `.env.example` with placeholders and never the
  `.env`. Phase 1's verification includes an explicit secret grep, and `.gitignore`
  is extended before the first commit, not after.
- The `NUKE_SECRET` gates a `/nuke` test-cleanup endpoint. If `examples/demo/`
  documents that endpoint, it must state plainly that it destroys data and belongs
  to a demo deployment, not to production application code.

### Scalability

- Thin. One point: Phase 4's `serverless.yml` `package.patterns` must exclude the
  library repository's `tests/`, `docs/` and `thoughts/` from the submodule, or
  the Lambda artifact grows by the whole repository. The existing `slimPatterns`
  (`serverless.yml:38-47`) already exclude `**/tests/**` and `**/docs/**` for
  dependencies; the submodule needs the equivalent at the package level.

### Usability

- **Phase 5 is deliberately last and deliberately separate.** Everything before it
  is structural and reversible; the version jump from 3.9.0 to 3.14.0 is the part
  that can genuinely break, and it should not be able to block the code move.
- The `>=3.9.0` floating pin is the defect an agent actually hits — it cannot tell
  which API era the reference application demonstrates. Phase 4 replaces it with
  an exact pin, and Phase 3 makes the documentation state the version. Fixing
  either alone leaves the ambiguity.
- Any API drift Phase 5 surfaces is evidence about the *library*, not just the
  demo: a break that reached a consumer is a gap in coverage. Phase 5 requires
  regression tests land here, not only fixes there.
