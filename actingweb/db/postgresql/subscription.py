"""PostgreSQL implementation of subscription database operations."""

import logging
from typing import Any

import psycopg

from actingweb.db.exceptions import DbError
from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


class DbSubscription:
    """
    DbSubscription does all the db operations for subscription objects.

    The actor_id must always be set.
    """

    handle: dict[str, Any] | None

    def __init__(self) -> None:
        """Initialize DbSubscription (no auto-table creation, use migrations)."""
        self.handle = None

    def get(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
        *,
        strict: bool = True,
    ) -> dict[str, Any] | None:
        """
        Retrieve subscription from the database.

        Args:
            actor_id: The actor ID
            peerid: The peer ID
            subid: The subscription ID

        Returns:
            Dict with subscription data, or None if not found
        """
        if not actor_id:
            return None

        if not peerid or not subid:
            logger.debug("Attempt to get subscription without peerid or subid")
            return None

        peer_sub_id = peerid + ":" + subid

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, peer_sub_id, peerid, subid, granularity,
                               target, subtarget, resource, seqnr, callback
                        FROM subscriptions
                        WHERE id = %s AND peer_sub_id = %s
                        """,
                        (actor_id, peer_sub_id),
                    )
                    row = cur.fetchone()

                    if not row:
                        return None

                    # Build result dict
                    result: dict[str, Any] = {
                        "id": row[0],
                        "peerid": row[2],
                        "subscriptionid": row[3],
                        "granularity": row[4] or "",
                        "target": row[5] or "",
                        "subtarget": row[6] or "",
                        "resource": row[7] or "",
                        "sequence": row[8],
                        "callback": row[9],
                    }

                    # Store handle for future operations
                    self.handle = result
                    return result

        except Exception as e:
            if strict:
                raise DbError("subscription get") from e
            logger.error(
                f"Error retrieving subscription {actor_id}/{peerid}/{subid}: {e}"
            )
            return None

    def create(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
        granularity: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        seqnr: int = 0,
        callback: bool = False,
    ) -> bool:
        """
        Create a new subscription.

        Args:
            actor_id: The actor ID
            peerid: The peer ID
            subid: The subscription ID
            granularity: Granularity
            target: Target
            subtarget: Subtarget
            resource: Resource
            seqnr: Sequence number (default 0)
            callback: Callback flag (default False)

        Returns:
            True on success, False only for missing arguments or handle

        Raises:
            DbError: on a backend fault
        """
        if not actor_id or not peerid or not subid:
            return False

        # Check if subscription already exists
        if self.get(actor_id=actor_id, peerid=peerid, subid=subid):
            return False

        peer_sub_id = peerid + ":" + subid

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO subscriptions (
                            id, peer_sub_id, peerid, subid, granularity,
                            target, subtarget, resource, seqnr, callback
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            actor_id,
                            peer_sub_id,
                            peerid,
                            subid,
                            granularity,
                            target,
                            subtarget,
                            resource,
                            seqnr,
                            callback,
                        ),
                    )
                conn.commit()

            # Build handle
            self.handle = {
                "id": actor_id,
                "peerid": peerid,
                "subscriptionid": subid,
                "granularity": granularity or "",
                "target": target or "",
                "subtarget": subtarget or "",
                "resource": resource or "",
                "sequence": seqnr,
                "callback": callback,
            }

            return True

        except psycopg.errors.UniqueViolation:
            # A concurrent create won: the row exists, as the pre-check would
            # have said. Answer False like DbActor.create, not a 503 that
            # every retry would repeat.
            logger.warning(f"Trying to create a subscription that exists ({actor_id})")
            return False
        except Exception as e:
            raise DbError("subscription create") from e

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
        Modify a subscription.

        Args:
            peerid: New peer ID
            subid: New subscription ID
            granularity: New granularity
            target: New target
            subtarget: New subtarget
            resource: New resource
            seqnr: New sequence number
            callback: New callback flag

        Returns:
            True on success, False only for missing arguments or handle

        Raises:
            DbError: on a backend fault
        """
        if not self.handle:
            logger.debug("Attempted modification of DbSubscription without db handle")
            return False

        actor_id = self.handle.get("id")
        current_peerid = self.handle.get("peerid")
        current_subid = self.handle.get("subscriptionid")

        if not actor_id or not current_peerid or not current_subid:
            logger.error("DbSubscription handle missing required fields")
            return False

        peer_sub_id = current_peerid + ":" + current_subid

        # Build update query dynamically
        updates = []
        params = []

        if peerid and len(peerid) > 0:
            updates.append("peerid = %s")
            params.append(peerid)
            self.handle["peerid"] = peerid

        if subid and len(subid) > 0:
            updates.append("subid = %s")
            params.append(subid)
            self.handle["subscriptionid"] = subid

        if granularity and len(granularity) > 0:
            updates.append("granularity = %s")
            params.append(granularity)
            self.handle["granularity"] = granularity

        if callback is not None:
            updates.append("callback = %s")
            params.append(callback)
            self.handle["callback"] = callback

        if target and len(target) > 0:
            updates.append("target = %s")
            params.append(target)
            self.handle["target"] = target

        if subtarget and len(subtarget) > 0:
            updates.append("subtarget = %s")
            params.append(subtarget)
            self.handle["subtarget"] = subtarget

        if resource and len(resource) > 0:
            updates.append("resource = %s")
            params.append(resource)
            self.handle["resource"] = resource

        if seqnr is not None:
            updates.append("seqnr = %s")
            params.append(seqnr)
            self.handle["sequence"] = seqnr

        if not updates:
            return True  # Nothing to update

        # Add WHERE clause parameters
        params.extend([actor_id, peer_sub_id])

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE subscriptions
                        SET {", ".join(updates)}
                        WHERE id = %s AND peer_sub_id = %s
                        """,
                        tuple(params),
                    )
                conn.commit()
            return True

        except Exception as e:
            raise DbError("subscription modify") from e

    def increment_seq(
        self,
        actor_id: str | None = None,
        peerid: str | None = None,
        subid: str | None = None,
    ) -> int | None:
        """Atomically add 1 to the stored sequence and return the new value.

        One ``UPDATE ... SET seqnr = seqnr + 1 ... RETURNING seqnr``: two
        concurrent writers get two numbers. Works on the loaded handle, or on
        the row the three keys name without reading it first. None when the
        subscription row does not exist. A fault raises ``DbError``; the
        increment may then have committed, so the caller must not reuse the
        number it expected.
        """
        keyed = bool(actor_id and peerid and subid)
        if not keyed:
            if not self.handle:
                logger.debug(
                    "Attempted increment_seq of DbSubscription without db handle"
                )
                return None
            actor_id = self.handle.get("id")
            peerid = self.handle.get("peerid")
            subid = self.handle.get("subscriptionid")
        if not actor_id or not peerid or not subid:
            logger.error("DbSubscription handle missing required fields")
            return None
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE subscriptions
                        SET seqnr = seqnr + 1
                        WHERE id = %s AND peer_sub_id = %s
                        RETURNING seqnr
                        """,
                        (actor_id, peerid + ":" + subid),
                    )
                    row = cur.fetchone()
                conn.commit()
        except Exception as e:
            raise DbError("subscription increment_seq") from e
        if row is None:
            return None
        if not keyed and self.handle is not None:
            self.handle["sequence"] = int(row[0])
        return int(row[0])

    def delete(self) -> bool:
        """
        Delete subscription using self.handle.

        Returns:
            True on success, False only for missing arguments or handle

        Raises:
            DbError: on a backend fault
        """
        if not self.handle:
            logger.debug("Attempted delete of DbSubscription with no handle set.")
            return False

        actor_id = self.handle.get("id")
        peerid = self.handle.get("peerid")
        subid = self.handle.get("subscriptionid")

        if not actor_id or not peerid or not subid:
            logger.error("DbSubscription handle missing required fields")
            return False

        peer_sub_id = peerid + ":" + subid

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM subscriptions
                        WHERE id = %s AND peer_sub_id = %s
                        """,
                        (actor_id, peer_sub_id),
                    )
                conn.commit()

            self.handle = None
            return True

        except Exception as e:
            raise DbError("subscription delete") from e


class DbSubscriptionList:
    """
    DbSubscriptionList does all the db operations for list of subscription objects.

    The actor_id must always be set.
    """

    handle: Any | None
    actor_id: str | None
    subscriptions: list[dict[str, Any]] | None

    def __init__(self) -> None:
        """Initialize DbSubscriptionList."""
        self.handle = None
        self.actor_id = None
        self.subscriptions = []

    def fetch(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> list[dict[str, Any]] | list[Any]:
        """
        Retrieve all subscriptions for an actor.

        Args:
            actor_id: The actor ID

        Returns:
            List of subscription dicts, or empty list if none found
        """
        if not actor_id:
            return []

        self.actor_id = actor_id
        self.subscriptions = []

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, peer_sub_id, peerid, subid, granularity,
                               target, subtarget, resource, seqnr, callback
                        FROM subscriptions
                        WHERE id = %s
                        ORDER BY peer_sub_id
                        """,
                        (actor_id,),
                    )
                    rows = cur.fetchall()

                    for row in rows:
                        self.subscriptions.append(
                            {
                                "id": row[0],
                                "peerid": row[2],
                                "subscriptionid": row[3],
                                "granularity": row[4] or "",
                                "target": row[5] or "",
                                "subtarget": row[6] or "",
                                "resource": row[7] or "",
                                "sequence": row[8],
                                "callback": row[9],
                            }
                        )

                    return self.subscriptions

        except Exception as e:
            if strict:
                raise DbError("subscription list fetch") from e
            logger.error(f"Error fetching subscriptions for actor {actor_id}: {e}")
            return []

    def delete(self) -> bool:
        """
        Delete all subscriptions for the actor.

        Returns:
            True on success, False only for missing arguments or handle

        Raises:
            DbError: on a backend fault
        """
        if not self.actor_id:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM subscriptions
                        WHERE id = %s
                        """,
                        (self.actor_id,),
                    )
                conn.commit()

            self.handle = None
            return True

        except Exception as e:
            raise DbError("subscription list delete") from e
