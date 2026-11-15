"""PostgreSQL implementation of actor database operations."""

import json
import logging
import time
from collections.abc import Iterator, Sequence
from typing import Any

import psycopg

from actingweb.db.creator_rename import (
    INTERNAL_BUCKET,
    MARKER_NAME,
    AttrWrite,
    RenameOutcome,
    validate_rename_writes,
)
from actingweb.db.creator_rules import (
    UNIQUE_INDEX_NAME,
    dup_value,
    is_exempt,
    missing_enforcement_message,
    normalise_creator,
)
from actingweb.db.exceptions import AttributeKeyCollision, CreatorTaken, DbError
from actingweb.db.postgresql.connection import get_connection, get_schema_name

logger = logging.getLogger(__name__)

# Rows per keyset page of DbActorList.iter_rows.
_ITER_PAGE = 1000

# Schemas whose ``ux_actors_creator`` was seen valid. Positive only: an
# absent index or a fault is probed again on the next enforced write.
_index_seen_valid: set[str] = set()


def creator_index_state() -> str:
    """``"valid"``, ``"invalid"`` or ``"missing"`` for ``ux_actors_creator``
    in the current schema. Raises on a fault."""
    schema = get_schema_name()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = %s AND n.nspname = %s",
                (UNIQUE_INDEX_NAME, schema),
            )
            row = cur.fetchone()
    if not row:
        return "missing"
    return "valid" if row[0] else "invalid"


def _creator_index_present() -> bool:
    """Whether ``ux_actors_creator`` is valid in the current schema; one
    query per process and schema once it has been seen. Raises on a fault."""
    schema = get_schema_name()
    if schema in _index_seen_valid:
        return True
    if creator_index_state() != "valid":
        return False
    _index_seen_valid.add(schema)
    return True


def reset_index_probe() -> None:
    """Forget what the index probe saw (tests that build or drop it)."""
    _index_seen_valid.clear()


def _require_creator_index(op: str) -> None:
    """Refuse an enforced write the index would not enforce.

    Without a valid index a claim is a plain write that lands a duplicate,
    so the write fails closed with ``DbError(op)`` and the remedy is logged.
    """
    try:
        present = _creator_index_present()
    except Exception as e:
        raise DbError(op) from e
    if present:
        return
    logger.error(
        missing_enforcement_message(
            f"the PostgreSQL index {UNIQUE_INDEX_NAME} is missing or INVALID"
        )
    )
    raise DbError(op)


def _is_creator_violation(e: psycopg.errors.UniqueViolation) -> bool:
    """Whether a unique violation is on ``ux_actors_creator``, not the key.

    Checked whatever ``unique_creator`` says: with the index in place and the
    flag rolled back, a second holder still fails, and it must say so rather
    than read as "id taken".
    """
    return getattr(e.diag, "constraint_name", None) == UNIQUE_INDEX_NAME


class DbActor:
    """DbActor does all the db operations for actor objects."""

    handle: dict[str, Any] | None

    def __init__(self, *, unique_creator: bool = False) -> None:
        """Initialize DbActor (no auto-table creation, use migrations).

        ``unique_creator`` is enforced by the partial unique index
        ``ux_actors_creator``, which ``actingweb-unique-creators enable``
        builds; the startup check refuses to run with the flag on without it.
        An enforced write (create, creator rename, holder replacement) checks
        the index once per process and raises ``DbError`` while it is missing,
        so a process that skipped the check cannot land a duplicate. A
        positive answer is kept for the process's life: a worker that saw the
        index keeps writing without it if an operator drops it (``disable``)
        while the worker runs, until it restarts. Reads never probe.
        """
        self.handle = None
        self.unique_creator = unique_creator

    def get(
        self, actor_id: str | None = None, *, strict: bool = True
    ) -> dict[str, Any] | None:
        """
        Retrieve actor by ID.

        Args:
            actor_id: The actor ID to retrieve
            strict: When False, a read fault answers None instead of raising

        Returns:
            dict with keys: id, creator, passphrase, or None if not found

        Raises:
            DbError: on a read fault (unless ``strict=False``)
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
            if strict:
                raise DbError("actor get") from e
            logger.error(f"Error retrieving actor {actor_id}: {e}")
            return None

    def get_by_creator(
        self,
        creator: str | None = None,
        *,
        strict: bool = True,
        consistent: bool = False,
        ids_only: bool = False,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """
        Get actors by creator field.

        Args:
            creator: The creator email to search for
            strict: When False, a read fault answers None instead of raising
            consistent: Accepted for parity with DynamoDB; a PostgreSQL
                read is always consistent
            ids_only: Answer ``[{"id": ...}]`` only

        Returns:
            A list of actor dicts, ``[]`` when none was found

        Raises:
            DbError: on a read fault (unless ``strict=False``)
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
                        return []
                    if ids_only:
                        return [{"id": row[0]} for row in rows]

                    ret = []
                    for row in rows:
                        logger.debug(f"get_by_creator matched actor id={row[0]}")
                        actor_dict = {
                            "id": row[0],
                            "creator": row[1],
                            "passphrase": row[2],
                        }
                        ret.append(actor_dict)

                    return ret
        except Exception as e:
            if strict:
                raise DbError("actor get_by_creator") from e
            logger.error(f"Error retrieving actors by creator {creator}: {e}")
            return None

    def create(
        self,
        actor_id: str | None = None,
        creator: str | None = None,
        passphrase: str | None = None,
        *,
        replace_holder: str | None = None,
    ) -> bool:
        """
        Create new actor.

        Args:
            actor_id: Unique actor ID
            creator: Creator email
            passphrase: Actor passphrase
            replace_holder: Move ``creator`` from this actor in the same
                transaction (:meth:`replace_creator_holder`)

        Returns:
            True when created, False when the id is taken

        Raises:
            CreatorTaken: the unique index refused the creator
            DbError: on a backend fault
        """
        if not actor_id:
            return False

        # Email in creator needs to be lower case
        creator = normalise_creator(creator)

        if not passphrase:
            passphrase = ""

        if replace_holder is not None:
            return self.replace_creator_holder(
                replace_holder,
                actor_id=actor_id,
                creator=creator,
                passphrase=passphrase,
            )

        # Check if actor already exists
        if self.get(actor_id=actor_id):
            logger.warning(f"Trying to create actor that exists({actor_id})")
            return False
        if self.unique_creator and not is_exempt(creator):
            _require_creator_index("actor create")

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
        except psycopg.errors.UniqueViolation as e:
            if _is_creator_violation(e):
                raise CreatorTaken(creator) from e
            logger.warning(f"Trying to create actor that exists({actor_id})")
            return False
        except Exception as e:
            raise DbError("actor create") from e

    def replace_creator_holder(
        self,
        old_id: str,
        *,
        actor_id: str,
        creator: str,
        passphrase: str,
    ) -> bool:
        """Rename ``old_id``'s creator to its ``#dup-`` value and insert
        ``actor_id`` with ``creator``, in one transaction.

        False when ``actor_id`` is taken; ``CreatorTaken`` when ``old_id`` no
        longer holds ``creator`` (nothing is written either way). ``old_id``
        keeps its row, which the caller removes.
        """
        if not self.unique_creator:
            raise ValueError("replace_creator_holder needs unique_creator")
        creator = normalise_creator(creator)
        if is_exempt(creator):
            raise ValueError("an exempt creator has no holder to replace")
        _require_creator_index("actor replace holder")
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE actors SET creator = %s WHERE id = %s AND creator = %s",
                        (dup_value(creator, old_id), old_id, creator),
                    )
                    if cur.rowcount != 1:
                        conn.rollback()
                        raise CreatorTaken(creator)
                    cur.execute(
                        """
                        INSERT INTO actors (id, creator, passphrase, created_at)
                        VALUES (%s, %s, %s, NOW())
                        """,
                        (actor_id, creator, passphrase or ""),
                    )
                conn.commit()
        except CreatorTaken:
            raise
        except psycopg.errors.UniqueViolation as e:
            if _is_creator_violation(e):
                raise CreatorTaken(creator) from e
            logger.warning(f"Trying to create actor that exists({actor_id})")
            return False
        except Exception as e:
            raise DbError("actor replace holder") from e
        self.handle = {"id": actor_id, "creator": creator, "passphrase": passphrase}
        return True

    def release_stale_creator(self, creator: str, actor_id: str) -> bool:
        """No separate record: the unique row is the holder. Always False."""
        if not self.unique_creator:
            raise ValueError("release_stale_creator needs unique_creator")
        return False

    def get_creator_holder(
        self, creator: str | None = None, *, strict: bool = True
    ) -> str | None:
        """The id of the actor holding a non-exempt ``creator`` (the unique
        index allows one); None when nobody holds it."""
        if not self.unique_creator:
            raise ValueError("get_creator_holder needs unique_creator")
        value = normalise_creator(creator)

        if is_exempt(value):
            return None
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM actors WHERE creator = %s ORDER BY id LIMIT 1",
                        (value,),
                    )
                    row = cur.fetchone()
        except Exception as e:
            if strict:
                raise DbError("creator holder get") from e
            logger.error(f"Error reading the holder of creator {value!r}: {e}")
            return None
        return str(row[0]) if row else None

    def modify(
        self, creator: str | None = None, passphrase: bytes | None = None
    ) -> bool:
        """
        Modify existing actor using self.handle.

        Args:
            creator: New creator email (optional)
            passphrase: New passphrase bytes (optional)

        Returns:
            True on success, False without a handle or when no row matched

        Raises:
            DbError: on a backend fault
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
            creator = normalise_creator(creator)
            updates.append("creator = %s")
            params.append(creator)

        if passphrase and len(passphrase) > 0:
            passphrase_str = passphrase.decode("utf-8")
            updates.append("passphrase = %s")
            params.append(passphrase_str)

        if not updates:
            return True  # Nothing to update
        if creator and self.unique_creator and not is_exempt(creator):
            _require_creator_index("actor modify")

        params.append(actor_id)
        where = "id = %s"
        if creator:
            # A creator change from a stale handle (another process renamed
            # the actor since it was loaded) matches no row and answers
            # False, as on DynamoDB.
            where += " AND creator IS NOT DISTINCT FROM %s"
            params.append(self.handle.get("creator"))

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE actors
                        SET {", ".join(updates)}
                        WHERE {where}
                        """,
                        tuple(params),
                    )
                    if cur.rowcount != 1:
                        logger.error(
                            f"Modify of actor {actor_id} matched {cur.rowcount} rows"
                        )
                        conn.rollback()
                        return False
                conn.commit()
        except psycopg.errors.UniqueViolation as e:
            if _is_creator_violation(e):
                raise CreatorTaken(creator) from e
            raise DbError("actor modify") from e
        except Exception as e:
            raise DbError("actor modify") from e
        # Only after the commit: a failed modify leaves the handle as stored.
        if creator:
            self.handle["creator"] = creator
        if passphrase:
            self.handle["passphrase"] = passphrase.decode("utf-8")
        return True

    def rename_creator(
        self,
        actor_id: str,
        *,
        expected: str | None,
        creator: str,
        internal: Sequence[AttrWrite] = (),
        marker: str | None = None,
    ) -> RenameOutcome:
        """See ``DbActorProtocol.rename_creator``: one transaction on one
        connection, rolled back explicitly on anything but ``APPLIED``.

        Every named ``_internal`` row (the marker's included) is locked first,
        in key order, so a multi-row delete of the bucket cannot close a lock
        cycle with it. Two renames crossing on each other's creator can still
        deadlock on ``ux_actors_creator``; that is retried once."""
        if not actor_id:
            raise ValueError("rename_creator needs an actor id")
        validate_rename_writes(internal, marker)
        new_creator = normalise_creator(creator)
        if (
            self.unique_creator
            and not is_exempt(new_creator)
            and new_creator != expected
        ):
            _require_creator_index("actor rename")
        for attempt in range(2):
            try:
                outcome = self._rename_once(
                    actor_id, expected, new_creator, internal, marker
                )
            except psycopg.errors.DeadlockDetected as e:
                if attempt == 0:
                    continue
                raise DbError("actor rename") from e
            except psycopg.errors.UniqueViolation as e:
                if _is_creator_violation(e):
                    raise CreatorTaken(new_creator) from e
                raise DbError("actor rename") from e
            except (AttributeKeyCollision, CreatorTaken):
                raise
            except Exception as e:
                raise DbError("actor rename") from e
            if outcome is RenameOutcome.APPLIED:
                if self.handle is not None and self.handle.get("id") == actor_id:
                    self.handle["creator"] = new_creator
            elif outcome is RenameOutcome.ROW_CHANGED:
                logger.warning(
                    f"Rename of actor {actor_id}: the stored creator no longer "
                    "matches; nothing changed"
                )
            return outcome
        raise DbError("actor rename")

    @staticmethod
    def _rename_once(
        actor_id: str,
        expected: str | None,
        new_creator: str,
        internal: Sequence[AttrWrite],
        marker: str | None,
    ) -> RenameOutcome:
        from actingweb.db.utils import sanitize_json_data

        names = {w.name for w in internal}
        if marker is not None:
            names.add(MARKER_NAME)
        keys = sorted(INTERNAL_BUCKET + ":" + n for n in names)
        now = int(time.time())
        with get_connection() as conn:
            try:
                with conn.cursor() as cur:
                    # Rows of the named keys, locked in key order. A key
                    # held by another bucket is a collision, raised only
                    # after the row and the marker have been decided, the
                    # order DynamoDB decides them in.
                    stored: dict[str, tuple[str, Any]] = {}
                    if keys:
                        cur.execute(
                            """
                            SELECT bucket_name, bucket, data
                            FROM attributes
                            WHERE id = %s AND bucket_name = ANY(%s)
                            ORDER BY bucket_name
                            FOR UPDATE
                            """,
                            (actor_id, keys),
                        )
                        for bucket_name, bucket, data in cur.fetchall():
                            stored[bucket_name] = (bucket, data)
                    collided = [
                        bucket_name[len(INTERNAL_BUCKET) + 1 :]
                        for bucket_name, (bucket, _d) in sorted(stored.items())
                        if bucket != INTERNAL_BUCKET
                    ]

                    cur.execute(
                        """
                        UPDATE actors SET creator = %s
                        WHERE id = %s AND creator IS NOT DISTINCT FROM %s
                        """,
                        (new_creator, actor_id, expected),
                    )
                    if cur.rowcount != 1:
                        conn.rollback()
                        return RenameOutcome.ROW_CHANGED
                    if marker is not None:
                        # As on DynamoDB, the marker's TTL is not consulted
                        # (``_internal`` rows carry none).
                        row = stored.get(INTERNAL_BUCKET + ":" + MARKER_NAME)
                        if row is None or row[0] != INTERNAL_BUCKET or row[1] != marker:
                            conn.rollback()
                            return RenameOutcome.MARKER_CHANGED
                    if collided:
                        raise AttributeKeyCollision(
                            INTERNAL_BUCKET, collided[0], actor_id
                        )
                    for w in internal:
                        key = INTERNAL_BUCKET + ":" + w.name
                        if w.value is None:
                            cur.execute(
                                """
                                DELETE FROM attributes
                                WHERE id = %s AND bucket_name = %s AND bucket = %s
                                """,
                                (actor_id, key, INTERNAL_BUCKET),
                            )
                            continue
                        encoded = json.dumps(
                            sanitize_json_data(w.value, log_source="attribute")
                        )
                        # Each condition is in the statement itself: the
                        # locking read cannot lock a key that has no row
                        # yet, and a row inserted since must still decide.
                        if w.when == "equals":
                            cur.execute(
                                """
                                UPDATE attributes
                                SET data = %s::jsonb, timestamp = NULL,
                                    ttl_timestamp = NULL
                                WHERE id = %s AND bucket_name = %s AND bucket = %s
                                  AND data = %s::jsonb
                                """,
                                (
                                    encoded,
                                    actor_id,
                                    key,
                                    INTERNAL_BUCKET,
                                    json.dumps(w.expected),
                                ),
                            )
                        else:
                            only_expired = (
                                " AND attributes.ttl_timestamp IS NOT NULL"
                                " AND attributes.ttl_timestamp <= %s"
                                if w.when == "absent"
                                else ""
                            )
                            params: tuple[Any, ...] = (
                                actor_id,
                                key,
                                INTERNAL_BUCKET,
                                w.name,
                                encoded,
                            )
                            if w.when == "absent":
                                params += (now,)
                            cur.execute(
                                f"""
                                INSERT INTO attributes (
                                    id, bucket_name, bucket, name, data,
                                    timestamp, ttl_timestamp
                                ) VALUES (%s, %s, %s, %s, %s, NULL, NULL)
                                ON CONFLICT (id, bucket_name)
                                DO UPDATE SET
                                    data = EXCLUDED.data,
                                    timestamp = EXCLUDED.timestamp,
                                    ttl_timestamp = EXCLUDED.ttl_timestamp
                                WHERE attributes.bucket = EXCLUDED.bucket{only_expired}
                                """,
                                params,
                            )
                        if cur.rowcount == 0:
                            cur.execute(
                                "SELECT bucket FROM attributes "
                                "WHERE id = %s AND bucket_name = %s",
                                (actor_id, key),
                            )
                            other = cur.fetchone()
                            if other and other[0] != INTERNAL_BUCKET:
                                raise AttributeKeyCollision(
                                    INTERNAL_BUCKET, w.name, actor_id
                                )
                            conn.rollback()
                            return RenameOutcome.ATTR_CONDITION
                conn.commit()
                return RenameOutcome.APPLIED
            except BaseException:
                conn.rollback()
                raise

    def delete(self) -> bool:
        """
        Delete actor using self.handle.

        Returns:
            True when the row is gone after the call (an already-absent row
            counts), False without a handle

        Raises:
            DbError: on a backend fault
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
            raise DbError("actor delete") from e


class DbActorList:
    """DbActorList does all the db operations for list of actor objects."""

    handle: Any | None

    def __init__(self) -> None:
        """Initialize DbActorList."""
        self.handle = None

    def fetch(self, *, strict: bool = True) -> list[dict[str, Any]] | bool:
        """
        Fetch all actors.

        Returns:
            List of actor dicts (``[]`` when there are none); False on a read
            fault with ``strict=False``

        Raises:
            DbError: on a read fault (unless ``strict=False``)
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

                    return [{"id": row[0], "creator": row[1]} for row in rows]
        except Exception as e:
            if strict:
                raise DbError("actor list fetch") from e
            logger.error(f"Error fetching actor list: {e}")
            return False

    def iter_rows(
        self, *, consistent: bool = False, rate_limit: float | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield every actor as ``{"id", "creator"}`` in id order, in keyset
        pages of ``_ITER_PAGE``.

        Each page takes its own pooled connection and releases it before
        yielding, so a sweep abandoned part-way holds none. Reads are
        read-committed per page, not a fleet snapshot. ``consistent`` and
        ``rate_limit`` are accepted for parity with DynamoDB and ignored.
        """
        last = ""
        while True:
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, creator FROM actors WHERE id > %s "
                            "ORDER BY id LIMIT %s",
                            (last, _ITER_PAGE),
                        )
                        page = cur.fetchall()
            except Exception as e:
                raise DbError("actor list scan") from e
            for row in page:
                yield {"id": row[0], "creator": row[1]}
            if len(page) < _ITER_PAGE:
                return
            last = page[-1][0]
