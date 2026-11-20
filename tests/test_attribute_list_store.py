"""``AttributeListStore``: the attribute lists of one bucket
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 2), on the
in-memory attribute backend."""

import ast
import pathlib
from typing import Any
from unittest.mock import MagicMock

import pytest

from actingweb import attribute_list_store
from actingweb.attribute_list import ListAttribute
from actingweb.attribute_list_store import AttributeListStore
from tests.mcp_token_double import MemoryStore, make_config
from tests.test_attribute_list import ACTOR, BUCKET, _counting, _lst, _plant_old


@pytest.fixture
def env() -> tuple[Any, MemoryStore]:
    return make_config()


def _store(config: Any, bucket: str = BUCKET) -> AttributeListStore:
    return AttributeListStore(actor_id=ACTOR, bucket=bucket, config=config)


class TestInitialisation:
    def test_without_actor_or_bucket_or_config_there_is_nothing(self, env):
        config, _ = env
        for store in (
            AttributeListStore(actor_id=None, bucket=BUCKET, config=config),
            AttributeListStore(actor_id=ACTOR, bucket=None, config=config),
            AttributeListStore(actor_id=ACTOR, bucket=BUCKET, config=None),
        ):
            assert store.list_all() == []
            assert store.exists("x") is False

    def test_getattr_needs_actor_and_bucket(self, env):
        config, _ = env
        with pytest.raises(RuntimeError, match="actor_id"):
            AttributeListStore(actor_id=None, bucket=BUCKET, config=config).notes  # noqa: B018
        with pytest.raises(RuntimeError, match="bucket"):
            AttributeListStore(actor_id=ACTOR, bucket=None, config=config).notes  # noqa: B018


_NAMES = ["plain", "a:b", "ends-meta", "x-1", "x", "Zed", "has space", "ünï"]


class TestExistsAndListAll:
    def test_a_mix_of_layouts_and_awkward_names(self, env):
        config, store = env
        for name in _NAMES:
            _lst(config, name).extend(["i1", "i2"])
        _plant_old(store, "old", ["o"])
        _plant_old(store, "old:child", ["c"])
        _plant_old(store, "empty_old", [])
        store.bucket(ACTOR, BUCKET)["scalar"] = {"data": {"v": 1}}
        store.bucket(ACTOR, BUCKET)["list:stray-scalar"] = {"data": {"v": 2}}
        expected = sorted([*_NAMES, "old", "old:child", "empty_old"])
        assert _store(config).list_all() == expected
        for name in expected:
            assert _store(config).exists(name), name
        assert not _store(config).exists("scalar")
        assert not _store(config).exists("nope")

    def test_an_empty_list_is_listed_and_a_bucket_of_scalars_is_not(self, env):
        config, store = env
        _lst(config, "e").set_description("only metadata")
        store.bucket(ACTOR, BUCKET)["s"] = {"data": {"v": 1}}
        assert _store(config).list_all() == ["e"]

    def test_lists_of_another_bucket_are_not_listed(self, env):
        config, _ = env
        _lst(config, "mine").append("a")
        _lst(config, "theirs", bucket="other").append("b")
        assert _store(config).list_all() == ["mine"]
        assert _store(config, "other").list_all() == ["theirs"]

    def test_the_walk_reads_per_list_not_per_item(self, env):
        config, store = env
        for name in ("a", "b", "c"):
            _lst(config, name).extend(list(range(200)))
        counts = _counting(config, store)
        assert _store(config).list_all() == ["a", "b", "c"]
        assert counts.get("get_bucket", 0) == 0
        assert counts.get("get_attr_range", 0) == 0
        assert counts.get("get_last_attr_in_range", 0) <= 3 * 2 + 1

    def test_a_fault_raises_when_strict(self, env):
        from actingweb.db.exceptions import DbError

        config, _ = env
        _lst(config, "a").append("x")
        base = config.DbAttribute.DbAttribute

        class Faulty(base):  # type: ignore[misc,valid-type]
            def get_last_attr_in_range(self, *a: Any, **k: Any) -> Any:
                raise DbError("throttled")

        config.DbAttribute.DbAttribute = Faulty
        with pytest.raises(DbError):
            _store(config).list_all(strict=True)

    def test_list_all_raises_on_a_fault(self, env):
        """AC-44 (4.0): raises by default, as PropertyListStore.list_all()
        does; ``strict`` is an accepted no-op keyword."""
        from actingweb.db.exceptions import DbError

        config, _ = env
        _lst(config, "a").append("x")
        base = config.DbAttribute.DbAttribute

        class Faulty(base):  # type: ignore[misc,valid-type]
            def get_last_attr_in_range(self, *a: Any, **k: Any) -> Any:
                raise DbError("throttled")

        config.DbAttribute.DbAttribute = Faulty
        with pytest.raises(DbError):
            _store(config).list_all()
        with pytest.raises(DbError):
            _store(config).list_all(strict=False)

    def test_list_all_never_reads_a_whole_bucket(self):
        """A source guard beside the existing ones: no get_bucket() in the
        store module (a replica bucket can be large)."""
        path = pathlib.Path(attribute_list_store.__file__)
        tree = ast.parse(path.read_text(), filename=str(path))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "get_bucket" not in called


class TestGetAndGetattr:
    @pytest.mark.parametrize("name", ["exists", "__dict__", "_x", "list_all"])
    def test_get_reaches_any_name(self, env, name):
        config, _ = env
        lst = _store(config).get(name)
        assert isinstance(lst, ListAttribute) and lst.name == name
        lst.append("v")
        assert _store(config).get(name).to_list() == ["v"]

    def test_getattr_refuses_private_names(self, env):
        config, _ = env
        with pytest.raises(AttributeError):
            _store(config)._x  # noqa: B018

    def test_getattr_refuses_a_new_name_with_a_control_character(self, env):
        config, _ = env
        with pytest.raises(ValueError, match="control character"):
            getattr(_store(config), "bad\nname")

    def test_getattr_reaches_an_existing_name_with_a_control_character(self, env):
        config, store = env
        _plant_old(store, "bad\nname", ["x"])
        assert getattr(_store(config), "bad\nname").to_list() == ["x"]

    def test_each_access_is_a_fresh_instance(self, env):
        config, _ = env
        store = _store(config)
        assert store.notes is not store.notes


class TestRows:
    def test_list_prefix_with_rows_scopes_names_and_rows(self, env):
        config, _ = env
        _lst(config, "memory_a").extend(["1"])
        _lst(config, "memory_b").extend(["2"])
        _lst(config, "other").extend(["3"])
        names, rows = _store(config).list_prefix_with_rows("memory_")
        assert sorted(names) == ["memory_a", "memory_b"]
        assert all(r.startswith("list:memory_") for r in rows)
        fresh = _store(config).get("memory_a")
        assert fresh.to_list_from_rows(rows) == ["1"]
        with pytest.raises(ValueError):
            _store(config).list_prefix_with_rows("")

    def test_list_all_with_rows(self, env):
        config, _ = env
        _lst(config, "a").extend(["x", "y"])
        names, rows = _store(config).list_all_with_rows()
        assert names == ["a"]
        assert _store(config).get("a").to_list_from_rows(rows) == ["x", "y"]


class TestActorInterface:
    def test_attribute_lists_round_trip(self, env):
        from actingweb.interface.actor_interface import ActorInterface

        config, store = env
        core = MagicMock()
        core.id = ACTOR
        core.config = config
        actor = ActorInterface(core)
        lists = actor.attribute_lists("app_state")
        assert isinstance(lists, AttributeListStore)
        lists.get("notes").extend([{"id": 1}, {"id": 2}])
        assert actor.attribute_lists("app_state").notes.to_list() == [
            {"id": 1},
            {"id": 2},
        ]
        assert actor.attribute_lists("app_state").list_all() == ["notes"]
        assert store.rows.get(f"{ACTOR}:app_state")

    def test_the_store_is_exported(self):
        import actingweb.interface as interface

        assert interface.AttributeListStore is AttributeListStore


class TestBelow:
    @pytest.mark.parametrize(
        "name", ["list:a", "list:a\x00", "list:a\ue000", "list:é", "list:a\U0010ffff"]
    )
    def test_the_bound_is_below_and_valid(self, name):
        from actingweb.attribute_list_store import _below

        bound = _below(name)
        assert bound < name
        bound.encode("utf-8")  # no lone surrogate
