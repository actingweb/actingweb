"""PostgreSQL implementation of attribute database operations."""

import json
import logging
import time
from datetime import datetime
from typing import Any

from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


class DbAttribute:
    """
    DbAttribute does all the db operations for attribute objects (internal).

    The actor_id must always be set. get_attr(), set_attr() work with
    individual attributes in buckets.
    """

    def __init__(self) -> None:
        """Initialize DbAttribute (no auto-table creation, use migrations)."""
        pass

    @staticmethod
    def get_bucket(
        actor_id: str | None = None, bucket: str | None = None
    ) -> dict[str, dict[str, Any]] | None:
        """
        Get all attributes from a bucket.

        Args:
            actor_id: The actor ID
            bucket: The bucket name

        Returns:
            Dict of {attribute_name: {data: ..., timestamp: ...}}, or None
        """
        if not actor_id or not bucket:
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Query all attributes in this bucket
                    cur.execute(
                        """
                        SELECT name, data, timestamp
                        FROM attributes
                        WHERE id = %s AND bucket = %s
                        """,
                        (actor_id, bucket),
                    )
                    rows = cur.fetchall()

                    if not rows:
                        return None

                    ret = {}
                    for row in rows:
                        ret[row[0]] = {
                            "data": row[1],
                            "timestamp": row[2],
                        }

                    return ret

        except Exception as e:
            logger.error(f"Error retrieving bucket {actor_id}/{bucket}: {e}")
            return None

    @staticmethod
    def get_attr(
        actor_id: str | None = None, bucket: str | None = None, name: str | None = None
    ) -> dict[str, Any] | None:
        """
        Get a single attribute from a bucket.

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name

        Returns:
            Dict with {data: ..., timestamp: ...}, or None
        """
        if not actor_id or not bucket or not name:
            return None

        bucket_name = bucket + ":" + name

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT data, timestamp
                        FROM attributes
                        WHERE id = %s AND bucket_name = %s
                        """,
                        (actor_id, bucket_name),
                    )
                    row = cur.fetchone()

                    if not row:
                        return None

                    return {
                        "data": row[0],
                        "timestamp": row[1],
                    }

        except Exception as e:
            logger.error(f"Error retrieving attribute {actor_id}/{bucket}/{name}: {e}")
            return None

    @staticmethod
    def set_attr(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        data: Any = None,
        timestamp: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Set a data value for a given attribute in a bucket.

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name
            data: The data to store (JSON-serializable)
            timestamp: Optional timestamp
            ttl_seconds: Optional TTL in seconds from now. If provided,
                         PostgreSQL cleanup jobs should delete this item after expiry.
                         Note: A 1-hour buffer is added for clock skew safety.

        Returns:
            True on success, False on failure
        """
        if not actor_id or not name or not bucket:
            return False

        # Empty data means delete
        if not data:
            bucket_name = bucket + ":" + name
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            DELETE FROM attributes
                            WHERE id = %s AND bucket_name = %s
                            """,
                            (actor_id, bucket_name),
                        )
                    conn.commit()
                return True
            except Exception as e:
                logger.error(
                    f"Error deleting attribute {actor_id}/{bucket}/{name}: {e}"
                )
                return False

        # Calculate TTL timestamp if provided
        ttl_timestamp = None
        if ttl_seconds is not None:
            from actingweb.constants import TTL_CLOCK_SKEW_BUFFER

            # Add buffer for clock skew safety
            ttl_timestamp = int(time.time()) + ttl_seconds + TTL_CLOCK_SKEW_BUFFER

        bucket_name = bucket + ":" + name

        # Convert data to JSON if it's not already a string
        if isinstance(data, dict) or isinstance(data, list):
            data_json = data
        else:
            # Store as-is in JSONB (psycopg will handle conversion)
            data_json = data

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Use INSERT ... ON CONFLICT to upsert
                    cur.execute(
                        """
                        INSERT INTO attributes (
                            id, bucket_name, bucket, name, data, timestamp, ttl_timestamp
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (id, bucket_name)
                        DO UPDATE SET
                            data = EXCLUDED.data,
                            timestamp = EXCLUDED.timestamp,
                            ttl_timestamp = EXCLUDED.ttl_timestamp
                        """,
                        (
                            actor_id,
                            bucket_name,
                            bucket,
                            name,
                            json.dumps(data_json),
                            timestamp,
                            ttl_timestamp,
                        ),
                    )
                conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error setting attribute {actor_id}/{bucket}/{name}: {e}")
            return False

    def delete_attr(
        self,
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
    ) -> bool:
        """
        Delete an attribute in a bucket.

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name

        Returns:
            True on success, False on failure
        """
        return self.set_attr(actor_id=actor_id, bucket=bucket, name=name, data=None)

    @staticmethod
    def conditional_update_attr(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        old_data: Any = None,
        new_data: Any = None,
        timestamp: datetime | None = None,
    ) -> bool:
        """
        Conditionally update an attribute only if current data matches old_data.

        This provides atomic compare-and-swap functionality for race-free updates.

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name
            old_data: Expected current data value (for comparison)
            new_data: New data to set if current matches old_data
            timestamp: Optional timestamp

        Returns:
            True if update succeeded (current matched old_data), False otherwise
        """
        if not actor_id or not bucket or not name:
            return False

        bucket_name = bucket + ":" + name

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Update only if current data matches old_data
                    # Use JSONB comparison for reliability - PostgreSQL normalizes JSONB values
                    # so key ordering and whitespace differences don't affect equality
                    cur.execute(
                        """
                        UPDATE attributes
                        SET data = %s::jsonb, timestamp = %s
                        WHERE id = %s AND bucket_name = %s AND data = %s::jsonb
                        """,
                        (
                            json.dumps(new_data),
                            timestamp,
                            actor_id,
                            bucket_name,
                            json.dumps(old_data),
                        ),
                    )
                    rows_updated = cur.rowcount
                conn.commit()

                # Return True if exactly one row was updated
                return rows_updated == 1

        except Exception as e:
            logger.error(
                f"Error conditionally updating attribute {actor_id}/{bucket}/{name}: {e}"
            )
            return False

    @staticmethod
    def delete_bucket(actor_id: str | None = None, bucket: str | None = None) -> bool:
        """
        Delete an entire bucket.

        Args:
            actor_id: The actor ID
            bucket: The bucket name

        Returns:
            True on success, False on failure
        """
        if not actor_id or not bucket:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM attributes
                        WHERE id = %s AND bucket = %s
                        """,
                        (actor_id, bucket),
                    )
                conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error deleting bucket {actor_id}/{bucket}: {e}")
            return False


class DbAttributeBucketList:
    """
    DbAttributeBucketList handles multiple buckets.

    The actor_id must always be set.
    """

    def __init__(self) -> None:
        """Initialize DbAttributeBucketList."""
        pass

    @staticmethod
    def fetch(
        actor_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]] | None:
        """
        Retrieve all attributes for an actor, grouped by bucket.

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {bucket: {name: {data: ..., timestamp: ...}}}, or None
        """
        if not actor_id:
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT bucket, name, data, timestamp
                        FROM attributes
                        WHERE id = %s
                        ORDER BY bucket, name
                        """,
                        (actor_id,),
                    )
                    rows = cur.fetchall()

                    if not rows:
                        return None

                    ret: dict[str, dict[str, dict[str, Any]]] = {}
                    for row in rows:
                        bucket = row[0]
                        name = row[1]
                        data = row[2]
                        timestamp = row[3]

                        if bucket not in ret:
                            ret[bucket] = {}

                        ret[bucket][name] = {
                            "data": data,
                            "timestamp": timestamp,
                        }

                    return ret

        except Exception as e:
            logger.error(f"Error fetching all attributes for actor {actor_id}: {e}")
            return None

    @staticmethod
    def delete(actor_id: str | None = None) -> bool:
        """
        Delete all attributes for an actor.

        Args:
            actor_id: The actor ID

        Returns:
            True on success, False on failure
        """
        if not actor_id:
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM attributes
                        WHERE id = %s
                        """,
                        (actor_id,),
                    )
                conn.commit()
            return True

        except Exception as e:
            logger.error(f"Error deleting all attributes for actor {actor_id}: {e}")
            return False
