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

from collections.abc import Callable
from typing import Any

import pytest

_real_probe: Callable[[Any], None] | None = None
_real_unique: Callable[[Any], None] | None = None


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
