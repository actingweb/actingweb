# mypy: disable-error-code="override"
import logging
import os
from typing import Any

from pynamodb.attributes import UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import DeleteError, DoesNotExist, PutError, UpdateError
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table
from actingweb.db.exceptions import DbError

logger = logging.getLogger(__name__)

"""
    DbProperty handles all db operations for a property
    AWS DynamoDB is used as a backend.
"""


class Property(Model):
    """
    DynamoDB data model for a property.

    Declares NO global secondary index: reverse lookup goes through the
    ``property_lookup_v2`` table (value digest -> actor), so the table has no
    value-keyed GSI and no 2048-byte GSI-key limit on property values.
    """

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_properties"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)
        # Optional PynamoDB configuration attributes
        connect_timeout_seconds: int | None = None
        read_timeout_seconds: int | None = None
        # NOT None, unlike its siblings above: Connection.__init__ treats a
        # None max_retry_attempts as "use pynamodb.settings' default" (3),
        # but BatchWrite.commit()'s unprocessed-item retry loop -- used by
        # batch_delete() (Phase 12: thoughts/plans/2026-08-20-v2-
        # positional-access-cost.md) -- reads Meta.max_retry_attempts
        # directly with no such fallback, and `retries >= None` raises
        # TypeError. An explicit int here is required for that retry loop
        # to work at all, not merely a style preference.
        max_retry_attempts: int = 3
        max_pool_connections: int | None = None
        extra_headers: dict[str, str] | None = None
        aws_access_key_id: str | None = None
        aws_secret_access_key: str | None = None
        aws_session_token: str | None = None

    id = UnicodeAttribute(hash_key=True)
    name = UnicodeAttribute(range_key=True)
    value = UnicodeAttribute()


def _serialize_property_value(value: Any) -> str | None:
    """Serialize a property value the same way ``DbProperty.set()`` does.

    Returns ``None`` if the serialized value is empty (nothing to write —
    callers treat this as "would delete", which conditional-create callers
    must reject rather than silently no-op).
    """
    import json

    from actingweb.db.utils import sanitize_json_data

    if value is not None and not isinstance(value, str):
        try:
            sanitized_value = sanitize_json_data(value, log_source="property")
            value = json.dumps(sanitized_value)
        except (TypeError, ValueError):
            value = str(value)
    elif isinstance(value, str):
        value = sanitize_json_data(value, log_source="property")

    if not value or (hasattr(value, "__len__") and len(value) == 0):
        return None
    return value


class DbProperty:
    """
    DbProperty does all the db operations for property objects

    The actor_id must always be set. get(), set() and
    get_actor_id_from_property() will set a new internal handle
    that will be reused by set() (overwrite property) and
    delete().
    """

    # The largest row DynamoDB stores (400 KB, attribute names included).
    # The property-list layer reads this to set its span threshold and item
    # ceiling defaults (see actingweb.config.Config.list_item_span_threshold).
    MAX_ROW_BYTES: int | None = 409_600

    def __init__(self, *, indexed_properties: list[str]) -> None:
        """Initialize DbProperty.

        Args:
            indexed_properties: Property names that support reverse lookup.
                Required: the names come from ``Config.indexed_properties``
                (use :func:`actingweb.db.get_property`), never from the
                environment, so a direct construction cannot silently
                disagree with the configured set.
        """
        self.handle: Property | None = None
        self._indexed_properties = list(indexed_properties)
        ensure_table(Property)

    def _should_index_property(self, name: str) -> bool:
        """
        Check if property should be indexed in lookup table.

        Returns True if:
        1. Property name is in configured indexed_properties list
        2. Property is not a list-property item/meta row (belt-and-braces —
           list names are never configured as indexed properties, but this
           makes it structurally impossible for lookup-table sync to touch
           list storage rows)
        """
        return name in self._indexed_properties and not name.startswith("list:")

    def get(self, actor_id: str | None = None, name: str | None = None) -> str | None:
        """Retrieves the property from the database.

        Returns ``None`` only when the row is absent. A backend fault
        (throttle, timeout, connection error) raises ``DbError`` instead of
        being reported as absence.
        """
        if not actor_id or not name:
            return None
        if self.handle is not None and (
            str(self.handle.id) != actor_id or str(self.handle.name) != name
        ):
            # A handle cached from a previous get()/set() call for a
            # different (actor_id, name) must never be reused — discard it
            # and take the fresh-fetch path below.
            self.handle = None
        if self.handle:
            try:
                self.handle.refresh()
            except DoesNotExist:
                return None
            except Exception as e:
                raise DbError("property read", actor_id) from e
            return str(self.handle.value) if self.handle.value else None
        try:
            self.handle = Property.get(actor_id, name, consistent_read=True)
        except DoesNotExist:
            return None
        except Exception as e:
            raise DbError("property read", actor_id) from e
        return str(self.handle.value) if self.handle.value else None

    def get_actor_id_from_property(
        self,
        name: str | None = None,
        value: str | None = None,
        *,
        strict: bool = True,
    ) -> str | None:
        """
        Reverse lookup: find actor by property value.

        Resolved through the ``property_lookup_v2`` table (one ``GetItem``).

        Args:
            name: Property name (e.g., "oauthId")
            value: Property value to search for
            strict: When False, a read fault answers None instead of raising

        Returns:
            Actor ID if found, None otherwise

        Raises:
            DbError: on a read fault (unless ``strict=False``)
        """
        if not name or not value:
            return None
        try:
            return self._get_actor_id_from_property(name, value)
        except DbError:
            if strict:
                raise
            logger.error(f"Reverse lookup for '{name}' failed; returning None")
            return None

    def _get_actor_id_from_property(self, name: str, value: str) -> str | None:
        if name not in self._indexed_properties:
            # Enforce the documented contract: only properties configured
            # via with_indexed_properties() support reverse lookup.
            logger.warning(
                f"Reverse lookup requested for non-indexed property "
                f"'{name}' — add it to with_indexed_properties() (or "
                f"INDEXED_PROPERTIES) to enable reverse lookup; "
                f"returning None"
            )
            return None

        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        lookup = DbPropertyLookup()
        actor_id = lookup.get(property_name=name, value=value)  # raises

        if actor_id:
            # Load the property into self.handle for subsequent operations
            try:
                self.handle = Property.get(actor_id, name, consistent_read=True)
            except DoesNotExist:
                logger.warning(
                    f"Lookup found actor {actor_id} but property {name} doesn't exist"
                )
                return None
            except Exception as e:
                raise DbError("property reverse lookup") from e

        return actor_id

    def set(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """Sets a new value for the property name"""
        if not name:
            return False

        # Convert non-string values to JSON strings for storage
        import json

        from actingweb.db.utils import sanitize_json_data

        if value is not None and not isinstance(value, str):
            try:
                # Defensive sanitization of own data before JSON encoding
                sanitized_value = sanitize_json_data(value, log_source="property")
                value = json.dumps(sanitized_value)
            except (TypeError, ValueError):
                value = str(value)
        elif isinstance(value, str):
            # Sanitize string values too — surrogates in pre-serialized JSON
            # strings bypass json.dumps sanitization and corrupt storage
            value = sanitize_json_data(value, log_source="property")

        # Handle empty value (deletion)
        if not value or (hasattr(value, "__len__") and len(value) == 0):
            if self.get(actor_id=actor_id, name=name):
                self.delete()  # This will also delete lookup entry
            return True

        if (
            actor_id
            and self.handle is not None
            and (str(self.handle.id) != actor_id or str(self.handle.name) != name)
        ):
            # Same rule as get(): a handle cached for a different
            # (actor_id, name) must never be reused.
            self.handle = None

        # Get old value before updating (for lookup sync)
        old_value = None
        if self._should_index_property(name):
            if self.handle and self.handle.value:
                old_value = str(self.handle.value)
            elif actor_id:
                # PropertyStore.__setattr__ builds a fresh DbProperty for
                # every write, so self.handle is unset on the primary public
                # path. Read the current stored value (like the PostgreSQL
                # backend) so changing an indexed value deletes its stale
                # lookup row instead of leaving it to resolve forever.
                old_value = self.get(actor_id=actor_id, name=name)

        # Save property
        if not self.handle:
            if not actor_id:
                return False
            self.handle = Property(id=actor_id, name=name, value=value)
        else:
            self.handle.value = value

        if self._should_index_property(name):
            # D15: an indexed value and its lookup row commit together.
            handle_actor_id = str(self.handle.id) if self.handle.id else actor_id
            if handle_actor_id and (old_value is None or old_value != value):
                self._write_indexed(handle_actor_id, name, old_value, value)
                return True

        try:
            self.handle.save()
        except Exception as e:
            raise DbError("property write", actor_id) from e

        return True

    def _write_indexed(
        self, actor_id: str, name: str, old_value: str | None, new_value: str
    ) -> None:
        """Write an indexed property and its lookup row in one transaction.

        The lookup create succeeds when no row exists or the actor already
        owns it; a row owned by another actor is a collision, which is logged
        and leaves the property written without a lookup row (the unique
        reverse mapping stays with its first owner). The old value's lookup
        row is deleted in the same transaction when this actor owns it. Any
        other failure raises ``DbError`` and nothing is written.
        """
        from actingweb.db.dynamodb.actor import DbActor
        from actingweb.db.dynamodb.property_lookup import (
            DbPropertyLookup,
            PropertyLookupV2,
            compute_lookup_key,
        )

        ensure_table(PropertyLookupV2)  # cached: created lazily like the property table
        new_key = compute_lookup_key(name, new_value)
        own_or_absent = PropertyLookupV2.lookup_key.does_not_exist() | (
            PropertyLookupV2.actor_id == actor_id
        )
        include_delete = bool(old_value and old_value != new_value)
        old_key = compute_lookup_key(name, old_value) if old_value else None
        # A delete whose row another actor owns (a past collision) cannot be
        # part of the transaction; it is retried without the delete.
        for _ in range(2):

            def build(t: Any, with_delete: bool = include_delete) -> None:
                # TransactWriteItems order: deletes, then puts.
                if with_delete and old_key:
                    t.delete(
                        PropertyLookupV2(
                            lookup_key=old_key, actor_id=actor_id, property_name=name
                        ),
                        condition=own_or_absent,
                    )
                t.save(Property(id=actor_id, name=name, value=new_value))
                t.save(
                    PropertyLookupV2(
                        lookup_key=new_key, actor_id=actor_id, property_name=name
                    ),
                    condition=own_or_absent,
                )

            codes = DbActor._run_transaction(build, op="property set")  # pyright: ignore[reportPrivateUsage]
            if codes is None:
                self.handle = Property(id=actor_id, name=name, value=new_value)
                return
            offset = 1 if include_delete else 0
            create_failed = (
                len(codes) > offset + 1
                and codes[offset + 1] == "ConditionalCheckFailed"
            )
            delete_failed = include_delete and codes[0] == "ConditionalCheckFailed"
            if create_failed:
                logger.error(
                    f"LOOKUP_COLLISION: property={name} "
                    f"digest={new_key[:12]} actor={actor_id} — "
                    "two actors share an indexed value; not overwriting"
                )
                if include_delete and old_value:
                    # Release the old mapping this actor owns, then write the
                    # property alone: the value stays unindexed.
                    try:
                        lookup = DbPropertyLookup()
                        if lookup.get(property_name=name, value=old_value) == actor_id:
                            lookup.delete()
                    except DbError:
                        raise
                    except Exception as e:
                        raise DbError("property set", actor_id) from e
                try:
                    handle = Property(id=actor_id, name=name, value=new_value)
                    handle.save()
                    self.handle = handle
                except Exception as e:
                    raise DbError("property write", actor_id) from e
                return
            if delete_failed:
                include_delete = False
                continue
            raise DbError("property set", actor_id)
        raise DbError("property set", actor_id)

    def _delete_lookup_entry(self, actor_id: str | None, name: str, value: str) -> None:
        """
        Delete lookup table entry.

        Best-effort deletion - logs errors but doesn't fail property delete.
        """
        try:
            from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

            db = DbPropertyLookup()
            # Verify it belongs to the same actor before deleting
            if db.get(property_name=name, value=value) == actor_id:
                db.delete()
        except Exception as e:
            logger.warning(
                f"LOOKUP_DELETE_FAILED: actor={actor_id} property={name} "
                f"value_len={len(value)} error={e}"
            )
            # Don't fail the property delete

    def delete(self) -> bool:
        """Deletes the property in the database after a get()"""
        if not self.handle:
            return False

        # Save values before deletion
        actor_id = str(self.handle.id) if self.handle.id else None
        name = str(self.handle.name) if self.handle.name else None
        value = str(self.handle.value) if self.handle.value else None

        # Delete property
        self.handle.delete()
        self.handle = None

        # Delete lookup entry if property is indexed
        if name and value and self._should_index_property(name):
            self._delete_lookup_entry(actor_id, name, value)

        return True

    def get_range(
        self,
        actor_id: str | None = None,
        lower: str | None = None,
        upper: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        """Range-read rows whose name is in ``[lower, upper]``.

        See ``DbPropertyProtocol.get_range`` for the contract. DynamoDB's
        KeyConditionExpression rejects two separate comparisons on the same
        key (``>=`` AND ``<`` is invalid), so this uses ``between()``,
        which is INCLUSIVE on both ends — the caller MUST choose ``upper``
        as a sentinel value that can never equal a real row name (e.g. a
        delimiter character no real key contains), so inclusive-vs-exclusive
        at the boundary is unobservable. DynamoDB already returns range-key
        query results in ascending sort-key order, but this is NOT relied
        upon — the caller re-sorts.
        """
        if not actor_id or lower is None or upper is None:
            return {}

        condition = Property.name.between(lower, upper)
        attributes_to_get = ["name"] if keys_only else ["name", "value"]

        try:
            results: dict[str, str] = {}
            for item in Property.query(
                actor_id,
                range_key_condition=condition,
                consistent_read=consistent_read,
                attributes_to_get=attributes_to_get,
            ):
                results[str(item.name)] = "" if keys_only else str(item.value or "")
            return results
        except Exception as e:
            raise DbError("property range read", actor_id) from e

    def get_prefix(
        self,
        actor_id: str | None = None,
        prefix: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        """Read rows whose name begins with ``prefix``.

        See ``DbPropertyProtocol.get_prefix`` for the contract. Uses
        DynamoDB's native ``begins_with`` on the range key, which is EXACT
        for an arbitrary UTF-8 prefix: String sort keys are ordered by
        their UTF-8 bytes, and UTF-8 is prefix-preserving, so "sorts under
        this prefix" and "starts with these bytes" are the same set. That
        is why this is not a ``get_range`` with a synthesised upper bound —
        no such bound is exact.

        ``begins_with`` performs NO Unicode normalization, so an NFD prefix
        does not match an NFC name. This is deliberate and matches
        PostgreSQL's ``starts_with()``; it is what makes the two backends
        return byte-identical key sets.

        The empty prefix is rejected here rather than passed down:
        ``begins_with(name, "")`` is a ``ValidationException``.
        """
        if not actor_id or not prefix:
            return {}

        condition = Property.name.startswith(prefix)
        attributes_to_get = ["name"] if keys_only else ["name", "value"]

        try:
            results: dict[str, str] = {}
            for item in Property.query(
                actor_id,
                range_key_condition=condition,
                consistent_read=consistent_read,
                attributes_to_get=attributes_to_get,
            ):
                results[str(item.name)] = "" if keys_only else str(item.value or "")
            return results
        except Exception as e:
            raise DbError("property prefix read", actor_id) from e

    def create_if_not_exists(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """Conditionally create a row — see ``DbPropertyProtocol.create_if_not_exists``."""
        if not actor_id or not name:
            return False

        serialized = _serialize_property_value(value)
        if serialized is None:
            return False

        item = Property(id=actor_id, name=name, value=serialized)
        try:
            item.save(condition=Property.id.does_not_exist())
        except PutError as e:
            if e.cause_response_code == "ConditionalCheckFailedException":
                return False
            raise DbError("property conditional create", actor_id) from e
        except Exception as e:
            raise DbError("property conditional create", actor_id) from e
        return True

    def delete_if_value_equals(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """Conditionally delete — see ``DbPropertyProtocol.delete_if_value_equals``.

        The condition covers both "someone changed it" and "someone already
        deleted it": DynamoDB fails an equality condition on a missing
        attribute just as it does on a differing one, and both mean the same
        thing to the caller (re-resolve and retry).
        """
        if not actor_id or not name or value is None:
            return False

        item = Property(id=actor_id, name=name)
        try:
            item.delete(condition=Property.value == value)
        except DeleteError as e:
            if e.cause_response_code == "ConditionalCheckFailedException":
                return False
            raise DbError("property conditional delete", actor_id) from e
        except Exception as e:
            raise DbError("property conditional delete", actor_id) from e
        return True

    def set_if_value_equals(
        self,
        actor_id: str | None = None,
        name: str | None = None,
        expected: Any = None,
        value: Any = None,
    ) -> bool:
        """Conditionally set — see ``DbPropertyProtocol.set_if_value_equals``.

        Same condition-failure-vs-fault distinction as
        ``delete_if_value_equals``: a differing stored value and a vanished
        row both fail the equality condition on ``value`` the same way.
        """
        if not actor_id or not name or expected is None or value is None:
            return False

        item = Property(id=actor_id, name=name)
        try:
            item.update(
                actions=[Property.value.set(value)],
                condition=Property.value == expected,
            )
        except UpdateError as e:
            if e.cause_response_code == "ConditionalCheckFailedException":
                return False
            raise DbError("property conditional set", actor_id) from e
        except Exception as e:
            raise DbError("property conditional set", actor_id) from e
        return True

    def get_last_in_range(
        self,
        actor_id: str | None = None,
        lower: str | None = None,
        upper: str | None = None,
    ) -> str | None:
        """Bytewise-greatest row name in ``[lower, upper]`` — see
        ``DbPropertyProtocol.get_last_in_range``.

        ``scan_index_forward=False, limit=1`` reads DynamoDB's natural
        range-key sort order backwards and stops at the first item — one
        item's read capacity, not the whole range's.
        """
        if not actor_id or lower is None or upper is None:
            return None

        condition = Property.name.between(lower, upper)
        try:
            for item in Property.query(
                actor_id,
                range_key_condition=condition,
                consistent_read=True,
                scan_index_forward=False,
                limit=1,
                attributes_to_get=["name"],
            ):
                return str(item.name)
            return None
        except Exception as e:
            raise DbError("property last-in-range read", actor_id) from e

    def batch_delete(
        self, actor_id: str | None = None, names: list[str] | None = None
    ) -> None:
        """Unconditional bulk delete — see ``DbPropertyProtocol.batch_delete``.

        ``Property.batch_write()`` is PynamoDB's ``BatchWrite`` context
        manager: it chunks at 25 items (``BATCH_WRITE_PAGE_LIMIT``) and
        retries any items DynamoDB reports as unprocessed, raising
        ``PutError`` if ``Meta.max_retry_attempts`` is exhausted -- both
        behaviours come from the pinned PynamoDB version, not hand-rolled
        here.
        """
        if not actor_id or not names:
            return
        try:
            with Property.batch_write() as batch:
                for name in names:
                    batch.delete(Property(id=actor_id, name=name))
        except Exception as e:
            raise DbError("property batch delete", actor_id) from e


class DbPropertyList:
    """
    DbPropertyList does all the db operations for list of property objects

    The actor_id must always be set.
    """

    def __init__(self, *, indexed_properties: list[str]) -> None:
        """Initialize DbPropertyList.

        Args:
            indexed_properties: Property names that support reverse lookup
                (required; see :class:`DbProperty`).
        """
        self.handle: Any | None = None
        self.actor_id: str | None = None
        self.props: dict[str, str] | None = None
        self._indexed_properties = list(indexed_properties)
        ensure_table(Property)

    def fetch(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, str] | None:
        """Retrieves the PLAIN (non-list) properties of an actor_id from
        the database.

        A read fault raises ``DbError``; ``strict=False`` answers it with
        None.

        Two range-constrained Queries rather than a whole-partition Query
        with client-side filtering: DynamoDB cannot ``OR`` on a sort key,
        so excluding the ``list:``-prefixed rows takes a pair of Queries
        covering everything below and everything above that namespace,
        instead of paying for (and discarding) every list item row on
        every plain-property read.

        The upper sentinel is ``"list;"`` (``;`` is 0x3B, the byte right
        after ``:``), NOT ``"list:~"``: ``~`` is 0x7E, so any list whose
        NAME starts with a byte above ``~`` -- every non-ASCII list name --
        would sort after ``"list:~"`` and leak back into this result.
        ``name < "list:"`` and ``name >= "list;"`` is exact: a plain
        property named ``"list"`` sorts in the first range, one named
        ``"listen"`` in the second, and every ``list:*`` row in neither.
        """
        if not actor_id:
            return None
        self.actor_id = actor_id
        self.props = {}
        # Property.query() returns a truthy iterator regardless of match
        # count, so fetch() has always returned {} (not None) for an actor
        # whose partition holds no plain properties -- preserved here by
        # unconditionally returning self.props rather than reintroducing a
        # falsy-handle check against either query's result.
        try:
            for condition in (Property.name < "list:", Property.name >= "list;"):
                self.handle = Property.query(actor_id, range_key_condition=condition)
                for d in self.handle:
                    self.props[d.name] = d.value
        except Exception as e:
            self.props = {}
            if strict:
                raise DbError("property list fetch", actor_id) from e
            logger.error(f"Error fetching the properties of {actor_id}: {e}")
            return None
        return self.props

    def fetch_all_including_lists(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, str] | None:
        """Retrieves ALL properties including list properties - for internal PropertyListStore use

        A read fault raises ``DbError``; ``strict=False`` answers it with
        None.
        """
        if not actor_id:
            return None
        self.actor_id = actor_id
        props = {}
        try:
            for d in Property.query(actor_id):
                props[d.name] = d.value
        except Exception as e:
            if strict:
                raise DbError("property list fetch_all", actor_id) from e
            logger.error(f"Error fetching all properties of {actor_id}: {e}")
            return None
        return props

    def delete(self) -> bool:
        """Deletes all the properties in the database"""
        if not self.actor_id:
            return False

        # Single partition read: collect indexed properties (for lookup-row
        # cleanup) and item names, then delete everything in one batched
        # operation (Phase 12: thoughts/plans/2026-08-20-v2-positional-
        # access-cost.md) instead of one DeleteItem round trip per row.
        indexed_props: list[tuple[str, str]] = []
        names: list[str] = []
        try:
            for p in Property.query(self.actor_id):
                if str(p.name) in self._indexed_properties:
                    indexed_props.append((str(p.name), str(p.value)))
                names.append(str(p.name))
        except Exception as e:
            raise DbError("property list delete", self.actor_id) from e

        if names:
            try:
                with Property.batch_write() as batch:
                    for name in names:
                        batch.delete(Property(id=self.actor_id, name=name))
            except Exception as e:
                raise DbError("property batch delete", self.actor_id) from e

        # Delete lookup entries
        if indexed_props:
            from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

            db = DbPropertyLookup()
            for name, value in indexed_props:
                try:
                    # Verify ownership before deleting: a shared indexed value
                    # may map to another actor's row, which must survive this
                    # actor's deletion.
                    if db.get(property_name=name, value=value) == self.actor_id:
                        db.delete()
                except Exception as e:
                    logger.warning(
                        f"Failed to delete lookup entry for property {name}: {e}"
                    )

        self.handle = None
        return True
