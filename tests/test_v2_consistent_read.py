"""Phase 6 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): consistent_read becomes a per-call parameter.

An eventually consistent DynamoDB range read costs half the read capacity
of a strongly consistent one, but whether a stale read is tolerable is an
application decision -- this phase adds the choice without changing any
default. Uses the dict-backed ``FakePropertyDb`` fake from
``test_property_list_integrity.py`` with a spy that records the
``consistent_read`` kwarg each ``get_range()`` call actually received.
"""

import ast
import pathlib

import pytest

from actingweb.property_list import ListProperty
from tests.test_property_list_integrity import (
    FakePropertyDb,
    _patch_get_property,
    _seed_v2_list,
)


class RecordingPropertyDb(FakePropertyDb):
    """Records the ``consistent_read`` value of every get_range() call."""

    def __init__(self, store):
        super().__init__(store)
        self.consistent_read_calls = []

    def get_range(
        self,
        actor_id=None,
        lower=None,
        upper=None,
        keys_only=False,
        consistent_read=True,
    ):
        self.consistent_read_calls.append(consistent_read)
        return super().get_range(
            actor_id=actor_id,
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )


@pytest.fixture
def fake_store():
    return {}


class TestConsistentReadDefaultsToTrue:
    def test_to_list_defaults_to_consistent(self, monkeypatch, fake_store):
        actor_id, name = "actor-cr-1", "lst"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.to_list() == ["a", "b"]
        assert fake_db.consistent_read_calls == [True]

    def test_slice_defaults_to_consistent(self, monkeypatch, fake_store):
        actor_id, name = "actor-cr-2", "lst"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.slice(0, 2) == ["a", "b"]
        assert fake_db.consistent_read_calls == [True]

    def test_to_indexed_list_defaults_to_consistent(self, monkeypatch, fake_store):
        actor_id, name = "actor-cr-3", "lst"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.to_indexed_list() == [(0, "a"), (1, "b")]
        assert fake_db.consistent_read_calls == [True]


class TestConsistentFalseIsHonoured:
    def test_to_list_consistent_false(self, monkeypatch, fake_store):
        actor_id, name = "actor-cr-4", "lst"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.to_list(consistent=False) == ["a", "b"]
        assert fake_db.consistent_read_calls == [False]

    def test_slice_consistent_false(self, monkeypatch, fake_store):
        actor_id, name = "actor-cr-5", "lst"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.slice(1, 3, consistent=False) == ["b", "c"]
        assert fake_db.consistent_read_calls == [False]

    def test_to_indexed_list_consistent_false(self, monkeypatch, fake_store):
        actor_id, name = "actor-cr-6", "lst"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.to_indexed_list(consistent=False) == [(0, "a"), (1, "b")]
        assert fake_db.consistent_read_calls == [False]


class TestPositionalAccessIsAlwaysConsistent:
    def test_v2_ensure_rank_cache_is_always_consistent(self, monkeypatch, fake_store):
        actor_id, name = "actor-cr-7", "lst"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst[0] == "a"  # __getitem__ forces a fresh rank cache read
        assert lst[1] == "b"
        assert fake_db.consistent_read_calls == [True, True]

    def test_positional_mutations_take_no_consistent_parameter(self):
        import inspect

        for name in ("__setitem__", "__delitem__", "insert", "pop", "remove"):
            sig = inspect.signature(getattr(ListProperty, name))
            assert "consistent" not in sig.parameters, (
                f"{name}() must not accept a consistency override -- a "
                f"stale rank feeding a positional write touches the wrong "
                f"row"
            )


class TestHandlersNeverSpendTheGuarantee:
    """A REST client that does PUT then GET expects to see its own write --
    no call site under actingweb/handlers/ may pass consistent=False on the
    library's own behalf. A grep-style AST check so a later edit cannot
    quietly spend the guarantee without this test noticing."""

    def test_no_handler_passes_consistent_false(self):
        handlers_dir = (
            pathlib.Path(__file__).resolve().parent.parent / "actingweb" / "handlers"
        )
        offenders = []
        for path in sorted(handlers_dir.glob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg not in ("consistent", "consistent_read"):
                        continue
                    if isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        offenders.append(f"{path.name}:{node.lineno}")
        assert offenders == [], (
            f"handlers must never spend the read-your-writes guarantee on "
            f"a REST caller's behalf: {offenders}"
        )


class TestPostgreSQLAcceptsAndIgnoresConsistentRead:
    """PostgreSQL reads are consistent by construction -- the parameter is
    part of the protocol (DynamoDB's callers pass it uniformly), not a
    DynamoDB detail leaking upward. Real backend, gated like the sibling
    Phase 4 partition test."""

    @pytest.fixture(autouse=True)
    def _require_postgresql(self):
        import os

        if os.getenv("DATABASE_BACKEND") != "postgresql":
            pytest.skip("PostgreSQL-only test (run with DATABASE_BACKEND=postgresql)")

    def test_consistent_read_false_is_accepted_and_results_unchanged(self):
        import uuid

        from actingweb.db.postgresql.property import DbProperty

        actor_id = f"v2cost-consistent-{uuid.uuid4()}"
        db = DbProperty()
        for i in range(3):
            db.set(actor_id=actor_id, name=f"p{i}", value=f"v{i}")

        strong = db.get_range(
            actor_id=actor_id, lower="p0", upper="p9", consistent_read=True
        )
        eventual = db.get_range(
            actor_id=actor_id, lower="p0", upper="p9", consistent_read=False
        )
        assert strong == eventual == {f"p{i}": f"v{i}" for i in range(3)}

        for i in range(3):
            db.set(actor_id=actor_id, name=f"p{i}", value=None)
