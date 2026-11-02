"""A backend read fault on a v2 (fractional rank key) list raises.

Phase 4 of thoughts/plans/2026-11-02-3-16-small-followups.md. Every list
here is format 2 (``list:{name}-#{rank}`` item rows), built through
``append`` on the dict-backed ``FakePropertyDb`` and then read through a
subclass whose ``get_range`` or ``get_prefix`` raises ``DbError``. The read
must raise, never answer an empty list (or ``None`` from ``find``).

The store method each path calls (``actingweb/property_list.py``):

- iteration, ``to_list()`` and ``find()`` (through ``to_list()``):
  ``_v2_load_full`` -> ``get_range``;
- indexing: ``_v2_getitem`` -> ``_v2_ensure_rank_cache(force=True)`` ->
  ``get_range``;
- a spanned item, once its head is read: ``_resolve`` -> ``_read_span`` ->
  ``get_prefix`` on the actor's side partition; ``delete()`` enumerates the
  span rows with ``_aux_names`` -> ``get_prefix``.
"""

from typing import Any

import pytest

from actingweb.config import Config
from actingweb.db.exceptions import DbError
from actingweb.property_list import ListProperty
from tests.test_property_list_integrity import FakePropertyDb, _patch_get_property

ACTOR = "actorfaultreads"
NAME = "notes"


class FaultingReadDb(FakePropertyDb):
    """``FakePropertyDb`` whose ``get_range`` and ``get_prefix`` raise
    ``DbError`` while their method name is in the shared ``faults`` set."""

    def __init__(self, store: dict[Any, Any], faults: set[str]) -> None:
        super().__init__(store)
        self.faults = faults

    def get_range(
        self,
        actor_id: str | None = None,
        lower: str | None = None,
        upper: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, Any]:
        if "get_range" in self.faults:
            raise DbError("property get_range (simulated)", actor_id)
        return super().get_range(
            actor_id=actor_id,
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_prefix(
        self,
        actor_id: str | None = None,
        prefix: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, Any]:
        if "get_prefix" in self.faults:
            raise DbError("property get_prefix (simulated)", actor_id)
        return super().get_prefix(
            actor_id=actor_id,
            prefix=prefix,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )


@pytest.fixture
def faults() -> set[str]:
    return set()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, faults: set[str]) -> dict[Any, Any]:
    rows: dict[Any, Any] = {}
    _patch_get_property(monkeypatch, lambda config: FaultingReadDb(rows, faults))
    return rows


@pytest.fixture
def config() -> Config:
    return Config(
        database="dynamodb", list_item_span_threshold=2_000, list_item_max_bytes=20_000
    )


def _v2_list(config: Config, items: list[Any]) -> ListProperty:
    lst = ListProperty(ACTOR, NAME, config)
    for item in items:
        lst.append(item)
    assert lst.storage_format() == 2
    return lst


PLAIN = [{"id": "a", "n": 1}, {"id": "b", "n": 2}]
SPANNED = {"id": "big", "body": "x" * 5_000}


class TestRangeReadFault:
    """A ``get_range`` fault on a v2 list."""

    def test_iteration_raises(
        self, store: dict[Any, Any], faults: set[str], config: Config
    ) -> None:
        lst = _v2_list(config, PLAIN)
        assert list(ListProperty(ACTOR, NAME, config)) == PLAIN
        faults.add("get_range")
        with pytest.raises(DbError):
            list(lst)
        with pytest.raises(DbError):
            list(ListProperty(ACTOR, NAME, config))

    def test_to_list_raises(
        self, store: dict[Any, Any], faults: set[str], config: Config
    ) -> None:
        lst = _v2_list(config, PLAIN)
        faults.add("get_range")
        with pytest.raises(DbError):
            lst.to_list()

    def test_indexing_raises(
        self, store: dict[Any, Any], faults: set[str], config: Config
    ) -> None:
        lst = _v2_list(config, PLAIN)
        assert lst[1] == PLAIN[1]
        faults.add("get_range")
        # A warm rank cache does not help: the positional read forces a
        # fresh rank read.
        with pytest.raises(DbError):
            lst[0]
        with pytest.raises(DbError):
            ListProperty(ACTOR, NAME, config)[-1]

    def test_find_raises(
        self, store: dict[Any, Any], faults: set[str], config: Config
    ) -> None:
        lst = _v2_list(config, PLAIN)
        assert lst.find("id", "b") == PLAIN[1]
        faults.add("get_range")
        with pytest.raises(DbError):
            lst.find("id", "b")
        with pytest.raises(DbError):
            lst.find("id", "absent")


class TestPrefixReadFaultOnASpannedItem:
    """A ``get_prefix`` fault on a v2 list holding a spanned item: the
    body read of that item raises."""

    def test_reads_of_a_spanned_item_raise(
        self, store: dict[Any, Any], faults: set[str], config: Config
    ) -> None:
        lst = _v2_list(config, [PLAIN[0], SPANNED])
        assert any(aid == f"{ACTOR}$aux" for aid, _ in store), "item did not span"
        assert lst.to_list() == [PLAIN[0], SPANNED]
        faults.add("get_prefix")
        with pytest.raises(DbError):
            lst.to_list()
        with pytest.raises(DbError):
            list(lst)
        with pytest.raises(DbError):
            lst[1]
        with pytest.raises(DbError):
            lst.find("id", "big")

    def test_delete_raises_and_keeps_the_meta_row(
        self, store: dict[Any, Any], faults: set[str], config: Config
    ) -> None:
        """``delete()`` removes the heads, then enumerates the span rows:
        a fault there raises before the meta row goes, so a retry still
        finds the list and removes its bodies."""
        lst = _v2_list(config, [PLAIN[0], SPANNED])
        faults.add("get_prefix")
        with pytest.raises(DbError):
            lst.delete()
        assert (ACTOR, f"list:{NAME}-meta") in store
        assert any(aid == f"{ACTOR}$aux" for aid, _ in store)
        faults.clear()
        ListProperty(ACTOR, NAME, config).delete()
        assert not any(aid == f"{ACTOR}$aux" for aid, _ in store)
        assert (ACTOR, f"list:{NAME}-meta") not in store

    def test_a_plain_item_does_not_read_the_side_partition(
        self, store: dict[Any, Any], faults: set[str], config: Config
    ) -> None:
        """The fault is on the spanned path only: the plain item before it
        still reads."""
        lst = _v2_list(config, [PLAIN[0], SPANNED])
        faults.add("get_prefix")
        assert lst[0] == PLAIN[0]
