"""
Attribute lists: the list core over an attribute bucket.

An attribute is the private twin of a property: an application keeps data in
attributes when it must not reach a peer, and the replica of a peer's
``/properties`` lives in attribute buckets for the same reason. So an
attribute list offers the property list's interface: ``ListAttribute`` is
``actingweb.list_core.ListCore`` over ``AttributeListStorage`` (rank keys,
handles, spanned items, keyed appends, ``verify()``, ``compact()``), with
the property list's row layout in its bucket: ``list:{name}-meta`` and
``list:{name}-#{rank}``, each value the string the core writes, stored as
the attribute's JSON ``data``. Span bodies and key rows live in the side
bucket ``{bucket}$aux``.

**The old layout.** Before 3.16 an attribute list was ``list:{name}:meta``
(a JSON object with ``length``) and ``list:{name}:{index}`` rows. Such a
list is read in place (one range read, no write) until its first change,
which converts it: item ``i`` is written at the ``i``-th rank of
``generate_n_keys_between(None, None, n)`` with create-if-not-exists (two
converters write identical rows; an interrupted one resumes), then the
``-meta`` row is created carrying a cleanup marker (the create picks the
winner), then the old rows are deleted and the marker removed. A list whose
old rows are damaged (a hole, a wrong ``length``) is not converted:
``ListCorruptionError``. Rows of both layouts without the marker are what a
pre-3.16 writer leaves beside a converted list: neither copy is known to be
right, and every access raises ``ListLayoutConflictError``.
``clear()`` and ``delete()`` remove both layouts, whatever their state.

The core never goes through ``Attributes`` (which caches a bucket per
instance and deletes on falsy data): this storage calls the backend's list
primitives directly, so a string item such as ``"0"`` or ``"[]"`` is stored
like any other.
"""

import json
import logging
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import fractional_indexing as fi

from .list_core import (
    _NO_STASH,
    ListCore,
    ListCorruptionError,
    ListLayoutConflictError,
    _v2_is_rank,
)
from .property_list_span import AUX_SUFFIX, encode_item, parse, value_digest, wrap

logger = logging.getLogger(__name__)

# The -meta field a conversion writes and its cleanup removes: while it is
# there, old-layout rows beside the list are the conversion's residue, not a
# pre-3.16 writer's.
CLEANUP_MARKER = "layout_cleanup"
OLD_LAYOUT = "attribute-v1"
# Old rows the converter creates per batch, checking for a finished
# conversion between batches.
_CONVERT_BATCH = 25
# What a DynamoDB attribute row carries besides its data: the actor id, the
# composite key, the bucket and the name (each at most about 1 KB), the
# attribute names and the timestamp.
_ROW_KEY_OVERHEAD = 4096
# The worst growth of a string when the backend stores it as JSON: a control
# character in the str() fallback becomes "\\u00XX" (six bytes).
_JSON_GROWTH = 6
_OLD_INDEX_RE = re.compile(r"^\d+\Z")


def _accept_limit(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _as_core_value(data: Any) -> str:
    """A row's data as the core reads it: the string it wrote (anything
    else, which the core never writes, as JSON text)."""
    return data if isinstance(data, str) else json.dumps(data, sort_keys=True)


class AttributeListStorage:
    """``ListStorage`` over the attribute backend's list primitives: main
    bucket ``bucket``, side bucket ``{bucket}$aux`` (none for a bucket that
    contains ``$``)."""

    noun = "attribute"

    def __init__(self, actor_id: str, bucket: str, config: Any) -> None:
        self._actor_id = actor_id
        self.bucket = bucket
        self.config = config

    # -- description -----------------------------------------------------

    @property
    def actor_id(self) -> str:
        return self._actor_id

    @property
    def location(self) -> str:
        return f"actor {self._actor_id}, bucket {self.bucket!r}"

    @property
    def remedy(self) -> str:
        return (
            "Run actingweb-verify-property-lists --attributes on it (a "
            "replica of a peer's list is rebuilt from the peer's baseline)."
        )

    @property
    def key_scope(self) -> str:
        return self._actor_id

    def _db(self) -> Any:
        from .db import get_attribute

        return get_attribute(self.config)

    @property
    def span_threshold(self) -> int | None:
        """The configured threshold, lowered so that a row stored as JSON
        always fits the backend's row cap: parts are cut at the threshold
        too, so a body row fits as well."""
        configured = _accept_limit(
            getattr(self.config, "list_item_span_threshold", None)
        )
        backend = getattr(
            getattr(self.config, "DbAttribute", None), "DbAttribute", None
        )
        row_cap = _accept_limit(getattr(backend, "MAX_ROW_BYTES", None))
        if row_cap is None:
            return configured
        fits = (row_cap - _ROW_KEY_OVERHEAD) // _JSON_GROWTH
        return min(configured, fits) if configured is not None else fits

    @property
    def item_max_bytes(self) -> int | None:
        return _accept_limit(getattr(self.config, "list_item_max_bytes", None))

    # -- partitions ----------------------------------------------------------

    def side_key(self) -> str:
        if "$" in self.bucket:
            raise ValueError(
                f"Bucket {self.bucket!r} contains '$', which is reserved for "
                f"the attribute-list side bucket: lists there hold no item "
                f"over the span threshold"
            )
        return self.bucket + AUX_SUFFIX

    def side_available(self) -> bool:
        return "$" not in self.bucket

    def _bucket(self, side: bool) -> str:
        return self.side_key() if side else self.bucket

    # -- reads -----------------------------------------------------------------

    def scalar_exists(self, name: str) -> bool:
        return self.get(name) is not None

    def get(self, name: str, *, side: bool = False) -> str | None:
        row = self._db().get_attr(
            actor_id=self._actor_id, bucket=self._bucket(side), name=name
        )
        if row is None:
            return None
        return _as_core_value(row.get("data"))

    def get_range(
        self,
        lower: str,
        upper: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, str]:
        rows = self._db().get_attr_range(
            self._actor_id,
            self._bucket(side),
            lower,
            upper,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )
        return {k: "" if keys_only else _as_core_value(v) for k, v in rows.items()}

    def get_prefix(
        self,
        prefix: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, str]:
        return {
            k: "" if keys_only else _as_core_value(v)
            for k, v in self.get_prefix_raw(
                prefix, keys_only=keys_only, consistent_read=consistent_read, side=side
            ).items()
        }

    def get_prefix_raw(
        self,
        prefix: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, Any]:
        """``get_prefix`` with each row's stored JSON value as it is (the
        old layout stores items as JSON values, not strings)."""
        return self._db().get_attr_prefix(
            self._actor_id,
            self._bucket(side),
            prefix,
            keys_only=keys_only,
            consistent_read=consistent_read,
        )

    def get_last_in_range(
        self, lower: str, upper: str, *, side: bool = False
    ) -> str | None:
        return self._db().get_last_attr_in_range(
            self._actor_id, self._bucket(side), lower, upper
        )

    # -- writes ----------------------------------------------------------------

    def put(self, name: str, value: str, *, side: bool = False) -> bool | None:
        self._db().put_attr(self._actor_id, self._bucket(side), name, value)
        return True

    def remove(self, name: str, *, side: bool = False) -> bool | None:
        self._db().delete_attrs(self._actor_id, self._bucket(side), [name])
        return True

    def create_if_not_exists(
        self, name: str, value: str, *, side: bool = False
    ) -> bool:
        return bool(
            self._db().create_attr_if_not_exists(
                self._actor_id, self._bucket(side), name, value
            )
        )

    def create_many_if_not_exists(
        self, rows: dict[str, str], *, side: bool = False
    ) -> set[str]:
        if not rows:
            return set()
        return set(
            self._db().create_attrs_if_not_exist(
                self._actor_id, self._bucket(side), rows
            )
        )

    def set_if_value_equals(
        self, name: str, expected: str, value: str, *, side: bool = False
    ) -> bool:
        return bool(
            self._db().set_attr_if_data_equals(
                self._actor_id, self._bucket(side), name, expected, value
            )
        )

    def delete_if_value_equals(
        self, name: str, value: str, *, side: bool = False
    ) -> bool:
        return bool(
            self._db().delete_attr_if_data_equals(
                self._actor_id, self._bucket(side), name, value
            )
        )

    def batch_delete(self, names: list[str], *, side: bool = False) -> None:
        if names:
            self._db().delete_attrs(self._actor_id, self._bucket(side), list(names))


class ListAttribute(ListCore):
    """A list in an attribute bucket, with the property list's interface
    (every public method of ``ListProperty`` but its v1 migration).

    The layout dispatch runs once per instance, on its first access: one
    point read of the ``-meta`` row, handed to the core, and one of the old
    ``:meta`` row unless the ``-meta`` row carries the cleanup marker.
    """

    _RANK_REMEDY = "run compact() to rebalance (a replica is rebuilt instead)"

    def __init__(self, actor_id: str, bucket: str, name: str, config: Any) -> None:
        super().__init__(AttributeListStorage(actor_id, bucket, config), name)
        self.bucket = bucket
        self.config = config
        if not config:
            self._db = None
        # None until the first access settles it; then "v2" or "old".
        self._layout: str | None = None

    @property
    def _attr_storage(self) -> AttributeListStorage:
        storage = self._storage
        assert isinstance(storage, AttributeListStorage)
        return storage

    # -- names ----------------------------------------------------------------

    def _old_meta_name(self) -> str:
        return f"list:{self.name}:meta"

    def _old_prefix(self) -> str:
        return f"list:{self.name}:"

    # -- the old layout ----------------------------------------------------------

    def _old_rows(self) -> tuple[dict[str, Any] | None, dict[int, Any], list[str]]:
        """``(meta, {index: item}, row names)`` of the old layout: one prefix
        read, filtered to this list's own rows (a list named ``x`` never
        reads the rows of a list named ``x:y``)."""
        prefix = self._old_prefix()
        rows = self._attr_storage.get_prefix_raw(prefix)
        meta: dict[str, Any] | None = None
        items: dict[int, Any] = {}
        names: list[str] = []
        for name, data in rows.items():
            suffix = name[len(prefix) :]
            if suffix == "meta":
                meta = data if isinstance(data, dict) else {}
                names.append(name)
            elif _OLD_INDEX_RE.match(suffix):
                items[int(suffix)] = data
                names.append(name)
        return meta, items, names

    def _old_items(self) -> list[Any]:
        """The old layout's items in order, read in place.

        Raises:
            ListCorruptionError: an index below the recorded length has no
                row.
        """
        meta, items, _ = self._old_rows()
        length = int((meta or {}).get("length", 0) or 0)
        for i in range(length):
            if i not in items:
                raise ListCorruptionError(self.name, i)
        return [items[i] for i in range(length)]

    def _old_metadata(self) -> dict[str, Any]:
        meta, _, _ = self._old_rows()
        return dict(meta or {})

    def _old_row_names(self) -> list[str]:
        """The old layout's row names of this list: one keys-only prefix
        read, filtered to this list's own rows."""
        prefix = self._old_prefix()
        rows = self._attr_storage.get_prefix_raw(prefix, keys_only=True)
        return [
            name
            for name in rows
            if (suffix := name[len(prefix) :]) == "meta" or _OLD_INDEX_RE.match(suffix)
        ]

    def _foreign_rows(self, *, sweep: bool) -> int:
        """The old layout's rows of this list: deleted (``clear()``,
        ``delete()``, a conversion's cleanup) or counted (``verify()``)."""
        names = self._old_row_names()
        if sweep and names:
            self._storage.batch_delete(names)
        return len(names)

    # -- the layout dispatch -----------------------------------------------------

    def _settle_layout(
        self, meta: dict[str, Any] | None, *, fresh: bool = False
    ) -> str:
        """Which layout this list is in, given its ``-meta`` row as just
        read: ``"v2"`` (the core's), ``"old"`` (read in place), or
        ``ListLayoutConflictError``. Settled once per instance for reads;
        ``fresh`` (a mutation's dispatch, unless the instance already knows
        the list's ``-meta`` row) settles it again."""
        if self._layout is not None and not fresh:
            return self._layout
        if meta is not None and meta.get(CLEANUP_MARKER):
            self._layout = "v2"
            return self._layout
        old_meta = self._storage.get(self._old_meta_name())
        if meta is not None and old_meta is not None:
            raise ListLayoutConflictError(
                self.name,
                f"rows of both layouts ({self._storage.location}): "
                f"'{self._old_meta_name()}' beside '{self._get_meta_property_name()}' "
                f"without a cleanup marker, as a pre-3.16 writer leaves them. "
                f"{self._storage.remedy}",
            )
        self._layout = "old" if old_meta is not None else "v2"
        return self._layout

    def _load_metadata(self) -> dict[str, Any]:
        if self._meta_cache is not None or not self._db:
            return super()._load_metadata()
        if self._layout is None:
            parsed, _ = self._read_meta_row()
            if self._settle_layout(parsed) == "v2" and parsed is not None:
                self._meta_cache = parsed
                return parsed
        if self._layout == "old":
            # Format absent (1): the core's readers refuse it; the public
            # readers below serve the old layout in place.
            return self._old_metadata()
        return super()._load_metadata()

    def _dispatch_and_stash(self) -> int:
        """A mutation's fresh dispatch, which settles the layout first: an
        unconverted list is converted, a finished conversion's cleanup is
        completed, and only then is the ``-meta`` row stashed for the core."""
        parsed, raw = self._read_meta_row()
        known = (
            parsed is not None
            and not parsed.get(CLEANUP_MARKER)
            and self._layout == "v2"
        )
        layout = self._settle_layout(parsed, fresh=not known)
        changed = False
        if layout == "old":
            self._convert()
            changed = True
        if changed or (parsed is not None and parsed.get(CLEANUP_MARKER)):
            self._finish_cleanup()
            parsed, raw = self._read_meta_row()
        self._pending_meta_read = (parsed, raw)
        if parsed is None:
            return 2
        try:
            return int(parsed.get("format", 1) or 1)
        except (TypeError, ValueError):
            return 1

    # -- conversion --------------------------------------------------------------

    def _convert(self) -> None:
        """Write the old layout's items at deterministic ranks and create the
        ``-meta`` row with the cleanup marker; see the module docstring."""
        meta, items, _ = self._old_rows()
        old = meta or {}
        length = old.get("length", 0)
        # Rows at or above the recorded length are a crashed pre-3.16 append's
        # leftovers (it wrote the row before the length): ignored, as the old
        # readers ignore them, and swept with the old layout.
        if (
            not isinstance(length, int)
            or isinstance(length, bool)
            or not set(range(length)) <= set(items)
        ):
            if self._storage.get(self._get_meta_property_name()) is not None:
                return  # another converter finished and is cleaning up
            missing = sorted(
                set(range(length if isinstance(length, int) else 0)) - set(items)
            )
            raise ListCorruptionError(self.name, missing[0] if missing else len(items))
        ranks = fi.generate_n_keys_between(None, None, length) if length else []
        lower, upper = self._v2_bounds()
        prefix = self._v2_item_prefix()
        # What a previous run (or another converter) already wrote is
        # compared with what this conversion would write; a row the
        # conversion would not have written is a conflict, never adopted.
        # Ranks only: a sibling list named ``<name>-#...`` in the old layout
        # has rows inside this range that are not this list's.
        existing = {
            name[len(prefix) :]: raw
            for name, raw in self._storage.get_range(lower, upper).items()
            if _v2_is_rank(name[len(prefix) :])
        }
        if self._storage.get(self._get_meta_property_name()) is not None:
            # Another converter finished after this one read the old rows:
            # the rows are its (and may have changed since), not a conflict.
            return
        planned = set(ranks)
        stray = sorted(r for r in existing if r not in planned)
        if stray:
            raise ListLayoutConflictError(
                self.name,
                f"rows of the new layout the conversion did not write "
                f"({len(stray)}, first {self._v2_item_name(stray[0])!r}, "
                f"{self._storage.location}). {self._storage.remedy}",
            )
        for i, rank in enumerate(ranks):
            if rank in existing and not self._holds_item(existing[rank], items[i]):
                raise ListLayoutConflictError(
                    self.name,
                    f"the conversion met a row it did not write at "
                    f"{self._v2_item_name(rank)!r} ({self._storage.location}). "
                    f"{self._storage.remedy}",
                )
        for start in range(0, length, _CONVERT_BATCH):
            # Before every batch, the first included: a converter that read
            # the old rows before another finished must not recreate a row
            # deleted since (its rank no longer in ``existing``).
            if self._storage.get(self._get_meta_property_name()) is not None:
                return  # another converter finished; its rows are ours too
            self._create_batch(
                [
                    (ranks[i], items[i])
                    for i in range(start, min(start + _CONVERT_BATCH, length))
                    if ranks[i] not in existing
                ]
            )
        now = datetime.now().isoformat()
        new_meta = self._create_default_metadata_v2()
        for field in ("description", "explanation", "created_at", "updated_at"):
            if old.get(field) is not None:
                new_meta[field] = old[field]
        new_meta["created_at"] = new_meta.get("created_at") or now
        new_meta["count_hint"] = length
        new_meta[CLEANUP_MARKER] = OLD_LAYOUT
        self._storage.create_if_not_exists(
            self._get_meta_property_name(), json.dumps(new_meta)
        )
        self._invalidate_cache()
        logger.info(
            "Attribute list '%s' (%s): converted %d item(s) from the old layout",
            self.name,
            self._storage.location,
            length,
        )

    def _create_batch(self, batch: list[tuple[str, Any]]) -> None:
        heads: dict[str, str] = {}
        spans: dict[str, Any] = {}
        for rank, item in batch:
            try:
                value_str, carries_marker = encode_item(item), False
            except ValueError:
                # A pre-3.16 item carrying the reserved envelope key: kept
                # as it is, inside an envelope (a plain row would read as
                # one).
                value_str, carries_marker = json.dumps(item), True
            span = (
                self._write_bodies(value_str)
                if self._check_item_size(value_str, can_span=True)
                else None
            )
            name = self._v2_item_name(rank)
            spans[name] = span
            heads[name] = (
                wrap(value=item)
                if carries_marker and span is None
                else self._make_head(value_str, span)
            )
        # Some heads of the batch may land before a fault (a batch create is
        # not atomic on DynamoDB): their bodies stay, and the bodies of heads
        # that did not land are orphans the aged sweep removes.
        created = self._storage.create_many_if_not_exists(heads)
        for name in set(heads) - created:
            self._span_delete_bodies(spans[name])
            stored = self._storage.get(name)
            if stored != heads[name] and not self._same_spanned_item(
                stored, spans[name]
            ):
                raise ListLayoutConflictError(
                    self.name,
                    f"the conversion met a row it did not write at {name!r} "
                    f"({self._storage.location}). {self._storage.remedy}",
                )

    def _holds_item(self, raw: str, item: Any) -> bool:
        """Whether a stored head ``raw`` stands for ``item`` as this
        conversion would write it (a spanned head by its digest)."""
        try:
            value_str = encode_item(item)
            if raw == value_str:
                return True
        except ValueError:
            value_str = json.dumps(item)
            if raw == wrap(value=item):
                return True
        try:
            env = parse(raw)
        except ValueError:
            return False
        if env is None or env.span is None or env.span.sha256 is None:
            return False
        return env.span.sha256 == value_digest(value_str)

    @staticmethod
    def _same_spanned_item(stored: str | None, span: Any) -> bool:
        """Whether a head another converter wrote spans the same value as
        ours: its body generation differs, its digest does not."""
        if stored is None or span is None or span.sha256 is None:
            return False
        try:
            env = parse(stored)
        except ValueError:
            return False
        theirs = env.span if env is not None else None
        return theirs is not None and theirs.sha256 == span.sha256

    def _finish_cleanup(self) -> None:
        """Delete the old layout's rows, then remove the marker."""
        self._foreign_rows(sweep=True)
        self._pending_meta_read = _NO_STASH
        self._save_metadata({}, remove=(CLEANUP_MARKER,), create_if_absent=False)
        self._layout = "v2"

    def convert(self) -> bool:
        """Convert the list now if it is still in the old layout, as its
        first change would; finish a conversion's cleanup if one was
        interrupted. True when the list was in the old layout.

        Raises:
            ListCorruptionError: the old layout is damaged (a hole, a wrong
                ``length``); nothing is written.
            ListLayoutConflictError: rows of both layouts.
        """
        if not self._db:
            raise RuntimeError("No database connection available")
        was_old = self._is_old()
        self._dispatch_and_stash()
        self._pending_meta_read = _NO_STASH
        return was_old

    # -- the public layer: the old layout read in place --------------------------

    def _is_old(self) -> bool:
        if self._layout is None:
            self._load_metadata()
        return self._layout == "old"

    def storage_format(self) -> int | str:
        """``2``, or ``"attribute-v1"`` for a list still in the old layout."""
        if self._db and self._is_old():
            return OLD_LAYOUT
        return super().storage_format()

    def __len__(self) -> int:
        if self._db and self._is_old():
            return int(self._old_metadata().get("length", 0) or 0)
        return super().__len__()

    def __getitem__(self, index: int) -> Any:
        if self._db and self._is_old():
            items = self._old_items()
            if not -len(items) <= index < len(items):
                raise IndexError(
                    f"List index {index} out of range (length: {len(items)})"
                )
            return items[index]
        return super().__getitem__(index)

    def __iter__(self) -> Iterator[Any]:
        if self._db and self._is_old():
            return iter(self._old_items())
        return super().__iter__()

    def to_list(self, consistent: bool = True) -> list[Any]:
        if self._db and self._is_old():
            return self._old_items()
        return super().to_list(consistent=consistent)

    def slice(self, start: int, end: int, consistent: bool = True) -> list[Any]:
        if self._db and self._is_old():
            values = self._old_items()
            length = len(values)
            if start < 0:
                start = max(0, length + start)
            if end < 0:
                end = max(0, length + end)
            start = max(0, min(start, length))
            end = max(start, min(end, length))
            return values[start:end]
        return super().slice(start, end, consistent=consistent)

    def index(self, value: Any, start: int = 0, stop: int | None = None) -> int:
        if self._db and self._is_old():
            values = self._old_items()
            begin, end = self._normalize_search_bounds(start, stop, len(values))
            for i in range(begin, end):
                if values[i] == value:
                    return i
            raise ValueError(f"{value} is not in list")
        return super().index(value, start, stop)

    def count(self, value: Any) -> int:
        if self._db and self._is_old():
            return sum(1 for item in self._old_items() if item == value)
        return super().count(value)

    def find(
        self, identity_key: str, value: Any, consistent: bool = True
    ) -> Any | None:
        if self._db and self._is_old():
            for item in self._old_items():
                if isinstance(item, dict) and item.get(identity_key) == value:
                    return item
            return None
        return super().find(identity_key, value, consistent=consistent)

    def find_all(
        self, identity_key: str, value: Any, consistent: bool = True
    ) -> list[Any]:
        if self._db and self._is_old():
            return [
                item
                for item in self._old_items()
                if isinstance(item, dict) and item.get(identity_key) == value
            ]
        return super().find_all(identity_key, value, consistent=consistent)

    def get_metadata(self) -> dict[str, Any]:
        if self._db and self._is_old():
            meta = self._old_metadata()
            return {
                "created_at": meta.get("created_at", ""),
                "updated_at": meta.get("updated_at", ""),
                "version": meta.get("version", ""),
                "item_type": meta.get("item_type", ""),
                "chunk_size": meta.get("chunk_size", 1),
                "length": int(meta.get("length", 0) or 0),
            }
        return super().get_metadata()

    def prime_from_rows(self, rows: dict[str, Any]) -> None:
        """As the core's, with the layout settled from the rows: rows of both
        layouts raise ``ListLayoutConflictError``; a list in the old layout
        is not primed (its readers read it in place)."""
        new_meta = rows.get(self._get_meta_property_name())
        if self._old_meta_name() in rows:
            marked = False
            if new_meta is not None:
                try:
                    marked = bool(json.loads(new_meta).get(CLEANUP_MARKER))
                except (ValueError, TypeError, AttributeError):
                    marked = False
                if not marked:
                    # The instance keeps no layout: a later call settles it
                    # from storage (and raises the conflict there again).
                    self._layout = None
                    raise ListLayoutConflictError(self.name, "rows of both layouts")
            if new_meta is None:
                self._layout = "old"
                return
        if new_meta is not None:
            self._layout = "v2"
        super().prime_from_rows(rows)

    def compact(
        self, allow_reverted: bool = False, sweep_span_orphans: bool = False
    ) -> dict[str, Any]:
        """As the core's, converting a list still in the old layout first."""
        if self._db and self._is_old():
            self.convert()
        return super().compact(
            allow_reverted=allow_reverted, sweep_span_orphans=sweep_span_orphans
        )

    def repair_keys(self) -> dict[str, Any]:
        """As the core's, converting a list still in the old layout first."""
        if self._db and self._is_old():
            self.convert()
        return super().repair_keys()

    # -- metadata writes convert first -------------------------------------------

    def set_description(self, description: str) -> None:
        if self._db:
            self._dispatch_and_stash()
        super().set_description(description)

    def set_explanation(self, explanation: str) -> None:
        if self._db:
            self._dispatch_and_stash()
        super().set_explanation(explanation)

    # -- clear and delete: both layouts, whatever their state --------------------

    def clear(self) -> None:
        """Remove every item, of both layouts (a damaged or conflicting list
        included), leaving an empty list in the core's layout."""
        if not self._db:
            raise RuntimeError("No database connection available")
        # The core's clear() sweeps the old layout through _foreign_rows().
        self._layout = "v2"
        super().clear()

    def delete(self) -> None:
        """Delete the list, of both layouts, with its side-bucket rows. Any
        stored name can be deleted (names are validated on creation only)."""
        if not self._db:
            raise RuntimeError("No database connection available")
        self._invalidate_cache()
        self._foreign_rows(sweep=True)
        self._v2_delete()
        self._layout = None


def is_list_row_name(name: str) -> bool:
    """Whether an attribute name is a list row of either layout (or a side
    row), so a scalar enumeration skips it."""
    return name.startswith("list:")


__all__ = [
    "CLEANUP_MARKER",
    "OLD_LAYOUT",
    "AttributeListStorage",
    "ListAttribute",
    "is_list_row_name",
]
