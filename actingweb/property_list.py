"""
ListProperty implementation for ActingWeb distributed list storage.

This module provides a list interface that stores each list item as its own
property row, so the backend's row-size limit applies per item, not per list,
while keeping a Python list API. On a v2 list an item larger than the span
threshold spans several rows: its head row (in the list's own range) holds an
envelope naming a body generation, and the bodies live in the actor's side
partition (see ``actingweb.property_list_span``). An item larger than
``list_item_max_bytes`` is refused with ``ListItemTooLargeError`` before
anything is written.
"""

import json
import logging
import os
import re
import time as time  # consumers patch "actingweb.property_list.time.sleep"
from collections.abc import Iterator
from datetime import datetime
from typing import Any, NoReturn

import fractional_indexing as fi

from actingweb.db import get_property
from actingweb.db.exceptions import DbError

# The format moved to list_core; these names are re-exported under their
# pre-4.0 names. Patching one of them on this module changes nothing (the
# code that reads it is in list_core): patch actingweb.list_core instead.
from actingweb.list_core import (
    _KEYED_IN_FLIGHT_SECONDS as _KEYED_IN_FLIGHT_SECONDS,
)
from actingweb.list_core import (
    _METADATA_CAS_ADVISORY_MAX_ATTEMPTS as _METADATA_CAS_ADVISORY_MAX_ATTEMPTS,
)
from actingweb.list_core import (
    _METADATA_CAS_MAX_ATTEMPTS as _METADATA_CAS_MAX_ATTEMPTS,
)
from actingweb.list_core import (
    _V2_MAX_RANK_RETRIES as _V2_MAX_RANK_RETRIES,
)
from actingweb.list_core import (
    _V2_RANK_ALPHABET as _V2_RANK_ALPHABET,
)
from actingweb.list_core import (
    _V2_RANK_MARKER,
    UNRESOLVED,
    AppendOnceResult,
    ListCore,
    ListCorruptionError,
    ListItemHandle,
    ListItemNewerFormatError,
    ListItemSpanError,
    ListItemTooLargeError,
    ListLayoutConflictError,
    ListMetadataContentionError,
    ListRankExhaustedError,
)
from actingweb.list_core import (
    _V2_RANK_MAX_LEN as _V2_RANK_MAX_LEN,
)
from actingweb.list_core import (
    _V2_RANK_WARNING_LENGTH as _V2_RANK_WARNING_LENGTH,
)
from actingweb.list_core import (
    _ItemGone as _ItemGone,
)
from actingweb.list_core import (
    _v2_is_rank as _v2_is_rank,
)
from actingweb.property_list_span import (
    aux_partition,
    encoded_size,
    looks_like_envelope,
)

logger = logging.getLogger(__name__)

_V2_LAZY_MIGRATION_MAX_LENGTH = 0
_lazy_migration_nudge_logged = False
# Shape filter for a v1 item row's suffix. The v1 byte range alone is not
# enough to isolate a list's rows -- a sibling list whose NAME starts with a
# digit ("foo-5") stores "list:foo-5-0", which sorts inside list "foo"'s
# range. The suffix "5-0" fails this pattern; a genuine "list:foo-7" row's
# suffix "7" passes. Same role _v2_is_rank() plays for the v2 range.
_V1_INDEX_RE = re.compile(r"^\d+\Z")

__all__ = [
    "LIST_DIFF_OPERATIONS",
    "UNRESOLVED",
    "UNSET",
    "AppendOnceResult",
    "ListCorruptionError",
    "ListItemHandle",
    "ListItemSpanError",
    "ListItemNewerFormatError",
    "ListItemTooLargeError",
    "ListLayoutConflictError",
    "ListMetadataContentionError",
    "ListProperty",
    "ListPropertyIterator",
    "ListRankExhaustedError",
    "PropertyListStorage",
    "build_list_diff",
    "diff_reference",
    "spanned_reference",
]


def _lazy_migration_max_length() -> int:
    """Largest EXISTING v1 list that may migrate inline, during a user's
    write. ``0`` (the default) means none: no existing list ever changes
    format without an operator running
    ``scripts/migrate_property_lists.py``.

    Override with ``ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH``; 50 was the
    previous default and is a reasonable value once a release has been live
    long enough that rolling back is off the table.

    **This defaults to off because it is a rollback-safety control, not a
    performance one.** A process running a pre-v2 release does not error on
    a v2 list -- it reads it as *empty*, silently, because v2 stores no
    ``length`` field and an older reader takes the absence as zero. A write
    from that process then lands in v1 storage and the list forks across
    both formats with nothing reporting an error. Deployment gives at most a
    brief mixed-version window; rollback gives none at all -- convert lists
    for hours or days, roll back for an unrelated reason, and every
    converted list reads as empty in production, recoverable only one list
    at a time. With this at 0 a release changes no data, so rolling back is
    a pure code rollback.

    This does NOT make v2 opt-in. Every list created from now on is v2 with
    no operator action; only the conversion of data that already exists is
    deferred to a deliberate, rate-limited step.

    Migration is also inline and synchronous -- an ``append()`` to a 40-item
    v1 list does the whole migration inside that request -- which is the
    second, lesser reason to leave it off in latency-sensitive deployments.
    """
    raw = os.environ.get("ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH")
    if raw is None:
        return _V2_LAZY_MIGRATION_MAX_LENGTH
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning(
            f"Invalid ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH={raw!r} -- "
            f"using the default {_V2_LAZY_MIGRATION_MAX_LENGTH}"
        )
        return _V2_LAZY_MIGRATION_MAX_LENGTH


def _nudge_lazy_migration_disabled() -> None:
    """Say once per process that v1 lists exist and nothing will convert
    them.

    Lazy migration being off by default is the safe choice, but silence
    would turn it into "nobody ever migrates" -- an operator would have to
    already know the script exists to find out they need it. One INFO the
    first time a v1 list is actually encountered names the script, without
    nagging a deployment that intends to stay on v1.
    """
    global _lazy_migration_nudge_logged
    if _lazy_migration_nudge_logged:
        return
    _lazy_migration_nudge_logged = True
    logger.info(
        "Found v1-format list properties while lazy migration is disabled "
        "(ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH=0, the default). They keep "
        "working as v1 indefinitely. To convert them, run "
        "scripts/migrate_property_lists.py --migrate once this release has "
        "been live long enough that rolling back is off the table -- a "
        "pre-v2 process reads a converted list as empty. Logged once per "
        "process."
    )


_DIFF_VALUE_FIELDS = ("item", "old_item", "value", "items")

# "Not passed" for build_list_diff's value fields: None is a legal list item,
# and a diff for a None-valued item must still carry its item/old_item field
# (as JSON null), or the receiver reads a different operation.
UNSET: Any = object()

LIST_DIFF_OPERATIONS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "update",
        "delete",
        "pop",
        "remove",
        "clear",
        "delete_all",
        "metadata",
    }
)


def build_list_diff(
    list_name: str,
    operation: str,
    *,
    length: int,
    config: Any,
    item: Any = UNSET,
    index: int | None = None,
    items: list[Any] | None = None,
    old_item: Any = UNSET,
    spanned_bytes: int | None = None,
) -> dict[str, Any]:
    """The list diff a publisher registers for one change to ``list_name``.

    Every diff carries ``list``, ``operation`` and ``length``; ``item`` and
    ``old_item`` are present whenever passed (``None`` included), ``index``
    and ``items`` when not ``None``. A diff whose encoded blob would exceed
    the span threshold becomes a reference (:func:`diff_reference`); with
    ``spanned_bytes`` it is a reference regardless of size, for a spanned
    item whose value the caller did not read (:func:`spanned_reference`).

    The operation is one of :data:`LIST_DIFF_OPERATIONS`, the receiver's
    closed vocabulary; anything else raises ``ValueError``.
    """
    if operation not in LIST_DIFF_OPERATIONS:
        raise ValueError(f"unknown list diff operation {operation!r}")
    diff: dict[str, Any] = {
        "list": list_name,
        "operation": operation,
        "length": length,
    }
    if item is not UNSET:
        diff["item"] = item
    if index is not None:
        diff["index"] = index
    if items is not None:
        diff["items"] = items
    if old_item is not UNSET:
        diff["old_item"] = old_item
    if spanned_bytes is not None:
        return spanned_reference(diff, config, spanned_bytes)
    return diff_reference(diff, config)


def handle_old_item_fields(list_prop: Any, handle: Any) -> dict[str, Any]:
    """The ``build_list_diff`` fields that name the item a handle held before
    a change, read without its bodies: ``{"old_item": value}``, or
    ``{"spanned_bytes": n}`` for a spanned or malformed item, whose value was
    not read and is never serialised (the diff becomes a reference)."""
    if handle.spanned:
        return {"spanned_bytes": handle.bytes or 0}
    old = list_prop._unresolved_or_item(handle.rank, handle.raw_value)
    if old is UNRESOLVED:
        return {"spanned_bytes": encoded_size(str(handle.raw_value))}
    return {"old_item": old}


def diff_reference(diff: dict[str, Any], config: Any) -> dict[str, Any]:
    """The list-item diff to store and send for ``diff``: unchanged, or a
    *reference* when its encoded blob would exceed the span threshold.

    A ``SubscriptionDiff`` row has the same row cap as a list item, and an
    ``update`` diff carries two values, so the rule applies to the whole
    blob. A reference **removes** the value-carrying fields (``item``,
    ``old_item``, ``value``, ``items``) and adds top-level ``"spanned":
    true`` and ``"bytes"`` (the values' total encoded size). Removed rather
    than replaced by a marker, because a pre-4.0 receiver applies an
    ``append``/``insert``/``update`` whenever ``"item"`` is present and an
    ``extend`` whenever ``"items"`` is: without them an older receiver
    answers ``unknown operation`` and stores nothing. A subscriber that
    receives a reference re-reads the list.

    With no span threshold (PostgreSQL at its defaults) diffs carry their
    values as before.
    """
    span_threshold = getattr(config, "list_item_span_threshold", None)
    if (
        not isinstance(span_threshold, int)
        or isinstance(span_threshold, bool)
        or span_threshold <= 0
    ):
        return diff
    if encoded_size(json.dumps(diff)) <= span_threshold:
        return diff
    return _as_reference(diff, span_threshold)


def _as_reference(
    diff: dict[str, Any], span_threshold: int | None, extra_bytes: int = 0
) -> dict[str, Any]:
    size = extra_bytes + sum(
        encoded_size(json.dumps(diff[field]))
        for field in _DIFF_VALUE_FIELDS
        if field in diff
    )
    reference = {k: v for k, v in diff.items() if k not in _DIFF_VALUE_FIELDS}
    reference["spanned"] = True
    reference["bytes"] = size
    if span_threshold is not None and encoded_size(json.dumps(reference)) > (
        span_threshold
    ):
        raise ValueError("list diff reference is itself over the span threshold")
    return reference


def spanned_reference(
    diff: dict[str, Any], config: Any, spanned_bytes: int
) -> dict[str, Any]:
    """``diff`` as a reference regardless of its size: for a diff whose
    value is a spanned item the caller did not read (its handle carries
    only the size). ``spanned_bytes`` is that item's encoded size."""
    span_threshold = getattr(config, "list_item_span_threshold", None)
    threshold = (
        span_threshold
        if isinstance(span_threshold, int) and not isinstance(span_threshold, bool)
        else None
    )
    return _as_reference(diff, threshold, extra_bytes=spanned_bytes)


class ListPropertyIterator:
    """
    Lazy-loading iterator for ListProperty.

    Loads list items on-demand to minimize database queries and memory usage.
    """

    def __init__(self, list_prop: "ListProperty") -> None:
        self.list_prop = list_prop
        self.current_index = 0

    def __iter__(self) -> "ListPropertyIterator":
        return self

    def __next__(self) -> Any:
        if self.current_index >= len(self.list_prop):
            raise StopIteration

        item = self.list_prop[self.current_index]
        self.current_index += 1
        return item


def _accept_limit(value: Any) -> int | None:
    """A positive ``int``, else ``None``: a test's ``Mock()`` config (whose
    attributes are ``Mock`` objects) therefore sets no limit."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


class PropertyListStorage:
    """``ListStorage`` over an actor's property rows: the main partition is
    the actor id, the side partition ``{actor_id}$aux``.

    Takes a fresh ``get_property(config)`` per operation, as the list code
    always has (a reused handle conflicts), from this module's global so a
    test that patches ``actingweb.property_list.get_property`` reaches every
    row the list touches."""

    noun = "property"
    remedy = "Run verify() and compact() on it."

    def __init__(self, actor_id: str, config: Any) -> None:
        self._actor_id = actor_id
        self.config = config

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def span_threshold(self) -> int | None:
        return _accept_limit(getattr(self.config, "list_item_span_threshold", None))

    @property
    def item_max_bytes(self) -> int | None:
        return _accept_limit(getattr(self.config, "list_item_max_bytes", None))

    @property
    def key_scope(self) -> str:
        return self._actor_id

    @property
    def location(self) -> str:
        return f"actor {self._actor_id}"

    def side_key(self) -> str:
        return aux_partition(self._actor_id)

    def side_available(self) -> bool:
        return "$" not in self._actor_id

    def _partition(self, side: bool) -> str:
        return aux_partition(self._actor_id) if side else self._actor_id

    def scalar_exists(self, name: str) -> bool:
        return (
            get_property(self.config).get(actor_id=self._actor_id, name=name)
            is not None
        )

    def get(self, name: str, *, side: bool = False) -> str | None:
        return get_property(self.config).get(actor_id=self._partition(side), name=name)

    def put(self, name: str, value: str, *, side: bool = False) -> bool | None:
        return get_property(self.config).set(
            actor_id=self._partition(side), name=name, value=value
        )

    def remove(self, name: str, *, side: bool = False) -> bool | None:
        return get_property(self.config).set(
            actor_id=self._partition(side), name=name, value=None
        )

    def get_range(
        self,
        lower: str,
        upper: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, str]:
        return get_property(self.config).get_range(
            actor_id=self._partition(side),
            lower=lower,
            upper=upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_prefix(
        self,
        prefix: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, str]:
        return get_property(self.config).get_prefix(
            actor_id=self._partition(side),
            prefix=prefix,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_last_in_range(
        self, lower: str, upper: str, *, side: bool = False
    ) -> str | None:
        return get_property(self.config).get_last_in_range(
            actor_id=self._partition(side), lower=lower, upper=upper
        )

    def create_if_not_exists(
        self, name: str, value: str, *, side: bool = False
    ) -> bool:
        return get_property(self.config).create_if_not_exists(
            actor_id=self._partition(side), name=name, value=value
        )

    def create_many_if_not_exists(
        self, rows: dict[str, str], *, side: bool = False
    ) -> set[str]:
        return {
            name
            for name, value in rows.items()
            if self.create_if_not_exists(name, value, side=side)
        }

    def set_if_value_equals(
        self, name: str, expected: str, value: str, *, side: bool = False
    ) -> bool:
        return get_property(self.config).set_if_value_equals(
            actor_id=self._partition(side), name=name, expected=expected, value=value
        )

    def delete_if_value_equals(
        self, name: str, value: str, *, side: bool = False
    ) -> bool:
        return get_property(self.config).delete_if_value_equals(
            actor_id=self._partition(side), name=name, value=value
        )

    def batch_delete(self, names: list[str], *, side: bool = False) -> None:
        get_property(self.config).batch_delete(
            actor_id=self._partition(side), names=names
        )


class ListProperty(ListCore):
    """
    Distributed list storage implementation for ActingWeb properties.

    Metadata lives at ``list:{name}-meta``; its ``format`` field selects
    the item-row storage layout (dispatched throughout this class via
    ``_is_v2()``):

    - format 1 (absent/1, "v1"): items at ``list:{name}-{index}``, dense
      integers 0..length-1, authoritative ``length`` in metadata. Every
      list created before Phase 4 shipped.
    - format 2 ("v2"): items at ``list:{name}-#{rank}``, fractional
      ("rank") keys that sort into item order -- length is always counted
      from the rank-key range, never stored. Every NEW list as of Phase 4.

    Metadata writes go through ``_save_metadata()``, which names the fields
    it changes and merges them into a fresh read -- never a cached dict.
    See that method for why.

    KNOWN RESIDUAL (v1 only): ``append()`` and ``insert()`` derive the new
    ``length`` from ``len(self)``, which reads the metadata cache rather
    than storage. An instance an application retains across a concurrent
    mutation can therefore still write a stale ABSOLUTE length -- the
    write side is bounded (nothing else about the row is reverted), the
    read side is not. Quiesce writes during an operator rewrite, as the
    migration and repair docs already advise; a fix that makes ``length``
    relative is tracked in
    ``thoughts/todo/whole-list-rewrite-atomicity.md``.

    v2's ``get_metadata()["length"]`` is served from ``count_hint``, an
    ADVISORY count metadata mutations maintain as a side effect -- see
    ``_v2_touch_metadata()``. **The drift bound is a documented contract,
    not an implementation detail**: at any moment,
    ``|count_hint - len(list_prop)|`` is at most the number of mutations
    currently in flight against the list, plus -- during a rolling
    deploy only -- mutations applied by pre-3.14 writers since the last
    rank-counting 3.14 mutation (``_save_metadata()`` preserves fields it
    doesn't recognise, so an old writer carries the hint forward without
    maintaining it), plus one per mutation whose advisory metadata touch
    failed (tolerated CAS exhaustion, or a backend fault after the item
    write) since the last rank-counting mutation. Drift never accumulates
    beyond those three terms, and it self-corrects: the next
    rank-counting mutation (``insert()``/``pop()``/``remove()``/
    ``__delitem__()``/``compact()``, all of which hold a freshly-read
    rank map when they touch metadata) overwrites the hint with the
    counted truth. ``len(list_prop)`` always counts the rank-key range and
    is always exact; only ``get_metadata()["length"]`` is advisory. A quota
    check that must never over-admit should trust the hint while strictly
    below its limit and confirm with ``len()`` once it reaches the limit --
    the exact read is then paid only at the boundary, not on every save.

    SPANNED ITEMS (v2, 4.0). An item whose encoded size is over
    ``list_item_span_threshold`` is stored as a head row holding an envelope
    (``property_list_span``) plus body rows in the actor's side partition
    (``{actor_id}$aux``), which no dump or range read of the actor's
    partition returns. Cost rule: every resolving read pays one paged body
    read per spanned item (``resolve=False``/``item_at()`` defer it); a
    write pays its body rows plus the head, a spanned-to-spanned update
    about twice that, and a lost CAS wastes the new generation; enumerating
    ``$span-`` rows costs every body byte on DynamoDB, so only ``delete()``
    and the opt-in ``verify(spans=True)``/``compact(sweep_span_orphans=True)``
    do it. Deleting or rewriting a spanned item deletes its old generation
    best-effort after the head write committed.

    A v2 item mutator (``append``/``extend``/``insert``/``__setitem__``/
    ``__delitem__``/``pop``/``remove``/``delete_by_handle``/
    ``update_by_handle``/``remove_where``/``update_where``) that RETURNS
    has committed its item write -- the metadata touch that follows it can
    neither fail that mutation nor be the reason it raised (see
    ``ListMetadataContentionError`` and ``_v2_touch_metadata()``).
    """

    def __init__(self, actor_id: str, name: str, config: Any) -> None:
        super().__init__(PropertyListStorage(actor_id, config), name)
        self.config = config
        self._db = get_property(self.config) if self.config else None

    # -- the core's hooks, for the property formats ------------------------

    def _on_stored_format(self, meta: dict[str, Any] | None) -> NoReturn:
        fmt = (meta or {}).get("format", 1)
        raise ValueError(
            f"List '{self.name}' stores format {fmt!r}, which this "
            f"operation does not handle."
        )

    def _not_v2_error(self, operation: str, *, hint: bool = True) -> Exception:
        tail = " Call migrate_to_v2() first." if hint else ""
        return ValueError(
            f"{operation}() is v2-only -- list '{self.name}' is still v1.{tail}"
        )

    def _foreign_rows(self, *, sweep: bool) -> int:
        if sweep:
            return self.sweep_foreign_format_rows()
        return len(self._v1_item_names_in_range())

    def _before_mutation(self) -> None:
        self._maybe_lazy_migrate()

    def _default_metadata_no_db(self) -> dict[str, Any]:
        return self._create_default_metadata()

    def _merge_length_delta(
        self,
        meta: dict[str, Any],
        call_updates: dict[str, Any],
        length_delta: int,
        stored_format: int,
    ) -> None:
        if length_delta and stored_format == 1 and "length" not in call_updates:
            current_length = meta.get("length")
            if isinstance(current_length, int):
                meta["length"] = max(0, current_length + length_delta)

    def storage_format(self) -> int:
        """Which storage format this list uses: 1 (dense integers) or 2
        (fractional rank keys). One point read of the metadata row."""
        return self._format()

    # -- v1 and the dual-format public methods -----------------------------

    def _get_item_property_name(self, index: int) -> str:
        """Get the property name for a list item at given index (v1 only)."""
        return f"list:{self.name}-{index}"

    def _create_default_metadata(self) -> dict[str, Any]:
        """Create default metadata structure."""
        now = datetime.now().isoformat()
        return {
            "length": 0,
            "created_at": now,
            "updated_at": now,
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "",
            "explanation": "",
            "format_ever_changed": False,
        }

    def sizes_from_rows(self, rows: dict[str, Any]) -> list[int]:
        """Each item's encoded size, in list order, from a dump -- no body
        read: a spanned head carries its ``bytes``, a plain item's size is
        its raw value's. For the metadata GET, which reports sizes only.

        v1 falls back to ``to_list_from_rows()`` (no spanned items exist on
        v1)."""
        if not self._is_v2():
            return [
                encoded_size(json.dumps(item)) for item in self.to_list_from_rows(rows)
            ]
        return super().sizes_from_rows(rows)

    def to_list_from_rows(
        self, rows: dict[str, Any], *, resolve: bool = True
    ) -> list[Any]:
        """Like to_list(), but served from a pre-fetched name->value mapping.

        v1: falls back to a per-item database read (via __getitem__) for
        any row missing from the mapping. Item decoding matches
        __getitem__: JSON with a raw-string fallback.

        v2: the heads come from `rows` (no fallback reads -- there is no
        separate "recorded length" a v2 list could disagree with). A dump
        never holds a spanned item's body rows (they live in the actor's
        side partition), so each spanned item costs one paged body read,
        eventually consistent first, matching the dump. With
        ``resolve=False`` no body is read and a spanned item's slot holds
        ``UNRESOLVED``.

        Raises:
            ListCorruptionError: v1 only -- a row is missing from BOTH the
                mapping and storage.
            ListItemSpanError: v2 -- a spanned item's bodies are broken.
        """
        if self._is_v2():
            return super().to_list_from_rows(rows, resolve=resolve)

        length = len(self)
        result: list[Any] = []
        for i in range(length):
            item_str = rows.get(self._get_item_property_name(i))
            if item_str is None:
                # Not in the pre-fetched partition dump -- fall back to a
                # per-item read. __getitem__ raises ListCorruptionError if
                # the row is genuinely missing, not merely absent from
                # `rows`.
                result.append(self[i])
                continue
            try:
                result.append(json.loads(item_str))
            except (json.JSONDecodeError, TypeError):
                result.append(item_str)
        return result

    def get_metadata(self) -> dict[str, Any]:
        """
        Get list metadata as a read-only dictionary.

        Returns metadata including created_at, updated_at, version, item_type,
        chunk_size, and length. For description and explanation, use the
        dedicated get_description() and get_explanation() methods.

        Returns:
            Dictionary with metadata fields:
            - created_at: ISO timestamp when list was created
            - updated_at: ISO timestamp of last modification
            - version: Metadata schema version
            - item_type: Type of items stored (currently always "json")
            - chunk_size: A legacy field, always ``1``
            - length: Number of items in the list. **v1: exact. v2:
              ADVISORY** -- served from `count_hint`, a value mutations
              maintain as a side effect rather than count() every time.
              Drift is bounded (see the class docstring / property-lists
              guide) and self-correcting: it never resolves which rows
              exist, only how many. `to_list()`, `__getitem__` and
              iteration always return the true items regardless of what
              this says. Call `len(list_prop)` for an exact count -- it
              always counts the rank-key range, at the cost of the
              whole-list range query this field exists to avoid.

        Note: This returns a copy; modifications won't affect the stored metadata.
        Use set_description() and set_explanation() to update user-facing fields.
        """
        meta = self._load_metadata()
        if self._is_v2():
            hint = meta.get("count_hint")
            # A v2 list whose metadata predates this release has no hint
            # yet -- count once (the first rank-counting mutation then
            # establishes one) rather than silently reporting 0.
            length = hint if isinstance(hint, int) else len(self)
        else:
            length = meta.get("length", 0)
        return {
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
            "version": meta.get("version", ""),
            "item_type": meta.get("item_type", ""),
            "chunk_size": meta.get("chunk_size", 1),
            "length": length,
        }

    def __len__(self) -> int:
        """Get list length. v1: from metadata (no item loading). v2:
        counted from the (cached) rank-key range."""
        if self._is_v2():
            return len(self._v2_ensure_rank_cache())
        meta = self._load_metadata()
        length = meta.get("length", 0)
        return int(length) if length is not None else 0

    def __getitem__(self, index: int) -> Any:
        """Get item by index, loading from database.

        Raises:
            IndexError: ``index`` is outside ``[0, len(self))``.
            ListCorruptionError: v1 only -- ``index`` is in range but the
                row is missing from storage. Under v2 this can only happen
                transiently under concurrent mutation, and is resolved by
                one cache reload (see ``_v2_getitem``) rather than raised.
        """
        if self._is_v2():
            return self._v2_getitem(index)

        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self._db:
            raise RuntimeError("No database connection available")

        item_property_name = self._get_item_property_name(index)
        # Use fresh DB instance to avoid handle conflicts
        item_db = get_property(self.config)
        item_str = item_db.get(actor_id=self.actor_id, name=item_property_name)

        if item_str is None:
            raise ListCorruptionError(self.name, index)

        try:
            return json.loads(item_str)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse list item at index {index}: {e}")
            return item_str  # Return raw string if JSON parsing fails

    def __setitem__(self, index: int, value: Any) -> None:
        """Set item at index."""
        self._maybe_lazy_migrate()
        if self._dispatch_and_stash() == 2:
            self._v2_setitem(index, value)
            return

        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self._db:
            raise RuntimeError("No database connection available")

        value_str = self._encode_item(value)
        self._check_item_size(value_str)

        # Use fresh DB instance to avoid handle conflicts
        item_db = get_property(self.config)
        if not item_db.set(
            actor_id=self.actor_id,
            name=self._get_item_property_name(index),
            value=value_str,
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")

        # Update metadata timestamp
        self._save_metadata({}, create_if_absent=False)

    def __delitem__(self, index: int) -> None:
        """Delete item at index and shift remaining items."""
        self._maybe_lazy_migrate()
        if self._dispatch_and_stash() == 2:
            self._v2_delitem(index)
            return

        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self._db:
            raise RuntimeError("No database connection available")

        # Delete the item at index
        prop = get_property(self.config)
        if not prop.set(
            actor_id=self.actor_id,
            name=self._get_item_property_name(index),
            value=None,  # This will delete the property
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")

        # Shift all items after index down by one
        for i in range(index + 1, length):
            # Use fresh DB instance to avoid handle conflicts
            item_db = get_property(self.config)
            item_value = item_db.get(
                actor_id=self.actor_id, name=self._get_item_property_name(i)
            )

            if item_value is not None:
                # Move item from position i to position i-1
                move_db = get_property(self.config)
                if not move_db.set(
                    actor_id=self.actor_id,
                    name=self._get_item_property_name(i - 1),
                    value=item_value,
                ):
                    raise RuntimeError(
                        f"list item write failed for '{self.name}'[{i - 1}]"
                    )

                # Delete the old position
                delete_db = get_property(self.config)
                if not delete_db.set(
                    actor_id=self.actor_id,
                    name=self._get_item_property_name(i),
                    value=None,
                ):
                    raise RuntimeError(f"list item write failed for '{self.name}'[{i}]")

        # Update metadata length
        self._save_metadata({"length": length - 1}, create_if_absent=False)

    def __iter__(self) -> "ListPropertyIterator | Iterator[Any]":
        """Return an iterator over the list.

        v1: lazy, per-item loading (ListPropertyIterator). v2: one full
        range query up front (_v2_to_list()), then a plain list iterator --
        per-item __getitem__ calls in a loop would cost one query per item,
        which the range-read design exists specifically to avoid.
        """
        if self._is_v2():
            return iter(self._v2_to_list())
        return ListPropertyIterator(self)

    def append(self, item: Any) -> None:
        """Add item to end of list."""
        self.append_indexed(item, _locate=False)

    def append_indexed(self, item: Any, *, _locate: bool = True) -> int | None:
        """Add ``item`` to the end of the list and return the index it landed
        at, or None when it was written but its index could not be read
        (4.0; see :meth:`ListCore.append_indexed`). A v1 list writes at the
        index it read as the length, so two concurrent appends to a v1 list
        can both report (and write) the same index, as ``append()`` always
        could on v1."""
        if not self._db:
            raise RuntimeError("No database connection available")

        self._maybe_lazy_migrate()
        if self._dispatch_and_stash() == 2:
            rank = self._v2_append(item)
            return self._v2_index_of_rank(rank) if _locate else -1

        item_str = self._encode_item(item)
        self._check_item_size(item_str)

        length = len(self)

        # Store the new item - use fresh DB instance to avoid handle conflicts
        item_property_name = self._get_item_property_name(length)
        item_db = get_property(self.config)
        if not item_db.set(
            actor_id=self.actor_id, name=item_property_name, value=item_str
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{length}]")
        logger.debug(
            f"append(): Stored item at '{item_property_name}' with value: {item_str}"
        )

        # Update metadata with a DELTA under the compare-and-swap, not an
        # absolute `length + 1` computed from the cache -- `length` above
        # (used for the item's storage POSITION) is still cache-derived,
        # which is the KNOWN RESIDUAL the class docstring documents and
        # this does not fix. What this closes is the metadata VALUE: a
        # length_delta merges onto whatever count is freshly read under
        # the CAS, so a retained instance's stale `length` no longer
        # overwrites a concurrent writer's more-current one.
        self._save_metadata({}, length_delta=1, create_if_absent=False)
        return length

    def extend(self, items: list[Any]) -> None:
        """Add multiple items to end of list.

        v2: one last-rank read for the whole batch (see ``_v2_extend()``),
        not one per item. v1: unchanged, a loop over ``append()`` --
        Phase 9B does not touch the v1 path.
        """
        if not items:
            return

        self._maybe_lazy_migrate()
        if self._dispatch_and_stash() == 2:
            self._v2_extend(items)
            return

        # Size-check the whole batch first, as the v2 path does, so an
        # oversized item anywhere in it writes nothing.
        for item in items:
            self._check_item_size(self._encode_item(item))
        for item in items:
            self.append(item)

    def _v1_bounds(self) -> tuple[str, str]:
        """Inclusive [lower, upper] bounds for get_range() covering exactly
        this list's v1 item rows.

        v1 rows are ``list:{name}-{index}``, so the range runs from
        ``-0`` to ``-:`` (0x3A, the byte just past ``9``). That excludes
        the meta row (``m``, 0x6D) above and every v2 row (``#``, 0x23)
        below.

        It does NOT exclude a SIBLING list whose name begins with a digit:
        a list called ``foo-5`` stores ``list:foo-5-0``, which sorts inside
        list ``foo``'s bounds. Only the ``^\\d+$`` shape check on the
        suffix keeps the two apart -- the v1 counterpart of the hazard
        ``_v2_item_names_in_range()`` documents.
        """
        return (f"list:{self.name}-0", f"list:{self.name}-:")

    def _v1_item_names_in_range(self) -> list[str]:
        """This list's OWN v1 item row names, via one keys-only range read.

        Deliberately a ``get_range()`` and not a
        ``fetch_all_including_lists()`` partition dump: the bulk migration
        script avoids those precisely because they cost roughly one dump
        per list on a typical actor.
        """
        lower, upper = self._v1_bounds()
        db = get_property(self.config)
        rows = db.get_range(
            actor_id=self.actor_id, lower=lower, upper=upper, keys_only=True
        )
        return self._names_matching(
            rows, len(f"list:{self.name}-"), lambda s: bool(_V1_INDEX_RE.match(s))
        )

    def sweep_foreign_format_rows(self) -> int:
        """Delete this list's item rows belonging to the storage format it
        is NOT currently in, and return how many were removed.

        Both format-changing rewrites write the new format's rows, flip
        metadata, then delete the old format's rows -- and both early-return
        before reaching that last step when re-run, because by then the
        list already reads as the target format. So an interrupted rewrite
        leaves the old rows behind PERMANENTLY: re-running does not finish
        the job, it declines to start it. This is the cleanup those early
        returns call before returning.

        Cross-format residue is normally inert (each format's readers
        ignore the other's row shape), which is why it survived unnoticed.
        It stops being inert when the list is deleted and a new list is
        created under the same name: ``exists()`` and ``list_all()`` key
        off the meta row, so the residue is invisible until the moment a
        fresh list adopts it as its own items.

        The format is read from storage, never from the cache. A stale
        cache here would classify the LIVE rows as foreign and delete the
        list. When there is no meta row at all -- the list is gone, and
        both namespaces are residue by definition -- both are swept.

        Skips its range query (Phase 12: thoughts/plans/2026-08-20-v2-
        positional-access-cost.md) when the list's own metadata carries
        ``format_ever_changed: False`` -- set on every freshly created
        list, and the ONLY way residue can exist in the other namespace is
        a format-changing rewrite (``migrate_to_v2()``/the downgrade
        script), both of which set the flag ``True`` in the SAME metadata
        write as the format flip. A list that has never crossed formats
        therefore cannot have residue to find, and on an all-v2 fleet this
        is the common case: the range query this skips would always come
        back empty. Metadata that predates this flag (absent key) cannot
        rule anything out and always gets the full sweep -- same as every
        list did before this optimisation existed.
        """
        stored, _ = self._read_meta_row()
        if stored is not None and stored.get("format_ever_changed") is False:
            return 0
        aux_names: list[str] = []
        if stored is None:
            names = self._v1_item_names_in_range() + self._v2_item_names_in_range()
            # The list is gone: its side-partition rows are residue too.
            aux_names = self._aux_names("span") + self._aux_names("key")
        elif int(stored.get("format", 1) or 1) == 2:
            names = self._v1_item_names_in_range()
        else:
            names = self._v2_item_names_in_range()
            # A v1 list has no spanned or keyed items: any side-partition
            # row under its name is residue of an interrupted downgrade.
            aux_names = self._aux_names("span") + self._aux_names("key")

        if names:
            db = get_property(self.config)
            db.batch_delete(actor_id=self.actor_id, names=names)
        aux = self._aux_or_none()
        if aux_names and aux is not None:
            get_property(self.config).batch_delete(actor_id=aux, names=aux_names)
        swept = len(names) + len(aux_names)
        if swept:
            logger.info(
                f"List '{self.name}' (actor {self.actor_id}): swept "
                f"{swept} row(s) left by an interrupted format change"
            )
        return swept

    def clear(self) -> None:
        """Remove all items from list."""
        if not self._db:
            raise RuntimeError("No database connection available")

        # Dispatch on the STORED format, not a cached one. Both branches end
        # in a wholesale metadata write, so a stale v1 cache over migrated
        # storage would put `_create_default_metadata()` -- format 1, length
        # 0 -- over a live v2 list's meta row while its rows stay put. That
        # is the same format revert _save_metadata() exists to prevent,
        # arriving through the replace path instead of the merge path.
        self._invalidate_cache()

        # An emptied list must be empty in BOTH namespaces. The branches
        # below only clear the format the list currently reports, so
        # residue from an interrupted rewrite would survive a clear() and
        # then be adopted as items by whichever format the list next
        # changes to.
        self.sweep_foreign_format_rows()

        if self._is_v2():
            self._v2_clear()
            return

        length = len(self)

        # Delete all item properties -- one batched operation (Phase 12:
        # thoughts/plans/2026-08-20-v2-positional-access-cost.md) instead
        # of `length` serial round trips.
        item_names = [self._get_item_property_name(i) for i in range(length)]
        if item_names:
            get_property(self.config).batch_delete(
                actor_id=self.actor_id, names=item_names
            )

        # Reset metadata
        self._replace_metadata(self._create_default_metadata())

    def delete(self) -> None:
        """Delete the entire list including metadata."""
        if not self._db:
            raise RuntimeError("No database connection available")

        # Dispatch on the stored format -- see clear(). A stale cache here
        # picks the wrong item namespace to delete from, leaving the real
        # rows behind after the meta row is gone: invisible to exists() and
        # list_all(), and resurrected inside the next list created under
        # this name.
        self._invalidate_cache()

        # Sweep the other namespace BEFORE the meta row goes: cross-format
        # residue left by an interrupted rewrite outlives the list
        # otherwise, invisible to exists()/list_all() (which key off the
        # meta row) right up until a new list is created under this name
        # and reads it as its own items.
        self.sweep_foreign_format_rows()

        if self._is_v2():
            self._v2_delete()
            return

        length = len(self)

        # Delete all item properties -- one batched operation instead of
        # `length` serial round trips (Phase 12).
        item_names = [self._get_item_property_name(i) for i in range(length)]
        if item_names:
            get_property(self.config).batch_delete(
                actor_id=self.actor_id, names=item_names
            )

        # Delete metadata
        meta_db = get_property(self.config)
        if not meta_db.set(
            actor_id=self.actor_id, name=self._get_meta_property_name(), value=None
        ):
            raise RuntimeError(f"list metadata write failed for '{self.name}'")

        # Clear cache
        self._meta_cache = None

    def to_list(self, consistent: bool = True) -> list[Any]:
        """Load entire list into memory.

        v2: exactly one range query, regardless of length.

        Args:
            consistent: v2 only, ignored under v1 (which never issues a
                range read here). ``False`` halves DynamoDB read capacity
                (see ``get_range``'s ``consistent_read`` docstring) at the
                cost of possibly not seeing a just-landed write, including
                this instance's own. No default change -- whether a stale
                read is acceptable is an application decision.

        Raises:
            ListCorruptionError: v1 only -- a row within ``[0, len(self))``
                is missing from storage. Run ``compact()`` (or the caller's
                remedy) to repair, then retry. Not possible under v2 --
                there is no separate "recorded length" a v2 list's rows
                could disagree with.
        """
        if self._is_v2():
            return self._v2_to_list(consistent=consistent)

        length = len(self)
        result = []

        for i in range(length):
            result.append(self[i])

        return result

    def slice(self, start: int, end: int, consistent: bool = True) -> list[Any]:
        """Load a range of items efficiently.

        v2: exactly one range query (the full list), sliced in memory --
        still one query, not one per requested item.

        Args:
            consistent: see ``to_list()``.

        Raises:
            ListCorruptionError: v1 only -- a row within the requested
                range is missing from storage.
        """
        if self._is_v2():
            return super().slice(start, end, consistent)

        length = len(self)

        # Handle negative indices
        if start < 0:
            start = max(0, length + start)
        if end < 0:
            end = max(0, length + end)

        # Clamp to valid range
        start = max(0, min(start, length))
        end = max(start, min(end, length))

        result = []
        for i in range(start, end):
            result.append(self[i])

        return result

    def pop(self, index: int = -1) -> Any:
        """Remove and return item at index (default last)."""
        # v2 dispatch comes FIRST, and via a FRESH read (_dispatch_and_stash(),
        # not the cache -- row 9c): `len(self)` below is served from the
        # rank cache, which an instance that has seen an empty list keeps
        # until something forces a reload, and checking it before dispatch
        # would raise "pop from empty list" against a list another writer
        # has since appended to. _v2_pop() forces its own refresh and makes
        # its own empty check against that.
        #
        # Deliberately NOT calling _maybe_lazy_migrate() here: migration
        # closes holes in flight, so triggering it from pop() would make a
        # corrupted v1 list silently self-repair instead of raising, which
        # is the Phase 2/3 contract. The v1 branch below reaches
        # __delitem__, which triggers migration exactly as it always has.
        if self._dispatch_and_stash() == 2:
            return self._v2_pop(index)

        if len(self) == 0:
            raise IndexError("pop from empty list")

        if index == -1:
            index = len(self) - 1

        item = self[index]
        del self[index]
        return item

    def insert(self, index: int, item: Any) -> None:
        """Insert item at given index."""
        if not self._db:
            raise RuntimeError("No database connection available")

        self._maybe_lazy_migrate()
        if self._dispatch_and_stash() == 2:
            self._v2_insert(index, item)
            return

        length = len(self)

        if index < 0:
            index = max(0, length + index)
        if index > length:
            index = length

        item_str = self._encode_item(item)
        self._check_item_size(item_str)

        # Shift all items from index onwards up by one. Fresh DB instance
        # per call (like every other mutation method) — reusing self._db
        # across get()/set() calls for different item names left a stale
        # handle that, on DynamoDB, overwrote every shifted row with the
        # last-read value instead of its own.
        for i in range(length - 1, index - 1, -1):
            item_db = get_property(self.config)
            item_value = item_db.get(
                actor_id=self.actor_id, name=self._get_item_property_name(i)
            )

            if item_value is not None:
                move_db = get_property(self.config)
                if not move_db.set(
                    actor_id=self.actor_id,
                    name=self._get_item_property_name(i + 1),
                    value=item_value,
                ):
                    raise RuntimeError(
                        f"list item write failed for '{self.name}'[{i + 1}]"
                    )

        # Insert the new item
        insert_db = get_property(self.config)
        if not insert_db.set(
            actor_id=self.actor_id,
            name=self._get_item_property_name(index),
            value=item_str,
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")

        # DELTA under the compare-and-swap, not an absolute `length + 1`
        # computed from the cache -- see append()'s identical comment.
        self._save_metadata({}, length_delta=1, create_if_absent=False)

    def remove(self, value: Any) -> None:
        """Remove first occurrence of value."""
        # No _maybe_lazy_migrate() here, for the same reason pop() omits it:
        # migration closes holes in flight, so triggering it before the v1
        # scan would make a corrupted list silently self-repair instead of
        # raising. The v1 scan below reaches __delitem__, which migrates
        # exactly as it always has.
        if self._dispatch_and_stash() == 2:
            self._v2_remove(value)
            return

        for i, item in enumerate(self):
            if item == value:
                del self[i]
                return
        raise ValueError(f"{value} not in list")

    def index(self, value: Any, start: int = 0, stop: int | None = None) -> int:
        """Return index of first occurrence of value.

        ``start``/``stop`` follow ``list.index`` semantics, including
        negative values counting from the end.
        """
        if self._is_v2():
            return super().index(value, start, stop)

        length = len(self)
        begin, end = self._normalize_search_bounds(start, stop, length)

        for i in range(begin, end):
            if self[i] == value:
                return i

        raise ValueError(f"{value} is not in list")

    def count(self, value: Any) -> int:
        """Return number of occurrences of value."""
        if self._is_v2():
            return super().count(value)
        count = 0
        for item in self:
            if item == value:
                count += 1
        return count

    def remove_where(
        self, identity_key: str, value: Any, *, first_only: bool = False
    ) -> list[Any]:
        """Remove every item whose ``identity_key`` field equals ``value``,
        returning the removed items' decoded values, in removal order.
        ``len(result)`` is the count; pass ``first_only=True`` to stop
        after the first match (0 or 1 removed).

        Returning the actual values (not just a count) lets a caller that
        needs to know exactly what was removed -- notably
        ``NotifyingListProperty.remove_where()``, which raises one diff
        per removed item -- read it off this call instead of taking a
        separate snapshot and assuming a prefix of it lines up with the
        count. That prefix assumption breaks under a concurrent mutation
        between the two reads; this return value can't drift, because it
        names exactly the rows this call itself removed.

        Universal across v1 and v2, dispatched fresh (``_dispatch_and_stash()``,
        not the cached format belief -- same row-9c rationale as every
        other mutator):

        - v2: locates matches via ``_v2_items_with_handles()`` (one range
          read, already known-v2 from the dispatch above -- see that
          method's docstring for why this isn't the public
          ``items_with_handles()``), then deletes each with
          ``delete_by_handle()``. A match lost to a concurrent mutation
          between the read and its delete is simply not counted -- no
          retry, no rescan; see ``delete_by_handle()``.
        - v1: locates matches by positional scan, then deletes them via
          ``__delitem__`` in **descending index order**. Ascending order
          would shift every later match onto the wrong index as each
          earlier delete closes a hole.
        """
        if self._dispatch_and_stash() == 2:
            return self._v2_remove_where(identity_key, value, first_only=first_only)

        # Capture the values during the SAME scan that finds the indices
        # -- a second `self[i]` read here could return a different value
        # than the one that matched (and gets deleted) if a concurrent
        # writer lands between the two reads, which is exactly the drift
        # class this method's return value exists to preclude.
        matched = [
            (i, item)
            for i, item in enumerate(self)
            if isinstance(item, dict)
            and identity_key in item
            and item[identity_key] == value
        ]
        if first_only and matched:
            matched = matched[:1]
        for i, _ in sorted(matched, reverse=True):
            del self[i]
        return [item for _, item in matched]

    def update_where(
        self, identity_key: str, value: Any, item: Any, *, first_only: bool = False
    ) -> list[Any]:
        """Replace every item whose ``identity_key`` field equals ``value``
        with ``item``, returning the **pre-update** values of the items
        actually updated, in update order. ``len(result)`` is the count;
        pass ``first_only=True`` to stop after the first match.

        Same rationale as ``remove_where()`` for returning values instead
        of a count -- ``NotifyingListProperty.update_where()`` needs the
        exact pre-update value of each row it updated to raise an accurate
        ``old_item`` diff, not a value assumed from a separately-taken
        snapshot.

        Same v1/v2 split as ``remove_where()``, using ``update_by_handle()``
        under v2 and positional ``self[i] = item`` under v1 -- index order
        does not matter here, unlike ``remove_where()``: an update never
        shifts a later index the way a delete does.
        """
        if self._dispatch_and_stash() == 2:
            return self._v2_update_where(
                identity_key, value, item, first_only=first_only
            )

        # Same capture-during-scan rationale as remove_where()'s v1 branch:
        # the returned pre-update values must be the ones the match saw,
        # not whatever a second positional read happens to find.
        matched = [
            (i, existing)
            for i, existing in enumerate(self)
            if isinstance(existing, dict)
            and identity_key in existing
            and existing[identity_key] == value
        ]
        if first_only and matched:
            matched = matched[:1]
        for i, _ in matched:
            self[i] = item
        return [existing for _, existing in matched]

    def verify(
        self, identity_key: str | None = None, spans: bool = False
    ) -> dict[str, Any]:
        """Read-only integrity check against stored rows.

        v2: see ``_v2_verify()`` -- a structurally different report shape
        (no ``stored_length``/``missing_indices``/``orphan_indices``; those
        concepts don't exist when position IS the row's identity).

        v1 (below): fetches the actor's full property partition once and
        compares the metadata's ``length`` against which ``list:{name}-N``
        rows actually exist, in the range ``[0, length)``. Reports index
        numbers only -- never item values.

        Args:
            identity_key: Optional field name that identifies an item
                within your data (``"id"``, ``"uuid"``, ...). Strongly
                recommended if your items have one -- see the duplicate
                detection note below. On v2 this resolves every spanned
                item (one paged body read each).
            spans: v2 only. Also enumerate the list's body rows in the side
                partition and report ``span_body_rows``,
                ``orphan_span_gens`` and ``broken_spans``. Costs every body
                byte on DynamoDB, which is why it is opt-in.

        Returns:
            Dict with:
            - stored_length: the metadata's recorded length
            - readable_count: how many of ``[0, stored_length)`` are present
            - missing_indices: indices in ``[0, stored_length)`` with no row
              (holes)
            - orphan_indices: rows present at or past ``stored_length``
            - adjacent_duplicates: list of ``(a, b)`` readable-index pairs
              where ``b == a + 1`` and both rows hold byte-identical stored
              content -- see below
            - foreign_format_rows: how many v2-shaped rows share this
              list's name -- residue from an interrupted format change.
              Informational, NOT part of ``healthy``: they are inert to
              every v1 reader, and ``sweep_foreign_format_rows()`` removes
              them without operator involvement. Reported so an operator
              looking at a list can see that a rewrite was interrupted
            - duplicate_identities: ``None`` when no ``identity_key`` was
              supplied (the check did not run), otherwise
              ``{identity: [positions]}`` for every identity appearing more
              than once ANYWHERE in the list -- ``{}`` meaning checked and
              clean. Always present, and distinguishable from "not checked",
              because ``verify()``'s report shape already varies by storage
              format and a second silently-optional key would be one sharp
              edge too many for callers that index it directly
            - identity_checked_count: ``None`` when no ``identity_key`` was
              supplied, otherwise how many rows actually carried that field.
              **Check this before trusting an empty ``duplicate_identities``.**
              Rows without the field are excluded from the comparison, so a
              mistyped key produces a clean-looking report that compared
              nothing at all
            - healthy: True iff there are no holes, no orphans, no
              adjacent-duplicate hits, and no repeated identities

        **The two duplicate checks answer different questions, and each is
        blind to what the other catches.**

        ``adjacent_duplicates`` compares raw stored bytes of neighbouring
        rows. That is exactly the residue an interrupted delete/insert
        shift leaves -- always adjacent, always byte-identical by
        construction. Its false negative: the moment either copy is edited
        the bytes diverge and the signal vanishes, silently, for precisely
        the lists that have been used since the damage. A real deployment
        hit this -- a duplicated item edited afterwards reported
        ``adjacent_duplicates: []`` with both copies still present.

        ``duplicate_identities`` compares the ``identity_key`` field across
        the WHOLE list. It survives later edits, and it does not assume the
        copies stayed neighbours -- a real deployment had the same ``id``
        at positions 31 and 36, which any adjacency-bounded check reports
        as healthy. Duplicates arising from a different mechanism (a failed
        read turning an upsert into an append, say) are under no obligation
        to be adjacent at all.

        Pass ``identity_key`` whenever your items have an identifying
        field. It remains a heuristic in the other direction: a list that
        legitimately holds two items with the same identity will be
        reported.
        """
        if self._is_v2():
            return self._v2_verify(identity_key=identity_key, spans=spans)

        meta = self._load_metadata()
        stored_length = int(meta.get("length", 0) or 0)

        # Scoped to this list's own v1 item rows instead of dumping the
        # whole partition -- _v2_verify() already reads this way, through
        # _v2_load_full(); this is the v1 path catching up. See
        # migrate_to_v2() for why _v1_bounds() rather than a name prefix, why
        # consistent_read=True, and why the trailing "or {}" is gone.
        #
        # The report is unchanged: orphan_indices is drawn from `present`,
        # already filtered by ^list:{name}-(\d+)$, so no orphan shape exists
        # outside these bounds, and stored_length comes from _load_metadata()
        # rather than from rows.
        lower, upper = self._v1_bounds()
        rows = get_property(self.config).get_range(
            actor_id=self.actor_id,
            lower=lower,
            upper=upper,
            consistent_read=True,
        )

        pattern = re.compile(rf"^list:{re.escape(self.name)}-(\d+)\Z")
        present: set[int] = set()
        for key in rows:
            m = pattern.match(key)
            if m:
                present.add(int(m.group(1)))

        missing_indices = [i for i in range(stored_length) if i not in present]
        orphan_indices = sorted(i for i in present if i >= stored_length)
        readable_count = stored_length - len(missing_indices)

        ordered_present = [i for i in range(stored_length) if i in present]
        adjacent_duplicates: list[tuple[int, int]] = []
        for a, b in zip(ordered_present, ordered_present[1:], strict=False):
            if b != a + 1:
                continue
            va = rows.get(self._get_item_property_name(a))
            vb = rows.get(self._get_item_property_name(b))
            if va is not None and va == vb:
                adjacent_duplicates.append((a, b))

        duplicate_identities: dict[Any, list[int]] | None = None
        identity_checked_count: int | None = None
        if identity_key is not None:
            duplicate_identities, identity_checked_count = self._identity_duplicates(
                [
                    (i, self._identity_of(raw, identity_key))
                    for i in ordered_present
                    if (raw := rows.get(self._get_item_property_name(i))) is not None
                ]
            )

        # Cross-format residue. This USED to be counted out of the
        # whole-partition dump that `rows` came from; the scoped read above
        # cannot see it, because v2 rows sort at `#` (0x23), BELOW
        # _v1_bounds()' lower bound `list:{name}-0` (0x30). So it costs one
        # extra keys-only range read -- the exact mirror of what _v2_verify()
        # already spends on `len(self._v1_item_names_in_range())`, and still a
        # rounding error against the dump the pair of them replaced.
        # Side-partition rows under a v1 list's name are residue too (a v1
        # list never spans or keys an item): two keys-only prefix reads of
        # a partition that is normally empty.
        foreign_format_rows = (
            len(self._v2_item_names_in_range())
            + len(self._aux_names("span"))
            + len(self._aux_names("key"))
        )

        report: dict[str, Any] = {
            "stored_length": stored_length,
            "readable_count": readable_count,
            "missing_indices": missing_indices,
            "orphan_indices": orphan_indices,
            "adjacent_duplicates": adjacent_duplicates,
            "foreign_format_rows": foreign_format_rows,
            "healthy": not missing_indices
            and not orphan_indices
            and not adjacent_duplicates,
        }
        report["duplicate_identities"] = duplicate_identities
        report["identity_checked_count"] = identity_checked_count
        if duplicate_identities:
            report["healthy"] = False
        return report

    def compact(
        self, allow_reverted: bool = False, sweep_span_orphans: bool = False
    ) -> dict[str, Any]:
        """Repair holes and orphans by rewriting the list densely.

        v2: rebalances rank keys -- see ``_v2_compact()``.

        v1 (below): reads every row in ``[0, stored_length)`` that is
        actually present, in order, and rewrites them at ``0..n-1``;
        deletes every row from the new length through the highest index
        the list had (closing holes and removing orphans in one pass).
        ``description``, ``explanation`` and ``created_at`` are preserved
        -- unlike ``clear()`` + ``extend()``, which resets them via
        ``_create_default_metadata()``.

        Adjacent-duplicate residue (see ``verify()``) is left INTACT and
        reported, never rewritten: a duplicate always means a destroyed
        item, and silently collapsing one copy would bless the data loss
        as intentional rather than surface it.

        NOT CRASH-SAFE (v1, same shape as ``_v2_compact()``). Survivors are
        rewritten at their new positions BEFORE the tail rows are deleted,
        so an interruption between the two leaves a copy at both the old
        and the new position. Measured on a 4-slot list with one hole,
        interrupting at successive writes:

        - after the first move: rows ``[a, c, c, d]``, length still 4
        - after the second:     rows ``[a, c, d, d]``, length still 4

        Both are readable with **no error** -- length matches the rows
        present, so nothing looks wrong to a caller. ``verify()`` does
        catch them, via the adjacent byte-identical heuristic, so a
        follow-up sweep reports the list unhealthy.

        The sharp part: re-running ``compact()`` does NOT clean this up.
        Duplicates are preserved by design (above), so the repair tool
        will not remove the copy its own interruption created, and the
        list stays one item too long until someone resolves it by hand.
        Prefer running repair when the actor is not taking writes, and
        re-run ``verify()`` afterwards rather than assuming success.

        REFUSES A REVERTED MIGRATION. A v1 list that is damaged **and**
        has ``foreign_format_rows > 0`` is not an ordinary hole: it is a
        list whose migration to v2 was reverted, and its items are
        probably alive in the v2 rows. Compacting it would rewrite the
        (empty) v1 range, set the length to what it found, report the
        list **healthy**, and strand the only surviving copy as residue
        for the next ``clear()``/``delete()``/migrate re-run to sweep.
        That is the same unreportable loss ``migrate_to_v2()`` refuses
        damaged lists to avoid, in the other tool -- so this refuses too,
        and ``allow_reverted=True`` is the deliberate override.

        Found by consumer verification against 3.13.0 GA, not by the
        library's own tests: the shape needs a migration that got
        reverted, which no unit test built.

        Args:
            sweep_span_orphans: v2 only -- see ``_v2_compact()``. Remove
                aged orphan body generations and heads whose bodies are
                missing, after one enumeration of the list's body rows.
            allow_reverted: compact a v1 list that has rows of the other
                storage format, accepting that the items in them stop
                being reachable and stop being reported. Off by default.
                Recover first -- re-running ``migrate_to_v2()`` on the
                pre-revert metadata, or reading the v2 rows out by hand --
                and the question does not arise.

                Note this is one step removed from deletion rather than
                deletion itself, which is what makes it sharper than it
                looks: the v2 rows survive this call. What it removes is
                the *report* that they matter -- the list goes from loudly
                unhealthy to healthy -- so the next
                ``clear()``/``delete()``/migrate re-run sweeps them with
                nothing left to say they were the data.

        Returns:
            The ``verify()`` report this call acted on (taken before any
            write). On a refusal, that report plus ``compacted: False``
            and ``reason``.
        """
        if self._is_v2():
            return self._v2_compact(sweep_span_orphans=sweep_span_orphans)

        report = self.verify()

        damaged = bool(report["missing_indices"] or report["orphan_indices"])
        if damaged and report["foreign_format_rows"] and not allow_reverted:
            logger.error(
                "Refusing to compact list '%s' for actor %s: it is damaged AND "
                "carries %d row(s) of the v2 storage format. That combination "
                "means a migration was reverted, not that the list has an "
                "ordinary hole -- the items are probably intact in the v2 rows, "
                "and compacting would report this list healthy while stranding "
                "them. Recover the v2 rows first. Pass allow_reverted=True "
                "(--repair-reverted) only after deciding to abandon them.",
                self.name,
                self.actor_id,
                report["foreign_format_rows"],
            )
            return {**report, "compacted": False, "reason": "reverted_migration"}

        if not self._db:
            raise RuntimeError("No database connection available")

        stored_length = report["stored_length"]

        # Scoped, strongly-consistent, and no "or {}" -- see the identical
        # read in migrate_to_v2() for the full argument. compact() is the
        # sharpest case for all three: it writes survivors to 0..n-1 and then
        # deletes len(ordered_values)..highest_seen, so a read that under-
        # reports leaves the list shorter than it was, and a read FAULT used
        # to compute ordered_values = [], delete rows 0..stored_length-1 and
        # write length: 0. get_range() raises DbError instead.
        lower, upper = self._v1_bounds()
        rows = get_property(self.config).get_range(
            actor_id=self.actor_id,
            lower=lower,
            upper=upper,
            consistent_read=True,
        )

        ordered_values: list[str] = [
            rows[self._get_item_property_name(i)]
            for i in range(stored_length)
            if self._get_item_property_name(i) in rows
        ]

        for new_index, raw_value in enumerate(ordered_values):
            target_name = self._get_item_property_name(new_index)
            if rows.get(target_name) == raw_value:
                continue  # already correct -- skip the write
            item_db = get_property(self.config)
            if not item_db.set(
                actor_id=self.actor_id, name=target_name, value=raw_value
            ):
                raise RuntimeError(
                    f"list item write failed for '{self.name}'[{new_index}]"
                )

        highest_seen = max([stored_length - 1, *report["orphan_indices"]], default=-1)
        for i in range(len(ordered_values), highest_seen + 1):
            del_db = get_property(self.config)
            if not del_db.set(
                actor_id=self.actor_id, name=self._get_item_property_name(i), value=None
            ):
                raise RuntimeError(f"list item write failed for '{self.name}'[{i}]")

        self._save_metadata({"length": len(ordered_values)}, create_if_absent=False)

        return report

    def migrate_to_v2(self, allow_damaged: bool = False) -> dict[str, Any]:
        """Migrate this list from v1 (dense integers) to v2 (fractional
        rank keys) storage, in place.

        Idempotent and safe to re-run after a crash at any point, and safe
        to re-run even if the v1 list was mutated between attempts:

        1. Refuse (log an operator-actionable error, list keeps serving
           v1) if the name contains ``#``, or if metadata is unparsable
           (``verify()`` -> ``_load_metadata()`` raises ``ValueError``,
           which propagates -- Phase 2's existing fail-fast behavior).
        2. ``verify()`` the v1 list, and refuse a list with holes or
           orphans unless ``allow_damaged=True`` (see below). Duplicate
           residue migrates as both copies, as-is, and is reported.
        3. Clear any v2-range rows a PREVIOUS interrupted attempt left
           behind. This is what makes re-running safe even if the v1 list
           changed length in between: each attempt starts from a clean
           slate and regenerates a fresh, complete rank set from
           whatever the v1 list looks like right now, rather than trying
           to reconcile with a previous attempt's possibly-different rank
           count.
        4. Generate ``len(items)`` evenly distributed v2 ranks and write
           them (plain puts -- convergent on re-run because step 3 always
           clears first).
        5. Flip metadata to format 2 (drop ``length``) via a freshly read
           meta dict, so ``description``/``explanation``/``created_at``
           survive untouched.
        6. Delete the v1 item rows (idempotent -- a re-run just finds them
           already gone).

        A crash before step 5 leaves v1 fully authoritative: v1 reads and
        writes are completely unaffected (the half-written v2 rows are
        inert scratch space nothing reads), and the next attempt's step 3
        cleans them up before writing fresh ones. A crash after step 5
        leaves v2 authoritative with leftover v1 rows -- v2 readers ignore
        v1-shaped rows, and a re-run finishes the cleanup via
        ``sweep_foreign_format_rows()`` on the ``already_v2`` path.

        That last part used to be a false claim in this docstring. Step 6
        being idempotent does not help when nothing reaches it: the re-run
        sees format 2, returns at the top, and the v1 rows stay forever.
        The sweep is what makes the sentence true.

        Args:
            allow_damaged: migrate a list that ``verify()`` reports holes
                or orphans in, accepting that migration CLOSES them --
                the surviving rows are renumbered and the missing ones
                stop being missing. The lost item stays lost, but nothing
                reports it any more: the migrated list verifies healthy
                and there is no record left of what index went absent.
                That is the right trade for an operator who has looked at
                the damage and decided to move on, and the wrong one as a
                default, so it is off by default and this method refuses
                instead. Repair first (``compact()``, or
                ``actingweb-verify-property-lists --repair``) and the
                question does not arise.

                Only holes and orphans gate on this. Duplicate residue
                migrates freely, because it stays visible afterwards --
                ``_v2_verify()`` reports duplicates the same way
                ``verify()`` does, so migrating it destroys no evidence.
                ``_maybe_lazy_migrate()`` is deliberately stricter and
                skips any unhealthy list, duplicates included: it runs
                inside a user's write with nobody reading its output, so
                it declines anything it cannot handle silently.

        Returns:
            Dict with ``migrated`` (bool) and either ``reason`` (str, only
            when not migrated) or ``item_count``/``had_holes``/
            ``duplicate_count`` (when migrated). A ``"damaged"`` reason
            also carries ``missing_indices`` and ``orphan_indices``.
            ``"deleted_concurrently"`` means the list was deleted mid-run
            and this attempt rolled its own writes back -- not a refusal,
            and nothing for an operator to act on.
        """
        if _V2_RANK_MARKER in self.name:
            logger.error(
                f"List '{self.name}' cannot be migrated to v2: name "
                f"contains '{_V2_RANK_MARKER}', which is reserved for "
                f"internal storage keys -- rename the list before "
                f"migrating; it keeps working as v1 in the meantime"
            )
            return {"migrated": False, "reason": "name_contains_hash"}

        # Never decide "this list is v1" from a cached metadata dict. If
        # another instance (or process) migrated this list after we cached
        # its metadata, a stale read would send us down the v1 path: the v1
        # rows are gone, so verify() reports every index as a hole,
        # ordered_values comes back empty, and step 3 would delete the
        # now-authoritative v2 rows before writing an empty list over the
        # top -- silent, total data loss. Re-read from storage first.
        self._invalidate_cache()
        if self._is_v2():
            # Already v2 -- but that is also exactly what a migration
            # interrupted between steps 5 and 6 looks like, so finish its
            # cleanup instead of walking away from it. Without this, a
            # crash after the metadata flip leaves the v1 rows in place
            # forever: every re-run returns here and never reaches step 6.
            self.sweep_foreign_format_rows()
            return {"migrated": False, "reason": "already_v2"}

        report = self.verify()

        # Refuse a damaged list. Migration renumbers survivors, so a hole
        # does not survive it -- and neither does the evidence: the
        # migrated list verifies healthy, and the report naming what was
        # closed is this method's return value, which a bulk sweep over
        # hundreds of lists reduces to one line in a log. An operator who
        # repairs first gets to see the damage; one who migrates first
        # never finds out it was there.
        missing = report["missing_indices"]
        orphans = report["orphan_indices"]
        if (missing or orphans) and not allow_damaged:
            logger.error(
                f"List '{self.name}' not migrated to v2: verify() reports "
                f"missing_indices={missing} orphan_indices={orphans}. "
                f"Migration closes holes in flight, so the damage would "
                f"stop being reportable -- repair it first (compact(), or "
                f"actingweb-verify-property-lists --repair), or pass "
                f"allow_damaged=True to migrate and accept the loss. The "
                f"list keeps working as v1 in the meantime"
            )
            return {
                "migrated": False,
                "reason": "damaged",
                "missing_indices": missing,
                "orphan_indices": orphans,
            }

        if not self._db:
            raise RuntimeError("No database connection available")

        stored_length = report["stored_length"]

        # One scoped read of this list's own v1 item rows, not a
        # whole-partition dump: fetch_all_including_lists() costs roughly one
        # dump per list on a typical actor, which is why
        # _v1_item_names_in_range() has never used it.
        #
        # _v1_bounds(), not a f"list:{name}" prefix -- the prefix would also
        # match sibling lists sharing the name as a prefix (list "output"
        # matching list:output_embeddings_*), which on a measured account is
        # 403 rows and 678 RCU. The bounds span list:{name}-0 .. list:{name}-:
        # and exclude both the -meta row and every v2 row.
        #
        # consistent_read=True, unlike the eventual public bulk path
        # (PropertyListStore.list_prefix_with_rows()): this read is the input
        # to a destructive rewrite. migrate_to_v2() deletes v1 rows
        # 0..highest_seen below, so a row missed by a stale replica read has
        # its slot deleted silently. Once the read is scoped to one list,
        # strong consistency costs ~6-13 RCU more -- about 1% of what the
        # scoping just saved. property_list.py's v2 twins already state this
        # rule; this makes v1 agree.
        #
        # No "or {}": get_range() raises DbError on a backend fault, where
        # fetch_all_including_lists() returned None on PostgreSQL and the
        # trailing "or {}" turned a transient read fault into "every index is
        # missing" -- and then into a destructive rewrite from nothing.
        lower, upper = self._v1_bounds()
        rows = get_property(self.config).get_range(
            actor_id=self.actor_id,
            lower=lower,
            upper=upper,
            consistent_read=True,
        )

        ordered_values: list[str] = [
            rows[self._get_item_property_name(i)]
            for i in range(stored_length)
            if self._get_item_property_name(i) in rows
        ]

        # Step 4 copies raw v1 values into v2 heads. A pre-4.0 dict item
        # whose first key is the reserved envelope marker would then read
        # as an envelope. Refuse before writing anything, the way
        # downgrade_to_v1 refuses a list holding envelopes.
        if any(looks_like_envelope(raw) for raw in ordered_values):
            logger.error(
                f"List '{self.name}' (actor {self.actor_id}) not migrated to "
                f"v2: an item is a dict whose first key is the reserved "
                f"envelope marker '__aw_env', which a v2 reader would take "
                f"for the library's storage envelope. Rename that key in the "
                f"item first; the list keeps working as v1 in the meantime"
            )
            return {"migrated": False, "reason": "envelope-shaped item"}

        # Re-check the stored format one last time before the first
        # destructive write. The gap between the check above and here spans
        # verify()'s read and the item-row read above -- narrower than it was
        # when both were partition dumps, but still wide enough for a
        # concurrent migration to land in it. Reading the meta row directly
        # (not through the cache, which verify() just repopulated) is what
        # makes this a real second look.
        format_db = get_property(self.config)
        current_meta_str = format_db.get(
            actor_id=self.actor_id, name=self._get_meta_property_name()
        )
        if current_meta_str:
            try:
                current_meta = json.loads(current_meta_str)
            except (json.JSONDecodeError, TypeError):
                current_meta = None
            if isinstance(current_meta, dict) and current_meta.get("format") == 2:
                logger.info(
                    f"List '{self.name}' was migrated to v2 concurrently -- "
                    f"abandoning this attempt without touching its rows"
                )
                self._invalidate_cache()
                self.sweep_foreign_format_rows()
                return {"migrated": False, "reason": "already_v2"}

        # Step 3: clear any v2 scratch rows a previous interrupted attempt
        # left -- guarantees convergence regardless of what happened (or
        # changed) between attempts.
        for leftover_name in self._v2_item_names_in_range():
            del_db = get_property(self.config)
            if not del_db.set(actor_id=self.actor_id, name=leftover_name, value=None):
                raise RuntimeError(
                    f"list item write failed for '{self.name}' during "
                    f"migrate_to_v2() cleanup"
                )
        # Side-partition rows under a v1 list are residue of the same kind.
        self._delete_aux_rows(self._aux_names("span") + self._aux_names("key"))

        # Step 4: write the fresh v2 rows.
        ranks = fi.generate_n_keys_between(None, None, len(ordered_values))
        for rank, raw_value in zip(ranks, ordered_values, strict=True):
            item_db = get_property(self.config)
            if not item_db.set(
                actor_id=self.actor_id,
                name=self._v2_item_name(rank),
                value=raw_value,
            ):
                raise RuntimeError(
                    f"list item write failed for '{self.name}' during migrate_to_v2()"
                )

        # Step 5: flip metadata (fresh read -- preserves description/
        # explanation/created_at untouched).
        #
        # A VANISHED meta row is not a missing default to fill in: it means
        # the list was deleted while we were copying it. Recreating it here
        # would resurrect a deleted list, in v2 form, out of rows we wrote
        # ourselves. Undo step 4 and leave -- delete() has already removed
        # everything else, and the v2 rows are invisible to exists() and
        # list_all() (which key off the meta row) but WOULD be read as items
        # by the next list created under this name.
        stored_meta, _ = self._read_meta_row()
        if stored_meta is None:
            logger.warning(
                f"List '{self.name}' (actor {self.actor_id}) was deleted "
                f"while migrating to v2 -- abandoning the migration and "
                f"removing the {len(ranks)} v2 row(s) written so far"
            )
            # Delete CONDITIONALLY on the exact bytes we wrote, never by rank
            # name alone. Between the read above and this loop, the delete()
            # that removed the meta row can also have swept these rows, a new
            # list can have been created under the same name, and its first
            # append() lands on rank "a0" -- which is the first rank WE
            # generated, because generate_n_keys_between(None, None, n) is
            # deterministic. An unconditional delete by name would then
            # destroy the successor's item and leave its metadata intact:
            # exactly the silent cross-list loss this method exists to
            # prevent, committed by the rollback rather than the migration.
            for rank, raw_value in zip(ranks, ordered_values, strict=True):
                del_db = get_property(self.config)
                if not del_db.delete_if_value_equals(
                    actor_id=self.actor_id,
                    name=self._v2_item_name(rank),
                    value=raw_value,
                ):
                    # Already gone (the concurrent delete() swept it), or now
                    # holds somebody else's value. Either way it is not ours
                    # to remove, and that is a normal outcome here, not a
                    # failure.
                    logger.info(
                        f"List '{self.name}' (actor {self.actor_id}): rollback "
                        f"left row '{self._v2_item_name(rank)}' alone -- it is "
                        f"gone or no longer holds the value this migration "
                        f"wrote"
                    )
            self._invalidate_cache()
            return {"migrated": False, "reason": "deleted_concurrently"}

        meta = dict(stored_meta)
        meta.pop("length", None)
        meta["format"] = 2
        # Phase 12 (thoughts/plans/2026-08-20-v2-positional-access-cost.md):
        # this list has now crossed formats, so sweep_foreign_format_rows()
        # can no longer skip its range query on the strength of this
        # metadata -- an interrupted step 6 below would leave v1 residue a
        # skipped sweep would never find.
        meta["format_ever_changed"] = True
        self._replace_metadata(meta)
        self._v2_rank_cache = list(ranks)

        # Step 6: delete the v1 item rows (holes + orphans included).
        highest_seen = max([stored_length - 1, *report["orphan_indices"]], default=-1)
        for i in range(highest_seen + 1):
            del_db = get_property(self.config)
            if not del_db.set(
                actor_id=self.actor_id, name=self._get_item_property_name(i), value=None
            ):
                raise RuntimeError(
                    f"list item write failed for '{self.name}' during "
                    f"migrate_to_v2() v1 cleanup"
                )

        return {
            "migrated": True,
            "item_count": len(ordered_values),
            "had_holes": bool(report["missing_indices"]),
            "duplicate_count": len(report["adjacent_duplicates"]),
        }

    def _maybe_lazy_migrate(self) -> None:
        """Opportunistically migrate a small v1 list to v2 at the top of a
        mutation method.

        Best-effort: a failure here is logged and swallowed -- the
        original v1 mutation proceeds unaffected, because migration is a
        background upgrade, not a functional requirement for
        append()/insert()/etc to succeed. Only ever called from mutation
        methods, never from read paths (reads run under read-only
        permission -- handlers/properties.py, www.py).

        Larger v1 lists are left alone (see
        ``_V2_LAZY_MIGRATION_MAX_LENGTH``, overridable per deployment); they
        stay fully functional via the hardened v1 paths until
        ``scripts/migrate_property_lists.py`` runs. Set the limit to 0 to
        disable lazy migration entirely and migrate only via the script --
        migration is inline and synchronous, so an operator who does not
        want it happening inside user requests can opt out.

        UNHEALTHY LISTS ARE NEVER MIGRATED HERE. ``migrate_to_v2()`` closes
        holes in flight and reports what it closed, which is right for an
        operator running the script and reading its output -- but doing it
        silently under an ordinary ``append()`` destroys the evidence: the
        hole disappears, the item that was lost stays lost, duplicate
        residue is carried over as real data, ``verify()`` starts reporting
        ``healthy: true``, and the report naming what happened is discarded
        by this method's own return value. Repairing damaged data is an
        operator decision, so a damaged list keeps serving v1 (and keeps
        raising ``ListCorruptionError`` on the rows it has lost) until
        somebody runs ``compact()`` or the sweep script.

        NEVER call this from a method that must surface v1 corruption before
        it mutates. Migration closes holes in flight, so an eager call turns
        a `ListCorruptionError` (the Phase 1-3 fail-fast contract, and the
        409 an operator sees) into a silent self-repair. ``pop()`` and
        ``remove()`` both deliberately omit it and let their v1 path reach
        ``__delitem__``, which triggers migration after the scan. This
        mistake has been made twice; if you are adding a v2 dispatch to a
        method that reads before it writes, this paragraph is why the call
        you are about to copy from ``append()`` does not belong there.
        """
        if self._is_v2():
            return
        if _lazy_migration_max_length() <= 0:
            # A v1 list exists and nothing here will convert it -- say so
            # once, so "off by default" doesn't become "nobody ever knows".
            _nudge_lazy_migration_disabled()
            return
        meta = self._load_metadata()
        length = int(meta.get("length", 0) or 0)
        if length > _lazy_migration_max_length():
            return
        try:
            report = self.verify()
            if not report.get("healthy", True):
                logger.warning(
                    f"List '{self.name}' (actor {self.actor_id}) is not "
                    f"migrating to v2: it is damaged "
                    f"(missing={report.get('missing_indices')}, "
                    f"orphans={report.get('orphan_indices')}, "
                    f"duplicate_pairs={len(report.get('adjacent_duplicates', []))}). "
                    f"Migrating would close the holes and make the damage "
                    f"unreportable. Run compact() or "
                    f"scripts/verify_property_lists.py --repair first, then "
                    f"scripts/migrate_property_lists.py --migrate"
                )
                return
            self.migrate_to_v2()
        except DbError:
            raise
        except Exception as e:
            logger.warning(
                f"Lazy migration to v2 failed for list '{self.name}': {e} "
                f"-- continuing as v1"
            )
