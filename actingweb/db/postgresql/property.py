"""PostgreSQL implementation of property database operations."""

import json
import logging
import os
from typing import Any

from actingweb.db.exceptions import DbError
from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


def _serialize_property_value(value: Any) -> str | None:
    """Serialize a property value the same way ``DbProperty.set()`` does.

    Returns ``None`` if the serialized value is empty (nothing to write —
    callers treat this as "would delete", which conditional-create callers
    must reject rather than silently no-op).
    """
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
    DbProperty does all the db operations for property objects.

    The actor_id must always be set. get(), set() and
    get_actor_id_from_property() will set a new internal handle
    that will be reused by set() (overwrite property) and
    delete().
    """

    handle: dict[str, Any] | None

    def __init__(
        self,
        use_lookup_table: bool | None = None,
        indexed_properties: list[str] | None = None,
    ) -> None:
        """Initialize DbProperty.

        Args:
            use_lookup_table: Whether to use property lookup table. If None, reads from env.
            indexed_properties: List of property names to index. If None, uses defaults.
        """
        self.handle = None
        # Store configuration for lookup table
        if use_lookup_table is not None:
            self._use_lookup_table = use_lookup_table
        else:
            self._use_lookup_table = (
                os.getenv("USE_PROPERTY_LOOKUP_TABLE", "true").lower() == "true"
            )

        if indexed_properties is not None:
            self._indexed_properties = indexed_properties
        else:
            self._indexed_properties = ["oauthId", "email", "externalUserId"]
            if os.getenv("INDEXED_PROPERTIES"):
                env_props = os.getenv("INDEXED_PROPERTIES", "").split(",")
                self._indexed_properties = [p.strip() for p in env_props if p.strip()]

    def _should_index_property(self, name: str) -> bool:
        """
        Check if property should be indexed in lookup table.

        Returns True if:
        1. Lookup table mode is enabled
        2. Property name is in configured indexed_properties list
        3. Property is not a list-property item/meta row (belt-and-braces —
           list names are never configured as indexed properties, but this
           makes it structurally impossible for lookup-table sync to touch
           list storage rows)
        """
        return (
            self._use_lookup_table
            and name in self._indexed_properties
            and not name.startswith("list:")
        )

    def get(self, actor_id: str | None = None, name: str | None = None) -> str | None:
        """
        Get property value.

        Args:
            actor_id: The actor ID
            name: The property name

        Returns:
            Property value as string, or None if not found

        Raises:
            DbError: On a backend fault. Only row absence returns None.
        """
        if not actor_id or not name:
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, name, value
                        FROM properties
                        WHERE id = %s AND name = %s
                        """,
                        (actor_id, name),
                    )
                    row = cur.fetchone()

                    if row:
                        self.handle = {
                            "id": row[0],
                            "name": row[1],
                            "value": row[2],
                        }
                        return row[2]
                    else:
                        return None
        except Exception as e:
            logger.error(f"Error retrieving property {actor_id}/{name}: {e}")
            raise DbError("property read", actor_id) from e

    def get_actor_id_from_property(
        self, name: str | None = None, value: str | None = None
    ) -> str | None:
        """
        Reverse lookup: find actor by property value.

        Uses lookup table if configured, otherwise falls back to indexed query.

        Args:
            name: Property name (e.g., "oauthId")
            value: Property value to search for

        Returns:
            Actor ID if found, None otherwise
        """
        if not name or not value:
            return None

        if self._use_lookup_table and name not in self._indexed_properties:
            # Same contract as the DynamoDB backend: only properties
            # configured via with_indexed_properties() support reverse
            # lookup in lookup-table mode. The old behaviour silently fell
            # through to an unindexed full-table sequential scan.
            logger.warning(
                f"Reverse lookup requested for non-indexed property "
                f"'{name}' — add it to with_indexed_properties() (or "
                f"INDEXED_PROPERTIES) to enable reverse lookup; "
                f"returning None"
            )
            return None

        if self._use_lookup_table and name in self._indexed_properties:
            # Use new lookup table approach
            from actingweb.db.postgresql.property_lookup import DbPropertyLookup

            lookup = DbPropertyLookup()
            actor_id = lookup.get(property_name=name, value=value)

            if actor_id is None:
                # Migration fallback: an un-backfilled lookup table on an
                # upgrading deployment. The legacy query is an unindexed
                # sequential scan (the value index was dropped by migration
                # c3d4e5f6a7b8) — populate the lookup table to escape it.
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                SELECT id FROM properties
                                WHERE name = %s AND value = %s
                                LIMIT 1
                                """,
                                (name, value),
                            )
                            row = cur.fetchone()
                            if row:
                                actor_id = row[0]
                except Exception:
                    actor_id = None
                if actor_id:
                    logger.warning(
                        f"DEPRECATED: reverse lookup for '{name}' served by a "
                        f"full-table scan of the properties table — run "
                        f"scripts/backfill_property_lookup.py to populate the "
                        f"lookup table. This fallback is removed in the next "
                        f"major release."
                    )

            if actor_id:
                # Load the property into self.handle for subsequent operations
                try:
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                SELECT id, name, value
                                FROM properties
                                WHERE id = %s AND name = %s
                                """,
                                (actor_id, name),
                            )
                            row = cur.fetchone()
                            if row:
                                self.handle = {
                                    "id": row[0],
                                    "name": row[1],
                                    "value": row[2],
                                }
                            else:
                                logger.warning(
                                    f"Lookup found actor {actor_id} but property {name} doesn't exist"
                                )
                                return None
                except Exception as e:
                    logger.error(f"Error loading property after lookup: {e}")
                    return None

            return actor_id
        else:
            # Fall back to legacy indexed query approach
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT id, name, value
                            FROM properties
                            WHERE value = %s
                            LIMIT 1
                            """,
                            (value,),
                        )
                        row = cur.fetchone()

                        if row:
                            self.handle = {
                                "id": row[0],
                                "name": row[1],
                                "value": row[2],
                            }
                            return row[0]
                        else:
                            return None
            except Exception as e:
                logger.error(f"Error reverse lookup for property {name}: {e}")
                return None

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
            True on success, False on failure. Unlike ``get()``, backend
            faults are reported through this boolean (logged, not raised) —
            callers MUST check the return value.
        """
        if not name:
            return False

        # Convert non-string values to JSON strings for storage
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

        # Empty value means delete
        if not value or (hasattr(value, "__len__") and len(value) == 0):
            if self.get(actor_id=actor_id, name=name):
                self.delete()  # This will also delete lookup entry
            return True

        if not actor_id:
            return False

        # Get old value before updating (for lookup sync)
        old_value = None
        if self._should_index_property(name):
            old_value = self.get(actor_id=actor_id, name=name)

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Use INSERT ... ON CONFLICT to upsert
                    cur.execute(
                        """
                        INSERT INTO properties (id, name, value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id, name)
                        DO UPDATE SET value = EXCLUDED.value
                        """,
                        (actor_id, name, value),
                    )

                    # Update lookup table if property is indexed
                    if self._should_index_property(name):
                        self._update_lookup_entry_in_transaction(
                            cur, actor_id, name, old_value, value
                        )

                conn.commit()

            # Update handle
            self.handle = {
                "id": actor_id,
                "name": name,
                "value": value,
            }
            return True
        except Exception as e:
            logger.error(f"Error setting property {actor_id}/{name}: {e}")
            return False

    def _update_lookup_entry_in_transaction(
        self, cur: Any, actor_id: str, name: str, old_value: str | None, new_value: str
    ) -> None:
        """
        Update lookup table entry within a transaction (delete old, create new).

        Args:
            cur: Database cursor (within active transaction)
            actor_id: Actor ID
            name: Property name
            old_value: Previous property value
            new_value: New property value

        Best-effort update - logs errors but doesn't fail property write.
        """
        try:
            # Delete old lookup entry if exists
            if old_value and old_value != new_value:
                try:
                    cur.execute(
                        """
                        DELETE FROM property_lookup
                        WHERE property_name = %s AND value = %s AND actor_id = %s
                        """,
                        (name, old_value, actor_id),
                    )
                except Exception:
                    pass  # Entry doesn't exist or already deleted

            # Create new lookup entry (skip if value unchanged)
            if not old_value or old_value != new_value:
                cur.execute(
                    """
                    INSERT INTO property_lookup (property_name, value, actor_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (property_name, value) DO NOTHING
                    """,
                    (name, new_value, actor_id),
                )
                # Log conflict if another actor already claimed this value
                if cur.rowcount == 0:
                    logger.warning(
                        f"LOOKUP_CONFLICT: property={name} "
                        f"value_len={len(new_value)} actor={actor_id} - "
                        f"value already claimed by another actor"
                    )

        except Exception as e:
            logger.error(
                f"LOOKUP_TABLE_SYNC_FAILED: actor={actor_id} property={name} "
                f"old_value_len={len(old_value) if old_value else 0} "
                f"new_value_len={len(new_value)} error={e}"
            )
            # Don't fail the property write - accept eventual consistency

    def _delete_lookup_entry_in_transaction(
        self, cur: Any, actor_id: str | None, name: str, value: str
    ) -> None:
        """
        Delete lookup table entry within a transaction.

        Args:
            cur: Database cursor (within active transaction)
            actor_id: Actor ID
            name: Property name
            value: Property value

        Best-effort deletion - logs errors but doesn't fail property delete.
        """
        try:
            cur.execute(
                """
                DELETE FROM property_lookup
                WHERE property_name = %s AND value = %s AND actor_id = %s
                """,
                (name, value, actor_id),
            )
        except Exception as e:
            logger.warning(
                f"LOOKUP_DELETE_FAILED: actor={actor_id} property={name} "
                f"value_len={len(value)} error={e}"
            )
            # Don't fail the property delete

    def delete(self) -> bool:
        """
        Delete property using self.handle.

        Returns:
            True on success, False on failure
        """
        if not self.handle:
            return False

        actor_id = self.handle.get("id")
        name = self.handle.get("name")
        value = self.handle.get("value")

        if not actor_id or not name:
            logger.error("DbProperty handle missing id or name field")
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Delete property
                    cur.execute(
                        """
                        DELETE FROM properties
                        WHERE id = %s AND name = %s
                        """,
                        (actor_id, name),
                    )

                    # Delete lookup entry if property is indexed
                    if name and value and self._should_index_property(name):
                        self._delete_lookup_entry_in_transaction(
                            cur, actor_id, name, value
                        )

                conn.commit()

            self.handle = None
            return True
        except Exception as e:
            logger.error(f"Error deleting property {actor_id}/{name}: {e}")
            return False

    def get_range(
        self,
        actor_id: str | None = None,
        lower: str | None = None,
        upper: str | None = None,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, str]:
        """Range-read rows whose name is in ``[lower, upper]`` (inclusive).

        See ``DbPropertyProtocol.get_range`` for the contract. Uses a range
        comparison (``>=``/``<=``), never ``LIKE`` — no escaping surface.

        ``consistent_read`` is accepted and ignored: PostgreSQL reads are
        consistent by construction, there is no eventually-consistent read
        mode to opt into. It's part of the protocol (DynamoDB's callers
        pass it uniformly) rather than a DynamoDB detail leaking upward.
        """
        if not actor_id or lower is None or upper is None:
            return {}

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if keys_only:
                        cur.execute(
                            """
                            SELECT name
                            FROM properties
                            WHERE id = %s
                              AND name COLLATE "C" >= %s
                              AND name COLLATE "C" <= %s
                            """,
                            (actor_id, lower, upper),
                        )
                        return {row[0]: "" for row in cur.fetchall()}
                    cur.execute(
                        """
                        SELECT name, value
                        FROM properties
                        WHERE id = %s
                          AND name COLLATE "C" >= %s
                          AND name COLLATE "C" <= %s
                        """,
                        (actor_id, lower, upper),
                    )
                    return {row[0]: row[1] for row in cur.fetchall()}
        except Exception as e:
            logger.error(f"Error range-reading properties for actor {actor_id}: {e}")
            raise DbError("property range read", actor_id) from e

    def create_if_not_exists(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """Conditionally create a row — see ``DbPropertyProtocol.create_if_not_exists``."""
        if not actor_id or not name:
            return False

        serialized = _serialize_property_value(value)
        if serialized is None:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO properties (id, name, value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (id, name) DO NOTHING
                        """,
                        (actor_id, name, serialized),
                    )
                    created = cur.rowcount == 1
                conn.commit()
            if created:
                self.handle = {"id": actor_id, "name": name, "value": serialized}
            return created
        except Exception as e:
            logger.error(
                f"Error conditionally creating property {actor_id}/{name}: {e}"
            )
            raise DbError("property conditional create", actor_id) from e

    def delete_if_value_equals(
        self, actor_id: str | None = None, name: str | None = None, value: Any = None
    ) -> bool:
        """Conditionally delete — see ``DbPropertyProtocol.delete_if_value_equals``.

        A zero rowcount covers both "someone changed it" and "someone
        already deleted it"; both mean the same thing to the caller.
        """
        if not actor_id or not name or value is None:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM properties
                        WHERE id = %s AND name = %s AND value = %s
                        """,
                        (actor_id, name, value),
                    )
                    deleted = cur.rowcount == 1
                conn.commit()
            if deleted and isinstance(self.handle, dict):
                if (
                    self.handle.get("id") == actor_id
                    and self.handle.get("name") == name
                ):
                    self.handle = None
            return deleted
        except Exception as e:
            logger.error(
                f"Error conditionally deleting property {actor_id}/{name}: {e}"
            )
            raise DbError("property conditional delete", actor_id) from e


class DbPropertyList:
    """
    DbPropertyList does all the db operations for list of property objects.

    The actor_id must always be set.
    """

    handle: Any | None
    actor_id: str | None
    props: dict[str, str] | None

    def __init__(
        self,
        use_lookup_table: bool | None = None,
        indexed_properties: list[str] | None = None,
    ) -> None:
        """Initialize DbPropertyList.

        Args:
            use_lookup_table: Whether to use property lookup table. If None, reads from env.
            indexed_properties: List of property names to index. If None, uses defaults.
        """
        self.handle = None
        self.actor_id = None
        self.props = None

        if use_lookup_table is not None:
            self._use_lookup_table = use_lookup_table
        else:
            self._use_lookup_table = (
                os.getenv("USE_PROPERTY_LOOKUP_TABLE", "true").lower() == "true"
            )

        if indexed_properties is not None:
            self._indexed_properties = indexed_properties
        else:
            self._indexed_properties = ["oauthId", "email", "externalUserId"]
            if os.getenv("INDEXED_PROPERTIES"):
                env_props = os.getenv("INDEXED_PROPERTIES", "").split(",")
                self._indexed_properties = [p.strip() for p in env_props if p.strip()]

    def fetch(self, actor_id: str | None = None) -> dict[str, str] | None:
        """
        Retrieve the PLAIN (non-list) properties for an actor.

        Filters ``list:``-prefixed rows in the query itself via
        ``NOT LIKE 'list:%%'`` rather than fetching the whole partition and
        discarding list item rows client-side. Deliberately not a range
        comparison (unlike the DynamoDB backend, which cannot ``OR`` on a
        sort key and so needs one): PostgreSQL text ordering is
        collation-dependent, and a non-``C`` collation does not agree with
        byte order on punctuation, so a ``name < 'list:'`` condition would
        not reliably exclude every ``list:*`` row. ``NOT LIKE`` has no such
        dependency. (The ``%%`` is not a client-side-filter leftover: a
        literal, unparameterised ``%`` in the query text is misread by
        psycopg as an incomplete placeholder.)

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {property_name: property_value}, or None
        """
        if not actor_id:
            return None

        self.actor_id = actor_id

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT name, value
                        FROM properties
                        WHERE id = %s
                          AND name NOT LIKE 'list:%%'
                        ORDER BY name
                        """,
                        (actor_id,),
                    )
                    rows = cur.fetchall()

                    # Always {}, never None, once actor_id is valid --
                    # matching the DynamoDB backend, whose query iterator
                    # is truthy regardless of match count. Filtering
                    # list:-prefixed rows in SQL now (rather than
                    # client-side over the whole partition) means an actor
                    # with ONLY list: rows returns zero rows here same as
                    # one with none at all; both must still answer {},
                    # not None -- a caller distinguishing "no properties"
                    # from "an error" depends on it.
                    self.props = dict(rows)
                    return self.props
        except Exception as e:
            logger.error(f"Error fetching properties for actor {actor_id}: {e}")
            return None

    def fetch_all_including_lists(
        self, actor_id: str | None = None
    ) -> dict[str, str] | None:
        """
        Retrieve ALL properties including list properties.

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {property_name: property_value}, or None
        """
        if not actor_id:
            return None

        self.actor_id = actor_id

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT name, value
                        FROM properties
                        WHERE id = %s
                        ORDER BY name
                        """,
                        (actor_id,),
                    )
                    rows = cur.fetchall()

                    if rows:
                        props = {}
                        for row in rows:
                            name, value = row
                            props[name] = value
                        return props
                    else:
                        return None
        except Exception as e:
            logger.error(f"Error fetching all properties for actor {actor_id}: {e}")
            return None

    def delete(self) -> bool:
        """
        Delete all properties for the actor.

        Note: PostgreSQL foreign key CASCADE automatically handles lookup entry cleanup,
        but we explicitly delete them here for consistency and clarity.

        Returns:
            True on success, False on failure
        """
        if not self.actor_id:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # If using lookup table, collect indexed properties before deletion
                    indexed_props: list[tuple[str, str]] = []
                    if self._use_lookup_table:
                        cur.execute(
                            """
                            SELECT name, value
                            FROM properties
                            WHERE id = %s
                            """,
                            (self.actor_id,),
                        )
                        rows = cur.fetchall()
                        for row in rows:
                            name, value = row
                            if name in self._indexed_properties:
                                indexed_props.append((name, value))

                    # Delete all properties
                    cur.execute(
                        """
                        DELETE FROM properties
                        WHERE id = %s
                        """,
                        (self.actor_id,),
                    )

                    # Delete lookup entries (redundant with CASCADE but explicit)
                    if indexed_props:
                        for name, value in indexed_props:
                            try:
                                cur.execute(
                                    """
                                    DELETE FROM property_lookup
                                    WHERE property_name = %s AND value = %s AND actor_id = %s
                                    """,
                                    (name, value, self.actor_id),
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to delete lookup entry {name}={value}: {e}"
                                )

                conn.commit()

            self.handle = None
            return True
        except Exception as e:
            logger.error(f"Error deleting properties for actor {self.actor_id}: {e}")
            return False
