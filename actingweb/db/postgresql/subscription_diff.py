"""PostgreSQL implementation of subscription diff database operations."""

import logging
from datetime import datetime
from typing import Any

from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


class DbSubscriptionDiff:
    """
    DbSubscriptionDiff does all the db operations for subscription diff objects.

    The actor_id must always be set.
    """

    handle: dict[str, Any] | None

    def __init__(self) -> None:
        """Initialize DbSubscriptionDiff (no auto-table creation, use migrations)."""
        self.handle = None

    def get(
        self,
        actor_id: str | None = None,
        subid: str | None = None,
        seqnr: int | None = None,
    ) -> dict[str, Any] | None:
        """
        Retrieve subscription diff from the database.

        If seqnr is not provided, returns the diff with the lowest sequence number.

        Args:
            actor_id: The actor ID
            subid: The subscription ID
            seqnr: The sequence number (optional)

        Returns:
            Dict with subscription diff data, or None if not found
        """
        if not actor_id and not self.handle:
            return None

        if not subid and not self.handle:
            logger.debug("Attempt to get subscriptiondiff without subid")
            return None

        if self.handle:
            # Return cached handle
            t = self.handle
            return {
                "id": t["id"],
                "subscriptionid": t["subid"],
                "timestamp": t["timestamp"],
                "data": t["diff"],
                "sequence": t["seqnr"],
            }

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if seqnr is not None:
                        # Get specific diff by seqnr
                        subid_seqnr = (subid or "") + ":" + str(seqnr)
                        cur.execute(
                            """
                            SELECT id, subid_seqnr, subid, timestamp, diff, seqnr
                            FROM subscription_diffs
                            WHERE id = %s AND subid_seqnr = %s
                            """,
                            (actor_id, subid_seqnr),
                        )
                        row = cur.fetchone()

                        if not row:
                            return None

                        self.handle = {
                            "id": row[0],
                            "subid": row[2],
                            "timestamp": row[3],
                            "diff": row[4],
                            "seqnr": row[5],
                        }

                    else:
                        # Find the record with lowest seqnr for this subid
                        cur.execute(
                            """
                            SELECT id, subid_seqnr, subid, timestamp, diff, seqnr
                            FROM subscription_diffs
                            WHERE id = %s AND subid = %s
                            ORDER BY seqnr ASC
                            LIMIT 1
                            """,
                            (actor_id, subid),
                        )
                        row = cur.fetchone()

                        if not row:
                            return None

                        self.handle = {
                            "id": row[0],
                            "subid": row[2],
                            "timestamp": row[3],
                            "diff": row[4],
                            "seqnr": row[5],
                        }

                    # Return result
                    return {
                        "id": self.handle["id"],
                        "subscriptionid": self.handle["subid"],
                        "timestamp": self.handle["timestamp"],
                        "data": self.handle["diff"],
                        "sequence": self.handle["seqnr"],
                    }

        except Exception as e:
            logger.error(
                f"Error retrieving subscription diff {actor_id}/{subid}/{seqnr}: {e}"
            )
            return None

    def create(
        self,
        actor_id: str | None = None,
        subid: str | None = None,
        diff: str = "",
        seqnr: int = 1,
    ) -> bool:
        """
        Create a new subscription diff.

        Args:
            actor_id: The actor ID
            subid: The subscription ID
            diff: The diff data
            seqnr: The sequence number (default 1)

        Returns:
            True on success, False on failure
        """
        if not actor_id or not subid:
            logger.debug("Attempt to create subscriptiondiff without actorid or subid")
            return False

        subid_seqnr = subid + ":" + str(seqnr)
        timestamp = datetime.utcnow()

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO subscription_diffs (
                            id, subid_seqnr, subid, timestamp, diff, seqnr
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (actor_id, subid_seqnr, subid, timestamp, diff, seqnr),
                    )
                conn.commit()

            # Build handle
            self.handle = {
                "id": actor_id,
                "subid": subid,
                "timestamp": timestamp,
                "diff": diff,
                "seqnr": seqnr,
            }

            return True

        except Exception as e:
            logger.error(
                f"Error creating subscription diff {actor_id}/{subid}/{seqnr}: {e}"
            )
            return False

    def delete(self) -> bool:
        """
        Delete subscription diff using self.handle.

        Returns:
            True on success, False on failure
        """
        if not self.handle:
            return False

        actor_id = self.handle.get("id")
        subid = self.handle.get("subid")
        seqnr = self.handle.get("seqnr")

        if not actor_id or not subid or seqnr is None:
            logger.error("DbSubscriptionDiff handle missing required fields")
            return False

        subid_seqnr = subid + ":" + str(seqnr)

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM subscription_diffs
                        WHERE id = %s AND subid_seqnr = %s
                        """,
                        (actor_id, subid_seqnr),
                    )
                conn.commit()

            self.handle = None
            return True

        except Exception as e:
            logger.error(
                f"Error deleting subscription diff {actor_id}/{subid_seqnr}: {e}"
            )
            return False


class DbSubscriptionDiffList:
    """
    DbSubscriptionDiffList does all the db operations for list of diff objects.

    The actor_id must always be set.
    """

    handle: Any | None
    diffs: list[dict[str, Any]] | None
    actor_id: str | None
    subid: str | None

    def __init__(self) -> None:
        """Initialize DbSubscriptionDiffList."""
        self.handle = None
        self.diffs = []
        self.actor_id = None
        self.subid = None

    def fetch(
        self, actor_id: str | None = None, subid: str | None = None
    ) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve subscription diffs for an actor.

        Args:
            actor_id: The actor ID
            subid: Optional subscription ID to filter by

        Returns:
            List of subscription diff dicts sorted by sequence, or empty list if none found
        """
        if not actor_id:
            return []

        self.actor_id = actor_id
        self.subid = subid
        self.diffs = []

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if subid:
                        # Fetch diffs for specific subscription
                        cur.execute(
                            """
                            SELECT id, subid_seqnr, subid, timestamp, diff, seqnr
                            FROM subscription_diffs
                            WHERE id = %s AND subid = %s
                            ORDER BY seqnr
                            """,
                            (actor_id, subid),
                        )
                    else:
                        # Fetch all diffs for actor
                        cur.execute(
                            """
                            SELECT id, subid_seqnr, subid, timestamp, diff, seqnr
                            FROM subscription_diffs
                            WHERE id = %s
                            ORDER BY seqnr
                            """,
                            (actor_id,),
                        )

                    rows = cur.fetchall()

                    for row in rows:
                        self.diffs.append(
                            {
                                "id": row[0],
                                "subscriptionid": row[2],
                                "timestamp": row[3],
                                "diff": row[4],
                                "sequence": row[5],
                            }
                        )

                    return self.diffs

        except Exception as e:
            logger.error(f"Error fetching subscription diffs for actor {actor_id}: {e}")
            return []

    def delete(self, seqnr: int | None = None) -> bool:
        """
        Delete fetched subscription diffs.

        Optional seqnr deletes up to and including a specific seqnr.

        Args:
            seqnr: Optional sequence number to delete up to (inclusive)

        Returns:
            True on success, False on failure
        """
        if not self.actor_id:
            return False

        if not seqnr or not isinstance(seqnr, int):
            seqnr = 0

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if self.subid:
                        if seqnr == 0:
                            # Delete all diffs for this subscription
                            cur.execute(
                                """
                                DELETE FROM subscription_diffs
                                WHERE id = %s AND subid = %s
                                """,
                                (self.actor_id, self.subid),
                            )
                        else:
                            # Delete diffs up to and including seqnr
                            cur.execute(
                                """
                                DELETE FROM subscription_diffs
                                WHERE id = %s AND subid = %s AND seqnr <= %s
                                """,
                                (self.actor_id, self.subid, seqnr),
                            )
                    else:
                        if seqnr == 0:
                            # Delete all diffs for this actor
                            cur.execute(
                                """
                                DELETE FROM subscription_diffs
                                WHERE id = %s
                                """,
                                (self.actor_id,),
                            )
                        else:
                            # Delete all diffs up to and including seqnr
                            cur.execute(
                                """
                                DELETE FROM subscription_diffs
                                WHERE id = %s AND seqnr <= %s
                                """,
                                (self.actor_id, seqnr),
                            )

                conn.commit()

            self.handle = None
            return True

        except Exception as e:
            logger.error(
                f"Error deleting subscription diffs for actor {self.actor_id}: {e}"
            )
            return False
