"""The four permission-path stores keep a bounded LRU cache.

Each used a plain dict on a process-wide singleton that grew with every
actor:peer pair the process ever saw (thoughts/todo, permission-path caches).
"""

from __future__ import annotations

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
