"""Phase 9B of the v2 list read cost release (thoughts/plans/2026-08-20-v2-
positional-access-cost.md): `append()`/`extend()` stop paying a whole-list
range query for the one fact they actually need -- the current last rank.

Consumer feedback F-1: as originally drafted this release left `append()` --
the most common list write -- opening with a whole-list range Query on
every call (always cold, since ``property.py`` mints a fresh
``ListProperty`` per attribute access). Phase 8's ``get_last_in_range``
fetches the last rank for one item's read capacity instead. The stored-hint
design (a CAS'd ``last_rank`` field in the meta row) was considered and
REJECTED -- see Phase 9B's plan section for why; not re-litigated here.

Uses the dict-backed ``FakePropertyDb``/``CountingPropertyDb``/
``StaleLastRankPropertyDb`` fakes from ``test_property_list_integrity.py``.
"""

import json

import fractional_indexing as fi
import pytest

from actingweb.property_list import ListProperty
from tests.test_property_list_integrity import (
    CountingPropertyDb,
    FakePropertyDb,
    StaleLastRankPropertyDb,
    _patch_get_property,
    _seed_list,
    _seed_v2_list,
)


@pytest.fixture
def fake_store():
    return {}


class _CreateCountingPropertyDb(CountingPropertyDb):
    """Adds a ``create_if_not_exists()`` counter on top of
    ``CountingPropertyDb``'s ``get_range``/``get_last_in_range`` counts --
    ``extend()``'s "one last-rank read, n conditional creates" claim needs
    all three."""

    def __init__(self, store):
        super().__init__(store)
        self.create_call_count = 0

    def create_if_not_exists(self, actor_id=None, name=None, value=None):
        self.create_call_count += 1
        return super().create_if_not_exists(actor_id=actor_id, name=name, value=value)


class TestAppendIssuesOneLastRankReadAndNoRangeQuery:
    def test_append_to_a_populated_list_issues_zero_get_range_and_one_last_rank_read(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-9b-append-counts"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["a", "b", "c"])
        fake_db = CountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("d")

        assert fake_db.range_call_count == 0
        assert fake_db.last_in_range_call_count == 1
        assert lst.to_list() == ["a", "b", "c", "d"]

    def test_append_does_not_populate_a_cold_rank_cache(self, monkeypatch, fake_store):
        """Phase 9B's append() never LOADS a cold rank cache -- a
        single-row read has nothing correct to seed a full rank list
        with, and the callers that DO need the full list (``__setitem__``,
        ``insert()``, etc.) still force their own reload via
        ``_v2_ensure_rank_cache()``, unaffected.

        It DOES keep an already-warm cache in sync (see
        ``TestAppendKeepsAWarmRankCacheInSync`` below) -- that is a
        correctness requirement, not an optimization, found via a hang in
        ``tests/integration/test_post_properties.py``: a caller that warms
        the cache with ``len(list_prop)`` and then loops
        ``append()``/``len()`` on the SAME instance needs each append to
        advance what ``len()`` reports.
        """
        actor_id = "actor-9b-append-nocache"
        name = "notes"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        assert lst._v2_rank_cache is None  # noqa: SLF001

        lst.append("a")

        assert lst._v2_rank_cache is None  # noqa: SLF001
        assert lst.to_list() == ["a"]


class TestAppendKeepsAWarmRankCacheInSync:
    """The regression pin for the Phase 9B hang: ``len()`` must reflect
    ``append()`` immediately on the SAME instance whenever something
    earlier on that instance already warmed the rank cache -- exactly the
    shape of ``handlers/properties.py``'s bulk-update pass 1
    (``while len(list_prop) <= index: list_prop.append(None)``), which
    spun forever once ``append()`` stopped updating the cache ``len()``
    reads."""

    def test_len_reflects_append_immediately_when_the_cache_was_already_warm(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-9b-warm-cache"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, [])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        assert len(lst) == 0  # warms _v2_rank_cache to []

        lst.append("a")
        assert len(lst) == 1  # must NOT still read the pre-append cache

        lst.append("b")
        assert len(lst) == 2

    def test_the_exact_bulk_handler_shape_terminates(self, monkeypatch, fake_store):
        """``while len(list_prop) <= index: list_prop.append(None)`` for
        index=2 on a brand-new list -- the literal loop shape from
        ``handlers/properties.py``'s Pass 1, run directly against
        ``ListProperty`` rather than through HTTP."""
        actor_id = "actor-9b-bulk-shape"
        name = "notes"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        index = 2
        projected_length = len(lst)  # warms the cache, as the handler does
        assert projected_length == 0

        iterations = 0
        while len(lst) <= index:
            lst.append(None)
            iterations += 1
            assert iterations <= index + 1, "loop failed to terminate"

        assert lst.to_list() == [None, None, None]


class TestAppendToEmptyList:
    def test_first_rank_matches_what_the_rank_cache_path_produced(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-9b-empty"
        name = "notes"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("first")

        stored_names = [
            k[1] for k in fake_store if k[0] == actor_id and "list:notes-#" in k[1]
        ]
        assert len(stored_names) == 1
        prefix_len = len(f"list:{name}-#")
        actual_rank = stored_names[0][prefix_len:]
        # generate_last_in_range()->None is the same input the OLD
        # rank-cache path fed generate_key_between() for an empty list --
        # deterministic generation means the produced rank is identical.
        assert actual_rank == fi.generate_key_between(None, None)


class TestAppendRankCollisionRetriesAgainstFreshLastRank:
    def test_retry_lands_strictly_after_the_concurrent_writers_rank(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-9b-collision"
        name = "notes"
        fake_store[(actor_id, "list:notes-#a0")] = json.dumps("concurrent-writer")

        fake_db = StaleLastRankPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)
        lst = ListProperty(actor_id=actor_id, name=name, config=object())

        lst.append("mine")

        assert fake_db.last_in_range_calls >= 2
        assert lst.to_list() == ["concurrent-writer", "mine"]
        pairs = sorted(
            (name, value)
            for (aid, name), value in fake_store.items()
            if aid == actor_id and "list:notes-#" in name
        )
        ranks = [name.rsplit("#", 1)[1] for name, _ in pairs]
        assert ranks[0] < ranks[1], "the retried candidate must sort after a0"


class TestExtendBatchesOneLastRankReadForTheWholeCall:
    def test_extend_of_n_items_issues_one_last_rank_read_and_n_creates(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-9b-extend"
        name = "notes"
        fake_db = _CreateCountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.extend(["a", "b", "c", "d"])

        assert fake_db.range_call_count == 0
        assert fake_db.last_in_range_call_count == 1
        assert fake_db.create_call_count == 4
        assert lst.to_list() == ["a", "b", "c", "d"]

    def test_extend_iteration_order_matches_insertion_order(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-9b-extend-order"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, ["existing"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.extend(["a", "b", "c"])

        assert lst.to_list() == ["existing", "a", "b", "c"]

    def test_len_reflects_extend_immediately_when_the_cache_was_already_warm(
        self, monkeypatch, fake_store
    ):
        """The ``extend()`` counterpart of
        ``TestAppendKeepsAWarmRankCacheInSync`` -- same hang shape, batched."""
        actor_id = "actor-9b-extend-warm-cache"
        name = "notes"
        _seed_v2_list(fake_store, actor_id, name, [])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        assert len(lst) == 0  # warms _v2_rank_cache to []

        lst.extend(["a", "b", "c"])

        assert len(lst) == 3  # must NOT still read the pre-extend cache

    def test_extend_of_a_single_item_matches_append(self, monkeypatch, fake_store):
        actor_id = "actor-9b-extend-one"
        name = "notes"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.extend(["solo"])

        assert lst.to_list() == ["solo"]

    def test_extend_of_zero_items_is_a_no_op(self, monkeypatch, fake_store):
        actor_id = "actor-9b-extend-empty"
        name = "notes"
        fake_db = _CreateCountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.extend([])

        assert fake_db.last_in_range_call_count == 0
        assert (actor_id, "list:notes-meta") not in fake_store


class TestExtendRankCollisionReKeysFromTheCollisionPoint:
    def test_a_mid_batch_collision_re_keys_only_the_remaining_items(
        self, monkeypatch, fake_store
    ):
        """One writer's extend() races another writer's single append()
        that lands between two of the batch's planned ranks."""
        actor_id = "actor-9b-extend-collision"
        name = "notes"
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        real_create = FakePropertyDb.create_if_not_exists
        calls = {"n": 0}

        def _flaky_create(self, actor_id=None, name=None, value=None):
            calls["n"] += 1
            if calls["n"] == 2:
                # Simulate a concurrent writer stealing the SECOND
                # planned rank between our read and our write.
                self.store[(actor_id, name)] = json.dumps("stolen-by-concurrent-writer")
                return False
            return real_create(self, actor_id=actor_id, name=name, value=value)

        monkeypatch.setattr(FakePropertyDb, "create_if_not_exists", _flaky_create)

        lst.extend(["a", "b", "c"])

        result = lst.to_list()
        assert "a" in result
        assert "stolen-by-concurrent-writer" in result
        assert "b" in result
        assert "c" in result
        # Order preserved: whatever landed first sorts first.
        assert result.index("a") < result.index("stolen-by-concurrent-writer")
        assert result.index("stolen-by-concurrent-writer") < result.index("b")
        assert result.index("b") < result.index("c")


class TestV1AppendIsUntouchedByPhase9B:
    def test_v1_append_never_calls_get_last_in_range(self, monkeypatch, fake_store):
        actor_id = "actor-9b-v1-regression"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a", "b"])
        fake_db = CountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.append("c")

        assert fake_db.last_in_range_call_count == 0
        assert lst.to_list() == ["a", "b", "c"]

    def test_v1_extend_never_calls_get_last_in_range(self, monkeypatch, fake_store):
        actor_id = "actor-9b-v1-extend-regression"
        name = "notes"
        _seed_list(fake_store, actor_id, name, ["a"])
        fake_db = CountingPropertyDb(fake_store)
        _patch_get_property(monkeypatch, lambda config: fake_db)

        lst = ListProperty(actor_id=actor_id, name=name, config=object())
        lst.extend(["b", "c"])

        assert fake_db.last_in_range_call_count == 0
        assert lst.to_list() == ["a", "b", "c"]


class TestLastRankSkipsALegacyHashSiblingsRows:
    """A v2 list's byte range is NOT sufficient to isolate its rows (see
    ``TestV2LegacyHashSiblingIsolation`` in ``test_property_list_integrity.py``
    for the general case). ``get_last_in_range()`` has no notion of rank
    shape, so when a legacy ``#``-named sibling's OWN row (e.g. its
    ``-meta`` suffix) happens to be the bytewise-greatest row in the
    owner's range, it comes back as the "last rank" -- and feeding that
    straight to ``fi.generate_key_between()`` raises ``FIError``.

    Found via a real failure in
    ``tests/integration/test_migrate_property_lists_script.py::
    TestDowngradeToV1::test_downgrade_does_not_delete_a_hash_named_sibling_list``.
    """

    LEGACY = "foo-#bar"
    OWNER = "foo"

    def test_append_after_a_legacy_siblings_meta_row_does_not_raise(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-9b-legacy-sibling"
        # The legacy list's '-meta' row sorts after 'foo-#a...' rank rows
        # (byte-for-byte: 'm' > every base62 digit/letter fi generates for
        # a 2-item list), so it is the bytewise-greatest row in the
        # owner's ['list:foo-#', 'list:foo-$') range.
        _seed_list(fake_store, actor_id, self.LEGACY, ["legacy-a", "legacy-b"])
        _seed_v2_list(fake_store, actor_id, self.OWNER, ["mine-1", "mine-2"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        owner = ListProperty(actor_id=actor_id, name=self.OWNER, config=object())
        owner.append("mine-3")

        assert owner.to_list() == ["mine-1", "mine-2", "mine-3"]
        legacy = ListProperty(actor_id=actor_id, name=self.LEGACY, config=object())
        assert legacy.to_list() == ["legacy-a", "legacy-b"]

    def test_extend_after_a_legacy_siblings_meta_row_does_not_raise(
        self, monkeypatch, fake_store
    ):
        actor_id = "actor-9b-legacy-sibling-extend"
        _seed_list(fake_store, actor_id, self.LEGACY, ["legacy-a", "legacy-b"])
        _seed_v2_list(fake_store, actor_id, self.OWNER, ["mine-1", "mine-2"])
        _patch_get_property(monkeypatch, lambda config: FakePropertyDb(fake_store))

        owner = ListProperty(actor_id=actor_id, name=self.OWNER, config=object())
        owner.extend(["mine-3", "mine-4"])

        assert owner.to_list() == ["mine-1", "mine-2", "mine-3", "mine-4"]
