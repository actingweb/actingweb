"""
ListProperty implementation for ActingWeb distributed list storage.

This module provides a list interface that stores list items as individual
properties in DynamoDB, bypassing the 400KB limit while maintaining API compatibility.
"""

import json
import logging
import os
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import fractional_indexing as fi

from actingweb.db import get_property, get_property_list

logger = logging.getLogger(__name__)

# v2 storage format (fractional rank keys) -- see "Phase 4" of
# thoughts/plans/2026-08-08-property-list-index-integrity.md.
#
# Item rows are named "list:{name}-#{rank}" where {rank} is a
# fractional-indexing key (base62: '0'-'9','A'-'Z','a'-'z', ASCII 0x30-0x7A).
# The '#' marker (0x23) is what isolates a list's v2 rows from everything
# else sharing the "list:{name}-" prefix:
#   - v1 item rows "list:{name}-N" start with a digit (0x30-0x39) > '$'
#   - the meta row "list:{name}-meta" starts with 'm' (0x6D) > '$'
#   - a SIBLING list "list:{name}-x-#..." starts with 'x' (or any non-'#'
#     char) > '#', so it's excluded by the '<= upper' bound
# This is also why new list names may never contain '#': a list literally
# named "{name}-#suffix" would put its own v2 rows inside {name}'s range.
#
# That name ban only binds NEW lists, though. A list created before Phase 4
# and legitimately named e.g. "foo-#bar" keeps working as v1 indefinitely
# (migration refuses '#' names), and its rows -- "list:foo-#bar-0",
# "list:foo-#bar-meta" -- DO fall inside v2 list "foo"'s byte range. The
# range bounds alone therefore do not isolate a v2 list; every consumer of
# a range read must additionally check that the part after the '#' marker
# is a well-formed rank key via _v2_is_rank(). Rank keys are pure base62,
# and every v1 row name ends in "-{digits}" or "-meta", so the '-' in a
# legacy sibling's suffix is what gives it away.
_V2_RANK_MARKER = "#"
_V2_RANK_MAX_LEN = 180
# Rank keys this long or longer mean compact() should rebalance them before
# insert()/append() start failing at the cap.
_V2_RANK_WARNING_LENGTH = 140
_V2_MAX_RANK_RETRIES = 8
_V2_LAZY_MIGRATION_MAX_LENGTH = 0
_V2_RANK_ALPHABET = frozenset(fi.BASE_62_DIGITS)
# Shape filter for a v1 item row's suffix. The v1 byte range alone is not
# enough to isolate a list's rows -- a sibling list whose NAME starts with a
# digit ("foo-5") stores "list:foo-5-0", which sorts inside list "foo"'s
# range. The suffix "5-0" fails this pattern; a genuine "list:foo-7" row's
# suffix "7" passes. Same role _v2_is_rank() plays for the v2 range.
_V1_INDEX_RE = re.compile(r"^\d+$")
_lazy_migration_nudge_logged = False


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


def _v2_is_rank(candidate: str) -> bool:
    """True if ``candidate`` is a well-formed v2 rank key.

    Rank keys generated by ``fractional_indexing`` are non-empty strings
    drawn entirely from its base62 alphabet. Anything else sharing a v2
    list's byte range belongs to a legacy ``#``-named sibling list (whose
    row names always carry a ``-{index}``/``-meta`` suffix, and ``-`` is
    not in the alphabet) and must be filtered out -- see the module
    comment above.
    """
    return bool(candidate) and not (set(candidate) - _V2_RANK_ALPHABET)


class ListCorruptionError(IndexError):
    """A list item within the recorded length is missing from storage.

    Distinct from a genuine out-of-range ``IndexError``: this means the row
    at ``index`` should exist (``0 <= index < length``) but does not -- the
    signature an interrupted delete/insert shift leaves (see
    thoughts/research/2026-08-07-property-list-index-integrity.md). Being an
    ``IndexError`` subclass, existing ``except IndexError`` call sites keep
    working; new code can catch this specifically to offer a repair path.
    The message carries only the list name and index, never item values.
    """

    def __init__(self, list_name: str, index: int) -> None:
        self.list_name = list_name
        self.index = index
        super().__init__(
            f"List '{list_name}' item at index {index} is missing from "
            f"storage (recorded length claims it should exist); run "
            f"compact() to repair"
        )


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


class ListProperty:
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
    """

    def __init__(self, actor_id: str, name: str, config: Any) -> None:
        self.actor_id = actor_id
        self.name = name
        self.config = config
        self._meta_cache: dict[str, Any] | None = None
        self._db = get_property(self.config) if self.config else None
        # v2 only: sorted list of rank-key suffixes (without the
        # "list:{name}-#" prefix), lazily loaded. None means "not loaded
        # yet"; [] is a valid loaded-and-empty state.
        self._v2_rank_cache: list[str] | None = None

    def _get_meta_property_name(self) -> str:
        """Get the metadata property name."""
        return f"list:{self.name}-meta"

    def _get_item_property_name(self, index: int) -> str:
        """Get the property name for a list item at given index (v1 only)."""
        return f"list:{self.name}-{index}"

    def _format(self) -> int:
        """The storage format this list uses: 1 (dense integers, the
        original format) or 2 (fractional rank keys). Absent/unparsable
        `format` in metadata means 1 -- every list created before Phase 4
        shipped."""
        meta = self._load_metadata()
        try:
            return int(meta.get("format", 1) or 1)
        except (TypeError, ValueError):
            return 1

    def _is_v2(self) -> bool:
        return self._format() == 2

    def storage_format(self) -> int:
        """Which storage format this list uses: 1 (dense integers) or 2
        (fractional rank keys).

        One point read of the metadata row. Callers that only need the
        format -- the operator sweep scripts deciding what to do with a
        list -- should use this rather than ``verify()``, which fetches the
        actor's whole property partition to check integrity as well.
        """
        return self._format()

    def _decode_item(self, item_str: str) -> Any:
        try:
            return json.loads(item_str)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse list item for '{self.name}': {e}")
            return item_str

    def _encode_item(self, item: Any) -> str:
        try:
            return json.dumps(item)
        except (TypeError, ValueError):
            return str(item)

    # -- v2 (fractional rank key) helpers -----------------------------

    def _v2_item_prefix(self) -> str:
        return f"list:{self.name}-{_V2_RANK_MARKER}"

    def _v2_item_name(self, rank: str) -> str:
        return f"{self._v2_item_prefix()}{rank}"

    def _v2_bounds(self) -> tuple[str, str]:
        """Inclusive [lower, upper] bounds for get_range() that cover
        exactly this list's v2 item rows -- see the module docstring."""
        return (self._v2_item_prefix(), f"list:{self.name}-$")

    def _v2_ensure_rank_cache(self, force: bool = False) -> list[str]:
        """Return the sorted rank-key cache, loading it (one keys-only
        range query) if absent or `force`d. The returned list is the SAME
        object held in `self._v2_rank_cache` -- callers that insert/delete
        a single entry may mutate it in place instead of forcing a reload."""
        if self._v2_rank_cache is not None and not force:
            return self._v2_rank_cache
        lower, upper = self._v2_bounds()
        db = get_property(self.config)
        rows = db.get_range(
            actor_id=self.actor_id, lower=lower, upper=upper, keys_only=True
        )
        prefix_len = len(self._v2_item_prefix())
        self._v2_rank_cache = sorted(
            rank for name in rows if _v2_is_rank(rank := name[prefix_len:])
        )
        return self._v2_rank_cache

    def _v2_load_full(self) -> list[tuple[str, str]]:
        """One full range query -> sorted (rank, raw_value) pairs. Also
        refreshes the rank-key cache as a side effect (the invariant that
        to_list()/__iter__/slice() cost exactly one query, and warm the
        cache for any __getitem__ calls that follow)."""
        lower, upper = self._v2_bounds()
        db = get_property(self.config)
        rows = db.get_range(actor_id=self.actor_id, lower=lower, upper=upper)
        prefix_len = len(self._v2_item_prefix())
        pairs = sorted(
            (rank, value)
            for name, value in rows.items()
            if _v2_is_rank(rank := name[prefix_len:])
        )
        self._v2_rank_cache = [rank for rank, _ in pairs]
        return pairs

    def _v2_to_list(self) -> list[Any]:
        return [self._decode_item(value) for _, value in self._v2_load_full()]

    def _create_default_metadata_v2(self) -> dict[str, Any]:
        """Default metadata for a brand-new (v2) list. No `length` key --
        v2 has no authoritative stored length, it's always counted from the
        rank-key range."""
        now = datetime.now().isoformat()
        return {
            "format": 2,
            "created_at": now,
            "updated_at": now,
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "description": "",
            "explanation": "",
        }

    def _load_metadata(self) -> dict[str, Any]:
        """Load metadata from database, with caching."""
        if self._meta_cache is not None:
            return self._meta_cache

        if not self._db:
            return self._create_default_metadata()

        # Use fresh DB instance to avoid handle conflicts
        meta_db = get_property(self.config)
        meta_str = meta_db.get(
            actor_id=self.actor_id, name=self._get_meta_property_name()
        )

        if meta_str is None:
            # No metadata exists - this is a new list, created directly in
            # the v2 (fractional rank key) format.
            if _V2_RANK_MARKER in self.name:
                raise ValueError(
                    f"List name '{self.name}' cannot contain "
                    f"'{_V2_RANK_MARKER}' -- reserved for internal storage "
                    f"keys (a list named '...{_V2_RANK_MARKER}...' would "
                    f"put its item rows inside another list's storage "
                    f"range)"
                )

            # Check for property collision - error if property exists
            prop_db = get_property(self.config)
            existing_prop = prop_db.get(actor_id=self.actor_id, name=self.name)
            if existing_prop is not None:
                raise ValueError(
                    f"Cannot create list '{self.name}': a property with this name already exists. "
                    f"Delete the property first or use a different name."
                )

            # No metadata exists, create default
            # Don't save yet - let the caller save via set_description/set_explanation
            meta = self._create_default_metadata_v2()
            self._meta_cache = (
                meta  # Cache it for subsequent calls within this instance
            )
            return meta

        try:
            parsed_meta = json.loads(meta_str)
        except (json.JSONDecodeError, TypeError) as e:
            # Do NOT self-heal by writing a fresh default: that orphans
            # every existing item row (length: 0 with no way back to them).
            # An unparsable metadata row means real corruption -- raise so
            # the caller can run verify()/compact() (or the operator can
            # inspect the row directly) instead of silently losing data.
            raise ValueError(f"Unparsable metadata for list '{self.name}': {e}") from e
        if not isinstance(parsed_meta, dict):
            raise ValueError(
                f"Metadata for list '{self.name}' is not a JSON object "
                f"(got {type(parsed_meta).__name__})"
            )
        self._meta_cache = parsed_meta
        return self._meta_cache

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
        }

    def _read_meta_row(self) -> dict[str, Any] | None:
        """The meta row as stored RIGHT NOW, bypassing the cache entirely.

        ``None`` means the row is absent -- the list was never created, or
        another writer deleted it. Unparsable content raises, matching
        ``_load_metadata()``: self-healing over it orphans every item row.

        This is deliberately NOT ``_load_metadata()``. That method conflates
        "absent" with "a brand-new v2 list", which is the right default for
        a reader and the wrong one for a writer deciding whether it is
        allowed to recreate a row somebody else just deleted.
        """
        if not self._db:
            return None
        meta_db = get_property(self.config)
        meta_str = meta_db.get(
            actor_id=self.actor_id, name=self._get_meta_property_name()
        )
        if meta_str is None:
            return None
        try:
            parsed = json.loads(meta_str)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"Unparsable metadata for list '{self.name}': {e}") from e
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Metadata for list '{self.name}' is not a JSON object "
                f"(got {type(parsed).__name__})"
            )
        return parsed

    def _save_metadata(
        self,
        updates: dict[str, Any],
        *,
        remove: tuple[str, ...] = (),
        create_if_absent: bool = True,
    ) -> None:
        """Merge ``updates`` into a FRESH read of the meta row and write it
        back.

        **Never round-trip a cached metadata dict through here.** That is
        what this signature exists to prevent. A ``ListProperty`` instance
        caches metadata until something explicitly invalidates it -- for an
        instance an application retains, unboundedly -- so writing a whole
        cached dict back means a concurrent ``append()`` can revert a
        migration's ``format: 2`` flip long after it completed. Metadata
        then claims format 1 while every item lives in v2 rows nothing
        reads, and migration's final step deletes the v1 rows: total silent
        loss on ordinary traffic. Naming the fields you changed makes that
        impossible, because ``format`` is never among them unless you meant
        it.

        Args:
            updates: only the fields this caller is changing. ``length`` is
                dropped when the stored row is v2 -- v2 has no authoritative
                stored length, and a writer that computed one against a
                different view must not introduce one.
            remove: fields to delete from the stored row (migration drops
                ``length`` this way).
            create_if_absent: what to do when the meta row is gone. ``True``
                (list creation, and the v2 metadata touch whose whole purpose
                is to make the row exist) recreates it from this instance's
                view. ``False`` skips the write entirely: for the v1 length
                writers, an absent row means a concurrent ``delete()`` won,
                and merging a stale length would resurrect the list.
        """
        stored = self._read_meta_row()
        if stored is None:
            if not create_if_absent:
                logger.info(
                    f"List '{self.name}' (actor {self.actor_id}): metadata "
                    f"row is gone (deleted concurrently) -- skipping the "
                    f"metadata update rather than recreating the list"
                )
                # Drop BOTH caches, not just the metadata one: whatever this
                # instance believes about the list is describing something
                # that no longer exists.
                self._invalidate_cache()
                return
            # No stored state to preserve, so nothing can be reverted by
            # falling back to what this instance knows. _load_metadata()
            # also applies the '#'-name ban and the property-name collision
            # check that creating a list must go through.
            stored = dict(self._load_metadata())

        stored_format = int(stored.get("format", 1) or 1)

        # Did this instance dispatch the mutation it is now recording against
        # a format the list no longer has?
        #
        # The write itself is already done by the time we get here -- append()
        # stores the item row, then calls this -- so an item written by a
        # stale v1 instance into a list that is now v2 is sitting in a
        # v1-shaped row that no v2 reader will ever return. It is not lost
        # data, it is unreachable data, and until this warning existed the
        # only trace was a DEBUG line and a `foreign_format_rows` count that
        # verify() reports while calling the list HEALTHY.
        #
        # Self-limiting: _replace_metadata() below caches the merged row, so
        # this instance's NEXT mutation dispatches correctly. One write per
        # retained instance, which is why this warns rather than raises --
        # the caller's operation succeeded, it just landed somewhere nothing
        # reads. Found by consumer verification against 3.13.0 GA.
        if self._meta_cache is not None:
            believed_format = int(self._meta_cache.get("format", 1) or 1)
            if believed_format != stored_format:
                logger.warning(
                    "List '%s' (actor %s): this instance believed the storage "
                    "format was v%d but the stored row says v%d -- it was "
                    "migrated by someone else while this instance was held. "
                    "Any item this operation wrote went into a v%d-shaped row "
                    "that v%d readers do not see; verify() will still report "
                    "the list healthy, and the row shows up only as "
                    "foreign_format_rows. Re-issue the write. This instance "
                    "self-corrects from here.",
                    self.name,
                    self.actor_id,
                    believed_format,
                    stored_format,
                    believed_format,
                    stored_format,
                )

        meta = dict(stored)
        if stored_format == 2:
            updates = {k: v for k, v in updates.items() if k != "length"}
        meta.update(updates)
        for field in remove:
            meta.pop(field, None)
        self._replace_metadata(meta)

    def _replace_metadata(self, meta: dict[str, Any]) -> None:
        """Write ``meta`` wholesale and cache it.

        Only two kinds of caller may use this: a deliberate reset
        (``clear()``, which resets description/explanation by design) and
        one that derived ``meta`` from a read it just performed itself
        (migration's format flip). Everything else goes through
        ``_save_metadata()`` -- see its docstring for what writing a cached
        dict back costs.
        """
        meta["updated_at"] = datetime.now().isoformat()

        if self._db:
            meta_property_name = self._get_meta_property_name()
            meta_json = json.dumps(meta)
            # Use fresh DB instance to avoid handle conflicts
            meta_db = get_property(self.config)
            if not meta_db.set(
                actor_id=self.actor_id, name=meta_property_name, value=meta_json
            ):
                raise RuntimeError(f"list metadata write failed for '{self.name}'")

        self._meta_cache = meta

    def _invalidate_cache(self) -> None:
        """Invalidate the metadata cache AND the v2 rank cache.

        The two are coupled: the rank cache is only meaningful for the
        format the metadata cache reports, so keeping stale ranks after
        discarding the metadata they belong to is how a v1 view acquires a
        v2 list's positions. Nothing enforced that before; this does.

        Callers that only want the metadata re-read (every v2 item
        mutation, which has just updated the rank cache in place and would
        otherwise pay a full range query on the next operation) should not
        use this -- ``_save_metadata()`` already re-reads the row.
        """
        self._meta_cache = None
        self._v2_rank_cache = None

    def prime_from_rows(self, rows: dict[str, Any]) -> None:
        """Hydrate the metadata cache (and, for v2, the rank-key cache)
        from a pre-fetched name->value mapping.

        `rows` is the result of a bulk fetch_all_including_lists() read.
        Priming avoids re-reading the `list:<name>-meta` row that the bulk
        read already returned, and for v2 lists also serves `len()`,
        `to_list_from_rows()` and iteration with no further queries.

        It does NOT make positional access free. `self[i]`, `pop()` and
        `remove()` re-read the rank keys before acting, deliberately: a
        primed snapshot can be arbitrarily old by the time one of them
        runs, and resolving a position against a stale map means reading —
        or destroying — the wrong item. So a `for i in range(len(lst))`
        loop over `lst[i]` costs two queries per item under v2 even after
        priming.

        Use `to_list()`, `to_indexed_list()` or iteration for that: all
        three are a single range query regardless of length, and
        `to_indexed_list()` gives the `(index, item)` pairs such a loop is
        usually reaching for.

        Ignores missing or unparsable metadata (the normal lazy path then
        applies).
        """
        meta_str = rows.get(self._get_meta_property_name())
        if meta_str is None:
            return
        try:
            parsed = json.loads(meta_str)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(parsed, dict):
            return
        self._meta_cache = parsed
        if int(parsed.get("format", 1) or 1) == 2:
            prefix = self._v2_item_prefix()
            prefix_len = len(prefix)
            self._v2_rank_cache = sorted(
                rank
                for name in rows
                if name.startswith(prefix) and _v2_is_rank(rank := name[prefix_len:])
            )

    def to_list_from_rows(self, rows: dict[str, Any]) -> list[Any]:
        """Like to_list(), but served from a pre-fetched name->value mapping.

        v1: falls back to a per-item database read (via __getitem__) for
        any row missing from the mapping. Item decoding matches
        __getitem__: JSON with a raw-string fallback.

        v2: derived entirely from `rows` (no fallback reads -- there is no
        separate "recorded length" a v2 list could disagree with).

        Raises:
            ListCorruptionError: v1 only -- a row is missing from BOTH the
                mapping and storage.
        """
        if self._is_v2():
            prefix = self._v2_item_prefix()
            prefix_len = len(prefix)
            pairs = sorted(
                (rank, value)
                for name, value in rows.items()
                if name.startswith(prefix) and _v2_is_rank(rank := name[prefix_len:])
            )
            self._v2_rank_cache = [rank for rank, _ in pairs]
            return [self._decode_item(value) for _, value in pairs]

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

    def get_description(self) -> str:
        """Get the description field for UI info about the list."""
        meta = self._load_metadata()
        description = meta.get("description", "")
        return str(description) if description is not None else ""

    def set_description(self, description: str) -> None:
        """Set the description field for UI info about the list."""
        self._save_metadata({"description": description})

    def get_explanation(self) -> str:
        """Get the explanation field to be used for LLMs."""
        meta = self._load_metadata()
        explanation = meta.get("explanation", "")
        return str(explanation) if explanation is not None else ""

    def set_explanation(self, explanation: str) -> None:
        """Set the explanation field to be used for LLMs."""
        self._save_metadata({"explanation": explanation})

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
            - chunk_size: Internal chunk size (currently always 1)
            - length: Number of items in the list

        Note: This returns a copy; modifications won't affect the stored metadata.
        Use set_description() and set_explanation() to update user-facing fields.
        """
        meta = self._load_metadata()
        # v2 has no stored length -- meta.get("length", 0) would silently
        # report 0 for every non-empty v2 list. len(self) counts it (and
        # is cheap after the first call, via the cached rank-key range).
        length = len(self) if self._is_v2() else meta.get("length", 0)
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

    def _v2_getitem(self, index: int) -> Any:
        # Force a fresh rank read, for the same reason the positional writes
        # do: the cached rank at position i still EXISTS after another writer
        # inserts earlier in the list, so the missing-row fallback below never
        # fires and a stale read returns the item that used to be here. v1's
        # positional read is always current (it addresses the row by index
        # directly), and v2 should not be weaker.
        ranks = self._v2_ensure_rank_cache(force=True)
        length = len(ranks)
        orig_index = index
        if index < 0:
            index = length + index
        if index < 0 or index >= length:
            raise IndexError(f"List index {orig_index} out of range (length: {length})")

        rank = ranks[index]
        item_db = get_property(self.config)
        item_str = item_db.get(actor_id=self.actor_id, name=self._v2_item_name(rank))

        if item_str is None:
            # The cached rank list is stale (another instance mutated the
            # list between our cache load and this read) -- reload once
            # before concluding corruption. A concurrent mutation is a
            # normal race, not damaged storage.
            ranks = self._v2_ensure_rank_cache(force=True)
            if index < 0 or index >= len(ranks):
                raise IndexError(
                    f"List index {orig_index} out of range (length: {len(ranks)})"
                )
            rank = ranks[index]
            item_db = get_property(self.config)
            item_str = item_db.get(
                actor_id=self.actor_id, name=self._v2_item_name(rank)
            )
            if item_str is None:
                raise ListCorruptionError(self.name, index)

        return self._decode_item(item_str)

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

    def _v2_touch_metadata(self) -> None:
        """Persist the metadata row after a v2 item mutation.

        v2 doesn't store an authoritative length, so unlike v1 (where every
        mutation writes ``length`` into metadata as a side effect) nothing
        else forces the ``list:{name}-meta`` row to exist. But its
        existence IS load-bearing: ``PropertyListStore.exists()``,
        property/list name-collision detection, and ``list_all()`` all key
        off it. A list whose only mutations were append()/insert()/etc,
        with ``set_description()``/``set_explanation()`` never called,
        must still be discoverable -- so every v2 mutation persists
        metadata (matching v1's per-mutation write, just without a
        `length` field to update).

        Writes no fields of its own: the stored row is re-read and only its
        ``updated_at`` moves. That is what keeps a v2 mutation from carrying
        a cached ``format`` back to storage -- including the reverse of the
        migration case, a stale format-2 cache over storage another process
        has downgraded to v1.

        It DOES create the row when absent, unlike the v1 length writers,
        which skip the write on the grounds that a vanished row means a
        concurrent ``delete()`` won. The asymmetry is real and deliberate:
        under v2 there is no separate creation step, so ``append()`` to a
        list with no metadata row is how a list comes into existence. A
        ``delete()`` racing an ``append()`` therefore leaves a one-item list
        rather than nothing -- which is the same answer appending to a
        never-created list gives, and the alternative is an item row no
        ``exists()`` or ``list_all()`` can see.
        """
        self._save_metadata({})

    def _v2_setitem(self, index: int, value: Any) -> None:
        # Force a fresh rank read: this is a DESTRUCTIVE positional write,
        # and a cached rank list can be arbitrarily old on a long-lived
        # instance. If another writer inserted an item earlier in the list
        # since we cached, position i now names a different row than our
        # cache says -- and we would overwrite the wrong item. See
        # _v2_delitem for the same reasoning. (append()/insert() keep using
        # the cache: their conditional writes bound the damage to where an
        # item lands, never to destroying a different one.)
        ranks = self._v2_ensure_rank_cache(force=True)
        length = len(ranks)
        orig_index = index
        if index < 0:
            index = length + index
        if index < 0 or index >= length:
            raise IndexError(f"List index {orig_index} out of range (length: {length})")

        rank = ranks[index]
        value_str = self._encode_item(value)
        item_db = get_property(self.config)
        if not item_db.set(
            actor_id=self.actor_id, name=self._v2_item_name(rank), value=value_str
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")
        self._v2_touch_metadata()

    def __setitem__(self, index: int, value: Any) -> None:
        """Set item at index."""
        self._maybe_lazy_migrate()
        if self._is_v2():
            self._v2_setitem(index, value)
            return

        length = len(self)

        if index < 0:
            index = length + index

        if index < 0 or index >= length:
            raise IndexError(f"List index {index} out of range (length: {length})")

        if not self._db:
            raise RuntimeError("No database connection available")

        # Serialize the value
        try:
            value_str = json.dumps(value)
        except (TypeError, ValueError):
            value_str = str(value)

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

    def _v2_delitem(self, index: int) -> None:
        # Force a fresh rank read before deleting by position -- a stale
        # cache would delete whichever item USED to be at this index. See
        # _v2_setitem.
        ranks = self._v2_ensure_rank_cache(force=True)
        length = len(ranks)
        orig_index = index
        if index < 0:
            index = length + index
        if index < 0 or index >= length:
            raise IndexError(f"List index {orig_index} out of range (length: {length})")

        rank = ranks[index]
        item_db = get_property(self.config)
        if not item_db.set(
            actor_id=self.actor_id, name=self._v2_item_name(rank), value=None
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")

        # A single row delete IS the whole operation under v2 -- no shift
        # loop. Keep the cache consistent with the write we just made
        # (mutating the same list object _v2_ensure_rank_cache() returned).
        del ranks[index]
        self._v2_touch_metadata()

    def __delitem__(self, index: int) -> None:
        """Delete item at index and shift remaining items."""
        self._maybe_lazy_migrate()
        if self._is_v2():
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

    def _v2_append(self, item: Any) -> None:
        value_str = self._encode_item(item)
        for attempt in range(_V2_MAX_RANK_RETRIES):
            ranks = self._v2_ensure_rank_cache(force=(attempt > 0))
            last = ranks[-1] if ranks else None
            candidate = fi.generate_key_between(last, None)
            if len(candidate) > _V2_RANK_MAX_LEN:
                raise RuntimeError(
                    f"list '{self.name}' rank key exceeded {_V2_RANK_MAX_LEN} "
                    f"chars -- run compact() to rebalance"
                )
            item_db = get_property(self.config)
            if item_db.create_if_not_exists(
                actor_id=self.actor_id,
                name=self._v2_item_name(candidate),
                value=value_str,
            ):
                ranks.append(candidate)
                self._v2_touch_metadata()
                return
            # Collision: another writer took this rank between our cache
            # load and the write. Force-reread on the next attempt so the
            # regenerated key is based on the current actual last rank.
        raise RuntimeError(
            f"list '{self.name}' append: too many rank collisions, retry later"
        )

    def append(self, item: Any) -> None:
        """Add item to end of list."""
        if not self._db:
            raise RuntimeError("No database connection available")

        self._maybe_lazy_migrate()
        if self._is_v2():
            self._v2_append(item)
            return

        length = len(self)

        # Serialize the item
        try:
            item_str = json.dumps(item)
        except (TypeError, ValueError):
            item_str = str(item)

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

        # Update metadata. `length` here is derived from len(self), which
        # reads the metadata cache -- see the class docstring's note on the
        # residual this leaves. What _save_metadata() guarantees is only
        # that nothing ELSE about the stored row is reverted by this write.
        self._save_metadata({"length": length + 1}, create_if_absent=False)

    def extend(self, items: list[Any]) -> None:
        """Add multiple items to end of list."""
        for item in items:
            self.append(item)

    def _v2_item_names_in_range(self) -> list[str]:
        """This list's OWN v2 item row names.

        Used by the destructive paths (``clear()``/``delete()``/migration
        cleanup), so the rank filter is load-bearing here, not merely
        cosmetic: a legacy ``#``-named sibling list's rows share this byte
        range and must never be deleted as if they were ours.
        """
        lower, upper = self._v2_bounds()
        db = get_property(self.config)
        rows = db.get_range(
            actor_id=self.actor_id, lower=lower, upper=upper, keys_only=True
        )
        prefix_len = len(self._v2_item_prefix())
        return [name for name in rows if _v2_is_rank(name[prefix_len:])]

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
        prefix_len = len(f"list:{self.name}-")
        return [name for name in rows if _V1_INDEX_RE.match(name[prefix_len:])]

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
        """
        stored = self._read_meta_row()
        if stored is None:
            names = self._v1_item_names_in_range() + self._v2_item_names_in_range()
        elif int(stored.get("format", 1) or 1) == 2:
            names = self._v1_item_names_in_range()
        else:
            names = self._v2_item_names_in_range()

        for name in names:
            del_db = get_property(self.config)
            if not del_db.set(actor_id=self.actor_id, name=name, value=None):
                raise RuntimeError(
                    f"list item write failed for '{self.name}' during "
                    f"sweep_foreign_format_rows()"
                )
        if names:
            logger.info(
                f"List '{self.name}' (actor {self.actor_id}): swept "
                f"{len(names)} row(s) left by an interrupted format change"
            )
        return len(names)

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
            for item_name in self._v2_item_names_in_range():
                item_db = get_property(self.config)
                if not item_db.set(actor_id=self.actor_id, name=item_name, value=None):
                    raise RuntimeError(
                        f"list item write failed for '{self.name}' during clear()"
                    )
            self._replace_metadata(self._create_default_metadata_v2())
            self._v2_rank_cache = []
            return

        length = len(self)

        # Delete all item properties
        for i in range(length):
            item_db = get_property(self.config)
            if not item_db.set(
                actor_id=self.actor_id, name=self._get_item_property_name(i), value=None
            ):
                raise RuntimeError(f"list item write failed for '{self.name}'[{i}]")

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
            for item_name in self._v2_item_names_in_range():
                item_db = get_property(self.config)
                if not item_db.set(actor_id=self.actor_id, name=item_name, value=None):
                    raise RuntimeError(
                        f"list item write failed for '{self.name}' during delete()"
                    )
            meta_db = get_property(self.config)
            if not meta_db.set(
                actor_id=self.actor_id, name=self._get_meta_property_name(), value=None
            ):
                raise RuntimeError(f"list metadata write failed for '{self.name}'")
            self._meta_cache = None
            self._v2_rank_cache = None
            return

        length = len(self)

        # Delete all item properties
        for i in range(length):
            item_db = get_property(self.config)
            if not item_db.set(
                actor_id=self.actor_id, name=self._get_item_property_name(i), value=None
            ):
                raise RuntimeError(f"list item write failed for '{self.name}'[{i}]")

        # Delete metadata
        meta_db = get_property(self.config)
        if not meta_db.set(
            actor_id=self.actor_id, name=self._get_meta_property_name(), value=None
        ):
            raise RuntimeError(f"list metadata write failed for '{self.name}'")

        # Clear cache
        self._meta_cache = None

    def to_list(self) -> list[Any]:
        """Load entire list into memory.

        v2: exactly one range query, regardless of length.

        Raises:
            ListCorruptionError: v1 only -- a row within ``[0, len(self))``
                is missing from storage. Run ``compact()`` (or the caller's
                remedy) to repair, then retry. Not possible under v2 --
                there is no separate "recorded length" a v2 list's rows
                could disagree with.
        """
        if self._is_v2():
            return self._v2_to_list()

        length = len(self)
        result = []

        for i in range(length):
            result.append(self[i])

        return result

    def slice(self, start: int, end: int) -> list[Any]:
        """Load a range of items efficiently.

        v2: exactly one range query (the full list), sliced in memory --
        still one query, not one per requested item.

        Raises:
            ListCorruptionError: v1 only -- a row within the requested
                range is missing from storage.
        """
        if self._is_v2():
            values = self._v2_to_list()
            length = len(values)
            if start < 0:
                start = max(0, length + start)
            if end < 0:
                end = max(0, length + end)
            start = max(0, min(start, length))
            end = max(start, min(end, length))
            return values[start:end]

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

    def to_indexed_list(self) -> list[tuple[int, Any]]:
        """Load the list as ``(index, item)`` pairs.

        This is the contract the ``/items`` REST accessor documents:
        ``index`` is whatever ``__getitem__``/``__setitem__``/
        ``__delitem__`` accept for this same list, so GET and
        update/delete actions always agree.

        v1: ``index`` IS the storage row's numeric suffix -- storage
        identity and position coincide.

        v2: storage identity is the row's rank key, NOT its position --
        ``index`` here is purely positional (``0..len-1``, derived from
        rank sort order), and every mutation method translates position ->
        rank internally. This is exactly the divergence this method's
        contract was written to keep correct.

        Raises:
            ListCorruptionError: v1 only -- see ``to_list()``.
        """
        return list(enumerate(self.to_list()))

    def _v2_pop(self, index: int) -> Any:
        """Read and remove the item at ``index``.

        ``self[index]`` followed by ``del self[index]`` is not good enough
        under v2: each resolves the rank map independently, so a concurrent
        mutation between them makes pop() return one item and delete a
        different one. Resolving the rank once is necessary but still not
        sufficient — a concurrent ``__setitem__`` on that same rank between
        the read and the delete would discard the other writer's value while
        reporting the one we saw, which is not a valid ordering of the two
        operations either way round. So the delete is CONDITIONAL on the
        exact bytes that were read; if it fails, everything is re-resolved
        and tried again. What pop() returns is always what it removed.

        The retry also covers what would otherwise look like corruption: a
        row missing after the forced refresh usually means another writer
        got there first, which is an ordinary race, not damaged storage.
        """
        for _attempt in range(_V2_MAX_RANK_RETRIES):
            ranks = self._v2_ensure_rank_cache(force=True)
            length = len(ranks)
            if length == 0:
                raise IndexError("pop from empty list")
            resolved = index + length if index < 0 else index
            if resolved < 0 or resolved >= length:
                raise IndexError(f"List index {index} out of range (length: {length})")

            rank = ranks[resolved]
            name = self._v2_item_name(rank)

            item_db = get_property(self.config)
            item_str = item_db.get(actor_id=self.actor_id, name=name)
            if item_str is None:
                # Vanished between the range read and this get -- another
                # writer removed it. Re-resolve rather than calling it
                # corruption.
                continue
            item = self._decode_item(item_str)

            del_db = get_property(self.config)
            if del_db.delete_if_value_equals(
                actor_id=self.actor_id, name=name, value=item_str
            ):
                del ranks[resolved]
                self._v2_touch_metadata()
                return item
            # Value changed or row already gone -- re-resolve and retry.
        raise RuntimeError(
            f"list '{self.name}' pop: too many concurrent modifications, retry later"
        )

    def pop(self, index: int = -1) -> Any:
        """Remove and return item at index (default last)."""
        # v2 dispatch comes FIRST: `len(self)` is served from the rank cache,
        # which an instance that has seen an empty list keeps until something
        # forces a reload. Checking it here would raise "pop from empty list"
        # against a list another writer has since appended to. _v2_pop()
        # forces the refresh and makes its own empty check against that.
        if self._is_v2():
            return self._v2_pop(index)

        if len(self) == 0:
            raise IndexError("pop from empty list")

        # Deliberately NOT calling _maybe_lazy_migrate() here: migration
        # closes holes in flight, so triggering it from pop() would make a
        # corrupted v1 list silently self-repair instead of raising, which
        # is the Phase 2/3 contract. The v1 branch below reaches
        # __delitem__, which triggers migration exactly as it always has.
        if self._is_v2():
            return self._v2_pop(index)

        if index == -1:
            index = len(self) - 1

        item = self[index]
        del self[index]
        return item

    def _v2_insert(self, index: int, item: Any) -> None:
        value_str = self._encode_item(item)
        for attempt in range(_V2_MAX_RANK_RETRIES):
            ranks = self._v2_ensure_rank_cache(force=(attempt > 0))
            length = len(ranks)
            pos = index
            if pos < 0:
                pos = max(0, length + pos)
            if pos > length:
                pos = length

            lower = ranks[pos - 1] if pos > 0 else None
            upper = ranks[pos] if pos < length else None
            candidate = fi.generate_key_between(lower, upper)
            if len(candidate) > _V2_RANK_MAX_LEN:
                raise RuntimeError(
                    f"list '{self.name}' rank key exceeded {_V2_RANK_MAX_LEN} "
                    f"chars -- run compact() to rebalance"
                )
            item_db = get_property(self.config)
            if item_db.create_if_not_exists(
                actor_id=self.actor_id,
                name=self._v2_item_name(candidate),
                value=value_str,
            ):
                ranks.insert(pos, candidate)
                self._v2_touch_metadata()
                return
            # Collision: force a fresh read (recomputing neighbours at this
            # position) on the next attempt.
        raise RuntimeError(
            f"list '{self.name}' insert: too many rank collisions, retry later"
        )

    def insert(self, index: int, item: Any) -> None:
        """Insert item at given index."""
        if not self._db:
            raise RuntimeError("No database connection available")

        self._maybe_lazy_migrate()
        if self._is_v2():
            self._v2_insert(index, item)
            return

        length = len(self)

        if index < 0:
            index = max(0, length + index)
        if index > length:
            index = length

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
        try:
            item_str = json.dumps(item)
        except (TypeError, ValueError):
            item_str = str(item)

        insert_db = get_property(self.config)
        if not insert_db.set(
            actor_id=self.actor_id,
            name=self._get_item_property_name(index),
            value=item_str,
        ):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")

        # Update metadata
        self._save_metadata({"length": length + 1}, create_if_absent=False)

    def _v2_remove(self, value: Any) -> None:
        """Delete the first item equal to ``value``, by RANK.

        Same hazard `_v2_pop` addresses, one method over: iterating to find
        the position and then deleting by that position resolves the rank map
        twice, so a concurrent mutation in between makes remove() delete
        whatever happens to sit at that position now rather than the item it
        matched. Deleting the rank the match came from removes exactly the
        item that was matched, or nothing.
        """
        for _attempt in range(_V2_MAX_RANK_RETRIES):
            pairs = self._v2_load_full()
            for i, (rank, raw_value) in enumerate(pairs):
                if self._decode_item(raw_value) != value:
                    continue
                del_db = get_property(self.config)
                if not del_db.delete_if_value_equals(
                    actor_id=self.actor_id,
                    name=self._v2_item_name(rank),
                    value=raw_value,
                ):
                    # Overwritten or already deleted since the scan -- the
                    # match is stale, so rescan rather than deleting whatever
                    # is there now.
                    break
                # _v2_load_full() just set the cache to exactly these ranks
                # in this order, so dropping entry i keeps it consistent.
                ranks = self._v2_rank_cache
                if ranks is not None and i < len(ranks) and ranks[i] == rank:
                    del ranks[i]
                else:  # pragma: no cover -- defensive
                    self._v2_rank_cache = None
                self._v2_touch_metadata()
                return
            else:
                # Scanned every item without a match: the value genuinely
                # isn't there (possibly because a concurrent remove() of the
                # same value won), which is exactly ValueError.
                raise ValueError(f"{value} not in list")
        raise RuntimeError(
            f"list '{self.name}' remove: too many concurrent modifications, retry later"
        )

    def remove(self, value: Any) -> None:
        """Remove first occurrence of value."""
        # No _maybe_lazy_migrate() here, for the same reason pop() omits it:
        # migration closes holes in flight, so triggering it before the v1
        # scan would make a corrupted list silently self-repair instead of
        # raising. The v1 scan below reaches __delitem__, which migrates
        # exactly as it always has.
        if self._is_v2():
            self._v2_remove(value)
            return

        for i, item in enumerate(self):
            if item == value:
                del self[i]
                return
        raise ValueError(f"{value} not in list")

    @staticmethod
    def _normalize_search_bounds(
        start: int, stop: int | None, length: int
    ) -> tuple[int, int]:
        """Python-slice normalization for index()'s start/stop.

        Shared by both storage formats so they cannot drift: a list's
        ``index()`` must answer the same question before and after
        migration. Negative values count from the end and everything is
        clamped into ``[0, length]``, matching ``list.index``.
        """
        if start < 0:
            start = max(0, length + start)
        else:
            start = min(start, length)
        if stop is None:
            stop = length
        elif stop < 0:
            stop = max(0, length + stop)
        else:
            stop = min(stop, length)
        return start, stop

    def index(self, value: Any, start: int = 0, stop: int | None = None) -> int:
        """Return index of first occurrence of value.

        ``start``/``stop`` follow ``list.index`` semantics, including
        negative values counting from the end.
        """
        if self._is_v2():
            # One range query for the whole list, then scan in memory. Going
            # through self[i] would cost two queries PER ITEM now that
            # positional reads refresh the rank map, and it would compare
            # against a list that can shift under the loop.
            values = self._v2_to_list()
            begin, end = self._normalize_search_bounds(start, stop, len(values))
            for i in range(begin, end):
                if values[i] == value:
                    return i
            raise ValueError(f"{value} is not in list")

        length = len(self)
        begin, end = self._normalize_search_bounds(start, stop, length)

        for i in range(begin, end):
            if self[i] == value:
                return i

        raise ValueError(f"{value} is not in list")

    def count(self, value: Any) -> int:
        """Return number of occurrences of value."""
        count = 0
        for item in self:
            if item == value:
                count += 1
        return count

    def _identity_of(self, raw_value: str, identity_key: str) -> Any:
        """This row's value for ``identity_key``, or ``None`` if it has none.

        Rows that are not dicts, or that lack the field, are not
        identity-addressable and are excluded from identity duplicate
        detection entirely -- lumping them together under a shared "no
        identity" bucket would report every such row as a duplicate of
        every other.
        """
        decoded = self._decode_item(raw_value)
        if not isinstance(decoded, dict) or identity_key not in decoded:
            return None
        value = decoded[identity_key]
        try:
            hash(value)
        except TypeError:
            # Unhashable identity (list/dict); compare on a stable
            # serialization instead of refusing to check it.
            return ("json", json.dumps(value, sort_keys=True, default=str))
        # Type-tag even hashable values. Python considers True == 1 and
        # hashes them identically, so an untagged dict key would merge
        # {"id": true} with {"id": 1} and report a duplicate that does not
        # exist -- enough to mark a list unhealthy and fail a sweep.
        return (type(value).__name__, value)

    @staticmethod
    def _identity_duplicates(
        identities: list[tuple[int, Any]],
    ) -> tuple[dict[Any, list[int]], int]:
        """Group positions by identity, keeping only identities that appear
        more than once -- ANYWHERE in the list, not merely adjacently.

        Adjacency is the right constraint for the byte heuristic, because
        the shift-loop residue it looks for is always adjacent by
        construction. It is the wrong constraint here: a repeated identity
        is a defect wherever the two copies sit, and a real deployment had
        the same id at positions 31 and 36 with the sweep reporting the
        list healthy. One dict pass finds it.
        """
        by_identity: dict[Any, list[int]] = {}
        for index, identity in identities:
            if identity is None:
                continue
            by_identity.setdefault(identity, []).append(index)
        checked = sum(len(v) for v in by_identity.values())
        duplicates = {
            # Report the identity itself, not the internal type tag.
            k[1] if isinstance(k, tuple) and len(k) == 2 else k: v
            for k, v in by_identity.items()
            if len(v) > 1
        }
        return duplicates, checked

    def _v2_verify(self, identity_key: str | None = None) -> dict[str, Any]:
        """Read-only integrity check for v2 lists.

        Structurally, v2 cannot have holes or orphans -- there is no
        separate "recorded length" a row could disagree with; every
        present row IS a position. The only thing worth reporting is rank
        keys approaching the length cap (a signal to compact()/rebalance
        before insert()/append() start failing) and the same
        adjacent-duplicate heuristic v1 reports (informational, not part
        of ``healthy`` -- a duplicate value is never itself corruption
        under v2).

        Returns:
            Dict with:
            - format: 2
            - length: item count (one range query)
            - max_rank_length: the longest rank key currently in use
            - adjacent_duplicates: same heuristic as v1's verify(), but
              position-indexed pairs -- informational only
            - foreign_format_rows: how many v1-shaped rows share this
              list's name -- residue from an interrupted format change.
              Informational, NOT part of ``healthy``: the rows are inert to
              every v2 reader, and ``sweep_foreign_format_rows()`` (which
              ``clear()``, ``delete()`` and a re-run of the migration all
              call) removes them without operator involvement
            - needs_rebalance: True iff a rank key has reached the warning
              zone -- the ONLY v2 condition ``compact()`` can fix. Repair
              tooling should gate on this, not on ``healthy``, which also
              goes false for duplicate identities that ``compact()`` will
              not touch
            - healthy: True iff no rank key is within the rebalance
              warning zone of the cap and no identity is repeated
        """
        pairs = self._v2_load_full()
        max_rank_length = max((len(rank) for rank, _ in pairs), default=0)

        adjacent_duplicates: list[tuple[int, int]] = []
        for i in range(len(pairs) - 1):
            if pairs[i][1] == pairs[i + 1][1]:
                adjacent_duplicates.append((i, i + 1))

        report: dict[str, Any] = {
            "format": 2,
            "length": len(pairs),
            "max_rank_length": max_rank_length,
            "adjacent_duplicates": adjacent_duplicates,
            "foreign_format_rows": len(self._v1_item_names_in_range()),
            "needs_rebalance": max_rank_length >= _V2_RANK_WARNING_LENGTH,
            "healthy": max_rank_length < _V2_RANK_WARNING_LENGTH,
        }
        duplicates: dict[Any, list[int]] | None = None
        identity_checked_count: int | None = None
        if identity_key is not None:
            duplicates, identity_checked_count = self._identity_duplicates(
                [
                    (i, self._identity_of(raw, identity_key))
                    for i, (_, raw) in enumerate(pairs)
                ]
            )
        report["duplicate_identities"] = duplicates
        report["identity_checked_count"] = identity_checked_count
        if duplicates:
            report["healthy"] = False
        return report

    def verify(self, identity_key: str | None = None) -> dict[str, Any]:
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
                detection note below.

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
            return self._v2_verify(identity_key=identity_key)

        meta = self._load_metadata()
        stored_length = int(meta.get("length", 0) or 0)

        db_list = get_property_list(self.config)
        rows = db_list.fetch_all_including_lists(actor_id=self.actor_id) or {}

        pattern = re.compile(rf"^list:{re.escape(self.name)}-(\d+)$")
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

        # Cross-format residue, counted from the partition dump already in
        # hand rather than a second range read.
        v2_prefix = self._v2_item_prefix()
        v2_prefix_len = len(v2_prefix)
        foreign_format_rows = sum(
            1
            for key in rows
            if key.startswith(v2_prefix) and _v2_is_rank(key[v2_prefix_len:])
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

    def _v2_compact(self) -> dict[str, Any]:
        """Rebalance a v2 list's rank keys back to short, evenly-spaced
        values.

        Regenerates ``n`` evenly distributed ranks with
        ``fractional_indexing.generate_n_keys_between(None, None, n)`` --
        deterministic for a given ``n``, so re-running compact() without
        the list changing in between converges to the same result. Rows
        whose target rank already matches their current rank are left
        untouched. For rows that need renaming, the write uses a plain
        ``set()`` only when the target name is unoccupied or is this same
        item's own current row; if the target collides with a DIFFERENT
        item's not-yet-renamed row, a nudged rank is generated between the
        last successfully written rank and the next target instead of
        overwriting it -- compact() never clobbers a row it hasn't gotten
        to yet. Old rows that didn't survive under their original name are
        deleted last, so a crash mid-compact leaves every item readable
        under either its old or new name, never neither.

        CRASH WINDOW (known limitation, deliberate trade): because new rows
        become visible before any old row is retired, a crash between the
        write loop and the cleanup loop leaves BOTH copies of every
        already-rewritten item in the authoritative range. Reads then return
        duplicates, and re-running compact() does not recover the original
        list -- it treats all 2n rows as genuine items and rebalances them.
        Recovery is manual: compare against a backup, or delete the stale
        copies (the old ranks are the ones NOT drawn from the evenly-spaced
        ``a0, a1, ...`` sequence a fresh rebalance produces).

        This is chosen over the alternative -- deleting each old row right
        after writing its replacement -- because that trades a visible
        failure for an invisible one. Targets are always ``a0, a1, ...``
        while old ranks may sort anywhere (a list built by repeated
        insert-at-0 has ranks below ``a0``), so retiring old rows
        incrementally makes intermediate states silently REORDERED rather
        than duplicated, and a reordered list passes every check
        ``verify()`` performs. Duplicate residue at least shows up in the
        data. A staged-commit protocol that is genuinely recoverable is
        tracked in ``thoughts/todo/whole-list-rewrite-atomicity.md``.
        """
        report = self._v2_verify()

        if not self._db:
            raise RuntimeError("No database connection available")

        pairs = self._v2_load_full()
        n = len(pairs)
        old_ranks = [rank for rank, _ in pairs]
        old_names = {self._v2_item_name(rank) for rank in old_ranks}
        target_ranks = fi.generate_n_keys_between(None, None, n)

        written_ranks: list[str] = []
        for i, ((old_rank, value), target_rank) in enumerate(
            zip(pairs, target_ranks, strict=True)
        ):
            if target_rank == old_rank:
                written_ranks.append(old_rank)
                continue

            rank = target_rank
            for attempt in range(_V2_MAX_RANK_RETRIES + 1):
                new_name = self._v2_item_name(rank)
                if new_name not in old_names or rank == old_rank:
                    item_db = get_property(self.config)
                    if not item_db.set(
                        actor_id=self.actor_id, name=new_name, value=value
                    ):
                        raise RuntimeError(
                            f"list item write failed for '{self.name}' during compact()"
                        )
                    written_ranks.append(rank)
                    break
                if attempt == _V2_MAX_RANK_RETRIES:
                    raise RuntimeError(
                        f"compact() could not rebalance '{self.name}' -- "
                        f"rank collision storm"
                    )
                # Bisect between the rank that JUST collided and the next
                # unclaimed target boundary -- using the failed candidate
                # (not the last-written rank) as the new lower bound is
                # what makes each retry generate a genuinely different,
                # still-monotonic value instead of regenerating the same
                # collision forever.
                upper_idx = i + 1
                upper = target_ranks[upper_idx] if upper_idx < n else None
                rank = fi.generate_key_between(rank, upper)

        survivors = set(written_ranks)
        for old_rank in old_ranks:
            if old_rank not in survivors:
                del_db = get_property(self.config)
                if not del_db.set(
                    actor_id=self.actor_id,
                    name=self._v2_item_name(old_rank),
                    value=None,
                ):
                    raise RuntimeError(
                        f"list item write failed for '{self.name}' during compact() cleanup"
                    )

        self._v2_rank_cache = sorted(written_ranks)
        return report

    def compact(self, allow_reverted: bool = False) -> dict[str, Any]:
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
            allow_reverted: compact a v1 list that has rows of the other
                storage format, accepting that the items in them stop
                being reachable and stop being reported. Off by default.
                Recover first -- re-running ``migrate_to_v2()`` on the
                pre-revert metadata, or reading the v2 rows out by hand --
                and the question does not arise.

        Returns:
            The ``verify()`` report this call acted on (taken before any
            write). On a refusal, that report plus ``compacted: False``
            and ``reason``.
        """
        if self._is_v2():
            return self._v2_compact()

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

        db_list = get_property_list(self.config)
        rows = db_list.fetch_all_including_lists(actor_id=self.actor_id) or {}

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

        db_list = get_property_list(self.config)
        rows = db_list.fetch_all_including_lists(actor_id=self.actor_id) or {}

        ordered_values: list[str] = [
            rows[self._get_item_property_name(i)]
            for i in range(stored_length)
            if self._get_item_property_name(i) in rows
        ]

        # Re-check the stored format one last time before the first
        # destructive write. The gap between the check above and here spans
        # verify()'s and fetch_all_including_lists()' partition reads -- wide
        # enough for a concurrent migration to land in it. Reading the meta
        # row directly (not through the cache, which verify() just
        # repopulated) is what makes this a real second look.
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
        stored_meta = self._read_meta_row()
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
        except Exception as e:
            logger.warning(
                f"Lazy migration to v2 failed for list '{self.name}': {e} "
                f"-- continuing as v1"
            )
