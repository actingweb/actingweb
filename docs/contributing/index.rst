=============
Contributing
=============

**Audience**: Developers who want to contribute to the ActingWeb project.

Thank you for your interest in contributing to ActingWeb! This section provides everything you need to get started.

Contents
========

.. toctree::
   :maxdepth: 2

   architecture
   testing
   style-guide

Getting Started
===============

1. **Fork the repository** on GitHub
2. **Clone your fork** locally
3. **Set up development environment**:

   .. code-block:: bash

       poetry install --with dev,docs
       poetry shell

4. **Run tests** to verify setup:

   .. code-block:: bash

       poetry run pytest tests/ -v

5. **Read the architecture** overview: :doc:`architecture`

Development Workflow
====================

1. Create a feature branch from ``master``
2. Make your changes
3. Run quality checks:

   .. code-block:: bash

       poetry run pyright actingweb tests
       poetry run ruff check actingweb tests
       poetry run pytest tests/

4. Commit with descriptive message
5. Push and create pull request

Documentation
=============

**Architecture**
   Overview of the codebase structure and module responsibilities.

**Testing**
   Guide to running and writing tests.

**Style Guide**
   Code style conventions and type annotation guidelines.

Quality Standards
=================

All contributions must maintain:

- Zero pyright errors/warnings
- Zero ruff errors
- All tests passing
- Documentation for new features

See Also
========

- :doc:`../sdk/index` - SDK documentation
- `GitHub Repository <https://github.com/actingweb/actingweb>`_
- `Issue Tracker <https://github.com/actingweb/actingweb/issues>`_
