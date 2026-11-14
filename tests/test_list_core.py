"""``actingweb.list_core``: the list format extracted from ``ListProperty``
(thoughts/plans/2026-11-13-attribute-list-v2-port.md, Phase 1).

- the core reaches storage only through ``ListStorage`` (a source guard);
- ``ListProperty`` keeps its public surface, and the names that moved are
  the same objects under both modules;
- ``ListCore``'s own public layer, which ``ListProperty`` no longer
  executes for v2 (it calls the ``_v2_*`` halves), works over a minimal
  in-memory ``ListStorage``, and issues the same reads and writes per
  operation as the property list does over the property fake;
- the rank cap raises ``ListRankExhaustedError``, a ``RuntimeError``; a
  storage write that did not land does not.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
from collections import Counter
from typing import Any

import pytest

from actingweb import list_core, property_list
from actingweb.list_core import (
    ListCore,
    ListItemHandle,
    ListRankExhaustedError,
    ListStorage,
)
from actingweb.property_list import ListProperty, PropertyListStorage
from actingweb.property_list_span import AUX_SUFFIX
from tests.test_property_list_integrity import FakePropertyDb, _patch_get_property

LIST_CORE_PY = pathlib.Path(list_core.__file__)
ACTOR = "actor-core"


class MemoryListStorage:
    """A minimal ``ListStorage``: two dicts, and a tally of every call."""

    noun = "thing"
    location = "memory"
    remedy = "Rebuild it."

    def __init__(
        self,
        *,
        span_threshold: int | None = None,
        side: bool = True,
        fail_put: bool = False,
    ) -> None:
        self.rows: dict[str, str] = {}
        self.side_rows: dict[str, str] = {}
        self.scalars: dict[str, str] = {}
        self.calls: Counter[tuple[str, bool]] = Counter()
        self._span_threshold = span_threshold
        self._side = side
        self.fail_put = fail_put

    @property
    def actor_id(self) -> str:
        return ACTOR

    @property
    def span_threshold(self) -> int | None:
        return self._span_threshold

    @property
    def item_max_bytes(self) -> int | None:
        return None

    @property
    def key_scope(self) -> str:
        return ACTOR

    def side_key(self) -> str:
        if not self._side:
            raise ValueError("no side partition")
        return "side"

    def side_available(self) -> bool:
        return self._side

    def scalar_exists(self, name: str) -> bool:
        self.calls["scalar_exists", False] += 1
        return name in self.scalars

    def _part(self, side: bool) -> dict[str, str]:
        if side and not self._side:
            raise ValueError("no side partition")
        return self.side_rows if side else self.rows

    def get(self, name: str, *, side: bool = False) -> str | None:
        self.calls["get", side] += 1
        return self._part(side).get(name)

    def put(self, name: str, value: str, *, side: bool = False) -> bool | None:
        self.calls["put", side] += 1
        if self.fail_put:
            return False
        self._part(side)[name] = value
        return True

    def remove(self, name: str, *, side: bool = False) -> bool | None:
        self.calls["remove", side] += 1
        self._part(side).pop(name, None)
        return True

    def get_range(
        self,
        lower: str,
        upper: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, str]:
        self.calls["get_range", side] += 1
        return {
            k: ("" if keys_only else v)
            for k, v in self._part(side).items()
            if lower <= k <= upper
        }

    def get_prefix(
        self,
        prefix: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, str]:
        self.calls["get_prefix", side] += 1
        return {
            k: ("" if keys_only else v)
            for k, v in self._part(side).items()
            if k.startswith(prefix)
        }

    def get_last_in_range(
        self, lower: str, upper: str, *, side: bool = False
    ) -> str | None:
        self.calls["get_last_in_range", side] += 1
        names = [k for k in self._part(side) if lower <= k <= upper]
        return max(names) if names else None

    def create_if_not_exists(
        self, name: str, value: str, *, side: bool = False
    ) -> bool:
        self.calls["create_if_not_exists", side] += 1
        part = self._part(side)
        if name in part:
            return False
        part[name] = value
        return True

    def create_many_if_not_exists(
        self, rows: dict[str, str], *, side: bool = False
    ) -> set[str]:
        return {
            n for n, v in rows.items() if self.create_if_not_exists(n, v, side=side)
        }

    def set_if_value_equals(
        self, name: str, expected: str, value: str, *, side: bool = False
    ) -> bool:
        self.calls["set_if_value_equals", side] += 1
        part = self._part(side)
        if part.get(name) != expected:
            return False
        part[name] = value
        return True

    def delete_if_value_equals(
        self, name: str, value: str, *, side: bool = False
    ) -> bool:
        self.calls["delete_if_value_equals", side] += 1
        part = self._part(side)
        if part.get(name) != value:
            return False
        del part[name]
        return True

    def batch_delete(self, names: list[str], *, side: bool = False) -> None:
        self.calls["batch_delete", side] += 1
        part = self._part(side)
        for name in names:
            part.pop(name, None)


class TalliedPropertyDb(FakePropertyDb):
    """The property fake, tallied the way ``MemoryListStorage`` tallies:
    ``set(value=None)`` is a ``remove``, any other ``set`` a ``put``, and a
    call on ``{actor}$aux`` is a side call."""

    def __init__(self, store: dict[Any, Any], calls: Counter[tuple[str, bool]]):
        super().__init__(store)
        self.calls = calls

    def _t(self, op: str, actor_id: str | None) -> None:
        self.calls[op, bool(actor_id and actor_id.endswith(AUX_SUFFIX))] += 1

    def get(self, actor_id=None, name=None):
        self._t("get", actor_id)
        return super().get(actor_id=actor_id, name=name)

    def set(self, actor_id=None, name=None, value=None):
        self._t("remove" if value is None else "put", actor_id)
        return super().set(actor_id=actor_id, name=name, value=value)

    def get_range(
        self,
        actor_id=None,
        lower=None,
        upper=None,
        keys_only=False,
        consistent_read=True,
    ):
        self._t("get_range", actor_id)
        return super().get_range(
            actor_id=actor_id,
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_prefix(
        self, actor_id=None, prefix=None, keys_only=False, consistent_read=True
    ):
        self._t("get_prefix", actor_id)
        return super().get_prefix(
            actor_id=actor_id,
            prefix=prefix,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_last_in_range(self, actor_id=None, lower=None, upper=None):
        self._t("get_last_in_range", actor_id)
        return super().get_last_in_range(actor_id=actor_id, lower=lower, upper=upper)

    def create_if_not_exists(self, actor_id=None, name=None, value=None):
        self._t("create_if_not_exists", actor_id)
        return super().create_if_not_exists(actor_id=actor_id, name=name, value=value)

    def set_if_value_equals(self, actor_id=None, name=None, expected=None, value=None):
        self._t("set_if_value_equals", actor_id)
        return super().set_if_value_equals(
            actor_id=actor_id, name=name, expected=expected, value=value
        )

    def delete_if_value_equals(self, actor_id=None, name=None, value=None):
        self._t("delete_if_value_equals", actor_id)
        return super().delete_if_value_equals(actor_id=actor_id, name=name, value=value)

    def batch_delete(self, actor_id=None, names=None):
        self._t("batch_delete", actor_id)
        return super().batch_delete(actor_id=actor_id, names=names)


# ---------------------------------------------------------------- structure


class TestStructure:
    def _imports(self) -> list[tuple[str, list[str]]]:
        tree = ast.parse(LIST_CORE_PY.read_text(), filename=str(LIST_CORE_PY))
        found: list[tuple[str, list[str]]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                found.append((node.module or "", [a.name for a in node.names]))
            elif isinstance(node, ast.Import):
                found += [(a.name, []) for a in node.names]
        return found

    def test_the_core_imports_no_database_module_but_its_exceptions(self):
        offenders = [
            module
            for module, _ in self._imports()
            if module.startswith("actingweb.db") and module != "actingweb.db.exceptions"
        ]
        assert offenders == []

    def test_the_core_imports_neither_storage_layer(self):
        offenders = [
            module
            for module, _ in self._imports()
            if module in ("actingweb.property", "actingweb.attribute")
            or module.startswith(("actingweb.property.", "actingweb.attribute."))
            or module in ("actingweb.property_list", "actingweb.attribute_list")
        ]
        assert offenders == []

    def test_the_core_never_names_get_property(self):
        tree = ast.parse(LIST_CORE_PY.read_text(), filename=str(LIST_CORE_PY))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert "get_property" not in names

    def test_the_core_logs_under_the_property_list_logger(self):
        assert list_core.logger.name == "actingweb.property_list"


# ---------------------------------------------------------------- surface

# ListProperty's public methods and their signatures before the extraction
# (master at 2ece153), with module names stripped from annotations.
_FROZEN_SURFACE = {
    "__delitem__": "(self, index: int) -> None",
    "__getitem__": "(self, index: int) -> Any",
    "__init__": "(self, actor_id: str, name: str, config: Any) -> None",
    "__iter__": "(self) -> 'ListPropertyIterator | Iterator[Any]'",
    "__len__": "(self) -> int",
    "__setitem__": "(self, index: int, value: Any) -> None",
    "append": "(self, item: Any) -> None",
    "append_once": "(self, item: Any, *, key: str) -> AppendOnceResult",
    "check_item_size": "(self, item: Any) -> None",
    "clear": "(self) -> None",
    "compact": "(self, allow_reverted: bool = False, sweep_span_orphans: bool = False) -> dict[str, Any]",
    "count": "(self, value: Any) -> int",
    "delete": "(self) -> None",
    "delete_by_handle": "(self, handle: ListItemHandle) -> bool",
    "extend": "(self, items: list[Any]) -> None",
    "find": "(self, identity_key: str, value: Any, consistent: bool = True) -> Any | None",
    "find_all": "(self, identity_key: str, value: Any, consistent: bool = True) -> list[Any]",
    "get_description": "(self) -> str",
    "get_explanation": "(self) -> str",
    "get_metadata": "(self) -> dict[str, Any]",
    "index": "(self, value: Any, start: int = 0, stop: int | None = None) -> int",
    "insert": "(self, index: int, item: Any) -> None",
    "item_at": "(self, handle: ListItemHandle) -> tuple[ListItemHandle, Any]",
    "items_with_handles": "(self, *, resolve: bool = True) -> list[tuple[ListItemHandle, Any]]",
    "migrate_to_v2": "(self, allow_damaged: bool = False) -> dict[str, Any]",
    "pop": "(self, index: int = -1) -> Any",
    "prime_from_rows": "(self, rows: dict[str, Any]) -> None",
    "remove": "(self, value: Any) -> None",
    "remove_where": "(self, identity_key: str, value: Any, *, first_only: bool = False) -> list[Any]",
    "repair_keys": "(self) -> dict[str, Any]",
    "set_description": "(self, description: str) -> None",
    "set_explanation": "(self, explanation: str) -> None",
    "sizes_from_rows": "(self, rows: dict[str, Any]) -> list[int]",
    "slice": "(self, start: int, end: int, consistent: bool = True) -> list[Any]",
    "storage_format": "(self) -> int",
    "sweep_foreign_format_rows": "(self) -> int",
    "sweep_span_orphans": "(self) -> dict[str, Any]",
    "to_indexed_list": "(self, consistent: bool = True) -> list[tuple[int, Any]]",
    "to_list": "(self, consistent: bool = True) -> list[Any]",
    "to_list_from_rows": "(self, rows: dict[str, Any], *, resolve: bool = True) -> list[Any]",
    "update_by_handle": "(self, handle: ListItemHandle, item: Any) -> bool",
    "update_where": "(self, identity_key: str, value: Any, item: Any, *, first_only: bool = False) -> list[Any]",
    "verify": "(self, identity_key: str | None = None, spans: bool = False) -> dict[str, Any]",
}

# Moved to list_core and re-exported by property_list under the same name.
_MOVED = (
    "UNRESOLVED",
    "AppendOnceResult",
    "ListCorruptionError",
    "ListItemHandle",
    "ListItemSpanError",
    "ListItemTooLargeError",
    "ListMetadataContentionError",
    "ListRankExhaustedError",
    "ListLayoutConflictError",
    "_ItemGone",
    "_METADATA_CAS_MAX_ATTEMPTS",
    "_METADATA_CAS_ADVISORY_MAX_ATTEMPTS",
    "_KEYED_IN_FLIGHT_SECONDS",
    "_V2_MAX_RANK_RETRIES",
    "_V2_RANK_ALPHABET",
    "_V2_RANK_MARKER",
    "_V2_RANK_MAX_LEN",
    "_V2_RANK_WARNING_LENGTH",
    "_v2_is_rank",
)


def _sig(fn: Any) -> str:
    text = str(inspect.signature(fn))
    # 3.11 prints "typing.Any | None" where 3.14 prints "Any | None".
    for module in ("actingweb.list_core.", "actingweb.property_list.", "typing."):
        text = text.replace(module, "")
    return text


class TestSurface:
    @pytest.mark.parametrize("name", sorted(_FROZEN_SURFACE))
    def test_list_property_keeps_its_public_method(self, name):
        assert _sig(getattr(ListProperty, name)) == _FROZEN_SURFACE[name]

    @pytest.mark.parametrize("name", _MOVED)
    def test_a_moved_name_is_the_same_object_in_both_modules(self, name):
        assert getattr(property_list, name) is getattr(list_core, name)

    def test_a_consumer_patch_of_property_list_time_sleep_still_resolves(
        self, monkeypatch
    ):
        """Emm's suite patches "actingweb.property_list.time.sleep"; the
        module keeps a ``time`` name, the shared module list_core sleeps
        through."""
        calls: list[float] = []
        monkeypatch.setattr("actingweb.property_list.time.sleep", calls.append)
        list_core.time.sleep(0.25)
        assert calls == [0.25]

    def test_no_test_patches_a_re_exported_tunable_on_property_list(self):
        """Patching a name property_list only re-exports succeeds and
        changes nothing (list_core reads its own binding): every such patch
        string must name list_core."""
        moved = {n for n in dir(property_list) if hasattr(list_core, n)} - {
            "logger",
            "time",
        }
        tests_dir = pathlib.Path(__file__).resolve().parent
        offenders = [
            f"{path.name}: {name}"
            for path in tests_dir.rglob("*.py")
            for name in moved
            if f'"actingweb.property_list.{name}"' in path.read_text()
        ]
        assert offenders == []

    def test_the_package_lazy_exports_still_resolve(self):
        package = importlib.import_module("actingweb")
        for name in (
            "UNRESOLVED",
            "AppendOnceResult",
            "ListItemSpanError",
            "ListItemTooLargeError",
            "ListMetadataContentionError",
        ):
            assert getattr(package, name) is getattr(list_core, name)

    def test_list_property_is_the_core_over_property_storage(self, monkeypatch):
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb({}))
        lst = ListProperty(ACTOR, "x", object())
        assert isinstance(lst, ListCore)
        assert isinstance(lst._storage, PropertyListStorage)
        assert isinstance(lst._storage, ListStorage)

    def test_the_core_has_every_public_method_but_the_v1_migration(self):
        core = {n for n in dir(ListCore) if not n.startswith("_")}
        lp = {n for n in _FROZEN_SURFACE if not n.startswith("_")}
        assert lp - core == {"migrate_to_v2", "sweep_foreign_format_rows"}


# ---------------------------------------------------------------- the core's public layer


def _core(storage: ListStorage | None = None, name: str = "notes") -> ListCore:
    return ListCore(storage if storage is not None else MemoryListStorage(), name)


class TestPublicLayerOverMemory:
    def test_appends_reads_and_positional_access(self):
        lst = _core()
        lst.append("a")
        lst.extend(["b", "c"])
        assert len(lst) == 3
        assert lst.to_list() == ["a", "b", "c"]
        assert list(lst) == ["a", "b", "c"]
        assert lst[1] == "b" and lst[-1] == "c"
        assert lst.slice(1, 3) == ["b", "c"]
        assert lst.to_indexed_list() == [(0, "a"), (1, "b"), (2, "c")]
        assert lst.index("c") == 2 and lst.count("a") == 1
        assert lst.storage_format() == 2

    def test_positional_mutators(self):
        lst = _core()
        lst.extend(["a", "b", "c"])
        lst.insert(1, "x")
        lst[0] = "A"
        del lst[2]
        assert lst.pop() == "c"
        lst.remove("x")
        assert lst.to_list() == ["A"]
        with pytest.raises(IndexError):
            lst[5]

    def test_falsy_items_round_trip(self):
        lst = _core()
        lst.extend(["0", 0, None, "", [], {}, False])
        assert _core(lst._storage).to_list() == ["0", 0, None, "", [], {}, False]

    def test_handles_and_identity_operations(self):
        lst = _core()
        lst.extend([{"id": 1, "v": "a"}, {"id": 2, "v": "b"}, {"id": 2, "v": "c"}])
        assert lst.find("id", 2) == {"id": 2, "v": "b"}
        assert len(lst.find_all("id", 2)) == 2
        handles = lst.items_with_handles()
        assert all(isinstance(h, ListItemHandle) for h, _ in handles)
        h0, item0 = handles[0]
        assert lst.item_at(h0)[1] == item0
        assert lst.update_by_handle(h0, {"id": 1, "v": "A"})
        assert lst.update_where("id", 2, {"id": 2, "v": "z"}, first_only=True) == [
            {"id": 2, "v": "b"}
        ]
        assert lst.remove_where("id", 2) == [{"id": 2, "v": "z"}, {"id": 2, "v": "c"}]
        h, _ = lst.items_with_handles()[0]
        assert lst.delete_by_handle(h)
        assert lst.to_list() == []

    def test_append_once_and_repair_keys(self):
        lst = _core()
        first = lst.append_once("a", key="k1")
        again = lst.append_once("a", key="k1")
        assert first.created and not again.created
        assert lst.to_list() == ["a"]
        assert lst.repair_keys()["key_rows_created"] == 0

    def test_metadata_description_and_explanation(self):
        lst = _core()
        lst.set_description("d")
        lst.set_explanation("e")
        lst.append("a")
        fresh = _core(lst._storage)
        assert fresh.get_description() == "d"
        assert fresh.get_explanation() == "e"
        meta = fresh.get_metadata()
        assert meta["length"] == 1 and meta["created_at"]

    def test_rows_based_reads(self):
        storage = MemoryListStorage()
        lst = _core(storage)
        lst.extend(["a", "bb"])
        rows = dict(storage.rows)
        fresh = _core(storage)
        fresh.prime_from_rows(rows)
        assert fresh.to_list_from_rows(rows) == ["a", "bb"]
        assert fresh.sizes_from_rows(rows) == [3, 4]

    def test_verify_compact_and_spans(self):
        storage = MemoryListStorage(span_threshold=64)
        lst = _core(storage)
        big = "x" * 500
        lst.extend(["a", big])
        assert storage.side_rows, "the big item spans into the side partition"
        assert _core(storage).to_list() == ["a", big]
        report = lst.verify(spans=True)
        assert report["healthy"] and report["foreign_format_rows"] == 0
        assert lst.compact()["format"] == 2
        assert isinstance(lst.sweep_span_orphans(), dict)
        lst.check_item_size("small")

    def test_clear_and_delete_leave_no_rows(self):
        storage = MemoryListStorage(span_threshold=64)
        lst = _core(storage)
        lst.extend(["a", "x" * 500])
        lst.append_once("b", key="k")
        lst.clear()
        assert _core(storage).to_list() == []
        assert set(storage.rows) == {"list:notes-meta"}
        assert storage.side_rows == {}
        lst.extend(["c"])
        lst.delete()
        assert storage.rows == {} and storage.side_rows == {}

    def test_a_scalar_of_the_same_name_is_refused_with_the_storage_noun(self):
        storage = MemoryListStorage()
        storage.scalars["notes"] = "1"
        with pytest.raises(ValueError, match="a thing with this name already exists"):
            _core(storage).append("a")

    def test_a_meta_row_of_another_format_is_refused_with_the_storage_remedy(self):
        storage = MemoryListStorage()
        storage.rows["list:notes-meta"] = '{"format": 1, "length": 0}'
        with pytest.raises(ValueError, match="Rebuild it"):
            _core(storage).append("a")
        with pytest.raises(ValueError, match="needs format 2"):
            _core(storage).items_with_handles()

    def test_no_side_partition_refuses_a_spanning_write_before_writing(self):
        storage = MemoryListStorage(span_threshold=64, side=False)
        lst = _core(storage)
        with pytest.raises(ValueError, match="no side partition"):
            lst.append("x" * 500)
        assert storage.rows == {}
        lst.append("small")
        lst.delete()
        assert storage.rows == {}


# ---------------------------------------------------------------- counting parity

_OPS = {
    "append": lambda lst: lst.append("z"),
    "extend": lambda lst: lst.extend(["y", "z"]),
    "insert_middle": lambda lst: lst.insert(2, "m"),
    "insert_front": lambda lst: lst.insert(0, "f"),
    "setitem": lambda lst: lst.__setitem__(1, "s"),
    "delitem": lambda lst: lst.__delitem__(1),
    "pop_last": lambda lst: lst.pop(),
    "pop_first": lambda lst: lst.pop(0),
    "remove": lambda lst: lst.remove("c"),
    "getitem": lambda lst: lst[2],
    "len": len,
    "to_list": lambda lst: lst.to_list(),
    "iterate": list,
    "index": lambda lst: lst.index("c"),
    "count": lambda lst: lst.count("c"),
    "find": lambda lst: lst.find("id", 1),
    "items_with_handles": lambda lst: lst.items_with_handles(),
    "get_metadata": lambda lst: lst.get_metadata(),
    "set_description": lambda lst: lst.set_description("d"),
    "append_once": lambda lst: lst.append_once("k", key="key"),
    "verify": lambda lst: lst.verify(),
    "compact": lambda lst: lst.compact(),
    "remove_where": lambda lst: lst.remove_where("id", 1),
    "update_where": lambda lst: lst.update_where("id", 1, {"id": 1}),
}

_SEED = ["a", "b", "c", "d", {"id": 1}]
_PROPERTY_FOREIGN_RANGE_READS = {"verify": 1, "compact": 1}


def _without_reads(calls: Counter[tuple[str, bool]]) -> Counter[tuple[str, bool]]:
    """Every call but the point reads: the property list reads its meta row
    once more on a fresh instance (its lazy-migration check), the only
    difference between the two layers."""
    return Counter(
        {k: v for k, v in calls.items() if k[0] not in ("get", "scalar_exists")}
    )


class TestCallParityWithTheProperty:
    """For each public operation on a fresh instance of a seeded v2 list,
    the core over memory and the property list over the property fake
    issue the same range reads, last-rank reads and writes."""

    @pytest.mark.parametrize("op", sorted(_OPS))
    def test_same_calls_per_operation(self, op, monkeypatch):
        store: dict[Any, Any] = {}
        prop_calls: Counter[tuple[str, bool]] = Counter()
        db = TalliedPropertyDb(store, prop_calls)
        _patch_get_property(monkeypatch, lambda config: db)
        ListProperty(ACTOR, "notes", object()).extend(_SEED)
        prop_calls.clear()
        _OPS[op](ListProperty(ACTOR, "notes", object()))

        storage = MemoryListStorage()
        _core(storage).extend(_SEED)
        storage.calls.clear()
        _OPS[op](_core(storage))

        expected = _without_reads(prop_calls)
        # The property list also counts v1-shaped rows in the list's range
        # (its foreign-format hook): one keys-only range read the core,
        # which has no other format, does not make.
        expected["get_range", False] -= _PROPERTY_FOREIGN_RANGE_READS.get(op, 0)
        assert _without_reads(storage.calls) == +expected

    def test_absolute_pins_on_the_core(self):
        storage = MemoryListStorage()
        _core(storage).extend(_SEED)

        storage.calls.clear()
        _core(storage).append("z")
        assert storage.calls["get_range", False] == 0
        assert storage.calls["get_last_in_range", False] == 1

        storage.calls.clear()
        _core(storage).to_list()
        assert storage.calls["get_range", False] == 1

        storage.calls.clear()
        lst = _core(storage)
        len(lst)
        len(lst)
        assert storage.calls["get_range", False] == 1


# ---------------------------------------------------------------- rank cap


class TestRankExhausted:
    def test_the_rank_cap_raises_list_rank_exhausted_a_runtime_error(self, monkeypatch):
        monkeypatch.setattr(list_core, "_V2_RANK_MAX_LEN", 2)
        lst = _core()
        lst.extend(["a", "b"])
        with pytest.raises(ListRankExhaustedError) as caught:
            for _ in range(200):
                lst.insert(1, "x")
        assert isinstance(caught.value, RuntimeError)
        assert "compact()" in str(caught.value)

    def test_a_write_that_did_not_land_is_not_rank_exhaustion(self):
        lst = _core(MemoryListStorage(fail_put=True))
        lst.append("a")
        with pytest.raises(RuntimeError) as caught:
            lst[0] = "b"
        assert not isinstance(caught.value, ListRankExhaustedError)
        assert "write failed" in str(caught.value)
