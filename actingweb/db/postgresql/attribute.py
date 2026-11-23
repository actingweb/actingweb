"""PostgreSQL implementation of attribute database operations."""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from actingweb.db.exceptions import AttributeKeyCollision, DbError, require_json
from actingweb.db.postgresql.connection import get_connection

logger = logging.getLogger(__name__)


def ttl_deadline(ttl_seconds: int) -> int:
    """The stored ``ttl_timestamp`` for a row that lives ``ttl_seconds``.

    Adds ``TTL_CLOCK_SKEW_BUFFER`` so the expired-row purge never removes a row
    before its application-level expiry, whatever the clock skew.
    """
    from actingweb.constants import TTL_CLOCK_SKEW_BUFFER

    return int(time.time()) + ttl_seconds + TTL_CLOCK_SKEW_BUFFER


LIST_ROWS_INDEX = "ix_attributes_list_rows"
LIST_ROWS_REVISION = "a7b8c9d0e1f2"


def attribute_schema_problems() -> list[str]:
    """What keeps attribute lists from working on this schema: the two
    columns not yet TEXT, the list-row index missing or INVALID. ``[]`` when
    ready. Raises on a fault (``check_ready()`` refuses then too)."""
    from actingweb.db.postgresql.connection import get_schema_name

    schema = get_schema_name()
    problems: list[str] = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = 'attributes' "
                "AND column_name IN ('bucket_name', 'name')",
                (schema,),
            )
            types = {row[0]: row[1] for row in cur.fetchall()}
            cur.execute(
                "SELECT i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = %s AND n.nspname = %s",
                (LIST_ROWS_INDEX, schema),
            )
            index = cur.fetchone()
    for column in ("bucket_name", "name"):
        if types.get(column) != "text":
            problems.append(
                f"attributes.{column} is {types.get(column, 'missing')}, not text"
            )
    if index is None:
        problems.append(f"the index {LIST_ROWS_INDEX} is missing")
    elif not index[0]:
        problems.append(
            f"the index {LIST_ROWS_INDEX} is INVALID (a concurrent build that "
            "failed part-way): run 'alembic upgrade head' again, which drops "
            "and rebuilds it when the build failed during the upgrade, or "
            f"'REINDEX INDEX CONCURRENTLY {LIST_ROWS_INDEX}'"
        )
    return problems


def _delete_diagnostics_enabled() -> bool:
    """Whether to emit per-DELETE diagnostics for the attribute table.

    Off by default. Set ``ACTINGWEB_PG_DELETE_DIAGNOSTICS=1`` to turn it on;
    enabled in the parallel PostgreSQL CI matrix, where a per-actor attribute
    ``DELETE`` intermittently failed to take effect between 2026-06-15 and
    2026-08-15. The symptom has not recurred since the path was instrumented
    (#128); the investigation record was a todo, retired on 2026-09-02, and is
    readable with ``git show aaf101f:thoughts/todo/2026-06-15-postgres-parallel-delete-not-persisting.md``.

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
    except Exception:
        # If SAVEPOINT itself fails the transaction was already unusable before
        # we got here — PostgreSQL rejects SAVEPOINT in an aborted transaction,
        # accepting only COMMIT/ROLLBACK or ROLLBACK TO an *existing* savepoint.
        # Return without attempting a rollback: there is no savepoint to roll
        # back to. The DELETE that follows then fails loudly and set_attr()
        # returns False, which is the correct outcome — the one result that must
        # never be silent is success.
        #
        # Not expected to be reachable from set_attr(): this is the first
        # statement on a freshly checked-out connection, and psycopg_pool resets
        # a connection to IDLE before handing it out (the pool is also
        # configured with check=ConnectionPool.check_connection). Handled anyway
        # because the guarantee lives in another library, and because a future
        # caller might not run this first.
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

    # No row cap (JSONB holds up to 1 GB): attribute lists never span on
    # PostgreSQL unless the application sets a threshold.
    MAX_ROW_BYTES: int | None = None

    def __init__(self) -> None:
        """Initialize DbAttribute (no auto-table creation, use migrations)."""
        pass

    @staticmethod
    def get_bucket(
        actor_id: str | None = None, bucket: str | None = None, *, strict: bool = True
    ) -> dict[str, dict[str, Any]] | None:
        """
        Get all attributes from a bucket.

        Args:
            actor_id: The actor ID
            bucket: The bucket name

        Returns:
            Dict of {attribute_name: {data: ..., timestamp: ...}} -- ``{}``
            for an empty bucket. ``None`` only for missing arguments, or a
            read fault with ``strict=False``. Expired rows are returned.

        Raises:
            DbError: on a read fault (unless ``strict=False``)
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

                    ret: dict[str, dict[str, Any]] = {}
                    for row in rows:
                        ret[row[0]] = {
                            "data": row[1],
                            "timestamp": row[2],
                        }

                    return ret

        except Exception as e:
            if strict:
                raise DbError("attribute get_bucket") from e
            logger.error(f"Error retrieving bucket {actor_id}/{bucket}: {e}")
            return None

    @staticmethod
    def get_attr(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        *,
        strict: bool = True,
    ) -> dict[str, Any] | None:
        """
        Get a single attribute from a bucket.

        Args:
            actor_id: The actor ID
            bucket: The bucket name
            name: The attribute name
            strict: When False, a read fault answers None instead of raising

        Returns:
            Dict with {data: ..., timestamp: ...}, or None when absent. An
            expired row is returned (only ``get_attr_strict`` hides it).

        Raises:
            DbError: on a read fault (unless ``strict=False``)
        """
        if not actor_id or not bucket or not name:
            return None

        bucket_name = bucket + ":" + name

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # ``bucket_name`` alone is ambiguous -- bucket ``remote:abc``
                    # / name ``x`` and bucket ``remote`` / name ``abc:x`` share
                    # it -- so the exact bucket compare is what keeps a point
                    # read inside its own bucket, as it does for get_bucket().
                    cur.execute(
                        """
                        SELECT data, timestamp
                        FROM attributes
                        WHERE id = %s AND bucket_name = %s AND bucket = %s
                        """,
                        (actor_id, bucket_name, bucket),
                    )
                    row = cur.fetchone()

                    if not row:
                        return None

                    return {
                        "data": row[0],
                        "timestamp": row[1],
                    }

        except Exception as e:
            if strict:
                raise DbError("attribute get_attr") from e
            logger.error(f"Error retrieving attribute {actor_id}/{bucket}/{name}: {e}")
            return None

    @staticmethod
    def get_attr_strict(
        actor_id: str | None = None, bucket: str | None = None, name: str | None = None
    ) -> dict[str, Any] | None:
        """Read one attribute, distinguishing absence from failure.

        Absence (or expiry) returns ``None``; a fault raises ``DbError``.

        Expired rows read as absent. ``ttl_timestamp`` is only reclaimed by an
        explicit ``delete_expired()`` sweep on this backend, so honouring it at
        read time is what makes TTL mean the same thing on both backends.
        """
        if not actor_id or not bucket or not name:
            return None

        bucket_name = bucket + ":" + name

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT data, timestamp, ttl_timestamp
                        FROM attributes
                        WHERE id = %s AND bucket_name = %s AND bucket = %s
                        """,
                        (actor_id, bucket_name, bucket),
                    )
                    row = cur.fetchone()
        except Exception as e:
            raise DbError("attribute get_attr_strict") from e

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
            True on success (for a delete: the row is gone after the call, an
            absent row counts), False only for missing arguments

        Raises:
            DbError: on a backend fault
        """
        require_json(data, "attribute data")
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
                            WHERE id = %s AND bucket_name = %s AND bucket = %s
                            """,
                            (actor_id, bucket_name, bucket),
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
                raise DbError("attribute delete") from e

        # Calculate TTL timestamp if provided
        ttl_timestamp = None
        if ttl_seconds is not None:
            ttl_timestamp = ttl_deadline(ttl_seconds)

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
                            bucket = EXCLUDED.bucket,
                            name = EXCLUDED.name,
                            data = EXCLUDED.data,
                            timestamp = EXCLUDED.timestamp,
                            ttl_timestamp = EXCLUDED.ttl_timestamp
                        WHERE attributes.bucket = EXCLUDED.bucket
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
                    # No row written: another bucket owns the key ("a" +
                    # "b:c" and "a:b" + "c" share "a:b:c").
                    collided = cur.rowcount == 0
                conn.commit()
        except Exception as e:
            raise DbError("attribute set") from e
        if collided:
            raise AttributeKeyCollision(bucket, name, actor_id)
        return True

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
            True when the row is gone after the call (an absent row counts)

        Raises:
            DbError: on a backend fault
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
                        WHERE id = %s AND bucket_name = %s AND bucket = %s
                        """,
                        (actor_id, bucket_name, bucket),
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
        ttl_seconds: int | None = None,
        *,
        clear_ttl: bool = False,
        strict: bool = False,
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
            ttl_seconds: When given, the same UPDATE sets ``ttl_timestamp``
                (plus the clock-skew buffer, as ``set_attr`` does)
            clear_ttl: the same UPDATE sets ``ttl_timestamp`` to NULL (the
                row then never expires); ignored when ``ttl_seconds`` is given
            strict: raise ``DbError`` for a fault (4.0); a row that does not
                match still answers False

        Returns:
            True if update succeeded (current matched old_data), False
            otherwise; without ``strict`` also for a fault
        """
        require_json(new_data, "attribute data")
        if not actor_id or not bucket or not name:
            return False

        bucket_name = bucket + ":" + name

        # Defensive sanitization of data before JSON encoding
        from actingweb.db.utils import sanitize_json_data

        new_data = sanitize_json_data(new_data, log_source="attribute")
        old_data = sanitize_json_data(old_data, log_source="attribute")

        ttl_sql = ""
        ttl_params: tuple[Any, ...] = ()
        if ttl_seconds is not None:
            ttl_sql = ", ttl_timestamp = %s"
            ttl_params = (ttl_deadline(ttl_seconds),)
        elif clear_ttl:
            ttl_sql = ", ttl_timestamp = NULL"

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Update only if current data matches old_data
                    # Use JSONB comparison for reliability - PostgreSQL normalizes JSONB values
                    # so key ordering and whitespace differences don't affect equality
                    cur.execute(
                        f"""
                        UPDATE attributes
                        SET data = %s::jsonb, timestamp = %s{ttl_sql}
                        WHERE id = %s AND bucket_name = %s AND bucket = %s
                          AND data = %s::jsonb
                        """,
                        (
                            json.dumps(new_data),
                            timestamp,
                            *ttl_params,
                            actor_id,
                            bucket_name,
                            bucket,
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
            if strict:
                raise DbError("attribute conditional update", actor_id) from e
            return False

    @staticmethod
    def create_attr_if_absent(
        actor_id: str | None = None,
        bucket: str | None = None,
        name: str | None = None,
        data: Any = None,
        timestamp: datetime | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        """
        Create an attribute only if no live row holds its name.

        See ``DbAttributeProtocol.create_attr_if_absent`` for the contract.
        One ``INSERT ... ON CONFLICT DO UPDATE ... WHERE`` that replaces the
        existing row only when it is in the same bucket with a
        ``ttl_timestamp`` at or before now. A lost condition (no row
        written) is followed by one read: JSONB-equal stored data means the
        row is this call's own.
        """
        require_json(data, "attribute data")
        if not actor_id or not bucket or not name:
            raise ValueError("create_attr_if_absent needs actor_id, bucket and name")

        from actingweb.db.utils import sanitize_json_data

        bucket_name = bucket + ":" + name
        data = sanitize_json_data(data, log_source="attribute")
        encoded = json.dumps(data)
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # A lost write can be followed by the winner's row
                    # vanishing before the read-back (a delete, the TTL
                    # reaper): the name is then free, so it is tried once
                    # more rather than reported as lost.
                    for attempt in range(2):
                        cur.execute(
                            """
                            INSERT INTO attributes (
                                id, bucket_name, bucket, name, data, timestamp,
                                ttl_timestamp
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id, bucket_name)
                            DO UPDATE SET
                                bucket = EXCLUDED.bucket,
                                name = EXCLUDED.name,
                                data = EXCLUDED.data,
                                timestamp = EXCLUDED.timestamp,
                                ttl_timestamp = EXCLUDED.ttl_timestamp
                            WHERE attributes.bucket = EXCLUDED.bucket
                              AND attributes.ttl_timestamp IS NOT NULL
                              AND attributes.ttl_timestamp <= %s
                            """,
                            (
                                actor_id,
                                bucket_name,
                                bucket,
                                name,
                                encoded,
                                timestamp,
                                ttl_deadline(ttl_seconds)
                                if ttl_seconds is not None
                                else None,
                                int(time.time()),
                            ),
                        )
                        if cur.rowcount == 1:
                            written = True
                            break
                        cur.execute(
                            """
                            SELECT bucket = %s AND data = %s::jsonb
                            FROM attributes WHERE id = %s AND bucket_name = %s
                            """,
                            (bucket, encoded, actor_id, bucket_name),
                        )
                        row = cur.fetchone()
                        if row is None and attempt == 0:
                            continue  # the winner is gone: the name is free
                        written = bool(row and row[0])
                        break
                    else:  # pragma: no cover - the loop always breaks
                        written = False
                conn.commit()
            return written
        except Exception as e:
            raise DbError("attribute create", actor_id) from e

    # -- list primitives (thoughts/plans/2026-11-13-attribute-list-v2-port.md)
    #
    # The list core stores strings; each method reads and writes ``data`` as
    # given. Names compare by bytes (``COLLATE "C"``). A row another bucket
    # owns under the same composite key is never read, matched, overwritten
    # or deleted; a put or create that meets one raises
    # ``AttributeKeyCollision``. TTLs are ignored. The ``starts_with(name,
    # 'list:')`` clause is literal so the planner can use the partial index
    # ``ix_attributes_list_rows`` (every list row's name starts so).

    @staticmethod
    def _list_clause(*bounds: str) -> str:
        return (
            " AND starts_with(name, 'list:')"
            if all(b.startswith("list:") for b in bounds)
            else ""
        )

    @staticmethod
    def get_attr_range(
        actor_id: str,
        bucket: str,
        lower: str,
        upper: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, Any]:
        """Rows of ``bucket`` whose name is in ``[lower, upper]`` (bytes)."""
        del consistent_read  # every PostgreSQL read is current
        if not actor_id or not bucket or lower > upper:
            return {}
        column = "NULL" if keys_only else "data"
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT name, {column} FROM attributes
                        WHERE id = %s AND bucket = %s
                          {DbAttribute._list_clause(lower, upper)}
                          AND name COLLATE "C" >= %s AND name COLLATE "C" <= %s
                        ORDER BY name COLLATE "C"
                        """,
                        (actor_id, bucket, lower, upper),
                    )
                    rows = cur.fetchall()
        except Exception as e:
            raise DbError("attribute range read", actor_id) from e
        return {row[0]: "" if keys_only else row[1] for row in rows}

    @staticmethod
    def get_attr_prefix(
        actor_id: str,
        bucket: str,
        prefix: str,
        *,
        keys_only: bool = False,
        consistent_read: bool = True,
    ) -> dict[str, Any]:
        """Rows of ``bucket`` whose name begins with ``prefix``."""
        del consistent_read
        if not actor_id or not bucket:
            return {}
        column = "NULL" if keys_only else "data"
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT name, {column} FROM attributes
                        WHERE id = %s AND bucket = %s
                          {DbAttribute._list_clause(prefix)}
                          AND starts_with(name, %s)
                          AND name COLLATE "C" >= %s
                          AND name COLLATE "C" <= %s
                        ORDER BY name COLLATE "C"
                        """,
                        # The byte bounds give the index a range to scan;
                        # starts_with() keeps the answer exact.
                        (actor_id, bucket, prefix, prefix, prefix + "\U0010ffff"),
                    )
                    rows = cur.fetchall()
        except Exception as e:
            raise DbError("attribute prefix read", actor_id) from e
        return {row[0]: "" if keys_only else row[1] for row in rows}

    @staticmethod
    def get_last_attr_in_range(
        actor_id: str, bucket: str, lower: str, upper: str
    ) -> str | None:
        """The greatest name of ``bucket`` in ``[lower, upper]``, or None."""
        if not actor_id or not bucket or lower > upper:
            return None
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT name FROM attributes
                        WHERE id = %s AND bucket = %s
                          {DbAttribute._list_clause(lower, upper)}
                          AND name COLLATE "C" >= %s AND name COLLATE "C" <= %s
                        ORDER BY name COLLATE "C" DESC
                        LIMIT 1
                        """,
                        (actor_id, bucket, lower, upper),
                    )
                    row = cur.fetchone()
        except Exception as e:
            raise DbError("attribute last-in-range read", actor_id) from e
        return row[0] if row else None

    @staticmethod
    def create_attr_if_not_exists(
        actor_id: str, bucket: str, name: str, data: Any
    ) -> bool:
        """Create the row; True only when this call created it."""
        require_json(data, "attribute data")
        return name in DbAttribute.create_attrs_if_not_exist(
            actor_id, bucket, {name: data}
        )

    @staticmethod
    def create_attrs_if_not_exist(
        actor_id: str, bucket: str, rows: dict[str, Any]
    ) -> set[str]:
        """Create each row that does not exist, in one statement: the names
        this call created. A name whose key another bucket owns raises
        ``AttributeKeyCollision``, and the statement is rolled back: none of
        the batch is created (DynamoDB creates row by row and may have
        created some before it raises)."""
        require_json(rows, "attribute data")
        if not rows:
            return set()
        values = []
        params: list[Any] = []
        for name, data in rows.items():
            values.append("(%s, %s, %s, %s, %s)")
            params += [actor_id, bucket + ":" + name, bucket, name, json.dumps(data)]
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO attributes (id, bucket_name, bucket, name, data)
                        VALUES {", ".join(values)}
                        ON CONFLICT (id, bucket_name) DO NOTHING
                        RETURNING name
                        """,
                        params,
                    )
                    created = {row[0] for row in cur.fetchall()}
                    missed = [n for n in rows if n not in created]
                    foreign: list[str] = []
                    if missed:
                        cur.execute(
                            """
                            SELECT bucket_name FROM attributes
                            WHERE id = %s AND bucket_name = ANY(%s) AND bucket <> %s
                            """,
                            (actor_id, [bucket + ":" + n for n in missed], bucket),
                        )
                        foreign = [row[0][len(bucket) + 1 :] for row in cur.fetchall()]
                    if foreign:
                        # All or nothing: a batch that meets another bucket's
                        # row creates none of its rows.
                        conn.rollback()
                    else:
                        conn.commit()
        except Exception as e:
            raise DbError("attribute create", actor_id) from e
        if foreign:
            raise AttributeKeyCollision(bucket, foreign[0], actor_id)
        return created

    @staticmethod
    def set_attr_if_data_equals(
        actor_id: str, bucket: str, name: str, expected: str, data: Any
    ) -> bool:
        """Replace the row's data when it equals ``expected`` exactly."""
        require_json(data, "attribute data")
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE attributes SET data = %s::jsonb
                        WHERE id = %s AND bucket_name = %s AND bucket = %s
                          AND data = %s::jsonb
                        """,
                        (
                            json.dumps(data),
                            actor_id,
                            bucket + ":" + name,
                            bucket,
                            json.dumps(expected),
                        ),
                    )
                    updated = cur.rowcount == 1
                conn.commit()
        except Exception as e:
            raise DbError("attribute compare-and-swap", actor_id) from e
        return updated

    @staticmethod
    def delete_attr_if_data_equals(
        actor_id: str, bucket: str, name: str, expected: str
    ) -> bool:
        """Delete the row when its data equals ``expected`` exactly."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM attributes
                        WHERE id = %s AND bucket_name = %s AND bucket = %s
                          AND data = %s::jsonb
                        """,
                        (actor_id, bucket + ":" + name, bucket, json.dumps(expected)),
                    )
                    deleted = cur.rowcount == 1
                conn.commit()
        except Exception as e:
            raise DbError("attribute conditional delete", actor_id) from e
        return deleted

    @staticmethod
    def delete_attrs(actor_id: str, bucket: str, names: list[str]) -> None:
        """Delete each named row of ``bucket`` in one statement (absent ones
        are fine; a row another bucket owns stays)."""
        if not names:
            return
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM attributes
                        WHERE id = %s AND bucket = %s AND bucket_name = ANY(%s)
                        """,
                        (actor_id, bucket, [bucket + ":" + n for n in names]),
                    )
                conn.commit()
        except Exception as e:
            raise DbError("attribute batch delete", actor_id) from e

    @staticmethod
    def put_attr(actor_id: str, bucket: str, name: str, data: Any) -> None:
        """Write the row unconditionally within the bucket. A falsy ``data``
        is refused (``ValueError``), never turned into a delete."""
        require_json(data, "attribute data")
        if not data:
            raise ValueError("put_attr does not store falsy data")
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO attributes (id, bucket_name, bucket, name, data)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (id, bucket_name)
                        DO UPDATE SET data = EXCLUDED.data
                        WHERE attributes.bucket = EXCLUDED.bucket
                        """,
                        (actor_id, bucket + ":" + name, bucket, name, json.dumps(data)),
                    )
                    collided = cur.rowcount == 0
                conn.commit()
        except Exception as e:
            raise DbError("attribute put", actor_id) from e
        if collided:
            raise AttributeKeyCollision(bucket, name, actor_id)

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
                    # Locked in key order first, the order
                    # ``DbActor.rename_creator`` locks ``_internal`` rows in,
                    # so the two cannot deadlock on each other.
                    cur.execute(
                        """
                        SELECT 1 FROM attributes
                        WHERE id = %s AND bucket = %s
                        ORDER BY bucket_name
                        FOR UPDATE
                        """,
                        (actor_id, bucket),
                    )
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
            raise DbError("attribute delete_bucket") from e

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

        Raises:
            DbError: on a backend fault (never answered as 0).
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
            # Not 0: a fault must not read as "nothing expired" to the only
            # reaper of these rows. Every library caller folds it (a WARNING
            # in the token purges, a printed line in actingweb-deletions).
            raise DbError("expired attribute purge") from e

    @staticmethod
    def delete_by_chain(
        actor_id: str | None = None,
        buckets: list[str] | None = None,
        chain_id: str | None = None,
        defer_name: str | None = None,
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
            defer_name: Ignored: the single DELETE is atomic, so no row can be
                left half-way.

        Returns:
            Number of rows deleted.

        Raises:
            Exception: the delete failed. It is raised, never answered as 0,
                like DynamoDB's, so a failed revocation cannot pass for one
                that had nothing to delete.
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
            # Raised, not answered as 0: a zero is what "nothing matched"
            # returns too, and revocation must tell the two apart.
            logger.error(f"Error deleting token chain: {e}")
            raise


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
        actor_id: str | None = None, *, strict: bool = True
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
            if strict:
                raise DbError("attribute bucket list fetch") from e
            logger.error(f"Error fetching all attributes for actor {actor_id}: {e}")
            return None

    @staticmethod
    def fetch_timestamps(
        actor_id: str | None = None, *, strict: bool = True
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
            if strict:
                raise DbError("attribute bucket list fetch_timestamps") from e
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
                    # Key order first, as ``delete_bucket`` (see there).
                    cur.execute(
                        """
                        SELECT 1 FROM attributes
                        WHERE id = %s
                        ORDER BY bucket_name
                        FOR UPDATE
                        """,
                        (actor_id,),
                    )
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
            raise DbError("attribute bucket list delete") from e
