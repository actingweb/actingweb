"""Integrity regression tests for ListProperty's error-handling contract.

Uses a dict-backed fake patched onto ``actingweb.property_list.get_property``
-- NOT the config-attribute ``Mock`` pattern used in the sibling
``test_property_list.py`` -- because ``ListProperty`` takes a FRESH
``DbProperty`` handle per operation (one ``get_property(config)`` call per
get/set). A ``Mock(..., side_effect=[...])`` list exhausts after the first
few calls; a dict-backed fake shared across fresh instances behaves like
real storage and lets failures be injected by property name or by call
count.

These tests pin the Phase 1 contract from
thoughts/plans/2026-08-08-property-list-index-integrity.md: backend read
faults propagate as ``DbError`` instead of being swallowed as absence, and
backend write failures (``set()`` returning ``False``) raise ``RuntimeError``
instead of being silently ignored. The crash-injection test documents the
shift-loop's non-atomicity, which Phase 1 does NOT fix (that is Phase 4's
fractional-key rewrite) -- it only makes the failure loud instead of silent.
See thoughts/todo/property-list-delete-leaves-holes.md for the residue
patterns being pinned here.
"""

import json

import pytest

from actingweb.db.exceptions import DbError
from actingweb.property_list import ListCorruptionError, ListProperty


class FakePropertyDb:
    """Minimal DbPropertyProtocol fake backed by a shared dict.

    ``store`` and the failure sets are shared by reference across every
    instance the patched factory returns, so mutations and injected
    failures stay visible across the many fresh handles ListProperty takes
    per operation.
    """

    def __init__(self, store, fail_get_on=None, fail_set_on=None):
        self.store = store
        self.fail_get_on = fail_get_on if fail_get_on is not None else set()
        self.fail_set_on = fail_set_on if fail_set_on is not None else set()
        self.handle = None

    def get(self, actor_id=None, name=None):
        if name in self.fail_get_on:
            raise DbError("property read", actor_id)
        return self.store.get((actor_id, name))

    def set(self, actor_id=None, name=None, value=None):
        if name in self.fail_set_on:
            return False
        if value is None or (hasattr(value, "__len__") and len(value) == 0):
            self.store.pop((actor_id, name), None)
            return True
        self.store[(actor_id, name)] = value
        return True

    def get_actor_id_from_property(self, name=None, value=None):
        return None

    def delete(self):
        return True

    def get_range(self, actor_id=None, lower=None, upper=None, keys_only=False):
        result = {}
        for (aid, name), value in self.store.items():
            if aid != actor_id:
                continue
            if lower <= name <= upper:
                result[name] = "" if keys_only else value
        return result

    def create_if_not_exists(self, actor_id=None, name=None, value=None):
        if name in self.fail_set_on:
            return False
        if (actor_id, name) in self.store:
            return False
        self.store[(actor_id, name)] = value
        return True


class CrashInjectingPropertyDb(FakePropertyDb):
    """Simulates a hard interruption (process death, timeout) after a fixed
    number of successful backend calls, regardless of which name is
    targeted.

    Unlike ``FakePropertyDb``'s per-name failure injection, this models an
    abrupt discontinuation at an arbitrary point in a call sequence -- the
    kind of interruption that forms the holes and duplicates documented in
    thoughts/todo/property-list-delete-leaves-holes.md.
    """

    def __init__(self, store, calls_before_crash, call_counter):
        super().__init__(store)
        self.calls_before_crash = calls_before_crash
        self.call_counter = call_counter  # shared mutable [int]

    def _tick(self):
        self.call_counter[0] += 1
        if self.call_counter[0] > self.calls_before_crash:
            raise DbError("property write", None)

    def get(self, actor_id=None, name=None):
        self._tick()
        return super().get(actor_id=actor_id, name=name)

    def set(self, actor_id=None, name=None, value=None):
        self._tick()
        return super().set(actor_id=actor_id, name=name, value=value)


@pytest.fixture
def fake_store():
    return {}


def _patch_get_property(monkeypatch, factory):
    monkeypatch.setattr("actingweb.property_list.get_property", factory)


def _seed_list(store, actor_id, name, items):
    """Seed a v1-format list directly, bypassing ListProperty so no failure
    injection is active while seeding."""
    for i, item in enumerate(items):
        store[(actor_id, f"list:{name}-{i}")] = json.dumps(item)
    meta = {
        "length": len(items),
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "item_type": "json",
        "chunk_size": 1,
        "version": "1.0",
        "description": "",
        "explanation": "",
    }
    store[(actor_id, f"list:{name}-meta")] = json.dumps(meta)


def _meta_length(store, actor_id, name):
    return json.loads(store[(actor_id, f"list:{name}-meta")])["length"]


class TestDeleteReadFailurePropagates:
    """A backend read fault during the __delitem__ shift must propagate as
    DbError, not be swallowed into a silent skip."""

    def test_read_error_mid_shift_propagates_and_preserves_successor(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-read-fail"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c", "d"])

        _patch_get_property(
            monkeypatch,
            lambda config: FakePropertyDb(fake_store, fail_get_on={f"list:{name}-2"}),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(DbError):
            del prop_list[0]

        # length must NOT have been decremented: the meta write never ran.
        assert _meta_length(fake_store, actor_id, name) == 4

        # Rows past the failure point are untouched.
        assert fake_store[(actor_id, f"list:{name}-2")] == json.dumps("c")
        assert fake_store[(actor_id, f"list:{name}-3")] == json.dumps("d")

        # The shift step that completed before the failure (i=1 -> slot 0).
        assert fake_store[(actor_id, f"list:{name}-0")] == json.dumps("b")
        # The hole this leaves at the interruption point is real -- Phase 1
        # makes the failure loud, it does not make the shift atomic.
        assert (actor_id, f"list:{name}-1") not in fake_store


class TestWriteFailureRaisesRuntimeError:
    """A backend write fault (set() returning False, as PostgreSQL does on
    error) must raise RuntimeError, not be silently ignored."""

    def test_append_write_failure_raises_and_meta_unchanged(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-append-fail"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b"])

        _patch_get_property(
            monkeypatch,
            lambda config: FakePropertyDb(fake_store, fail_set_on={f"list:{name}-2"}),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(RuntimeError, match="write failed"):
            prop_list.append("c")

        assert _meta_length(fake_store, actor_id, name) == 2
        assert (actor_id, f"list:{name}-2") not in fake_store

    def test_setitem_write_failure_raises_and_item_unchanged(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-setitem-fail"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])

        _patch_get_property(
            monkeypatch,
            lambda config: FakePropertyDb(fake_store, fail_set_on={f"list:{name}-1"}),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(RuntimeError, match="write failed"):
            prop_list[1] = "updated-b"

        assert fake_store[(actor_id, f"list:{name}-1")] == json.dumps("b")

    def test_delitem_write_failure_raises_and_meta_unchanged(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-delitem-fail"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c", "d"])

        # Fail the delete-old-position write for shift step i=1 (its move to
        # slot 0 has already succeeded by then).
        _patch_get_property(
            monkeypatch,
            lambda config: FakePropertyDb(fake_store, fail_set_on={f"list:{name}-1"}),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(RuntimeError, match="write failed"):
            del prop_list[0]

        assert _meta_length(fake_store, actor_id, name) == 4


class TestCrashInjectionResidue:
    """Documents the shift loop's non-atomicity ahead of the Phase 4
    fractional-key rewrite: an interruption between the move-write and the
    delete-of-old-position write leaves an exact duplicate with `length`
    still one too high -- one of the three residue shapes catalogued in
    thoughts/todo/property-list-delete-leaves-holes.md."""

    def test_crash_between_move_and_delete_leaves_duplicate(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-crash"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c", "d"])

        call_counter = [0]
        # Call sequence for del prop_list[0]:
        #   1. meta get (len())
        #   2. delete item at index 0
        #   3. get item at index 1 ("b")
        #   4. move: set item at index 0 <- "b"
        #   5. delete item at index 1   <-- crashes here
        _patch_get_property(
            monkeypatch,
            lambda config: CrashInjectingPropertyDb(
                fake_store, calls_before_crash=4, call_counter=call_counter
            ),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(DbError):
            del prop_list[0]

        # The residue signature: length one too high (never decremented).
        assert _meta_length(fake_store, actor_id, name) == 4

        # Exact duplicate: both slot 0 (moved) and slot 1 (never cleared)
        # hold the value that was at index 1 before the shift began.
        assert fake_store[(actor_id, f"list:{name}-0")] == json.dumps("b")
        assert fake_store[(actor_id, f"list:{name}-1")] == json.dumps("b")

        # Rows the loop never reached are untouched.
        assert fake_store[(actor_id, f"list:{name}-2")] == json.dumps("c")
        assert fake_store[(actor_id, f"list:{name}-3")] == json.dumps("d")


class TestUnparsableMetadataRaises:
    """Unparsable/non-dict metadata must raise ValueError, not self-heal by
    overwriting it with a fresh `length: 0` default -- the old behaviour
    orphaned every existing item row with no way back to them."""

    def test_invalid_json_raises_and_row_untouched(self, monkeypatch, fake_store):
        actor_id = "actor-badmeta"
        name = "mylist"
        fake_store[(actor_id, f"list:{name}-meta")] = "{not valid json"
        fake_store[(actor_id, f"list:{name}-0")] = json.dumps("a")

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(ValueError, match="Unparsable metadata"):
            len(prop_list)

        # The bad row was never rewritten with a fresh default.
        assert fake_store[(actor_id, f"list:{name}-meta")] == "{not valid json"
        assert fake_store[(actor_id, f"list:{name}-0")] == json.dumps("a")

    def test_non_dict_json_raises_and_row_untouched(self, monkeypatch, fake_store):
        actor_id = "actor-badmeta2"
        name = "mylist"
        fake_store[(actor_id, f"list:{name}-meta")] = json.dumps([1, 2, 3])

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(ValueError, match="not a JSON object"):
            len(prop_list)

        assert fake_store[(actor_id, f"list:{name}-meta")] == json.dumps([1, 2, 3])


class TestFailFastReads:
    """to_list()/slice()/to_list_from_rows() raise ListCorruptionError on a
    hole instead of silently compacting past it (Phase 3). __getitem__
    distinguishes a genuine out-of-range IndexError from a
    ListCorruptionError (in-range but missing) -- these tests pin that
    distinction too."""

    def test_getitem_in_range_hole_raises_list_corruption_error(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-ff-1"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        del fake_store[(actor_id, f"list:{name}-1")]

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(ListCorruptionError):
            _ = prop_list[1]

    def test_getitem_out_of_range_raises_plain_index_error_not_corruption(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-ff-2"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(IndexError) as exc_info:
            _ = prop_list[5]
        assert not isinstance(exc_info.value, ListCorruptionError)

    def test_to_list_raises_on_hole(self, monkeypatch, fake_store):
        actor_id = "actor-ff-3"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        del fake_store[(actor_id, f"list:{name}-1")]

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        with pytest.raises(ListCorruptionError):
            prop_list.to_list()

    def test_slice_raises_on_hole_within_range(self, monkeypatch, fake_store):
        actor_id = "actor-ff-4"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c", "d"])
        del fake_store[(actor_id, f"list:{name}-2")]

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        # The hole is outside this slice -- must succeed.
        assert prop_list.slice(0, 2) == ["a", "b"]

        # The hole is inside this slice -- must raise.
        with pytest.raises(ListCorruptionError):
            prop_list.slice(1, 4)

    def test_to_list_from_rows_raises_on_hole_missing_from_both(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-ff-5"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        del fake_store[(actor_id, f"list:{name}-1")]

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        # A row present in the pre-fetched mapping is served from it even
        # if storage itself has since diverged.
        rows = {
            f"list:{name}-0": json.dumps("a"),
            f"list:{name}-1": json.dumps("b"),
            f"list:{name}-2": json.dumps("c"),
        }
        assert prop_list.to_list_from_rows(rows) == ["a", "b", "c"]

        # Missing from the mapping AND from storage -- falls back to
        # __getitem__, which raises.
        with pytest.raises(ListCorruptionError):
            prop_list.to_list_from_rows({f"list:{name}-0": json.dumps("a")})

    def test_to_indexed_list_shape(self, monkeypatch, fake_store):
        actor_id = "actor-ff-6"
        name = "mylist"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        assert prop_list.to_indexed_list() == [(0, "a"), (1, "b"), (2, "c")]


class CountingPropertyDb(FakePropertyDb):
    """Counts get_range() calls -- the query-count guard's instrument."""

    def __init__(self, store):
        super().__init__(store)
        self.range_call_count = 0

    def get_range(self, actor_id=None, lower=None, upper=None, keys_only=False):
        self.range_call_count += 1
        return super().get_range(
            actor_id=actor_id, lower=lower, upper=upper, keys_only=keys_only
        )


class StaleReadPropertyDb(FakePropertyDb):
    """Simulates a genuine rank-key race: get_range() returns a stale
    (pre-write) snapshot on its FIRST call only, but create_if_not_exists()
    always sees the real, already-written store -- modeling two writers
    whose read happened before the other's write landed."""

    def __init__(self, store, stale_missing_name):
        super().__init__(store)
        self.stale_missing_name = stale_missing_name
        self.get_range_calls = 0

    def get_range(self, actor_id=None, lower=None, upper=None, keys_only=False):
        self.get_range_calls += 1
        result = super().get_range(
            actor_id=actor_id, lower=lower, upper=upper, keys_only=keys_only
        )
        if self.get_range_calls == 1:
            result.pop(self.stale_missing_name, None)
        return result


class TestV2NewListDefaultsAndValidation:
    """New (format-2) lists are the default as of Phase 4; '#' is reserved
    and rejected in NEW list names, but an existing (seeded) v1 or v2 list
    already named with a '#' stays readable -- Phase 4 only blocks NEW
    offenders, it doesn't touch legacy data."""

    def test_new_list_is_format_2(self, monkeypatch, fake_store):
        actor_id = "actor-v2-new"
        name = "brandnew"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        prop_list.append("first")

        assert prop_list.verify()["format"] == 2
        meta = json.loads(fake_store[(actor_id, f"list:{name}-meta")])
        assert meta["format"] == 2
        assert "length" not in meta

    def test_hash_in_new_list_name_raises(self, monkeypatch, fake_store):
        actor_id = "actor-v2-hash"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name="foo#bar", config=object())

        with pytest.raises(ValueError, match="cannot contain"):
            prop_list.append("x")

    def test_existing_v1_list_with_hash_in_name_stays_readable(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-v2-hash-legacy"
        name = "legacy#list"
        # Seeded directly, bypassing the name-validation check ListProperty
        # only applies to brand-new lists -- this is what an already-migrated
        # or pre-Phase-4 list named this way looks like.
        _seed_list(fake_store, actor_id, name, ["a", "b"])

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        assert prop_list.to_list() == ["a", "b"]


class TestV2QueryCountGuard:
    def test_to_list_after_append_is_one_range_query(self, monkeypatch, fake_store):
        actor_id = "actor-v2-qc"
        name = "qc"
        fake_db = CountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        for item in ["a", "b", "c"]:
            prop_list.append(item)

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        fake_db.range_call_count = 0
        assert fresh.to_list() == ["a", "b", "c"]
        assert fake_db.range_call_count == 1


class TestV2ConditionalWriteCollision:
    def test_append_retries_on_rank_collision(self, monkeypatch, fake_store):
        actor_id = "actor-v2-collision"
        name = "mylist"
        # Pre-occupy the rank the very first append() on an empty list
        # would naturally generate.
        fake_store[(actor_id, "list:mylist-#a0")] = json.dumps("existing-item")

        fake_db = StaleReadPropertyDb(fake_store, stale_missing_name="list:mylist-#a0")
        _patch_get_property(monkeypatch, lambda config: fake_db)
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        prop_list.append("new-item")

        # The stale first read didn't see "a0", so the first candidate
        # collided; a fresh reread on retry found it and generated past it.
        assert fake_db.get_range_calls >= 2
        assert prop_list.to_list() == ["existing-item", "new-item"]
        assert fake_store[(actor_id, "list:mylist-#a0")] == json.dumps("existing-item")

    def test_insert_retries_on_rank_collision(self, monkeypatch, fake_store):
        actor_id = "actor-v2-collision-2"
        name = "mylist"
        fake_store[(actor_id, "list:mylist-#a0")] = json.dumps("first")
        fake_store[(actor_id, "list:mylist-#a1")] = json.dumps("last")

        import fractional_indexing as fi

        between = fi.generate_key_between("a0", "a1")
        fake_store[(actor_id, f"list:mylist-#{between}")] = json.dumps("already-there")

        fake_db = StaleReadPropertyDb(
            fake_store, stale_missing_name=f"list:mylist-#{between}"
        )
        _patch_get_property(monkeypatch, lambda config: fake_db)
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        prop_list.insert(1, "inserted")

        assert fake_db.get_range_calls >= 2
        assert prop_list.to_list() == ["first", "inserted", "already-there", "last"]


class TestV2RankCapAndCompact:
    def test_insert_between_raises_past_cap_and_compact_rebalances(
        self, monkeypatch, fake_store
    ):
        import fractional_indexing as fi

        actor_id = "actor-v2-cap"
        name = "capped"

        # Build a lo/hi pair via real bisection until a further bisection
        # between them would exceed the 180-char cap.
        lo, hi = "a0", "a1"
        k = lo
        while len(k) <= 180:
            k = fi.generate_key_between(lo, hi)
            lo = k
        assert len(fi.generate_key_between(lo, hi)) > 180  # sanity on the setup

        fake_store[(actor_id, f"list:{name}-#{lo}")] = json.dumps("left")
        fake_store[(actor_id, f"list:{name}-#{hi}")] = json.dumps("right")

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        assert prop_list.to_list() == ["left", "right"]

        with pytest.raises(RuntimeError, match="rank key exceeded"):
            prop_list.insert(1, "overflow")

        # Not written -- the list is unchanged.
        assert prop_list.to_list() == ["left", "right"]

        report = prop_list.compact()
        assert report["format"] == 2

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == ["left", "right"]
        assert fresh.verify()["max_rank_length"] < 10

        # Ranks are short again -- insert-between works now.
        fresh.insert(1, "middle")
        assert fresh.to_list() == ["left", "middle", "right"]
