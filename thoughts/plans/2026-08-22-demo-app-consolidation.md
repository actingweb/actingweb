---
status: proposed
---

# Implementation Plan: Consolidate the demo app into the library repository

**Date:** 2026-08-22
**Research:** thoughts/research/2026-08-22-ai-agent-discoverability.md
**Related plan:** thoughts/plans/2026-08-22-ai-agent-discoverability.md
**Branch:** master

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
- `examples/demo/application.py` — **remove the `sys.path.insert` hack** at
  `:26` and import `shared_hooks` as a proper relative package. The hack exists
  only because the demo repo has no package structure; it should not survive the
  move into a repository that does.
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
  explicitly.

### New tests

- An import smoke test asserting `examples/demo/application.py` imports and its
  `ActingWebApp` builds without network or database access. This is the test that
  makes the example version-locked in practice rather than in principle.
- A test asserting `register_all_shared_hooks(app)` registers every hook category
  the demo claims (`subscription`, `trust`, `lifecycle`, `method`, `action`,
  `callback`, `property`, `ui`) — the `shared_hooks/__init__.py` docstring makes
  eight promises and this checks all eight.
- A test asserting `examples/` is **not** present in the built wheel, guarding the
  repo-only decision against a future `include` edit.

### Verification

- [ ] `poetry run pyright actingweb tests examples` — 0 errors
- [ ] `poetry run ruff check actingweb tests examples` passes
- [ ] `poetry run ruff format --check actingweb tests examples` passes
- [ ] `poetry run pytest tests/ -k demo_example -v` passes
- [ ] `poetry build && poetry run python -c "import zipfile,glob; w=glob.glob('dist/*.whl')[-1]; assert not [n for n in zipfile.ZipFile(w).namelist() if n.startswith('examples/')], 'examples leaked into wheel'"`
- [ ] `grep -c "sys.path.insert" examples/demo/application.py` returns 0
- [ ] `grep -rniE "client_secret *= *[\"'][^\"']+|AKIA[0-9A-Z]{16}" examples/` finds
      nothing — no credential rides along with the move
- [ ] Manual: run the example locally against DynamoDB Local
      (`docker compose -f docker-compose.test.yml up dynamodb-test`) and confirm
      actor creation and the `/www` UI respond

### Implementation Status: Not Started

---

## Phase 2: CI tests the example against the library

The point of the move is that the demo cannot silently rot against the library.
That only holds if CI enforces it.

### Changes

- `.github/workflows/tests.yml` — extend the `changes` filter
  (`:73-111`) so edits under `examples/**` set the appropriate output. Follow the
  existing pattern: the filter already reasons carefully about which changes
  warrant which jobs, and the comments at `:94-105` explain why.
- `.github/workflows/tests.yml` — run the Phase 1 example tests in the existing
  test job rather than adding a new job. A separate job costs a matrix slot for
  three assertions.
- `.github/workflows/tests.yml:20-30` — if a new required check is introduced,
  update the `changes` job outputs accordingly. The comments at `:8-22` warn that
  a docs-only PR waits forever on a check that is never created; do not
  reintroduce that failure mode.

### New tests

- No new test files — this phase wires Phase 1's tests into CI. The verification
  is that CI actually runs them.

### Verification

- [ ] A PR touching only `examples/demo/` triggers the example tests
- [ ] A PR touching only `docs/` does **not** trigger them, and is still mergeable
      — re-check the `:8-22` unmergeable-docs-PR hazard explicitly
- [ ] A deliberate breaking edit to `examples/demo/application.py` (e.g. calling a
      renamed method) fails CI; revert after confirming
- [ ] `make test-all-parallel` passes locally

### Implementation Status: Not Started

---

## Phase 3: Wire the example into the documentation

The example is only worth moving if the documentation points at it, and the
discoverability plan has two places that currently make an ambiguous claim.

### Changes

- `README.rst:303-304` — the "Example application" bullet. State the ActingWeb
  version the demo tracks, now that it is knowable, and note that the application
  code lives in `examples/demo/` in this repository while `actingwebdemo` is the
  deployment wrapper.
- `AGENTS.md` — the "Building an application WITH ActingWeb" section from the
  discoverability plan's Phase 6: same correction. That phase explicitly deferred
  the version claim to this plan.
- `docs/guides/mcp-quickstart.rst` and `docs/guides/p2p-quickstart.rst` — a
  "see a complete application" pointer to `examples/demo/`, mirroring the way
  `mcp-applications.rst:954` offers a complete worked example.
- `docs/quickstart/index.rst` — add the example to the routing, so the
  "Choose Your Path" flow at `index.rst:8-21` can reach it.

### New tests

- No unit tests. The `-W` docs build is the gate for RST validity.

### Verification

- [ ] `poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html` passes
- [ ] `grep -rn "actingwebdemo" README.rst AGENTS.md` — no remaining claim that
      leaves the tracked version ambiguous
- [ ] Manual: follow each new pointer and confirm it lands somewhere that answers
      the question it promised

### Implementation Status: Not Started

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

- [ ] `git submodule update --init --recursive` produces the example at the
      expected path
- [ ] `sls package --stage dev` succeeds and the resulting artifact contains
      `examples/demo/` but **not** the library's `tests/`, `docs/`, or `thoughts/`
- [ ] `sls deploy --stage dev` succeeds; the dev-stage URL serves the demo
- [ ] Manual: confirm the deployed dev stage runs the pinned library version, not
      a floating resolve — check the version reported by the app

### Implementation Status: Not Started

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

- [ ] `sls deploy --stage dev` succeeds and the dev URL exercises actor creation,
      OAuth login, an MCP tool call, and a trust + subscription round trip
- [ ] `make test-all-parallel` passes in this repository with any new regression
      tests added
- [ ] `sls deploy` (prod) succeeds
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://demo.actingweb.io/` returns
      200 and the deployed version reports 3.14.0 or later
- [ ] Manual: complete one full OAuth login against the live site

### Implementation Status: Not Started

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
