Contributing Guide
==================

This guide is for contributors to the ActingWeb Python library. For user and API docs, see the pages under docs/.

Local Setup
===========

- Python 3.11+ and Poetry required.
- Install (with all optional extras):

  .. code-block:: bash

      poetry install -E all

- Useful commands:

  - Tests + coverage: ``poetry run pytest`` (fails <80%; HTML in ``htmlcov/``)
  - Parallel tests: ``make test-parallel`` (3-4x faster using all CPU cores)
  - Lint: ``poetry run ruff check .``
  - Format: ``poetry run black .``
  - Types: ``poetry run mypy actingweb``
  - Docs: ``make html`` (output in ``_build/html``)

Development Workflow
====================

1. Create a feature branch; keep changes focused.
2. Run ruff, black, mypy, and pytest locally; ensure coverage ≥ 80%.
3. Update docs under docs/ for user‑visible behavior; put contributor‑only notes here in CONTRIBUTING.rst.
4. Add CHANGELOG.rst entries (top section for unreleased) when behavior changes.
5. Open a PR with a clear description, motivation, and test coverage.

Coding Standards
================

- Style: Black (line length 88), Ruff for lint, type hints required on public APIs; keep ``py.typed`` intact.
- Naming: modules/functions ``snake_case``, classes ``PascalCase``, constants ``UPPER_SNAKE_CASE``.
- Avoid one‑letter names; prefer explicit, minimal changes aligned with existing patterns.

Devtest Endpoints (Library Testing Aids)
========================================

Devtest endpoints are for validating ActingWeb behavior during development. Never enable in production.

- Enable: ``ActingWebApp(...).with_devtest(True)`` or ``Config(devtest=True)``.
- Paths (all under ``/<actor_id>/devtest``):

  - ``GET/POST/PUT/DELETE /devtest/ping`` → 204 (auth/route sanity).
  - ``/devtest/proxy/...``: exercise peer calls via the loopback trust (``shorttype="myself"``):
    - ``GET /devtest/proxy/properties`` → fetch peer properties.
    - ``PUT /devtest/proxy/properties/<name>`` with JSON → set a property via proxy.
    - ``DELETE /devtest/proxy/properties`` → delete all peer properties.
  - ``/devtest/attribute/...``: inspect/mutate internal Attributes storage:
    - ``GET /devtest/attribute`` → list buckets; ``GET /devtest/attribute/<bucket>`` → list entries.
    - ``POST /devtest/attribute/<bucket>`` with JSON → create bucket entries.
    - ``PUT /devtest/attribute/<bucket>/<key>`` with JSON → set value.
    - ``DELETE /devtest/attribute/<bucket>/<key>`` or ``DELETE /devtest/attribute`` → remove key/buckets.

Running Tests
=============

Sequential Execution
--------------------

Run tests one at a time (traditional approach):

.. code-block:: bash

    # All integration tests
    make test-integration

    # Unit tests only
    poetry run pytest tests/ --ignore=tests/integration

    # Specific test file
    poetry run pytest tests/integration/test_factory.py -v

Parallel Execution (Recommended)
---------------------------------

Run tests in parallel across multiple CPU cores for 3-4x speedup:

.. code-block:: bash

    # All integration tests (auto-detects CPU cores)
    make test-parallel

    # Fast tests only (skips slow tests)
    make test-parallel-fast

    # All tests (unit + integration)
    make test-all-parallel

    # Manual control (4 workers with loadgroup distribution)
    poetry run pytest tests/integration/ -n 4 -v --dist loadgroup

**How Parallel Testing Works:**

- Each worker gets isolated database tables (``test_w0_``, ``test_w1_``, etc.)
- Test servers run on unique ports per worker (5555, 5565, 5575, etc.)
- Actor emails are automatically made unique (``user_gw0_1_abc@example.com``)
- Tests marked with ``@pytest.mark.xdist_group`` stay on the same worker (``--dist loadgroup``)
- No test code changes needed - isolation is automatic

**Writing Parallel-Safe Tests:**

- Always use ``actor_factory`` fixture for creating actors
- Avoid hardcoded emails - let the factory generate unique ones
- Don't share state between tests
- Each test should be independent

.. code-block:: python

    # Good - automatically unique per worker
    def test_something(actor_factory):
        actor = actor_factory.create("test@example.com")

    # Bad - may conflict across workers
    def test_something(actor_factory):
        actor = actor_factory.create("fixed_email_123@example.com")

**Debugging Parallel Tests:**

.. code-block:: bash

    # Run with single worker for easier debugging
    poetry run pytest tests/integration/ -n 1 -v

    # Run sequentially (no parallelization)
    poetry run pytest tests/integration/ -v

DynamoDB for Development
========================

- Local (DynamoDB Local):

  .. code-block:: bash

      docker run -p 8000:8000 amazon/dynamodb-local
      export AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1

- Production: use proper IAM; tables are accessed by modules under ``actingweb.db_dynamodb``.

Docs and Examples
=================

- User docs live under docs/; add or update examples in ``docs/getting-started.rst``, ``docs/developers.rst``, and related pages.
- Build docs with ``make html`` and verify the updated pages in ``_build/html``.

- Reference demo application (for patterns and testing): https://github.com/actingweb/actingwebdemo

Commits and PRs
===============

- Commits: imperative mood, concise (e.g., "Fix trust permission mapping").
- PRs: include motivation, scope, linked issues (e.g., ``Closes #123``), test updates, and any doc changes.
- CI must pass: pytest (with coverage), mypy, Ruff, Black, and package build.

CI/CD Testing
=============

- GitHub Actions runs tests in parallel using ``pytest-xdist`` for 3-4× speedup
- Tests run with 4 workers on public repos, 2 workers on private repos
- Coverage reporting works seamlessly with parallel execution
- Same test suite runs locally (``make test-parallel``) and in CI

Release Process
===============

Releases are decoupled from PRs. PRs merge to master without version bumps; releases are triggered by git tags.

**For contributors:** Add CHANGELOG.rst entries to the "Unreleased" section. No version bumps needed in PRs.

**For maintainers (stable release):**

1. Update version in ``pyproject.toml`` and ``actingweb/__init__.py``
2. Rename "Unreleased" to ``vX.Y.Z: Date`` in ``CHANGELOG.rst``
3. Add new empty "Unreleased" section at top
4. Commit: ``git commit -am "Release vX.Y.Z"``
5. Tag: ``git tag vX.Y.Z``
6. Push: ``git push && git push --tags``

GitHub Actions validates the tag is on master, runs tests, publishes to PyPI, and creates a GitHub Release.

Pre-Release Versions
--------------------

Pre-release versions are automatically published to **TestPyPI** (not production PyPI).

**Supported patterns:**

- Alpha: ``X.Y.ZaN`` (e.g., ``3.10.0a1``)
- Beta: ``X.Y.ZbN`` (e.g., ``3.10.0b1``)
- Release Candidate: ``X.Y.ZrcN`` (e.g., ``3.10.0rc1``)
- Development: ``X.Y.Z.devN`` (e.g., ``3.10.0.dev1``)

**To create a pre-release:**

1. Update version to pre-release version (e.g., ``3.10.0a1``)
2. Commit and tag: ``git tag v3.10.0a1``
3. Push: ``git push && git push --tags``

**Installing pre-releases from TestPyPI:**

.. code-block:: bash

    pip install --index-url https://test.pypi.org/simple/ \
        --extra-index-url https://pypi.org/simple/ \
        actingweb==3.10.0a1

**Branch restriction:** Tags can only be released from commits on the master branch. Tags on feature branches will fail the release workflow.

**Required repository secrets:**

- ``POETRY_PYPI_TOKEN_PYPI`` - Production PyPI API token (stable releases)
- ``POETRY_TESTPYPI_TOKEN`` - TestPyPI API token (pre-releases)
