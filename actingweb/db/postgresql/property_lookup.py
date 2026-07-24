import logging
from typing import Any

from .connection import get_connection

logger = logging.getLogger(__name__)


class DbPropertyLookup:
    """
    DbPropertyLookup handles all db operations for property lookup table.

    This table enables reverse lookups (property value → actor_id) without
    size limitations.
    """

    def __init__(self) -> None:
        """Initialize DbPropertyLookup (no auto-table creation, use migrations)."""
        self.handle: dict[str, Any] | None = None

    def get(
        self, property_name: str | None = None, value: str | None = None
    ) -> str | None:
        """
        Retrieve actor_id by property name and value.

        Args:
            property_name: Property name (e.g., "oauthId")
            value: Property value to lookup

        Returns:
            Actor ID if found, None otherwise
        """
        if not property_name or not value:
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT property_name, value, actor_id
                        FROM property_lookup
                        WHERE property_name = %s AND value = %s
                        """,
                        (property_name, value),
                    )
                    row = cur.fetchone()
                    if row:
                        self.handle = {
                            "property_name": row[0],
                            "value": row[1],
                            "actor_id": row[2],
                        }
                        return row[2]
                    return None
        except Exception as e:
            logger.error(f"Error getting lookup for property {property_name}: {e}")
            return None

    def create(
        self,
        property_name: str | None = None,
        value: str | None = None,
        actor_id: str | None = None,
        overwrite: bool = False,
    ) -> bool:
        """
        Create lookup entry.

        Same contract as the DynamoDB backend: an existing row for the same
        (name, value) owned by a DIFFERENT actor is a collision — logged
        loudly and rejected (pass overwrite=True for legitimate moves).
        Re-creating the identical mapping is idempotent.

        Returns:
            True on success (including idempotent re-create), False on
            collision or error
        """
        if not property_name or not value or not actor_id:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if overwrite:
                        cur.execute(
                            """
                            INSERT INTO property_lookup (property_name, value, actor_id)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (property_name, value)
                            DO UPDATE SET actor_id = EXCLUDED.actor_id
                            """,
                            (property_name, value, actor_id),
                        )
                        inserted = True
                    else:
                        cur.execute(
                            """
                            INSERT INTO property_lookup (property_name, value, actor_id)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (property_name, value) DO NOTHING
                            """,
                            (property_name, value, actor_id),
                        )
                        inserted = cur.rowcount > 0
                    if not inserted:
                        cur.execute(
                            """
                            SELECT actor_id FROM property_lookup
                            WHERE property_name = %s AND value = %s
                            """,
                            (property_name, value),
                        )
                        row = cur.fetchone()
                        existing_actor = row[0] if row else None
                        if existing_actor != actor_id:
                            logger.error(
                                f"LOOKUP_COLLISION: property={property_name} "
                                f"actor={actor_id} existing_actor={existing_actor} — "
                                "two actors share an indexed value; not overwriting"
                            )
                            conn.commit()
                            return False
                conn.commit()
                self.handle = {
                    "property_name": property_name,
                    "value": value,
                    "actor_id": actor_id,
                }
                return True
        except Exception as e:
            logger.error(
                f"LOOKUP_CREATE_FAILED: property={property_name} "
                f"actor={actor_id} error={e}"
            )
            return False

    def delete(self) -> bool:
        """Delete lookup entry after get()."""
        if not self.handle:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM property_lookup
                        WHERE property_name = %s AND value = %s
                        """,
                        (self.handle["property_name"], self.handle["value"]),
                    )
                conn.commit()
                self.handle = None
                return True
        except Exception as e:
            logger.error(f"LOOKUP_DELETE_FAILED: error={e}")
            return False
