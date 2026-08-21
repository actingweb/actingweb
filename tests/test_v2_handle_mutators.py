"""Phase 10 of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): value-addressed handle mutators
(``delete_by_handle``/``update_by_handle``) and the universal ``_where``
wrappers (``remove_where``/``update_where``) built on top of them.

Uses the dict-backed fakes from ``test_property_list_integrity.py``.
"""

import json

import pytest

from actingweb.property_list import ListItemHandle, ListProperty
from tests.test_property_list_integrity import (
    CountingPropertyDb,
    FakePropertyDb,
    _patch_get_property,
    _seed_list,
    _seed_v2_list,
)


@pytest.fixture
def fake_store():
    return {}


class TestHandleMutatorsAreV2Only:
    def test_delete_by_handle_raises_on_v1_naming_migrate_to_v2(self, monkeypatch, fake_store):
        actor_id = "actor-handle-v1"
        name = "items"
        _seed_list(fake_store, actor_id, name, ["a", "b"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        handle = ListItemHandle(rank="a0", raw_value=json.dumps("a"))
        with pytest.raises(ValueError, match="migrate_to_v2"):
            lst.delete_by_handle(handle)

    def test_update_by_handle_raises_on_v1_naming_migrate_to_v2(self, monkeypatch, fake_store):
        actor_id = "actor-handle-v1b"
        name = "items"
        _seed_list(fake_store, actor_id, name, ["a", "b"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        handle = ListItemHandle(rank="a0", raw_value=json.dumps("a"))
        with pytest.raises(ValueError, match="migrate_to_v2"):
            lst.update_by_handle(handle, "z")

    def test_delete_by_handle_succeeds_on_v2(self, monkeypatch, fake_store):
        actor_id = "actor-handle-v2"
        name = "items"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        handle, item = lst.items_with_handles()[1]
        assert item == "b"
        assert lst.delete_by_handle(handle) is True
        assert lst.to_list() == ["a", "c"]

    def test_update_by_handle_succeeds_on_v2(self, monkeypatch, fake_store):
        actor_id = "actor-handle-v2b"
        name = "items"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        handle, item = lst.items_with_handles()[1]
        assert item == "b"
        assert lst.update_by_handle(handle, "B") is True
        assert lst.to_list() == ["a", "B", "c"]


class TestHandleMutatorsAreSingleShotNoRetry:
    """A failed condition IS the answer -- returned as False, never
    retried. Pin this by making the underlying write fail unconditionally
    and confirming there is exactly ONE attempt (no retry loop consuming
    extra calls)."""

    def test_delete_by_handle_returns_false_once_no_retry(self, monkeypatch, fake_store):
        actor_id = "actor-handle-race"
        name = "items"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = CountingPropertyDb(fake_store)

        call_count = {"n": 0}
        orig = fake_db.delete_if_value_equals

        def counting_delete(*args, **kwargs):
            call_count["n"] += 1
            return orig(*args, **kwargs)

        fake_db.delete_if_value_equals = counting_delete
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        handle, _ = lst.items_with_handles()[0]
        # Mutate the row out from under the handle before using it.
        real_db = FakePropertyDb(fake_store)
        real_db.set_if_value_equals(
            actor_id=actor_id,
            name=lst._v2_item_name(handle.rank),
            expected=handle.raw_value,
            value=json.dumps("changed"),
        )

        assert lst.delete_by_handle(handle) is False
        assert call_count["n"] == 1
        assert lst.to_list() == ["changed", "b"]

    def test_update_by_handle_returns_false_once_no_retry(self, monkeypatch, fake_store):
        actor_id = "actor-handle-race2"
        name = "items"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = CountingPropertyDb(fake_store)

        call_count = {"n": 0}
        orig = fake_db.set_if_value_equals

        def counting_set(*args, **kwargs):
            call_count["n"] += 1
            return orig(*args, **kwargs)

        fake_db.set_if_value_equals = counting_set
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        handle, _ = lst.items_with_handles()[0]
        fake_store[(actor_id, lst._v2_item_name(handle.rank))] = json.dumps("changed")

        assert lst.update_by_handle(handle, "new") is False
        # One call for the item write itself; _v2_touch_metadata() is
        # never reached on a failed condition, so no second
        # set_if_value_equals from that path either.
        assert call_count["n"] == 1
        assert lst.to_list() == ["changed", "b"]


class TestHandleGenerationBoundary:
    """A handle is only valid within the list's current 'generation' --
    delete() followed by append() starts a brand new rank sequence, and
    generate_n_keys_between(None, None, n) is deterministic, so a fresh
    list's first rank collides in NAME (not identity) with the deleted
    list's first rank. A stale handle must fail, never silently address
    the wrong (new) item."""

    def test_stale_handle_fails_after_delete_and_recreate(self, monkeypatch, fake_store):
        actor_id = "actor-handle-gen"
        name = "items"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        stale_handle, _ = lst.items_with_handles()[0]
        lst.delete()
        lst.append("fresh")

        fresh_handle, fresh_item = lst.items_with_handles()[0]
        assert fresh_handle.rank == stale_handle.rank  # same rank, new generation
        assert fresh_item == "fresh"

        # The stale handle's raw bytes ("a"'s encoding) no longer match
        # what is actually stored at that rank ("fresh"'s encoding) --
        # the condition fails, exactly as it should.
        assert lst.delete_by_handle(stale_handle) is False
        assert lst.to_list() == ["fresh"]


class TestRemoveWhereQueryCost:
    def test_remove_where_issues_one_get_range_and_k_point_deletes(self, monkeypatch, fake_store):
        actor_id = "actor-removewhere-cost"
        name = "items"
        items = [{"id": i, "grp": "x" if i % 5 == 0 else "y"} for i in range(50)]
        _seed_v2_list(fake_store, actor_id, name, items)
        fake_db = CountingPropertyDb(fake_store)
        delete_calls = {"n": 0}
        orig_delete = fake_db.delete_if_value_equals

        def counting_delete(*args, **kwargs):
            delete_calls["n"] += 1
            return orig_delete(*args, **kwargs)

        fake_db.delete_if_value_equals = counting_delete
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        removed = lst.remove_where("grp", "x")

        expected_matches = sum(1 for i in range(50) if i % 5 == 0)
        assert removed == expected_matches
        assert fake_db.range_call_count == 1
        assert delete_calls["n"] == expected_matches
        assert len(lst.to_list()) == 50 - expected_matches


class TestRemoveWhereAndUpdateWhereBehavior:
    def test_remove_where_first_only_removes_exactly_one(self, monkeypatch, fake_store):
        actor_id = "actor-removewhere-first"
        name = "items"
        items = [{"id": 1, "tag": "a"}, {"id": 2, "tag": "a"}, {"id": 3, "tag": "b"}]
        _seed_v2_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        removed = lst.remove_where("tag", "a", first_only=True)

        assert removed == 1
        remaining_ids = [item["id"] for item in lst.to_list()]
        assert remaining_ids in ([2, 3], [1, 3])

    def test_remove_where_no_match_returns_zero(self, monkeypatch, fake_store):
        actor_id = "actor-removewhere-none"
        name = "items"
        items = [{"id": 1, "tag": "a"}]
        _seed_v2_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.remove_where("tag", "does-not-exist") == 0
        assert lst.to_list() == items

    def test_update_where_first_only_updates_exactly_one(self, monkeypatch, fake_store):
        actor_id = "actor-updatewhere-first"
        name = "items"
        items = [{"id": 1, "tag": "a"}, {"id": 2, "tag": "a"}]
        _seed_v2_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        updated = lst.update_where("tag", "a", {"id": 99, "tag": "z"}, first_only=True)

        assert updated == 1
        tags = [item["tag"] for item in lst.to_list()]
        assert tags.count("z") == 1
        assert tags.count("a") == 1

    def test_update_where_no_match_returns_zero(self, monkeypatch, fake_store):
        actor_id = "actor-updatewhere-none"
        name = "items"
        items = [{"id": 1, "tag": "a"}]
        _seed_v2_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        assert lst.update_where("tag", "nope", {"id": 2}) == 0
        assert lst.to_list() == items

    def test_update_where_updates_all_matches_by_default(self, monkeypatch, fake_store):
        actor_id = "actor-updatewhere-all"
        name = "items"
        items = [{"id": 1, "tag": "a"}, {"id": 2, "tag": "a"}, {"id": 3, "tag": "b"}]
        _seed_v2_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        updated = lst.update_where("tag", "a", {"tag": "z"})

        assert updated == 2
        tags = sorted(item["tag"] for item in lst.to_list())
        assert tags == ["b", "z", "z"]


class TestRemoveWhereV1DescendingOrder:
    """Ascending index order would shift every later match onto the wrong
    row as each earlier delete closes a hole -- descending order is the
    only correct choice for a multi-match v1 delete."""

    def test_v1_remove_where_removes_all_matches_correctly(self, monkeypatch, fake_store):
        actor_id = "actor-removewhere-v1"
        name = "items"
        items = [
            {"id": 0, "tag": "x"},
            {"id": 1, "tag": "y"},
            {"id": 2, "tag": "x"},
            {"id": 3, "tag": "y"},
            {"id": 4, "tag": "x"},
        ]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        removed = lst.remove_where("tag", "x")

        assert removed == 3
        assert [item["id"] for item in lst.to_list()] == [1, 3]

    def test_v1_update_where_updates_all_matches_correctly(self, monkeypatch, fake_store):
        actor_id = "actor-updatewhere-v1"
        name = "items"
        items = [
            {"id": 0, "tag": "x"},
            {"id": 1, "tag": "y"},
            {"id": 2, "tag": "x"},
        ]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        updated = lst.update_where("tag", "x", {"id": -1, "tag": "z"})

        assert updated == 2
        assert [item["tag"] for item in lst.to_list()] == ["z", "y", "z"]


class TestDeleteByHandleMaintainsCountHint:
    def test_delete_by_handle_decrements_count_hint(self, monkeypatch, fake_store):
        actor_id = "actor-handle-hint"
        name = "items"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        meta_key = (actor_id, f"list:{name}-meta")
        meta = json.loads(fake_store[meta_key])
        meta["count_hint"] = 3
        fake_store[meta_key] = json.dumps(meta)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        handle, _ = lst.items_with_handles()[0]
        lst.delete_by_handle(handle)

        meta = json.loads(fake_store[(actor_id, f"list:{name}-meta")])
        assert meta["count_hint"] == 2


class TestRemoveWhereKeepsRankCacheInSyncOnTheSameInstance:
    """items_with_handles() (via _v2_load_full()) warms self._v2_rank_cache
    as a side effect. Each delete_by_handle() inside remove_where()'s own
    loop must keep that cache in sync, or a mutator called afterwards on
    the SAME instance (len(), __setitem__, insert(), pop()) resolves
    positions against a cache that still contains deleted ranks."""

    def test_len_and_to_list_agree_immediately_after_multi_match_remove_where(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-removewhere-cache"
        name = "items"
        items = [{"id": i, "tag": "x" if i % 2 == 0 else "y"} for i in range(10)]
        _seed_v2_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        removed = lst.remove_where("tag", "x")

        assert removed == 5
        assert len(lst) == len(lst.to_list()) == 5
        assert all(item["tag"] == "y" for item in lst.to_list())
