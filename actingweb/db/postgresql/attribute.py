"""PostgreSQL implementation of attribute database operations."""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


def _delete_diagnostics_enabled() -> bool:
    """Whether to emit per-DELETE diagnostics for the attribute table.

    Off by default. Set ``ACTINGWEB_PG_DELETE_DIAGNOSTICS=1`` to turn it on;
    enabled in the parallel PostgreSQL CI matrix, where a per-actor attribute
    ``DELETE`` has intermittently failed to take effect since 2026-06-15
    (``thoughts/todo/2026-06-15-postgres-parallel-delete-not-persisting.md``).

    The two candidate mechanisms produce different evidence, and nothing in the
    logs today distinguishes them:

    * **0 rows matched** — the statement ran against the wrong schema (a pooled
      connection whose ``search_path`` drifted under per-worker isolation) or
      against the wrong key.
    * **1 row matched but is still readable afterwards** — the statement matched
      and the transaction did not durably commit, or the follow-up read is
      served from a *different* schema than the delete was.

    So the diagnostic reports the rowcount, the schema the deleting connection
    resolved, and a post-commit re-read on a freshly checked-out connection with
    the schema *it* resolved. One failing CI run then names the mechanism.
    """
    return os.getenv("ACTINGWEB_PG_DELETE_DIAGNOSTICS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


_DIAG_SAVEPOINT = "actingweb_delete_diag"


def _read_schema_state(cur: Any) -> tuple[str, str] | None:
    """Read the connection's schema and ``search_path``, inside a savepoint.

    **The savepoint is load-bearing, and so is running this before the DELETE.**
    A server-side failure in this query — a statement timeout, a cancellation —
    marks the *entire* PostgreSQL transaction as aborted. Catching the Python
    exception does not un-abort it: the later ``conn.commit()`` would silently
    degrade to a rollback while ``set_attr()`` still returned ``True``. That is
    precisely the "DELETE that does not persist" this instrumentation exists to
    diagnose, which would make the diagnostic a source of the bug it is meant to
    identify. Reported by Codex review on PR #128.

    Rolling back to a savepoint taken *before* the query restores the
    transaction to a usable state, so the DELETE that follows is unaffected
    either way. Returns ``None`` when the state could not be read; the delete
    proceeds and the log line says ``schema=?``.
    """
    try:
        cur.execute(f"SAVEPOINT {_DIAG_SAVEPOINT}")
    except Exception:  # pragma: no cover - defensive
        logger.warning("PG_DELETE_DIAG could not open a savepoint", exc_info=True)
        return None

    try:
        cur.execute("SELECT current_schema(), current_setting('search_path')")
        row = cur.fetchone()
        cur.execute(f"RELEASE SAVEPOINT {_DIAG_SAVEPOINT}")
    except Exception:
        logger.warning(
            "PG_DELETE_DIAG could not read connection schema state", exc_info=True
        )
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {_DIAG_SAVEPOINT}")
        except Exception:  # pragma: no cover - connection is beyond saving
            # The DELETE below will now fail loudly and set_attr() returns
            # False. Loud is the correct outcome; silent success is not.
            logger.warning("PG_DELETE_DIAG could not roll back to savepoint")
        return None

    if not row:  # pragma: no cover - current_schema() always returns a row
        return None
    return (row[0], row[1])


def _log_delete_diagnostics(
    conn: Any,
    actor_id: str,
    bucket: str,
    name: str,
    rowcount: int,
    schema_state: tuple[str, str] | None,
) -> None:
    """Record where the DELETE landed, using state captured before it ran."""
    schema, search_path = schema_state if schema_state else ("?", "?")
    logger.warning(
        "PG_DELETE_DIAG attr=%s/%s/%s rowcount=%s conn=%s schema=%s search_path=%s",
        actor_id,
        bucket,
        name,
        rowcount,
        id(conn),
        schema,
        search_path,
    )


def _log_delete_aftermath(actor_id: str, bucket: str, name: str, rowcount: int) -> None:
    """Re-read the deleted row on a fresh connection, after the commit.

    This is the half that separates the two mechanisms. ``present=True`` here
    with ``rowcount=1`` above means the DELETE matched and the row survived it
    — either the commit did not stick, or the reader is looking at a different
    schema than the writer, which the logged schema pair then shows directly.
    """
    bucket_name = bucket + ":" + name
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT current_schema(), current_setting('search_path'),
                           EXISTS(
                               SELECT 1 FROM attributes
                               WHERE id = %s AND bucket_name = %s
                           )
                    """,
                    (actor_id, bucket_name),
                )
                row = cur.fetchone()
        logger.warning(
            "PG_DELETE_DIAG post-commit attr=%s/%s/%s rowcount=%s conn=%s "
            "schema=%s search_path=%s present=%s",
            actor_id,
            bucket,
            name,
            rowcount,
            id(conn),
            row[0] if row else "?",
            row[1] if row else "?",
            row[2] if row else "?",
        )
    except Exception:  # pragma: no cover - diagnostics must never break the delete
        logger.warning("PG_DELETE_DIAG post-commit re-read failed", exc_info=True)


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
    def get_attr_strict(
        actor_id: str | None = None, bucket: str | None = None, name: str | None = None
    ) -> dict[str, Any] | None:
        """Read one attribute, distinguishing absence from failure.

        ``get_attr()`` logs and returns ``None`` for both a missing row and a
        failed query. Callers whose "absent" branch is a decision rather than a
        fallback — the deletion tombstone read — need the two separated, so
        operational errors propagate here instead of being swallowed.

        Expired rows read as absent. ``ttl_timestamp`` is only reclaimed by an
        explicit ``delete_expired()`` sweep on this backend, so honouring it at
        read time is what makes TTL mean the same thing on both backends.
        """
        if not actor_id or not bucket or not name:
            return None

        bucket_name = bucket + ":" + name

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data, timestamp, ttl_timestamp
                    FROM attributes
                    WHERE id = %s AND bucket_name = %s
                    """,
                    (actor_id, bucket_name),
                )
                row = cur.fetchone()

        if not row:
            return None
        if row[2] is not None and row[2] <= int(time.time()):
            return None
        return {
            "data": row[0],
            "timestamp": row[1],
        }

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
            diagnostics = _delete_diagnostics_enabled()
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        # Before the DELETE, and savepoint-isolated — see
                        # _read_schema_state() for why that ordering is not
                        # cosmetic.
                        schema_state = _read_schema_state(cur) if diagnostics else None
                        cur.execute(
                            """
                            DELETE FROM attributes
                            WHERE id = %s AND bucket_name = %s
                            """,
                            (actor_id, bucket_name),
                        )
                        rowcount = cur.rowcount
                        if diagnostics:
                            _log_delete_diagnostics(
                                conn, actor_id, bucket, name, rowcount, schema_state
                            )
                    conn.commit()
                if diagnostics:
                    _log_delete_aftermath(actor_id, bucket, name, rowcount)
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

        # Defensive sanitization of data before JSON encoding
        from actingweb.db.utils import sanitize_json_data

        data_json = sanitize_json_data(data_json, log_source="attribute")

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
    def delete_attr_conditional(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
    ) -> bool:
        """
        Atomically delete an attribute, returning True only if THIS call
        removed an existing row.

        A single ``DELETE`` statement takes a row lock: when two transactions
        race on the same attribute, one deletes the row (rowcount 1) and the
        other, after the first commits, finds nothing to delete (rowcount 0).
        Exactly one caller sees True. Backs single-use/atomic-consume
        semantics (e.g. mobile-ticket redemption).

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name

        Returns:
            True if this call removed an existing row, False otherwise
        """
        if not actor_id or not bucket or not name:
            return False

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
                    rows_deleted = cur.rowcount
                conn.commit()
            return rows_deleted == 1
        except Exception as e:
            logger.error(
                f"Error conditionally deleting attribute {actor_id}/{bucket}/{name}: {e}"
            )
            return False

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

        # Defensive sanitization of data before JSON encoding
        from actingweb.db.utils import sanitize_json_data

        new_data = sanitize_json_data(new_data, log_source="attribute")
        old_data = sanitize_json_data(old_data, log_source="attribute")

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

    @staticmethod
    def delete_expired(
        now_epoch: int | None = None, buckets: list[str] | None = None
    ) -> int:
        """
        Delete attributes whose ttl_timestamp is in the past.

        Issues a single set-based DELETE backed by the partial index
        ``idx_attributes_ttl`` (``ttl_timestamp WHERE ttl_timestamp IS NOT
        NULL``), so cost scales with the number of expired rows rather than the
        whole table. Optionally restricted to specific buckets.

        Args:
            now_epoch: Cutoff Unix timestamp (defaults to now).
            buckets: Optional bucket whitelist to scope the purge.

        Returns:
            Number of rows deleted.
        """
        if now_epoch is None:
            now_epoch = int(time.time())

        sql = (
            "DELETE FROM attributes "
            "WHERE ttl_timestamp IS NOT NULL AND ttl_timestamp < %s"
        )
        params: list[Any] = [now_epoch]
        if buckets:
            sql += " AND bucket = ANY(%s)"
            params.append(list(buckets))

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    deleted = cur.rowcount
                conn.commit()
            return deleted if deleted and deleted > 0 else 0
        except Exception as e:
            logger.error(f"Error purging expired attributes: {e}")
            return 0

    @staticmethod
    def delete_by_chain(
        actor_id: str | None = None,
        buckets: list[str] | None = None,
        chain_id: str | None = None,
    ) -> int:
        """
        Delete attributes whose stored ``data->>'chain_id'`` matches ``chain_id``.

        Backs refresh-token family (chain) revocation. A single set-based DELETE
        backed by the partial expression index ``idx_attributes_chain_id`` on
        ``(data ->> 'chain_id')`` — so cost scales with the number of rows in the
        chain (a handful), not the whole shared token partition.

        Args:
            actor_id: Storage partition id (the system actor the tokens live under).
            buckets: Bucket whitelist (the SPA access + refresh token buckets).
            chain_id: The refresh-token family identifier to delete.

        Returns:
            Number of rows deleted.
        """
        if not actor_id or not chain_id or not buckets:
            return 0

        sql = (
            "DELETE FROM attributes "
            "WHERE id = %s AND bucket = ANY(%s) AND data->>'chain_id' = %s"
        )
        params: list[Any] = [actor_id, list(buckets), chain_id]
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    deleted = cur.rowcount
                conn.commit()
            return deleted if deleted and deleted > 0 else 0
        except Exception as e:
            logger.error(f"Error deleting token chain: {e}")
            return 0


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
    def fetch_timestamps(
        actor_id: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Retrieve timestamps for all attribute buckets.

        Args:
            actor_id: The actor ID

        Returns:
            Dict of {bucket: timestamp}, or None
        """
        if not actor_id:
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT bucket, MAX(timestamp) as max_timestamp
                        FROM attributes
                        WHERE id = %s
                        GROUP BY bucket
                        ORDER BY bucket
                        """,
                        (actor_id,),
                    )
                    rows = cur.fetchall()

                    if not rows:
                        return None

                    ret: dict[str, Any] = {}
                    for row in rows:
                        bucket = row[0]
                        timestamp = row[1]
                        ret[bucket] = timestamp

                    return ret

        except Exception as e:
            logger.error(f"Error fetching timestamps for actor {actor_id}: {e}")
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
