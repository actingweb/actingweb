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
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, TypeVar

K = TypeVar("K")
V = TypeVar("V")

_MISSING: Any = object()

# Per store, per process. Four times the permission evaluator's pattern bound
# (permission_evaluator._PATTERN_CACHE_MAX_ENTRIES), since keys are pairs;
# above it a store degrades to reading through to the database, which is
# correct, only slower.
CACHE_MAX_ENTRIES = 4096


class BoundedDict(OrderedDict[K, V]):
    """An ``OrderedDict`` that keeps at most ``maxsize`` entries (LRU).

    Every read or write refreshes the entry's recency. It stays a dict, so
    ``== {}``, ``pop`` and ``clear`` behave as before.
    """

    def __init__(self, maxsize: int) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        super().__init__()
        self.maxsize = maxsize
        self._lock = threading.RLock()

    def lookup(self, key: K) -> tuple[bool, V | None]:
        """``(True, value)`` for a cached key, ``(False, None)`` otherwise."""
        with self._lock:
            value = super().get(key, _MISSING)
            if value is _MISSING:
                return False, None
            self.move_to_end(key)
            return True, value

    def __getitem__(self, key: K) -> V:
        with self._lock:
            value = super().__getitem__(key)
            self.move_to_end(key)
            return value

    def get(self, key: K, default: Any = None) -> Any:  # type: ignore[override]
        hit, value = self.lookup(key)
        return value if hit else default

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            super().__setitem__(key, value)
            self.move_to_end(key)
            while len(self) > self.maxsize:
                self.popitem(last=False)

    def pop(self, key: K, *args: Any) -> Any:  # type: ignore[override]
        with self._lock:
            return super().pop(key, *args)

    def clear(self) -> None:
        with self._lock:
            super().clear()

    def __delitem__(self, key: K) -> None:
        with self._lock:
            super().__delitem__(key)
