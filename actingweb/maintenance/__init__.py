"""Operator tooling that ships with the library.

These live inside the package, not in ``scripts/``, because they are the
documented path for work an operator has to be able to do from an installed
wheel -- converting existing property lists to the v2 storage format, and
sweeping for the corruption the pre-3.13 write paths could leave. A tool
that only exists in a source checkout is not a remedy for someone who
installed from PyPI.

Console entry points (see ``pyproject.toml``)::

    actingweb-verify-property-lists
    actingweb-migrate-property-lists

``scripts/`` keeps thin wrappers so existing runbooks and repo-relative
invocations keep working.
"""
