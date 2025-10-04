# Repository Guidelines

Use CLAUDE.md to understand details of the repo.

## Project Structure & Module Organization

- Source: `actingweb/` (core library modules, e.g., `actor.py`, `auth.py`, `handlers/`, `interface/`).
- Tests: `tests/` (pytest suite; coverage targets configured in `pyproject.toml`).
- Docs: Sphinx config at repo root (`conf.py`, `index.rst`), content in `docs/`.
- Packaging/Config: `pyproject.toml` (Poetry), `README.rst`, `CHANGELOG.rst`.

## Build, Test, and Development Commands

- Install (with dev extras): `poetry install` (use `-E all` to include optional extras).
- Run tests + coverage: `poetry run pytest` (fails under 80% coverage; HTML at `htmlcov/`).
- Lint (Ruff): `poetry run ruff check .`
- Format (Black): `poetry run black .`
- Type check (mypy): `poetry run mypy actingweb`
- Build package: `poetry build`
- Build docs: `make html` (Sphinx; output in `_build/html`).

## Coding Style & Naming Conventions

- Python 3.11+, 4-space indentation, line length 88.
- Naming: modules/functions `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE_CASE`.
- Imports: keep tidy; Ruff enforces style; Black handles formatting.
- Type hints required in new/modified public functions; keep `py.typed` intact.

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
  - Pass CI: pytest, mypy, Ruff, Black, and package build.

## Security & Configuration Tips

- Do not commit secrets or AWS credentials. Use environment variables for local dev.
- Optional extras: `-E flask`, `-E fastapi`, `-E mcp` (or `-E all`) when working with those integrations.
- Initialize any required singletons at app startup if embedding the library (see docs under `docs/`).
