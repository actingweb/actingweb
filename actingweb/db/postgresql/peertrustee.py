"""PostgreSQL implementation of peertrustee database operations."""

import logging
from typing import Any

from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


class DbPeerTrustee:
    """
    DbPeerTrustee does all the db operations for peertrustee objects.

    The actor_id must always be set.
    """

    handle: dict[str, Any] | None

    def __init__(self) -> None:
        """Initialize DbPeerTrustee (no auto-table creation, use migrations)."""
        self.handle = None

    def get(
        self,
        actor_id: str | None = None,
        peer_type: str | None = None,
        peerid: str | None = None,
    ) -> dict[str, Any] | bool | None:
        """
        Retrieve peertrustee from the database.

        Args:
            actor_id: The actor ID
            peer_type: The peer type (used if peerid not provided)
            peerid: The peer ID (takes precedence over peer_type)

        Returns:
            Dict with peertrustee data, False if multiple peers found with same type,
            or None if not found
        """
        if not actor_id:
            return None

        if not peerid and not peer_type:
            logger.debug("Attempt to get DbPeerTrustee without peerid or type")
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if peerid:
                        # Query by actor_id and peerid (primary key)
                        cur.execute(
                            """
                            SELECT id, peerid, baseuri, type, passphrase
                            FROM peertrustees
                            WHERE id = %s AND peerid = %s
                            """,
                            (actor_id, peerid),
                        )
                        row = cur.fetchone()

                        if row:
                            self.handle = {
                                "id": row[0],
                                "peerid": row[1],
                                "baseuri": row[2],
                                "type": row[3],
                                "passphrase": row[4],
                            }
                            return self.handle
                        else:
                            return None

                    else:  # peer_type is set
                        # Query by actor_id and type
                        cur.execute(
                            """
                            SELECT id, peerid, baseuri, type, passphrase
                            FROM peertrustees
                            WHERE id = %s AND type = %s
                            """,
                            (actor_id, peer_type),
                        )
                        rows = cur.fetchall()

                        if not rows:
                            return None

                        if len(rows) > 1:
                            logger.error(
                                f"Found more than one peer of this peer trustee type({peer_type}). "
                                "Unable to determine which, need peerid lookup."
                            )
                            return False

                        # Exactly one row found
                        row = rows[0]
                        self.handle = {
                            "id": row[0],
                            "peerid": row[1],
                            "baseuri": row[2],
                            "type": row[3],
                            "passphrase": row[4],
                        }
                        return self.handle

        except Exception as e:
            logger.error(
                f"Error retrieving peertrustee {actor_id}/{peerid or peer_type}: {e}"
            )
            return None

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        peer_type: str | None = None,
        baseuri: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """
        Create a new peertrustee.

        Args:
            actor_id: The actor ID
            peerid: The peer ID
            peer_type: The peer type
            baseuri: Base URI
            passphrase: Passphrase

        Returns:
            True on success, False on failure
        """
        if not actor_id or not peerid or not peer_type:
            logger.debug(
                "actor_id, peerid, and type are mandatory when creating peertrustee in db"
            )
            return False

        if not baseuri:
            baseuri = ""
        if not passphrase:
            passphrase = ""

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO peertrustees (id, peerid, baseuri, type, passphrase)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (actor_id, peerid, baseuri, peer_type, passphrase),
                    )
                conn.commit()

            # Set handle
            self.handle = {
                "id": actor_id,
                "peerid": peerid,
                "baseuri": baseuri,
                "type": peer_type,
                "passphrase": passphrase,
            }
            return True

        except Exception as e:
            logger.error(f"Error creating peertrustee {actor_id}/{peerid}: {e}")
            return False

    def modify(
        self,
        peer_type: str | None = None,
        baseuri: str | None = None,
        passphrase: str | None = None,
    ) -> bool:
        """
        Modify a peertrustee.

        Args:
            peer_type: New peer type
            baseuri: New base URI
            passphrase: New passphrase

        Returns:
            True on success, False on failure
        """
        if not self.handle:
            logger.debug("Attempted modification of DbPeerTrustee without db handle")
            return False

        actor_id = self.handle.get("id")
        peerid = self.handle.get("peerid")

        if not actor_id or not peerid:
            logger.error("DbPeerTrustee handle missing id or peerid field")
            return False

        # Build update query dynamically
        updates = []
        params = []

        if baseuri and len(baseuri) > 0:
            updates.append("baseuri = %s")
            params.append(baseuri)
            self.handle["baseuri"] = baseuri

        if passphrase and len(passphrase) > 0:
            updates.append("passphrase = %s")
            params.append(passphrase)
            self.handle["passphrase"] = passphrase

        if peer_type and len(peer_type) > 0:
            updates.append("type = %s")
            params.append(peer_type)
            self.handle["type"] = peer_type

        if not updates:
            return True  # Nothing to update

        # Add WHERE clause parameters
        params.extend([actor_id, peerid])

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE peertrustees
                        SET {", ".join(updates)}
                        WHERE id = %s AND peerid = %s
                        """,
                        tuple(params),
                    )
                conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error modifying peertrustee {actor_id}/{peerid}: {e}")
            return False

    def delete(self) -> bool:
        """
        Delete peertrustee using self.handle.

        Returns:
            True on success, False on failure
        """
        if not self.handle:
            return False

        actor_id = self.handle.get("id")
        peerid = self.handle.get("peerid")

        if not actor_id or not peerid:
            logger.error("DbPeerTrustee handle missing id or peerid field")
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM peertrustees
                        WHERE id = %s AND peerid = %s
                        """,
                        (actor_id, peerid),
                    )
                conn.commit()

            self.handle = None
            return True

        except Exception as e:
            logger.error(f"Error deleting peertrustee {actor_id}/{peerid}: {e}")
            return False


class DbPeerTrusteeList:
    """
    DbPeerTrusteeList does all the db operations for list of peertrustee objects.

    The actor_id must always be set.
    """

    handle: Any | None
    actor_id: str | None
    peertrustees: list[dict[str, Any]] | None

    def __init__(self) -> None:
        """Initialize DbPeerTrusteeList."""
        self.handle = None
        self.actor_id = None
        self.peertrustees = []

    def fetch(self, actor_id: str | None = None) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all peertrustees for an actor.

        Args:
            actor_id: The actor ID

        Returns:
            List of peertrustee dicts, or empty list if none found
        """
        if not actor_id:
            return []

        self.actor_id = actor_id
        self.peertrustees = []

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, peerid, baseuri, type, passphrase
                        FROM peertrustees
                        WHERE id = %s
                        ORDER BY peerid
                        """,
                        (actor_id,),
                    )
                    rows = cur.fetchall()

                    for row in rows:
                        self.peertrustees.append(
                            {
                                "id": row[0],
                                "peerid": row[1],
                                "baseuri": row[2],
                                "type": row[3],
                                "passphrase": row[4],
                            }
                        )

                    return self.peertrustees

        except Exception as e:
            logger.error(f"Error fetching peertrustees for actor {actor_id}: {e}")
            return []

    def delete(self) -> bool:
        """
        Delete all peertrustees for the actor.

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
                        DELETE FROM peertrustees
                        WHERE id = %s
                        """,
                        (self.actor_id,),
                    )
                conn.commit()

            self.handle = None
            return True

        except Exception as e:
            logger.error(f"Error deleting peertrustees for actor {self.actor_id}: {e}")
            return False
