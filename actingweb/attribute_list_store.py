"""
AttributeListStore - the attribute lists of one bucket.

The attribute counterpart of ``PropertyListStore``: the same interface over
one actor's bucket (``actor.attribute_lists(bucket)``). See
``actingweb.attribute_list`` for the row layout and the old layout it
converts.
"""

import logging
import re
from collections.abc import Callable
from typing import Any

from .attribute_list import AttributeListStorage, ListAttribute
from .identifiers import first_control_character

logger = logging.getLogger(__name__)

_TOP = "\U0010ffff"
_NEW_ITEM_RE = re.compile(r"^list:(.*)-#[0-9A-Za-z]+\Z", re.S)
_NEW_META_RE = re.compile(r"^list:(.*)-meta\Z", re.S)
_OLD_ITEM_RE = re.compile(r"^list:(.*):\d+\Z", re.S)
_OLD_META_RE = re.compile(r"^list:(.*):meta\Z", re.S)


def _below(name: str) -> str:
    """An inclusive upper bound below ``name`` that every string sorting
    before it meets (by code point, which is UTF-8 byte order)."""
    if not name:
        return ""
    last = ord(name[-1])
    if last == 0:
        return name[:-1]
    last -= 1
    if 0xD800 <= last <= 0xDFFF:
        last = 0xD7FF  # no surrogate in a bound
    return name[:-1] + chr(last) + _TOP


class AttributeListStore:
    """The attribute lists of one actor's bucket."""

    def __init__(
        self,
        actor_id: str | None = None,
        bucket: str | None = None,
        config: Any | None = None,
    ) -> None:
        self._actor_id = actor_id
        self._bucket = bucket
        self._config = config
        self.__initialised = True

    def _storage(self) -> AttributeListStorage | None:
        if not (self._config and self._actor_id and self._bucket):
            return None
        return AttributeListStorage(self._actor_id, self._bucket, self._config)

    def exists(self, name: str) -> bool:
        """Whether the list exists, in either layout: one or two point
        reads, never a write. A fault raises ``DbError``."""
        storage = self._storage()
        if storage is None:
            return False
        return (
            storage.get(f"list:{name}-meta") is not None
            or storage.get(f"list:{name}:meta") is not None
        )

    def list_all(self, *, strict: bool = False) -> list[str]:
        """The names of the bucket's lists, in either layout.

        A skip-scan, never a whole-bucket read: one "greatest name below
        the cursor" read per list (and per row of a list still in the old
        layout's metadata), jumping past a list's item rows as a block.
        ``strict=True`` raises ``DbError`` on a fault instead of answering
        ``[]`` (a caller deleting what it lists must not read a fault as
        "nothing to delete").

        Known gap: a list whose name continues another list's name with
        ``-#`` (``a-#x``, possible only for a pre-3.16 list) or ``:<digit>``
        (``a:1x``, of either layout) beside that list has its rows inside the
        other list's item block, which the walk jumps, and is not listed.
        """
        try:
            return self._skip_scan()
        except Exception as e:  # folds DbError: documented [] unless strict
            if strict:
                raise
            logger.error(f"Error in list_all(): {e}")
            return []

    def _skip_scan(self, on_read: Callable[[], None] | None = None) -> list[str]:
        """``list_all()``'s walk; ``on_read`` runs before each read (the
        operator tool paces its reads with it)."""
        storage = self._storage()
        if storage is None:
            return []
        found: dict[str, None] = {}
        upper = "list:" + _TOP
        while True:
            if on_read is not None:
                on_read()
            row = storage.get_last_in_range("list:", upper)
            if row is None:
                break
            if match := _OLD_META_RE.match(row):
                found[match.group(1)] = None
                upper = _below(row)
            elif match := _OLD_ITEM_RE.match(row):
                # The old layout's item rows of this list, as one block.
                upper = _below(f"list:{match.group(1)}:0")
            elif match := _NEW_META_RE.match(row):
                found[match.group(1)] = None
                upper = _below(row)
            elif match := _NEW_ITEM_RE.match(row):
                upper = _below(f"list:{match.group(1)}-#")
            else:
                # A scalar whose name starts "list:" (refused since 3.16).
                upper = _below(row)
            if upper < "list:":
                break
        return sorted(found)

    def list_all_with_rows(self) -> tuple[list[str], dict[str, str]]:
        """The bucket's list names and every list row (as the core reads
        them), for ``prime_from_rows()`` / ``to_list_from_rows()``.

        Reads every row whose name starts ``list:`` (that is what the rows
        are for). A list still in the old layout is named, but its rows are
        not in the format ``to_list_from_rows()`` reads until its first
        change converts it. On a fault this returns ``([], {})``, as
        ``PropertyListStore.list_all_with_rows()`` does."""
        storage = self._storage()
        if storage is None:
            return [], {}
        try:
            rows = storage.get_prefix("list:")
            names = self._skip_scan()
        except Exception as e:  # folds DbError: documented ([], {}) on error
            logger.error(f"Error in list_all_with_rows(): {e}")
            return [], {}
        return names, rows

    def list_prefix_with_rows(self, prefix: str) -> tuple[list[str], dict[str, str]]:
        """Lists whose name begins with ``prefix`` and their rows, as
        ``PropertyListStore.list_prefix_with_rows()`` (eventually
        consistent; a fault raises ``DbError``; names from ``-meta`` rows).

        Raises:
            ValueError: ``prefix`` is empty.
        """
        if not prefix:
            raise ValueError(
                "list_prefix_with_rows() needs a non-empty prefix; call "
                "list_all_with_rows() for every list."
            )
        storage = self._storage()
        if storage is None:
            return [], {}
        rows = storage.get_prefix(f"list:{prefix}", consistent_read=False)
        names = [
            name[5:-5]
            for name in rows
            if name.startswith("list:") and name.endswith("-meta")
        ]
        return names, rows

    def get(self, name: str) -> ListAttribute:
        """The list named ``name`` (created on its first write). Any string,
        unlike attribute access: ``store.get("exists")`` is the list named
        ``exists``."""
        if self._actor_id is None:
            raise RuntimeError("Cannot create ListAttribute without a valid actor_id")
        if self._bucket is None:
            raise RuntimeError("Cannot create ListAttribute without a valid bucket")
        return ListAttribute(self._actor_id, self._bucket, name, self._config)

    def __getattr__(self, k: str) -> ListAttribute:
        """Return a ListAttribute for the requested list name."""
        if k.startswith("_"):
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{k}'"
            )
        if self._actor_id is None:
            raise RuntimeError("Cannot create ListAttribute without a valid actor_id")
        if self._bucket is None:
            raise RuntimeError("Cannot create ListAttribute without a valid bucket")
        # A list name with a control character cannot be created (see
        # identifiers.py). One that already exists stays reachable so its
        # owner can still read it and delete it.
        bad = first_control_character(k)
        if bad is not None and not self.exists(k):
            raise ValueError(
                f"Cannot create list attribute {k!r}: name contains the "
                f"control character {bad}"
            )
        return self.get(k)
