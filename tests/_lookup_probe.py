"""Test seam for the reverse-lookup readiness probe.

``ActingWebApp.check_ready()`` refuses a store whose properties hold data but
whose indexed names carry no backfill-complete marker. The shared test stores
(the ``test`` prefix, the per-worker ``test_w<N>_`` prefixes) hold properties
from earlier runs and tests, so every ``integrate_*`` call would refuse. Tests
that are not about readiness run with the probe stubbed for the whole process;
a test that is about it requests ``real_lookup_probe`` to put the real probe
back.

The fixtures are imported by ``tests/conftest.py`` and
``tests/integration/conftest.py``: an integration-only run
(``pytest tests/integration``) takes its rootdir from the integration
``pytest.ini`` and does not load the root conftest. In a full run both
conftests define them, so each worker instantiates the session fixture once
per scope; the real probe is therefore captured once, in a module global, and
the stub is never undone (a second scope's teardown must not restore the real
probe under tests still running with the stub).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest

_real_probe: Callable[[Any], None] | None = None
_real_unique: Callable[[Any], None] | None = None
_real_pg_index: Callable[[], bool] | None = None
_real_ddb_backfill: Callable[[], bool] | None = None


def real_probe() -> Callable[[Any], None]:
    """The real ``ActingWebApp._check_property_lookup_ready``."""
    global _real_probe
    if _real_probe is None:
        from actingweb.interface.app import ActingWebApp

        _real_probe = ActingWebApp._check_property_lookup_ready  # pyright: ignore[reportPrivateUsage]
    return _real_probe


@pytest.fixture(scope="session", autouse=True)
def _stub_property_lookup_probe() -> None:
    """Stub the lookup readiness probe for the whole process."""
    from actingweb.interface.app import ActingWebApp

    real_probe()  # capture before the first stub
    ActingWebApp._check_property_lookup_ready = lambda self: None  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def real_lookup_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the real reverse-lookup readiness probe in this test."""
    from actingweb.interface.app import ActingWebApp

    monkeypatch.setattr(ActingWebApp, "_check_property_lookup_ready", real_probe())


def real_unique_probe_fn() -> Callable[[Any], None]:
    """The real ``ActingWebApp._check_unique_creator_ready``."""
    global _real_unique
    if _real_unique is None:
        from actingweb.interface.app import ActingWebApp

        _real_unique = ActingWebApp._check_unique_creator_ready  # pyright: ignore[reportPrivateUsage]
    return _real_unique


@pytest.fixture(scope="session", autouse=True)
def _stub_unique_creator_probe() -> None:
    """Stub the creator-uniqueness readiness probe for the whole process.

    Uniqueness is on by default, so every ``integrate_*`` call would refuse
    on a shared store that never ran ``actingweb-unique-creators enable``
    (and the shared stores hold deliberate duplicate creators). Tests that
    are about the probe request ``real_unique_probe``.
    """
    from actingweb.interface.app import ActingWebApp

    real_unique_probe_fn()
    ActingWebApp._check_unique_creator_ready = lambda self: None  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def real_unique_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the real creator-uniqueness readiness probe in this test."""
    from actingweb.interface.app import ActingWebApp

    monkeypatch.setattr(
        ActingWebApp, "_check_unique_creator_ready", real_unique_probe_fn()
    )


def _postgresql_run() -> bool:
    return os.environ.get("DATABASE_BACKEND", "dynamodb") == "postgresql"


def real_pg_index_probe_fn() -> Callable[[], bool]:
    """The real ``actingweb.db.postgresql.actor._creator_index_present``."""
    global _real_pg_index
    if _real_pg_index is None:
        from actingweb.db.postgresql import actor as pg_actor

        _real_pg_index = pg_actor._creator_index_present  # pyright: ignore[reportPrivateUsage]
    return _real_pg_index


@pytest.fixture(scope="session", autouse=True)
def _stub_pg_creator_index_probe() -> None:
    """Stub the PostgreSQL ``ux_actors_creator`` probe for the whole process.

    An enforced create refuses while the index is missing, and the index
    cannot be built over the shared schemas, which hold deliberate duplicate
    creators (the unit ``public`` schema and the per-worker integration
    schemas, which Alembic builds without it). Tests that are about the
    probe request ``real_pg_index_probe``. A DynamoDB run imports no psycopg.
    """
    if not _postgresql_run():
        return
    from actingweb.db.postgresql import actor as pg_actor

    real_pg_index_probe_fn()
    pg_actor._creator_index_present = lambda: True  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def real_pg_index_probe(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the real PostgreSQL creator-index probe in this test, with a
    clean cache before and after."""
    from actingweb.db.postgresql import actor as pg_actor

    pg_actor.reset_index_probe()
    monkeypatch.setattr(pg_actor, "_creator_index_present", real_pg_index_probe_fn())
    yield
    pg_actor.reset_index_probe()


def real_dynamodb_backfill_probe_fn() -> Callable[[], bool]:
    """The real ``actingweb.db.dynamodb._backfill_probe.creators_backfilled``."""
    global _real_ddb_backfill
    if _real_ddb_backfill is None:
        from actingweb.db.dynamodb import _backfill_probe

        _real_ddb_backfill = _backfill_probe.creators_backfilled
    return _real_ddb_backfill


@pytest.fixture(autouse=True)
def _stub_dynamodb_backfill_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the DynamoDB creators backfill probe in every test.

    An enforced create refuses while the creators table is not backfilled,
    and the shared test stores cannot be (they hold deliberate duplicate
    creators). Installed on every backend: several unit tests pin
    ``database="dynamodb"`` whatever the run's backend. Function-scoped, not
    session-scoped like the other stubs: importing anything under
    ``actingweb.db.dynamodb`` imports every table model, whose names freeze
    at import, and a session fixture can run before the integration
    conftest has set the worker's ``AWS_DB_PREFIX``. Tests that are about
    the probe request ``real_dynamodb_backfill_probe``.
    """
    from actingweb.db.dynamodb import _backfill_probe

    real_dynamodb_backfill_probe_fn()
    monkeypatch.setattr(_backfill_probe, "creators_backfilled", lambda: True)


@pytest.fixture
def real_dynamodb_backfill_probe(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run the real DynamoDB backfill probe in this test, with a clean cache
    before and after."""
    from actingweb.db.dynamodb import _backfill_probe

    _backfill_probe.reset_backfill_probe()
    monkeypatch.setattr(
        _backfill_probe, "creators_backfilled", real_dynamodb_backfill_probe_fn()
    )
    yield
    _backfill_probe.reset_backfill_probe()
