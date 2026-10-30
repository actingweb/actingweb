"""Operator tooling that ships with the library.

These live inside the package, not in ``scripts/``, because they are the
documented path for work an operator has to be able to do from an installed
wheel -- converting existing property lists to the v2 storage format,
sweeping for the corruption the pre-3.13 write paths could leave, and
scanning whole tables for rows orphaned by an interrupted actor deletion,
marking existing actors vouched when upgrading to 3.16, and finding and
resolving duplicate creators before turning ``with_unique_creator()`` on.
A tool that only exists in a source checkout is not a remedy for someone
who installed from PyPI.

Console entry points (see ``pyproject.toml``)::

    actingweb-verify-property-lists
    actingweb-migrate-property-lists
    actingweb-verify-orphans
    actingweb-mark-actors-vouched
    actingweb-unique-creators

``scripts/`` keeps thin wrappers so existing runbooks and repo-relative
invocations keep working.
"""
