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
