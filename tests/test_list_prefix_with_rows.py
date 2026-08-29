"""``PropertyListStore.list_prefix_with_rows()`` and ``property.rows_for()``.

The scoped counterpart of ``list_all_with_rows()``: one namespace of an
actor's lists instead of the whole partition. Three properties decide whether
it is worth having at all, and each has a test here:

* the storage prefix is ``f"list:{prefix}"`` and the read is EVENTUALLY
  consistent. At ``get_range``'s strong default the five measured families
  cost ~1,370 RCU against the 1,361 dump they replace -- the public path has
  to be eventual to pay at all, so this is the acceptance gate, not a detail;
* ``(names, rows)`` stay internally consistent, so a caller can prime every
  named list from the rows in hand;
* a backend fault RAISES rather than swallowing to ``([], {})``. For a scoped
  read "nothing here" is the ordinary answer, so the sibling's swallow idiom
  would render a throttled query as content.

``rows_for()`` is tested here rather than with its Phase 5 caller because the
row encoding it reads belongs to this module.
"""

import json

import pytest

from actingweb.db.exceptions import DbError
from actingweb.property import PropertyListStore, rows_for


class FakePrefixDb:
    """Serves get_prefix() out of a dict, recording every call."""

    def __init__(self, store, fail=False):
        self.store = store
        self.fail = fail
        self.prefix_calls: list[dict] = []
        self.range_calls: list[dict] = []

    def get_prefix(
        self, actor_id=None, prefix=None, keys_only=False, consistent_read=True
    ):
        self.prefix_calls.append(
            {
                "actor_id": actor_id,
                "prefix": prefix,
                "keys_only": keys_only,
                "consistent_read": consistent_read,
            }
        )
        if self.fail:
            raise DbError("property prefix read", actor_id)
        if not prefix:
            return {}
        return {
            name: value
            for (aid, name), value in self.store.items()
            if aid == actor_id and name.startswith(prefix)
        }

    def get(self, actor_id=None, name=None):
        return self.store.get((actor_id, name))


class FakePartitionDb:
    """Serves fetch_all_including_lists() out of the same dict."""

    def __init__(self, store, fail=False):
        self.store = store
        self.fail = fail
        self.calls = 0

    def fetch_all_including_lists(self, actor_id=None):
        self.calls += 1
        if self.fail:
            raise DbError("property partition read", actor_id)
        return {
            name: value for (aid, name), value in self.store.items() if aid == actor_id
        }


ACTOR = "actor-prefix"


def _seed_v1(store, name, items, actor_id=ACTOR):
    store[(actor_id, f"list:{name}-meta")] = json.dumps({"length": len(items)})
    for i, item in enumerate(items):
        store[(actor_id, f"list:{name}-{i}")] = json.dumps(item)


def _seed_v2(store, name, items, actor_id=ACTOR):
    import fractional_indexing as fi

    store[(actor_id, f"list:{name}-meta")] = json.dumps({"format": 2})
    for rank, item in zip(
        fi.generate_n_keys_between(None, None, len(items)), items, strict=True
    ):
        store[(actor_id, f"list:{name}-#{rank}")] = json.dumps(item)


@pytest.fixture
def store():
    return {}


@pytest.fixture
def patched(monkeypatch, store):
    """Returns (list_store, prefix_db, partition_db) sharing one dict."""
    prefix_db = FakePrefixDb(store)
    partition_db = FakePartitionDb(store)
    monkeypatch.setattr("actingweb.property.get_property", lambda config: prefix_db)
    monkeypatch.setattr(
        "actingweb.property.get_property_list", lambda config: partition_db
    )
    return PropertyListStore(actor_id=ACTOR, config=object()), prefix_db, partition_db


class TestTheReadItself:
    def test_storage_prefix_and_eventual_consistency(self, patched, store):
        """The acceptance gate. ``consistent_read=False`` matches what
        ``fetch_all_including_lists()`` already does on DynamoDB (PynamoDB's
        ``Model.query()`` default is ``False``) and halves the read capacity
        -- without it the change costs MORE than the dump it replaces."""
        _seed_v1(store, "memory_a", ["x"])
        list_store, prefix_db, _ = patched

        list_store.list_prefix_with_rows("memory_")

        assert prefix_db.prefix_calls == [
            {
                "actor_id": ACTOR,
                "prefix": "list:memory_",
                "keys_only": False,
                "consistent_read": False,
            }
        ]

    def test_one_query_per_call(self, patched, store):
        _seed_v1(store, "memory_a", ["x"])
        _seed_v1(store, "memory_b", ["y"])
        list_store, prefix_db, partition_db = patched

        list_store.list_prefix_with_rows("memory_")

        assert len(prefix_db.prefix_calls) == 1
        assert partition_db.calls == 0, "no partition dump on this path"

    def test_names_and_rows_are_internally_consistent(self, patched, store):
        """Every name has its ``-meta`` row and all its item rows present, so
        a caller can prime each named list from the rows in hand."""
        _seed_v1(store, "memory_a", ["x", "y"])
        _seed_v2(store, "memory_b", ["p", "q", "r"])
        list_store, _, _ = patched

        names, rows = list_store.list_prefix_with_rows("memory_")

        assert sorted(names) == ["memory_a", "memory_b"]
        for name in names:
            assert f"list:{name}-meta" in rows
        assert {n for n in rows if n.startswith("list:memory_a-")} == {
            "list:memory_a-meta",
            "list:memory_a-0",
            "list:memory_a-1",
        }
        assert len([n for n in rows if n.startswith("list:memory_b-#")]) == 3

    def test_it_is_a_prefix_not_a_namespace(self, patched, store):
        """The documented semantics, and the reason the docstring tells
        callers to pass the delimiter."""
        _seed_v1(store, "memory", ["a"])
        _seed_v1(store, "memory_a", ["b"])
        _seed_v1(store, "memory-old", ["c"])
        _seed_v1(store, "notes", ["d"])
        list_store, _, _ = patched

        broad, _ = list_store.list_prefix_with_rows("memory")
        narrow, _ = list_store.list_prefix_with_rows("memory_")

        assert sorted(broad) == ["memory", "memory-old", "memory_a"]
        assert narrow == ["memory_a"]

    def test_a_non_matching_prefix_is_an_ordinary_empty_answer(self, patched, store):
        _seed_v1(store, "notes", ["a"])
        list_store, _, _ = patched

        assert list_store.list_prefix_with_rows("memory_") == ([], {})

    def test_names_are_scoped_too(self, patched, store):
        """Stated as a contract, not a caveat: this is the silent way a
        migration from ``list_all_with_rows()`` goes wrong."""
        _seed_v1(store, "memory_a", ["x"])
        _seed_v1(store, "notes", ["y"])
        list_store, _, _ = patched

        all_names, _ = list_store.list_all_with_rows()
        scoped_names, scoped_rows = list_store.list_prefix_with_rows("memory_")

        assert sorted(all_names) == ["memory_a", "notes"]
        assert scoped_names == ["memory_a"]
        assert not any(n.startswith("list:notes") for n in scoped_rows)

    def test_a_metaless_lists_rows_are_returned_without_a_name(self, patched, store):
        """The half of the (names, rows) invariant that does NOT hold, stated
        deliberately. ``names`` comes from ``-meta`` rows, so item rows whose
        meta row was lost appear in ``rows`` attributed to no name. That is
        exactly what ``list_all_with_rows()`` does today, and matching it is
        the point: pruning them here would silently discard recoverable data
        from a damaged list, and ``rows_for()`` is the tool for narrowing
        rows when a caller actually needs attribution."""
        _seed_v1(store, "memory_a", ["x"])
        _seed_v1(store, "memory_damaged", ["p", "q"])
        del store[(ACTOR, "list:memory_damaged-meta")]
        list_store, _, _ = patched

        names, rows = list_store.list_prefix_with_rows("memory_")

        assert names == ["memory_a"]
        assert "list:memory_damaged-0" in rows
        # And the sibling method behaves identically, which is why this is
        # a contract rather than a defect of the scoped read.
        all_names, all_rows = list_store.list_all_with_rows()
        assert all_names == ["memory_a"]
        assert "list:memory_damaged-0" in all_rows


class TestErrorHandling:
    def test_empty_prefix_raises_and_names_the_right_door(self, patched):
        list_store, prefix_db, _ = patched

        with pytest.raises(ValueError) as excinfo:
            list_store.list_prefix_with_rows("")

        assert "list_all_with_rows()" in str(excinfo.value)
        assert prefix_db.prefix_calls == []

    def test_a_backend_fault_propagates_and_is_not_swallowed(self, monkeypatch, store):
        """The asymmetry with ``list_all_with_rows()``. For a scoped read an
        empty result is the COMMON answer, so ``([], {})`` would present a
        throttled query as "you have no memories"."""
        monkeypatch.setattr(
            "actingweb.property.get_property",
            lambda config: FakePrefixDb(store, fail=True),
        )
        list_store = PropertyListStore(actor_id=ACTOR, config=object())

        with pytest.raises(DbError):
            list_store.list_prefix_with_rows("memory_")

    def test_list_all_with_rows_still_swallows(self, monkeypatch, store):
        """The sibling's behaviour is unchanged -- the asymmetry is chosen,
        not drift."""
        monkeypatch.setattr(
            "actingweb.property.get_property_list",
            lambda config: FakePartitionDb(store, fail=True),
        )
        list_store = PropertyListStore(actor_id=ACTOR, config=object())

        assert list_store.list_all_with_rows() == ([], {})


class TestListAllIsUnchanged:
    def test_same_query_count_and_same_results(self, patched, store):
        _seed_v1(store, "memory_a", ["x"])
        _seed_v2(store, "notes", ["y"])
        list_store, prefix_db, partition_db = patched

        names = list_store.list_all()
        names_with_rows, rows = list_store.list_all_with_rows()

        assert sorted(names) == ["memory_a", "notes"]
        assert sorted(names_with_rows) == ["memory_a", "notes"]
        assert set(rows) == {name for (_aid, name) in store}
        assert partition_db.calls == 2
        assert prefix_db.prefix_calls == [], (
            "list_all* must not have been rerouted through the prefix read"
        )


class TestRowsFor:
    """A bare ``startswith(f"list:{name}-")`` is the wrong implementation and
    these are the cases that show it. Used to PRUNE, it strips a permitted
    sibling's item rows while keeping its ``-meta`` row, and
    ``to_list_from_rows()`` then reports the permitted list as empty."""

    def _all_rows(self, store, actor_id=ACTOR):
        return {name: value for (aid, name), value in store.items() if aid == actor_id}

    def test_a_sibling_keeps_all_of_its_own_rows_v1(self, store):
        _seed_v1(store, "foo", ["a", "b"])
        _seed_v1(store, "foo-old", ["p", "q", "r"])
        rows = self._all_rows(store)

        kept = rows_for(["foo-old"], rows)

        assert set(kept) == {
            "list:foo-old-meta",
            "list:foo-old-0",
            "list:foo-old-1",
            "list:foo-old-2",
        }

    def test_a_sibling_keeps_all_of_its_own_rows_v2(self, store):
        _seed_v2(store, "foo", ["a", "b"])
        _seed_v2(store, "foo-old", ["p", "q", "r"])
        rows = self._all_rows(store)

        kept = rows_for(["foo-old"], rows)

        assert "list:foo-old-meta" in kept
        assert len([n for n in kept if n.startswith("list:foo-old-#")]) == 3
        assert not any(n.startswith("list:foo-#") for n in kept), (
            "none of foo's rows may be claimed by foo-old"
        )

    def test_asking_for_foo_does_not_claim_foo_olds_rows(self, store):
        _seed_v1(store, "foo", ["a", "b"])
        _seed_v1(store, "foo-old", ["p", "q"])
        rows = self._all_rows(store)

        kept = rows_for(["foo"], rows)

        assert set(kept) == {"list:foo-meta", "list:foo-0", "list:foo-1"}

    def test_a_digit_named_sibling_is_separated_by_the_shape_check(self, store):
        """``foo-5``'s row ``list:foo-5-0`` starts with ``list:foo-`` and its
        suffix ``5-0`` fails ``_V1_INDEX_RE`` -- the same shape check every
        reader in property_list.py applies."""
        _seed_v1(store, "foo", ["a"])
        _seed_v1(store, "foo-5", ["p", "q"])
        rows = self._all_rows(store)

        assert set(rows_for(["foo"], rows)) == {"list:foo-meta", "list:foo-0"}
        assert set(rows_for(["foo-5"], rows)) == {
            "list:foo-5-meta",
            "list:foo-5-0",
            "list:foo-5-1",
        }

    def test_both_siblings_together_lose_nothing(self, store):
        _seed_v1(store, "foo", ["a"])
        _seed_v1(store, "foo-5", ["p", "q"])
        rows = self._all_rows(store)

        kept = rows_for(["foo", "foo-5"], rows)

        assert set(kept) == set(rows)

    def test_rows_of_unnamed_lists_are_dropped(self, store):
        _seed_v1(store, "foo", ["a"])
        _seed_v1(store, "bar", ["b"])
        rows = self._all_rows(store)

        assert set(rows_for(["foo"], rows)) == {"list:foo-meta", "list:foo-0"}

    def test_no_names_keeps_nothing(self, store):
        _seed_v1(store, "foo", ["a"])
        assert rows_for([], self._all_rows(store)) == {}

    def test_a_legacy_hash_named_list_is_not_claimed_as_a_v2_row(self, store):
        """A list created before the ``#`` name ban and named ``foo-#bar``
        stores ``list:foo-#bar-0``, which starts with v2 list ``foo``'s item
        prefix. Its suffix ``bar-0`` is not a base62 rank (``-`` is not in
        the alphabet), so ``_v2_is_rank()`` rejects it."""
        _seed_v2(store, "foo", ["a", "b"])
        _seed_v1(store, "foo-#bar", ["legacy"])
        rows = self._all_rows(store)

        kept = rows_for(["foo"], rows)

        assert "list:foo-#bar-0" not in kept
        assert "list:foo-#bar-meta" not in kept
        assert "list:foo-meta" in kept
        assert len([n for n in kept if n.startswith("list:foo-#")]) == 2

    def test_the_result_can_be_primed_back_into_a_list(self, store, monkeypatch):
        """The point of the helper: what survives must still read as the
        list's real contents, not as ``[]``."""
        from actingweb.property_list import ListProperty

        _seed_v1(store, "foo", ["a", "b"])
        _seed_v1(store, "foo-old", ["p", "q", "r"])
        monkeypatch.setattr(
            "actingweb.property_list.get_property",
            lambda config: FakePrefixDb(store),
        )

        kept = rows_for(["foo-old"], self._all_rows(store))
        prop = ListProperty(actor_id=ACTOR, name="foo-old", config=object())

        assert prop.to_list_from_rows(kept) == ["p", "q", "r"]
