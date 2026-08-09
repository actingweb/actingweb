"""
Regression tests for the hot-path N+1 fixes.

The property read path used to re-read every property individually right
after bulk-reading them all, re-read list metadata rows the bulk read
already returned, pay a list-collision GetItem on every repeat write, and
load the actor's _internal attribute bucket eagerly (twice) on every Actor
construction. These tests pin the fixed read counts.
"""

import uuid
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _require_dynamodb():
    import os

    if os.getenv("DATABASE_BACKEND", "dynamodb") != "dynamodb":
        pytest.skip("DynamoDB-only test")


@pytest.fixture
def config():
    from actingweb.config import Config

    return Config(database="dynamodb")


@pytest.fixture
def actor_id():
    return f"nplus1-{uuid.uuid4()}"


@pytest.fixture
def populated_actor(config, actor_id):
    """Actor with 5 simple properties; cleans up after the test."""
    from actingweb import property as property_module

    store = property_module.PropertyStore(actor_id=actor_id, config=config)
    for i in range(5):
        setattr(store, f"prop{i}", f"value{i}")
    yield actor_id
    from actingweb.db import get_property_list

    lst = get_property_list(config)
    lst.fetch(actor_id=actor_id)
    lst.delete()


class TestPropertyStoreBulkReads:
    def _interface_store(self, config, actor_id):
        from actingweb import property as property_module
        from actingweb.interface.property_store import PropertyStore

        core = property_module.PropertyStore(actor_id=actor_id, config=config)
        return PropertyStore(core), core

    def test_to_dict_is_single_bulk_read(self, config, populated_actor):
        store, core = self._interface_store(config, populated_actor)
        with (
            mock.patch.object(type(core), "get_all", wraps=core.get_all) as get_all_spy,
            mock.patch.object(
                type(core),
                "__getattr__",
                side_effect=AssertionError("per-key read on the bulk path"),
            ),
        ):
            result = store.to_dict()
        assert result == {f"prop{i}": f"value{i}" for i in range(5)}
        assert get_all_spy.call_count == 1

    def test_items_and_values_are_bulk_reads(self, config, populated_actor):
        store, core = self._interface_store(config, populated_actor)
        with mock.patch.object(
            type(core), "get_all", wraps=core.get_all
        ) as get_all_spy:
            items = dict(store.items())
            values = sorted(store.values())
        assert items == {f"prop{i}": f"value{i}" for i in range(5)}
        assert values == sorted(f"value{i}" for i in range(5))
        # one bulk read per bulk operation, none per key
        assert get_all_spy.call_count == 2

    def test_repeat_write_skips_collision_check(self, config, populated_actor):
        from actingweb import property as property_module

        core = property_module.PropertyStore(actor_id=populated_actor, config=config)
        # Load the property into the instance first
        assert core["prop0"] == "value0"
        with mock.patch.object(
            property_module.PropertyListStore, "exists"
        ) as exists_spy:
            core["prop0"] = "new-value"
        exists_spy.assert_not_called()

    def test_first_write_still_collision_checks(self, config, actor_id):
        from actingweb import property as property_module

        core = property_module.PropertyStore(actor_id=actor_id, config=config)
        with mock.patch.object(
            property_module.PropertyListStore, "exists", return_value=True
        ):
            with pytest.raises(ValueError, match="list with this name"):
                core["newprop"] = "value"


class TestListPropertyPriming:
    def test_primed_list_serves_from_rows(self, config, actor_id):
        from actingweb.db import get_property_list
        from actingweb.db.dynamodb.property import DbProperty
        from actingweb.property_list import ListProperty

        lst = ListProperty(actor_id, "mylist", config)
        lst.append({"a": 1})
        lst.append("plain string")
        lst.append([1, 2, 3])
        try:
            rows = (
                get_property_list(config).fetch_all_including_lists(actor_id=actor_id)
                or {}
            )
            fresh = ListProperty(actor_id, "mylist", config)
            fresh.prime_from_rows(rows)

            # v2 list: priming must hydrate both the metadata cache AND the
            # rank-key cache from the bulk dump -- len()/to_list_from_rows()
            # after priming must issue ZERO further get_range()/get() calls
            # (the whole point of prime_from_rows() -- see Phase 4 of
            # thoughts/plans/2026-08-08-property-list-index-integrity.md).
            with (
                mock.patch.object(
                    DbProperty,
                    "get_range",
                    side_effect=AssertionError("get_range() after priming"),
                ),
                mock.patch.object(
                    DbProperty,
                    "get",
                    side_effect=AssertionError("get() after priming"),
                ),
            ):
                assert len(fresh) == 3
                assert fresh.to_list_from_rows(rows) == [
                    {"a": 1},
                    "plain string",
                    [1, 2, 3],
                ]

            # Items served from rows match the per-item read path exactly
            assert fresh.to_list_from_rows(rows) == lst.to_list()
        finally:
            lst.delete()

    def test_to_list_is_one_range_query(self, config, actor_id):
        """v2's whole storage-format point: to_list() on an N-item list is
        ONE range query, not N GetItems."""
        from actingweb.db.dynamodb.property import DbProperty
        from actingweb.property_list import ListProperty

        lst = ListProperty(actor_id, "querycountlist", config)
        for i in range(20):
            lst.append(f"item-{i}")
        try:
            fresh = ListProperty(actor_id, "querycountlist", config)
            original_get_range = DbProperty.get_range
            call_count = [0]

            def _counting_get_range(self, *args, **kwargs):
                call_count[0] += 1
                return original_get_range(self, *args, **kwargs)

            with mock.patch.object(DbProperty, "get_range", _counting_get_range):
                result = fresh.to_list()
            assert result == [f"item-{i}" for i in range(20)]
            assert call_count[0] == 1
        finally:
            lst.delete()

    def test_unprimed_behaviour_unchanged(self, config, actor_id):
        from actingweb.property_list import ListProperty

        lst = ListProperty(actor_id, "otherlist", config)
        lst.append("x")
        try:
            fresh = ListProperty(actor_id, "otherlist", config)
            fresh.prime_from_rows({})  # nothing to prime — lazy path applies
            assert fresh.to_list() == ["x"]
        finally:
            lst.delete()


class TestInternalStoreLazy:
    def test_construction_does_not_query_bucket(self, config, actor_id):
        from actingweb import attribute

        with mock.patch.object(
            attribute.Attributes,
            "get_bucket",
            side_effect=AssertionError("bucket loaded during construction"),
        ):
            attribute.InternalStore(actor_id=actor_id, config=config)

    def test_first_access_loads_bucket_once(self, config, actor_id):
        from actingweb import attribute

        store = attribute.InternalStore(actor_id=actor_id, config=config)
        with mock.patch.object(
            attribute.Attributes, "get_bucket", return_value={"em": {"data": "x@y.z"}}
        ) as spy:
            assert store.em == "x@y.z"
            assert store.missing is None
        assert spy.call_count == 1

    def test_write_then_read_sees_full_bucket(self, config, actor_id):
        from actingweb import attribute

        # Seed the bucket through one store
        seed = attribute.InternalStore(actor_id=actor_id, config=config)
        seed.existing = "seeded"
        # A fresh store that WRITES first must still see other attributes
        # (the load-before-write rule; a partial-cache bug would lose them)
        fresh = attribute.InternalStore(actor_id=actor_id, config=config)
        fresh.other = "written"
        assert fresh.existing == "seeded"
        # Cleanup
        fresh.existing = None
        fresh.other = None


class TestNegativePermissionCache:
    def test_missing_override_cached(self, config):
        from actingweb.trust_permissions import TrustPermissionStore

        store = TrustPermissionStore(config)
        fake_bucket = mock.MagicMock()
        fake_bucket.get_attr.return_value = None
        with mock.patch.object(
            TrustPermissionStore, "_get_permissions_bucket", return_value=fake_bucket
        ):
            assert store.get_permissions("actor-x", "peer-y") is None
            assert store.get_permissions("actor-x", "peer-y") is None
        # Second call must be served from the cache
        assert fake_bucket.get_attr.call_count == 1
