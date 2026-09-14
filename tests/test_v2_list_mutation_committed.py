"""thoughts/plans/2026-09-14-v2-list-mutation-raises-after-its-write-committed.md:
a v2 ``ListProperty`` mutator commits its item row and then calls
``_v2_touch_metadata()``. Before this plan the touch's ``advisory=True``
swallowed compare-and-swap exhaustion only; a backend fault (``DbError``, or
PostgreSQL's ``RuntimeError`` on the row-creation branch) still raised out of
a mutation that had already committed. This file pins:

- every v2 item mutator's touch now swallows a backend fault too, on an
  EXISTING meta row (``TestExistingRowSwallowsBackendFault``);
- a list's first mutation creates its meta row BEFORE its first item row,
  so a fault on the item write leaves an empty but VISIBLE list instead of
  an orphan (``TestFirstMutationFaults``, ``TestFirstMutationWriteOrder``);
- the narrow residual (a ``delete()`` sweep between the two first-mutation
  writes, plus a fault on the recreation) is still swallowed with a WARNING
  (``TestResidualOrphan``);
- what stays un-swallowed: a lost meta-row create raises
  ``ListMetadataContentionError`` before any write
  (``TestFirstMutationLostCreate``), and corruption (``ValueError``) is
  never treated as an advisory fault (``TestBoundaries``).
"""

import json
import logging
from unittest.mock import Mock

import pytest

from actingweb.db.exceptions import DbError
from actingweb.interface.property_store import NotifyingListProperty
from actingweb.property_list import ListMetadataContentionError, ListProperty
from tests.test_property_list_integrity import (
    FakePropertyDb,
    _patch_get_property,
    _seed_list,
    _seed_v2_list,
)


@pytest.fixture
def fake_store():
    return {}


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Copied from tests/test_v2_metadata_cas.py:87-94 -- the meta
    get-on-retry case (and the residual's CAS-then-creation-branch path)
    needs the CAS loop to lose at least once before its fault fires, and
    the retry loop backs off with real time.sleep() between attempts."""
    monkeypatch.setattr("actingweb.property_list.time.sleep", lambda *_: None)


def _meta_name(name):
    return f"list:{name}-meta"


def _stored_meta(store, actor_id, name):
    return json.loads(store[(actor_id, _meta_name(name))])


def _item_rows(store, actor_id, name):
    prefix = f"list:{name}-#"
    return {
        k: v for k, v in store.items() if k[0] == actor_id and k[1].startswith(prefix)
    }


class _MetaFaultPropertyDb(FakePropertyDb):
    """Raises ``DbError`` from named ops on the meta row only -- item rows
    never end in "-meta", so this filter never touches them.

    ``fail_ops``: subset of {"set", "set_if_value_equals",
    "create_if_not_exists"}.
    ``lose_cas_first``: ``set_if_value_equals`` on the meta row returns
    ``False`` this many times (a lost CAS, not a fault) before the
    configured fault fires.
    ``fail_get_after_cas_losses``: ``get()`` on the meta row raises
    ``DbError``, but only once at least one CAS loss has already
    happened -- so the pre-write dispatch read and (if applicable) the
    lazy-migrate collision check, both before any write, succeed, and the
    fault lands on ``_save_metadata()``'s retry-attempt read instead.
    """

    def __init__(
        self, store, fail_ops, lose_cas_first=0, fail_get_after_cas_losses=False
    ):
        super().__init__(store)
        self.fail_ops = set(fail_ops)
        self.lose_cas_first = lose_cas_first
        self.fail_get_after_cas_losses = fail_get_after_cas_losses
        self._cas_loss_count = 0
        self.call_counts: dict[str, int] = {}

    def _tick(self, op):
        self.call_counts[op] = self.call_counts.get(op, 0) + 1

    def get(self, actor_id=None, name=None):
        if name is not None and name.endswith("-meta"):
            self._tick("get")
            if self.fail_get_after_cas_losses and self._cas_loss_count > 0:
                raise DbError("property read", actor_id)
        return super().get(actor_id=actor_id, name=name)

    def set(self, actor_id=None, name=None, value=None):
        if name is not None and name.endswith("-meta"):
            self._tick("set")
            if "set" in self.fail_ops:
                raise DbError("property write", actor_id)
        return super().set(actor_id=actor_id, name=name, value=value)

    def create_if_not_exists(self, actor_id=None, name=None, value=None):
        if name is not None and name.endswith("-meta"):
            self._tick("create_if_not_exists")
            if "create_if_not_exists" in self.fail_ops:
                raise DbError("property write", actor_id)
        return super().create_if_not_exists(actor_id=actor_id, name=name, value=value)

    def set_if_value_equals(self, actor_id=None, name=None, expected=None, value=None):
        if name is not None and name.endswith("-meta"):
            self._tick("set_if_value_equals")
            if self._cas_loss_count < self.lose_cas_first:
                self._cas_loss_count += 1
                return False
            if "set_if_value_equals" in self.fail_ops:
                raise DbError("property write", actor_id)
        return super().set_if_value_equals(
            actor_id=actor_id, name=name, expected=expected, value=value
        )


class _ItemFaultPropertyDb(FakePropertyDb):
    """Raises ``DbError`` from ``create_if_not_exists`` on ITEM rows
    (names containing the v2 rank marker ``-#``). ``fail_at_call``, if
    given, faults only that 1-indexed item-row create call; ``None``
    (the default) faults every one."""

    def __init__(self, store, fail_at_call=None):
        super().__init__(store)
        self.fail_at_call = fail_at_call
        self.item_create_call_count = 0

    def create_if_not_exists(self, actor_id=None, name=None, value=None):
        if name is not None and "-#" in name:
            self.item_create_call_count += 1
            if (
                self.fail_at_call is None
                or self.item_create_call_count == self.fail_at_call
            ):
                raise DbError("property write", actor_id)
        return super().create_if_not_exists(actor_id=actor_id, name=name, value=value)


class _ConcurrentCreatorPropertyDb(FakePropertyDb):
    """On the FIRST ``create_if_not_exists`` for a "-meta" name, writes
    ``injected_meta`` into the store (unless it is ``None``, simulating a
    row created and deleted again inside the window) and returns
    ``False`` -- another writer won the race to create the row."""

    def __init__(self, store, injected_meta):
        super().__init__(store)
        self.injected_meta = injected_meta
        self._fired = False

    def create_if_not_exists(self, actor_id=None, name=None, value=None):
        if not self._fired and name is not None and name.endswith("-meta"):
            self._fired = True
            if self.injected_meta is not None:
                self.store[(actor_id, name)] = json.dumps(self.injected_meta)
            return False
        return super().create_if_not_exists(actor_id=actor_id, name=name, value=value)


class _DeleteAfterCreatePropertyDb(FakePropertyDb):
    """After a successful ``create_if_not_exists`` on "-meta", pops the
    row again (a concurrent ``delete()`` won the race) and raises
    ``DbError`` from the next unconditional ``set`` on "-meta" -- the
    touch's row-recreation branch, reached because the stash's CAS then
    loses against the now-absent row."""

    def __init__(self, store):
        super().__init__(store)
        self._created = False

    def create_if_not_exists(self, actor_id=None, name=None, value=None):
        result = super().create_if_not_exists(actor_id=actor_id, name=name, value=value)
        if result and name is not None and name.endswith("-meta"):
            self._created = True
            del self.store[(actor_id, name)]
        return result

    def set(self, actor_id=None, name=None, value=None):
        if self._created and name is not None and name.endswith("-meta"):
            raise DbError("property write", actor_id)
        return super().set(actor_id=actor_id, name=name, value=value)


class _RecordingPropertyDb(FakePropertyDb):
    """Appends ``(op, name)`` to a shared list for every write."""

    def __init__(self, store, calls):
        super().__init__(store)
        self.calls = calls

    def create_if_not_exists(self, actor_id=None, name=None, value=None):
        self.calls.append(("create_if_not_exists", name))
        return super().create_if_not_exists(actor_id=actor_id, name=name, value=value)

    def set_if_value_equals(self, actor_id=None, name=None, expected=None, value=None):
        self.calls.append(("set_if_value_equals", name))
        return super().set_if_value_equals(
            actor_id=actor_id, name=name, expected=expected, value=value
        )

    def set(self, actor_id=None, name=None, value=None):
        self.calls.append(("set", name))
        return super().set(actor_id=actor_id, name=name, value=value)


def _warning_records(caplog, needle="backend fault"):
    return [
        r
        for r in caplog.records
        if r.name == "actingweb.property_list" and needle in r.getMessage()
    ]


class TestTheExactBulkHandlerShapeFromANeverCreatedList:
    """CRITICAL regression pin: the diff changes existing first-mutation
    behaviour and no existing unit test covers the instance-reuse path on
    a NEVER-CREATED list. handlers/properties.py's bulk pass loops
    ``len(list_prop)`` / ``list_prop.append(None)`` on the SAME instance
    -- this hung once when the rank cache stopped advancing
    (_v2_append()'s docstring). _v2_create_meta_row()'s
    _invalidate_cache() is exactly the kind of change that could
    reintroduce that hang, because it drops the rank cache the touch's
    caller may be relying on staying warm. tests/test_v2_append_last_rank.py:124
    (test_the_exact_bulk_handler_shape_terminates) pins the same shape
    from an ALREADY-SEEDED list; this pins it starting from a
    never-created one and adds the positional write after the appends.
    """

    @pytest.mark.timeout(5)
    def test_bulk_shape_terminates_from_a_never_created_list(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-bulk-shape"
        name = "notes"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert len(lst) == 0
        lst.append(None)
        assert len(lst) == 1
        lst.append(None)
        assert len(lst) == 2

        lst[1] = "x"
        assert lst.to_list() == [None, "x"]


class TestFirstMutationWriteOrder:
    def test_first_append_creates_meta_then_item_then_touches(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-order"
        name = "notes"
        calls: list[tuple[str, str | None]] = []
        _patch_get_property(
            monkeypatch, lambda config: _RecordingPropertyDb(fake_store, calls)
        )

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("a")

        meta_name = _meta_name(name)
        assert calls[0] == ("create_if_not_exists", meta_name)
        assert calls[1][0] == "create_if_not_exists"
        assert calls[1][1] != meta_name  # the item row
        assert calls[2] == ("set_if_value_equals", meta_name)
        assert _stored_meta(fake_store, actor_id, name)["count_hint"] == 1

    def test_extend_of_zero_items_on_a_never_created_list_records_nothing(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-extend-empty"
        name = "notes"
        calls: list[tuple[str, str | None]] = []
        _patch_get_property(
            monkeypatch, lambda config: _RecordingPropertyDb(fake_store, calls)
        )

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.extend([])

        assert calls == []
        assert (actor_id, _meta_name(name)) not in fake_store


# -- Mutator cases shared by the existing-row swallow tests -----------------
#
# Each case seeds a v2 list, performs one mutation, and returns (result,
# expected_to_list) for the test to assert against. Kept as plain functions
# (not lambdas) because several need more than one statement (resolving a
# handle first).


def _do_append(lst):
    return lst.append("d")


def _do_extend(lst):
    return lst.extend(["d", "e"])


def _do_insert(lst):
    return lst.insert(1, "x")


def _do_setitem(lst):
    lst[1] = "x"
    return None


def _do_delitem(lst):
    del lst[2]
    return None


def _do_pop(lst):
    return lst.pop()


def _do_remove(lst):
    return lst.remove("b")


def _do_delete_by_handle(lst):
    handle, _ = lst.items_with_handles()[1]
    return lst.delete_by_handle(handle)


def _do_update_by_handle(lst):
    handle, _ = lst.items_with_handles()[1]
    return lst.update_by_handle(handle, "X")


def _do_remove_where(lst):
    return lst.remove_where("id", 2)


def _do_update_where(lst):
    return lst.update_where("id", 2, {"id": 2, "v": "new"})


_SCALAR_SEED = ["a", "b", "c"]
_DICT_SEED = [{"id": 1}, {"id": 2}, {"id": 3}]

_MUTATOR_CASES = [
    ("append", _SCALAR_SEED, _do_append, ["a", "b", "c", "d"]),
    ("extend", _SCALAR_SEED, _do_extend, ["a", "b", "c", "d", "e"]),
    ("insert", _SCALAR_SEED, _do_insert, ["a", "x", "b", "c"]),
    ("__setitem__", _SCALAR_SEED, _do_setitem, ["a", "x", "c"]),
    ("__delitem__", _SCALAR_SEED, _do_delitem, ["a", "b"]),
    ("pop", _SCALAR_SEED, _do_pop, ["a", "b"]),
    ("remove", _SCALAR_SEED, _do_remove, ["a", "c"]),
    ("delete_by_handle", _SCALAR_SEED, _do_delete_by_handle, ["a", "c"]),
    ("update_by_handle", _SCALAR_SEED, _do_update_by_handle, ["a", "X", "c"]),
    ("remove_where", _DICT_SEED, _do_remove_where, [{"id": 1}, {"id": 3}]),
    (
        "update_where",
        _DICT_SEED,
        _do_update_where,
        [{"id": 1}, {"id": 2, "v": "new"}, {"id": 3}],
    ),
]


class TestExistingRowSwallowsBackendFault:
    @pytest.mark.parametrize(
        "case_id,seed,action,expected",
        _MUTATOR_CASES,
        ids=[c[0] for c in _MUTATOR_CASES],
    )
    def test_touch_fault_on_an_existing_row_is_swallowed(
        self, monkeypatch, fake_store, caplog, case_id, seed, action, expected
    ):
        actor_id = f"actor-committed-swallow-{case_id}"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, seed)
        meta = _stored_meta(fake_store, actor_id, name)
        meta["count_hint"] = len(seed)
        fake_store[(actor_id, _meta_name(name))] = json.dumps(meta)

        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with caplog.at_level(logging.WARNING, logger="actingweb.property_list"):
            action(lst)  # must not raise

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == expected

        warnings = _warning_records(caplog)
        assert len(warnings) == 1
        assert warnings[0].exc_info is not None
        assert "database error during" in warnings[0].getMessage()

    def test_pop_returns_the_popped_item_despite_the_fault(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-pop-return"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        assert lst.pop() == "c"

    def test_remove_where_three_matches_and_a_fault_on_every_touch_returns_all_three(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-removewhere-three"
        name = "notes"
        seed = [{"id": 1, "n": 1}, {"id": 1, "n": 2}, {"id": 1, "n": 3}]
        _seed_v2_list(fake_store, actor_id, name, seed)
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        removed = lst.remove_where("id", 1)
        assert removed == seed

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == []

    def test_update_where_three_matches_and_a_fault_on_every_touch_returns_all_pre_update(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-updatewhere-three"
        name = "notes"
        seed = [{"id": 1, "n": 1}, {"id": 1, "n": 2}, {"id": 1, "n": 3}]
        _seed_v2_list(fake_store, actor_id, name, seed)
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        updated = lst.update_where("id", 1, {"id": 1, "n": "new"})
        assert updated == seed

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == [{"id": 1, "n": "new"}] * 3

    def test_retry_read_fault_after_one_lost_cas_is_swallowed(
        self, monkeypatch, fake_store
    ):
        """Pins the retry-read fault path specifically: attempt 0 loses
        its CAS (a normal contention loss, not a fault), attempt 1's
        re-read raises DbError."""
        actor_id = "actor-committed-retry-read-fault"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a"])
        fake_db = _MetaFaultPropertyDb(
            fake_store,
            fail_ops=set(),
            lose_cas_first=1,
            fail_get_after_cas_losses=True,
        )
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("b")  # must not raise

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == ["a", "b"]

    def test_drift_after_swallowed_fault_is_bounded_and_the_next_mutation_repairs_it(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-drift-repair"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a"])
        meta = _stored_meta(fake_store, actor_id, name)
        meta["count_hint"] = 1
        fake_store[(actor_id, _meta_name(name))] = json.dumps(meta)

        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("b")  # item lands; touch faults and is swallowed

        assert _stored_meta(fake_store, actor_id, name)["count_hint"] == 1  # stale
        assert lst.get_metadata()["length"] == 1  # advisory, off by one

        report = lst.verify()
        assert report["count_hint"] == 1
        assert report["count_hint_drift"] == -1
        assert report["healthy"] is True

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        repaired = ListProperty(actor_id=actor_id, name=name, config=object())
        repaired.pop()  # writes counted truth

        assert repaired.to_list() == ["a"]
        assert repaired.verify()["count_hint_drift"] == 0


class TestBoundaries:
    def test_v1_semantic_length_write_still_raises_on_backend_fault(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-v1-boundary"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["x"])
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(DbError):
            lst.append("y")

        # The item write itself committed before the (non-advisory)
        # metadata write raised.
        assert fake_store[(actor_id, f"list:{name}-1")] == json.dumps("y")

    def test_set_description_on_an_existing_row_still_raises_on_backend_fault(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-semantic-boundary"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a"])
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(DbError):
            lst.set_description("new description")

    def test_corruption_value_error_still_raises_even_though_the_touch_is_advisory(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-corruption-boundary"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a"])
        meta_name = _meta_name(name)

        fake_db = _MetaFaultPropertyDb(
            fake_store,
            fail_ops=set(),
            lose_cas_first=1,
            fail_get_after_cas_losses=False,
        )
        _patch_get_property(monkeypatch, lambda config: fake_db)

        real_get = FakePropertyDb.get

        def _corrupt_after_cas_loss(self, actor_id=None, name=None):
            if name == meta_name and fake_db._cas_loss_count > 0:
                return "not json"
            return real_get(self, actor_id=actor_id, name=name)

        monkeypatch.setattr(_MetaFaultPropertyDb, "get", _corrupt_after_cas_loss)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(ValueError):
            lst.append("b")


class TestFirstMutationFaults:
    @pytest.mark.parametrize(
        "mutate",
        [
            lambda lst: lst.append("a"),
            lambda lst: lst.extend(["a"]),
            lambda lst: lst.insert(0, "a"),
        ],
        ids=["append", "extend", "insert"],
    )
    def test_meta_create_fault_raises_and_nothing_is_written(
        self, monkeypatch, fake_store, mutate
    ):
        actor_id = "actor-committed-meta-create-fault"
        name = "notes"
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"create_if_not_exists"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(DbError):
            mutate(lst)

        assert fake_store == {}

    def test_item_write_fault_after_meta_create_leaves_an_empty_visible_list(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-item-fault"
        name = "notes"
        fake_db = _ItemFaultPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(DbError):
            lst.append("a")

        meta = _stored_meta(fake_store, actor_id, name)
        assert meta["format"] == 2
        assert meta["count_hint"] == 0
        assert meta["format_ever_changed"] is False

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == []
        assert (actor_id, _meta_name(name)) in fake_store

    def test_set_if_value_equals_fault_on_a_never_created_list_lands_the_item_with_drift(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-first-cas-fault"
        name = "notes"
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("a")  # must not raise

        item_rows = _item_rows(fake_store, actor_id, name)
        assert len(item_rows) == 1
        assert (
            _stored_meta(fake_store, actor_id, name)["count_hint"] == 0
        )  # drift of one

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == ["a"]

        fake_db2 = FakePropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db2)
        clean = ListProperty(actor_id=actor_id, name=name, config=object())
        clean.append("b")
        assert clean.to_list() == ["a", "b"]

    def test_extend_faulting_on_the_second_item_only_leaves_the_first_landed(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-extend-partial"
        name = "notes"
        fake_db = _ItemFaultPropertyDb(fake_store, fail_at_call=2)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(DbError):
            lst.extend(["a", "b", "c"])

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == ["a"]
        # The touch never ran (the raise happened before it).
        assert _stored_meta(fake_store, actor_id, name)["count_hint"] == 0

        report = fresh.verify()
        assert report["count_hint_drift"] == -1

    def test_hash_name_raises_value_error_before_any_write(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-hash-name"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name="bad#name", config=object())
        with pytest.raises(ValueError):
            lst.append("a")

        assert fake_store == {}

    def test_scalar_collision_raises_value_error_before_any_write(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-collision"
        name = "notes"
        fake_store[(actor_id, name)] = json.dumps("i am a scalar")
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(ValueError):
            lst.append("a")

        assert (actor_id, _meta_name(name)) not in fake_store


class TestFirstMutationLostCreate:
    def test_losing_to_a_concurrent_v2_creator_proceeds_against_their_row(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-lost-create-v2"
        name = "notes"
        injected = {
            "format": 2,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "count_hint": 4,
            "description": "theirs",
            "explanation": "",
            "format_ever_changed": False,
        }
        fake_db = _ConcurrentCreatorPropertyDb(fake_store, injected)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("a")  # must not raise -- proceeds against the winner's row

        meta = _stored_meta(fake_store, actor_id, name)
        assert meta["description"] == "theirs"
        assert meta["count_hint"] == 5

    def test_losing_to_a_concurrent_v1_creator_raises_contention_and_writes_nothing(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-lost-create-v1"
        name = "notes"
        injected = {
            "length": 0,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "",
            "explanation": "",
            "format_ever_changed": False,
        }
        fake_db = _ConcurrentCreatorPropertyDb(fake_store, injected)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(ListMetadataContentionError) as exc_info:
            lst.append("a")

        assert "first-mutation create" in str(exc_info.value)
        assert "sustained contention" not in str(exc_info.value)
        assert _item_rows(fake_store, actor_id, name) == {}

    def test_losing_to_a_creator_that_then_vanished_also_raises_contention(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-lost-create-vanished"
        name = "notes"
        fake_db = _ConcurrentCreatorPropertyDb(fake_store, injected_meta=None)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(ListMetadataContentionError) as exc_info:
            lst.append("a")

        assert "first-mutation create" in str(exc_info.value)
        assert fake_store == {}

    def test_the_error_messages_and_handler_body(self):
        from actingweb.handlers.properties import PropertiesHandler

        default_err = ListMetadataContentionError("notes", "actor-1")
        assert "sustained contention" in str(default_err)
        assert str(default_err).endswith("retry the request")

        detailed_err = ListMetadataContentionError(
            "notes",
            "actor-1",
            detail="metadata row changed under a first-mutation create",
        )
        assert "metadata row changed under a first-mutation create" in str(detailed_err)
        assert str(detailed_err).endswith("retry the request")

        class FakeResponse:
            def __init__(self):
                self.status = None
                self.headers = {}
                self.body = None

            def set_status(self, code, message=None):
                self.status = code

            def write(self, text):
                self.body = text

        handler = PropertiesHandler.__new__(PropertiesHandler)
        fake_response = FakeResponse()
        handler.response = fake_response  # type: ignore[assignment]
        handler._respond_list_metadata_contended(detailed_err)

        assert fake_response.status == 503
        assert fake_response.headers["Retry-After"]
        assert fake_response.body is not None
        body = json.loads(fake_response.body)
        assert body["detail"] == str(detailed_err)


class TestResidualOrphan:
    def test_delete_sweep_between_the_two_writes_plus_a_recreation_fault_is_swallowed(
        self, monkeypatch, fake_store, caplog
    ):
        actor_id = "actor-committed-residual"
        name = "notes"
        fake_db = _DeleteAfterCreatePropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        with caplog.at_level(logging.WARNING, logger="actingweb.property_list"):
            lst.append("a")  # must not raise

        warnings = _warning_records(caplog)
        assert len(warnings) == 1

        assert _item_rows(fake_store, actor_id, name) != {}
        assert (actor_id, _meta_name(name)) not in fake_store  # the documented residual


class TestNotifyingListPropertyStillRegistersDiffs:
    def test_append_registers_a_diff_despite_a_swallowed_fault(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-notify-append"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a"])
        meta = _stored_meta(fake_store, actor_id, name)
        meta["count_hint"] = 1
        fake_store[(actor_id, _meta_name(name))] = json.dumps(meta)

        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        inner = ListProperty(actor_id=actor_id, name=name, config=object())
        actor = Mock()
        notifying = NotifyingListProperty(inner, name, actor)

        notifying.append("b")

        actor.register_diffs.assert_called_once()
        diff = json.loads(actor.register_diffs.call_args.kwargs["blob"])
        assert diff["operation"] == "append"

    def test_pop_returns_the_item_and_registers_a_diff(self, monkeypatch, fake_store):
        actor_id = "actor-committed-notify-pop"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        inner = ListProperty(actor_id=actor_id, name=name, config=object())
        actor = Mock()
        notifying = NotifyingListProperty(inner, name, actor)

        assert notifying.pop() == "b"
        actor.register_diffs.assert_called_once()
        diff = json.loads(actor.register_diffs.call_args.kwargs["blob"])
        assert diff["operation"] == "pop"

    def test_remove_where_registers_one_diff_per_removed_item(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-committed-notify-removewhere"
        name = "notes"
        seed = [{"id": 1}, {"id": 1}, {"id": 1}]
        _seed_v2_list(fake_store, actor_id, name, seed)
        fake_db = _MetaFaultPropertyDb(fake_store, fail_ops={"set_if_value_equals"})
        _patch_get_property(monkeypatch, lambda config: fake_db)

        inner = ListProperty(actor_id=actor_id, name=name, config=object())
        actor = Mock()
        notifying = NotifyingListProperty(inner, name, actor)

        assert notifying.remove_where("id", 1) == 3
        assert actor.register_diffs.call_count == 3


class TestExistingRegressionsStayGreen:
    """Named in the plan as pins that must not move: a pre-existing
    concurrent-delete-then-append test, and the full CAS/notification
    suites -- covered by running those files directly, not re-asserted
    here. This class documents the pointer."""

    def test_pointer_only(self):
        pytest.importorskip("tests.test_property_list_integrity")
        pytest.importorskip("tests.test_v2_metadata_cas")
        pytest.importorskip("tests.test_property_list_notifications")
