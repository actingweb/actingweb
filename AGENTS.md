# AGENTS.md

Quick reference for AI agents working with this repository.

## Project

**ActingWeb** - Python library for distributed micro-services with the ActingWeb REST protocol.

## Structure

```text
actingweb/          # Source code
├── interface/      # Modern API (ActingWebApp, ActorInterface)
├── handlers/       # HTTP handlers
├── db/dynamodb/    # Database backend
tests/              # pytest tests (900+)
docs/               # Sphinx documentation
```

## Commands

```bash
# Setup
poetry install

# Quality (run before commits)
poetry run pyright actingweb tests    # Type check - 0 errors required
poetry run ruff check actingweb tests # Lint - must pass
poetry run ruff format actingweb tests

# Test (Sequential - most reliable)
make test-integration                 # Integration tests (~5 min)
make test-integration-fast            # Skip slow tests (~3 min)

# Test (Parallel - faster, may have isolation issues)
make test-parallel                    # Integration tests (~2 min)
make test-all-parallel                # ALL tests - unit + integration (~4 min)

# Build
poetry build
```

## Quality Requirements

- **Zero errors, zero warnings** on pyright and ruff
- **Type hints required** on all functions
- **All tests passing** before merge

## Pre-commit Checklist

**CRITICAL**: Run ALL tests before committing!

```bash
poetry run pyright actingweb tests    # → 0 errors, 0 warnings
poetry run ruff check actingweb tests # → All checks passed
make test-all-parallel                # → ALL 900+ tests passing
```

### Test Execution Modes

**Sequential (Recommended for CI)**
- `make test-integration` - Most reliable, ~5 min
- Better test isolation, no parallel issues

**Parallel (Recommended for Development)**
- `make test-all-parallel` - Faster, ~4 min
- 2-3x speed improvement
- May have occasional isolation issues (safe to re-run)

**If parallel tests fail**:
1. Re-run with `make test-integration` (sequential mode)
2. If sequential passes → test isolation issue (not a bug)
3. If sequential fails → investigate the actual failure

## Version Updates

Change version in three files:
1. `pyproject.toml`
2. `actingweb/__init__.py`
3. `CHANGELOG.rst`

## Documentation

| Topic | File |
|-------|------|
| Configuration | `docs/quickstart/configuration.rst` |
| Routing & Redirects | `docs/reference/routing-overview.rst` |
| Authentication | `docs/guides/authentication.rst` |
| SPA Mode | `docs/guides/spa-authentication.rst` |
| Web UI | `docs/guides/web-ui.rst` |
| Hooks | `docs/reference/hooks-reference.rst` |
| Testing | `CONTRIBUTING.rst` |

## Key Files

- `CLAUDE.md` - Detailed guidance for Claude Code
- `CONTRIBUTING.rst` - Contribution guidelines
- `docs/` - Full documentation
- `thoughts/shared/` - Development notes, patterns, plans

## Commits

- Imperative mood: "Add feature" not "Added feature"
- Include scope when helpful: "fix(oauth): Handle token refresh"
- Link issues: "Closes #123"
