"""The four permission-path stores keep a bounded LRU cache.

Each used a plain dict on a process-wide singleton that grew with every
actor:peer pair the process ever saw (thoughts/todo, permission-path caches).
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from actingweb._bounded_cache import CACHE_MAX_ENTRIES, BoundedDict
from actingweb.peer_capabilities import CachedCapabilitiesStore
from actingweb.peer_permissions import PeerPermissionStore
from actingweb.peer_profile import PeerProfileStore
from actingweb.trust_permissions import TrustPermissionStore


@pytest.mark.parametrize(
    "store_cls",
    [
        TrustPermissionStore,
        PeerProfileStore,
        PeerPermissionStore,
        CachedCapabilitiesStore,
    ],
)
def test_each_store_caches_in_a_bounded_dict(store_cls: Any) -> None:
    store = store_cls(mock.Mock())
    assert isinstance(store._cache, BoundedDict)  # pyright: ignore[reportPrivateUsage]
    assert store._cache.maxsize == CACHE_MAX_ENTRIES  # pyright: ignore[reportPrivateUsage]


def _store_with_bucket(rows: dict[str, Any]) -> tuple[TrustPermissionStore, Any]:
    store = TrustPermissionStore(mock.Mock())
    bucket = mock.Mock()
    bucket.get_attr.side_effect = lambda name: rows.get(name)
    return store, bucket


def test_a_cached_no_override_is_not_read_again() -> None:
    store, bucket = _store_with_bucket({})
    with mock.patch.object(store, "_get_permissions_bucket", return_value=bucket):
        assert store.get_permissions("a1", "p1") is None
        assert store.get_permissions("a1", "p1") is None
    assert bucket.get_attr.call_count == 1


def test_an_evicted_pair_is_read_again() -> None:
    store, bucket = _store_with_bucket({})
    store._cache = BoundedDict(2)  # pyright: ignore[reportPrivateUsage]
    with mock.patch.object(store, "_get_permissions_bucket", return_value=bucket):
        for peer in ("p1", "p2", "p3"):  # p1 is evicted by p3
            store.get_permissions("a1", peer)
        assert bucket.get_attr.call_count == 3
        store.get_permissions("a1", "p1")
    assert bucket.get_attr.call_count == 4


# 3.16: the override cache expires an entry after 300 seconds, so a change
# another process stored is in force here within that window.


class _Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    from actingweb import _bounded_cache

    c = _Clock()
    monkeypatch.setattr(_bounded_cache, "_monotonic", c)
    return c


def _row(methods: list[str]) -> dict[str, Any]:
    return {
        "data": json.dumps(
            {
                "actor_id": "a1",
                "peer_id": "p1",
                "trust_type": "friend",
                "methods": {"allowed": methods},
            }
        )
    }


def test_an_override_changed_elsewhere_is_in_force_after_the_window(
    clock: _Clock,
) -> None:
    rows: dict[str, Any] = {"a1:p1": _row(["read"])}
    store, bucket = _store_with_bucket(rows)
    with mock.patch.object(store, "_get_permissions_bucket", return_value=bucket):
        first = store.get_permissions("a1", "p1")
        assert first is not None and first.methods == {"allowed": ["read"]}
        rows["a1:p1"] = _row([])  # another process narrows the grant
        clock.now += 301
        now = store.get_permissions("a1", "p1")
    assert now is not None and now.methods == {"allowed": []}


def test_an_override_stored_elsewhere_replaces_a_cached_absence_after_the_window(
    clock: _Clock,
) -> None:
    rows: dict[str, Any] = {}
    store, bucket = _store_with_bucket(rows)
    with mock.patch.object(store, "_get_permissions_bucket", return_value=bucket):
        assert store.get_permissions("a1", "p1") is None
        rows["a1:p1"] = _row(["read"])
        clock.now += 301
        now = store.get_permissions("a1", "p1")
    assert now is not None and now.methods == {"allowed": ["read"]}


def test_an_entry_just_inside_the_window_reads_nothing(clock: _Clock) -> None:
    rows: dict[str, Any] = {"a1:p1": _row(["read"])}
    store, bucket = _store_with_bucket(rows)
    with mock.patch.object(store, "_get_permissions_bucket", return_value=bucket):
        store.get_permissions("a1", "p1")
        rows["a1:p1"] = _row([])
        clock.now += 299.9
        cached = store.get_permissions("a1", "p1")
    assert cached is not None and cached.methods == {"allowed": ["read"]}
    assert bucket.get_attr.call_count == 1


def test_a_store_and_a_delete_here_are_seen_at_once(clock: _Clock) -> None:
    from actingweb.trust_permissions import TrustPermissions

    rows: dict[str, Any] = {}
    store, bucket = _store_with_bucket(rows)
    bucket.set_attr.return_value = True
    bucket.delete_attr.return_value = True
    with (
        mock.patch.object(store, "_get_permissions_bucket", return_value=bucket),
        mock.patch("actingweb.mcp.invalidation.evict_caches_for_actor"),
    ):
        assert store.get_permissions("a1", "p1") is None
        stored = TrustPermissions(
            actor_id="a1",
            peer_id="p1",
            trust_type="friend",
            methods={"allowed": ["read"]},
        )
        assert store.store_permissions(stored, notify_peer=False)
        seen = store.get_permissions("a1", "p1")
        assert seen is not None and seen.methods == {"allowed": ["read"]}
        assert store.delete_permissions("a1", "p1")
        assert store.get_permissions("a1", "p1") is None


def test_update_permissions_merges_from_storage(clock: _Clock) -> None:
    rows: dict[str, Any] = {"a1:p1": _row(["read"])}
    store, bucket = _store_with_bucket(rows)
    with mock.patch.object(store, "_get_permissions_bucket", return_value=bucket):
        store.get_permissions("a1", "p1")  # cached: methods read
        rows["a1:p1"] = _row([])  # another process narrows methods
        with mock.patch.object(store, "store_permissions", return_value=True) as put:
            assert store.update_permissions("a1", "p1", {"notes": "n"})
    merged = put.call_args.args[0]
    assert merged.methods == {"allowed": []}
    assert merged.notes == "n"


class _RefillingCache(BoundedDict[str, Any]):
    """A cache another thread refills the moment an entry is dropped: what
    it held is what that thread read before this one's write."""

    def __init__(self, stale: Any) -> None:
        super().__init__(CACHE_MAX_ENTRIES)
        self.stale = stale

    def pop(self, key: str, *args: Any) -> Any:
        dropped = super().pop(key, *args)
        self[key] = self.stale
        return dropped


def test_the_uncached_read_is_never_answered_from_the_cache() -> None:
    from actingweb.trust_permissions import TrustPermissions

    rows: dict[str, Any] = {"a1:p1": _row([])}
    store, bucket = _store_with_bucket(rows)
    stale = TrustPermissions.from_dict(json.loads(_row(["read"])["data"]))
    store._cache = _RefillingCache(stale)  # pyright: ignore[reportPrivateUsage]
    store._cache["a1:p1"] = stale  # pyright: ignore[reportPrivateUsage]
    with mock.patch.object(store, "_get_permissions_bucket", return_value=bucket):
        read = store.get_permissions_uncached("a1", "p1")
    assert read is not None and read.methods == {"allowed": []}
