import json
import logging
from typing import Any

from actingweb.db.exceptions import DbError

from .connection import get_connection

logger = logging.getLogger(__name__)

CONFIGURED_KIND = "configured"
NAME_KIND = "name"


def read_readiness(names: list[str]) -> tuple[set[str], set[str] | None]:
    """The names with a backfill-complete marker, and the recorded name set.

    ``names`` is accepted for parity with the DynamoDB backend (which reads
    exactly those keys); PostgreSQL reads the whole small table. The second
    element is ``None`` when no set has been recorded yet. A missing
    relation (the Alembic migration has not run) and any other fault raise
    ``DbError``.
    """
    marked: set[str] = set()
    configured: set[str] | None = None
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT property_name, kind, value FROM property_lookup_backfill"
                )
                for property_name, kind, value in cur.fetchall():
                    if kind == CONFIGURED_KIND:
                        configured = set(json.loads(value or "[]"))
                    elif kind == NAME_KIND:
                        marked.add(property_name)
    except Exception as e:
        if getattr(e, "sqlstate", None) == "42P01" or "does not exist" in str(e):
            raise DbError(
                "lookup table missing: property_lookup_backfill "
                "(run 'alembic upgrade head')"
            ) from e
        raise DbError("property lookup readiness read") from e
    return marked, configured


def mark_backfilled(names: list[str]) -> None:
    """Write the backfill-complete marker of each name (idempotent)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for name in names:
                    cur.execute(
                        """
                        INSERT INTO property_lookup_backfill (property_name, kind)
                        VALUES (%s, %s)
                        ON CONFLICT (property_name, kind) DO NOTHING
                        """,
                        (name, NAME_KIND),
                    )
            conn.commit()
    except Exception as e:
        raise DbError("property lookup mark") from e


def unmark(names: list[str]) -> None:
    """Remove the backfill-complete marker of each name (idempotent)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for name in names:
                    cur.execute(
                        "DELETE FROM property_lookup_backfill "
                        "WHERE property_name = %s AND kind = %s",
                        (name, NAME_KIND),
                    )
            conn.commit()
    except Exception as e:
        raise DbError("property lookup unmark") from e


def record_configured(names: list[str]) -> None:
    """Record the configured indexed-name set."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # One row with a fixed key, replaced atomically, so concurrent
                # first starts cannot leave two rows or fail on the key.
                cur.execute(
                    """
                    INSERT INTO property_lookup_backfill (property_name, kind, value)
                    VALUES ('*', %s, %s)
                    ON CONFLICT (property_name, kind)
                    DO UPDATE SET value = EXCLUDED.value, completed_at = now()
                    """,
                    (CONFIGURED_KIND, json.dumps(sorted(set(names)))),
                )
            conn.commit()
    except Exception as e:
        raise DbError("property lookup record") from e


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
        self,
        property_name: str | None = None,
        value: str | None = None,
        *,
        strict: bool = True,
    ) -> str | None:
        """
        Retrieve actor_id by property name and value.

        Args:
            property_name: Property name (e.g., "oauthId")
            value: Property value to lookup
            strict: When False, a read fault answers None instead of raising

        Returns:
            Actor ID if found, None otherwise

        Raises:
            DbError: on a read fault (unless ``strict=False``)
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
            if strict:
                raise DbError("property lookup get") from e
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
