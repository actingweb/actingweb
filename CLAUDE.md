# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**ActingWeb** is a Python library implementing the ActingWeb REST protocol for distributed micro-services. Each user gets their own "actor" instance with a unique URL, enabling secure bot-to-bot communication and granular data sharing.

## Workflow

This repository uses the workflow and slash commands from
<https://github.com/gregertw/claude> (installed at `~/.claude`; the process is
described in its `README.md` there). The commands read the subsections below
as instructions, not prose. Per-command addenda live in
[`.claude/workflow/<command>.md`](.claude/workflow/README.md).

The chain: `/plan_feature` → `/research_codebase` → `/create_plan` (or
`/update_plan` before work starts) → `/implement_plan` →
`/verify_implementation` → `/iterate_plan`. `/fix_bug` for bugs.
`/changelog` → `/commit` → `/release` to ship. All thinking is checked in
under `thoughts/` alongside the code. Reports from consumer repositories land
in `thoughts/inbound/` and are triaged before anything is filed from them.

### Checks

Two tiers. **Fast** runs after every implementation phase and after each
group of iteration changes. **Full** runs before every commit, during
verification, and before a release. All must pass with **0 errors and 0
warnings**; never commit code that breaks the existing suite. Type hints are
required on all functions.

Fast:

```bash
docker compose -f docker-compose.test.yml up -d dynamodb-test
poetry run ruff check actingweb tests
poetry run ruff format --check actingweb tests
poetry run pyright actingweb tests
poetry run pytest tests/ --ignore=tests/integration --ignore=tests/performance -m "not benchmark" --no-cov -q
```

Full:

```bash
poetry run ruff check actingweb tests
poetry run ruff format --check actingweb tests
poetry run pyright actingweb tests
poetry run python tests/integration/verify_groups.py
make test-all-parallel
DATABASE_BACKEND=postgresql PG_DB_HOST=localhost PG_DB_PORT=5433 PG_DB_NAME=actingweb_test PG_DB_USER=actingweb PG_DB_PASSWORD=testpassword make test-all-parallel
poetry run sphinx-build -W --keep-going -D suppress_warnings="ref.doc,misc.highlighting_failure" -b html . _build/html
```

Preconditions and warnings (the commands follow these as instructions):

- After switching branches or pulling a lock change run
  `poetry install --with dev --extras "all"` first.
- Docker must be running. `docker-compose.test.yml` maps DynamoDB Local to
  `:8001` and PostgreSQL to `:5433`. The unit tests need DynamoDB Local too
  (system-actor bootstrap); without it they fail with "Could not connect to
  the endpoint URL", which is not a code regression. The `make` targets start
  and stop both containers themselves.
- Run one test run at a time. Separate runs, including one in another
  session, share the test server port `5555` and the `test_w0_` database
  prefix and corrupt each other; serialize before trusting a failure.
- Parallel runs (`make test-all-parallel`, `-n auto --dist loadgroup`) are
  2–3x faster but can show isolation flakes. Re-run a failure sequentially
  (`make test-integration`, or the failing file alone) before treating it as
  real.
- Inside the Claude Code sandbox add `-p no:rerunfailures` to a direct
  `pytest` call: the rerun plugin binds a loopback socket the sandbox
  refuses. CI keeps `--reruns 2`.
- Benchmarks (`-m benchmark`, `tests/performance/`) never run in parallel and
  are excluded from CI; run them alone when a change touches list storage.
- A PostgreSQL failure that DynamoDB does not show is a real backend
  difference, not a flake; CI requires both backends green.
- Docs: `-W` turns warnings into errors. Read the Docs builds the same tree
  with `fail_on_warning: false`, so CI is the stricter gate.

### App

- Start for checks: none. The integration tests start their own server on
  `:5555` and the database containers.
- Start for browser QA: the reference app in `examples/demo/`. Start
  DynamoDB Local (`docker compose -f docker-compose.test.yml up -d
  dynamodb-test`), copy `examples/demo/.env.example` to `examples/demo/.env`
  with a real OAuth2 client id and secret, then `poetry install --extras
  flask && poetry run python examples/demo/application.py`
  (`http://localhost:5000`). Login goes through the real provider, so browser
  QA can only cover what an already-logged-in session reaches.
- Allowed hosts for browser QA: `localhost`, `127.0.0.1`
- Seed or reset data: none. (`GET /nuke?secret=` deletes every actor and is
  only armed when `NUKE_SECRET` is set; leave it unset.)
- Stop: `Ctrl-C`, then `docker compose -f docker-compose.test.yml down -v`

### Test account

- none. The demo app logs in through a real OAuth2 provider; the browser
  agent never types a real account's credentials.

### Commits

- Attribution lines (Co-Authored-By, session links added by the harness): keep
- Never stage: `.env*`, `examples/demo/.env`, `coverage.xml`, `htmlcov/`,
  `dist/`, `_build/` (all gitignored; do not force-add them)
- When `pyproject.toml` changes, regenerate `docs/requirements.txt`
  (`poetry export --with docs --without-hashes -o docs/requirements.txt`) in
  the same commit; `scripts/install-git-hooks.sh` installs a pre-commit hook
  that does it.
- Branch names: `fix/<version>-<slug>` for a patch, `release/<version>-<slug>`
  for a minor or a release PR, `docs/<slug>` for docs-only work. `master` is
  protected: every change arrives through a PR.

### CI policy

- Opening a PR: triggers Tests (Python 3.11 × dynamodb, postgresql),
  type-check (pyright, ruff check, ruff format) and Documentation Build, plus
  a Claude code review on open only. All four check contexts are required on
  `master`.
- Pushing to an open PR: re-runs the test workflows (`pull_request`
  synchronize); the Claude review does not re-run.
- Re-triggering CI: push a commit. Never `gh workflow run` the test workflow;
  the release workflow's `workflow_dispatch` is the user's only.
- A docs-only PR skips the heavy matrix through the `changes` job's
  step-level gating; never move those filters up to `on:`, the required
  per-backend contexts would then never be created and the PR could not
  merge (the workflow file says why).
- Local pre-PR gate: none beyond the Full tier.

### Tools

- Second opinion for plans: use codex
- Second opinion for diffs: use codex
- Scope lock: use self-check
- Diagrams: use mermaid-fence

Browser QA auto-detects (`bash ~/.claude/bin/detect-tools`).

### Changelog

- File: `CHANGELOG.rst`, top section `Unreleased` (dashes underline), then
  `vX.Y.Z: Month D, YYYY` sections
- Categories, in the order they appear when present: `SECURITY`, `REMOVED`,
  `CHANGED`, `ADDED`, `FIXED` (tilde underline)
- Entry style: multi-line user-facing RST prose. A bold first sentence names
  the symptom, then the cause, then the new behaviour and what a consumer
  should check. Every consumer-visible shift gets a bold **Behavior change:**
  sentence; a wire-shape or API change gets a **Breaking:** lead under
  `CHANGED`. Exactly-true guarantee wording beats shorter wording.
- Sidecar files to keep in sync: none. A minor gets `docs/migration/vX.Y.rst`
  plus its `docs/migration/index.rst` row; a patch never touches
  `docs/migration/`, the changelog carries its behaviour notes.
- Contributors add the entry under `Unreleased` in the same PR; no version
  bump outside a release PR.

### Release

Releases are triggered by git tags. **The version bump and changelog rename
go in the release PR itself**: no separate release PR, no bump on `master`
after merging. Tag the merge commit.

- Version files: `pyproject.toml` (`version = "X.Y.Z"`) and
  `actingweb/__init__.py` (`__version__ = "X.Y.Z"`), PEP 440; both must match
  the tag exactly. The tag workflow validates this.
- Patch vs minor: a patch (`3.14.x`) when no route, hook name, kwarg,
  response field, public signature or config option changes (additive
  keyword-only parameters with defaults are fine); a minor otherwise, with a
  migration guide.
- Changelog promotion: rename `Unreleased` to `vX.Y.Z: Month D, YYYY` (or
  `vX.Y.ZrcN: ...`), add a new empty `Unreleased` above it; a minor's entry
  opens with a `.. note::` pointing at its migration guide.
- Branch and PR: `release/<version>-<slug>` (or the feature's `fix/` branch)
  with the bump, commit `Release vX.Y.Z` (or `Pre-release vX.Y.ZrcN`), PR to
  `master`, CI green on both backends, merge; then on `master`: `git pull`,
  `git tag vX.Y.Z` on the merge commit, `git push origin vX.Y.Z`. Tags are
  pushed by name. Tags on any commit not on `master` fail the release
  workflow.
- Tags: `vX.Y.Z`; extra tags: none
- Pre-releases (`X.Y.ZaN`, `X.Y.ZbN`, `X.Y.ZrcN`, `X.Y.Z.devN`) publish to
  **TestPyPI** and a GitHub Release marked pre-release; a stable version
  publishes to PyPI. Install a pre-release with
  `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ actingweb==X.Y.ZrcN`.
- Publish: nothing beyond the tag (`.github/workflows/publish-to-pypi.yml`
  reacts to `v*`). Repository secrets `POETRY_PYPI_TOKEN_PYPI` and
  `POETRY_TESTPYPI_TOKEN` must exist.
- Pre-PR gate for release PRs: skip (a version-only diff was reviewed in its
  feature PRs)
- Runbook: this section; `CONTRIBUTING.rst` repeats the tag restriction.

### Dependencies

- `../actingweb_mcp` (Emm AI) and `../actingwebdemo` consume this library
  pinned by version. A regression reported from a consumer is bisected in a
  git worktree of this repo pointed at by the consumer's path dependency;
  never move this repo's `HEAD` for that. Consumer reports arrive as
  `thoughts/inbound/<slug>.md` and are verified against the tree before
  anything is filed (`thoughts/README.md`, "inbound/").
- `examples/demo/` is the application code behind `demo.actingweb.io`; the
  `actingwebdemo` repository only deploys it. It is imported by tests here,
  so it cannot drift from the library.

### Thoughts

- Layout: [`thoughts/README.md`](thoughts/README.md) is authoritative. Read
  it before adding anything there, and re-read it before recording that work
  is finished. Directories: `features/`, `research/`, `plans/`,
  `verifications/`, `reference/`, `todo/`, `inbound/`. A directory is a
  **kind** of document, never a **status**; a finished plan stays in `plans/`
  with `status: done`, it is never moved.
- `todo/` holds only what is NOT done. When work lands the file is
  **deleted**, not annotated; the plan and the verification are the record.
  Keep `todo/INDEX.md` in step: add a row with the file, remove it with the
  file. Todos are identified by filename, never by a number.
- `inbound/` is an inbox and is normally empty. Triage means **verify**, not
  transcribe: check every claim against the tree, write down what the check
  changed, file what survives (a todo with an `INDEX.md` row, a research
  note, or a plan), carry the attribution across, then delete the report.
- Update a plan's `status:` when its last phase lands, including phases it
  deliberately deferred. Find work in flight with
  `grep -l "^status: active" thoughts/plans/*.md`.
- Durable **product** documentation released publicly goes in `docs/` (see
  the index below), not in `thoughts/reference/`. Check both before starting
  significant work.

## Documentation

Comprehensive documentation is in `docs/`. Key references:

| Topic | Location |
| ------- | ---------- |
| **Getting Started** | `docs/quickstart/` |
| **Configuration** | `docs/quickstart/configuration.rst` |
| **Authentication & OAuth2** | `docs/guides/authentication.rst`, `docs/guides/spa-authentication.rst` |
| **Routing & Redirects** | `docs/reference/routing-overview.rst` |
| **Web UI & SPA Mode** | `docs/guides/web-ui.rst` |
| **Hooks Reference** | `docs/reference/hooks-reference.rst` |
| **API Reference** | `docs/reference/` |
| **SDK & Developer API** | `docs/sdk/` |
| **Testing Guide** | `CONTRIBUTING.rst`, `docs/contributing/testing.rst` |

## Architecture Overview

```text
actingweb/
├── interface/           # Modern fluent API (ActingWebApp, ActorInterface)
│   ├── app.py          # ActingWebApp - main configuration entry point
│   ├── actor_interface.py  # ActorInterface - actor operations
│   ├── hook_registry.py    # Decorator-based event handling
│   └── integrations/   # Flask & FastAPI integrations
├── handlers/           # HTTP request handlers
├── db/                 # Database backends (pluggable)
│   ├── dynamodb/      # DynamoDB backend (PynamoDB models)
│   ├── postgresql/    # PostgreSQL backend (psycopg3 + Alembic)
│   └── protocols.py   # Database interface protocols
├── actor.py           # Core actor implementation
├── config.py          # Configuration management
├── oauth2.py          # OAuth2 authentication
└── auth.py            # Authentication logic
```

**Key Concepts:**
- **Actor**: User instance with unique URL (`/{actor_id}`)
- **Properties**: Key-value storage per actor
- **Trust**: Relationships between actors with permissions
- **Subscriptions**: Event notifications between actors
- **Hooks**: Application callbacks for lifecycle events

See `docs/sdk/handler-architecture.rst` for detailed architecture.

## Database Backends

ActingWeb supports two database backends:

### DynamoDB (Default)
- **Production-ready**: AWS-managed NoSQL database
- **Auto-scaling**: Automatic read/write capacity management
- **Requirements**: DynamoDB Local for testing (`docker compose -f docker-compose.test.yml up dynamodb-test`)
- **Installation**: No extra dependencies needed

### PostgreSQL
- **Production-ready**: Open-source relational database
- **Schema management**: Alembic migrations
- **Requirements**: PostgreSQL 12+ server
- **Installation**: `poetry install --extras postgresql`

### PostgreSQL Setup

**Installation**:
```bash
poetry install --extras postgresql
```

**Environment Configuration**:
```bash
DATABASE_BACKEND=postgresql    # Select PostgreSQL backend
PG_DB_HOST=localhost          # Database host
PG_DB_PORT=5432               # Database port (5433 for test)
PG_DB_NAME=actingweb          # Database name
PG_DB_USER=actingweb          # Database user
PG_DB_PASSWORD=yourpassword   # Database password
PG_DB_PREFIX=                 # Optional: prefix for schema names (used in tests)
PG_DB_SCHEMA=public           # Schema name (default: public)
```

**Run Migrations**:
```bash
cd actingweb/db/postgresql/migrations
alembic upgrade head
```

**Testing with PostgreSQL**:
```bash
# Start PostgreSQL test container
docker compose -f docker-compose.test.yml up postgres-test -d

# Run tests with PostgreSQL backend
DATABASE_BACKEND=postgresql \
PG_DB_HOST=localhost \
PG_DB_PORT=5433 \
PG_DB_NAME=actingweb_test \
PG_DB_USER=actingweb \
PG_DB_PASSWORD=testpassword \
make test-integration

# Stop container when done
docker compose -f docker-compose.test.yml down
```

**Migration Management**:
```bash
cd actingweb/db/postgresql/migrations

# Create a new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show current migration version
alembic current
```

## Critical Configuration

```python
from actingweb.interface import ActingWebApp

app = (
    ActingWebApp(
        aw_type="urn:actingweb:example.com:myapp",
        database="dynamodb",    # or "postgresql" - can also use DATABASE_BACKEND env var
        fqdn="myapp.example.com",
        proto="https://"
    )
    .with_oauth(client_id="...", client_secret="...")
    .with_web_ui(enable=True)   # False for SPAs
    .with_devtest(enable=False) # MUST be False in production
    .with_mcp(enable=True)
    .with_sync_callbacks()      # Recommended for Lambda/serverless
)
```

**Database Backend Selection**:
- Set `database="postgresql"` in ActingWebApp, OR
- Set `DATABASE_BACKEND=postgresql` environment variable (takes precedence)
- Default is `"dynamodb"` if not specified

**Lambda/Serverless Deployments**:
- Use `.with_sync_callbacks()` to ensure subscription callbacks complete before the function freezes
- Async fire-and-forget callbacks may be lost when Lambda functions freeze after returning a response
- See `docs/quickstart/deployment.rst` for details

See `docs/quickstart/configuration.rst` for all options.

## Browser Redirect Behavior

The `with_web_ui()` setting controls browser redirects:

| Scenario | `with_web_ui()` | Redirect |
| ---------- | ----------------- | ---------- |
| Unauthenticated browser → `/<actor_id>` | Any | `/login` |
| Authenticated browser → `/<actor_id>` | `True` | `/<actor_id>/www` |
| Authenticated browser → `/<actor_id>` | `False` | `/<actor_id>/app` |
| After OAuth login | `True` | `/<actor_id>/www` |
| After OAuth login | `False` | `/<actor_id>/app` |

API clients always receive JSON. See `docs/reference/routing-overview.rst`.

## Property Reverse Lookup

ActingWeb supports reverse lookups (find actor by property value) via lookup tables:

```python
app.with_indexed_properties(["oauthId", "email", "externalUserId"])
app.with_legacy_property_index(enable=False)  # Recommended for new deployments
```

**Key Points:**
- **Default**: Lookup table mode disabled (`USE_PROPERTY_LOOKUP_TABLE=false`) for backward compatibility
- **Legacy mode**: Uses DynamoDB GSI (2048-byte limit) or PostgreSQL index
- **Lookup table mode**: No size limits, better performance for indexed properties
- **Migration**: Dual-mode support for gradual transition
- **Cleanup**: Automatic when properties/actors deleted

**Environment Variables:**
```bash
export USE_PROPERTY_LOOKUP_TABLE=true                    # Enable lookup tables
export INDEXED_PROPERTIES=oauthId,email,externalUserId  # Configure indexed properties
```

See `docs/quickstart/configuration.rst` for full migration guide and best practices.

## Logging and Request Correlation

ActingWeb uses hierarchical logging with named loggers (`__name__`) and automatic request correlation.

**Quick setup with correlation**:
```python
from actingweb.logging_config import (
    configure_actingweb_logging,
    enable_request_context_filter
)
import logging

# Configure base logging
configure_actingweb_logging(logging.DEBUG)  # Development
configure_actingweb_logging(logging.WARNING, db_level=logging.ERROR)  # Production

# Enable automatic context injection (recommended)
enable_request_context_filter()
```

**Log format with context**:
```
2024-01-15 10:23:45,123 [a1b2c3d4:actor123:peer456] actingweb.handlers:INFO: Property updated
```
- `a1b2c3d4`: Request ID (last 8 chars)
- `actor123`: Actor handling request
- `peer456`: Peer making request (or `-` if creator/trustee)

**Convenience functions**: `configure_production_logging()`, `configure_development_logging()`, `configure_testing_logging()`

**Request correlation features**:
- Request IDs automatically extracted from `X-Request-ID` header or generated
- Context automatically managed by Flask and FastAPI integrations
- Peer requests include correlation headers for request chain tracing
- Easy grepping: `grep "a1b2c3d4" logs` or `grep ":actor123:" logs`

**Performance-critical loggers** (use WARNING+ in production):
- `actingweb.db.dynamodb`, `actingweb.auth`, `actingweb.handlers.properties`, `actingweb.aw_proxy`

**See also**:
- `actingweb/logging_config.py` module docstrings for detailed configuration
- `docs/guides/logging-and-correlation.rst` for comprehensive guide with grepping patterns

## Security Notes

- `with_devtest(enable=False)` - **MUST** be False in production
- Use HTTPS in production (`proto="https://"`)
- Never commit secrets - use environment variables
- See `docs/reference/security.rst` for full checklist
