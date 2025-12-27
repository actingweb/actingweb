# AGENTS.md

Quick reference for AI agents working with this repository.

## Project

**ActingWeb** - Python library for distributed micro-services with the ActingWeb REST protocol.

## Structure

```text
actingweb/          # Source code
├── interface/      # Modern API (ActingWebApp, ActorInterface)
├── handlers/       # HTTP handlers
├── db_dynamodb/    # Database backend
tests/              # pytest tests (474+)
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

# Test
make test-integration                 # Full test suite with DynamoDB
poetry run pytest tests/ -v           # Tests only (DynamoDB must be running)

# Build
poetry build
```

## Quality Requirements

- **Zero errors, zero warnings** on pyright and ruff
- **Type hints required** on all functions
- **All tests passing** before merge

## Pre-commit Checklist

```bash
poetry run pyright actingweb tests    # → 0 errors, 0 warnings
poetry run ruff check actingweb tests # → All checks passed
poetry run pytest tests/              # → All tests passing
```

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
