"""
Database backend protocols defining the contract all backends must implement.

These protocols use typing.Protocol to enable structural typing - any class
implementing these methods will be compatible, without explicit inheritance.

All database backends (DynamoDB, PostgreSQL, etc.) must implement these protocols
to ensure consistent interfaces across the ActingWeb codebase.

The fault contract (3.16), which every method below follows unless its own
docstring says otherwise:

- **Absence is an answer.** A read that finds nothing answers ``None``,
  ``[]``, ``{}`` or ``False`` as documented per method.
- **A fault raises.** A backend fault (throttle, timeout, connection error,
  a query error) raises ``actingweb.db.exceptions.DbError``, chained to the
  backend exception. It is never answered like absence.
- **``strict=False`` restores the folded answer** on the reads that take it
  (every ``get`` but ``DbPropertyProtocol.get``, which takes none and always
  raises, and every ``fetch`` and ``get_bucket``): the fault is logged at ERROR
  and answered as absence. Only display reads should pass it.
- **A delete on a loaded handle is confirmed.** It answers True when the row
  is gone after the call; a row that was already absent counts. A fault
  raises ``DbError``. A delete without a handle answers False.
- **Conditional operations are exempt.** ``delete_attr_conditional``,
  ``conditional_update_attr`` and every ``*_if_*`` method answer True only
  when THIS call changed the row; single-use consumption depends on it.
  ``create_attr_if_absent`` is the exception to the exception: it raises
  ``DbError`` on a fault, because its callers (a retried create) must tell a
  lost race from an outage. ``delete_attr_conditional`` and
  ``conditional_update_attr`` answer False on a fault (callers tell the two
  apart with ``get_attr_strict``).
- **Writes raise.** A ``create``, ``modify`` or ``set`` that faults raises
  ``DbError``; False is reserved for the documented non-fault refusals
  (missing arguments or handle, an id that is taken).
"""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

# =============================================================================
# Actor Protocols
# =============================================================================


@runtime_checkable
class DbActorProtocol(Protocol):
    """Protocol for actor database operations.

    The constructor takes a keyword-only ``unique_creator: bool = False``
    (``actingweb.db.get_actor`` passes ``config.unique_creator``). When it is
    set, a backend **must** enforce one actor per non-exempt creator (the
    rules are in :mod:`actingweb.db.creator_rules`): a create or creator
    change that would make a second holder raises
    :class:`~actingweb.db.exceptions.CreatorTaken`, and
    :meth:`replace_creator_holder`, :meth:`get_creator_holder` and
    :meth:`release_stale_creator` work. A
    custom backend that does not accept the argument fails at construction,
    never silently.
    """

    handle: Any | None

    def get(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, Any] | None:
        """
        Retrieve actor by ID.

        Args:
            actor_id: The actor ID to retrieve
            strict: When False, a read fault answers None instead of raising

        Returns:
            dict with keys: id, creator, passphrase, or None if not found
        """
        ...

    def get_by_creator(
        self,
        creator: str | None = None,
        *,
        strict: bool = True,
        consistent: bool = False,
        ids_only: bool = False,
    ) -> list[dict[str, Any]] | None:
        """
        Get actors by creator field.

        Args:
            creator: The creator email to search for
            strict: When False, a read fault answers None instead of raising
            consistent: Re-read each listed row consistently and leave out an
                actor the index lists whose row is gone (DynamoDB's creator
                index is eventually consistent; PostgreSQL always is). The
                adoption rule passes it.
            ids_only: Answer ``[{"id": ...}]`` with no per-row read; a
                caller that reads only some rows lists them cheaply.

        Returns:
            List of dicts (possibly empty), or None if no creator provided
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        creator: str | None = None,
        passphrase: str | None = None,
        *,
        replace_holder: str | None = None,
    ) -> bool:
        """
        Create new actor.

        Args:
            actor_id: Unique actor ID
            creator: Creator email
            passphrase: Actor passphrase
            replace_holder: With ``unique_creator``, the id of the actor that
                holds ``creator`` now; the create then goes through
                :meth:`replace_creator_holder`

        Returns:
            True when created, False when the id is taken

        Raises:
            CreatorTaken: another actor holds a non-exempt ``creator``
            DbError: on a backend fault
        """
        ...

    def modify(
        self, creator: str | None = None, passphrase: bytes | None = None
    ) -> bool:
        """
        Modify existing actor using self.handle.

        Args:
            creator: New creator email (optional)
            passphrase: New passphrase bytes (optional)

        Returns:
            True on success; False only without a handle or arguments, or
            when the stored row no longer matches the handle.
            A fault raises ``DbError``; a new creator another actor holds
            raises ``CreatorTaken`` (with ``unique_creator``, and on
            PostgreSQL whenever the unique index exists).
        """
        ...

    def replace_creator_holder(
        self,
        old_id: str,
        *,
        actor_id: str,
        creator: str,
        passphrase: str,
    ) -> bool:
        """
        Create ``actor_id`` and move ``creator`` to it from ``old_id``, in one
        atomic step (``unique_creator`` only). ``old_id`` keeps its row; the
        caller removes it afterwards.

        Returns:
            True when created, False when ``actor_id`` is taken

        Raises:
            CreatorTaken: ``creator`` is no longer held by ``old_id``;
                nothing was written
            DbError: on a backend fault
        """
        ...

    def get_creator_holder(
        self, creator: str | None = None, *, strict: bool = True
    ) -> str | None:
        """
        The id of the actor holding a non-exempt ``creator``, read
        consistently (``unique_creator`` only); None when nobody holds it.

        Raises:
            DbError: on a read fault (unless ``strict=False``)
        """
        ...

    def release_stale_creator(self, creator: str, actor_id: str) -> bool:
        """
        Remove the record that says ``actor_id`` holds ``creator``, only if
        a consistent read shows that actor is gone or holds another creator
        now (``unique_creator`` only). True when a record was removed.

        A backend whose holder is the actor row itself (PostgreSQL) has no
        separate record and answers False.

        Raises:
            DbError: on a fault
        """
        ...

    def delete(self) -> bool:
        """
        Delete actor using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


@runtime_checkable
class DbActorListProtocol(Protocol):
    """Protocol for actor list operations."""

    handle: Any | None

    def fetch(self, *, strict: bool = True) -> list[dict[str, Any]] | bool:
        """
        Fetch all actors.

        Returns:
            List of actor dicts (``[]`` when there are none); False on a read
            fault with ``strict=False``
        """
        ...


# =============================================================================
# Property Protocols
# =============================================================================


@runtime_checkable
class DbPropertyProtocol(Protocol):
    """Protocol for property operations.

    Optional capability: a backend's ``DbProperty`` class may declare
    ``MAX_ROW_BYTES: int | None``, the largest row (in bytes) it can store.
    ``Config`` reads it to choose the property-list size defaults: an
    ``int`` gives a span threshold of 390,000 bytes and a 4 MiB item
    ceiling, anything else (``None``, or the attribute absent, which is
    what a custom backend gets by default) turns spanning off and sets no
    ceiling. The application can set both explicitly with
    ``ActingWebApp.with_list_item_limits()``.
    """

    handle: Any | None

    def get(self, actor_id: str | None = None, name: str | None = None) -> str | None:
        """
        Get property value.

        Args:
            actor_id: The actor ID
            name: The property name

        Returns:
            Property value as string, or ``None`` if the row does not exist.
            ``None`` means absence ONLY — a backend fault (throttle, timeout,
            connection error) raises ``DbError``
            (``actingweb.db.exceptions.DbError``), it is never reported as
            absence.
        """
        ...

    def get_actor_id_from_property(
        self,
        name: str | None = None,
        value: str | None = None,
        *,
        strict: bool = True,
    ) -> str | None:
        """
        Reverse lookup: find actor by property value.

        Args:
            name: Property name
            value: Property value to search for

        Returns:
            Actor ID if found, None otherwise
        """
        ...

    def set(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """
        Set property value (empty value deletes).

        Args:
            actor_id: The actor ID
            name: Property name
            value: Property value (None or empty string deletes)

        Returns:
            True on success, False only on failure — callers MUST check the
            return value; a write is not confirmed until this is True.

        Note:
            A ``handle`` cached by a prior ``get()``/``set()`` call for a
            different ``(actor_id, name)`` MUST NOT be reused — implementations
            discard a stale handle and take the fresh-fetch/create path
            whenever the arguments disagree with what the handle was built
            for.
        """
        ...

    def delete(self) -> bool:
        """
        Delete property using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def get_range(
        self,
        actor_id: str | None = None,
        lower: str | None = None,
        upper: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        """
        Range-read property rows whose name falls in ``[lower, upper]``
        (bytewise comparison, INCLUSIVE on both ends).

        Used by v2 list-property storage to read a list's item rows in one
        query instead of one per item. ``upper`` is inclusive because
        DynamoDB's KeyConditionExpression rejects two separate comparisons
        on the same key (no ``>=`` AND ``<``) — callers MUST choose
        ``upper`` as a sentinel value that can never equal a real row name
        (e.g. a delimiter character no real key contains), so the
        inclusive boundary is unobservable in practice.

        Ordering is NOT guaranteed by this method — backends may return
        results in different orders (DynamoDB's natural range-key sort vs.
        an unordered scan), so a caller that needs a specific order MUST
        sort the returned dict's items itself. This is deliberate: it keeps
        ordering behavior identical across backends instead of depending on
        a per-backend implementation detail.

        Args:
            actor_id: The actor ID
            lower: Inclusive lower bound on name
            upper: Inclusive upper bound on name (see above — use a
                sentinel value)
            keys_only: If True, returned values are ``""`` (a projection
                read used when only presence/count/order is needed).
                Cheaper on PostgreSQL, where it is a genuine ``SELECT
                name``. **No capacity saving on DynamoDB**: this is still
                a base-table Query, and AWS documents that requesting a
                subset of attributes "has no impact on the item size
                calculations" for capacity purposes -- it saves network
                bytes and deserialization, not read capacity.
            consistent_read: Defaults to ``True`` -- this preserves today's
                behaviour, and the default does not change. On DynamoDB, an
                eventually consistent read costs HALF the read capacity of
                a strongly consistent one (measured on an 81-row list: 241
                RCU -> 120.5 RCU). PostgreSQL accepts and ignores this --
                its reads are consistent by construction, but the
                parameter is part of the protocol rather than a DynamoDB
                detail leaking upward. Whether a given read may be stale
                is an APPLICATION question: pass ``False`` only where the
                caller cannot have just written the rows it is about to
                read, since a write that has landed may briefly not be
                visible to an eventually consistent read on DynamoDB.

        Returns:
            Dict of ``{name: value}`` (or ``{name: ""}`` when
            ``keys_only``) for rows in the range. Empty dict if none found.

        Raises:
            DbError: On a backend fault.
        """
        ...

    def get_prefix(
        self,
        actor_id: str | None = None,
        prefix: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        """
        Read every property row of ``actor_id`` whose name BEGINS WITH
        ``prefix``.

        The sibling of ``get_range`` above, for the case a range cannot
        express: a prefix has no exact inclusive upper bound. Any
        synthesised sentinel (``prefix + "~"``, ``prefix + "\uffff"``) is a
        guess about which byte sorts last, and it is wrong for names that
        continue past it — so this is a first-class primitive rather than
        arithmetic on ``get_range``'s bounds. DynamoDB has a native
        ``begins_with``; PostgreSQL has ``starts_with()``.

        Ordering is NOT guaranteed, exactly as for ``get_range``: backends
        may return results in different orders, so a caller that needs a
        specific order MUST sort the returned dict's items itself.

        **No Unicode normalization, on either backend.** The comparison is
        over bytes: an NFD prefix does not match an NFC name, nor the
        reverse. Verified on a live PostgreSQL 16.11 under both the libc
        ``en_US.utf8`` and the ICU ``en-US-x-icu`` collations —
        ``starts_with(U&'cafe\0301x', 'café')`` is ``false`` under both,
        which is also what DynamoDB's ``begins_with`` does. That agreement
        is the reason for choosing these two primitives: byte ordering
        itself does NOT agree across collations (``'a' < '{'`` is ``true``
        under libc and ``false`` under ICU), which is why no bound pair can
        be trusted here.

        The failure direction, if a backend ever were inexact, is to
        UNDER-read: a prefix read cannot leak rows from outside the prefix,
        it can only silently truncate. That matters because truncating a v2
        list's item rows while keeping its ``-meta`` row produces ``[]``
        from ``to_list_from_rows()`` with no fallback — an empty list, not
        an error.

        Args:
            actor_id: The actor ID
            prefix: The name prefix. A FALSY prefix (``None`` or ``""``)
                returns ``{}`` without touching the backend: PostgreSQL's
                ``starts_with(x, '')`` is ``true`` for every row, while
                DynamoDB's ``begins_with(name, "")`` is a
                ``ValidationException`` — so "everything" and "an error"
                are what the two backends would otherwise do, and neither
                is a useful answer from a method named for a prefix.
            keys_only: If True, returned values are ``""``. Same trade as
                ``get_range``: cheaper on PostgreSQL (a genuine ``SELECT
                name``), **no capacity saving on DynamoDB**, where a
                projection still pays for the whole item.
            consistent_read: Defaults to ``True``, matching ``get_range``.
                On DynamoDB an eventually consistent read costs HALF the
                read capacity. PostgreSQL accepts and ignores it. Pass
                ``False`` only where the caller cannot have just written
                the rows it is about to read.

        Returns:
            Dict of ``{name: value}`` (or ``{name: ""}`` when
            ``keys_only``) for rows under the prefix. Empty dict if none
            found, and for a falsy prefix.

        Raises:
            DbError: On a backend fault.
        """
        ...

    def create_if_not_exists(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """
        Conditionally create a property row — succeeds only if no row for
        this ``(actor_id, name)`` exists yet.

        Used by v2 list-property storage for collision-free rank-key
        inserts: two writers racing to use the same generated rank produce
        one winner and one ``False``, never a silent overwrite of one
        writer's item by the other's.

        Args:
            actor_id: The actor ID
            name: Property name
            value: Property value (serialized the same way as ``set()``)

        Returns:
            True if the row was created. False if a row already existed at
            this name — a normal outcome (the caller should regenerate the
            key and retry), not a failure.

        Raises:
            DbError: On a backend fault (not a conflict).
        """
        ...

    def delete_if_value_equals(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """
        Conditionally delete a property row — succeeds only if the row
        currently holds exactly ``value``.

        Used by v2 list-property storage wherever the item being deleted is
        coupled to content the caller already read: ``pop()`` returns the
        item it removed, and ``remove()`` deletes the item it matched. An
        unconditional delete cannot honour either promise, because a
        concurrent ``__setitem__`` on that same row between the read and the
        delete would silently discard the other writer's value while
        reporting the one this caller saw — an outcome that corresponds to
        no serial ordering of the two operations.

        ``__delitem__``/``__setitem__`` deliberately do NOT use this:
        "delete whatever is at position i" and last-writer-wins are both
        satisfied by an unconditional write.

        ``value`` must be the RAW STORED STRING the caller read, not a
        re-serialization of a decoded value — round-tripping through
        decode/encode is not guaranteed byte-identical.

        No lookup-table maintenance is performed or needed: ``list:``-
        prefixed names are structurally excluded from indexing by
        ``_should_index_property()`` on both backends.

        Args:
            actor_id: The actor ID
            name: Property name
            value: The exact stored value required for the delete to happen

        Returns:
            True if the row was deleted. False if it held a different value
            or no longer exists — both normal outcomes meaning "re-resolve
            and retry", not failures.

        Raises:
            DbError: On a backend fault (not a condition failure).
        """
        ...

    def set_if_value_equals(
        self,
        actor_id: str | None = None,
        name: str | None = None,
        expected: Any = None,
        value: Any = None,
    ) -> bool:
        """
        Conditionally set a property row's value — succeeds only if the
        row currently holds exactly ``expected``.

        Same contract family as ``delete_if_value_equals``: a differing
        value and a vanished row both fail the condition the same way, and
        both mean "re-resolve and retry" to the caller, not failure. This
        is compare-and-swap, the write-side counterpart to that method's
        conditional delete — used wherever a caller wants to update content
        it has already read without silently clobbering a concurrent
        writer's change (list metadata rewrites; a value-addressed
        update-in-place via a handle).

        ``expected`` must be the RAW STORED STRING the caller read, not a
        re-serialization of a decoded value — same requirement
        ``delete_if_value_equals`` documents, for the same reason.

        **A conditional write whose expression evaluates false still
        consumes write capacity on DynamoDB.** A retry loop built on this
        primitive must not be written as though a losing attempt is free.

        No lookup-table maintenance is performed or needed: ``list:``-
        prefixed names are structurally excluded from indexing by
        ``_should_index_property()`` on both backends.

        Args:
            actor_id: The actor ID
            name: Property name
            expected: The exact stored value required for the set to happen
            value: The new value to write

        Returns:
            True if the row was updated. False if it held a different
            value or no longer exists — both normal outcomes meaning
            "re-resolve and retry", not failures.

        Raises:
            DbError: On a backend fault (not a condition failure).
        """
        ...

    def get_last_in_range(
        self,
        actor_id: str | None = None,
        lower: str | None = None,
        upper: str | None = None,
    ) -> str | None:
        """
        Return the NAME of the bytewise-greatest row in ``[lower, upper]``
        (inclusive on both ends, same bounds convention as ``get_range``),
        or ``None`` if the range is empty.

        Unlike ``get_range``, whose contract deliberately guarantees no
        ordering, byte-order maximality IS this method's contract on both
        backends — it exists to find a v2 list's highest rank key without
        reading the whole list (Phase 9B's ``append()``).

        **Always strongly consistent, with no caller override.** A stale
        maximum here is a mid-list append by another route: the same
        reasoning ``_v2_ensure_rank_cache()`` and ``items_with_handles()``
        already carry.

        No lookup-table maintenance is performed or needed: same exclusion
        as ``get_range``.

        Args:
            actor_id: The actor ID
            lower: Inclusive lower bound on name
            upper: Inclusive upper bound on name (see ``get_range`` — use a
                sentinel value)

        Returns:
            The bytewise-greatest row name in the range, or ``None`` if no
            row falls in it.

        Raises:
            DbError: On a backend fault.
        """
        ...

    def batch_delete(
        self, actor_id: str | None = None, names: list[str] | None = None
    ) -> None:
        """
        Unconditionally delete every named row in one batched operation.

        For an UNCONDITIONAL, bulk delete only -- ``clear()``/``delete()``
        wiping every row of one list, or an actor's whole property
        partition, where every named row is meant to go regardless of its
        current content. Never for a delete that depends on what a row
        currently holds (a single item, or any subset selected by value) --
        that is what ``delete_if_value_equals`` exists for, and DynamoDB's
        ``BatchWriteItem`` cannot express a condition per item.

        DynamoDB: chunks into groups of 25 (the ``BatchWriteItem`` limit)
        and retries unprocessed items with backoff -- both provided by
        PynamoDB's ``Model.batch_write()`` context manager, not
        hand-rolled here. Note that batching saves round trips, not
        capacity: ``BatchWriteItem`` consumes the same number of write
        capacity units as the equivalent individual deletes. PostgreSQL:
        a single ``DELETE ... WHERE id = %s AND name = ANY(%s)``.

        No lookup-table maintenance is performed -- same exclusion
        ``create_if_not_exists``/``delete_if_value_equals``/
        ``set_if_value_equals`` document: callers of this method delete
        ``list:``-prefixed rows, which are structurally excluded from
        indexing.

        Args:
            actor_id: The actor ID
            names: The exact row names to delete. A name that does not
                exist is not an error -- deleting nothing is deleting
                nothing, on both backends.

        Raises:
            DbError: On a backend fault, including DynamoDB's unprocessed-
                item retry budget being exhausted.
        """
        ...


@runtime_checkable
class DbPropertyListProtocol(Protocol):
    """Protocol for property list operations."""

    handle: Any | None
    actor_id: str | None
    props: dict[str, str] | None

    def fetch(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, str] | None:
        """
        Retrieve all properties for an actor (excluding list: properties).

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {property_name: property_value}, or None
        """
        ...

    def fetch_all_including_lists(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, str] | None:
        """
        Retrieve ALL properties including list properties.

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {property_name: property_value}, or None
        """
        ...

    def delete(self) -> bool:
        """
        Delete all properties for the actor.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


# =============================================================================
# Trust Protocols
# =============================================================================


@runtime_checkable
class DbTrustProtocol(Protocol):
    """Protocol for trust relationship operations."""

    handle: Any | None

    def get(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        token: str | None = None,
        *,
        strict: bool = True,
    ) -> dict[str, Any] | None:
        """
        Retrieve trust from database.

        Args:
            actor_id: The actor ID
            peerid: Peer ID (takes precedence over token)
            token: Secret token for lookup

        Returns:
            Trust dict with all fields, or None if not found
        """
        ...

    def modify(
        self,
        baseuri: str | None = None,
        secret: str | None = None,
        desc: str | None = None,
        approved: bool | None = None,
        verified: bool | None = None,
        verification_token: str | None = None,
        peer_approved: bool | None = None,
        # Unified trust attributes
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | datetime | None = None,
        last_accessed: str | datetime | None = None,
        last_connected_via: str | None = None,
        # OAuth2 client metadata
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
        # Peer capability tracking
        aw_supported: str | None = None,
        aw_version: str | None = None,
        capabilities_fetched_at: str | datetime | None = None,
    ) -> bool:
        """
        Modify trust using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        baseuri: str = "",
        peer_type: str = "",
        relationship: str = "",
        secret: str = "",
        approved: bool = False,
        verified: bool = False,
        peer_approved: bool = False,
        verification_token: str = "",
        desc: str = "",
        # Unified trust attributes
        peer_identifier: str | None = None,
        established_via: str | None = None,
        created_at: str | datetime | None = None,
        last_accessed: str | datetime | None = None,
        last_connected_via: str | None = None,
        # OAuth2 client metadata
        client_name: str | None = None,
        client_version: str | None = None,
        client_platform: str | None = None,
        oauth_client_id: str | None = None,
        # Peer capability tracking
        aw_supported: str | None = None,
        aw_version: str | None = None,
        capabilities_fetched_at: str | datetime | None = None,
    ) -> bool:
        """
        Create new trust.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def delete(self) -> bool:
        """
        Delete trust using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    @staticmethod
    def is_token_in_db(actor_id: str | None = None, token: str | None = None) -> bool:
        """
        Check if token exists in database.

        Args:
            actor_id: The actor ID
            token: Secret token to check

        Returns:
            True if token found, False otherwise
        """
        ...


@runtime_checkable
class DbTrustListProtocol(Protocol):
    """Protocol for trust list operations."""

    handle: Any | None
    actor_id: str | None
    trusts: list[dict[str, Any]]

    def fetch(
        self, actor_id: str | None, *, strict: bool = True
    ) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all trusts for an actor.

        Args:
            actor_id: The actor ID
            strict: Raise on a backend read fault instead of answering with
                an empty list (PostgreSQL catches faults; DynamoDB raises
                either way).

        Returns:
            List of trust dicts, or empty list
        """
        ...

    def delete(self) -> bool:
        """
        Delete all trusts for the actor.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


# =============================================================================
# PeerTrustee Protocols
# =============================================================================


@runtime_checkable
class DbPeerTrusteeProtocol(Protocol):
    """Protocol for peer trustee operations."""

    handle: Any | None

    def get(
        self,
        actor_id: str | None = None,
        peer_type: str | None = None,
        peerid: str | None = None,
        *,
        strict: bool = True,
    ) -> dict[str, Any] | bool | None:
        """
        Retrieve peer trustee from database.

        Args:
            actor_id: The actor ID
            peer_type: Type of peer (alternative to peerid)
            peerid: Peer ID

        Returns:
            PeerTrustee dict, False when several peers match ``peer_type``
            (pass ``peerid``), or None if not found
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        peer_type: str | None = None,
        baseuri: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """
        Create new peer trustee.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def modify(
        self,
        peer_type: str | None = None,
        baseuri: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """
        Modify peer trustee using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def delete(self) -> bool:
        """
        Delete peer trustee using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


@runtime_checkable
class DbPeerTrusteeListProtocol(Protocol):
    """Protocol for peer trustee list operations."""

    handle: Any | None
    actor_id: str | None
    peertrustees: list[dict[str, Any]] | None

    def fetch(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all peer trustees for an actor.

        Args:
            actor_id: The actor ID
            strict: Raise on a backend read fault instead of answering ``[]``

        Returns:
            List of peer trustee dicts, or empty list
        """
        ...

    def delete(self) -> bool:
        """
        Delete all peer trustees for the actor.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


# =============================================================================
# Subscription Protocols
# =============================================================================


@runtime_checkable
class DbSubscriptionProtocol(Protocol):
    """Protocol for subscription operations."""

    handle: Any | None

    def get(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
        *,
        strict: bool = True,
    ) -> dict[str, Any] | None:
        """
        Retrieve subscription from database.

        Args:
            actor_id: The actor ID
            peerid: Peer ID
            subid: Subscription ID

        Returns:
            Subscription dict, or None if not found
        """
        ...

    def modify(
        self,
        peerid: str | None = None,
        subid: str | None = None,
        granularity: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        seqnr: int | None = None,
        callback: bool | None = None,
    ) -> bool:
        """
        Modify subscription using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def increment_seq(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
    ) -> int | None:
        """
        Atomically add 1 to the stored sequence number and return the new one.

        Must be a single atomic update on the backend (an ``ADD`` or a
        ``seqnr = seqnr + 1``), never a read followed by a write: concurrent
        changes to one subscription must each get their own number, as the
        protocol requires a sequence number per change. Works on the loaded
        handle, or, with all three keys, on that row without reading it
        first.

        Returns:
            The new sequence number; None when the row does not exist.
            A fault raises ``DbError`` (the increment may have landed).
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
        granularity: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        seqnr: int = 1,
        callback: bool = False,
    ) -> bool:
        """
        Create new subscription.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def delete(self) -> bool:
        """
        Delete subscription using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


@runtime_checkable
class DbSubscriptionListProtocol(Protocol):
    """Protocol for subscription list operations."""

    handle: Any | None
    actor_id: str | None
    subscriptions: list[dict[str, Any]]

    def fetch(
        self, actor_id: str | None, *, strict: bool = True
    ) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all subscriptions for an actor.

        Args:
            actor_id: The actor ID
            strict: Raise on a backend read fault instead of answering with
                an empty list (PostgreSQL catches faults; DynamoDB raises
                either way).

        Returns:
            List of subscription dicts, or empty list
        """
        ...

    def delete(self) -> bool:
        """
        Delete all subscriptions for the actor.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


# =============================================================================
# SubscriptionDiff Protocols
# =============================================================================


@runtime_checkable
class DbSubscriptionDiffProtocol(Protocol):
    """Protocol for subscription diff operations."""

    handle: Any | None

    def get(
        self,
        actor_id: str | None = None,
        subid: str | None = None,
        seqnr: int | None = None,
        *,
        strict: bool = True,
    ) -> dict[str, Any] | None:
        """
        Retrieve subscription diff from database.

        Args:
            actor_id: The actor ID
            subid: Subscription ID
            seqnr: Sequence number (optional, finds lowest if not specified)

        Returns:
            SubscriptionDiff dict, or None if not found
        """
        ...

    def create(
        self,
        actor_id: str | None = None,
        subid: str | None = None,
        diff: str = "",
        seqnr: int = 1,
    ) -> bool:
        """
        Create new subscription diff.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def delete(self) -> bool:
        """
        Delete subscription diff using self.handle.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


@runtime_checkable
class DbSubscriptionDiffListProtocol(Protocol):
    """Protocol for subscription diff list operations."""

    handle: Any | None
    diffs: list[dict[str, Any]]
    actor_id: str | None
    subid: str | None

    def fetch(
        self,
        actor_id: str | None = None,
        subid: str | None = None,
        *,
        strict: bool = True,
    ) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve subscription diffs for an actor.

        Args:
            actor_id: The actor ID
            subid: Optional subscription ID to filter

        Returns:
            List of diff dicts, or empty list
        """
        ...

    def delete(self, seqnr: int | None = None) -> bool:
        """
        Delete subscription diffs.

        Args:
            seqnr: Optional sequence number (deletes up to and including this seqnr)

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


# =============================================================================
# Attribute Protocols
# =============================================================================


@runtime_checkable
class DbAttributeProtocol(Protocol):
    """Protocol for attribute operations (internal storage)."""

    @staticmethod
    def get_bucket(
        actor_id: str | None = None, bucket: str | None = None, *, strict: bool = True
    ) -> dict[str, dict[str, Any]] | None:
        """
        Get all attributes from a bucket.

        Args:
            actor_id: The actor ID
            bucket: Bucket name

        Returns:
            Dict of {attr_name: {"data": ..., "timestamp": ...}}. An empty
            bucket is ``{}``. ``None`` only for missing arguments, or a read
            fault with ``strict=False``. Expired rows are returned: a sweep
            that reads a bucket to find what to delete must find them.
        """
        ...

    @staticmethod
    def get_attr(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        *,
        strict: bool = True,
    ) -> dict[str, Any] | None:
        """
        Get single attribute from bucket.

        Args:
            actor_id: The actor ID
            bucket: Bucket name
            name: Attribute name
            strict: When False, a read fault answers None instead of raising

        Returns:
            Dict with "data" and "timestamp", or None when absent. An
            expired row is returned; only ``get_attr_strict`` hides it.
        """
        ...

    @staticmethod
    def get_attr_strict(
        actor_id: str | None = None, bucket: str | None = None, name: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get single attribute, distinguishing absence from failure.

        The one read that hides expired rows (``ttl_timestamp`` in the past),
        for decision reads that must not act on a stale token. None for an
        absent or expired row; a fault raises.

        Returns:
            Dict with "data" and "timestamp", or None if the attribute does
            not exist or has expired.

        Raises:
            DbError: on a read fault.
        """
        ...

    @staticmethod
    def set_attr(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        data: Any = None,
        timestamp: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Set attribute value.

        Args:
            actor_id: The actor ID
            bucket: Bucket name
            name: Attribute name
            data: Data to store (JSON-serializable)
            timestamp: Optional timestamp
            ttl_seconds: Optional TTL in seconds

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    def delete_attr(
        self,
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
    ) -> bool:
        """
        Delete single attribute.

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    @staticmethod
    def delete_attr_conditional(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
    ) -> bool:
        """
        Atomically delete a single attribute, reporting whether THIS call
        removed an existing item.

        Unlike ``delete_attr`` (which reports only that the delete statement
        ran), this returns True only when the row actually existed and was
        removed by this call. Concurrent callers racing to delete the same
        attribute therefore see exactly one True; all others get False. This
        is the primitive behind single-use / atomic-consume semantics such as
        mobile-ticket redemption.

        Args:
            actor_id: The actor ID
            bucket: Bucket name
            name: Attribute name

        Returns:
            True if this call removed an existing item, False otherwise
            (item absent, already consumed by a concurrent caller, or error)
        """
        ...

    @staticmethod
    def conditional_update_attr(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        old_data: Any = None,
        new_data: Any = None,
        timestamp: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Conditionally update an attribute only if current data matches old_data.

        This provides atomic compare-and-swap functionality for race-free updates.

        Args:
            actor_id: The actor ID
            bucket: Bucket name
            name: Attribute name
            old_data: Expected current data value (for comparison)
            new_data: New data to set if current matches old_data
            timestamp: Optional timestamp
            ttl_seconds: When given, the same write sets the row's storage
                TTL (as ``set_attr`` does). Never an upsert: a row that is
                gone stays gone.

        Returns:
            True if update succeeded (current matched old_data), False otherwise
            (a mismatch, a missing row, or a backend fault; use
            ``get_attr_strict`` to tell the last apart)
        """
        ...

    @staticmethod
    def create_attr_if_absent(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        data: Any = None,
        timestamp: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Create an attribute only if no live row holds its name (atomic).

        One conditional write; never an overwrite of a live row. An
        expired-but-present row (``ttl_timestamp`` in the past, the rule
        ``get_attr_strict`` applies) counts as absent and is replaced in the
        same write.

        Args:
            actor_id: The actor ID
            bucket: Bucket name
            name: Attribute name
            data: The data to store (stored as given; a falsy value is
                stored, not a delete)
            timestamp: Optional timestamp
            ttl_seconds: When given, the row's storage TTL, as ``set_attr``:
                the stored deadline includes ``TTL_CLOCK_SKEW_BUFFER``, so the
                name frees up ``ttl_seconds`` plus one hour after the write

        Returns:
            True when this call created the row or replaced an expired one
            (both mean "you won"), or when the row already holds JSON-equal
            data to what this call wrote (an SDK-retried create that landed
            must not be reported as lost). False when a live row holds the
            name, or another bucket owns the key.

        Raises:
            ValueError: ``actor_id``, ``bucket`` or ``name`` is missing (a
                False there would read as "lost").
            DbError: on a backend fault, including a fault while reading the
                row back after a lost condition.

        Two callers that write identical data both get True. A caller that
        needs exactly one winner puts a per-call nonce in ``data`` (the
        ``consume_id`` pattern of single-use consumption). Do not use it on
        names an untrusted party chooses, in a bucket where an expired row
        still carries meaning (a consumed marker under ``consumed_ttl``): it
        replaces an expired row. A caller that then reads the row should use
        ``get_attr_strict`` to see the same expiry rule (``get_attr`` returns
        expired rows).
        """
        ...

    @staticmethod
    def delete_bucket(actor_id: str | None = None, bucket: str | None = None) -> bool:
        """
        Delete entire bucket.

        Args:
            actor_id: The actor ID
            bucket: Bucket name

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...

    @staticmethod
    def delete_expired(
        now_epoch: int | None = None, buckets: list[str] | None = None
    ) -> int:
        """
        Delete attributes whose ``ttl_timestamp`` is in the past.

        A set-based purge of TTL-expired rows, used for bounded cleanup of
        token-like buckets without scanning every row. Backends that expire rows
        natively (e.g. DynamoDB TTL) may treat this as a no-op and return 0.

        Args:
            now_epoch: Cutoff Unix timestamp; rows with ``ttl_timestamp`` below
                it are deleted. Defaults to the current time.
            buckets: Optional list of bucket names to restrict the purge to. When
                omitted, all expired rows are eligible.

        Returns:
            Number of rows deleted (0 when the backend relies on native TTL).
        """
        ...

    @staticmethod
    def delete_by_chain(
        actor_id: str | None = None,
        buckets: list[str] | None = None,
        chain_id: str | None = None,
        defer_name: str | None = None,
    ) -> int:
        """
        Delete attributes whose stored ``data['chain_id']`` matches ``chain_id``.

        Backs refresh-token family (chain) revocation. PostgreSQL uses an
        expression index for an O(chain) delete; DynamoDB scans the given
        buckets and filters in memory. Both raise on a fault. The scan is
        routine (every SPA logout and revoke), acceptable while the two SPA
        token buckets together stay under about 1 MB (about 3,000 rows);
        beyond that a GSI on a promoted ``chain_id`` is due.

        Args:
            actor_id: Storage partition id the tokens live under.
            buckets: Bucket names to search.
            chain_id: The chain/family identifier to delete.
            defer_name: A row name to delete last. A backend that deletes row
                by row (DynamoDB) removes it only after every other row, so a
                fault part-way leaves it in place; a set-based delete
                (PostgreSQL) is atomic and ignores it.

        Returns:
            Number of rows deleted.
        """
        ...


@runtime_checkable
class DbAttributeBucketListProtocol(Protocol):
    """Protocol for attribute bucket list operations."""

    @staticmethod
    def fetch(
        actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, dict[str, dict[str, Any]]] | None:
        """
        Retrieve all attributes for an actor grouped by bucket.

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {bucket: {name: {"data": ..., "timestamp": ...}}}, or None
        """
        ...

    @staticmethod
    def fetch_timestamps(
        actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, Any] | None:
        """
        Retrieve timestamps for all attribute buckets.

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {bucket: timestamp}, or None (no actor id, no rows on
            PostgreSQL, or a read fault with ``strict=False``)
        """
        ...

    @staticmethod
    def delete(actor_id: str | None = None) -> bool:
        """
        Delete all attributes for the actor.

        Args:
            actor_id: The actor ID

        Returns:
            True on success; False only without a handle or arguments.
            A fault raises ``DbError``.
        """
        ...


# =============================================================================
# Subscription Suspension Protocols
# =============================================================================


@runtime_checkable
class SubscriptionSuspensionProtocol(Protocol):
    """Protocol for subscription suspension state persistence.

    Suspension allows temporarily disabling diff registration for specific
    targets/subtargets during bulk operations (imports, migrations).
    When resumed, resync callbacks notify subscribers to re-fetch state.
    """

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if a target/subtarget is currently suspended.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if suspended, False otherwise
        """
        ...

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration for a target/subtarget.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if newly suspended, False if already suspended
        """
        ...

    def resume(self, target: str, subtarget: str | None = None) -> bool:
        """Resume diff registration for a target/subtarget.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if was suspended and now resumed, False if wasn't suspended
        """
        ...

    def get_all_suspended(self) -> list[tuple[str, str | None]]:
        """Get all currently suspended target/subtarget pairs.

        Returns:
            List of (target, subtarget) tuples
        """
        ...
