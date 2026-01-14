"""PostgreSQL implementation of actor database operations."""

import logging
from typing import Any

from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


class DbActor:
    """DbActor does all the db operations for actor objects."""

    handle: dict[str, Any] | None

    def __init__(self) -> None:
        """Initialize DbActor (no auto-table creation, use migrations)."""
        self.handle = None

    def get(self, actor_id: str | None = None) -> dict[str, Any] | None:
        """
        Retrieve actor by ID.

        Args:
            actor_id: The actor ID to retrieve

        Returns:
            dict with keys: id, creator, passphrase, or None if not found
        """
        if not actor_id:
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, creator, passphrase
                        FROM actors
                        WHERE id = %s
                        """,
                        (actor_id,),
                    )
                    row = cur.fetchone()

                    if row:
                        self.handle = {
                            "id": row[0],
                            "creator": row[1],
                            "passphrase": row[2],
                        }
                        return self.handle
                    else:
                        return None
        except Exception as e:
            logger.error(f"Error retrieving actor {actor_id}: {e}")
            return None

    def get_by_creator(
        self, creator: str | None = None
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """
        Get actors by creator field.

        Args:
            creator: The creator email to search for

        Returns:
            Single dict if one found, list of dicts if multiple found, None if none found
        """
        if not creator:
            return None

        # Email in creator needs to be lower case
        if "@" in creator:
            creator = creator.lower()

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, creator, passphrase
                        FROM actors
                        WHERE creator = %s
                        """,
                        (creator,),
                    )
                    rows = cur.fetchall()

                    if not rows:
                        return None

                    ret = []
                    for row in rows:
                        logger.warning(f"    id ({row[0]})")
                        actor_dict = {
                            "id": row[0],
                            "creator": row[1],
                            "passphrase": row[2],
                        }
                        ret.append(actor_dict)

                    return ret
        except Exception as e:
            logger.error(f"Error retrieving actors by creator {creator}: {e}")
            return None

    def create(
        self,
        actor_id: str | None = None,
        creator: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """
        Create new actor.

        Args:
            actor_id: Unique actor ID
            creator: Creator email
            passphrase: Actor passphrase

        Returns:
            True on success, False on failure
        """
        if not actor_id:
            return False

        if not creator:
            creator = ""

        # Email in creator needs to be lower case
        if "@" in creator:
            creator = creator.lower()

        if not passphrase:
            passphrase = ""

        # Check if actor already exists
        if self.get(actor_id=actor_id):
            logger.warning(f"Trying to create actor that exists({actor_id})")
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO actors (id, creator, passphrase, created_at)
                        VALUES (%s, %s, %s, NOW())
                        """,
                        (actor_id, creator, passphrase),
                    )
                conn.commit()

            # Set handle to the newly created actor
            self.handle = {
                "id": actor_id,
                "creator": creator,
                "passphrase": passphrase,
            }
            return True
        except Exception as e:
            logger.error(f"Error creating actor {actor_id}: {e}")
            return False

    def modify(
        self, creator: str | None = None, passphrase: bytes | None = None
    ) -> bool:
        """
        Modify existing actor using self.handle.

        Args:
            creator: New creator email (optional)
            passphrase: New passphrase bytes (optional)

        Returns:
            True on success, False on failure
        """
        if not self.handle:
            logger.debug("Attempted modification of DbActor without db handle")
            return False

        actor_id = self.handle.get("id")
        if not actor_id:
            logger.error("DbActor handle missing id field")
            return False

        updates = []
        params = []

        if creator and len(creator) > 0:
            # Email in creator needs to be lower case
            if "@" in creator:
                creator = creator.lower()
            updates.append("creator = %s")
            params.append(creator)
            self.handle["creator"] = creator

        if passphrase and len(passphrase) > 0:
            passphrase_str = passphrase.decode("utf-8")
            updates.append("passphrase = %s")
            params.append(passphrase_str)
            self.handle["passphrase"] = passphrase_str

        if not updates:
            return True  # Nothing to update

        params.append(actor_id)

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE actors
                        SET {", ".join(updates)}
                        WHERE id = %s
                        """,
                        tuple(params),
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error modifying actor {actor_id}: {e}")
            return False

    def delete(self) -> bool:
        """
        Delete actor using self.handle.

        Returns:
            True on success, False on failure
        """
        if not self.handle:
            logger.debug("Attempted delete of DbActor without db handle")
            return False

        actor_id = self.handle.get("id")
        if not actor_id:
            logger.error("DbActor handle missing id field")
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM actors
                        WHERE id = %s
                        """,
                        (actor_id,),
                    )
                conn.commit()

            self.handle = None
            return True
        except Exception as e:
            logger.error(f"Error deleting actor {actor_id}: {e}")
            return False


class DbActorList:
    """DbActorList does all the db operations for list of actor objects."""

    handle: Any | None

    def __init__(self) -> None:
        """Initialize DbActorList."""
        self.handle = None

    def fetch(self) -> list[dict[str, Any]] | bool:
        """
        Fetch all actors.

        Returns:
            List of actor dicts, or False on error
        """
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, creator
                        FROM actors
                        ORDER BY id
                        """
                    )
                    rows = cur.fetchall()

                    if rows:
                        ret = []
                        for row in rows:
                            ret.append(
                                {
                                    "id": row[0],
                                    "creator": row[1],
                                }
                            )
                        return ret
                    else:
                        return False
        except Exception as e:
            logger.error(f"Error fetching actor list: {e}")
            return False
