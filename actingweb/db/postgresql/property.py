"""PostgreSQL implementation of property database operations."""

import json
import logging
from typing import Any

from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


class DbProperty:
    """
    DbProperty does all the db operations for property objects.

    The actor_id must always be set. get(), set() and
    get_actor_id_from_property() will set a new internal handle
    that will be reused by set() (overwrite property) and
    delete().
    """

    handle: dict[str, Any] | None

    def __init__(self) -> None:
        """Initialize DbProperty (no auto-table creation, use migrations)."""
        self.handle = None

    def _should_index_property(self, name: str) -> bool:
        """
        Check if property should be indexed in lookup table.

        Returns True if:
        1. Lookup table mode is enabled (config.use_lookup_table)
        2. Property name is in configured indexed_properties list
        """
        from actingweb.config import Config

        config = Config()
        return config.use_lookup_table and name in config.indexed_properties

    def get(self, actor_id: str | None = None, name: str | None = None) -> str | None:
        """
        Get property value.

        Args:
            actor_id: The actor ID
            name: The property name

        Returns:
            Property value as string, or None if not found
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
            return None

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

        from actingweb.config import Config

        config = Config()

        if config.use_lookup_table and name in config.indexed_properties:
            # Use new lookup table approach
            from actingweb.db.postgresql.property_lookup import DbPropertyLookup

            lookup = DbPropertyLookup()
            actor_id = lookup.get(property_name=name, value=value)

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
                logger.error(f"Error reverse lookup property {name}={value}: {e}")
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
            True on success, False on failure
        """
        if not name:
            return False

        # Convert non-string values to JSON strings for storage
        if value is not None and not isinstance(value, str):
            try:
                value = json.dumps(value)
            except (TypeError, ValueError):
                value = str(value)

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


class DbPropertyList:
    """
    DbPropertyList does all the db operations for list of property objects.

    The actor_id must always be set.
    """

    handle: Any | None
    actor_id: str | None
    props: dict[str, str] | None

    def __init__(self) -> None:
        """Initialize DbPropertyList."""
        self.handle = None
        self.actor_id = None
        self.props = None

    def fetch(self, actor_id: str | None = None) -> dict[str, str] | None:
        """
        Retrieve all properties for an actor (excluding list: properties).

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
                        self.props = {}
                        for row in rows:
                            name, value = row
                            # Filter out list properties (they have "list:" prefix)
                            if not name.startswith("list:"):
                                self.props[name] = value
                        return self.props
                    else:
                        return None
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
            from actingweb.config import Config

            config = Config()

            with get_connection() as conn:
                with conn.cursor() as cur:
                    # If using lookup table, collect indexed properties before deletion
                    indexed_props: list[tuple[str, str]] = []
                    if config.use_lookup_table:
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
                            if name in config.indexed_properties:
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
