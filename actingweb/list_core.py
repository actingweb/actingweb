"""The list format, independent of where its rows are stored.

``ListCore`` holds the v2 list format (fractional rank keys, handles, spanned
items, keyed appends, ``verify()``, ``compact()``) and reaches its rows only
through a ``ListStorage``. ``ListProperty`` (``actingweb.property_list``) is
the core over an actor's property rows, plus the property-only v1 format and
its migration; ``ListAttribute`` (``actingweb.attribute_list``) is the core
over an attribute bucket.

The core logs under ``actingweb.property_list``, the logger name consumers
already configure.
"""

import hashlib
import hmac
import json
import logging
import random
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NamedTuple, NoReturn, Protocol, runtime_checkable

import fractional_indexing as fi

from actingweb.db.exceptions import DbError
from actingweb.property_list_span import (
    GEN_IN_RAW_RE,
    GEN_RE,
    KEY_ROW_RE,
    MAX_PARTS,
    SPAN_PART_BYTES,
    SPAN_ROW_RE,
    Envelope,
    EnvelopeError,
    SpanInfo,
    carries_library_marker,
    encode_item,
    encoded_size,
    gen_age_seconds,
    key_prefix,
    key_row_name,
    looks_like_envelope,
    new_gen,
    parse,
    part_names,
    span_prefix,
    split_parts,
    value_digest,
    wrap,
)

logger = logging.getLogger("actingweb.property_list")

# Bounded compare-and-swap retry on the metadata row (Phase 9 of
# thoughts/plans/2026-08-20-v2-positional-access-cost.md). Single digits,
# full-jitter exponential backoff -- in a lambda-like fleet the contending
# writers are separate containers, so no in-process lock can dampen the
# race; the bound and the jitter are the whole mechanism.
#
# The advisory bound (a v2 metadata TOUCH -- updated_at/count_hint on an
# already-committed mutation) is deliberately smaller than the semantic
# bound (a write that creates the row or carries format/length): the
# advisory path spends its retries only to then SWALLOW exhaustion and
# succeed anyway, so there is no correctness reason to let it burn as much
# wall-clock as a write the caller is actually waiting on.
_METADATA_CAS_MAX_ATTEMPTS = 6
_METADATA_CAS_ADVISORY_MAX_ATTEMPTS = 3
_METADATA_CAS_BACKOFF_BASE_SECONDS = 0.05

# Distinguishes "no stashed read" from "stashed a read that found the row
# absent" (a valid, meaningful (None, None) tuple) -- see
# ListProperty._dispatch_and_stash().
_NO_STASH = object()

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
_V2_RANK_ALPHABET = frozenset(fi.BASE_62_DIGITS)

# Spanned items (thoughts/plans/2026-10-30-spanned-list-items.md, Phase 2).
# A reader that finds a spanned item's body set short re-reads the head
# strongly at most this many times (following a changed generation) before
# calling the span broken.
_SPAN_MAX_REREADS = 2
# The orphan sweep (compact(sweep_span_orphans=True)) never removes a body
# generation younger than this: an append that has written its bodies and not
# yet its head must not lose them.
_SPAN_ORPHAN_MIN_AGE_SECONDS = 3600

# Idempotent appends (Phase 3 of the same plan). One append_once() call makes
# at most this many arbitration passes (a key-row create and what follows a
# lost one) before giving up with RuntimeError.
_APPEND_ONCE_MAX_ATTEMPTS = 3
# The longest idempotency key append_once() accepts, in characters.
_APPEND_ONCE_KEY_MAX_LEN = 512
# verify(), compact() and repair_keys() leave alone what an append_once() call
# wrote this recently (by its writer token's timestamp): a second head for a
# key, or a head without its key row, is the normal state of a call still
# running, not damage.
_KEYED_IN_FLIGHT_SECONDS = 3600


class _Unresolved:
    """The type of ``UNRESOLVED``."""

    _instance: "_Unresolved | None" = None

    def __new__(cls) -> "_Unresolved":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNRESOLVED"

    def __bool__(self) -> bool:
        return False


# The slot value ``items_with_handles(resolve=False)`` and
# ``to_list_from_rows(rows, resolve=False)`` put where a spanned item's body
# was not read. Its handle carries ``spanned=True`` and ``bytes``; read the
# item with ``item_at(handle)``.
UNRESOLVED: Any = _Unresolved()


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


class ListItemSpanError(ListCorruptionError):
    """A spanned item's body rows are missing or do not match its head, or
    its head is a malformed envelope.

    Raised instead of ever returning a partial item, after the reader has
    re-read the head and the bodies strongly (a concurrent update can make
    a reader's view of the old generation short for a moment). A
    ``ListCorruptionError`` (and so an ``IndexError``), so the handlers'
    409 applies, with ``remedy`` naming the repair: the orphan sweep
    removes the broken head, or the caller removes the item by handle. The
    message carries the list name, rank and part counts only.
    """

    remedy = (
        "run actingweb-verify-property-lists --repair --sweep-spans, or remove "
        "the item with delete_by_handle()"
    )

    def __init__(
        self,
        list_name: str,
        rank: str,
        *,
        expected_parts: int | None = None,
        found_parts: int | None = None,
        detail: str | None = None,
    ) -> None:
        self.list_name = list_name
        self.rank = rank
        self.index = rank  # type: ignore[assignment]
        self.expected_parts = expected_parts
        self.found_parts = found_parts
        if detail is None:
            detail = (
                f"spans {expected_parts} body row(s) but {found_parts} matching "
                f"row(s) were found"
            )
        IndexError.__init__(
            self, f"List '{list_name}' item at rank {rank!r} {detail}; {self.remedy}"
        )


class _ItemGone(IndexError):
    """A spanned item's head vanished between a reader's head read and its
    body read: another request deleted the item. Not corruption. Whole-list
    readers drop the item (the delete won the race); point reads see an
    ordinary ``IndexError``."""


class ListMetadataContentionError(RuntimeError):
    """A list's metadata row stayed under contention through every
    compare-and-swap retry this mutation was willing to make.

    This means OTHER writers, not this one: in a lambda-like fleet the
    contending writers are separate containers, so no in-process lock can
    dampen the race -- the bounded retry count and jittered backoff are
    the whole mechanism. A retryable condition, not a server fault:
    ``handlers/`` maps this to **503 with ``Retry-After``**, not a bare
    500, so an API-gateway consumer sees "retry" rather than "there is a
    bug".

    Raised only for a metadata write that CREATES the row or carries a
    semantic field (a ``format`` flip, v1's ``length``) -- there the
    metadata write IS the operation. An advisory touch (``updated_at``
    plus v2's ``count_hint`` on an already-existing row) swallows the
    same exhaustion, or a backend fault, with one WARNING instead: the
    item row it is recording is already committed, and failing the whole
    mutation over a missed count-hint update would manufacture retries
    (and duplicate writes) a caller cannot guard against in-process on
    lambda.

    Also raised, with a ``detail``, by a list's first mutation that lost
    its conditional meta-row create to a writer whose row it cannot
    follow (see ``ListProperty._v2_create_meta_row()``): nothing has been
    written in that case, and the 503's "retry" is exactly right.
    """

    def __init__(
        self, list_name: str, actor_id: str, *, detail: str | None = None
    ) -> None:
        self.list_name = list_name
        self.actor_id = actor_id
        clause = (
            detail if detail is not None else "metadata is under sustained contention"
        )
        super().__init__(
            f"List '{list_name}' (actor {actor_id}) {clause} -- retry the request"
        )


class ListItemTooLargeError(ValueError):
    """A list item's encoded size is over a configured limit.

    Raised **before any write** (no item row, and on a never-created list
    no meta row either), so a caller can split the item or raise the limit
    and try again. A ``ValueError`` subclass; catch it ahead of any generic
    ``except ValueError``. The REST handlers answer **413**.

    ``limit`` is the limit that was exceeded: ``list_item_max_bytes``, or,
    where a backend row cap applies and the item cannot be stored across
    several rows, ``list_item_span_threshold``. The message carries the list
    name, the sizes and the reason only, never item content.
    """

    def __init__(self, list_name: str, size: int, limit: int, reason: str) -> None:
        self.list_name = list_name
        self.bytes = size
        self.limit = limit
        self.reason = reason
        super().__init__(
            f"List '{list_name}' item is {size} bytes encoded, over the "
            f"{limit}-byte limit ({reason})"
        )


class ListNameTakenError(ValueError):
    """A list cannot be created: a scalar row of the same name exists (a
    property, or an attribute). A ``ValueError`` as before; the replica
    path catches it to replace the scalar with the list."""


class ListRankExhaustedError(RuntimeError):
    """A rank key would pass the length cap: the list needs ``compact()``
    (or, on a replica, a rebuild) before another item can go here.

    A ``RuntimeError`` so callers that caught the plain ``RuntimeError`` this
    replaced keep catching it."""


class ListLayoutConflictError(ListCorruptionError):
    """The list's rows are in two layouts at once (what a pre-3.16 writer
    leaves beside a converted attribute list), or a conversion met rows it
    did not write. Neither copy is known to be right; nothing is merged."""

    def __init__(self, list_name: str, detail: str) -> None:
        IndexError.__init__(self, f"List '{list_name}': {detail}")
        self.list_name = list_name
        self.index = -1
        self.detail = detail


@dataclass(frozen=True)
class ListItemHandle:
    """Opaque handle to one v2 list item, as it existed at read time.

    Carries the item's rank key and the EXACT raw stored string the read
    returned -- both are required for Phase 10's conditional writes
    (``set_if_value_equals()``/``delete_if_value_equals()`` require the
    raw stored string, not a re-serialization of the decoded value; see
    ``DbPropertyProtocol.delete_if_value_equals``).

    **Not wire-stable.** A rank is unique only within a list's current
    "generation": ``delete()`` followed by ``append()`` starts a brand new
    rank sequence, and ``fractional_indexing.generate_n_keys_between(None,
    None, n)`` is deterministic, so a fresh list's first rank is also
    ``a0`` -- identical to the deleted list's first rank. A handle from
    before the delete would silently address the wrong (new) item after
    one. Use a handle only within the request/process that read it,
    against the same list instance, and never persist or transmit one.

    ``__repr__`` deliberately omits the raw value -- printing it would
    invite treating this as a serializable snapshot rather than the
    single-use read receipt it is.
    """

    rank: str
    raw_value: str
    # True when the item spans body rows; ``bytes`` is then its encoded size
    # (read from the head, no body read). Informational: the CAS contract is
    # still rank + raw_value, and a spanned head's raw value is its envelope.
    spanned: bool = False
    bytes: int | None = None
    # The keyed-append hash of an item stored by ``append_once()`` (an HMAC
    # of its key, never the key itself), else ``None``.
    key_hash: str | None = None

    def __repr__(self) -> str:
        return f"ListItemHandle(rank={self.rank!r})"


@dataclass(frozen=True)
class AppendOnceResult:
    """What ``ListProperty.append_once()`` did.

    ``created`` is ``True`` when this call stored the item and ``False``
    when an item with the same key was already there (from an earlier call,
    or a concurrent one that won). ``item`` is the stored item either way --
    on a repeat, the FIRST call's item, whatever payload the repeat sent --
    and ``handle`` addresses it.
    """

    created: bool
    item: Any
    handle: ListItemHandle
    # True when this call is the one that announces the item to
    # subscribers: it made the metadata touch, and NotifyingListProperty
    # registers the diff. Usually equal to ``created``; a repeat that
    # finished a call which stopped before its key row is ``created=False``
    # and ``announced=True``. At most one call announces an item.
    announced: bool = field(default=False, compare=False)
    # For an announced repeat: the item's position when it was adopted (it
    # can sit anywhere in the list, so the diff is an insert there, not an
    # append). ``None`` for a creating call, whose item is the last.
    announce_index: int | None = field(default=None, compare=False)


class _KeyRow(NamedTuple):
    """A parsed key row of ``append_once()``."""

    rank: str
    tok: str
    by: str | None


@runtime_checkable
class ListStorage(Protocol):
    """Where a ``ListCore`` keeps its rows: a main partition (the meta row,
    the item heads) and a side partition (span bodies, key rows), chosen by
    ``side=True``.

    Contract: a fault raises ``DbError``. ``put`` and ``remove`` may answer
    ``False`` for a write that did not land (the property backend's
    ``set()`` does); the core raises its own ``RuntimeError`` for that. The
    conditional writes answer ``False`` when their condition did not hold.
    """

    @property
    def actor_id(self) -> str:
        """The actor whose rows these are (log and error text)."""
        ...

    @property
    def span_threshold(self) -> int | None:
        """The encoded size over which an item spans, or ``None``."""
        ...

    @property
    def item_max_bytes(self) -> int | None:
        """The encoded size over which an item is refused, or ``None``."""
        ...

    @property
    def key_scope(self) -> str:
        """What keyed-append hashes are keyed by."""
        ...

    @property
    def noun(self) -> str:
        """``"property"`` or ``"attribute"``: what error text calls a row."""
        ...

    @property
    def location(self) -> str:
        """Where the rows live, for error text (``"actor X"``)."""
        ...

    @property
    def remedy(self) -> str:
        """What an operator does about a damaged list here."""
        ...

    def side_key(self) -> str:
        """The side partition's key; ``ValueError`` when there is none."""
        ...

    def side_available(self) -> bool:
        """Whether this storage has a side partition."""
        ...

    def scalar_exists(self, name: str) -> bool:
        """Whether a non-list row named ``name`` exists."""
        ...

    def get(self, name: str, *, side: bool = False) -> str | None: ...

    def put(self, name: str, value: str, *, side: bool = False) -> bool | None: ...

    def remove(self, name: str, *, side: bool = False) -> bool | None: ...

    def get_range(
        self,
        lower: str,
        upper: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, str]: ...

    def get_prefix(
        self,
        prefix: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
        side: bool = False,
    ) -> dict[str, str]: ...

    def get_last_in_range(
        self, lower: str, upper: str, *, side: bool = False
    ) -> str | None: ...

    def create_if_not_exists(
        self, name: str, value: str, *, side: bool = False
    ) -> bool: ...

    def create_many_if_not_exists(
        self, rows: dict[str, str], *, side: bool = False
    ) -> set[str]: ...

    def set_if_value_equals(
        self, name: str, expected: str, value: str, *, side: bool = False
    ) -> bool: ...

    def delete_if_value_equals(
        self, name: str, value: str, *, side: bool = False
    ) -> bool: ...

    def batch_delete(self, names: list[str], *, side: bool = False) -> None: ...


class ListCore:
    """The v2 list format over a ``ListStorage``.

    Metadata lives at ``list:{name}-meta``; items at ``list:{name}-#{rank}``,
    fractional ("rank") keys that sort into item order. Length is counted
    from the rank-key range, never stored; ``get_metadata()["length"]`` is
    the advisory ``count_hint`` (see ``ListProperty`` for the drift bound,
    spanned items and the cost rules, which apply to every storage).

    A subclass fills the hooks: ``_on_stored_format()`` (a meta row whose
    format is not 2), ``_foreign_rows()`` (rows of another format in the
    list's range), ``_before_mutation()``, ``_default_metadata_no_db()``,
    ``_merge_length_delta()`` and ``_not_v2_error()``.
    """

    # What the rank-cap error tells the caller to do.
    _RANK_REMEDY = "run compact() to rebalance"

    def __init__(self, storage: ListStorage, name: str) -> None:
        self._storage = storage
        self.actor_id = storage.actor_id
        self.name = name
        self._meta_cache: dict[str, Any] | None = None
        # Truthy when there is a store to read; ListProperty without a
        # config sets None.
        self._db: Any = storage
        # Sorted list of rank-key suffixes (without the "list:{name}-#"
        # prefix), lazily loaded. None means "not loaded yet"; [] is a valid
        # loaded-and-empty state.
        self._v2_rank_cache: list[str] | None = None
        # A fresh (parsed, raw) meta-row read a mutation's dispatch just
        # took, for _save_metadata()'s FIRST compare-and-swap attempt to
        # consume instead of reading again -- see _dispatch_and_stash().
        # _NO_STASH (not None -- (None, None) is a valid stashed "row is
        # absent" reading) until a mutator sets it; every mutator sets it
        # fresh at its own top, so a stash left behind by an exception in a
        # PRIOR call can never be read without having just been overwritten.
        self._pending_meta_read: tuple[dict[str, Any] | None, str | None] | object = (
            _NO_STASH
        )
        # Per thread: True while a spanning head write's backend call, or the
        # read-back after it, is in flight (see _write_spanning /
        # _probed_write). Thread-local so an instance shared across threads
        # never reads another call's mark.
        self._probe = threading.local()

    # -- hooks a storage-specific subclass fills -------------------------

    def _on_stored_format(self, meta: dict[str, Any] | None) -> NoReturn:
        """A meta row whose ``format`` is not 2. The core reads format 2
        only."""
        fmt = (meta or {}).get("format", 1)
        raise ValueError(
            f"{self._storage.noun.capitalize()} list '{self.name}' "
            f"({self._storage.location}) stores format {fmt!r}; this "
            f"implementation reads format 2 only. {self._storage.remedy}"
        )

    def _not_v2_error(self, operation: str, *, hint: bool = True) -> Exception:
        """The error a format-2-only operation raises on another format."""
        del hint
        fmt = self._load_metadata().get("format", 1)
        return ValueError(
            f"{operation}() needs format 2 -- {self._storage.noun} list "
            f"'{self.name}' stores format {fmt!r}."
        )

    def _foreign_rows(self, *, sweep: bool) -> int:
        """Rows of another format in this list's range: deleted when
        ``sweep``, counted otherwise. The core knows none."""
        del sweep
        return 0

    def _before_mutation(self) -> None:
        """Runs before a mutation's dispatch (the property list's lazy
        migration)."""

    def _default_metadata_no_db(self) -> dict[str, Any]:
        """Metadata for an instance with no store."""
        return self._create_default_metadata_v2()

    def _merge_length_delta(
        self,
        meta: dict[str, Any],
        call_updates: dict[str, Any],
        length_delta: int,
        stored_format: int,
    ) -> None:
        """Merge a stored-``length`` delta (a format the core does not
        write)."""
        del meta, call_updates, length_delta, stored_format

    def _require_v2(self) -> None:
        """Refuse a list whose (cached) metadata says another format."""
        if not self._is_v2():
            self._on_stored_format(self._load_metadata())

    def _dispatch_v2(self) -> None:
        """A mutation's fresh dispatch: stash the meta row and refuse
        another format."""
        if self._dispatch_and_stash() != 2:
            stashed = self._pending_meta_read
            self._on_stored_format(stashed[0] if isinstance(stashed, tuple) else None)

    # -- the format -------------------------------------------------------

    def _get_meta_property_name(self) -> str:
        """Get the metadata property name."""
        return f"list:{self.name}-meta"

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

    def storage_format(self) -> int | str:
        """Which storage format this list uses: 1 (dense integers) or 2
        (fractional rank keys).

        One point read of the metadata row. Callers that only need the
        format -- the operator sweep scripts deciding what to do with a
        list -- should use this rather than ``verify()``, which fetches the
        actor's whole property partition to check integrity as well.
        """
        return self._format()

    def _dispatch_and_stash(self) -> int:
        """Fresh-read the meta row for a mutation about to dispatch on
        storage format, and stash ``(parsed, raw)`` for
        ``_save_metadata()``'s first compare-and-swap attempt to consume.

        Every public mutator (``append``/``insert``/``__setitem__``/
        ``__delitem__``/``pop``/``remove``) calls this INSTEAD OF
        ``self._is_v2()`` to decide which storage format to write into.
        Dispatching on the cache is row 9c: a ``ListProperty`` instance
        retained across a migration keeps believing v1 (or v2) long after
        the list's format changed, writes an item into the format the list
        no longer has, and that row becomes unreachable -- invisible to
        every reader of the CURRENT format, reported only as
        ``foreign_format_rows`` while ``verify()`` calls the list healthy.

        Stashing the read (rather than letting ``_save_metadata()`` read
        again after the item write) does two things a second, later read
        would not: it lets the metadata write's compare-and-swap condition
        on the SAME bytes the dispatch decision saw, so a format flip
        landing anywhere in the window between dispatch and the metadata
        touch is caught by the CAS (condition fails against the now-changed
        row -> retry -> re-read -> see the new format) instead of only
        a flip that happens to still be visible after the fact; and it
        keeps ``self._meta_cache`` untouched here, which matters because
        ``_save_metadata()``'s stale-cache WARNING compares
        ``self._meta_cache`` (what this instance believed) against a fresh
        read -- refreshing the cache at dispatch time would make the two
        always agree and silence that warning for exactly the scenario it
        exists to catch.

        Every mutator sets this stash fresh at its own top (overwriting
        whatever was there), so a stash left behind by an exception in a
        PRIOR, unrelated call can never be read without having just been
        replaced.

        Returns:
            1 or 2. A brand-new list (no stored row yet) dispatches as 2 --
            Phase 4's default for every list with no existing v1 rows.
        """
        parsed, raw = self._read_meta_row()
        self._pending_meta_read = (parsed, raw)
        if parsed is None:
            return 2
        try:
            return int(parsed.get("format", 1) or 1)
        except (TypeError, ValueError):
            return 1

    def _dispatch_saw_no_row(self) -> bool:
        """True if the ``_dispatch_and_stash()`` call at the top of this
        mutation found no meta row -- the stash it left is the ``(None,
        None)`` reading, not ``_NO_STASH`` (which means "no dispatch stash
        was taken at all" and never compares equal to a stashed tuple).
        The three creating v2 mutators (``append``/``extend``/``insert``)
        use this to decide whether to run ``_v2_create_meta_row()`` before
        their first item write.
        """
        return self._pending_meta_read == (None, None)

    def _limits(self) -> tuple[int | None, int | None]:
        """``(span_threshold, max_bytes)`` from the storage, each ``None``
        unless it is a positive ``int``. A test's ``Mock()`` config (whose
        attributes are ``Mock`` objects) therefore sets no limit."""

        def _accept(value: Any) -> int | None:
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
            return None

        return (
            _accept(self._storage.span_threshold),
            _accept(self._storage.item_max_bytes),
        )

    def _check_item_size(self, value_str: str, *, can_span: bool = False) -> bool:
        """Check an encoded item against the limits before anything is
        written, and say whether it must span.

        Over ``list_item_max_bytes``: refused on both formats. Over
        ``list_item_span_threshold`` (set by default only where the backend
        has a row cap): spans on v2 (``can_span=True``; returns ``True``)
        and is refused on v1, where the row would fail at the backend.

        Raises:
            ListItemTooLargeError: The item is over a limit it cannot meet.
        """
        span_threshold, max_bytes = self._limits()
        size = encoded_size(value_str)
        if max_bytes is not None and size > max_bytes:
            raise ListItemTooLargeError(
                self.name, size, max_bytes, "list_item_max_bytes"
            )
        if span_threshold is not None and size > span_threshold:
            if can_span:
                # A spanning write needs the side partition: refuse an actor
                # id that cannot have one now, before any row is written.
                self._aux()
                # Parts are cut on character boundaries, so a non-ASCII value
                # (the str() fallback) can need more parts than its size
                # suggests; count them now rather than fail mid-write.
                if not value_str.isascii():
                    part_bytes = min(SPAN_PART_BYTES, span_threshold)
                    try:
                        split_parts(value_str, part_bytes)
                    except ValueError:
                        raise ListItemTooLargeError(
                            self.name,
                            size,
                            span_threshold * MAX_PARTS,
                            f"more than {MAX_PARTS} body rows",
                        ) from None
                return True
            raise ListItemTooLargeError(
                self.name,
                size,
                span_threshold,
                "list_item_span_threshold, the largest item one row stores; "
                "a v1 list does not span, run migrate_to_v2()",
            )
        return False

    def check_item_size(self, item: Any) -> None:
        """Raise ``ListItemTooLargeError`` (or ``ValueError`` for an item
        carrying the reserved envelope key) if writing ``item`` to this list
        would be refused, without writing anything. For a caller that
        validates a whole batch before its first write, as the bulk REST
        update does."""
        self._check_item_size(self._encode_item(item), can_span=self._is_v2())

    def _decode_item(self, item_str: str) -> Any:
        try:
            return json.loads(item_str)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse list item for '{self.name}': {e}")
            return item_str

    def _encode_item(self, item: Any) -> str:
        """Encode an item for storage (``encode_item``): JSON, or the
        sanitised ``str()`` fallback. Refuses an item carrying the reserved
        envelope key with ``ValueError``, before any write."""
        return encode_item(item)

    # -- spanned items: the side partition ----------------------------

    def _aux(self) -> str:
        """This actor's side partition key. Raises ``ValueError`` for an
        actor id containing ``$`` (only a spanning write needs it)."""
        return self._storage.side_key()

    def _aux_or_none(self) -> str | None:
        """The side partition key, or ``None`` for an actor id containing
        ``$``, which can hold no spanned item. For the cleanup paths, which
        must keep working on such an actor."""
        try:
            return self._storage.side_key()
        except ValueError:
            return None

    @staticmethod
    def _names_matching(
        names: Any, prefix_len: int, matches: Callable[[str], bool]
    ) -> list[str]:
        """The names whose suffix after ``prefix_len`` passes ``matches``:
        the shape filter every enumeration of a shared byte range applies
        (a sibling list's rows can share the prefix)."""
        return [name for name in names if matches(name[prefix_len:])]

    def _aux_names(self, kind: str) -> list[str]:
        """This list's own ``$span-`` (``kind="span"``) or ``$key-``
        (``kind="key"``) row names in the side partition, shape-filtered.

        One keys-only prefix read. On DynamoDB a keys-only projection saves
        no capacity, so enumerating ``$span-`` rows costs every body byte:
        only ``delete()``, ``verify(spans=True)`` and
        ``compact(sweep_span_orphans=True)`` (and the residue sweeps) pay it.
        """
        aux = self._aux_or_none()
        if aux is None:
            return []
        if kind == "span":
            prefix, shape = span_prefix(self.name), SPAN_ROW_RE
        else:
            prefix, shape = key_prefix(self.name), KEY_ROW_RE
        rows = self._storage.get_prefix(side=True, prefix=prefix, keys_only=True)
        return self._names_matching(
            rows, len(prefix), lambda suffix: bool(shape.match(suffix))
        )

    def _delete_aux_rows(self, names: list[str]) -> None:
        """Unconditionally delete side-partition rows (a list being cleared
        or deleted). A fault propagates, like the head deletes beside it."""
        aux = self._aux_or_none()
        if names and aux is not None:
            self._storage.batch_delete(side=True, names=names)

    def _span_delete_bodies(self, span: SpanInfo | None) -> None:
        """Best-effort delete of one body generation (names derived, no
        read). Runs after a head write committed, so a fault only leaves an
        orphan generation for the aged sweep: logged at WARNING, never
        raised."""
        if span is None:
            return
        aux = self._aux_or_none()
        if aux is None:
            return
        try:
            self._storage.batch_delete(
                side=True, names=part_names(self.name, span.gen, span.parts)
            )
        except (  # folds DbError: best-effort cascade after commit; aged sweep repairs
            DbError,
            RuntimeError,
        ) as exc:
            logger.warning(
                "List '%s' (actor %s): could not delete body generation %s "
                "(%s) -- it is an orphan now; compact(sweep_span_orphans=True) "
                "removes it once it is older than %d s",
                self.name,
                self.actor_id,
                span.gen,
                exc,
                _SPAN_ORPHAN_MIN_AGE_SECONDS,
            )

    def _cascade(self, raw: str | None) -> None:
        """After a head was deleted or overwritten: delete the body
        generation its old raw value named, if any. Best-effort."""
        try:
            env = parse(raw)
        except EnvelopeError:
            return
        if env is not None:
            self._span_delete_bodies(env.span)

    def _write_bodies(self, value_str: str) -> SpanInfo:
        """Write ``value_str`` as a fresh body generation in the side
        partition and return its ``SpanInfo``. Parts are at most the span
        threshold (and ``SPAN_PART_BYTES``) each. On a fault, deletes the
        parts it wrote (best-effort) and re-raises."""
        span_threshold, _ = self._limits()
        part_bytes = min(SPAN_PART_BYTES, span_threshold or SPAN_PART_BYTES)
        parts = split_parts(value_str, part_bytes)
        gen = new_gen()
        span = SpanInfo(
            gen=gen,
            parts=len(parts),
            bytes=encoded_size(value_str),
            sha256=value_digest(value_str),
        )
        self._aux()
        names = part_names(self.name, gen, len(parts))
        try:
            for name, part in zip(names, parts, strict=True):
                if not self._storage.put(side=True, name=name, value=part):
                    raise RuntimeError(
                        f"list body write failed for '{self.name}' (gen {gen})"
                    )
        except BaseException:
            self._span_delete_bodies(span)
            raise
        return span

    def _make_head(
        self,
        value_str: str,
        span: SpanInfo | None,
        carry: Envelope | None = None,
    ) -> str:
        """The head row's raw value for an item encoded as ``value_str``.

        A spanned item is an envelope naming its bodies. An unspanned item
        is its plain JSON, unless ``carry`` (the envelope the head held
        before a rewrite) has fields that must survive -- a key, a writer
        token, or fields a later version added -- in which case it is an
        envelope with ``v``.
        """
        key = carry.key if carry is not None else None
        tok = carry.tok if carry is not None else None
        extra = dict(carry.extra) if carry is not None else {}
        if span is not None:
            return wrap(span=span, key=key, tok=tok, extra=extra)
        if key is None and tok is None and not extra:
            return value_str
        try:
            item: Any = json.loads(value_str)
        except json.JSONDecodeError:
            # The str() fallback for a value JSON cannot encode: the item
            # IS that string, as a plain row would decode it.
            item = value_str
        return wrap(value=item, key=key, tok=tok, extra=extra)

    def _write_spanning(
        self,
        value_str: str,
        spans: bool,
        head_write: Callable[[str], bool],
        *,
        carry: Envelope | None = None,
        head_name: str | None = None,
    ) -> tuple[bool, str]:
        """Bodies first, then the head through ``head_write`` (the caller's
        own conditional or unconditional write), once per call.

        Returns ``(landed, head)``. Deleting the previous generation is the
        caller's (it knows the old head).

        Bodies are deleted again only when the head is known not to have
        landed. ``head_write`` issues its backend write through
        ``_probed_write()``, which marks the call in flight:

        - A raise while a write is in flight (a timeout after the backend
          applied it) is an **unknown outcome**: the bodies are kept, an
          orphan for the aged sweep if the head did not land; deleting them
          would break a head that did.
        - A raise before any write was in flight (a fault reading the last
          rank, the rank cap, a collision storm) is **known not landed**:
          the bodies are deleted.
        - A ``False`` from a conditional write can be an SDK retry of a write
          that committed and then failed its own condition, so with
          ``head_name`` a spanned or keyed head is read back once: a row
          holding exactly this head (its bytes name a fresh generation, or
          carry its writer's token) means the write landed. A plain head cannot be told
          from another writer's identical value, so its ``False`` stands.
          Otherwise the bodies are deleted; a read-back that raises keeps
          them (unknown outcome).
        """
        # The unspanned head, built once. An envelope re-encodes the item
        # (non-ASCII text from the str() fallback becomes \uXXXX escapes), so
        # a carried key or token can push a head the size check passed over
        # the threshold: span it instead.
        plain_head: str | None = None
        if not spans:
            plain_head = self._make_head(value_str, None, carry)
            span_threshold, _ = self._limits()
            if (
                carry is not None
                and span_threshold is not None
                and encoded_size(plain_head) > span_threshold
            ):
                self._aux()
                spans = True
                plain_head = None
        span = self._write_bodies(value_str) if spans else None
        head = (
            plain_head
            if plain_head is not None
            else self._make_head(value_str, span, carry)
        )
        self._head_write_in_flight = False
        try:
            landed = head_write(head)
        except BaseException:
            if span is not None:
                if self._head_write_in_flight:
                    logger.warning(
                        "List '%s' (actor %s): a spanned head write failed "
                        "with an unknown outcome; its body generation %s is "
                        "kept (an orphan for the aged sweep if the head did "
                        "not land)",
                        self.name,
                        self.actor_id,
                        span.gen,
                    )
                else:
                    self._span_delete_bodies(span)
            raise
        finally:
            self._head_write_in_flight = False
        if not landed:
            # A read-back that faults here has an unknown outcome too: the
            # raise propagates and the bodies stay (the mark is set inside
            # _landed_anyway while it reads).
            if head_name is not None and self._landed_anyway(head_name, head):
                return True, head
            self._span_delete_bodies(span)
        return landed, head

    @property
    def _head_write_in_flight(self) -> bool:
        return bool(getattr(self._probe, "in_flight", False))

    @_head_write_in_flight.setter
    def _head_write_in_flight(self, value: bool) -> None:
        self._probe.in_flight = value

    def _probed_write(self, write: Callable[..., Any], **kwargs: Any) -> Any:
        """Call one backend head write, marking it in flight for
        ``_write_spanning()``: a raise that escapes while the mark is set
        has an unknown outcome."""
        self._head_write_in_flight = True
        result = write(**kwargs)
        self._head_write_in_flight = False
        return result

    def _landed_anyway(self, name: str, head: str) -> bool:
        """After a ``False`` from a conditional write of a spanned or keyed
        head: does the row hold exactly ``head`` (this call's write committed
        and a retry then failed its condition)? A spanned head names a fresh
        body generation and an ``append_once()`` head a fresh writer token,
        so their bytes are unique to the call. A rewrite of a keyed item
        carries its old token, so two concurrent identical rewrites have the
        same bytes: the loser then reads as landed, which is the intended end
        state (that value at that rank). A plain head cannot be told from a
        concurrent byte-identical write, so it never qualifies."""
        try:
            env = parse(head)
        except EnvelopeError:
            return False
        if env is None or (env.span is None and env.tok is None):
            return False
        # The read-back is part of the write's outcome: a raise from it is
        # an unknown outcome, so the in-flight mark stays set if it raises.
        self._head_write_in_flight = True
        holds = self._storage.get(name=name) == head
        self._head_write_in_flight = False
        return holds

    # -- spanned items: reading ----------------------------------------

    def _read_span(self, span: SpanInfo, *, consistent: bool) -> tuple[str | None, int]:
        """Read one body generation. Returns ``(value_str, found)``:
        ``value_str`` is ``None`` unless the rows are exactly
        ``p0000..p{parts-1}`` and join to ``span.bytes`` bytes; ``found``
        counts the rows that match the expected names."""
        aux = self._aux_or_none()
        if aux is None:
            return None, 0
        rows = self._storage.get_prefix(
            side=True,
            prefix=span_prefix(self.name, span.gen),
            consistent_read=consistent,
        )
        expected = part_names(self.name, span.gen, span.parts)
        found = sum(1 for name in expected if name in rows)
        if set(rows) != set(expected):
            return None, found
        joined = "".join(rows[name] for name in expected)
        if encoded_size(joined) != span.bytes:
            return None, found
        if span.sha256 is not None and value_digest(joined) != span.sha256:
            # Same length, wrong content (a body row restored from the wrong
            # backup, say): never returned as the item.
            return None, found
        return joined, found

    def _parse_head(self, raw: str, rank: str) -> Envelope | None:
        """``parse(raw)``, with a malformed envelope reported as the
        ``ListItemSpanError`` it is."""
        try:
            return parse(raw)
        except EnvelopeError as e:
            raise ListItemSpanError(
                self.name, rank, detail=f"has a malformed envelope ({e})"
            ) from None

    def _read_head(
        self, rank: str, *, consistent: bool = True
    ) -> tuple[str | None, Envelope | None]:
        """One point read of the head at ``rank``: ``(raw, envelope)``,
        ``(None, None)`` when the row is gone, ``(raw, None)`` for a plain
        item. Point reads are always strongly consistent on DynamoDB."""
        raw = self._storage.get(name=self._v2_item_name(rank))
        if raw is None:
            return None, None
        return raw, self._parse_head(raw, rank)

    def _read_head_tolerant(self, rank: str) -> tuple[str | None, Envelope | None]:
        """``_read_head()`` for a writer about to replace or delete the
        head: a malformed envelope reads as no envelope (nothing to carry,
        nothing to cascade) instead of raising, so the write can repair
        it."""
        raw = self._storage.get(name=self._v2_item_name(rank))
        if raw is None:
            return None, None
        try:
            return raw, parse(raw)
        except EnvelopeError:
            return raw, None

    def _handle_for(self, rank: str, raw: str) -> ListItemHandle:
        """A handle for a head. A malformed envelope gets a plain handle
        (``spanned=False``), so the item can still be deleted or replaced by
        handle -- the remedy ``ListItemSpanError`` names."""
        try:
            env = parse(raw)
        except EnvelopeError:
            return ListItemHandle(rank=rank, raw_value=raw)
        if env is None:
            return ListItemHandle(rank=rank, raw_value=raw)
        if env.span is not None:
            return ListItemHandle(
                rank=rank,
                raw_value=raw,
                spanned=True,
                bytes=env.span.bytes,
                key_hash=env.key,
            )
        return ListItemHandle(rank=rank, raw_value=raw, key_hash=env.key)

    def _resolve(self, raw: str, *, rank: str, consistent: bool) -> Any:
        """The item a v2 head's raw value stands for.

        A plain value decodes as JSON. An envelope with ``v`` returns it. A
        spanned envelope reads its body generation with the caller's
        consistency (bodies never change once written, so that is enough
        for the common path); on a short set it re-reads the head strongly,
        follows a changed generation, and reads the bodies strongly, at
        most ``_SPAN_MAX_REREADS`` times. Never returns a partial item.

        Raises:
            ListItemSpanError: The head is malformed, or after the re-reads
                it still names a generation whose bodies are short.
            _ItemGone: (an ``IndexError``) the head was deleted while it was
                being read; whole-list readers drop the item.
        """
        env = self._parse_head(raw, rank)
        if env is None:
            return self._decode_item(raw)
        if env.span is None:
            return env.value
        value_str, found = self._read_span(env.span, consistent=consistent)
        if value_str is not None:
            return self._decode_item(value_str)
        current = env.span
        for _ in range(_SPAN_MAX_REREADS):
            head_raw, head_env = self._read_head(rank, consistent=True)
            if head_raw is None:
                # Deleted under us (its delete cascaded the bodies): the
                # item is gone, the list is not damaged.
                raise _ItemGone(
                    f"List '{self.name}' item at rank {rank!r} was deleted "
                    f"while it was being read"
                )
            if head_env is None:
                return self._decode_item(head_raw)
            if head_env.span is None:
                return head_env.value
            same_gen = head_env.span.gen == current.gen
            current = head_env.span
            value_str, found = self._read_span(current, consistent=True)
            if value_str is not None:
                return self._decode_item(value_str)
            if same_gen:
                # The head still names this generation and a strong read
                # of it is short: really broken, not a reader race.
                break
        if found == current.parts:
            raise ListItemSpanError(
                self.name,
                rank,
                expected_parts=current.parts,
                found_parts=found,
                detail=(
                    f"has all {found} body row(s), but they do not match the "
                    f"size and digest its head records"
                ),
            )
        raise ListItemSpanError(
            self.name, rank, expected_parts=current.parts, found_parts=found
        )

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
        """Return the sorted rank-key cache, loading it (one whole-list
        range query -- `keys_only` saves bytes on PostgreSQL but no
        capacity on DynamoDB, see `DbPropertyProtocol.get_range`) if
        absent or `force`d. The returned list is the SAME object held in
        `self._v2_rank_cache` -- callers that insert/delete a single entry
        may mutate it in place instead of forcing a reload."""
        if self._v2_rank_cache is not None and not force:
            return self._v2_rank_cache
        lower, upper = self._v2_bounds()
        db = self._storage
        rows = db.get_range(lower=lower, upper=upper, keys_only=True)
        prefix_len = len(self._v2_item_prefix())
        self._v2_rank_cache = sorted(
            rank for name in rows if _v2_is_rank(rank := name[prefix_len:])
        )
        return self._v2_rank_cache

    def _v2_last_rank(self) -> str | None:
        """The current highest rank key, via one bytewise-greatest-row read
        (``get_last_in_range``) instead of a whole-list range query.

        Phase 9B: this is what ``append()``/``extend()`` use instead of
        ``_v2_ensure_rank_cache()`` -- an append only ever needs the LAST
        rank, and paying for the whole list to get it is the cost this
        release exists to remove. Always strongly consistent, same
        reasoning as ``_v2_ensure_rank_cache()``: a stale last rank here is
        a mid-list append by another route.

        This method itself deliberately does not read or write
        ``self._v2_rank_cache`` -- a cache built from a single-row read
        would be wrong to reuse for anything that needs the FULL rank list
        (``__setitem__``, ``insert()``, etc., which still call
        ``_v2_ensure_rank_cache()`` directly), and populating it here
        would just be a stale entry those callers would have to
        force-reread past anyway. Its callers (``_v2_append()``/
        ``_v2_extend()``) DO append their newly-created rank(s) onto
        ``self._v2_rank_cache`` afterwards, but only when it is already
        warm -- see those methods' docstrings.
        """
        lower, upper = self._v2_bounds()
        db = self._storage
        last_name = db.get_last_in_range(lower=lower, upper=upper)
        if last_name is None:
            return None
        prefix_len = len(self._v2_item_prefix())
        candidate_rank = last_name[prefix_len:]
        if _v2_is_rank(candidate_rank):
            return candidate_rank
        # The bytewise-greatest row in our byte range is not rank-shaped
        # -- a legacy '#'-named sibling list's row (its own item/meta
        # suffix, e.g. '-meta' or '-3', sorts inside OUR range because its
        # name starts with our list's name plus '#'). get_last_in_range()
        # has no notion of rank shape, so it happily returns that row.
        # Feeding it to fi.generate_key_between() raises FIError. Rare in
        # practice -- new list names have banned '#' since Phase 4, this
        # only triggers when a pre-Phase-4 sibling still exists -- so fall
        # back to the full, shape-filtered read rather than optimizing
        # for a case that no longer occurs on new lists.
        ranks = self._v2_ensure_rank_cache(force=True)
        return ranks[-1] if ranks else None

    def _v2_load_full(self, consistent: bool = True) -> list[tuple[str, str]]:
        """One full range query -> sorted (rank, raw_value) pairs. Also
        refreshes the rank-key cache as a side effect (the invariant that
        to_list()/__iter__/slice() cost exactly one query, and warm the
        cache for any __getitem__ calls that follow).

        ``consistent=False`` halves DynamoDB read capacity (see
        ``get_range``'s ``consistent_read`` docstring) at the cost of
        possibly not seeing a just-landed write -- including this
        instance's OWN. Callers that mutate and then immediately read back
        their own write (``_v2_remove()``, ``_v2_verify()``,
        ``_v2_compact()``) must not pass ``False`` here; only the public
        read methods that take an explicit ``consistent`` parameter do.
        """
        lower, upper = self._v2_bounds()
        db = self._storage
        rows = db.get_range(
            lower=lower,
            upper=upper,
            consistent_read=consistent,
        )
        prefix_len = len(self._v2_item_prefix())
        pairs = sorted(
            (rank, value)
            for name, value in rows.items()
            if _v2_is_rank(rank := name[prefix_len:])
        )
        self._v2_rank_cache = [rank for rank, _ in pairs]
        return pairs

    def _v2_to_list(self, consistent: bool = True) -> list[Any]:
        """Every item, resolved: one range read of the heads, plus one
        paged body read per spanned item (with the same consistency)."""
        return [
            item
            for _, _, item in self._resolve_pairs(
                self._v2_load_full(consistent=consistent), consistent=consistent
            )
        ]

    def _resolve_pairs(
        self, pairs: list[tuple[str, str]], *, consistent: bool
    ) -> list[tuple[str, str, Any]]:
        """``(rank, raw, item)`` for every head, resolved, dropping an item
        deleted while it was being read (``_ItemGone``)."""
        resolved: list[tuple[str, str, Any]] = []
        for rank, raw in pairs:
            try:
                item = self._resolve(raw, rank=rank, consistent=consistent)
            except _ItemGone:
                continue
            resolved.append((rank, raw, item))
        return resolved

    def _create_default_metadata_v2(self) -> dict[str, Any]:
        """Default metadata for a brand-new (v2) list. No `length` key --
        v2 has no authoritative stored length. `count_hint` is an ADVISORY
        item count -- deliberately not named `length`, so it can never be
        mistaken for v1's authoritative field -- maintained by mutations
        as a side effect so a count doesn't have to pay for a whole-list
        range query. See `get_metadata()` and `_v2_touch_metadata()` for
        the drift bound this carries."""
        now = datetime.now().isoformat()
        return {
            "format": 2,
            "created_at": now,
            "updated_at": now,
            "item_type": "json",
            "chunk_size": 1,
            "version": "1.0",
            "count_hint": 0,
            "description": "",
            "explanation": "",
            "format_ever_changed": False,
        }

    def _load_metadata(self) -> dict[str, Any]:
        """Load metadata from database, with caching."""
        if self._meta_cache is not None:
            return self._meta_cache

        if not self._db:
            return self._default_metadata_no_db()

        # Use fresh DB instance to avoid handle conflicts
        meta_db = self._storage
        meta_str = meta_db.get(name=self._get_meta_property_name())

        if meta_str is None:
            # No metadata exists - this is a new list, created directly in
            # the v2 (fractional rank key) format.
            for reserved in (_V2_RANK_MARKER, "$"):
                if reserved in self.name:
                    raise ValueError(
                        f"List name '{self.name}' cannot contain "
                        f"'{reserved}' -- reserved for internal storage "
                        f"keys (a list named '...{reserved}...' would put "
                        f"its rows inside another list's storage range)"
                    )

            # Check for a scalar collision - error if one exists
            if self._storage.scalar_exists(self.name):
                noun = self._storage.noun
                article = "an" if noun[:1] in "aeiou" else "a"
                raise ListNameTakenError(
                    f"Cannot create list '{self.name}': {article} {noun} with this name already exists. "
                    f"Delete the {noun} first or use a different name."
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

    def _read_meta_row(self) -> tuple[dict[str, Any] | None, str | None]:
        """The meta row as stored RIGHT NOW, bypassing the cache entirely --
        returns ``(parsed, raw)``, the decoded dict AND the exact raw stored
        string it came from.

        ``raw`` is what a compare-and-swap write conditions on: a
        conditional write's ``expected`` must be the RAW STORED STRING the
        caller read, not a re-serialization of the decoded value (see
        ``DbPropertyProtocol.set_if_value_equals``) -- round-tripping
        through decode/encode is not guaranteed byte-identical.

        ``(None, None)`` means the row is absent -- the list was never
        created, or another writer deleted it. Unparsable content raises,
        matching ``_load_metadata()``: self-healing over it orphans every
        item row.

        This is deliberately NOT ``_load_metadata()``. That method conflates
        "absent" with "a brand-new v2 list", which is the right default for
        a reader and the wrong one for a writer deciding whether it is
        allowed to recreate a row somebody else just deleted.
        """
        if not self._db:
            return None, None
        meta_db = self._storage
        meta_str = meta_db.get(name=self._get_meta_property_name())
        if meta_str is None:
            return None, None
        try:
            parsed = json.loads(meta_str)
        except (json.JSONDecodeError, TypeError) as e:
            raise ValueError(f"Unparsable metadata for list '{self.name}': {e}") from e
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Metadata for list '{self.name}' is not a JSON object "
                f"(got {type(parsed).__name__})"
            )
        return parsed, meta_str

    def _save_metadata(
        self,
        updates: dict[str, Any],
        *,
        remove: tuple[str, ...] = (),
        create_if_absent: bool = True,
        count_delta: int = 0,
        length_delta: int = 0,
        advisory: bool = False,
    ) -> None:
        """Merge ``updates`` into a FRESH read of the meta row and write it
        back, via a bounded compare-and-swap retry loop.

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

        The row this writes against is either the stash a mutator's
        ``_dispatch_and_stash()`` just took (consumed on this call's FIRST
        attempt only) or a fresh read (every retry, and any caller that
        skipped dispatch staging entirely -- ``set_description()``/
        ``set_explanation()``/``clear()``'s v1 length writers). Either way
        the row is fresh, never the cache.

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
                view, with an UNCONDITIONAL write -- there is no prior row to
                condition on, and no CAS retry applies to this branch.
                ``False`` skips the write entirely: for the v1 length
                writers, an absent row means a concurrent ``delete()`` won,
                and merging a stale length would resurrect the list.
            count_delta: merged onto the freshly-read stored ``count_hint``
                under the SAME read the compare-and-swap conditions on --
                for a v2 mutation that does not know the list's true count
                (append()/insert(), which reuse a possibly-stale rank
                cache). Ignored under v1, and ignored when ``count_hint``
                isn't present in ``updates`` and isn't an int in the stored
                row (a pre-3.14 list with no hint yet -- the next
                rank-counting mutation establishes one instead of guessing
                at a delta).
            length_delta: the v1 counterpart of ``count_delta`` -- merged
                onto the freshly-read stored ``length`` under the same
                read, instead of v1 ``append()``/``insert()`` computing an
                ABSOLUTE new length from ``len(self)`` (which reads
                ``_meta_cache``, a value a retained instance can hold
                stale across a concurrent writer's mutation). Ignored
                under v2 (v2 has no stored ``length``), and ignored when
                ``length`` isn't present in ``updates`` and isn't an int
                in the stored row.
            advisory: ``True`` ONLY for the v2 metadata touch
                (``updated_at``/``count_hint`` on an ALREADY-EXISTING row,
                after the item row it is recording has already been
                committed). Exhausting the (smaller) advisory retry bound
                logs one WARNING and returns instead of raising -- the
                caller's mutation already succeeded; the missed count-hint
                update is Phase 5's documented drift bound's third term,
                repaired by the next rank-counting mutation or
                ``compact()``. Does NOT apply to any write carrying a
                semantic field (``format``, v1's ``length``) -- there the
                metadata write IS the operation, so those callers must pass
                ``advisory=False`` (the default). A genuine backend fault
                under ``advisory=True`` (on either the CAS write or the
                row-creation branch above) is not swallowed here -- see
                ``_v2_touch_metadata()``, the only ``advisory=True`` caller,
                for where that is caught.

        Raises:
            ListMetadataContentionError: the retry bound was exhausted on a
                non-advisory write -- the row stayed under contention
                through every attempt this call was willing to make.
        """
        max_attempts = (
            _METADATA_CAS_ADVISORY_MAX_ATTEMPTS
            if advisory
            else _METADATA_CAS_MAX_ATTEMPTS
        )
        warned_stale_cache = False

        for attempt in range(max_attempts):
            if attempt == 0 and self._pending_meta_read is not _NO_STASH:
                stored, expected_raw = self._pending_meta_read  # type: ignore[misc]
                self._pending_meta_read = _NO_STASH
            else:
                stored, expected_raw = self._read_meta_row()

            if stored is None:
                if not create_if_absent:
                    logger.info(
                        f"List '{self.name}' (actor {self.actor_id}): metadata "
                        f"row is gone (deleted concurrently) -- skipping the "
                        f"metadata update rather than recreating the list"
                    )
                    # Drop BOTH caches, not just the metadata one: whatever
                    # this instance believes about the list is describing
                    # something that no longer exists.
                    self._invalidate_cache()
                    return
                # No stored state to preserve, so nothing can be reverted by
                # falling back to what this instance knows -- and if this
                # instance is holding a cache from BEFORE the row vanished
                # (its own earlier read, or a stale v1 belief), that cache
                # describes a list that no longer exists and must not seed
                # the one replacing it: a cached v1 dict would recreate the
                # row with a stale `length` and no `format` key while the
                # item this call is recording just landed in a v2-shaped
                # row, producing a row that claims v1 with a v2 item under
                # it -- corruption, not resurrection. Drop the cache first
                # so _load_metadata() takes its own absent-row path and
                # returns a clean v2 default. It also applies the '#'-name
                # ban and the property-name collision check that creating a
                # list must go through. UNCONDITIONAL write: there is no
                # prior row to CAS against.
                self._invalidate_cache()
                meta = dict(self._load_metadata())
                new_format = int(meta.get("format", 1) or 1)
                call_updates = (
                    {k: v for k, v in updates.items() if k != "length"}
                    if new_format == 2
                    else updates
                )
                meta.update(call_updates)
                # A list's first-ever mutation goes through here too (a
                # brand-new row has nothing to be absent-because-deleted
                # about) -- append()/insert()'s count_delta must land on
                # the freshly-created default (count_hint: 0) the same way
                # it lands on an existing row below, or the count silently
                # drops on every list's very first append().
                if count_delta and new_format == 2 and "count_hint" not in call_updates:
                    current_hint = meta.get("count_hint")
                    if isinstance(current_hint, int):
                        meta["count_hint"] = max(0, current_hint + count_delta)
                self._merge_length_delta(meta, call_updates, length_delta, new_format)
                for field in remove:
                    meta.pop(field, None)
                self._replace_metadata(meta, expected_raw=None)
                return

            stored_format = int(stored.get("format", 1) or 1)

            # Did this instance dispatch the mutation it is now recording
            # against a format the list no longer has?
            #
            # The write itself is already done by the time we get here --
            # append() stores the item row, then calls this -- so an item
            # written by a stale v1 instance into a list that is now v2 is
            # sitting in a v1-shaped row that no v2 reader will ever return.
            # It is not lost data, it is unreachable data, and until this
            # warning existed the only trace was a DEBUG line and a
            # `foreign_format_rows` count that verify() reports while
            # calling the list HEALTHY.
            #
            # Self-limiting: the write below caches the merged row on
            # success, so this instance's NEXT mutation dispatches
            # correctly. One warning per retained instance's stale write,
            # which is why this warns rather than raises -- the caller's
            # operation succeeded, it just landed somewhere nothing reads.
            # Found by consumer verification against 3.13.0 GA. Emitted at
            # most once per _save_metadata() call (attempt 0's read only) --
            # self._meta_cache does not change between retries, so
            # re-comparing it against each retry's newer read would just
            # repeat the same finding.
            if not warned_stale_cache and self._meta_cache is not None:
                believed_format = int(self._meta_cache.get("format", 1) or 1)
                if believed_format != stored_format:
                    warned_stale_cache = True
                    logger.warning(
                        "List '%s' (actor %s): this instance believed the "
                        "storage format was v%d but the stored row says v%d "
                        "-- it was migrated by someone else while this "
                        "instance was held. Any item this operation wrote "
                        "went into a v%d-shaped row that v%d readers do not "
                        "see; verify() will still report the list healthy, "
                        "and the row shows up only as foreign_format_rows. "
                        "Re-issue the write. This instance self-corrects "
                        "from here.",
                        self.name,
                        self.actor_id,
                        believed_format,
                        stored_format,
                        believed_format,
                        stored_format,
                    )

            meta = dict(stored)
            call_updates = updates
            if stored_format == 2:
                call_updates = {k: v for k, v in updates.items() if k != "length"}
            meta.update(call_updates)
            if count_delta and stored_format == 2 and "count_hint" not in call_updates:
                current_hint = meta.get("count_hint")
                if isinstance(current_hint, int):
                    meta["count_hint"] = max(0, current_hint + count_delta)
            self._merge_length_delta(meta, call_updates, length_delta, stored_format)
            for field in remove:
                meta.pop(field, None)

            if self._replace_metadata(meta, expected_raw=expected_raw):
                return

            # Lost the compare-and-swap: another writer changed the row
            # between our read and this write. Re-resolve on the next
            # attempt rather than blindly retrying the same stale merge.
            if attempt < max_attempts - 1:
                backoff = random.uniform(
                    0, _METADATA_CAS_BACKOFF_BASE_SECONDS * (2**attempt)
                )
                if backoff:
                    time.sleep(backoff)

        if advisory:
            logger.warning(
                "List '%s' (actor %s): advisory metadata touch (updated_at/"
                "count_hint) exhausted %d compare-and-swap attempts under "
                "sustained contention -- the mutation this touch was "
                "recording already succeeded. The missed update self-"
                "corrects at the next rank-counting mutation or compact().",
                self.name,
                self.actor_id,
                max_attempts,
            )
            return
        raise ListMetadataContentionError(self.name, self.actor_id)

    def _replace_metadata(
        self, meta: dict[str, Any], *, expected_raw: str | None = None
    ) -> bool:
        """Write ``meta`` wholesale and cache it.

        Two kinds of caller use this: a deliberate reset (``clear()``,
        which resets description/explanation by design) or migration's
        format flip -- both pass ``expected_raw=None`` (unconditional
        write, the same last-writer-wins behaviour this method has always
        had) -- and ``_save_metadata()``'s compare-and-swap retry loop,
        which passes the raw bytes its current attempt read. Everything
        else goes through ``_save_metadata()`` -- see its docstring for
        what writing a cached dict back costs.

        Args:
            meta: the full metadata dict to write (derived from a read the
                caller already performed itself, never from the cache).
            expected_raw: ``None`` writes unconditionally. A raw JSON
                string conditions the write via
                ``set_if_value_equals(expected=expected_raw)`` -- succeeds
                only if the row still holds exactly those bytes.

        Returns:
            ``True`` if the write landed and ``self._meta_cache`` was
            updated. ``False`` only when ``expected_raw`` was given and the
            row no longer holds those bytes -- nothing was written, the
            cache is untouched, and the caller (``_save_metadata()``) is
            expected to re-read and retry, not to treat this as failure.

        Raises:
            RuntimeError: an unconditional write reports a fault as
                ``False`` (PostgreSQL's ``set``).
            DbError: an unconditional write raises directly on a fault
                (DynamoDB's ``set``), or a conditional write faults on
                either backend (``set_if_value_equals``).
        """
        meta["updated_at"] = datetime.now().isoformat()

        if self._db:
            meta_property_name = self._get_meta_property_name()
            meta_json = json.dumps(meta)
            # Use fresh DB instance to avoid handle conflicts
            meta_db = self._storage
            if expected_raw is None:
                if not meta_db.put(name=meta_property_name, value=meta_json):
                    raise RuntimeError(f"list metadata write failed for '{self.name}'")
            else:
                if not meta_db.set_if_value_equals(
                    name=meta_property_name,
                    expected=expected_raw,
                    value=meta_json,
                ):
                    return False

        self._meta_cache = meta
        return True

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

    def _v2_pairs_from_rows(self, rows: dict[str, Any]) -> list[tuple[str, str]]:
        """This list's ``(rank, raw)`` heads from a dump, in order."""
        prefix = self._v2_item_prefix()
        prefix_len = len(prefix)
        return sorted(
            (rank, value)
            for name, value in rows.items()
            if name.startswith(prefix) and _v2_is_rank(rank := name[prefix_len:])
        )

    def _unresolved_or_item(self, rank: str, raw: str) -> Any:
        """A head's item without reading bodies: ``UNRESOLVED`` for a
        spanned item or a malformed envelope (unreadable; ``item_at()``
        raises ``ListItemSpanError`` for it), the item otherwise."""
        try:
            env = parse(raw)
        except EnvelopeError:
            return UNRESOLVED
        if env is None:
            return self._decode_item(raw)
        if env.span is not None:
            return UNRESOLVED
        return env.value

    def sizes_from_rows(self, rows: dict[str, Any]) -> list[int]:
        """Each item's encoded size, in list order, from a dump -- no body
        read: a spanned head carries its ``bytes``, a plain item's size is
        its raw value's. For the metadata GET, which reports sizes only."""
        self._require_v2()
        sizes: list[int] = []
        for rank, raw in self._v2_pairs_from_rows(rows):
            env = self._parse_head(raw, rank)
            if env is not None and env.span is not None:
                sizes.append(env.span.bytes)
            elif env is not None:
                sizes.append(encoded_size(json.dumps(env.value)))
            else:
                sizes.append(encoded_size(raw))
        return sizes

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
        or destroying — the wrong item. That re-read is a whole-list range
        query, so a `for i in range(len(lst))` loop over `lst[i]` costs
        one whole-list query PER ITEM under v2 -- O(n) total, not a fixed
        two-query factor -- even after priming.

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

    def to_list_from_rows(
        self, rows: dict[str, Any], *, resolve: bool = True
    ) -> list[Any]:
        """Like to_list(), but served from a pre-fetched name->value mapping.

        The heads come from `rows` (no fallback reads -- there is no
        separate "recorded length" a v2 list could disagree with). A dump
        never holds a spanned item's body rows (they live in the actor's
        side partition), so each spanned item costs one paged body read,
        eventually consistent first, matching the dump. With
        ``resolve=False`` no body is read and a spanned item's slot holds
        ``UNRESOLVED``.

        Raises:
            ListItemSpanError: a spanned item's bodies are broken.
        """
        self._require_v2()
        pairs = self._v2_pairs_from_rows(rows)
        self._v2_rank_cache = [rank for rank, _ in pairs]
        if not resolve:
            return [self._unresolved_or_item(rank, value) for rank, value in pairs]
        return [item for _, _, item in self._resolve_pairs(pairs, consistent=False)]

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
        self._require_v2()
        hint = meta.get("count_hint")
        # A v2 list whose metadata predates this release has no hint
        # yet -- count once (the first rank-counting mutation then
        # establishes one) rather than silently reporting 0.
        length = hint if isinstance(hint, int) else len(self)
        return {
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", ""),
            "version": meta.get("version", ""),
            "item_type": meta.get("item_type", ""),
            "chunk_size": meta.get("chunk_size", 1),
            "length": length,
        }

    def __len__(self) -> int:
        """Get list length, counted from the (cached) rank-key range."""
        self._require_v2()
        return len(self._v2_ensure_rank_cache())

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
        item_db = self._storage
        item_str = item_db.get(name=self._v2_item_name(rank))

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
            item_db = self._storage
            item_str = item_db.get(name=self._v2_item_name(rank))
            if item_str is None:
                raise ListCorruptionError(self.name, index)

        return self._resolve(item_str, rank=rank, consistent=True)

    def __getitem__(self, index: int) -> Any:
        """Get item by index, loading from database.

        Raises:
            IndexError: ``index`` is outside ``[0, len(self))``.
            ListCorruptionError: the row vanished twice in a row; a missing
                row under concurrent mutation is resolved by one cache
                reload (see ``_v2_getitem``) rather than raised.
        """
        self._require_v2()
        return self._v2_getitem(index)

    def _v2_touch_metadata(
        self, count: int | None = None, count_delta: int = 0
    ) -> None:
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

        Besides ``updated_at`` (always moved), this also maintains the
        advisory ``count_hint``:

        - ``count``: this mutation holds a rank cache it knows is CURRENT
          (it forced a fresh read before mutating, and mutated the same
          list object in place) -- write it as the counted truth.
          ``__setitem__`` passes this too, even though it doesn't change
          the count: writing the true count is strictly better than
          leaving a possibly-stale one, and it's what makes the
          "``__setitem__`` leaves the hint unchanged" contract hold in the
          normal case (no concurrent writer) without a special case here.
        - ``count_delta``: this mutation does NOT know the list's true
          count (it may have reused a stale rank cache) -- merge the delta
          onto whatever is currently stored, under the same fresh read
          ``_save_metadata()`` already performs. This is append()/
          insert()'s path, deliberately, so the mechanism does not have to
          change when Phase 9B removes their rank cache entirely.
        - neither: the stored hint is preserved as-is (not included in
          ``updates``, so ``_save_metadata()``'s merge leaves it alone).

        That is what keeps a v2 mutation from carrying a cached ``format``
        back to storage -- including the reverse of the migration case, a
        stale format-2 cache over storage another process has downgraded
        to v1.

        A list comes into existence through ``_v2_create_meta_row()``,
        called by ``append()``/``extend()``/``insert()`` before their first
        item write when ``_dispatch_saw_no_row()`` is true -- not through
        this touch. This method's own row-creation branch (inside
        ``_save_metadata()``, reached when the meta row is absent) is the
        FALLBACK for a row that vanished between the two writes -- a
        ``delete()`` racing the first mutation's create-then-item-write
        window -- or for a mutation landing against orphan rows left by a
        pre-3.14.7 fault. Either way it still creates the row rather than
        skip the write the way the v1 length writers do on an absent row:
        the asymmetry is real and deliberate, and the result -- a
        ``delete()`` racing a v2 mutation leaves a one-item list rather
        than nothing -- is the same answer appending to a never-created
        list gives.

        Always passes ``advisory=True`` to ``_save_metadata()``: every
        caller of this method is a v2 mutator that has ALREADY written (or
        deleted) the item row it is now recording -- that write is
        committed regardless of what happens to this touch. Contention
        that exhausts the (smaller) advisory retry bound, AND a genuine
        backend fault (``DbError``, or PostgreSQL's ``RuntimeError`` on
        the row-creation branch), are both swallowed with one WARNING
        rather than raised, so the mutation the caller invoked still
        returns success. A ``ValueError`` (unparsable meta row, or the
        row-creation branch's ``#``-name/scalar-collision check) is
        semantic corruption, not a fault, and is deliberately let through.
        """
        updates: dict[str, Any] = {}
        if count is not None:
            updates["count_hint"] = count
        try:
            self._save_metadata(
                updates,
                count_delta=0 if count is not None else count_delta,
                advisory=True,
            )
        except (  # folds DbError: hint touch only; recount repairs
            DbError,
            RuntimeError,
        ) as exc:
            # ListMetadataContentionError subclasses RuntimeError, so this
            # clause WOULD swallow it -- but _save_metadata() never raises
            # it under advisory=True: its exhaustion path returns after
            # one WARNING when advisory is set, and the raise sits behind
            # that return. If that invariant ever changes, the outcome
            # here (swallow: the item write is already committed) is still
            # the right one, but the WARNING below would mislabel
            # contention as a backend fault -- catch it separately then.
            logger.warning(
                "List '%s' (actor %s): advisory metadata touch hit a "
                "backend fault after the item write committed (%s) -- the "
                "mutation this touch was recording already succeeded. "
                "count_hint may be off by one until the next "
                "rank-counting mutation or compact(); if the meta row was "
                "being recreated, it may be absent until the next "
                "mutation.",
                self.name,
                self.actor_id,
                exc,
                exc_info=True,
            )

    def _v2_setitem(self, index: int, value: Any) -> None:
        value_str = self._encode_item(value)
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

        # Size check after the bounds check (as v1 does), before any write.
        spans = self._check_item_size(value_str, can_span=True)
        rank = ranks[index]
        name = self._v2_item_name(rank)
        # One point read of the head before the unconditional write: its
        # envelope names the body generation to delete afterwards and the
        # fields (key, token, unknown ones) the rewrite carries across.
        # Positional writes gain this one item read; they stay
        # unconditional (a concurrent update between this read and the
        # write leaves the other writer's generation as an orphan, never a
        # broken span).
        old_raw, old_env = self._read_head_tolerant(rank)

        def head_write(head: str) -> bool:
            if not self._probed_write(
                self._storage.put,
                name=name,
                value=head,
            ):
                raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")
            return True

        self._write_spanning(value_str, spans, head_write, carry=old_env)
        self._cascade(old_raw)
        self._v2_touch_metadata(count=len(ranks))

    def __setitem__(self, index: int, value: Any) -> None:
        """Set item at index."""
        self._before_mutation()
        self._dispatch_v2()
        self._v2_setitem(index, value)

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
        # One point read: the envelope names the body generation the
        # delete cascades to (positional writes gain one item read).
        old_raw, _ = self._read_head_tolerant(rank)
        item_db = self._storage
        if not item_db.remove(name=self._v2_item_name(rank)):
            raise RuntimeError(f"list item write failed for '{self.name}'[{index}]")
        self._cascade(old_raw)
        self._retire_key_row(old_raw)

        # A single row delete IS the whole operation under v2 -- no shift
        # loop. Keep the cache consistent with the write we just made
        # (mutating the same list object _v2_ensure_rank_cache() returned).
        del ranks[index]
        self._v2_touch_metadata(count=len(ranks))

    def __delitem__(self, index: int) -> None:
        """Delete item at index and shift remaining items."""
        self._before_mutation()
        self._dispatch_v2()
        self._v2_delitem(index)

    def __iter__(self) -> Iterator[Any]:
        """Return an iterator over the list: one full range query up front
        (``_v2_to_list()``), then a plain list iterator -- per-item
        ``__getitem__`` calls in a loop would cost one query per item."""
        self._require_v2()
        return iter(self._v2_to_list())

    def _v2_create_meta_row(self) -> None:
        """A list's first mutation creates its meta row BEFORE its first
        item row, conditionally. Called by ``_v2_append()``/
        ``_v2_extend()``/``_v2_insert()`` only when
        ``_dispatch_saw_no_row()`` is true, so an item row can no longer
        exist without a meta row through this path -- except when a
        concurrent ``delete()`` races the first mutation and the
        recreation write (inside ``_v2_touch_metadata()``'s row-creation
        branch) also faults, which is logged and reported by ``verify()``.

        ::

            append()/extend()/insert() on a list whose dispatch read found NO meta row
            ──────────────────────────────────────────────────────────────────────────
             _dispatch_and_stash()        read meta ──► (None, None) stashed
                    │
                    ▼
             _v2_create_meta_row()        _load_metadata() ── ValueError ('#' name,
                    │                     (2 reads)             scalar collision) ► raise, nothing written
                    │                                        ── DbError            ► raise, nothing written
                    │
                    ├─ create_if_not_exists(meta) ── DbError  ► raise, nothing written            [exit 1]
                    │        ├─ True  ► stash = (meta, bytes just written)
                    │        └─ False ► re-read: v2 row     ► stash = (row, raw); continue
                    │                            absent / v1 ► ListMetadataContentionError(detail=…)
                    │                                          nothing written                    [exit 2]
                    ▼
             item write  create_if_not_exists(list:{name}-#rank)
                    │        └─ DbError ► raise; meta row exists: list is EMPTY and VISIBLE      [exit 3]
                    ▼
             _v2_touch_metadata()   try: _save_metadata(advisory=True)
                    │                 attempt 0 CASes on the stashed bytes
                    │                 ├─ CAS exhausted         ► WARNING, return (hint drift +1)
                    │                 ├─ DbError/RuntimeError  ► WARNING, return (hint drift +1)  [exit 4]
                    │                 │    (creation branch only if a delete() swept the row
                    │                 │     between create and item write: residual orphan)
                    │                 └─ ValueError            ► raise (corruption stays visible)
                    ▼
             return   the item write is committed; nothing after it can fail the call

        The re-stash on a successful create is load-bearing: without it,
        the touch's attempt 0 would consume the ``(None, None)`` stash
        ``_dispatch_and_stash()`` left, take the creation branch, and
        overwrite the row just created with an unconditional ``set`` --
        defeating the CAS and any concurrent writer's update. With it,
        attempt 0 conditions on the exact bytes just written.

        ``_invalidate_cache()`` runs first, for the same reason the
        creation branch inside ``_save_metadata()`` does it: a retained
        instance's stale v1 (or otherwise stale) cache must not seed the
        row. ``_load_metadata()`` then takes its absent-row path and
        returns a clean v2 default (``_create_default_metadata_v2()``,
        ``count_hint: 0``, ``format_ever_changed: False``) -- which is
        also where the ``#``-name ban and the scalar-property-collision
        check run, before any write.
        """
        self._invalidate_cache()
        meta = dict(self._load_metadata())
        meta_json = json.dumps(meta)
        meta_db = self._storage
        if meta_db.create_if_not_exists(
            name=self._get_meta_property_name(), value=meta_json
        ):
            self._meta_cache = meta
            self._pending_meta_read = (meta, meta_json)
            return
        # Lost the create: another writer made the row in the window.
        parsed, raw = self._read_meta_row()
        if parsed is not None and int(parsed.get("format", 1) or 1) == 2:
            self._meta_cache = parsed
            self._pending_meta_read = (parsed, raw)
            return
        raise ListMetadataContentionError(
            self.name,
            self.actor_id,
            detail="metadata row changed under a first-mutation create",
        )

    def _v2_append(self, item: Any) -> None:
        """Phase 9B: one ``get_last_in_range`` read (a single item's read
        capacity) instead of ``_v2_ensure_rank_cache()``'s whole-list range
        query -- append only ever needs the last rank. The collision loop
        is UNCHANGED, which is what keeps the race behaviour byte-for-byte
        identical to the rank-cache version: rank generation is
        deterministic, so two appenders that read the same last rank
        produce the same candidate, ``create_if_not_exists`` rejects the
        loser, and the retry re-reads the (now current) last rank.

        On success, appends the new rank to ``self._v2_rank_cache`` IF that
        cache is already warm (not ``None``) -- never loads a cold one,
        which would defeat the whole point of using
        ``get_last_in_range()`` here. This is not optional bookkeeping: a
        caller that reuses the SAME instance across several operations
        (``handlers/properties.py``'s bulk-update pass, which calls
        ``len(list_prop)`` then loops ``list_prop.append(None)`` while
        re-checking ``len()``) depends on ``len()`` reflecting each
        append immediately. Before this, `append()` maintained the cache
        via ``_v2_ensure_rank_cache()``'s in-place mutation; dropping that
        without a replacement left ``len()`` reading a cache that never
        advanced, so ``while len(list_prop) <= index: list_prop.append(
        None)`` never terminated -- found via a hang in
        ``tests/integration/test_post_properties.py``.

        On a list whose dispatch found no meta row, creates it first via
        ``_v2_create_meta_row()`` -- see that method's docstring for the
        full write-order diagram.
        """
        value_str = self._encode_item(item)
        spans = self._check_item_size(value_str, can_span=True)
        if self._dispatch_saw_no_row():
            self._v2_create_meta_row()
        landed: list[str] = []

        def head_write(head: str) -> bool:
            landed.append(self._v2_write_item_at_new_rank(head))
            return True

        # Bodies (if the item spans) are written once, before the rank loop;
        # a loop that gives up before or between writes deletes them again
        # (see _write_spanning).
        self._write_spanning(value_str, spans, head_write)
        if self._v2_rank_cache is not None:
            self._v2_rank_cache.append(landed[0])
        self._v2_touch_metadata(count_delta=1)

    def _v2_write_item_at_new_rank(self, head: str) -> str:
        """Write ``head`` at a fresh rank after the current last one, and
        return the rank.

        The collision loop ``append()`` has always used: rank generation is
        deterministic, so two appenders that read the same last rank produce
        the same candidate, ``create_if_not_exists`` rejects the loser, and
        the retry re-reads the (now current) last rank. A ``False`` for a
        spanned or keyed head is read back first (``_landed_anyway``): a
        row holding exactly ``head`` is this call's own write.

        Raises:
            RuntimeError: Too many collisions, or the rank grew past the cap.
        """
        last = self._v2_last_rank()
        for attempt in range(_V2_MAX_RANK_RETRIES):
            candidate = fi.generate_key_between(last, None)
            if len(candidate) > _V2_RANK_MAX_LEN:
                raise ListRankExhaustedError(
                    f"list '{self.name}' rank key exceeded {_V2_RANK_MAX_LEN} "
                    f"chars -- {self._RANK_REMEDY}"
                )
            item_db = self._storage
            name = self._v2_item_name(candidate)
            if self._probed_write(
                item_db.create_if_not_exists,
                name=name,
                value=head,
            ) or self._landed_anyway(name, head):
                return candidate
            # Collision: another writer took this rank between our read
            # and the write. Re-read the last rank for the next attempt --
            # NOT `candidate` itself, since the collision means someone
            # else's row is now there, not necessarily the new last one.
            if attempt < _V2_MAX_RANK_RETRIES - 1:
                last = self._v2_last_rank()
        raise RuntimeError(
            f"list '{self.name}' append: too many rank collisions, retry later"
        )

    def append(self, item: Any) -> None:
        """Add item to end of list."""
        if not self._db:
            raise RuntimeError("No database connection available")

        self._before_mutation()
        self._dispatch_v2()
        self._v2_append(item)

    # -- idempotent appends ----------------------------------------------

    @staticmethod
    def _validate_append_key(key: Any) -> None:
        """Refuse a key ``append_once()`` cannot use, before any read or
        write. The message never carries the key."""
        if not isinstance(key, str):
            raise ValueError("append_once() key must be a str")
        if not key:
            raise ValueError("append_once() key must not be empty")
        if len(key) > _APPEND_ONCE_KEY_MAX_LEN:
            raise ValueError(
                f"append_once() key must be at most {_APPEND_ONCE_KEY_MAX_LEN} "
                f"characters"
            )
        if any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in key):
            raise ValueError("append_once() key must not contain control characters")
        try:
            key.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("append_once() key must be valid Unicode text") from None

    def _key_hash(self, key: str) -> str:
        """The key's stored form: HMAC-SHA256 keyed by the actor id, hex.
        Separates actors (the same key hashes differently on each); the actor
        id is public, so it does not make a guessable key safe."""
        return hmac.new(
            self._storage.key_scope.encode("utf-8"), key.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _key_row(self, key_hash: str) -> str:
        return key_row_name(self.name, key_hash)

    @staticmethod
    def _key_row_value(rank: str, tok: str, by: str) -> str:
        """A key row: the item's rank (a hint), its head's writer token (the
        authority) and the token of the call that wrote the row (``by``,
        which says whether a writer's own create landed or another call
        adopted its head)."""
        return json.dumps({"rank": rank, "tok": tok, "by": by})

    @staticmethod
    def _parse_key_row(raw: str | None) -> _KeyRow | None:
        """A key row's fields, or ``None`` when it is absent or malformed (a
        malformed row is treated as dangling)."""
        if raw is None:
            return None
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(obj, dict):
            return None
        rank, tok, by = obj.get("rank"), obj.get("tok"), obj.get("by")
        if not isinstance(rank, str) or not isinstance(tok, str):
            return None
        return _KeyRow(rank=rank, tok=tok, by=by if isinstance(by, str) else None)

    @staticmethod
    def _in_flight(tok: str | None) -> bool:
        """True for a writer token younger than ``_KEYED_IN_FLIGHT_SECONDS``:
        its ``append_once()`` call may still be running, so the maintenance
        paths neither report nor repair what it has written so far. A token
        of another shape counts as old."""
        if not tok or not GEN_RE.match(tok):
            return False
        # A token minted more than the window in the future (a host clock
        # far ahead) counts as old rather than hiding damage until then.
        return (
            -_KEYED_IN_FLIGHT_SECONDS < gen_age_seconds(tok) < _KEYED_IN_FLIGHT_SECONDS
        )

    def _read_key_row(self, key_hash: str) -> tuple[str | None, _KeyRow | None]:
        """One point read of a key row: ``(raw, fields)``."""
        raw = self._storage.get(side=True, name=self._key_row(key_hash))
        return raw, self._parse_key_row(raw)

    def _drop_key_row(self, key_hash: str, raw: str) -> bool:
        """Delete a key row only if it still holds ``raw``."""
        return bool(
            self._storage.delete_if_value_equals(
                side=True, name=self._key_row(key_hash), value=raw
            )
        )

    def _best_effort(self, what: str, write: Callable[[], Any]) -> None:
        """Run a key-row write whose failure only delays convergence (the
        next call with the key, or ``compact()``, repeats it): a fault is
        logged at WARNING and swallowed."""
        try:
            write()
        except (  # folds DbError: best-effort key-row upkeep; later calls converge
            DbError,
            RuntimeError,
        ) as exc:
            logger.warning(
                "List '%s' (actor %s): could not %s (%s); the next "
                "append_once() with that key, or compact(), repeats it",
                self.name,
                self.actor_id,
                what,
                exc,
            )

    def _keyed_heads(self, key_hash: str) -> list[tuple[str, str, str | None]]:
        """Every head carrying ``key_hash``: ``(rank, raw, tok)``, from one
        strongly consistent range read of the heads, no body read."""
        return self._keyed_by_hash(self._v2_load_full()).get(key_hash, [])

    def _locate_keyed(
        self, key_hash: str, rank: str, tok: str
    ) -> tuple[str, str] | None:
        """The head a key row names: the one carrying ``key_hash`` and
        ``tok``, at the hinted ``rank`` (one point read) or, when the hint is
        stale, anywhere (one strong range read). ``(rank, raw)`` or
        ``None``."""
        raw, env = self._read_head_tolerant(rank)
        if raw is not None and env is not None and env.key == key_hash:
            if (env.tok or "") == tok:
                return rank, raw
        for found_rank, found_raw, found_tok in self._keyed_heads(key_hash):
            if (found_tok or "") == tok:
                return found_rank, found_raw
        return None

    def _keyed_result(
        self,
        rank: str,
        raw: str,
        *,
        announce: bool = False,
        index: int | None = None,
    ) -> AppendOnceResult:
        """``created=False`` for the existing item at ``rank``. With
        ``announce``, this call finished a call that never wrote its key
        row, so it also makes the metadata touch (and, through the
        notifying wrapper, the ``append`` diff) that call never made.

        Raises:
            _ItemGone: It was deleted while being read.
        """
        item = self._resolve(raw, rank=rank, consistent=True)
        if announce:
            self._v2_touch_metadata(count_delta=1)
        return AppendOnceResult(
            created=False,
            item=item,
            handle=self._handle_for(rank, raw),
            announced=announce,
            announce_index=index if announce else None,
        )

    def _find_keyed(self, key_hash: str, tok: str) -> AppendOnceResult | None:
        """Steps 2 and 3 of ``append_once()``: the item already stored under
        ``key_hash``, or ``None`` when there is none (and no key row left
        naming one). ``tok`` is this call's token, recorded as ``by`` when
        it adopts a head that has no key row.

        Raises:
            _ItemGone: The item was deleted under the read; the caller
                retries.
        """
        db = self._storage
        raw_k, named = self._read_key_row(key_hash)
        if raw_k is not None:
            if named is not None:
                hit = self._locate_keyed(key_hash, named.rank, named.tok)
                if hit is not None:
                    rank, raw = hit
                    if rank != named.rank:
                        # compact() moved it: repair the hint for the next
                        # repeat (a lost CAS means someone else did).
                        self._best_effort(
                            "rewrite a stale key-row hint",
                            lambda: db.set_if_value_equals(
                                side=True,
                                name=self._key_row(key_hash),
                                expected=raw_k,
                                value=self._key_row_value(
                                    rank, named.tok, named.by or named.tok
                                ),
                            ),
                        )
                    return self._keyed_result(rank, raw)
            # Dangling: its item was deleted and the key row's own delete
            # never ran (or the row is malformed).
            self._best_effort(
                "delete a dangling key row",
                lambda: self._drop_key_row(key_hash, raw_k),
            )
        # No key row: a head that landed before its key row was written (a
        # crash between the two, or a call still running) is found by a
        # strongly consistent scan, so an item deleted a moment ago is never
        # seen and a head written a moment ago always is.
        found = self._keyed_heads(key_hash)
        if not found:
            return None
        # Two or more (a loser's faulted delete, then the winner's deletion):
        # the newest writer's head is the item. The others are left for
        # compact(): deleting them here could remove a running call's head
        # just before it creates its key row.
        rank, raw, head_tok = max(found, key=lambda h: h[2] or "")
        head_tok = head_tok or ""
        row = self._key_row_value(rank, head_tok, tok)
        for _ in range(_APPEND_ONCE_MAX_ATTEMPTS):
            if db.create_if_not_exists(
                side=True, name=self._key_row(key_hash), value=row
            ):
                return self._adopted(key_hash, rank, head_tok, row)
            _, now = self._read_key_row(key_hash)
            if now is None:
                continue  # deleted since the create failed: create again
            if now.tok == head_tok:
                # Bound to this head already: by this call (an SDK retry of
                # the create that landed) or by its own writer.
                if now.by == tok:
                    return self._adopted(key_hash, rank, head_tok, row)
                return self._keyed_result(rank, raw)
            # Another call bound the key to another head meanwhile: follow it.
            hit = self._locate_keyed(key_hash, now.rank, now.tok)
            if hit is not None:
                return self._keyed_result(*hit)
            raise _ItemGone(f"List '{self.name}' keyed item moved while adopting")
        raise _ItemGone(f"List '{self.name}' key row kept vanishing while adopting")

    def _adopted(
        self, key_hash: str, rank: str, head_tok: str, row: str
    ) -> AppendOnceResult:
        """This call bound the key to a head another call wrote: confirm the
        head still carries the key and token (a delete or a reused rank since
        the scan takes the row back and starts over), then announce it, as an
        insert at its position, since later appends may sit after it."""
        now_raw, now_env = self._read_head_tolerant(rank)
        if (
            now_raw is None
            or now_env is None
            or now_env.key != key_hash
            or (now_env.tok or "") != head_tok
        ):
            self._best_effort(
                "delete a key row naming a deleted item",
                lambda: self._drop_key_row(key_hash, row),
            )
            raise _ItemGone(
                f"List '{self.name}' keyed item at rank {rank!r} was deleted "
                f"while it was being adopted"
            )
        position = (
            self._v2_rank_cache.index(rank)
            if self._v2_rank_cache is not None and rank in self._v2_rank_cache
            else None
        )
        return self._keyed_result(rank, now_raw, announce=True, index=position)

    def _retire_own_head(self, key_hash: str, rank: str, head: str, tok: str) -> bool:
        """Delete this call's own head after it lost the key race, cascading
        its bodies, and say whether it did. If the head moved (a concurrent
        ``compact()``), it is found by its token. A ``DbError`` propagates;
        the duplicate it leaves is ``compact()``'s to remove."""
        db = self._storage
        target: tuple[str, str] | None = None
        if db.delete_if_value_equals(name=self._v2_item_name(rank), value=head):
            target = (rank, head)
        else:
            for found_rank, found_raw, found_tok in self._keyed_heads(key_hash):
                if (found_tok or "") != tok:
                    continue
                if db.delete_if_value_equals(
                    name=self._v2_item_name(found_rank),
                    value=found_raw,
                ):
                    target = (found_rank, found_raw)
                    break
        if target is None:
            return False
        self._cascade(target[1])
        if self._v2_rank_cache is not None and target[0] in self._v2_rank_cache:
            self._v2_rank_cache.remove(target[0])
        return True

    def _retire_key_row(self, raw: str | None) -> None:
        """After a keyed item's head was deleted: delete its key row, if the
        row still names this head's token (a loser's duplicate must not
        free the winner's key). Best-effort: the head delete committed, and a
        row left behind is dangling, which the next ``append_once()`` with
        the key and ``compact()`` both remove."""
        if raw is None or not looks_like_envelope(raw):
            return
        try:
            env = parse(raw)
        except EnvelopeError:
            return
        if env is None or env.key is None or self._aux_or_none() is None:
            return
        key_hash = env.key

        def retire() -> None:
            raw_k, named = self._read_key_row(key_hash)
            if raw_k is not None and (named is None or named.tok == (env.tok or "")):
                self._drop_key_row(key_hash, raw_k)

        self._best_effort("delete the key row of a deleted keyed item", retire)

    def append_once(self, item: Any, *, key: str) -> AppendOnceResult:
        """Append ``item`` unless an item with the same ``key`` is already
        in the list, and return what is stored under the key.

        For a client that must be able to repeat a create whose answer it
        never saw (a gateway timeout while the server finished the write):
        mint an unguessable ``key`` with the first attempt, keep it with the
        draft, and send the same key on every repeat.

        - First call: stores ``item`` and returns ``created=True``.
        - A repeat with the same key: stores nothing and returns
          ``created=False`` with the item the first call stored, **whatever
          payload the repeat sends**. Compare ``result.item`` yourself to
          detect a changed payload.
        - A key is bound to its item: once the item is deleted (by handle,
          ``pop``, ``remove``, ``del``, ``clear`` or ``delete``), a repeat
          with the key creates it again. A rewrite (``update_by_handle``,
          ``lst[i] = ...``) keeps the key.

        The key is never stored or logged: rows carry
        ``HMAC-SHA256(actor_id, key)``, which separates actors but does not
        make a guessable key safe (the actor id is public). Keys are a
        non-empty ``str`` of at most 512 characters, no control characters.

        **Concurrency.** The key row ``list:{name}-$key-{hash}`` in the
        actor's side partition is the authority; its conditional create
        decides between overlapping calls. Two calls with one key that
        overlap both write the item, and the one that loses the key row
        deletes its own copy and returns the winner's, so two items are
        visible for the length of that delete. If that delete faults, the
        error propagates and the duplicate stays: ``verify()`` reports it
        (``duplicate_keyed_items``, once it is an hour old) and
        ``compact()`` or ``repair_keys()`` removes it, keeping the key row's
        item. A call that stops after storing the item and before its key
        row leaves an item a repeat finds and finishes (the repeat then
        makes the metadata touch and, through the notifying wrapper, the
        ``append`` diff the first call never made). ``verify()`` reports such
        an item as ``unkeyed_keyed_items`` after an hour, and ``compact()``
        writes its key row. Nothing waits inside the call. ``compact()`` and
        ``repair_keys()`` leave anything written in the last hour alone, but
        like every operator rewrite they expect writes to be quiesced.

        **Raises after a write.** Any exception after the head write (a
        timeout on it, a fault on the key row or on deleting a losing copy,
        a span read) may follow a head that committed. A repeat with the key
        converges either way.

        **Announcing.** ``result.announced`` says this call made the
        metadata touch and is the one whose diff the notifying wrapper
        sends: the creating call, or a repeat that finished a call which
        stopped before its key row (``announce_index`` is then the item's
        position). An item is announced at most once; a call that stops
        between its key row and its diff leaves it unannounced. The
        maintenance paths' one-hour guard uses the writer token's
        timestamp, so the hosts' clocks should agree.

        **Cost.** A repeat: two point reads (plus one strong range read of
        the heads and a compare-and-swap when ``compact()`` moved the item
        since). A first call: one point read, one strongly consistent range
        read of the list's heads (spanned bodies are not read; plain items
        cost their full size), the item write and the key-row create. Each
        of at most three arbitration passes adds at most one head write
        (with its bodies) and up to three range reads, before
        ``RuntimeError``.

        **v2 only.** Raises ``ValueError`` naming ``migrate_to_v2()`` on a v1
        list. The first keyed item makes the list unreadable to readers
        older than 3.16 (as a spanned item does).

        Raises:
            ValueError: The key is invalid, the list is v1, or the item
                carries the reserved envelope key.
            ListItemTooLargeError: The item is over ``list_item_max_bytes``.
            RuntimeError: The attempt budget ran out under contention. The
                item this call wrote may be stored without its key row; a
                repeat with the key finishes it (``created=False``).
        """
        if not self._db:
            raise RuntimeError("No database connection available")
        self._validate_append_key(key)
        self._before_mutation()
        if self._dispatch_and_stash() != 2:
            raise self._not_v2_error("append_once")
        return self._v2_append_once(item, key)

    def _v2_append_once(self, item: Any, key: str) -> AppendOnceResult:
        """The protocol behind ``append_once()``; see the plan's Phase 3.

        Item first, then the key row: point-read the key row (and the head
        it names); else scan the heads for one that landed without its key
        row; else write a head carrying the key hash and a fresh token, then
        create the key row. A lost create reads the row back: our own token
        is a win (an SDK retry of our create, or another call that adopted
        our head and announced it); a row naming no head is dangling and is
        replaced; anything else is another writer's win, and our head is
        deleted.
        """
        value_str = self._encode_item(item)
        spans = self._check_item_size(value_str, can_span=True)
        self._aux()  # key rows need the side partition: refuse a '$' actor id now
        key_hash = self._key_hash(key)
        if self._dispatch_saw_no_row():
            self._v2_create_meta_row()

        tok = new_gen()
        own: tuple[str, str] | None = None  # (rank, head) once written
        key_name = self._key_row(key_hash)
        for _attempt in range(_APPEND_ONCE_MAX_ATTEMPTS):
            if own is None:
                try:
                    found = self._find_keyed(key_hash, tok)
                except _ItemGone:
                    continue
                if found is not None:
                    return found
                landed: list[str] = []

                def head_write(head: str, landed: list[str] = landed) -> bool:
                    landed.append(self._v2_write_item_at_new_rank(head))
                    return True

                _, head = self._write_spanning(
                    value_str,
                    spans,
                    head_write,
                    carry=Envelope(key=key_hash, tok=tok),
                )
                own = (landed[0], head)

            rank, head = own
            row = self._key_row_value(rank, tok, tok)
            db = self._storage
            if db.create_if_not_exists(side=True, name=key_name, value=row):
                return self._created(rank, head, value_str, announce=True)
            raw_k, named = self._read_key_row(key_hash)
            if raw_k is None:
                continue  # deleted since the create failed: create again
            if named is not None and named.tok == tok:
                # Our head is the item: an SDK retry of our own create that
                # landed (``by`` is ours), or another call adopted our head
                # and made the announcement itself.
                return self._created(
                    rank, head, value_str, announce=named.by in (None, tok)
                )
            winner = (
                self._locate_keyed(key_hash, named.rank, named.tok)
                if named is not None
                else None
            )
            if winner is None:
                # Names no head (its item was deleted, or the hint is the
                # rank our own head reused): dangling. Replace it.
                self._drop_key_row(key_hash, raw_k)
                continue
            # Another writer owns the key: ours is the duplicate.
            if not self._retire_own_head(key_hash, rank, head, tok):
                # A repeat adopted our head after the winner's item went:
                # ours is the stored item now, announced by that repeat.
                _, now = self._read_key_row(key_hash)
                if now is not None and now.tok == tok:
                    return self._created(rank, head, value_str, announce=False)
            if self._v2_rank_cache is not None and winner[0] not in self._v2_rank_cache:
                self._v2_rank_cache.append(winner[0])
                self._v2_rank_cache.sort()
            try:
                return self._keyed_result(*winner)
            except _ItemGone:
                own = None  # the winner's item went too: start over
                tok = new_gen()
                continue
        if own is not None:
            # A repeat may have adopted our head since our last create: if
            # the key row now names it, it is the stored item.
            _, named = self._read_key_row(key_hash)
            if named is not None and named.tok == tok:
                return self._created(
                    own[0], own[1], value_str, announce=named.by in (None, tok)
                )
            # No live winner exists here (every pass ended with the row absent,
            # dangling or its item gone), so the head is kept: deleting it
            # could remove an item a repeat is adopting right now. A repeat
            # with the key finishes it.
        raise RuntimeError(
            f"list '{self.name}' append_once: too many concurrent attempts with "
            f"this key, retry later"
        )

    def _created(
        self, rank: str, head: str, value_str: str, *, announce: bool
    ) -> AppendOnceResult:
        """``created=True`` for this call's own head. With ``announce`` (no
        other call announced it), the metadata touch a creating call makes."""
        if self._v2_rank_cache is not None and rank not in self._v2_rank_cache:
            self._v2_rank_cache.append(rank)
            self._v2_rank_cache.sort()
        if announce:
            self._v2_touch_metadata(count_delta=1)
        return AppendOnceResult(
            created=True,
            item=self._decode_item(value_str),
            handle=self._handle_for(rank, head),
            announced=announce,
        )

    def _v2_extend(self, items: list[Any]) -> None:
        """Phase 9B: one last-rank read for the WHOLE batch, then n
        conditional creates and a single metadata touch -- not n calls to
        ``append()``, which would each pay their own last-rank read.

        Collision handling generalizes ``_v2_append()``'s per-item retry:
        on a collision at item i, the items from i onward are re-keyed
        against a freshly re-read last rank and retried; items before i
        already landed and are not retried. ``count_delta`` covers exactly
        the items that landed, even on the raise path (a partial batch is
        possible on exhausted retries, same as a partial ``extend()`` via
        the old per-item loop would have left).

        Same cache discipline as ``_v2_append()``: created ranks are
        appended to ``self._v2_rank_cache`` IF it is already warm, never
        loading a cold one.

        On a list whose dispatch found no meta row, creates it first via
        ``_v2_create_meta_row()``. ``extend()`` already returns before
        dispatch on an empty ``items``, so this never runs on a
        never-created list for an empty batch.
        """
        # Every item is encoded and size-checked before the first write, so
        # an oversized item anywhere in the batch writes nothing.
        encoded = [self._encode_item(item) for item in items]
        spans = [self._check_item_size(v, can_span=True) for v in encoded]
        if self._dispatch_saw_no_row():
            self._v2_create_meta_row()
        # Bodies of the spanning items first (one generation each), then
        # the heads through the batch's rank loop. Heads that never land
        # have their bodies deleted again below.
        heads: list[str] = []
        head_spans: list[SpanInfo | None] = []
        try:
            for value_str, item_spans in zip(encoded, spans, strict=True):
                span = self._write_bodies(value_str) if item_spans else None
                head_spans.append(span)
                heads.append(self._make_head(value_str, span))
        except BaseException:
            for span in head_spans:
                self._span_delete_bodies(span)
            raise
        created = 0
        created_ranks: list[str] = []
        remaining = heads
        in_create = False  # a create call for item `created` is in flight
        try:
            last = self._v2_last_rank()
            for attempt in range(_V2_MAX_RANK_RETRIES):
                if not remaining:
                    break
                candidates = fi.generate_n_keys_between(last, None, len(remaining))
                collided_at = None
                for i, (candidate, value_str) in enumerate(
                    zip(candidates, remaining, strict=True)
                ):
                    if len(candidate) > _V2_RANK_MAX_LEN:
                        raise ListRankExhaustedError(
                            f"list '{self.name}' rank key exceeded {_V2_RANK_MAX_LEN} "
                            f"chars -- {self._RANK_REMEDY}"
                        )
                    item_db = self._storage
                    name = self._v2_item_name(candidate)
                    in_create = True
                    wrote = item_db.create_if_not_exists(
                        name=name, value=value_str
                    ) or self._landed_anyway(name, value_str)
                    in_create = False
                    if not wrote:
                        # Collision: another writer took this rank. The items
                        # before it already landed; re-key from here.
                        collided_at = i
                        break
                    created += 1
                    created_ranks.append(candidate)
                    last = candidate
                if collided_at is None:
                    remaining = []
                    break
                remaining = remaining[collided_at:]
                if attempt < _V2_MAX_RANK_RETRIES - 1:
                    last = self._v2_last_rank()
        except BaseException:
            # A fault part-way: the landed items stay, with their bodies.
            # If the raise came from a create in flight, that item's outcome
            # is unknown and its bodies stay (an orphan for the aged sweep if
            # it did not land); otherwise (a last-rank read, the rank cap)
            # it was never written. Bodies of items never written go.
            for span in head_spans[created + 1 if in_create else created :]:
                self._span_delete_bodies(span)
            if created_ranks and self._v2_rank_cache is not None:
                self._v2_rank_cache.extend(created_ranks)
            raise
        if created_ranks and self._v2_rank_cache is not None:
            self._v2_rank_cache.extend(created_ranks)
        if created:
            self._v2_touch_metadata(count_delta=created)
        if remaining:
            # The un-landed tail's bodies: delete them, keep the landed ones.
            for span in head_spans[created:]:
                self._span_delete_bodies(span)
            raise RuntimeError(
                f"list '{self.name}' extend: too many rank collisions, retry later"
            )

    def extend(self, items: list[Any]) -> None:
        """Add multiple items to end of list: one last-rank read for the whole
        batch (see ``_v2_extend()``), not one per item."""
        if not items:
            return

        self._before_mutation()
        self._dispatch_v2()
        self._v2_extend(items)

    def _v2_item_names_in_range(self) -> list[str]:
        """This list's OWN v2 item row names.

        Used by the destructive paths (``clear()``/``delete()``/migration
        cleanup), so the rank filter is load-bearing here, not merely
        cosmetic: a legacy ``#``-named sibling list's rows share this byte
        range and must never be deleted as if they were ours.
        """
        lower, upper = self._v2_bounds()
        db = self._storage
        rows = db.get_range(lower=lower, upper=upper, keys_only=True)
        return self._names_matching(rows, len(self._v2_item_prefix()), _v2_is_rank)

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
        self._foreign_rows(sweep=True)

        self._require_v2()
        self._v2_clear()

    def _v2_clear(self) -> None:
        """The v2 half of ``clear()``: remove every item. The caller has
        dispatched on the stored format and swept foreign rows."""
        # One range read WITH values (not keys-only): the heads name
        # the body generations to delete, so clear() never enumerates
        # $span- rows. Only the generations of heads it deletes go, so
        # an append racing clear() keeps its bodies (its head lands on
        # the emptied list, the same outcome as before spanning).
        pairs = self._v2_load_full()
        item_names = [self._v2_item_name(rank) for rank, _ in pairs]
        if item_names:
            self._storage.batch_delete(names=item_names)
        for _, raw in pairs:
            self._cascade(raw)
        # Only the key rows of the heads it deleted, as with bodies: an
        # append_once() racing clear() keeps its key with its head.
        # Rows already dangling go too, unless a running call may have
        # written them after the read (the in-flight guard). Like every
        # whole-list rewrite, this assumes writes are quiesced beyond that
        # window and that hosts' clocks agree.
        deleted = {
            (key_hash, tok or "")
            for key_hash, keyed in self._keyed_by_hash(pairs).items()
            for _, _, tok in keyed
        }
        stale = [
            self._key_row(key_hash)
            for key_hash, raw_k in self._key_rows().items()
            if (named := self._parse_key_row(raw_k)) is None
            or (key_hash, named.tok) in deleted
            or not self._in_flight(named.tok)
        ]
        self._delete_aux_rows(stale)
        self._replace_metadata(self._create_default_metadata_v2())
        self._v2_rank_cache = []

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
        self._foreign_rows(sweep=True)

        self._require_v2()
        self._v2_delete()

    def _v2_delete(self) -> None:
        """The v2 half of ``delete()``: delete every row of the list, metadata included. The caller has
        dispatched on the stored format and swept foreign rows."""
        item_names = self._v2_item_names_in_range()
        if item_names:
            self._storage.batch_delete(names=item_names)
        # Every side-partition row of the list, orphan generations
        # included: once the meta row is gone no sweep can reach them.
        # Like an actor delete, this assumes writes to the list are
        # quiesced: an append whose head lands after delete() leaves a
        # head without bodies (a 409 the sweep removes), never a whole
        # item a recreated list would adopt. Enumerating $span- rows
        # costs every body byte on DynamoDB.
        self._delete_aux_rows(self._aux_names("span") + self._aux_names("key"))
        meta_db = self._storage
        if not meta_db.remove(name=self._get_meta_property_name()):
            raise RuntimeError(f"list metadata write failed for '{self.name}'")
        self._meta_cache = None
        self._v2_rank_cache = None

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
        self._require_v2()
        return self._v2_to_list(consistent=consistent)

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
        self._require_v2()
        values = self._v2_to_list(consistent=consistent)
        length = len(values)
        if start < 0:
            start = max(0, length + start)
        if end < 0:
            end = max(0, length + end)
        start = max(0, min(start, length))
        end = max(start, min(end, length))
        return values[start:end]

    def to_indexed_list(self, consistent: bool = True) -> list[tuple[int, Any]]:
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

        Args:
            consistent: see ``to_list()``.

        Raises:
            ListCorruptionError: v1 only -- see ``to_list()``.
        """
        return list(enumerate(self.to_list(consistent=consistent)))

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

            item_db = self._storage
            item_str = item_db.get(name=name)
            if item_str is None:
                # Vanished between the range read and this get -- another
                # writer removed it. Re-resolve rather than calling it
                # corruption.
                continue
            try:
                item = self._resolve(item_str, rank=rank, consistent=True)
            except _ItemGone:
                continue  # deleted under us: re-resolve, as for a vanished row

            del_db = self._storage
            if del_db.delete_if_value_equals(name=name, value=item_str):
                del ranks[resolved]
                self._cascade(item_str)
                self._retire_key_row(item_str)
                self._v2_touch_metadata(count=len(ranks))
                return item
            # Value changed or row already gone -- re-resolve and retry.
        raise RuntimeError(
            f"list '{self.name}' pop: too many concurrent modifications, retry later"
        )

    def pop(self, index: int = -1) -> Any:
        """Remove and return item at index (default last)."""
        # A fresh dispatch first, never the cache: see the property
        # list's pop() for why the empty check is _v2_pop()'s own.
        self._dispatch_v2()
        return self._v2_pop(index)

    def _v2_insert(self, index: int, item: Any) -> None:
        """On a list whose dispatch found no meta row, creates it first via
        ``_v2_create_meta_row()`` -- see that method's docstring for the
        full write-order diagram. A spanning item's bodies are written once,
        before the rank loop, and deleted again if the loop gives up."""
        value_str = self._encode_item(item)
        spans = self._check_item_size(value_str, can_span=True)
        if self._dispatch_saw_no_row():
            self._v2_create_meta_row()

        def head_write(head: str) -> bool:
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
                    raise ListRankExhaustedError(
                        f"list '{self.name}' rank key exceeded {_V2_RANK_MAX_LEN} "
                        f"chars -- {self._RANK_REMEDY}"
                    )
                item_db = self._storage
                name = self._v2_item_name(candidate)
                if self._probed_write(
                    item_db.create_if_not_exists,
                    name=name,
                    value=head,
                ) or self._landed_anyway(name, head):
                    ranks.insert(pos, candidate)
                    return True
                # Collision: force a fresh read (recomputing neighbours at
                # this position) on the next attempt.
            raise RuntimeError(
                f"list '{self.name}' insert: too many rank collisions, retry later"
            )

        self._write_spanning(value_str, spans, head_write)
        self._v2_touch_metadata(count_delta=1)

    def insert(self, index: int, item: Any) -> None:
        """Insert item at given index."""
        if not self._db:
            raise RuntimeError("No database connection available")

        self._before_mutation()
        self._dispatch_v2()
        self._v2_insert(index, item)

    @staticmethod
    def _sought_size(value: Any) -> int | None:
        """The encoded size of a sought value, for value scans to compare
        with a spanned head's ``span.bytes`` without reading its bodies;
        ``None`` when it cannot be encoded as an item (then every spanned
        item is read)."""
        try:
            return encoded_size(encode_item(value))
        except ValueError:
            return None

    def _head_equals(
        self, raw: str, rank: str, value: Any, sought_size: int | None
    ) -> bool:
        """Whether the item a head stands for equals ``value``.

        A spanned item's bodies are read only when its encoded size (from
        the head) equals the sought value's: equal items encode to the same
        bytes, whatever span threshold was configured when either was
        written. (Python equality that crosses encodings, such as ``1`` and
        ``1.0`` inside an item, is not matched against a spanned item.) A
        malformed head equals nothing (``verify()`` reports it), so a scan
        passes it."""
        try:
            env = parse(raw)
        except EnvelopeError:
            return False
        if env is None:
            return bool(self._decode_item(raw) == value)
        if env.span is None:
            return bool(env.value == value)
        if sought_size is not None and sought_size != env.span.bytes:
            return False
        try:
            return bool(self._resolve(raw, rank=rank, consistent=True) == value)
        except _ItemGone:
            return False

    def _v2_remove(self, value: Any) -> None:
        """Delete the first item equal to ``value``, by RANK.

        Same hazard `_v2_pop` addresses, one method over: iterating to find
        the position and then deleting by that position resolves the rank map
        twice, so a concurrent mutation in between makes remove() delete
        whatever happens to sit at that position now rather than the item it
        matched. Deleting the rank the match came from removes exactly the
        item that was matched, or nothing.
        """
        sought_size = self._sought_size(value)
        for _attempt in range(_V2_MAX_RANK_RETRIES):
            pairs = self._v2_load_full()
            for i, (rank, raw_value) in enumerate(pairs):
                if not self._head_equals(raw_value, rank, value, sought_size):
                    continue
                del_db = self._storage
                if not del_db.delete_if_value_equals(
                    name=self._v2_item_name(rank),
                    value=raw_value,
                ):
                    # Overwritten or already deleted since the scan -- the
                    # match is stale, so rescan rather than deleting whatever
                    # is there now.
                    break
                self._cascade(raw_value)
                self._retire_key_row(raw_value)
                # _v2_load_full() just set the cache to exactly these ranks
                # in this order, so dropping entry i keeps it consistent.
                ranks = self._v2_rank_cache
                if ranks is not None and i < len(ranks) and ranks[i] == rank:
                    del ranks[i]
                else:  # pragma: no cover -- defensive
                    self._v2_rank_cache = None
                # len(pairs) - 1, not len(ranks): the defensive branch
                # above can leave the cache None, but `pairs` (this
                # attempt's fresh _v2_load_full() read) always reflects
                # exactly one fewer item than what was just deleted.
                self._v2_touch_metadata(count=len(pairs) - 1)
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
        self._dispatch_v2()
        self._v2_remove(value)

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
        self._require_v2()
        # One range query for the whole list, then scan in memory. Going
        # through self[i] would cost a whole-list range query PER ITEM
        # (O(n) total) now that positional reads refresh the rank map,
        # and it would compare against a list that can shift under the
        # loop.
        # Spanned items' bodies are read only when the sought value is
        # large enough to equal one.
        pairs = self._v2_load_full()
        sought_size = self._sought_size(value)
        begin, end = self._normalize_search_bounds(start, stop, len(pairs))
        for i in range(begin, end):
            rank, raw = pairs[i]
            if self._head_equals(raw, rank, value, sought_size):
                return i
        raise ValueError(f"{value} is not in list")

    def count(self, value: Any) -> int:
        """Return number of occurrences of value."""
        self._require_v2()
        sought_size = self._sought_size(value)
        return sum(
            1
            for rank, raw in self._v2_load_full()
            if self._head_equals(raw, rank, value, sought_size)
        )

    def find(
        self, identity_key: str, value: Any, consistent: bool = True
    ) -> Any | None:
        """Return the first item whose ``identity_key`` field equals
        ``value``, or ``None`` if there is no match.

        One whole-list read (``to_list()``), matched in memory -- the same
        query cost as any other full scan, just without every caller
        writing the scan loop by hand. Universal across v1 and v2.

        Items that are not a dict, or that lack ``identity_key`` entirely,
        never match (a missing field is not the same as the field being
        present with value ``None``) and never raise.

        Args:
            identity_key: field name to match on -- same parameter name as
                ``verify()``'s duplicate-identity check.
            value: value to match.
            consistent: see ``to_list()``. Ignored under v1.
        """
        for item in self.to_list(consistent=consistent):
            if (
                isinstance(item, dict)
                and identity_key in item
                and item[identity_key] == value
            ):
                return item
        return None

    def find_all(
        self, identity_key: str, value: Any, consistent: bool = True
    ) -> list[Any]:
        """Return every item whose ``identity_key`` field equals ``value``
        -- see ``find()``. A list a caller with duplicate identities (see
        ``verify()``'s ``duplicate_identities``) needs to see all of, not
        just the first."""
        return [
            item
            for item in self.to_list(consistent=consistent)
            if isinstance(item, dict)
            and identity_key in item
            and item[identity_key] == value
        ]

    def items_with_handles(
        self, *, resolve: bool = True
    ) -> list[tuple[ListItemHandle, Any]]:
        """One range read -> ``[(handle, decoded_item), ...]``, in list
        order.

        **v2 only.** v1 has no rank identity to hand out a handle for --
        only positional identity, which ``to_indexed_list()`` already
        serves. Raises on a v1 list, naming ``migrate_to_v2()``.

        **Always strongly consistent**, regardless of Phase 6's
        ``consistent`` parameter or any application-level default: a
        handle carries the raw stored bytes, and a conditional write
        (``set_if_value_equals()``/``delete_if_value_equals()``) checks
        exactly those bytes. A handle read from a stale replica would fail
        its condition against a row nobody has actually touched -- the
        bulk endpoint would then report every item as "concurrently
        modified" and apply nothing. Same rationale
        ``_v2_ensure_rank_cache()`` already carries, for the same reason.

        Args:
            resolve: ``True`` (the default) reads every spanned item's body
                rows. ``False`` reads the heads only: a spanned item's slot
                holds ``UNRESOLVED`` and its handle carries
                ``spanned=True`` and ``bytes``; read it on demand with
                ``item_at(handle)``. Plain items are decoded either way.
        """
        if not self._is_v2():
            raise self._not_v2_error("items_with_handles")
        return self._v2_items_with_handles(resolve=resolve)

    def item_at(self, handle: ListItemHandle) -> tuple[ListItemHandle, Any]:
        """Read the item at ``handle.rank`` NOW, resolving a spanned item,
        and return it with a fresh handle: ``(fresh_handle, item)``.

        One strongly consistent point read of the head, plus the body read
        for a spanned item. **The rank is the address, not the item**: if
        the item was updated since ``handle`` was read, this returns the
        new value; if it was deleted and its trailing rank reissued to a
        later append (see ``ListItemHandle``), this returns that other
        item. A caller that needs "unchanged since I read it" compares
        ``fresh_handle.raw_value`` to ``handle.raw_value``.

        Raises:
            ValueError: The list is v1.
            IndexError: No item is at that rank any more.
            ListItemSpanError: The item's bodies are broken.
        """
        if not self._is_v2():
            raise self._not_v2_error("item_at")
        raw, _ = self._read_head(handle.rank, consistent=True)
        if raw is None:
            raise IndexError(
                f"List '{self.name}' has no item at rank {handle.rank!r} any more"
            )
        item = self._resolve(raw, rank=handle.rank, consistent=True)
        return self._handle_for(handle.rank, raw), item

    def _v2_items_with_handles(
        self, *, resolve: bool = True
    ) -> list[tuple[ListItemHandle, Any]]:
        """Same read as ``items_with_handles()``, without the ``_is_v2()``
        format check.

        For callers that already dispatched fresh via
        ``_dispatch_and_stash() == 2`` themselves (``remove_where()``,
        ``update_where()``): re-checking via ``_is_v2()`` here would
        consult ``_load_metadata()``'s cache-consulting path again,
        undoing the whole point of dispatching fresh in the first place --
        see ``_dispatch_and_stash()``'s docstring. Not for direct use;
        callers must already know the list is v2.
        """
        pairs = self._v2_load_full()  # default consistent=True, no override
        if resolve:
            return [
                (self._handle_for(rank, raw), item)
                for rank, raw, item in self._resolve_pairs(pairs, consistent=True)
            ]
        return [
            (self._handle_for(rank, raw), self._unresolved_or_item(rank, raw))
            for rank, raw in pairs
        ]

    def delete_by_handle(self, handle: ListItemHandle) -> bool:
        """Delete exactly the item ``handle`` addresses, single-shot.

        **v2 only** -- raises ``ValueError`` naming ``migrate_to_v2()`` on a
        v1 list. Uses ``delete_if_value_equals()`` against the handle's raw
        stored bytes: no re-scan, no retry. If the row has since changed or
        vanished, the condition fails and this returns ``False`` -- a
        failed condition IS the answer, not something to retry. A handle
        pins the exact bytes it read; retrying would mean "delete whatever
        is there now", which is exactly the bug class handles exist to
        rule out.

        Dispatches on a fresh meta-row read (``_dispatch_and_stash()``),
        not the cached format belief -- this is a mutator, and a stale
        cache here would either wrongly refuse a v2 list or, worse,
        silently no-op against storage the list has moved away from.
        """
        if self._dispatch_and_stash() != 2:
            raise self._not_v2_error("delete_by_handle")
        db = self._storage
        if not db.delete_if_value_equals(
            name=self._v2_item_name(handle.rank),
            value=handle.raw_value,
        ):
            return False
        # The handle's raw value is the head that was deleted: its envelope
        # names the body generation to delete (best-effort, after commit),
        # and a keyed item's key row goes with it.
        self._cascade(handle.raw_value)
        self._retire_key_row(handle.raw_value)
        # Only drop the rank from an already-warm cache -- never load a
        # cold one, matching _v2_append()/_v2_extend()'s discipline.
        if self._v2_rank_cache is not None:
            try:
                self._v2_rank_cache.remove(handle.rank)
            except ValueError:  # pragma: no cover -- defensive
                pass
        # count_delta, not an absolute count: this call never read the
        # whole list, so it has no counted truth to write, only a
        # relative change to merge onto whatever is currently stored.
        self._v2_touch_metadata(count_delta=-1)
        return True

    def update_by_handle(self, handle: ListItemHandle, item: Any) -> bool:
        """Replace exactly the item ``handle`` addresses with ``item``,
        single-shot.

        **v2 only** -- raises ``ValueError`` naming ``migrate_to_v2()`` on a
        v1 list. Uses ``set_if_value_equals()`` against the handle's raw
        stored bytes: no re-scan, no retry, same rationale as
        ``delete_by_handle()``. Returns ``False`` if the row has since
        changed or vanished.

        The item count is unaffected, so unlike ``delete_by_handle()`` this
        does not touch ``count_hint`` at all -- only ``updated_at`` moves.
        """
        if self._dispatch_and_stash() != 2:
            raise self._not_v2_error("update_by_handle")
        value_str = self._encode_item(item)
        spans = self._check_item_size(value_str, can_span=True)
        try:
            old_env = parse(handle.raw_value)
        except EnvelopeError:
            old_env = None

        def head_write(head: str) -> bool:
            return bool(
                self._probed_write(
                    self._storage.set_if_value_equals,
                    name=self._v2_item_name(handle.rank),
                    expected=handle.raw_value,
                    value=head,
                )
            )

        # Bodies first, then the head CAS; a lost CAS deletes the new
        # bodies again and returns False. The envelope's key, token and
        # unknown fields are carried into the new head.
        landed, _ = self._write_spanning(
            value_str,
            spans,
            head_write,
            carry=old_env,
            head_name=self._v2_item_name(handle.rank),
        )
        if not landed:
            return False
        self._cascade(handle.raw_value)
        self._v2_touch_metadata()
        return True

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
        self._dispatch_v2()
        return self._v2_remove_where(identity_key, value, first_only=first_only)

    def _v2_remove_where(
        self, identity_key: str, value: Any, *, first_only: bool = False
    ) -> list[Any]:
        """The v2 half of ``remove_where()``, for a caller that has dispatched
        fresh (``_dispatch_and_stash() == 2``)."""
        matches = self._v2_items_with_handles()
        removed: list[Any] = []
        for handle, item in matches:
            if (
                isinstance(item, dict)
                and identity_key in item
                and item[identity_key] == value
            ):
                if self.delete_by_handle(handle):
                    removed.append(item)
                    if first_only:
                        break
        return removed

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
        self._dispatch_v2()
        return self._v2_update_where(identity_key, value, item, first_only=first_only)

    def _v2_update_where(
        self, identity_key: str, value: Any, item: Any, *, first_only: bool = False
    ) -> list[Any]:
        """The v2 half of ``update_where()``, for a caller that has dispatched
        fresh (``_dispatch_and_stash() == 2``)."""
        matches = self._v2_items_with_handles()
        updated: list[Any] = []
        for handle, existing in matches:
            if (
                isinstance(existing, dict)
                and identity_key in existing
                and existing[identity_key] == value
            ):
                if self.update_by_handle(handle, item):
                    updated.append(existing)
                    if first_only:
                        break
        return updated

    def _identity_of(
        self, raw_value: str, identity_key: str, rank: str | None = None
    ) -> Any:
        """This row's value for ``identity_key``, or ``None`` if it has none.

        With ``rank`` (a v2 head) a spanned item is resolved first, so
        ``verify(identity_key=...)`` reads every spanned item's bodies.

        Rows that are not dicts, or that lack the field, are not
        identity-addressable and are excluded from identity duplicate
        detection entirely -- lumping them together under a shared "no
        identity" bucket would report every such row as a duplicate of
        every other.
        """
        if rank is None:
            decoded = self._decode_item(raw_value)
        else:
            try:
                decoded = self._resolve(raw_value, rank=rank, consistent=True)
            except (_ItemGone, ListItemSpanError):
                # Gone, or a broken span: not identity-addressable here.
                # verify(spans=True) reports a broken one; raising would stop
                # the repair tool that removes it.
                return None
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

    def _v2_verify(
        self, identity_key: str | None = None, spans: bool = False
    ) -> dict[str, Any]:
        """Read-only integrity check for v2 lists.

        Structurally, v2 cannot have holes -- there is no separate
        "recorded length" a row could disagree with; every present row IS
        a position. It CAN have an orphan: item rows with no meta row at
        all, the state a fault on the item write of a list's first
        mutation could leave before thoughts/plans/2026-09-14-v2-list-
        mutation-raises-after-its-write-committed.md's Phase 1, and that a
        rare residual (a concurrent ``delete()`` plus a fault on the
        touch's recreation write) can still leave. An orphan is invisible
        to ``exists()``/``list_all()``/REST and is swept as residue by the
        next ``delete()``/``clear()``/``migrate_to_v2()`` -- worth
        flagging even though the next mutation through ``ListProperty``,
        or ``compact()``, repairs it. Besides that, the only other things
        worth reporting are rank keys approaching the length cap (a signal
        to compact()/rebalance before insert()/append() start failing) and
        the same adjacent-duplicate heuristic v1 reports (informational,
        not part of ``healthy`` -- a duplicate value is never itself
        corruption under v2).

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
            - count_hint: the stored advisory count (``None`` if this
              list's metadata predates ``count_hint`` entirely, or if the
              meta row is absent entirely -- see ``meta_row_present``)
            - count_hint_drift: ``count_hint - length`` (``None`` when
              ``count_hint`` is ``None``). Informational, NOT part of
              ``healthy`` -- see the class docstring for the documented
              drift bound; nonzero here is expected under concurrent
              mutation, not corruption
            - meta_row_present: whether the meta row physically exists.
              ``False`` for a never-created list (no meta row, no items)
              as well as for an orphan. The orphan state is the
              combination ``meta_row_present is False and length > 0``;
              ``healthy`` encodes exactly that combination, so a consumer
              wanting "is this an orphan" should read ``healthy`` (or
              test both keys), not ``meta_row_present`` alone
            - spanned_items, span_bytes: how many items span body rows and
              their total encoded size, from the heads alone (no body read)
            - malformed_heads: ranks whose head is a malformed envelope
              (part of ``healthy``)
            - with ``spans=True`` only (one enumeration of the list's
              ``$span-`` rows in the side partition, which costs every body
              byte on DynamoDB): ``span_body_rows``; ``orphan_span_gens``,
              the number of body generations no head names (a crash between
              bodies and head, or a failed best-effort cascade);
              ``broken_spans``, the ranks of heads whose part set is not
              exactly the one their envelope names (part of ``healthy``)
            - healthy: True iff no rank key is within the rebalance
              warning zone of the cap, no identity is repeated, the list is
              not an orphan (``meta_row_present is False`` while
              ``length > 0``), no head is malformed and (with ``spans``) no
              span is broken. A never-created list is healthy.
            - key_rows: how many key rows (``append_once()``) the list has,
              from one prefix read of its small ``$key-`` rows (always on)
            - dangling_key_rows: the rank hints of key rows that name no
              head carrying their key and token (the item was deleted and
              its key row's delete never ran); the next ``append_once()``
              with the key, ``compact()`` or ``repair_keys()`` removes
              them. Informational
            - duplicate_keyed_items: the ranks of heads that share a key
              with another head (an overlapping ``append_once()`` whose
              loser could not delete its copy); part of ``healthy``, and
              ``compact()``/``repair_keys()`` keep the key row's item and
              remove the others
            - unkeyed_keyed_items: the ranks of keyed heads that no key row
              names (a call that stopped between its item and its key row);
              a repeat with the key, ``compact()`` or ``repair_keys()``
              writes the row. Informational
            The three key findings leave out anything an ``append_once()``
            call wrote in the last hour (its writer token's age): a second
            copy, or a head without its key row, is then a call still
            running. They report ranks, never key hashes.
        """
        pairs = self._v2_load_full()
        max_rank_length = max((len(rank) for rank, _ in pairs), default=0)
        length = len(pairs)

        adjacent_duplicates: list[tuple[int, int]] = []
        for i in range(len(pairs) - 1):
            if pairs[i][1] == pairs[i + 1][1]:
                adjacent_duplicates.append((i, i + 1))

        stored, _ = self._read_meta_row()
        meta_row_present = stored is not None
        stored = stored or {}
        count_hint = stored.get("count_hint")
        count_hint = count_hint if isinstance(count_hint, int) else None

        report: dict[str, Any] = {
            "format": 2,
            "length": length,
            "max_rank_length": max_rank_length,
            "adjacent_duplicates": adjacent_duplicates,
            "foreign_format_rows": self._foreign_rows(sweep=False),
            "needs_rebalance": max_rank_length >= _V2_RANK_WARNING_LENGTH,
            "count_hint": count_hint,
            "count_hint_drift": (
                count_hint - length if count_hint is not None else None
            ),
            "meta_row_present": meta_row_present,
            "healthy": (
                max_rank_length < _V2_RANK_WARNING_LENGTH
                and not (not meta_row_present and length > 0)
            ),
        }
        span_heads, malformed = self._span_heads(pairs)
        report["spanned_items"] = len(span_heads)
        report["span_bytes"] = sum(span.bytes for _, span in span_heads)
        report["malformed_heads"] = malformed
        if malformed:
            report["healthy"] = False
        if spans:
            span_names = self._aux_names("span")
            broken, orphan_gens = self._span_inventory(
                span_heads, span_names, check_content=True
            )
            raw_by_rank = dict(pairs)
            for gen in self._gens_named_by(raw_by_rank[r] for r in malformed):
                orphan_gens.pop(gen, None)
            report["span_body_rows"] = len(span_names)
            report["orphan_span_gens"] = len(orphan_gens)
            report["broken_spans"] = broken
            if broken:
                report["healthy"] = False
        report.update(self._key_report(pairs))
        if report["duplicate_keyed_items"]:
            report["healthy"] = False
        duplicates: dict[Any, list[int]] | None = None
        identity_checked_count: int | None = None
        if identity_key is not None:
            duplicates, identity_checked_count = self._identity_duplicates(
                [
                    (
                        i,
                        None
                        if rank in malformed
                        else self._identity_of(raw, identity_key, rank),
                    )
                    for i, (rank, raw) in enumerate(pairs)
                ]
            )
        report["duplicate_identities"] = duplicates
        report["identity_checked_count"] = identity_checked_count
        if duplicates:
            report["healthy"] = False
        return report

    def _span_heads(
        self, pairs: list[tuple[str, str]]
    ) -> tuple[list[tuple[str, SpanInfo]], list[str]]:
        """From ``(rank, raw)`` heads: the spanned ones as ``(rank, span)``,
        and the ranks of malformed envelopes. No body read."""
        spanned: list[tuple[str, SpanInfo]] = []
        malformed: list[str] = []
        for rank, raw in pairs:
            try:
                env = parse(raw)
            except EnvelopeError:
                malformed.append(rank)
                continue
            if env is not None and env.span is not None:
                spanned.append((rank, env.span))
        return spanned, malformed

    def _key_rows(self) -> dict[str, str]:
        """``{key_hash: raw}`` for the list's key rows: one prefix read of
        the side partition, shape-filtered (key rows are a few dozen bytes)."""
        aux = self._aux_or_none()
        if aux is None:
            return {}
        prefix = key_prefix(self.name)
        rows = self._storage.get_prefix(side=True, prefix=prefix)
        return {
            name[len(prefix) :]: rows[name]
            for name in self._names_matching(
                rows, len(prefix), lambda suffix: bool(KEY_ROW_RE.match(suffix))
            )
        }

    @staticmethod
    def _keyed_by_hash(
        pairs: list[tuple[str, str]],
    ) -> dict[str, list[tuple[str, str, str | None]]]:
        """``{key_hash: [(rank, raw, tok), ...]}`` for the keyed heads among
        ``pairs``, in list order. No body read."""
        by_key: dict[str, list[tuple[str, str, str | None]]] = {}
        for rank, raw in pairs:
            if not looks_like_envelope(raw):
                continue
            try:
                env = parse(raw)
            except EnvelopeError:
                continue
            if env is not None and env.key is not None:
                by_key.setdefault(env.key, []).append((rank, raw, env.tok))
        return by_key

    def _key_findings(
        self, pairs: list[tuple[str, str]]
    ) -> tuple[
        dict[str, list[tuple[str, str, str | None]]],
        dict[str, str],
        dict[str, Any],
    ]:
        """What ``verify()`` reports about key rows and what
        ``_repair_keys()`` acts on, both leaving alone anything an
        ``append_once()`` call wrote in the last ``_KEYED_IN_FLIGHT_SECONDS``.

        Returns ``(by_key, rows, plan)``. ``plan`` maps each key hash that
        needs work to ``{"keep": (rank, raw, tok) | None, "remove": [...],
        "drop_row": bool, "create_row": bool}``.
        """
        by_key = self._keyed_by_hash(pairs)
        rows = self._key_rows()
        plan: dict[str, Any] = {}
        for key_hash, raw_k in rows.items():
            if key_hash in by_key:
                continue
            named = self._parse_key_row(raw_k)
            if named is not None and self._in_flight(named.tok):
                continue  # a call may be writing its head right now
            plan[key_hash] = {
                "keep": None,
                "remove": [],
                "drop_row": True,
                "create_row": False,
                "hint": named.rank if named is not None else None,
            }
        for key_hash, keyed in by_key.items():
            named = self._parse_key_row(rows.get(key_hash))
            keep = None
            if named is not None:
                keep = next((h for h in keyed if (h[2] or "") == named.tok), None)
                if keep is None and self._in_flight(named.tok):
                    # The row names a head this read did not see, written by
                    # a call that may still be running (its head landed after
                    # the read): leave the whole key alone.
                    continue
            drop_row = rows.get(key_hash) is not None and keep is None
            if keep is None:
                aged = [h for h in keyed if not self._in_flight(h[2])]
                if not aged:
                    continue  # every head is a running call's
                keep = max(aged, key=lambda h: h[2] or "")
            remove = [h for h in keyed if h is not keep and not self._in_flight(h[2])]
            create_row = keep is not None and (named is None or drop_row)
            if create_row and self._in_flight(keep[2]):
                create_row = False
            if remove or drop_row or create_row:
                plan[key_hash] = {
                    "keep": keep,
                    "remove": remove,
                    "drop_row": drop_row,
                    "create_row": create_row,
                    "hint": named.rank if named is not None else None,
                }
        return by_key, rows, plan

    def _key_report(self, pairs: list[tuple[str, str]]) -> dict[str, Any]:
        """The key-row part of ``verify()``'s report; see there."""
        by_key, rows, plan = self._key_findings(pairs)
        dangling: list[str | None] = []
        duplicates: list[str] = []
        unkeyed: list[str] = []
        for key_hash, work in plan.items():
            if work["drop_row"]:
                dangling.append(work["hint"])
            if work["remove"]:
                duplicates.extend([work["keep"][0], *(h[0] for h in work["remove"])])
            if work["create_row"]:
                unkeyed.extend(
                    h[0] for h in by_key.get(key_hash, []) if not self._in_flight(h[2])
                )
        return {
            "key_rows": len(rows),
            "dangling_key_rows": dangling,
            "duplicate_keyed_items": sorted(set(duplicates)),
            "unkeyed_keyed_items": sorted(set(unkeyed)),
        }

    def _repair_keys(
        self, pairs: list[tuple[str, str]]
    ) -> tuple[dict[str, Any], list[tuple[str, str]], dict[str, tuple[str, str]]]:
        """The key repair ``compact()`` runs before it rebalances, and
        ``repair_keys()`` runs alone.

        For each key: with a key row naming one of its heads, that head is
        the item and the other heads are removed; without one (or with a row
        naming none of them, which is deleted as dangling), the head with the
        newest token is kept, the others removed, and a key row is created
        for it once its final rank is known. Key rows naming no head are
        deleted, after a strong re-read of the heads confirms it. Nothing an
        ``append_once()`` call wrote in the last ``_KEYED_IN_FLIGHT_SECONDS``
        is touched.

        Returns ``(counts, surviving_pairs, {key_hash: (rank, tok)})`` for
        the key rows still to create.
        """
        _, rows, plan = self._key_findings(pairs)
        if any(work["keep"] is None for work in plan.values()):
            # A key row that names no head in ``pairs`` may belong to a call
            # that wrote its head after ``pairs`` was read: confirm against a
            # fresh, strongly consistent read before deleting any.
            fresh = self._keyed_by_hash(self._v2_load_full())
            plan = {
                key_hash: work
                for key_hash, work in plan.items()
                if work["keep"] is not None or key_hash not in fresh
            }
        db = self._storage
        removed_ranks: set[str] = set()
        dangling_removed = 0
        to_create: dict[str, tuple[str, str]] = {}
        for key_hash, work in plan.items():
            if work["drop_row"] and self._drop_key_row(key_hash, rows[key_hash]):
                dangling_removed += 1
            for rank, raw, _ in work["remove"]:
                if db.delete_if_value_equals(name=self._v2_item_name(rank), value=raw):
                    self._cascade(raw)
                    removed_ranks.add(rank)
            if work["create_row"]:
                keep = work["keep"]
                to_create[key_hash] = (keep[0], keep[2] or "")
        counts = {
            "duplicate_keyed_items_removed": len(removed_ranks),
            "dangling_key_rows_removed": dangling_removed,
        }
        survivors = [(rank, raw) for rank, raw in pairs if rank not in removed_ranks]
        return counts, survivors, to_create

    def _create_key_rows(
        self,
        to_create: dict[str, tuple[str, str]],
        moved_to: dict[str, str] | None = None,
    ) -> int:
        """Create the key rows ``_repair_keys()`` found missing, at each
        head's final rank. Returns how many were created (a lost create means
        a running call wrote it first)."""
        created = 0
        for key_hash, (rank, tok) in to_create.items():
            final = (moved_to or {}).get(rank, rank)
            if self._storage.create_if_not_exists(
                side=True,
                name=self._key_row(key_hash),
                value=self._key_row_value(final, tok, ""),
            ):
                created += 1
        return created

    def repair_keys(self) -> dict[str, Any]:
        """The key-row repair ``compact()`` makes, without rebalancing.

        Removes duplicate keyed items (keeping the one the key row names),
        deletes dangling key rows and creates missing ones; anything an
        ``append_once()`` call wrote in the last hour is left alone. Like
        ``compact()``, run it with writes quiesced. One strong range read of
        the heads and one prefix read of the key rows (one more range read
        when a key row names no head), plus the writes.

        Returns:
            ``duplicate_keyed_items_removed``, ``dangling_key_rows_removed``
            and ``key_rows_created``.

        Raises:
            ValueError: The list is v1 (it holds no keyed items).
        """
        if not self._db:
            raise RuntimeError("No database connection available")
        if self._dispatch_and_stash() != 2:
            raise self._not_v2_error("repair_keys", hint=False)
        pairs = self._v2_load_full()
        counts, survivors, to_create = self._repair_keys(pairs)
        counts["key_rows_created"] = self._create_key_rows(to_create)
        if any(counts.values()):
            # The counted truth: a repaired item that never had a key row was
            # never counted by the call that stopped before writing it. The
            # cache is dropped, not rebuilt: a second read may have run.
            self._v2_rank_cache = None
            self._v2_touch_metadata(count=len(survivors))
        return counts

    @staticmethod
    def _gens_named_by(raws: Any) -> set[str]:
        """Body generations named in raw heads that do not parse."""
        return {m.group(1) for raw in raws for m in GEN_IN_RAW_RE.finditer(raw)}

    def _span_inventory(
        self,
        span_heads: list[tuple[str, SpanInfo]],
        span_names: list[str],
        *,
        check_content: bool = False,
    ) -> tuple[list[str], dict[str, list[str]]]:
        """Compare the heads' generations with the enumerated body rows.

        Returns ``(broken_ranks, orphan_gens)``: heads whose exact part set
        is not present (or, with ``check_content``, whose bodies do not join
        to the size and digest the head records), and ``{gen: [row names]}``
        for generations no head names. ``check_content`` reads every
        complete generation's bodies strongly: the cost the enumeration
        already pays on DynamoDB, once more."""
        prefix_len = len(span_prefix(self.name))
        by_gen: dict[str, list[str]] = {}
        for name in span_names:
            gen = name[prefix_len:][:30]  # {13 digits}-{16 hex}
            by_gen.setdefault(gen, []).append(name)
        broken: list[str] = []
        named_gens: set[str] = set()
        for rank, span in span_heads:
            named_gens.add(span.gen)
            expected = set(part_names(self.name, span.gen, span.parts))
            if set(by_gen.get(span.gen, [])) != expected:
                broken.append(rank)
            elif check_content and self._read_span(span, consistent=True)[0] is None:
                broken.append(rank)
        orphans = {gen: names for gen, names in by_gen.items() if gen not in named_gens}
        return broken, orphans

    def verify(
        self, identity_key: str | None = None, spans: bool = False
    ) -> dict[str, Any]:
        """Read-only integrity check against stored rows; see ``_v2_verify()``
        for the report. Reports positions and counts only, never item values.

        Args:
            identity_key: Optional field name that identifies an item within
                your data (``"id"``, ``"uuid"``, ...): reports items that
                share it anywhere in the list. Resolves every spanned item
                (one paged body read each).
            spans: Also enumerate the list's body rows in the side partition
                and report ``span_body_rows``, ``orphan_span_gens`` and
                ``broken_spans``. Costs every body byte on DynamoDB, which
                is why it is opt-in.
        """
        self._require_v2()
        return self._v2_verify(identity_key=identity_key, spans=spans)

    def _v2_compact(self, sweep_span_orphans: bool = False) -> dict[str, Any]:
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

        SPANNED ITEMS. A spanned head that moves to a new rank gets a FRESH
        body generation: its bodies are read strongly and written again
        before the new head, and the old head's delete in the cleanup loop
        cascades the old generation. Sharing the generation would make the
        manual recovery above destructive (deleting either duplicate would
        cascade bodies the survivor still names); with a generation per
        head, every duplicate a crash leaves is independently readable. A
        rebalance of a list with many spanned items is therefore a bulk copy,
        O(total spanned bytes). A spanned head whose bodies cannot be read
        stops compact() with ``ListItemSpanError``: run it with
        ``sweep_span_orphans=True`` first. A ``compact()`` racing a spanned
        ``update_by_handle()`` turns today's silent lost update into a 409
        for that item: quiesce writes during repair, as above.

        ``sweep_span_orphans=True`` first enumerates the list's body rows
        once (every body byte, on DynamoDB) and removes (a) body generations
        no head names that are older than ``_SPAN_ORPHAN_MIN_AGE_SECONDS``
        (younger ones may belong to an append that has not written its head
        yet), reported as ``orphan_span_gens_removed``, and (b) heads whose
        bodies are not all there, reported as ``broken_spans_removed`` --
        the item is lost already; this makes the list readable again.

        KEYED ITEMS (``append_once()``). Before rebalancing, the repair
        ``repair_keys()`` makes runs: a key with two or more heads keeps the
        one its key row names and removes the others
        (``duplicate_keyed_items_removed``); a keyed head no key row names
        keeps the newest-token copy and gets its key row, at its final rank
        (``key_rows_created``); a key row naming no head is deleted
        (``dangling_key_rows_removed``). Anything an ``append_once()`` call
        wrote in the last hour is left alone. The key repair runs before the
        spanned-body copy check below and is not undone if a span cannot be
        read. Key rows' hints are not
        remapped when ranks move: a repeat finds a moved head by scan and
        repairs its own hint.

        Cost: two item ranges, plus every moved spanned item's bodies
        (read and written), plus the deletes, plus two prefix reads of the
        list's key rows (small); with the flag, every body byte once more.
        """
        report = self._v2_verify()

        if not self._db:
            raise RuntimeError("No database connection available")

        if sweep_span_orphans:
            report.update(self._sweep_spans())

        pairs = self._v2_load_full()
        key_counts, pairs, key_rows_to_create = self._repair_keys(pairs)
        report.update(key_counts)
        n = len(pairs)
        old_ranks = [rank for rank, _ in pairs]
        old_names = {self._v2_item_name(rank) for rank in old_ranks}
        target_ranks = fi.generate_n_keys_between(None, None, n)

        # Copy every spanned head that will move to a fresh generation
        # BEFORE the first head is written: a span that cannot be read must
        # stop compact() with nothing moved, not part-way through the write
        # loop with some items already duplicated at new ranks. Copies
        # already made are deleted again (no head names them yet).
        copies: dict[str, tuple[str, SpanInfo | None]] = {}
        try:
            for (old_rank, value), target_rank in zip(pairs, target_ranks, strict=True):
                if target_rank != old_rank:
                    copies[old_rank] = self._copy_span_head(value, old_rank)
        except BaseException:
            for _, copied_span in copies.values():
                self._span_delete_bodies(copied_span)
            raise

        written_ranks: list[str] = []
        # Old heads overwritten in place with a fresh generation (a retry
        # landing back on its own rank): their old generation is cascaded
        # with the cleanup below.
        rewritten_in_place: list[str] = []
        # On a failure part-way, the copies of items whose head was never
        # written are deleted again; only a copy whose write was in flight
        # (an unknown outcome) is kept.
        written_old: set[str] = set()
        in_flight: str | None = None
        try:
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
                        new_value, new_span = copies[old_rank]
                        item_db = self._storage
                        # A fault inside set() has an unknown outcome: this
                        # copy's bodies stay (an orphan for the aged sweep if
                        # the head did not land), see _write_spanning(). A
                        # False is known not landed.
                        in_flight = old_rank
                        ok = item_db.put(name=new_name, value=new_value)
                        in_flight = None
                        if not ok:
                            raise RuntimeError(
                                f"list item write failed for '{self.name}' during compact()"
                            )
                        written_old.add(old_rank)
                        if rank == old_rank and new_span is not None:
                            rewritten_in_place.append(value)
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

        except BaseException:
            for copied_rank, (_, copied_span) in copies.items():
                if copied_rank not in written_old and copied_rank != in_flight:
                    self._span_delete_bodies(copied_span)
            raise

        survivors = set(written_ranks)
        for old_rank, old_value in pairs:
            if old_rank not in survivors:
                del_db = self._storage
                if not del_db.remove(name=self._v2_item_name(old_rank)):
                    raise RuntimeError(
                        f"list item write failed for '{self.name}' during compact() cleanup"
                    )
                # The moved copy has its own generation; the old one goes
                # with its head.
                self._cascade(old_value)
        for old_value in rewritten_in_place:
            self._cascade(old_value)

        # Key rows for keyed heads that had none, at their final rank.
        report["key_rows_created"] = self._create_key_rows(
            key_rows_to_create, dict(zip(old_ranks, written_ranks, strict=True))
        )

        self._v2_rank_cache = sorted(written_ranks)
        # compact() just counted every row it rewrote -- write the exact
        # truth back to count_hint rather than leaving whatever drift
        # accumulated before this repair ran.
        self._save_metadata({"count_hint": n})
        return report

    def _copy_span_head(self, raw: str, rank: str) -> tuple[str, SpanInfo | None]:
        """For compact(): the value to write for a head moving off
        ``rank``. A spanned head gets its bodies copied to a fresh
        generation (read strongly) and a head naming it; anything else is
        written as it is. Returns ``(head, new_span)``."""
        try:
            env = parse(raw)
        except EnvelopeError:
            return raw, None
        if env is None or env.span is None:
            return raw, None
        value_str, found = self._read_span(env.span, consistent=True)
        if value_str is None:
            raise ListItemSpanError(
                self.name,
                rank,
                expected_parts=env.span.parts,
                found_parts=found,
            )
        span = self._write_bodies(value_str)
        return wrap(span=span, key=env.key, tok=env.tok, extra=env.extra), span

    def _sweep_spans(self) -> dict[str, Any]:
        """compact(sweep_span_orphans=True)'s sweep: one enumeration of the
        list's body rows, then remove aged orphan generations and heads
        whose bodies are not all there. See ``_v2_compact()``."""
        pairs = self._v2_load_full()
        span_heads, malformed = self._span_heads(pairs)
        span_names = self._aux_names("span")
        broken, orphans = self._span_inventory(
            span_heads, span_names, check_content=True
        )
        raw_by_rank = dict(pairs)
        # Malformed heads first. One with the library marker names no
        # readable item: removing it makes the list readable again. One
        # without it (not valid JSON) is left for an operator. Either way
        # the bodies a malformed head names survive this run (a head damaged
        # in a side field may still have intact bodies); the warning names
        # them, and they are ordinary orphans for the next sweep once their
        # head is gone.
        malformed_removed = 0
        malformed_kept: list[str] = []
        gens_by_rank = {r: self._gens_named_by([raw_by_rank[r]]) for r in malformed}
        for rank in malformed:
            raw = raw_by_rank[rank]
            if carries_library_marker(raw) and self._storage.delete_if_value_equals(
                name=self._v2_item_name(rank),
                value=raw,
            ):
                malformed_removed += 1
                logger.warning(
                    "List '%s' (actor %s): removed the item at rank %r "
                    "(%d bytes), whose head was a malformed storage envelope; "
                    "the body generation(s) it named, %s, are kept until the "
                    "next sweep",
                    self.name,
                    self.actor_id,
                    rank,
                    len(raw),
                    sorted(gens_by_rank[rank]) or "none",
                )
            else:
                malformed_kept.append(rank)
        for gens in gens_by_rank.values():
            for gen in gens:
                orphans.pop(gen, None)
        span_by_rank = dict(span_heads)
        aux = self._aux_or_none()
        broken_removed = 0
        for rank in broken:
            if self._storage.delete_if_value_equals(
                name=self._v2_item_name(rank),
                value=raw_by_rank[rank],
            ):
                broken_removed += 1
                self._span_delete_bodies(span_by_rank[rank])
                self._retire_key_row(raw_by_rank[rank])
                logger.warning(
                    "List '%s' (actor %s): removed the item at rank %r, whose "
                    "body rows were missing or did not match its head (a "
                    "broken span)",
                    self.name,
                    self.actor_id,
                    rank,
                )
        orphans_removed = 0
        for gen, names in orphans.items():
            if gen_age_seconds(gen) < _SPAN_ORPHAN_MIN_AGE_SECONDS:
                continue
            if aux is not None:
                self._storage.batch_delete(side=True, names=names)
            orphans_removed += 1
        if broken_removed or malformed_removed:
            self._v2_rank_cache = None
        return {
            "span_body_rows": len(span_names),
            "orphan_span_gens": len(orphans),
            "broken_spans": broken,
            "orphan_span_gens_removed": orphans_removed,
            "broken_spans_removed": broken_removed,
            "malformed_heads_removed": malformed_removed,
            # Malformed heads still in place: not removable here (no
            # library marker) or changed under the sweep.
            "malformed_heads_kept": len(malformed_kept),
        }

    def sweep_span_orphans(self) -> dict[str, Any]:
        """Remove what spanned items leave behind, without rebalancing.

        v2 only. One enumeration of the list's body rows in the side
        partition (every body byte, on DynamoDB), then: body generations no
        head names that are older than an hour (younger ones may belong to
        an append still in flight), heads whose bodies are not all there
        (the item is lost already; this makes the list readable again), and
        heads that are malformed envelopes with the library marker (a head
        that is not valid JSON is reported, and kept with its bodies). No head is moved or rewritten,
        so this costs no copy of any body, unlike
        ``compact(sweep_span_orphans=True)``, which also rebalances.

        Returns:
            ``span_body_rows``, ``orphan_span_gens``, ``broken_spans`` (as
            found) and ``orphan_span_gens_removed``,
            ``broken_spans_removed``, ``malformed_heads_removed`` and
            ``malformed_heads_kept`` (heads not valid JSON, which need
            ``delete_by_handle()``, or ones that changed under the sweep).

        Raises:
            ValueError: The list is v1.
        """
        if not self._is_v2():
            raise self._not_v2_error("sweep_span_orphans")
        return self._sweep_spans()

    def compact(
        self, allow_reverted: bool = False, sweep_span_orphans: bool = False
    ) -> dict[str, Any]:
        """Rebalance the list's rank keys; see ``_v2_compact()``.

        Args:
            allow_reverted: Accepted for the property list's signature; the
                core has no reverted migration to refuse.
            sweep_span_orphans: Also remove aged orphan body generations and
                heads whose bodies are missing, after one enumeration of the
                list's body rows.

        Returns:
            The ``verify()`` report this call acted on (taken before any
            write), with what the rebalance did.
        """
        del allow_reverted
        self._require_v2()
        return self._v2_compact(sweep_span_orphans=sweep_span_orphans)
