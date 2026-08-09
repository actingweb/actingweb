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

    def delete_if_value_equals(self, actor_id=None, name=None, value=None):
        if name in self.fail_set_on:
            return False
        if self.store.get((actor_id, name)) != value:
            return False
        del self.store[(actor_id, name)]
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

        # This test pins the v1 shift loop's crash residue, and injects the
        # crash by absolute call number. A 4-item v1 list is a lazy-migration
        # candidate, so __delitem__ would first attempt migrate_to_v2() (which
        # fails harmlessly here and is swallowed) -- but its metadata reads
        # land in the same counter and shift the crash point. Disable it so
        # the sequence below describes only the shift loop.
        monkeypatch.setattr(ListProperty, "_maybe_lazy_migrate", lambda self: None)

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


def _seed_v2_list(store, actor_id, name, items):
    """Seed a v2-format list directly (evenly spaced ranks + meta row)."""
    import fractional_indexing as fi

    ranks = fi.generate_n_keys_between(None, None, len(items))
    for rank, item in zip(ranks, items, strict=True):
        store[(actor_id, f"list:{name}-#{rank}")] = json.dumps(item)
    store[(actor_id, f"list:{name}-meta")] = json.dumps(
        {
            "format": 2,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "",
            "explanation": "",
        }
    )


class TestV2LegacyHashSiblingIsolation:
    """A v2 list's byte range is NOT sufficient to isolate its rows.

    New list names may not contain '#', but lists created before Phase 4
    may, and migration deliberately refuses them so they keep serving as
    v1 forever. Such a list's rows -- e.g. 'list:foo-#bar-0' for a legacy
    list named 'foo-#bar' -- sort INSIDE the range ['list:foo-#',
    'list:foo-$'] that a new v2 list named 'foo' reads. Only the rank-shape
    check (_v2_is_rank) keeps the two apart. Regression for the P1 raised
    on PR #121.
    """

    LEGACY = "foo-#bar"
    OWNER = "foo"

    def _seed_both(self, store, actor_id):
        _seed_list(store, actor_id, self.LEGACY, ["legacy-a", "legacy-b"])
        _seed_v2_list(store, actor_id, self.OWNER, ["mine-1", "mine-2"])

    def _legacy_rows(self, store, actor_id):
        return {
            k: v
            for k, v in store.items()
            if k[0] == actor_id and k[1].startswith(f"list:{self.LEGACY}-")
        }

    def test_reads_exclude_legacy_sibling_rows(self, monkeypatch, fake_store):
        actor_id = "actor-sib-read"
        self._seed_both(fake_store, actor_id)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        owner = ListProperty(actor_id=actor_id, name=self.OWNER, config=object())
        assert owner.to_list() == ["mine-1", "mine-2"]
        assert len(owner) == 2
        assert list(owner) == ["mine-1", "mine-2"]
        assert owner.verify()["length"] == 2

        legacy = ListProperty(actor_id=actor_id, name=self.LEGACY, config=object())
        assert legacy.to_list() == ["legacy-a", "legacy-b"]

    def test_primed_reads_exclude_legacy_sibling_rows(self, monkeypatch, fake_store):
        actor_id = "actor-sib-prime"
        self._seed_both(fake_store, actor_id)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        # A bulk partition dump contains BOTH lists' rows -- the primed path
        # matches row names in Python, so it needs the same filter as the
        # range-query path.
        rows = {
            name: value for (aid, name), value in fake_store.items() if aid == actor_id
        }
        owner = ListProperty(actor_id=actor_id, name=self.OWNER, config=object())
        owner.prime_from_rows(rows)

        assert len(owner) == 2
        assert owner.to_list_from_rows(rows) == ["mine-1", "mine-2"]

    def test_clear_does_not_delete_legacy_sibling_rows(self, monkeypatch, fake_store):
        actor_id = "actor-sib-clear"
        self._seed_both(fake_store, actor_id)
        before = self._legacy_rows(fake_store, actor_id)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        ListProperty(actor_id=actor_id, name=self.OWNER, config=object()).clear()

        assert self._legacy_rows(fake_store, actor_id) == before
        legacy = ListProperty(actor_id=actor_id, name=self.LEGACY, config=object())
        assert legacy.to_list() == ["legacy-a", "legacy-b"]

    def test_delete_does_not_delete_legacy_sibling_rows(self, monkeypatch, fake_store):
        actor_id = "actor-sib-delete"
        self._seed_both(fake_store, actor_id)
        before = self._legacy_rows(fake_store, actor_id)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        ListProperty(actor_id=actor_id, name=self.OWNER, config=object()).delete()

        assert self._legacy_rows(fake_store, actor_id) == before

    def test_migration_of_owner_does_not_clear_legacy_sibling_rows(
        self, monkeypatch, fake_store
    ):
        """migrate_to_v2()'s step-3 'clear leftover v2 scratch rows' runs a
        range query too -- unfiltered, it would wipe the legacy sibling."""
        actor_id = "actor-sib-migrate"
        _seed_list(fake_store, actor_id, self.LEGACY, ["legacy-a", "legacy-b"])
        _seed_list(fake_store, actor_id, self.OWNER, ["mine-1", "mine-2"])
        before = self._legacy_rows(fake_store, actor_id)

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        owner = ListProperty(actor_id=actor_id, name=self.OWNER, config=object())
        assert owner.migrate_to_v2()["migrated"] is True

        assert owner.to_list() == ["mine-1", "mine-2"]
        assert self._legacy_rows(fake_store, actor_id) == before


class _FakePropertyList:
    """Minimal DbPropertyList fake: one partition dump for verify()."""

    def __init__(self, store):
        self.store = store

    def fetch_all_including_lists(self, actor_id=None):
        return {
            name: value for (aid, name), value in self.store.items() if aid == actor_id
        }


class TestMigrateToV2StaleMetadata:
    """migrate_to_v2() must never decide 'this list is v1' from a cached
    metadata dict. Regression for the P1 raised on PR #121: a stale v1
    cache over already-migrated v2 storage sent migration down the v1
    path, where verify() sees every index as a hole, so step 3 deleted the
    authoritative v2 rows and step 4 wrote an empty list over them."""

    def test_stale_v1_cache_over_v2_storage_does_not_destroy_rows(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-stale-meta"
        name = "notes"

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        # The instance loaded metadata while the list was still v1...
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        stale = ListProperty(actor_id=actor_id, name=name, config=object())
        assert stale.to_list() == ["a", "b", "c"]  # populates _meta_cache as v1

        # ...and another writer migrated it in the meantime.
        for i in range(3):
            fake_store.pop((actor_id, f"list:{name}-{i}"), None)
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        rows_after_migration = dict(fake_store)

        result = stale.migrate_to_v2()

        assert result == {"migrated": False, "reason": "already_v2"}
        assert fake_store == rows_after_migration
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == ["a", "b", "c"]


class TestV2StaleRankCacheOnPositionalMutation:
    """Destructive positional operations must re-read the rank keys.

    A cached rank list can be arbitrarily old on a long-lived instance; if
    another writer inserted an item earlier in the list, position i names a
    different row than the cache says, and del/setitem would destroy the
    wrong item. Regression for the P1 raised on PR #121.
    """

    def test_delitem_deletes_the_item_currently_at_that_position(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-stale-rank-del"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        stale = ListProperty(actor_id=actor_id, name=name, config=object())
        stale.extend(["a", "b", "c"])
        assert stale.to_list() == ["a", "b", "c"]  # rank cache warm

        # Another instance inserts at the front.
        other = ListProperty(actor_id=actor_id, name=name, config=object())
        other.insert(0, "x")
        assert other.to_list() == ["x", "a", "b", "c"]

        del stale[1]

        # Position 1 is "a" as of now -- NOT "b", which is what the stale
        # cache would have pointed at.
        assert ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list() == ["x", "b", "c"]

    def test_setitem_overwrites_the_item_currently_at_that_position(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-stale-rank-set"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        stale = ListProperty(actor_id=actor_id, name=name, config=object())
        stale.extend(["a", "b", "c"])
        assert stale.to_list() == ["a", "b", "c"]

        other = ListProperty(actor_id=actor_id, name=name, config=object())
        other.insert(0, "x")

        stale[1] = "REPLACED"

        assert ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list() == ["x", "REPLACED", "b", "c"]


class TestV2StaleRankCacheOnPositionalRead:
    """Positional READS must not resolve through a stale rank map either.

    The cached rank at position i still exists after another writer inserts
    earlier in the list, so `_v2_getitem`'s missing-row fallback never fires
    and the read silently returns the item that used to be at that position.
    v1's positional read is always current, and v2 should not be weaker.
    Regression for the second-round P1 on PR #121.
    """

    def test_getitem_returns_the_item_currently_at_that_position(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-stale-read-get"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        stale = ListProperty(actor_id=actor_id, name=name, config=object())
        stale.extend(["a", "b", "c"])
        assert stale.to_list() == ["a", "b", "c"]  # rank cache warm

        ListProperty(actor_id=actor_id, name=name, config=object()).insert(0, "x")

        # Position 1 is "a" now, not the cached "b".
        assert stale[1] == "a"

    def test_pop_returns_exactly_what_it_removed(self, monkeypatch, fake_store):
        """pop() resolved the rank twice -- once for the read, once for the
        delete -- so a concurrent mutation in between made it return one item
        and delete a different one."""
        actor_id = "actor-stale-read-pop"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        stale = ListProperty(actor_id=actor_id, name=name, config=object())
        stale.extend(["a", "b", "c"])
        assert stale.to_list() == ["a", "b", "c"]

        ListProperty(actor_id=actor_id, name=name, config=object()).insert(0, "x")
        # Storage is now ["x", "a", "b", "c"].

        popped = stale.pop(1)

        remaining = ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list()
        assert popped == "a"
        assert remaining == ["x", "b", "c"]
        assert popped not in remaining, "pop() must remove exactly the item it returned"

    def test_index_finds_the_current_position(self, monkeypatch, fake_store):
        actor_id = "actor-stale-read-index"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        stale = ListProperty(actor_id=actor_id, name=name, config=object())
        stale.extend(["a", "b", "c"])
        assert stale.to_list() == ["a", "b", "c"]

        ListProperty(actor_id=actor_id, name=name, config=object()).insert(0, "x")

        assert stale.index("a") == 1
        assert stale.index("x") == 0

    def test_remove_deletes_the_item_it_matched(self, monkeypatch, fake_store):
        """remove() found a position by iterating a snapshot, then deleted by
        that position after a refresh -- so a concurrent mutation in between
        made it delete whatever sat there now. Same shape as the pop() bug,
        one method over; found by applying the same reasoning rather than by
        review."""
        actor_id = "actor-stale-read-remove"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        stale = ListProperty(actor_id=actor_id, name=name, config=object())
        stale.extend(["a", "b", "c"])
        assert stale.to_list() == ["a", "b", "c"]

        other = ListProperty(actor_id=actor_id, name=name, config=object())

        # Interleave a front-insert between remove()'s scan and its delete.
        original_load = ListProperty._v2_load_full
        fired = []

        def _insert_after_scan(self):
            pairs = original_load(self)
            if not fired:
                fired.append(True)
                other.insert(0, "x")
            return pairs

        monkeypatch.setattr(ListProperty, "_v2_load_full", _insert_after_scan)
        stale.remove("b")
        monkeypatch.setattr(ListProperty, "_v2_load_full", original_load)

        # "b" is gone and nothing else is: deleting by rank removes exactly
        # the matched item regardless of how positions shifted.
        assert ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list() == ["x", "a", "c"]


class TestLazyMigrationRefusesDamagedLists:
    """Lazy migration must never silently repair a damaged list.

    migrate_to_v2() closes holes in flight and REPORTS what it closed --
    right for an operator running the script and reading the output. Doing
    it under an ordinary append() destroys the evidence instead: the hole
    disappears, the lost item stays lost, duplicate residue is promoted to
    real data, verify() starts saying healthy, and the report naming any of
    it is thrown away by _maybe_lazy_migrate(). Raised by a downstream
    consumer (actingweb_mcp) against 4a7d8b2 with a production-shaped
    fixture.
    """

    def test_damaged_v1_list_stays_v1_on_append(self, monkeypatch, fake_store):
        actor_id = "actor-damaged-lazy"
        name = "damaged"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        # Punch a hole: metadata still claims 3 items, row 1 is gone.
        del fake_store[(actor_id, f"list:{name}-1")]

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        prop_list.append("d")

        # Still v1, still damaged, still reporting it.
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        report = fresh.verify()
        assert report.get("format") != 2
        assert report["missing_indices"] == [1]
        assert report["healthy"] is False
        # And the corruption is still surfaced to readers.
        with pytest.raises(ListCorruptionError):
            fresh.to_list()

    def test_healthy_v1_list_still_migrates_on_append(self, monkeypatch, fake_store):
        actor_id = "actor-healthy-lazy"
        name = "healthy"
        _seed_list(fake_store, actor_id, name, ["a", "b"])

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        ListProperty(actor_id=actor_id, name=name, config=object()).append("c")

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.verify()["format"] == 2
        assert fresh.to_list() == ["a", "b", "c"]


class TestLazyMigrationThresholdIsConfigurable:
    """Migration is inline and synchronous, so an operator must be able to
    keep it out of user requests entirely and sweep with the script."""

    def test_zero_disables_lazy_migration(self, monkeypatch, fake_store):
        actor_id = "actor-lazy-off"
        name = "small"
        _seed_list(fake_store, actor_id, name, ["a"])

        monkeypatch.setenv("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH", "0")
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        ListProperty(actor_id=actor_id, name=name, config=object()).append("b")

        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.verify().get("format") != 2
        assert fresh.to_list() == ["a", "b"]

    def test_raised_limit_migrates_a_bigger_list(self, monkeypatch, fake_store):
        actor_id = "actor-lazy-big"
        name = "big"
        _seed_list(fake_store, actor_id, name, [f"i{n}" for n in range(60)])

        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        # Default limit is 50 -- a 60-item list is left alone.
        ListProperty(actor_id=actor_id, name=name, config=object()).append("x")
        assert (
            ListProperty(actor_id=actor_id, name=name, config=object())
            .verify()
            .get("format")
            != 2
        )

        monkeypatch.setenv("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH", "100")
        ListProperty(actor_id=actor_id, name=name, config=object()).append("y")
        assert (
            ListProperty(actor_id=actor_id, name=name, config=object()).verify()[
                "format"
            ]
            == 2
        )


class TestIndexNegativeBounds:
    """index()'s start/stop follow list.index semantics, identically before
    and after migration -- a list must answer the same question in both
    formats."""

    @staticmethod
    def _cases(prop_list):
        return [
            (("a",), 0),
            (("a", 1), 2),
            (("a", -1), 2),
            (("a", -2), 2),
            (("b", 0, -1), 1),
        ]

    def test_v2_matches_python_list(self, monkeypatch, fake_store):
        actor_id = "actor-index-v2"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name="idx", config=object())
        prop_list.extend(["a", "b", "a"])
        reference = ["a", "b", "a"]

        for args, expected in self._cases(prop_list):
            assert prop_list.index(*args) == expected == reference.index(*args)

    def test_v1_matches_python_list(self, monkeypatch, fake_store):
        actor_id = "actor-index-v1"
        _seed_list(fake_store, actor_id, "idx", ["a", "b", "a"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name="idx", config=object())
        reference = ["a", "b", "a"]

        for args, expected in self._cases(prop_list):
            assert prop_list.index(*args) == expected == reference.index(*args)


class TestV2PopEmptyCheckUsesFreshState:
    def test_pop_sees_an_append_made_after_the_cache_went_empty(
        self, monkeypatch, fake_store
    ):
        """`len(self)` is served from the rank cache, so an instance that has
        seen the list empty would raise "pop from empty list" against a list
        another writer has since appended to."""
        actor_id = "actor-pop-empty"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        stale = ListProperty(actor_id=actor_id, name=name, config=object())
        stale.append("only")
        stale.pop()
        assert stale.to_list() == []  # cache now empty

        ListProperty(actor_id=actor_id, name=name, config=object()).append("new")

        assert stale.pop() == "new"

    def test_pop_on_a_genuinely_empty_v2_list_raises(self, monkeypatch, fake_store):
        actor_id = "actor-pop-really-empty"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        prop_list = ListProperty(actor_id=actor_id, name="empty", config=object())
        prop_list.append("x")
        prop_list.pop()

        with pytest.raises(IndexError, match="pop from empty list"):
            prop_list.pop()


class TestConditionalDeleteOnPopAndRemove:
    """pop() returns what it removed; remove() removes what it matched.

    Resolving the rank once is not enough: a concurrent __setitem__ on that
    same rank between the read and the delete would discard the other
    writer's value while reporting the one we saw -- an outcome that matches
    no serial ordering of the two operations. The delete is conditional on
    the exact bytes read, and a failed condition re-resolves. Raised by
    Codex on PR #121, round 3.

    __delitem__/__setitem__ deliberately stay unconditional: "delete
    whatever is at position i" and last-writer-wins are satisfied by an
    unconditional write.
    """

    def test_pop_does_not_discard_a_concurrent_overwrite(self, monkeypatch, fake_store):
        actor_id = "actor-cond-pop"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        prop_list.extend(["a", "b", "c"])

        other = ListProperty(actor_id=actor_id, name=name, config=object())
        fired = []
        real_get = FakePropertyDb.get

        def _overwrite_after_read(self, actor_id=None, name=None):
            result = real_get(self, actor_id=actor_id, name=name)
            if not fired and name and "-#" in name:
                fired.append(True)
                other[1] = "OVERWRITTEN"
            return result

        monkeypatch.setattr(FakePropertyDb, "get", _overwrite_after_read)
        popped = prop_list.pop(1)
        monkeypatch.setattr(FakePropertyDb, "get", real_get)

        remaining = ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list()
        # Whatever pop returned, it is what left the list -- the concurrent
        # write is either still present or was the value returned, never
        # silently dropped while a stale value was reported.
        assert popped not in remaining
        assert remaining == ["a", "c"]
        assert popped == "OVERWRITTEN"

    def test_remove_rescans_when_its_match_is_overwritten(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-cond-remove"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        prop_list.extend(["a", "b", "c", "b"])

        other = ListProperty(actor_id=actor_id, name=name, config=object())
        fired = []
        real_load = ListProperty._v2_load_full

        def _overwrite_first_match(self):
            pairs = real_load(self)
            if not fired:
                fired.append(True)
                other[1] = "NOT-B-ANYMORE"
            return pairs

        monkeypatch.setattr(ListProperty, "_v2_load_full", _overwrite_first_match)
        prop_list.remove("b")
        monkeypatch.setattr(ListProperty, "_v2_load_full", real_load)

        # The first "b" was overwritten before the delete landed, so the
        # conditional delete refused, the scan re-ran, and the SECOND "b"
        # was removed. The overwrite survives.
        assert ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list() == ["a", "NOT-B-ANYMORE", "c"]

    def test_remove_raises_value_error_when_the_value_is_gone(
        self, monkeypatch, fake_store
    ):
        """A concurrent remove() of the same value wins: the loser rescans,
        finds nothing, and raises ValueError -- matching list.remove."""
        actor_id = "actor-cond-remove-gone"
        name = "mylist"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        prop_list.extend(["a", "b"])

        other = ListProperty(actor_id=actor_id, name=name, config=object())
        fired = []
        real_load = ListProperty._v2_load_full

        def _remove_first(self):
            pairs = real_load(self)
            if not fired:
                fired.append(True)
                other.remove("b")
            return pairs

        monkeypatch.setattr(ListProperty, "_v2_load_full", _remove_first)
        with pytest.raises(ValueError):
            prop_list.remove("b")
        monkeypatch.setattr(ListProperty, "_v2_load_full", real_load)

        assert ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list() == ["a"]


class TestDuplicateDetectionAfterAnEdit:
    """verify()'s duplicate check had a false NEGATIVE, not just false
    positives.

    An interrupted delete/insert shift leaves two byte-identical adjacent
    rows -- but the moment either copy is edited, the bytes diverge and the
    only signal that a duplicate exists disappears, silently, for exactly
    the lists that have been used since the damage. Found in a real
    deployment: a duplicated item edited afterwards reported
    adjacent_duplicates: [] with both copies still present.
    """

    @staticmethod
    def _seed_diverged_duplicate(store, actor_id, name):
        # Same logical item (id=112) at two adjacent slots, one since edited.
        items = [
            {"id": 110, "title": "a"},
            {"id": 112, "title": "Self-Review", "body": "original"},
            {"id": 112, "title": "Self-Review", "body": "edited later"},
            {"id": 114, "title": "d"},
        ]
        _seed_list(store, actor_id, name, items)

    def test_byte_comparison_misses_a_diverged_duplicate(self, monkeypatch, fake_store):
        actor_id = "actor-dup-diverged"
        name = "outputs"
        self._seed_diverged_duplicate(fake_store, actor_id, name)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        # This is the documented-but-previously-unstated weakness.
        assert prop_list.verify()["adjacent_duplicates"] == []

    def test_identity_key_finds_it(self, monkeypatch, fake_store):
        actor_id = "actor-dup-identity"
        name = "outputs"
        self._seed_diverged_duplicate(fake_store, actor_id, name)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        report = prop_list.verify(identity_key="id")
        # Byte comparison still misses it -- that is the false negative.
        assert report["adjacent_duplicates"] == []
        assert report["duplicate_identities"] == {112: [1, 2]}
        assert report["healthy"] is False

    def test_identity_key_does_not_flag_distinct_items(self, monkeypatch, fake_store):
        actor_id = "actor-dup-clean"
        name = "outputs"
        _seed_list(
            fake_store,
            actor_id,
            name,
            [{"id": 1, "t": "x"}, {"id": 2, "t": "x"}, {"id": 3, "t": "x"}],
        )
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        assert prop_list.verify(identity_key="id")["duplicate_identities"] == {}

    def test_items_without_the_key_fall_back_to_byte_comparison(
        self, monkeypatch, fake_store
    ):
        """Plain strings, or dicts lacking the field, must not all collapse
        into 'identical' just because the key is absent."""
        actor_id = "actor-dup-nokey"
        name = "outputs"
        _seed_list(fake_store, actor_id, name, ["alpha", "beta", "beta"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        report = prop_list.verify(identity_key="id")
        # Not identity-addressable, so excluded from the identity check --
        # but still caught by the byte heuristic.
        assert report["duplicate_identities"] == {}
        assert report["adjacent_duplicates"] == [(1, 2)]

    def test_v2_lists_take_the_same_identity_key(self, monkeypatch, fake_store):
        actor_id = "actor-dup-v2"
        name = "outputs"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        prop_list.extend(
            [
                {"id": 1, "body": "one"},
                {"id": 2, "body": "original"},
                {"id": 2, "body": "edited later"},
            ]
        )

        assert prop_list.verify()["adjacent_duplicates"] == []
        assert prop_list.verify(identity_key="id")["duplicate_identities"] == {
            2: [1, 2]
        }

    def test_identity_duplicates_need_not_be_adjacent(self, monkeypatch, fake_store):
        """Adjacency is right for the byte heuristic and wrong for identity.

        Shift residue is adjacent by construction, but a duplicate arising
        any other way -- a failed read turning an upsert into an append, for
        instance -- is under no obligation to be. A real deployment had the
        same id at positions 31 and 36 and the sweep called the list healthy.
        """
        actor_id = "actor-dup-far-apart"
        name = "embeddings"
        items = [{"id": n, "vec": f"v{n}"} for n in range(8)]
        items[6] = {"id": 1, "vec": "a newer vector for 1"}  # id 1 at 1 and 6
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        # Neither byte-identical nor adjacent: invisible to the old check.
        assert prop_list.verify()["adjacent_duplicates"] == []
        assert prop_list.verify()["healthy"] is True

        report = prop_list.verify(identity_key="id")
        assert report["duplicate_identities"] == {1: [1, 6]}
        assert report["healthy"] is False

    def test_every_row_sharing_one_identity_is_reported(self, monkeypatch, fake_store):
        """The pathological real case: 14 rows, one distinct id."""
        actor_id = "actor-dup-all-same"
        name = "embeddings_actions"
        _seed_list(
            fake_store, actor_id, name, [{"id": 3, "vec": f"v{n}"} for n in range(14)]
        )
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        report = prop_list.verify(identity_key="id")
        assert report["duplicate_identities"] == {3: list(range(14))}
        assert report["healthy"] is False

    def test_unhashable_identity_values_are_still_compared(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-dup-unhashable"
        name = "tagged"
        _seed_list(
            fake_store,
            actor_id,
            name,
            [{"id": ["a", 1]}, {"id": ["b", 2]}, {"id": ["a", 1]}],
        )
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        duplicates = prop_list.verify(identity_key="id")["duplicate_identities"]
        assert list(duplicates.values()) == [[0, 2]]
