"""``actingweb._bounded_cache.BoundedDict``: a locked LRU dict."""

from __future__ import annotations

import threading

import pytest

from actingweb._bounded_cache import BoundedDict


def test_past_maxsize_the_least_recently_used_entry_goes() -> None:
    cache: BoundedDict[str, int] = BoundedDict(2)
    cache["a"] = 1
    cache["b"] = 2
    cache["c"] = 3
    assert list(cache) == ["b", "c"]


@pytest.mark.parametrize("read", ["getitem", "get", "lookup"])
def test_a_read_refreshes_recency(read: str) -> None:
    cache: BoundedDict[str, int] = BoundedDict(2)
    cache["a"] = 1
    cache["b"] = 2
    if read == "getitem":
        assert cache["a"] == 1
    elif read == "get":
        assert cache.get("a") == 1
    else:
        assert cache.lookup("a") == (True, 1)
    cache["c"] = 3
    assert "a" in cache and "b" not in cache


def test_lookup_tells_a_cached_none_from_a_miss() -> None:
    cache: BoundedDict[str, int | None] = BoundedDict(4)
    cache["neg"] = None
    assert cache.lookup("neg") == (True, None)
    assert cache.lookup("absent") == (False, None)
    assert cache.get("absent", "dflt") == "dflt"


def test_it_still_behaves_as_a_dict() -> None:
    cache: BoundedDict[str, int] = BoundedDict(4)
    assert cache == {}
    cache["a"] = 1
    assert cache == {"a": 1}
    assert cache.pop("a") == 1
    assert cache.pop("a", None) is None
    cache["b"] = 2
    cache.clear()
    assert cache == {} and len(cache) == 0


def test_maxsize_must_be_positive() -> None:
    with pytest.raises(ValueError):
        BoundedDict(0)


def test_concurrent_reads_and_evicting_writes_never_raise() -> None:
    cache: BoundedDict[int, int] = BoundedDict(8)
    errors: list[BaseException] = []

    def worker(offset: int) -> None:
        try:
            for i in range(2000):
                key = (i + offset) % 32
                cache[key] = i
                cache.lookup((key + 1) % 32)
                cache.pop((key + 2) % 32, None)
                assert len(cache) <= 8
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(cache) <= 8


def test_copy_pickle_and_iterating_while_indexing_work() -> None:
    import copy
    import pickle

    cache: BoundedDict[str, int] = BoundedDict(3)
    for key, value in (("a", 1), ("b", 2), ("c", 3)):
        cache[key] = value
    assert [cache[k] for k in cache] == [1, 2, 3]  # reads reorder; no error
    for clone in (cache.copy(), copy.copy(cache), copy.deepcopy(cache)):
        assert clone == cache and clone.maxsize == 3 and clone is not cache
    restored = pickle.loads(pickle.dumps(cache))
    assert restored == cache and restored.maxsize == 3
    restored["d"] = 4
    assert len(restored) == 3
