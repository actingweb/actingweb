"""A size-bounded, thread-safe LRU dict for per-process caches.

The permission-path stores (``trust_permissions``, ``peer_profile``,
``peer_permissions``, ``peer_capabilities``) cache one entry per
``actor:peer`` pair in a dict on a process-wide singleton. A plain dict grows
with every pair the process ever sees; this bounds it, evicting the least
recently used entry.

Reads go through :meth:`BoundedDict.lookup`, which answers hit/miss and the
value under one lock. A ``key in cache`` followed by ``cache[key]`` can see
the key evicted in between (a plain dict never removes a key on its own, so
that two-step read was safe before), and ``get()`` cannot tell a cached
``None`` (``TrustPermissionStore``'s "no override stored") from a miss.

With a ``ttl`` an entry also expires: every read treats one set more than
``ttl`` seconds ago as absent and drops it. The time an entry was set is kept
beside it under the same lock, and only ``__setitem__`` writes it, so no
writer of the cache can store a value without its stamp.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, TypeVar

K = TypeVar("K")
V = TypeVar("V")

_MISSING: Any = object()

# The clock entries are stamped with; a module reference so a test can
# replace it. Monotonic: wall-clock time moving back keeps nothing alive.
_monotonic = time.monotonic

# Per store, per process. Four times the permission evaluator's pattern bound
# (permission_evaluator._PATTERN_CACHE_MAX_ENTRIES), since keys are pairs;
# above it a store degrades to reading through to the database, which is
# correct, only slower.
CACHE_MAX_ENTRIES = 4096


class BoundedDict(OrderedDict[K, V]):
    """An ``OrderedDict`` that keeps at most ``maxsize`` entries (LRU).

    Every read or write refreshes the entry's recency (not its age: only a
    write restamps it). It stays a dict, so ``== {}``, ``pop`` and ``clear``
    behave as before. ``ttl`` (seconds) makes entries expire; ``None``, the
    default, never.
    """

    def __init__(
        self, maxsize: int = CACHE_MAX_ENTRIES, ttl: float | None = None
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        if ttl is not None and ttl <= 0:
            raise ValueError("ttl must be positive")
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl
        self._set_at: dict[Any, float] = {}
        self._lock = threading.RLock()

    def _expired(self, key: Any) -> bool:
        """Drop ``key`` when it is older than the ttl; caller holds the lock."""
        if self.ttl is None:
            return False
        set_at = self._set_at.get(key)
        # An entry without a stamp is expired: the cache fails closed.
        if set_at is not None and _monotonic() - set_at <= self.ttl:
            return False
        super().pop(key, None)
        self._set_at.pop(key, None)
        return True

    def _drop_expired(self) -> None:
        if self.ttl is None:
            return
        for key in list(super().__iter__()):
            self._expired(key)

    def lookup(self, key: K) -> tuple[bool, V | None]:
        """``(True, value)`` for a cached key, ``(False, None)`` otherwise."""
        with self._lock:
            value = super().get(key, _MISSING)
            if value is _MISSING or self._expired(key):
                return False, None
            self.move_to_end(key)
            return True, value

    def __getitem__(self, key: K) -> V:
        with self._lock:
            if self._expired(key):
                raise KeyError(key)
            value = super().__getitem__(key)
            self.move_to_end(key)
            return value

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return super().__contains__(key) and not self._expired(key)

    def get(self, key: K, default: Any = None) -> Any:  # type: ignore[override]
        hit, value = self.lookup(key)
        return value if hit else default

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            super().__setitem__(key, value)
            if self.ttl is not None:
                self._set_at[key] = _monotonic()
            self.move_to_end(key)
            while len(self) > self.maxsize:
                self.popitem(last=False)

    def pop(self, key: K, *args: Any) -> Any:  # type: ignore[override]
        with self._lock:
            if self._expired(key):
                if args:
                    return args[0]
                raise KeyError(key)
            self._set_at.pop(key, None)
            return super().pop(key, *args)

    def clear(self) -> None:
        with self._lock:
            super().clear()
            self._set_at.clear()

    def __delitem__(self, key: K) -> None:
        with self._lock:
            super().__delitem__(key)
            self._set_at.pop(key, None)

    # The remaining mutators take the lock too, and the inserting ones go
    # through __setitem__ so the bound holds.
    def setdefault(self, key: K, default: Any = None) -> Any:  # type: ignore[override]
        with self._lock:
            hit, value = self.lookup(key)
            if hit:
                return value
            self[key] = default
            return default

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        merged: dict[Any, Any] = dict(*args, **kwargs)
        with self._lock:
            for key, value in merged.items():
                self[key] = value

    def popitem(self, last: bool = True) -> tuple[K, V]:
        with self._lock:
            key, value = super().popitem(last=last)
            self._set_at.pop(key, None)
            return key, value

    def move_to_end(self, key: K, last: bool = True) -> None:
        with self._lock:
            super().move_to_end(key, last=last)

    # Reads move entries, so iterating the live dict while indexing it (or
    # while another thread reads) would raise "mutated during iteration":
    # iterate a snapshot taken under the lock instead.
    # Expired entries are dropped before the snapshot.
    def __iter__(self) -> Any:
        with self._lock:
            self._drop_expired()
            return iter(list(super().__iter__()))

    def items(self) -> Any:  # type: ignore[override]
        with self._lock:
            self._drop_expired()
            return list(super().items())

    def values(self) -> Any:  # type: ignore[override]
        with self._lock:
            self._drop_expired()
            return list(super().values())

    def keys(self) -> Any:  # type: ignore[override]
        with self._lock:
            self._drop_expired()
            return list(super().keys())

    def copy(self) -> BoundedDict[K, V]:
        # A copy's entries start a fresh window.
        new: BoundedDict[K, V] = BoundedDict(self.maxsize, self.ttl)
        for key, value in self.items():
            new[key] = value
        return new

    def __copy__(self) -> BoundedDict[K, V]:
        return self.copy()

    def __reduce__(self) -> Any:
        # The lock is not picklable; rebuild it, keeping maxsize, ttl and
        # entries (which start a fresh window).
        return (type(self), (self.maxsize, self.ttl), None, None, iter(self.items()))
