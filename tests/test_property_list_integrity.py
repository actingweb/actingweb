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

    def get_range(
        self,
        actor_id=None,
        lower=None,
        upper=None,
        keys_only=False,
        consistent_read=True,
    ):
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

    def set_if_value_equals(self, actor_id=None, name=None, expected=None, value=None):
        if name in self.fail_set_on:
            return False
        if self.store.get((actor_id, name)) != expected:
            return False
        self.store[(actor_id, name)] = value
        return True

    def get_last_in_range(self, actor_id=None, lower=None, upper=None):
        names = [
            name
            for (aid, name) in self.store
            if aid == actor_id and lower <= name <= upper
        ]
        return max(names) if names else None

    def batch_delete(self, actor_id=None, names=None):
        if not actor_id or not names:
            return
        for name in names:
            self.store.pop((actor_id, name), None)


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
        #   1. meta get (_dispatch_and_stash()'s fresh dispatch read -- added
        #      by Phase 9's row-9c fix; deliberately NOT cached into
        #      self._meta_cache, so len() below still does its own read)
        #   2. meta get (len())
        #   3. delete item at index 0
        #   4. get item at index 1 ("b")
        #   5. move: set item at index 0 <- "b"
        #   6. delete item at index 1   <-- crashes here
        _patch_get_property(
            monkeypatch,
            lambda config: CrashInjectingPropertyDb(
                fake_store, calls_before_crash=5, call_counter=call_counter
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
    """Counts get_range()/get_last_in_range() calls -- the query-count
    guard's instrument. The latter is Phase 9B's addition: append()/
    extend() use it instead of a whole-list get_range()."""

    def __init__(self, store):
        super().__init__(store)
        self.range_call_count = 0
        self.last_in_range_call_count = 0

    def get_last_in_range(self, actor_id=None, lower=None, upper=None):
        self.last_in_range_call_count += 1
        return super().get_last_in_range(actor_id=actor_id, lower=lower, upper=upper)

    def get_range(
        self,
        actor_id=None,
        lower=None,
        upper=None,
        keys_only=False,
        consistent_read=True,
    ):
        self.range_call_count += 1
        return super().get_range(
            actor_id=actor_id,
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
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

    def get_range(
        self,
        actor_id=None,
        lower=None,
        upper=None,
        keys_only=False,
        consistent_read=True,
    ):
        self.get_range_calls += 1
        result = super().get_range(
            actor_id=actor_id,
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )
        if self.get_range_calls == 1:
            result.pop(self.stale_missing_name, None)
        return result


class StaleLastRankPropertyDb(FakePropertyDb):
    """The ``get_last_in_range()`` counterpart of ``StaleReadPropertyDb``:
    simulates a genuine last-rank race for append()/extend() (Phase 9B),
    which read the last rank via ``get_last_in_range()`` rather than a
    whole-list ``get_range()``. Reports an EMPTY range (``None``) on its
    FIRST call only, regardless of the real store contents;
    ``create_if_not_exists()`` always sees the real, already-written
    store -- modeling two writers whose read happened before the other's
    write landed."""

    def __init__(self, store):
        super().__init__(store)
        self.last_in_range_calls = 0

    def get_last_in_range(self, actor_id=None, lower=None, upper=None):
        self.last_in_range_calls += 1
        if self.last_in_range_calls == 1:
            return None
        return super().get_last_in_range(actor_id=actor_id, lower=lower, upper=upper)


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

        # Phase 9B: append() reads the last rank via get_last_in_range(),
        # not get_range() -- StaleReadPropertyDb (which stales get_range())
        # no longer models this race for append(); StaleLastRankPropertyDb
        # is its get_last_in_range() counterpart.
        fake_db = StaleLastRankPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        prop_list.append("new-item")

        # The stale first read reported an empty list, so the first
        # candidate collided with "a0"; a fresh reread on retry found it
        # and generated past it.
        assert fake_db.last_in_range_calls >= 2
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
        # Opt in, so this proves the unhealthy check refuses -- not merely
        # that lazy migration is off by default.
        monkeypatch.setenv("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH", "50")
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
        monkeypatch.setenv("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH", "50")
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

        # Default is 0 (off) -- a 60-item list is left alone either way.
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
        # Not checked at all without an identity key -- distinguishable
        # from "checked and clean".
        assert prop_list.verify()["duplicate_identities"] is None

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

    def test_wrong_identity_key_is_distinguishable_from_clean(
        self, monkeypatch, fake_store
    ):
        """`duplicate_identities == {}` means "checked, clean" only if
        something was actually checked.

        Rows without the field are excluded from the comparison -- correct,
        since bucketing them together would make every one a duplicate of
        every other -- but that makes a mistyped key produce a report shaped
        exactly like a healthy one. `identity_checked_count` is how an
        operator tells the two apart.
        """
        actor_id = "actor-wrong-key"
        name = "outputs"
        _seed_list(
            fake_store,
            actor_id,
            name,
            [{"itemId": 1, "t": "a"}, {"itemId": 1, "t": "b"}],
        )
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())

        wrong = prop_list.verify(identity_key="id")
        assert wrong["duplicate_identities"] == {}
        assert wrong["identity_checked_count"] == 0  # compared nothing

        right = prop_list.verify(identity_key="itemId")
        assert right["duplicate_identities"] == {1: [0, 1]}
        assert right["identity_checked_count"] == 2

        unchecked = prop_list.verify()
        assert unchecked["duplicate_identities"] is None
        assert unchecked["identity_checked_count"] is None

    def test_true_and_one_are_not_the_same_identity(self, monkeypatch, fake_store):
        """Python considers True == 1 and hashes them alike, so an untagged
        dict key would report a duplicate that does not exist."""
        actor_id = "actor-bool-int"
        name = "outputs"
        _seed_list(fake_store, actor_id, name, [{"id": True}, {"id": 1}])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        report = ListProperty(actor_id=actor_id, name=name, config=object()).verify(
            identity_key="id"
        )
        assert report["duplicate_identities"] == {}
        assert report["identity_checked_count"] == 2
        assert report["healthy"] is True


class TestCompactIsNotCrashSafe:
    """Pins the documented interruption states of v1 ``compact()``.

    Repair writes survivors to their new positions before deleting the tail,
    so an interruption leaves a copy at both -- with the stored length
    unchanged, which means the list reads back with NO error. Documented in
    compact()'s docstring, the property-lists guide and the migration
    guide's repair step; this test is what keeps those honest.

    The sharp part is the last assertion: re-running compact() does not
    clean it up, because duplicates are preserved by design -- including the
    one the interrupted repair itself created.
    """

    @staticmethod
    def _seed_holed(store, actor_id, name):
        # [a, <hole>, c, d] with the length still claiming 4.
        for i, v in [(0, "a"), (2, "c"), (3, "d")]:
            store[(actor_id, f"list:{name}-{i}")] = json.dumps(v)
        store[(actor_id, f"list:{name}-meta")] = json.dumps(
            {
                "length": 4,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
                "item_type": "json",
                "chunk_size": 1,
                "version": "1.0",
                "description": "",
                "explanation": "",
            }
        )

    @pytest.mark.parametrize(
        ("calls_before_crash", "expected_rows"),
        [(2, ["a", "c", "c", "d"]), (3, ["a", "c", "d", "d"])],
    )
    def test_interrupted_repair_leaves_a_readable_duplicate(
        self, monkeypatch, fake_store, calls_before_crash, expected_rows
    ):
        actor_id = f"actor-compact-crash-{calls_before_crash}"
        name = "damaged"
        self._seed_holed(fake_store, actor_id, name)
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )
        counter = [0]
        _patch_get_property(
            monkeypatch,
            lambda config: CrashInjectingPropertyDb(
                fake_store, calls_before_crash=calls_before_crash, call_counter=counter
            ),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        with pytest.raises(DbError):
            prop_list.compact()

        # No error on read: the length still matches the rows present, so
        # nothing is structurally inconsistent -- it is just wrong.
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == expected_rows
        assert _meta_length(fake_store, actor_id, name) == 4

        # verify() does catch it -- the copy is adjacent and byte-identical.
        report = fresh.verify()
        assert report["adjacent_duplicates"]
        assert report["healthy"] is False

        # But repair will not remove it: duplicates are preserved by design,
        # including the one the interrupted repair created.
        fresh.compact()
        after = ListProperty(actor_id=actor_id, name=name, config=object())
        assert after.to_list() == expected_rows, (
            "re-running repair must not silently collapse the duplicate -- "
            "and equally must not be mistaken for cleaning it up"
        )


class TestStaleMetadataIsNeverWrittenBack:
    """A retained ListProperty instance must not revert a concurrent
    migration by round-tripping its cached metadata dict.

    The previously-unfiled P0 from the 2026-08-15 review round: metadata was
    saved by writing the WHOLE cached dict back, so a concurrent v1
    ``append()`` restored ``format: 1`` over a completed migration. Metadata
    then claimed v1 while every item lived in v2 rows nothing read, and
    migration's final step deleted the v1 rows -- total silent loss on
    ordinary traffic. The window is one round trip for a fresh instance and
    UNBOUNDED for any instance an application retains, because the metadata
    cache only clears on an explicit invalidation.

    See thoughts/plans/2026-08-15-property-list-metadata-integrity.md Phase 1.

    Phase 9 (2026-08-20-v2-positional-access-cost.md) closed a second,
    related gap: dispatch itself (``_dispatch_and_stash()``) now does a
    FRESH read of the meta row on every mutation instead of trusting
    ``self._is_v2()``'s cache-backed belief. Under the OLD dispatch, a stale
    instance's mutation landed in whichever storage space the instance
    itself believed in -- invisible until that same instance's NEXT
    operation self-corrected. Under the fixed dispatch, a stale instance's
    mutation lands in the CURRENT storage space on its very first
    post-migration call: correct immediately, not merely
    correct-by-the-next-call. The tests below that exercise a stale
    instance's ``append()`` after a concurrent migration were written
    against the old (delayed) self-correction and have been updated to
    assert the new (immediate) one -- the WARNING that flags a stale-cache
    dispatch still fires (see
    ``test_a_retained_instance_does_not_resurrect_its_cached_format``), it
    just no longer means the write was lost.
    """

    @staticmethod
    def _migrate_underneath(store, actor_id, name, items):
        """Another process migrates the list to v2 while our instance holds
        a cached v1 metadata dict."""
        for i in range(len(items)):
            store.pop((actor_id, f"list:{name}-{i}"), None)
        _seed_v2_list(store, actor_id, name, items)

    @staticmethod
    def _stored_meta(store, actor_id, name):
        return json.loads(store[(actor_id, f"list:{name}-meta")])

    def test_concurrent_append_does_not_revert_the_format_flip(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-writeback-append"
        name = "notes"
        items = ["a", "b", "c"]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        # An instance the application retained, holding v1 metadata.
        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert retained.to_list() == items

        self._migrate_underneath(fake_store, actor_id, name, items)

        retained.append("d")

        # The flip survives, every migrated item survives, AND the stale
        # instance's own append() -- dispatched fresh, not off its cached
        # v1 belief -- lands as a real v2 item rather than being lost in
        # dead v1 space.
        assert self._stored_meta(fake_store, actor_id, name)["format"] == 2
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == [*items, "d"]

    def test_v2_metadata_row_never_acquires_a_length(self, monkeypatch, fake_store):
        """`length` is authoritative for v1 and absent for v2.

        A stale v1 writer computed its length against a different view of
        the list, so merging it into a v2 row would plant a number no v2
        reader agrees with -- and that a later downgrade would believe.
        """
        actor_id = "actor-writeback-length"
        name = "notes"
        items = ["a", "b", "c"]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert len(retained) == 3
        self._migrate_underneath(fake_store, actor_id, name, items)

        retained.append("d")

        assert "length" not in self._stored_meta(fake_store, actor_id, name)

    def test_concurrent_clear_is_not_undone(self, monkeypatch, fake_store):
        """A cleared list's format and metadata shape stay clean, and a
        stale instance's own write after the clear lands correctly.

        clear() resets a v2 list's metadata wholesale. Under Phase 9's fresh
        dispatch, a stale v1 instance's append() AFTER the clear no longer
        writes its cached ``format: 1``/pre-clear ``length`` back over that
        reset -- it reads the CURRENT (post-clear) v2 row and dispatches
        into v2 space, so the append becomes the list's first real item
        rather than either reverting the clear or vanishing into dead v1
        rows.
        """
        actor_id = "actor-writeback-clear"
        name = "notes"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        # v1 list, plus an instance holding its metadata.
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert len(retained) == 3

        # Another process migrated, then cleared it.
        self._migrate_underneath(fake_store, actor_id, name, ["a", "b", "c"])
        ListProperty(actor_id=actor_id, name=name, config=object()).clear()

        retained.append("d")

        meta = self._stored_meta(fake_store, actor_id, name)
        assert meta["format"] == 2
        assert "length" not in meta
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == ["d"]

    def test_concurrent_delete_is_not_undone(self, monkeypatch, fake_store):
        """A deleted list's absent row is not resurrected as a CORRUPT one.

        Before Phase 9, dispatch on an absent row went through
        ``self._is_v2()``'s CACHED belief, so a retained instance holding a
        stale v1 cache took the v1 append path, whose ``create_if_absent
        =False`` declined to write metadata back -- but v1 ``append()``
        writes its item row FIRST, so the write this test used to assert
        "doesn't happen" actually left an invisible orphan v1 item row with
        no meta row pointing at it (worse: the next list created under this
        name silently adopts it).

        Phase 9's fresh dispatch treats an absent row uniformly as "create
        as v2" -- the same choice ``_v2_touch_metadata()`` already makes
        deliberately for a v2 instance racing a delete() ("a delete() racing
        an append() leaves a one-item list rather than nothing"). This test
        now pins that the resurrected list is COHERENT: format v2, no
        `length` key, and the one item actually readable -- not a v1-shaped
        row over a v2 item, and not an invisible orphan.
        """
        actor_id = "actor-writeback-delete"
        name = "notes"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert len(retained) == 3

        ListProperty(actor_id=actor_id, name=name, config=object()).delete()
        assert (actor_id, f"list:{name}-meta") not in fake_store

        retained.append("d")

        meta = self._stored_meta(fake_store, actor_id, name)
        assert meta["format"] == 2
        assert "length" not in meta
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == ["d"]

    def test_a_retained_instance_does_not_resurrect_its_cached_format(
        self, monkeypatch, fake_store
    ):
        """Not one operation: the cache survives until something invalidates
        it, so EVERY later operation on a retained instance is a chance to
        write the stale format back -- and, since Phase 9, a chance for the
        WARNING to fire, without a chance for the write itself to be lost.

        ``_dispatch_and_stash()`` reads the meta row fresh on every
        mutation, so ``retained``'s belief (cached at construction, v1)
        never governs where a write lands -- only the WARNING comparison
        uses it. Both appends below dispatch into the CURRENT v2 space and
        both survive; the cache only affects whether the WARNING logs, not
        correctness. The cache still never gets written back: ``format``
        stays 2 throughout.
        """
        actor_id = "actor-writeback-retained"
        name = "notes"
        items = ["a", "b", "c"]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert retained.to_list() == items
        self._migrate_underneath(fake_store, actor_id, name, items)

        retained.append("d")  # dispatched fresh: a real v2 item despite the stale cache
        retained.set_description("written while this instance thought it was v1")
        retained.append("e")  # cache refreshed by now too: still a real v2 item

        assert self._stored_meta(fake_store, actor_id, name)["format"] == 2
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == [*items, "d", "e"]
        assert (
            fresh.get_description() == "written while this instance thought it was v1"
        )

    def test_stale_v1_clear_does_not_downgrade_live_v2_storage(
        self, monkeypatch, fake_store
    ):
        """clear() dispatches on the STORED format, not a cached one.

        Both branches end in a wholesale metadata write, so a stale v1
        cache would put `_create_default_metadata()` over a live v2 list's
        meta row while its rows stayed put -- the same format revert,
        arriving through the replace path rather than the merge path.
        """
        actor_id = "actor-stale-clear"
        name = "notes"
        items = ["a", "b", "c"]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert retained.to_list() == items
        self._migrate_underneath(fake_store, actor_id, name, items)

        retained.clear()

        meta = self._stored_meta(fake_store, actor_id, name)
        assert meta["format"] == 2
        fresh = ListProperty(actor_id=actor_id, name=name, config=object())
        assert fresh.to_list() == []
        # The v2 rows are actually gone, not merely unreachable.
        assert not [
            k for k in fake_store if k[0] == actor_id and f"list:{name}-#" in k[1]
        ]

    def test_stale_v1_delete_removes_the_v2_rows(self, monkeypatch, fake_store):
        """delete() dispatches on the stored format too. A stale cache
        deletes the wrong namespace and leaves the real rows behind, where
        nothing can see them -- until the next list of the same name."""
        actor_id = "actor-stale-delete"
        name = "notes"
        items = ["a", "b", "c"]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert retained.to_list() == items
        self._migrate_underneath(fake_store, actor_id, name, items)

        retained.delete()

        assert not [k for k in fake_store if k[0] == actor_id], (
            "every row of the deleted list must be gone, whichever format "
            "the deleting instance had cached"
        )


class TestMigrateRefusesAVanishedMetaRow:
    """migrate_to_v2() must not recreate a meta row that was deleted while
    it was copying: the list was deleted, and recreating it resurrects it
    out of rows migration wrote itself."""

    def test_deleted_mid_migration_rolls_back_rather_than_recreating(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-migrate-vanish"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        class DeletingMetaDb(FakePropertyDb):
            """Deletes the whole list the moment migration writes its first
            v2 row -- the window between steps 4 and 5."""

            def set(self, actor_id=None, name=None, value=None):
                result = super().set(actor_id=actor_id, name=name, value=value)
                if "-#" in (name or "") and self.store.get(
                    (actor_id, f"list:{prop_name}-meta")
                ):
                    for key in [k for k in list(self.store) if "-#" not in k[1]]:
                        self.store.pop(key, None)
                return result

        prop_name = name
        _patch_get_property(monkeypatch, lambda config: DeletingMetaDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        result = prop_list.migrate_to_v2()

        assert result == {"migrated": False, "reason": "deleted_concurrently"}
        assert fake_store == {}, (
            "the v2 rows this attempt wrote must be rolled back -- they are "
            "invisible to exists()/list_all() without a meta row, but the "
            "next list created under this name would read them as its items"
        )


class TestInvalidateCacheClearsBothCaches:
    """The metadata cache and the v2 rank cache are semantically coupled:
    ranks are only meaningful for the format the metadata reports. Nothing
    enforced that before."""

    def test_invalidate_cache_clears_the_rank_cache_too(self, monkeypatch, fake_store):
        actor_id = "actor-cache-coupling"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        assert prop_list.to_list() == ["a", "b", "c"]
        assert prop_list._v2_rank_cache is not None  # noqa: SLF001

        prop_list._invalidate_cache()  # noqa: SLF001

        assert prop_list._meta_cache is None  # noqa: SLF001
        assert prop_list._v2_rank_cache is None  # noqa: SLF001

    def test_v2_mutations_keep_their_rank_cache(self, monkeypatch, fake_store):
        """The metadata touch after every v2 mutation re-reads the meta row
        but must NOT discard the rank cache it just updated in place --
        that would cost a full range query per mutation.

        Phase 9B changed HOW ``append()`` finds its own rank (one
        ``get_last_in_range()`` read instead of the full rank cache), but
        it still keeps an ALREADY-WARM ``self._v2_rank_cache`` in sync by
        appending to it on success -- it just never LOADS a cold one. See
        ``test_v2_append_last_rank.py``'s ``TestAppendKeepsAWarmRankCacheInSync``
        for why that's a correctness requirement, not an optimization: a
        caller (``handlers/properties.py``'s bulk-update pass) that warms
        the cache via ``len()`` and then loops ``append()``/``len()`` on
        the SAME instance depends on exactly this.
        """
        actor_id = "actor-cache-kept"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        assert prop_list.to_list() == ["a", "b"]
        prop_list.append("c")

        assert prop_list._v2_rank_cache is not None  # noqa: SLF001
        assert len(prop_list._v2_rank_cache) == 3  # noqa: SLF001


class TestSweepForeignFormatRows:
    """The cleanup primitive both interrupted rewrites need, and the shape
    filters that keep it from eating a sibling list."""

    def test_sweeps_v1_residue_from_a_v2_list(self, monkeypatch, fake_store):
        actor_id = "actor-sweep-v1"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        # Residue a migration crashed before deleting.
        for i, item in enumerate(["a", "b"]):
            fake_store[(actor_id, f"list:{name}-{i}")] = json.dumps(item)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        assert prop_list.sweep_foreign_format_rows() == 2

        assert (actor_id, f"list:{name}-0") not in fake_store
        assert prop_list.to_list() == ["a", "b"]

    def test_sweeps_v2_residue_from_a_v1_list(self, monkeypatch, fake_store):
        actor_id = "actor-sweep-v2"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b"])
        fake_store[(actor_id, f"list:{name}-#a0")] = json.dumps("a")
        fake_store[(actor_id, f"list:{name}-#a1")] = json.dumps("b")
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        assert prop_list.sweep_foreign_format_rows() == 2

        assert not [k for k in fake_store if "-#" in k[1]]
        assert prop_list.to_list() == ["a", "b"]

    def test_a_stale_cache_cannot_make_the_sweep_delete_the_live_rows(
        self, monkeypatch, fake_store
    ):
        """The format comes from storage. A cached v1 view over migrated
        storage would classify every LIVE v2 row as foreign."""
        actor_id = "actor-sweep-stale"
        name = "notes"
        items = ["a", "b", "c"]
        _seed_list(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        retained = ListProperty(actor_id=actor_id, name=name, config=object())
        assert retained.to_list() == items
        for i in range(len(items)):
            fake_store.pop((actor_id, f"list:{name}-{i}"), None)
        _seed_v2_list(fake_store, actor_id, name, items)

        assert retained.sweep_foreign_format_rows() == 0
        assert ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list() == (items)

    def test_a_digit_named_sibling_list_survives_a_v1_sweep(
        self, monkeypatch, fake_store
    ):
        """A list called 'foo-5' stores 'list:foo-5-0', which sorts inside
        list 'foo''s v1 byte range. Only the ^\\d+$ suffix check keeps the
        sweep off it -- the v1 counterpart of the '#'-sibling hazard."""
        actor_id = "actor-sweep-sibling-v1"
        _seed_v2_list(fake_store, actor_id, "foo", ["mine"])
        _seed_list(fake_store, actor_id, "foo-5", ["sibling-a", "sibling-b"])
        sibling_before = {
            k: v for k, v in fake_store.items() if k[1].startswith("list:foo-5-")
        }
        assert sibling_before
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        owner = ListProperty(actor_id=actor_id, name="foo", config=object())
        assert owner.sweep_foreign_format_rows() == 0

        assert {
            k: v for k, v in fake_store.items() if k[1].startswith("list:foo-5-")
        } == sibling_before

    def test_a_legacy_hash_named_sibling_survives_a_v2_sweep(
        self, monkeypatch, fake_store
    ):
        """A pre-Phase-4 list named 'foo-#bar' stores 'list:foo-#bar-0',
        inside list 'foo''s v2 range. _v2_is_rank() is what excludes it."""
        actor_id = "actor-sweep-sibling-v2"
        _seed_list(fake_store, actor_id, "foo", ["mine"])
        _seed_list(fake_store, actor_id, "foo-#bar", ["legacy-a", "legacy-b"])
        sibling_before = {
            k: v for k, v in fake_store.items() if k[1].startswith("list:foo-#bar-")
        }
        assert sibling_before
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        owner = ListProperty(actor_id=actor_id, name="foo", config=object())
        assert owner.sweep_foreign_format_rows() == 0

        assert {
            k: v for k, v in fake_store.items() if k[1].startswith("list:foo-#bar-")
        } == sibling_before

    def test_the_meta_row_is_never_swept(self, monkeypatch, fake_store):
        actor_id = "actor-sweep-meta"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a"])
        fake_store[(actor_id, f"list:{name}-0")] = json.dumps("a")
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        prop_list.sweep_foreign_format_rows()

        assert (actor_id, f"list:{name}-meta") in fake_store


class TestInterruptedRewritesConverge:
    """Re-running an interrupted format change must finish it. Both
    rewrites early-returned before reaching their own cleanup, so the
    residue was permanent: a re-run did not finish the job, it declined to
    start it."""

    @staticmethod
    def _crash_migration_after_the_flip(store, actor_id, name, items):
        """The state a crash between migrate_to_v2()'s step 5 and step 6
        leaves: v2 rows plus v2 metadata, with the v1 rows still there."""
        _seed_v2_list(store, actor_id, name, items)
        for i, item in enumerate(items):
            store[(actor_id, f"list:{name}-{i}")] = json.dumps(item)

    def test_rerunning_migrate_to_v2_sweeps_the_v1_rows(self, monkeypatch, fake_store):
        actor_id = "actor-converge-migrate"
        name = "notes"
        items = ["a", "b", "c"]
        self._crash_migration_after_the_flip(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        assert prop_list.migrate_to_v2() == {"migrated": False, "reason": "already_v2"}

        assert not [
            k
            for k in fake_store
            if k[1].startswith(f"list:{name}-")
            and "-#" not in k[1]
            and not k[1].endswith("-meta")
        ]
        assert prop_list.to_list() == items

    def test_the_bulk_script_reaches_that_cleanup(self, monkeypatch, fake_store):
        """The load-bearing one. migrate_actor() gated on
        `if already_v2: continue`, so after an interrupted migration the
        list reads format 2 and the script skipped it without ever calling
        migrate_to_v2() -- making the fix above unreachable from the
        command operators actually run.
        """
        from actingweb.maintenance.migrate_property_lists import (
            RateLimiter,
            migrate_actor,
        )

        actor_id = "actor-converge-script"
        name = "notes"
        items = ["a", "b", "c"]
        self._crash_migration_after_the_flip(fake_store, actor_id, name, items)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )
        monkeypatch.setattr(
            "actingweb.property.get_property_list",
            lambda config: _FakePropertyList(fake_store),
            raising=False,
        )

        _checked, _migrated, errored, refused = migrate_actor(
            actor_id, object(), migrate=True, limiter=RateLimiter(0)
        )

        assert (errored, refused) == (0, [])
        assert not [
            k
            for k in fake_store
            if k[1].startswith(f"list:{name}-")
            and "-#" not in k[1]
            and not k[1].endswith("-meta")
        ], "the script's already_v2 path must sweep, not skip"
        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        assert prop_list.to_list() == items

    def test_rerunning_downgrade_sweeps_the_v2_rows(self, monkeypatch, fake_store):
        from actingweb.maintenance.migrate_property_lists import downgrade_to_v1

        actor_id = "actor-converge-downgrade"
        name = "notes"
        items = ["a", "b"]
        # A downgrade interrupted after its metadata flip: v1 rows and v1
        # metadata, with the v2 rows still present.
        _seed_list(fake_store, actor_id, name, items)
        fake_store[(actor_id, f"list:{name}-#a0")] = json.dumps("a")
        fake_store[(actor_id, f"list:{name}-#a1")] = json.dumps("b")
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.db.get_property",
            lambda config: FakePropertyDb(fake_store),
            raising=False,
        )

        result = downgrade_to_v1(actor_id, name, object())

        assert result["downgraded"] is False
        assert result["swept_v2_rows"] == 2
        assert not [k for k in fake_store if "-#" in k[1]]
        assert ListProperty(
            actor_id=actor_id, name=name, config=object()
        ).to_list() == (items)

    def test_a_deleted_list_does_not_resurrect_inside_its_successor(
        self, monkeypatch, fake_store
    ):
        """Residue outlives the list: exists()/list_all() key off the meta
        row, so nothing reports it -- until a new list is created under the
        same name and adopts it as its own items."""
        actor_id = "actor-resurrect"
        name = "notes"
        self._crash_migration_after_the_flip(
            fake_store, actor_id, name, ["old-a", "old-b"]
        )
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        ListProperty(actor_id=actor_id, name=name, config=object()).delete()
        assert not [k for k in fake_store if k[0] == actor_id]

        recreated = ListProperty(actor_id=actor_id, name=name, config=object())
        assert recreated.to_list() == []
        recreated.append("new-a")
        assert recreated.to_list() == ["new-a"]

    def test_clear_empties_both_namespaces(self, monkeypatch, fake_store):
        actor_id = "actor-clear-both"
        name = "notes"
        self._crash_migration_after_the_flip(fake_store, actor_id, name, ["a", "b"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        prop_list.clear()

        assert prop_list.to_list() == []
        assert [k[1] for k in fake_store if k[0] == actor_id] == [f"list:{name}-meta"]


class TestVerifyReportsForeignFormatRows:
    """Cross-format residue is reported but does NOT fail `healthy`.

    It is inert to every reader of the current format, and the sweep
    removes it without operator involvement -- matching v2's informational
    duplicate reporting rather than v1's, where duplicates do fail.
    """

    def test_v2_verify_reports_v1_residue_without_failing_healthy(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-verify-foreign-v2"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b"])
        for i, item in enumerate(["a", "b"]):
            fake_store[(actor_id, f"list:{name}-{i}")] = json.dumps(item)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        report = ListProperty(actor_id=actor_id, name=name, config=object()).verify()

        assert report["foreign_format_rows"] == 2
        assert report["healthy"] is True

    def test_v1_verify_reports_v2_residue_without_failing_healthy(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-verify-foreign-v1"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b"])
        fake_store[(actor_id, f"list:{name}-#a0")] = json.dumps("a")
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        report = ListProperty(actor_id=actor_id, name=name, config=object()).verify()

        assert report["foreign_format_rows"] == 1
        assert report["healthy"] is True

    def test_a_clean_list_reports_zero(self, monkeypatch, fake_store):
        actor_id = "actor-verify-foreign-clean"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        report = ListProperty(actor_id=actor_id, name=name, config=object()).verify()
        assert report["foreign_format_rows"] == 0


class TestMigrationRollbackDoesNotEatASuccessorList:
    """The abort path must delete only rows it still owns.

    Raised as a P2 by Codex review on PR #127 and accepted as real. Between
    migrate_to_v2() observing the metadata row absent and its rollback loop
    running, the concurrent delete() can sweep the scratch rows AND a new
    list can be created under the same name. That successor's first
    append() lands on rank "a0" -- the same rank migration generated, because
    ``generate_n_keys_between(None, None, n)`` is deterministic. Deleting by
    rank name alone therefore destroys the successor's item while leaving its
    metadata intact: silent cross-list loss, committed by the rollback rather
    than the migration.
    """

    def test_rollback_leaves_a_successors_row_alone(self, monkeypatch, fake_store):
        import fractional_indexing as fi

        actor_id = "actor-rollback-successor"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        first_rank = fi.generate_n_keys_between(None, None, 3)[0]
        successor_row = (actor_id, f"list:{name}-#{first_rank}")
        prop = name

        class Racing(FakePropertyDb):
            """Trip on migration's STEP 5 metadata read -- identified by the
            v2 rows step 4 has just written being present. Report the row as
            absent, and in the same instant do what a concurrent delete() plus
            a fresh create() would: sweep every row of the old list, then
            stand a new list up under the same name whose first item takes
            the very rank migration used."""

            def get(self, actor_id=None, name=None):
                step_five = name == f"list:{prop}-meta" and any(
                    "-#" in k[1] for k in self.store
                )
                if not step_five:
                    return super().get(actor_id=actor_id, name=name)
                for key in [k for k in list(self.store) if f"list:{prop}-" in k[1]]:
                    self.store.pop(key, None)
                self.store[successor_row] = json.dumps("successor-item")
                self.store[(actor_id, f"list:{prop}-meta")] = json.dumps(
                    {"format": 2, "created_at": "x", "updated_at": "x"}
                )
                return None  # what migration's step-5 read observes

        _patch_get_property(monkeypatch, lambda config: Racing(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        result = prop_list.migrate_to_v2()

        assert result == {"migrated": False, "reason": "deleted_concurrently"}
        assert fake_store.get(successor_row) == json.dumps("successor-item"), (
            "the rollback deleted a row belonging to the list that replaced "
            "the one being migrated"
        )

    def test_rollback_still_removes_its_own_rows(self, monkeypatch, fake_store):
        """The conditional delete must not become a no-op: when nothing else
        touched the rows, the rollback still cleans up after itself."""
        actor_id = "actor-rollback-own"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b", "c"])
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(fake_store),
        )

        class MetaVanishes(FakePropertyDb):
            def get(self, actor_id=None, name=None):
                if name == f"list:{name_}-meta" and any(
                    "-#" in k[1] for k in self.store
                ):
                    # Step 4 has written the v2 rows; the meta row is gone.
                    self.store.pop((actor_id, name), None)
                    return None
                return super().get(actor_id=actor_id, name=name)

        name_ = name
        _patch_get_property(monkeypatch, lambda config: MetaVanishes(fake_store))

        prop_list = ListProperty(actor_id=actor_id, name=name, config=object())
        result = prop_list.migrate_to_v2()

        assert result == {"migrated": False, "reason": "deleted_concurrently"}
        assert not [k for k in fake_store if "-#" in k[1]], (
            "rows this migration wrote, and that nobody else touched, must "
            "still be rolled back"
        )


def _seed_reverted_migration(store, actor_id, name, items):
    """Build the shape a format-reverted migration leaves behind.

    Metadata claims v1 with the pre-migration length, the v1 item rows are
    gone (migration's last step deleted them), and the items are alive in v2
    rows. Reachable two ways: a concurrent write landing inside
    ``_save_metadata()``'s read-modify-write gap, and any list left this way
    by a ``v3.13.0rc5``/``rc6`` migration.
    """
    import fractional_indexing as fi

    ranks = fi.generate_n_keys_between(None, None, len(items))
    for rank, item in zip(ranks, items, strict=True):
        store[(actor_id, f"list:{name}-#{rank}")] = json.dumps(item)
    store[(actor_id, f"list:{name}-meta")] = json.dumps(
        {
            "length": len(items),
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "",
            "explanation": "",
        }
    )


class TestCompactRefusesARevertedMigration:
    """``--repair`` must not bless a reverted migration as healthy.

    Found by consumer verification against 3.13.0 GA, and reproduced before
    fixing: ``verify()`` reported the list unhealthy with
    ``foreign_format_rows > 0``, reads raised loudly, and then ``compact()``
    rewrote the empty v1 range, set the length to 0, and reported the list
    **healthy** — with the only surviving copy left as unreferenced residue
    for the next ``clear()``/``delete()``/migrate re-run to sweep.

    That is the same unreportable loss ``migrate_to_v2()`` refuses damaged
    lists to avoid, in the other operator tool.
    """

    NAME = "reverted"
    ITEMS = ["alpha", "beta", "gamma"]

    def _prepare(self, monkeypatch):
        store = {}
        _seed_reverted_migration(store, "actor1", self.NAME, self.ITEMS)
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(store),
        )
        return store

    def test_the_shape_is_detected_as_damaged_with_foreign_rows(
        self, monkeypatch
    ) -> None:
        store = self._prepare(monkeypatch)
        report = ListProperty(
            actor_id="actor1", name=self.NAME, config=object()
        ).verify()
        assert report["healthy"] is False
        assert report["missing_indices"] == [0, 1, 2]
        assert report["foreign_format_rows"] == 3
        assert len([k for k in store if "-#" in k[1]]) == 3

    def test_compact_refuses_and_says_why(self, monkeypatch) -> None:
        self._prepare(monkeypatch)
        result = ListProperty(
            actor_id="actor1", name=self.NAME, config=object()
        ).compact()
        assert result["compacted"] is False
        assert result["reason"] == "reverted_migration"

    def test_the_override_strands_the_data_and_reports_healthy(
        self, monkeypatch
    ) -> None:
        """What the refusal is protecting against, asserted rather than argued.

        ``compact()`` does not itself delete the v2 rows — it rewrites the
        (empty) v1 range. The harm is what it leaves: a list that reports
        **healthy** and reads **empty** while its contents sit in rows nothing
        references, waiting for the next ``clear()``/``delete()``/migrate
        re-run to sweep them. Loss with nothing left to report it, which is
        exactly the trade ``migrate_to_v2(allow_damaged=...)`` gates on.
        """
        store = self._prepare(monkeypatch)
        ListProperty(actor_id="actor1", name=self.NAME, config=object()).compact(
            allow_reverted=True
        )

        after = ListProperty(actor_id="actor1", name=self.NAME, config=object())
        assert after.verify()["healthy"] is True
        assert after.to_list() == []
        # The items are still on disk — unreachable, and no longer reported as
        # a problem by anything.
        stranded = sorted(json.loads(v) for k, v in store.items() if "-#" in k[1])
        assert stranded == sorted(self.ITEMS)

    def test_the_list_stays_loudly_unhealthy(self, monkeypatch) -> None:
        """A refusal must not quietly look like a successful repair."""
        self._prepare(monkeypatch)
        ListProperty(actor_id="actor1", name=self.NAME, config=object()).compact()
        after = ListProperty(
            actor_id="actor1", name=self.NAME, config=object()
        ).verify()
        assert after["healthy"] is False
        assert after["foreign_format_rows"] == 3

    def test_allow_reverted_is_the_deliberate_override(self, monkeypatch) -> None:
        self._prepare(monkeypatch)
        result = ListProperty(
            actor_id="actor1", name=self.NAME, config=object()
        ).compact(allow_reverted=True)
        assert result.get("compacted") is not False

    def test_an_ordinary_hole_still_compacts(self, monkeypatch) -> None:
        """The gate must be narrow: damage alone is not a reverted migration.

        Without the ``foreign_format_rows`` half of the condition this would
        refuse every damaged list and break repair entirely.
        """
        store = {}
        _seed_list(store, "actor1", "ordinary", ["a", "b", "c"])
        del store[("actor1", "list:ordinary-1")]
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(store),
        )
        result = ListProperty(
            actor_id="actor1", name="ordinary", config=object()
        ).compact()
        assert result.get("compacted") is not False
        assert ListProperty(
            actor_id="actor1", name="ordinary", config=object()
        ).to_list() == ["a", "c"]


class TestAStaleFormatWriteIsLoud:
    """A write from an instance retained across a migration must not be silent.

    Also from consumer verification: the item lands in a row of the format
    the instance believed, which readers of the current format never return.
    ``verify()`` reports the list **healthy** — the row shows up only as
    ``foreign_format_rows``, which is documented as inert residue. So before
    this warning the only trace was a DEBUG line.
    """

    def test_appending_from_a_stale_instance_warns(self, monkeypatch, caplog) -> None:
        import logging

        store = {}
        _seed_list(store, "actor1", "held", ["alpha", "beta"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(store),
        )

        stale = ListProperty(actor_id="actor1", name="held", config=object())
        assert stale.to_list() == ["alpha", "beta"]  # caches format v1

        ListProperty(actor_id="actor1", name="held", config=object()).migrate_to_v2()

        with caplog.at_level(logging.WARNING, logger="actingweb.property_list"):
            stale.append("gamma")

        assert any(
            "believed the storage format was v1" in r.getMessage()
            for r in caplog.records
        ), "a write against a migrated-away format must not be silent"

    def test_the_instance_self_corrects_after_the_warning(self, monkeypatch) -> None:
        """Bounded to one write: the metadata write refreshes the cache."""
        store = {}
        _seed_list(store, "actor1", "held", ["alpha", "beta"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(store),
        )
        stale = ListProperty(actor_id="actor1", name="held", config=object())
        stale.to_list()
        ListProperty(actor_id="actor1", name="held", config=object()).migrate_to_v2()

        stale.append("gamma")  # lost to v1-shaped row
        stale.append("delta")  # must land correctly

        assert (
            "delta"
            in ListProperty(actor_id="actor1", name="held", config=object()).to_list()
        )

    def test_no_warning_when_nothing_changed_underneath(
        self, monkeypatch, caplog
    ) -> None:
        import logging

        store = {}
        _seed_list(store, "actor1", "quiet", ["alpha"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(store))
        monkeypatch.setattr(
            "actingweb.property_list.get_property_list",
            lambda config: _FakePropertyList(store),
        )
        lp = ListProperty(actor_id="actor1", name="quiet", config=object())
        lp.to_list()
        with caplog.at_level(logging.WARNING, logger="actingweb.property_list"):
            lp.append("beta")
        assert not [
            r for r in caplog.records if "believed the storage format" in r.getMessage()
        ]
