# Repository Guidelines

Use CLAUDE.md to understand details of the repo.

## Project Structure & Module Organization

- Source: `actingweb/` (core library modules, e.g., `actor.py`, `auth.py`, `handlers/`, `interface/`).
- Tests: `tests/` (pytest suite; coverage targets configured in `pyproject.toml`).
- Docs: Sphinx config at repo root (`conf.py`, `index.rst`), content in `docs/`.
- Packaging/Config: `pyproject.toml` (Poetry), `README.rst`, `CHANGELOG.rst`.

## Build, Test, and Development Commands

- Install (with dev extras): `poetry install` (use `-E all` to include optional extras).
- Run tests: `poetry run pytest` (474 tests, 100% passing).
- **Type check (Pyright - PRIMARY)**: `poetry run pyright actingweb tests` ✅ **0 errors, 0 warnings**
- **Lint (Ruff)**: `poetry run ruff check actingweb tests` ✅ **All checks passing**
- Format (Ruff): `poetry run ruff format actingweb tests`
- Type check (mypy - legacy): `poetry run mypy actingweb`
- Build package: `poetry build`
- Build docs: `make html` (Sphinx; output in `_build/html`).

**Quality Status:** The codebase maintains **zero errors and zero warnings** for all type checking and linting.

## Coding Style & Naming Conventions

- Python 3.11+, 4-space indentation, line length 88.
- Naming: modules/functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
- Imports: keep tidy; Ruff enforces style and formatting.
- **Type hints REQUIRED**: All new/modified functions must have type annotations.
- **Zero-tolerance for warnings**: All code must pass `pyright` and `ruff` with zero errors/warnings.
- Configuration files: `pyrightconfig.json`, `pyproject.toml` (ruff config), `.vscode/settings.json`.

## Testing Guidelines

- Framework: `pytest` with config in `pyproject.toml`.
- Discover: files `test_*.py` or `*_test.py`, classes `Test*`, functions `test_*`.
- Coverage: minimum 80% (`--cov=actingweb`); add focused unit tests for new logic.
- Avoid external dependencies in unit tests; mock AWS/DynamoDB and network I/O.

## Commit & Pull Request Guidelines

- Commits: imperative mood, concise summary (e.g., "Add OAuth2 token refresh"), include scope when helpful.
- PRs must:
  - Describe changes, motivation, and impact.
  - Link related issues (e.g., `Closes #123`).
  - Include tests and docs updates when applicable.
  - **Pass ALL quality checks with zero errors/warnings**:
    - `poetry run pyright actingweb tests` → 0 errors, 0 warnings
    - `poetry run ruff check actingweb tests` → All checks passing
    - `poetry run pytest` → All tests passing
  - Build package: `poetry build`

**Pre-commit Checklist:**
```bash
poetry run pyright actingweb tests  # Must show: 0 errors, 0 warnings
poetry run ruff check actingweb tests  # Must show: All checks passed!
poetry run pytest tests/  # Must show: 474 passed
```

## Security & Configuration Tips

- Do not commit secrets or AWS credentials. Use environment variables for local dev.
- Optional extras: `-E flask`, `-E fastapi`, `-E mcp` (or `-E all`) when working with those integrations.
- Initialize any required singletons at app startup if embedding the library (see docs under `docs/`).
