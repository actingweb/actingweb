"""``tests/test_v2_list_mutation_committed.py`` run through a bare
``ListCore`` over ``PropertyListStorage`` (Phase 1 of
thoughts/plans/2026-11-13-attribute-list-v2-port.md): ``ListProperty``
calls the core's ``_v2_*`` halves, so the core's own public layer meets a
real storage adapter here, with the suite's fault injection unchanged.

The suite's module name ``ListProperty`` is rebound for each test. Left out:
the v1 case (the core has no v1) and the notifying wrapper's diffs (a
property-store concern, which wraps a ``ListProperty`` only)."""

from typing import Any

import pytest

import tests.test_v2_list_mutation_committed as suite
from actingweb.list_core import ListCore
from actingweb.property_list import PropertyListStorage


class _BareCore(ListCore):
    """The core with the property constructor, nothing else."""

    def __init__(self, actor_id: str, name: str, config: Any) -> None:
        super().__init__(PropertyListStorage(actor_id, config), name)


@pytest.fixture(autouse=True)
def _bare_core(monkeypatch):
    monkeypatch.setattr(suite, "ListProperty", _BareCore)


@pytest.fixture
def fake_store():
    return {}


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """As the suite's own: its CAS-loss cases back off with time.sleep()."""
    monkeypatch.setattr("actingweb.list_core.time.sleep", lambda *_: None)


class TestCoreBulkHandlerShape(suite.TestTheExactBulkHandlerShapeFromANeverCreatedList):
    pass


class TestCoreFirstMutationWriteOrder(suite.TestFirstMutationWriteOrder):
    pass


class TestCoreExistingRowSwallowsBackendFault(
    suite.TestExistingRowSwallowsBackendFault
):
    pass


class TestCoreBoundaries(suite.TestBoundaries):
    @pytest.mark.skip(reason="v1 only: the core has no stored length")
    def test_v1_semantic_length_write_still_raises_on_backend_fault(
        self, monkeypatch, fake_store
    ):
        pass


class TestCoreFirstMutationFaults(suite.TestFirstMutationFaults):
    pass


class TestCoreFirstMutationLostCreate(suite.TestFirstMutationLostCreate):
    pass


class TestCoreResidualOrphan(suite.TestResidualOrphan):
    pass


class TestCoreExistingRegressionsStayGreen(suite.TestExistingRegressionsStayGreen):
    pass


class TestCoreVerifyReportsOrphanState(suite.TestVerifyReportsOrphanState):
    pass
