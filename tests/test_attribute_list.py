"""``ListAttribute``: the list core over an attribute bucket
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 2), on the
in-memory attribute backend of ``tests/mcp_token_double.py``.

Old-layout rows (``list:{name}:meta`` / ``list:{name}:{index}``) are planted
the way pre-3.16 code wrote them: the item itself as the attribute's data,
and a metadata object with ``length``.
"""

import copy
import json
import math
from typing import Any

import pytest

from actingweb.attribute_list import (
    CLEANUP_MARKER,
    OLD_LAYOUT,
    AttributeListStorage,
    ListAttribute,
)
from actingweb.db.exceptions import DbError
from actingweb.list_core import (
    ListCore,
    ListCorruptionError,
    ListLayoutConflictError,
    ListNameTakenError,
)
from tests.mcp_token_double import MemoryDbAttribute, MemoryStore, make_config

ACTOR = "a" * 32
BUCKET = "remote:" + "b" * 32


@pytest.fixture
def env() -> tuple[Any, MemoryStore]:
    return make_config()


def _rows(store: MemoryStore, bucket: str = BUCKET) -> dict[str, Any]:
    return {n: r["data"] for n, r in store.rows.get(f"{ACTOR}:{bucket}", {}).items()}


def _plant_old(
    store: MemoryStore,
    name: str,
    items: list[Any],
    *,
    length: int | None = None,
    bucket: str = BUCKET,
    meta: dict[str, Any] | None = None,
) -> None:
    rows = store.bucket(ACTOR, bucket)
    rows[f"list:{name}:meta"] = {
        "data": {
            "length": len(items) if length is None else length,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-02T00:00:00",
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "desc",
            "explanation": "expl",
            **(meta or {}),
        }
    }
    for i, item in enumerate(items):
        rows[f"list:{name}:{i}"] = {"data": copy.deepcopy(item)}


def _lst(config: Any, name: str = "notes", bucket: str = BUCKET) -> ListAttribute:
    return ListAttribute(ACTOR, bucket, name, config)


def _counting(config: Any, store: MemoryStore) -> dict[str, int]:
    """Count every backend call by method name."""
    counts: dict[str, int] = {}
    base = config.DbAttribute.DbAttribute

    def wrap(name: str, fn: Any) -> Any:
        def counted(self: Any, *a: Any, **k: Any) -> Any:
            counts[name] = counts.get(name, 0) + 1
            return fn(self, *a, **k)

        return counted

    methods = {
        n: wrap(n, getattr(MemoryDbAttribute, n))
        for n in dir(MemoryDbAttribute)
        if not n.startswith("_") and callable(getattr(MemoryDbAttribute, n))
    }
    config.DbAttribute.DbAttribute = type("Counting", (base,), methods)
    return counts


_WRITES = (
    "put_attr",
    "create_attr_if_not_exists",
    "create_attrs_if_not_exist",
    "set_attr_if_data_equals",
    "delete_attr_if_data_equals",
    "delete_attrs",
    "set_attr",
    "delete_attr",
)


def _crash_after(config: Any, writes: int) -> list[int]:
    """Make the backend raise ``DbError`` on the write after ``writes``
    successful ones (one per row: a batch create counts its rows)."""
    done = [0]
    base = config.DbAttribute.DbAttribute

    def tick(n: int = 1) -> None:
        if done[0] + n > writes:
            raise DbError("injected crash")
        done[0] += n

    class Crashing(base):  # type: ignore[misc,valid-type]
        def put_attr(self, *a: Any, **k: Any) -> Any:
            tick()
            return super().put_attr(*a, **k)

        def create_attr_if_not_exists(self, *a: Any, **k: Any) -> Any:
            tick()
            return super().create_attr_if_not_exists(*a, **k)

        def create_attrs_if_not_exist(self, actor_id, bucket, rows):  # type: ignore[no-untyped-def]
            created = set()
            for name, data in rows.items():
                tick()
                if super().create_attr_if_not_exists(actor_id, bucket, name, data):
                    created.add(name)
            return created

        def set_attr_if_data_equals(self, *a: Any, **k: Any) -> Any:
            tick()
            return super().set_attr_if_data_equals(*a, **k)

        def delete_attr_if_data_equals(self, *a: Any, **k: Any) -> Any:
            tick()
            return super().delete_attr_if_data_equals(*a, **k)

        def delete_attrs(self, actor_id, bucket, names):  # type: ignore[no-untyped-def]
            for name in names:
                tick()
                super().delete_attrs(actor_id, bucket, [name])

    config.DbAttribute.DbAttribute = Crashing
    return done


# ---------------------------------------------------------------- shape


class TestShape:
    def test_it_is_the_core_over_attribute_storage(self, env):
        config, _ = env
        lst = _lst(config)
        assert isinstance(lst, ListCore)
        assert isinstance(lst._storage, AttributeListStorage)
        assert (lst.actor_id, lst.bucket, lst.name, lst.config) == (
            ACTOR,
            BUCKET,
            "notes",
            config,
        )

    def test_rows_take_the_property_layout(self, env):
        config, store = env
        _lst(config).extend(["a", "b"])
        names = set(_rows(store))
        assert "list:notes-meta" in names
        assert {n for n in names if n.startswith("list:notes-#")} and len(names) == 3
        assert all(isinstance(v, str) for v in _rows(store).values())

    def test_falsy_items_round_trip_in_order(self, env):
        config, _ = env
        items = ["0", "null", "[]", "", 0, None, [], {}, False]
        _lst(config).extend(items)
        assert _lst(config).to_list() == items

    def test_without_config_there_is_no_store(self):
        lst = ListAttribute(ACTOR, BUCKET, "notes", None)
        with pytest.raises(RuntimeError, match="No database connection"):
            lst.append("a")
        with pytest.raises(RuntimeError):
            lst.clear()

    def test_a_scalar_attribute_of_the_name_is_refused_in_attribute_wording(self, env):
        config, store = env
        store.bucket(ACTOR, BUCKET)["notes"] = {"data": {"value": 1}}
        with pytest.raises(ListNameTakenError, match="an attribute with this name"):
            _lst(config).append("a")

    def test_the_rank_cap_names_a_rebuild_for_a_replica(self, env, monkeypatch):
        from actingweb import list_core

        config, _ = env
        monkeypatch.setattr(list_core, "_V2_RANK_MAX_LEN", 2)
        lst = _lst(config)
        lst.extend(["a", "b"])
        with pytest.raises(list_core.ListRankExhaustedError, match="rebuilt"):
            for _ in range(200):
                lst.insert(1, "x")


# ---------------------------------------------------------------- old layout, read in place


_READS = {
    "len": len,
    "getitem": lambda lst: lst[1],
    "getitem_negative": lambda lst: lst[-1],
    "iterate": list,
    "to_list": lambda lst: lst.to_list(),
    "to_indexed_list": lambda lst: lst.to_indexed_list(),
    "slice": lambda lst: lst.slice(0, 2),
    "index": lambda lst: lst.index("two"),
    "count": lambda lst: lst.count("two"),
    "find": lambda lst: lst.find("id", 1),
    "find_all": lambda lst: lst.find_all("id", 1),
    "get_metadata": lambda lst: lst.get_metadata(),
    "get_description": lambda lst: lst.get_description(),
    "get_explanation": lambda lst: lst.get_explanation(),
    "storage_format": lambda lst: lst.storage_format(),
}

_OLD_ITEMS = [{"id": 1, "v": "one"}, "two", 3]


class TestOldLayoutReads:
    @pytest.mark.parametrize("read", sorted(_READS))
    def test_every_read_serves_the_old_layout_and_writes_nothing(self, env, read):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        before = copy.deepcopy(_rows(store))
        counts = _counting(config, store)
        _READS[read](_lst(config))
        assert _rows(store) == before
        assert not any(counts.get(w) for w in _WRITES), counts

    def test_the_old_layout_reads_as_its_items(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        lst = _lst(config)
        assert lst.to_list() == _OLD_ITEMS
        assert len(lst) == 3 and lst[0] == _OLD_ITEMS[0] and lst[-1] == 3
        assert lst.storage_format() == OLD_LAYOUT
        assert lst.get_metadata()["length"] == 3
        assert lst.get_description() == "desc"

    def test_a_read_then_a_mutation_converts_once(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        lst = _lst(config)
        assert lst.to_list() == _OLD_ITEMS
        lst.append(4)
        lst.append(5)
        assert _lst(config).to_list() == [*_OLD_ITEMS, 4, 5]
        assert not [n for n in _rows(store) if n.startswith("list:notes:")]

    def test_a_list_x_does_not_read_the_rows_of_a_list_x_colon_y(self, env):
        config, store = env
        _plant_old(store, "x", ["a"])
        _plant_old(store, "x:y", ["b", "c"])
        assert _lst(config, "x").to_list() == ["a"]
        _lst(config, "x").append("z")
        assert _lst(config, "x:y").to_list() == ["b", "c"]
        assert _lst(config, "x").to_list() == ["a", "z"]


# ---------------------------------------------------------------- conversion

_MUTATORS = {
    "append": lambda lst: lst.append("new"),
    "extend": lambda lst: lst.extend(["new"]),
    "insert": lambda lst: lst.insert(0, "new"),
    "setitem": lambda lst: lst.__setitem__(1, "new"),
    "delitem": lambda lst: lst.__delitem__(1),
    "pop": lambda lst: lst.pop(),
    "remove": lambda lst: lst.remove("two"),
    "append_once": lambda lst: lst.append_once("new", key="k"),
    "remove_where": lambda lst: lst.remove_where("id", 1),
    "update_where": lambda lst: lst.update_where("id", 1, {"id": 1, "v": "x"}),
    "set_description": lambda lst: lst.set_description("d2"),
    "set_explanation": lambda lst: lst.set_explanation("e2"),
}


class TestConversion:
    @pytest.mark.parametrize("mutate", sorted(_MUTATORS))
    def test_each_mutator_converts_a_healthy_list(self, env, mutate):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        _MUTATORS[mutate](_lst(config))
        names = set(_rows(store))
        assert "list:notes-meta" in names
        assert not {n for n in names if n.startswith("list:notes:")}
        fresh = _lst(config)
        assert fresh.storage_format() == 2
        meta = _rows(store)["list:notes-meta"]
        assert CLEANUP_MARKER not in meta

    def test_metadata_carries_over(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        before = _lst(config)
        assert before.get_metadata()["updated_at"] == "2025-01-02T00:00:00"
        _lst(config).append("new")
        after = _lst(config)
        assert after.get_description() == "desc"
        assert after.get_explanation() == "expl"
        meta = after.get_metadata()
        assert meta["created_at"] == "2025-01-01T00:00:00"
        assert meta["length"] == 4
        assert meta["updated_at"]

    @pytest.mark.parametrize("crash_at", range(0, 9))
    def test_a_crash_after_any_write_then_a_second_access_is_right(self, env, crash_at):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        real = config.DbAttribute.DbAttribute
        _crash_after(config, crash_at)
        try:
            _lst(config).append("new")
            crashed = False
        except DbError:
            crashed = True
        config.DbAttribute.DbAttribute = real
        lst = _lst(config)
        lst.append("after")
        result = _lst(config).to_list()
        assert result[:3] == _OLD_ITEMS
        assert result[-1] == "after"
        assert result in ([*_OLD_ITEMS, "after"], [*_OLD_ITEMS, "new", "after"])
        if not crashed:
            assert result == [*_OLD_ITEMS, "new", "after"]
        names = set(_rows(store))
        assert not {n for n in names if n.startswith("list:notes:")}
        assert CLEANUP_MARKER not in _rows(store)["list:notes-meta"]

    def test_a_kill_every_k_writes_on_a_long_list_converges(self, env):
        config, store = env
        n, k = 300, 40
        _plant_old(store, "big", list(range(n)))
        real = config.DbAttribute.DbAttribute
        runs = 0
        while True:
            runs += 1
            _crash_after(config, k)
            try:
                _lst(config, "big").convert()
                break
            except DbError:
                continue
            finally:
                config.DbAttribute.DbAttribute = real
        # Each run resumes: n creates, the -meta create, then the old rows'
        # n + 1 deletes, at k writes a run (a delete is a write here; one
        # PostgreSQL statement deletes them all).
        assert runs <= math.ceil((2 * n + 2) / k) + 1
        assert _lst(config, "big").to_list() == list(range(n))
        assert not [m for m in _rows(store) if m.startswith("list:big:")]

    def test_two_converters_end_in_one_list(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        first, second = _lst(config), _lst(config)
        assert first.storage_format() == second.storage_format() == OLD_LAYOUT
        first.append("a")
        second.append("b")
        result = _lst(config).to_list()
        assert result == [*_OLD_ITEMS, "a", "b"]
        assert len([n for n in _rows(store) if n.startswith("list:notes-#")]) == 5

    def test_a_converter_that_finds_meta_between_batches_stops(self, env):
        config, store = env
        n = 60
        _plant_old(store, "big", list(range(n)))
        other = _lst(config, "big")
        base = config.DbAttribute.DbAttribute
        state = {"batches": 0}

        class Interleaving(base):  # type: ignore[misc,valid-type]
            def create_attrs_if_not_exist(self, actor_id, bucket, rows):  # type: ignore[no-untyped-def]
                state["batches"] += 1
                created = super().create_attrs_if_not_exist(actor_id, bucket, rows)
                if state["batches"] == 1:
                    # Another converter runs its whole conversion meanwhile.
                    config.DbAttribute.DbAttribute = base
                    other.convert()
                    config.DbAttribute.DbAttribute = Interleaving
                return created

        config.DbAttribute.DbAttribute = Interleaving
        _lst(config, "big").convert()
        config.DbAttribute.DbAttribute = base
        assert state["batches"] == 1
        assert _lst(config, "big").to_list() == list(range(n))

    def test_a_lost_create_with_different_data_raises(self, env):
        """A row that appears at a conversion rank between the keys-only
        read and the create (not this list's conversion) is compared."""
        from fractional_indexing import generate_n_keys_between

        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        rank = generate_n_keys_between(None, None, 3)[1]
        base = config.DbAttribute.DbAttribute

        class Racing(base):  # type: ignore[misc,valid-type]
            def create_attrs_if_not_exist(self, actor_id, bucket, rows):  # type: ignore[no-untyped-def]
                store.bucket(ACTOR, BUCKET)[f"list:notes-#{rank}"] = {"data": '"other"'}
                return super().create_attrs_if_not_exist(actor_id, bucket, rows)

        config.DbAttribute.DbAttribute = Racing
        with pytest.raises(ListLayoutConflictError, match="did not write"):
            _lst(config).append("new")
        assert "list:notes:meta" in _rows(store)
        assert "list:notes-meta" not in _rows(store)

    @pytest.mark.parametrize(
        "damage",
        ["hole", "length_too_long", "length_not_int"],
    )
    def test_a_damaged_old_list_raises_and_loses_no_row(self, env, damage):
        config, store = env
        if damage == "hole":
            _plant_old(store, "notes", _OLD_ITEMS)
            del store.bucket(ACTOR, BUCKET)["list:notes:1"]
        elif damage == "length_too_long":
            _plant_old(store, "notes", _OLD_ITEMS, length=5)
        else:
            _plant_old(store, "notes", _OLD_ITEMS, meta={"length": "3"})
        before = copy.deepcopy(_rows(store))
        with pytest.raises(ListCorruptionError):
            _lst(config).append("new")
        assert _rows(store) == before

    def test_rows_above_the_recorded_length_are_leftovers(self, env):
        """A crashed pre-3.16 append wrote its row before the length: the old
        readers ignore it, the conversion ignores it and sweeps it."""
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS, length=2)
        _lst(config).append("new")
        assert _lst(config).to_list() == [_OLD_ITEMS[0], "two", "new"]
        assert not [n for n in _rows(store) if n.startswith("list:notes:")]

    def test_a_leftover_new_layout_row_at_a_conversion_rank_is_a_conflict(self, env):
        """Conversion ranks are a fresh list's first ranks: a row an earlier
        list left there is compared, never adopted."""
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        store.bucket(ACTOR, BUCKET)["list:notes-#a0"] = {"data": '"stale"'}
        before = copy.deepcopy(_rows(store))
        with pytest.raises(ListLayoutConflictError, match="did not write"):
            _lst(config).append("new")
        assert _rows(store) == before

    def test_a_stray_new_layout_row_is_a_conflict(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        store.bucket(ACTOR, BUCKET)["list:notes-#zz"] = {"data": '"stray"'}
        with pytest.raises(ListLayoutConflictError, match="did not write"):
            _lst(config).append("new")

    def test_a_matching_row_from_an_interrupted_run_is_adopted(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        store.bucket(ACTOR, BUCKET)["list:notes-#a0"] = {
            "data": '{"id": 1, "v": "one"}'
        }
        _lst(config).append("new")
        assert _lst(config).to_list() == [*_OLD_ITEMS, "new"]

    def test_a_stale_instance_meets_a_pre_316_write_after_the_conversion(self, env):
        """An instance that read the old layout must not re-convert a list
        another converter finished, after a pre-3.16 writer wrote to it."""
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        stale = _lst(config)
        assert stale.to_list() == _OLD_ITEMS
        _lst(config).append("new")
        _OLD_WRITERS["append"](store.bucket(ACTOR, BUCKET))
        with pytest.raises(ListLayoutConflictError):
            stale.append("x")

    def test_compact_converts_first(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        _lst(config).compact()
        assert _lst(config).storage_format() == 2
        assert _lst(config).to_list() == _OLD_ITEMS

    def test_primed_rows_of_both_layouts_are_a_conflict(self, env):
        from actingweb.attribute_list_store import AttributeListStore

        config, store = env
        _converted(config, store)
        _OLD_WRITERS["clear"](store.bucket(ACTOR, BUCKET))
        _, rows = AttributeListStore(ACTOR, BUCKET, config).list_all_with_rows()
        with pytest.raises(ListLayoutConflictError):
            _lst(config).prime_from_rows(rows)

    def test_an_item_carrying_the_envelope_key_is_stored_wrapped(self, env):
        from actingweb.property_list_span import ENVELOPE_MARKER

        config, store = env
        item = {ENVELOPE_MARKER: 1, "x": "y"}
        _plant_old(store, "notes", [item, "b"])
        _lst(config).append("c")
        assert _lst(config).to_list() == [item, "b", "c"]

    def test_an_item_over_the_stored_size_limit_spans(self, env):
        config, store = env
        config.list_item_span_threshold = 64
        big = {"text": "x" * 1000}
        _plant_old(store, "notes", ["a", big])
        _lst(config).append("c")
        assert _lst(config).to_list() == ["a", big, "c"]
        assert store.rows.get(f"{ACTOR}:{BUCKET}$aux")

    @pytest.mark.parametrize("op", ["clear", "delete"])
    def test_clear_and_delete_remove_a_damaged_list(self, env, op):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS, length=7)
        getattr(_lst(config), op)()
        assert not [n for n in _rows(store) if n.startswith("list:notes:")]
        assert _lst(config).to_list() == []


# ---------------------------------------------------------------- old writers


def _converted(config: Any, store: MemoryStore) -> None:
    _plant_old(store, "notes", _OLD_ITEMS)
    _lst(config).append("new")


_OLD_WRITERS = {
    # What pre-3.16 code writes beside a converted list.
    "append": lambda rows: rows.update(
        {
            "list:notes:0": {"data": "late"},
            "list:notes:meta": {"data": {"length": 1}},
        }
    ),
    "clear": lambda rows: rows.update({"list:notes:meta": {"data": {"length": 0}}}),
    "clear_then_extend": lambda rows: rows.update(
        {
            "list:notes:meta": {"data": {"length": 2}},
            "list:notes:0": {"data": "a"},
            "list:notes:1": {"data": "b"},
        }
    ),
}


class TestOldWriters:
    @pytest.mark.parametrize("writer", sorted(_OLD_WRITERS))
    @pytest.mark.parametrize("access", ["read", "mutation"])
    def test_an_old_writer_beside_a_converted_list_is_a_conflict(
        self, env, writer, access
    ):
        config, store = env
        _converted(config, store)
        _OLD_WRITERS[writer](store.bucket(ACTOR, BUCKET))
        before = copy.deepcopy(_rows(store))
        with pytest.raises(ListLayoutConflictError, match="both layouts"):
            if access == "read":
                _lst(config).to_list()
            else:
                _lst(config).append("x")
        assert _rows(store) == before

    def test_a_crash_inside_the_cleanup_is_not_a_conflict(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        real = config.DbAttribute.DbAttribute
        # Items (3) and the meta create (1) land; the cleanup's delete dies.
        _crash_after(config, 4)
        with pytest.raises(DbError):
            _lst(config).append("new")
        config.DbAttribute.DbAttribute = real
        assert CLEANUP_MARKER in _rows(store)["list:notes-meta"]
        assert _lst(config).to_list() == _OLD_ITEMS
        _lst(config).append("after")
        assert _lst(config).to_list() == [*_OLD_ITEMS, "after"]
        assert CLEANUP_MARKER not in _rows(store)["list:notes-meta"]

    def test_clear_and_delete_work_on_a_conflicting_list(self, env):
        config, store = env
        _converted(config, store)
        _OLD_WRITERS["append"](store.bucket(ACTOR, BUCKET))
        _lst(config).clear()
        assert _lst(config).to_list() == []
        _OLD_WRITERS["append"](store.bucket(ACTOR, BUCKET))
        _lst(config).delete()
        assert not [n for n in _rows(store) if n.startswith("list:notes")]


# ---------------------------------------------------------------- the side bucket


class TestSideBucket:
    def test_same_named_lists_in_two_buckets_keep_separate_side_rows(self, env):
        config, store = env
        config.list_item_span_threshold = 64
        other = "remote:" + "c" * 32
        big_a, big_b = "a" * 500, "b" * 500
        _lst(config).append_once(big_a, key="k")
        _lst(config, bucket=other).append_once(big_b, key="k")
        assert _lst(config).to_list() == [big_a]
        assert _lst(config, bucket=other).to_list() == [big_b]
        assert store.rows[f"{ACTOR}:{BUCKET}$aux"]
        assert store.rows[f"{ACTOR}:{other}$aux"]

    def test_a_bucket_with_a_dollar_has_no_spanning_and_says_so(self, env):
        config, _ = env
        config.list_item_span_threshold = 64
        lst = _lst(config, bucket="odd$bucket")
        with pytest.raises(ValueError, match="reserved for the attribute-list side"):
            lst.append("x" * 500)
        lst.append("small")
        assert _lst(config, bucket="odd$bucket").to_list() == ["small"]

    @pytest.mark.parametrize("op", ["delete", "clear", "bucket"])
    def test_teardown_leaves_no_row_in_either_bucket(self, env, op):
        from actingweb.attribute import Attributes

        config, store = env
        config.list_item_span_threshold = 64
        lst = _lst(config)
        lst.extend(["a", "x" * 500])
        lst.append_once("y" * 500, key="k")
        if op == "bucket":
            Attributes(actor_id=ACTOR, bucket=BUCKET, config=config).delete_bucket()
            assert not store.rows.get(f"{ACTOR}:{BUCKET}")
        else:
            getattr(lst, op)()
            assert set(_rows(store)) <= {"list:notes-meta"}
        assert not store.rows.get(f"{ACTOR}:{BUCKET}$aux")

    def test_the_span_threshold_keeps_a_json_stored_row_under_the_cap(self, env):
        config, _ = env
        config.list_item_span_threshold = 390_000
        MemoryDbAttribute.MAX_ROW_BYTES = 409_600
        try:
            threshold = AttributeListStorage(ACTOR, BUCKET, config).span_threshold
        finally:
            MemoryDbAttribute.MAX_ROW_BYTES = None
        assert threshold is not None and threshold * 6 + 4096 <= 409_600
        config.list_item_span_threshold = None
        assert AttributeListStorage(ACTOR, BUCKET, config).span_threshold is None


# ---------------------------------------------------------------- costs


class TestCosts:
    def test_a_converted_list_costs_one_extra_point_read_per_instance(self, env):
        config, store = env
        _lst(config).extend(["a", "b"])
        counts = _counting(config, store)
        _lst(config).append("c")
        appends_one = dict(counts)
        counts.clear()
        lst = _lst(config)
        lst.append("d")
        lst.append("e")
        # The second append on the same instance makes no layout read.
        assert counts.get("get_attr", 0) == appends_one.get("get_attr", 0) + 1

    def test_round_trip_pins_at_5000_items(self, env):
        config, store = env
        n = 5000
        _plant_old(store, "big", list(range(n)))
        counts = _counting(config, store)
        _lst(config, "big").convert()
        assert counts.get("create_attrs_if_not_exist") == math.ceil(n / 25)
        assert counts.get("get_attr_prefix", 0) <= 3
        counts.clear()
        lst = _lst(config, "big")
        lst.clear()
        lst.extend(list(range(n)))
        assert counts.get("get_attr_range", 0) <= 3
        assert _lst(config, "big").to_list() == list(range(n))


class TestVerificationFindings:
    """Verification 2026-11-13 (code review 3 and 8)."""

    def test_a_late_converter_does_not_recreate_a_row_deleted_since(self, env):
        config, store = env
        _plant_old(store, "notes", _OLD_ITEMS)
        late = _lst(config)
        snapshot = late._old_rows()  # noqa: SLF001 -- read before A finished
        other = _lst(config)
        other.append("new")  # A converts and finishes
        other.pop(0)  # a user deletes item 0 since
        expected = _lst(config).to_list()
        late._old_rows = lambda: snapshot  # type: ignore[method-assign]
        late._convert()  # noqa: SLF001
        assert _lst(config).to_list() == expected

    def test_a_primed_conflict_leaves_no_layout_behind(self, env):
        config, store = env
        _converted(config, store)
        _plant_old(store, "notes", ["x"])
        lst = _lst(config)
        rows = dict(store.bucket(ACTOR, BUCKET))
        rows = {name: row["data"] for name, row in rows.items()}
        meta = json.loads(rows["list:notes-meta"])
        meta.pop("layout_cleanup", None)
        rows["list:notes-meta"] = json.dumps(meta)
        with pytest.raises(ListLayoutConflictError):
            lst.prime_from_rows(rows)
        assert lst._layout is None  # noqa: SLF001
