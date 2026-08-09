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
