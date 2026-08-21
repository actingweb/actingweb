"""Phase 7 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): value-addressed reads.

``find()``/``find_all()`` are ergonomics, not a cost fix -- a value-
addressed read was already one query via ``to_list()`` plus an in-memory
scan, but writing that scan by hand is where an index escapes into a
later write. ``items_with_handles()`` is the read half of Phase 10's
handle-based writers: an opaque, single-use, always-strongly-consistent
read receipt that a later phase's ``update_by_handle()``/
``delete_by_handle()`` condition their writes on.

Uses the dict-backed ``FakePropertyDb`` fake and ``_seed_v2_list``/
``_seed_list`` helpers from ``test_property_list_integrity.py``.
"""

import json

import pytest

from actingweb.property_list import ListItemHandle, ListProperty
from tests.test_property_list_integrity import (
    FakePropertyDb,
    _patch_get_property,
    _seed_list,
    _seed_v2_list,
)


@pytest.fixture
def fake_store():
    return {}


def _seed_dict_items(fake_store, actor_id, name, items, v2=True):
    seeder = _seed_v2_list if v2 else _seed_list
    seeder(fake_store, actor_id, name, items)


class TestFindAndFindAll:
    @pytest.mark.parametrize("v2", [True, False])
    def test_find_returns_first_match_same_result_both_formats(
        self, monkeypatch, fake_store, v2
    ):
        actor_id = f"actor-find-{v2}"
        name = "tasks"
        items = [
            {"id": "a", "title": "first"},
            {"id": "b", "title": "second"},
            {"id": "a", "title": "duplicate-a"},
        ]
        _seed_dict_items(fake_store, actor_id, name, items, v2=v2)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.find("id", "a") == {"id": "a", "title": "first"}
        assert lst.find("id", "missing") is None

    @pytest.mark.parametrize("v2", [True, False])
    def test_find_all_returns_every_match_same_result_both_formats(
        self, monkeypatch, fake_store, v2
    ):
        actor_id = f"actor-findall-{v2}"
        name = "tasks"
        items = [
            {"id": "a", "title": "first"},
            {"id": "b", "title": "second"},
            {"id": "a", "title": "duplicate-a"},
        ]
        _seed_dict_items(fake_store, actor_id, name, items, v2=v2)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.find_all("id", "a") == [
            {"id": "a", "title": "first"},
            {"id": "a", "title": "duplicate-a"},
        ]
        assert lst.find_all("id", "missing") == []

    def test_find_on_non_dict_items_does_not_raise(self, monkeypatch, fake_store):
        actor_id = "actor-find-nondict"
        name = "mixed"
        _seed_v2_list(fake_store, actor_id, name, ["plain-string", 42, {"id": "x"}])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.find("id", "x") == {"id": "x"}
        assert lst.find_all("id", "x") == [{"id": "x"}]
        assert lst.find("id", "plain-string") is None

    def test_find_missing_key_never_matches_none_value(self, monkeypatch, fake_store):
        """A row lacking `identity_key` entirely is not the same as one
        that has the field set to None."""
        actor_id = "actor-find-missing-key"
        name = "mixed"
        _seed_v2_list(fake_store, actor_id, name, [{"other": 1}, {"id": None}])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.find("id", None) == {"id": None}
        assert lst.find_all("id", None) == [{"id": None}]

    def test_find_honours_consistent_parameter(self, monkeypatch, fake_store):
        from tests.test_v2_consistent_read import RecordingPropertyDb

        actor_id = "actor-find-consistent"
        name = "tasks"
        _seed_v2_list(fake_store, actor_id, name, [{"id": "a"}])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        lst.find("id", "a", consistent=False)
        assert fake_db.consistent_read_calls == [False]

        fake_db.consistent_read_calls = []
        lst.find_all("id", "a", consistent=False)
        assert fake_db.consistent_read_calls == [False]


class TestItemsWithHandles:
    def test_issues_exactly_one_get_range(self, monkeypatch, fake_store):
        from tests.test_property_list_integrity import CountingPropertyDb

        actor_id = "actor-handles-count"
        name = "tasks"
        _seed_v2_list(fake_store, actor_id, name, [{"id": "a"}, {"id": "b"}])
        fake_db = CountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        fake_db.range_call_count = 0
        pairs = lst.items_with_handles()
        assert fake_db.range_call_count == 1
        assert [item for _, item in pairs] == [{"id": "a"}, {"id": "b"}]

    def test_raises_on_v1_naming_migrate_to_v2(self, monkeypatch, fake_store):
        actor_id = "actor-handles-v1"
        name = "tasks"
        _seed_list(fake_store, actor_id, name, [{"id": "a"}])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(ValueError, match="migrate_to_v2"):
            lst.items_with_handles()

    def test_handle_raw_value_round_trips_for_delete_if_value_equals(
        self, monkeypatch, fake_store
    ):
        """A handle's raw_value is the exact bytes stored, not a
        re-encoding -- what delete_if_value_equals()/set_if_value_equals()
        will require."""
        actor_id = "actor-handles-roundtrip"
        name = "tasks"
        _seed_v2_list(fake_store, actor_id, name, [{"id": "a", "n": 1}])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        (handle, item) = lst.items_with_handles()[0]
        assert item == {"id": "a", "n": 1}
        stored_raw = fake_store[(actor_id, f"list:{name}-#{handle.rank}")]
        assert handle.raw_value == stored_raw
        assert json.loads(handle.raw_value) == item

    def test_handle_repr_omits_raw_value(self):
        handle = ListItemHandle(rank="a0", raw_value='{"secret": "do-not-print"}')
        assert "do-not-print" not in repr(handle)
        assert "a0" in repr(handle)

    def test_always_strongly_consistent_regardless_of_default(
        self, monkeypatch, fake_store
    ):
        from tests.test_v2_consistent_read import RecordingPropertyDb

        actor_id = "actor-handles-consistent"
        name = "tasks"
        _seed_v2_list(fake_store, actor_id, name, [{"id": "a"}])
        fake_db = RecordingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        lst.items_with_handles()
        assert fake_db.consistent_read_calls == [True]


class TestReachableThroughTheFluentInterface:
    """Phase 2's allowlist regression: a method added to
    NotifyingListProperty without a matching entry on
    _PermissionEnforcingListView is otherwise unreachable through
    actor.property_lists.<name>, the only path the fluent API offers."""

    def test_find_find_all_and_items_with_handles_reach_notifying_list_property(
        self,
    ):
        from actingweb.interface.property_store import NotifyingListProperty

        for method in ("find", "find_all", "items_with_handles"):
            assert hasattr(NotifyingListProperty, method), (
                f"NotifyingListProperty must delegate {method}()"
            )

    def test_phase_10_handle_and_where_mutators_reach_both_wrapper_layers(self):
        """Phase 10's delete_by_handle/update_by_handle/remove_where/
        update_where -- same reachability contract, both wrappers."""
        from actingweb.interface.authenticated_views import (
            _PermissionEnforcingListView,
        )
        from actingweb.interface.property_store import NotifyingListProperty

        for method in (
            "delete_by_handle",
            "update_by_handle",
            "remove_where",
            "update_where",
        ):
            assert hasattr(NotifyingListProperty, method), (
                f"NotifyingListProperty must delegate {method}()"
            )
            assert hasattr(_PermissionEnforcingListView, method), (
                f"_PermissionEnforcingListView must delegate {method}()"
            )

    def test_permission_enforcing_view_still_matches_notifying_list_property(self):
        from actingweb.interface.authenticated_views import (
            _PermissionEnforcingListView,
        )
        from actingweb.interface.property_store import NotifyingListProperty

        def public_methods(cls):
            return {
                name
                for name in dir(cls)
                if not name.startswith("_") or name in ("__len__", "__getitem__")
            }

        notifying_surface = public_methods(NotifyingListProperty)
        view_surface = public_methods(_PermissionEnforcingListView)
        assert notifying_surface <= view_surface, (
            f"Missing from _PermissionEnforcingListView: "
            f"{notifying_surface - view_surface}"
        )
