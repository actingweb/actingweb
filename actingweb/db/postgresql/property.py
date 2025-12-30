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

        Args:
            name: Property name
            value: Property value to search for

        Returns:
            Actor ID if found, None otherwise
        """
        if not name or not value:
            return None

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
                self.delete()
            return True

        if not actor_id:
            return False

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

        if not actor_id or not name:
            logger.error("DbProperty handle missing id or name field")
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM properties
                        WHERE id = %s AND name = %s
                        """,
                        (actor_id, name),
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
            logger.error(
                f"Error fetching all properties for actor {actor_id}: {e}"
            )
            return None

    def delete(self) -> bool:
        """
        Delete all properties for the actor.

        Returns:
            True on success, False on failure
        """
        if not self.actor_id:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM properties
                        WHERE id = %s
                        """,
                        (self.actor_id,),
                    )
                conn.commit()

            self.handle = None
            return True
        except Exception as e:
            logger.error(f"Error deleting properties for actor {self.actor_id}: {e}")
            return False
