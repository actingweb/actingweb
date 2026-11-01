"""Make the reverse-lookup table ready: ``actingweb-property-lookup``.

Reverse lookup (``get_by_property``, OAuth sign-in by email) resolves an
indexed property value to its actor through the lookup table. A deployment
that held data before the table existed, or before a name was indexed, has
properties with no lookup row. This command backfills those rows and records
that it did, per indexed name, so the application's startup check
(``ActingWebApp.check_ready()``) can tell a ready store from one that would
silently miss lookups.

Subcommands (dry-run unless ``--apply``):

``report``
    Per indexed name: property rows, lookup rows, whether the name is marked
    backfill-complete and whether it was in the last recorded name set. Exit
    1 when the startup check would refuse.
``backfill``
    Write the missing lookup rows from the properties table (the source of
    truth), then mark each name that completed with no fault and no
    collision, and record the name set.
``mark-complete``
    Write the markers without a backfill, for a deployment that already ran
    the 3.13 backfill. Refuses a name that has property rows and no lookup
    rows unless ``--force``.
``unmark``
    Remove a name's marker (the rollback, and the step before dropping a
    name from the indexed set).

The marker is an operator assertion that the backfill ran for that name.
Data copied into a store by a tool, not written through the library, needs
``backfill --apply`` after the copy.

Run it with the same environment as the application (``DATABASE_BACKEND``,
``AWS_DB_PREFIX``, ``INDEXED_PROPERTIES``, credentials). Exit status is 0 on
success and 1 when the work is incomplete or a name is not ready.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from actingweb.db.exceptions import DbError

logger = logging.getLogger(__name__)

PROG = "actingweb-property-lookup"
GUIDE = 'docs/migration/v3.16.rst, "One reverse-lookup mechanism"'


class StoreUnavailable(RuntimeError):
    """The store cannot be read as the application's store (wrong prefix,
    missing table, no connection); never reported as an empty store."""


# ---------------------------------------------------------------------------
# Backend selection and the probe shared with ActingWebApp.check_ready()
# ---------------------------------------------------------------------------


def lookup_backend(database: str) -> ModuleType:
    """The backend module holding the four readiness functions."""
    import importlib

    return importlib.import_module(f"actingweb.db.{database}.property_lookup")


SYSTEM_ACTOR_PREFIX = "_actingweb_"


def properties_table_empty(database: str) -> bool:
    """Whether the properties table holds no row of an actor's own.

    The library's system actors (``_actingweb_system``, ``_actingweb_oauth2``)
    store their rows in the properties table before the first request, so a
    store with no users still has some. Rows whose id starts with
    ``_actingweb_`` do not count. One limited read; raises ``DbError`` on a
    fault or a missing table.
    """
    try:
        if database == "postgresql":
            from actingweb.db.postgresql.connection import get_connection

            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM properties WHERE NOT starts_with(id, %s) LIMIT 1",
                    (SYSTEM_ACTOR_PREFIX,),
                )
                return cur.fetchone() is None
        from actingweb.db.dynamodb.property import Property

        # ``page_size`` bounds each read, not the total: the scan keeps going
        # until it meets an actor's row or the table ends. (``limit`` would
        # cap the total, and a system partition with 25 rows would then read
        # a populated store as empty.)
        for item in Property.scan(page_size=25, attributes_to_get=["id"]):
            if not str(item.id).startswith(SYSTEM_ACTOR_PREFIX):
                return False
        return True
    except Exception as e:  # folds DbError: reported
        raise DbError("properties empty check") from e


@dataclass
class Readiness:
    """What the markers say about the configured indexed names."""

    names: list[str]
    marked: set[str]
    recorded: set[str] | None
    attention: list[str] = field(default_factory=list)

    @property
    def set_changed(self) -> bool:
        return self.recorded is None or set(self.names) != self.recorded


def read_readiness(database: str, names: list[str]) -> Readiness:
    """Read the markers and the recorded set; raises ``DbError``.

    ``attention`` lists the configured names that are unmarked, or marked but
    absent from the last recorded set (a name dropped for a deploy and
    restored has unindexed values). No recorded set is not a refusal.
    """
    marked, recorded = lookup_backend(database).read_readiness(names)
    attention = [
        n
        for n in names
        if n not in marked or (recorded is not None and n not in recorded)
    ]
    return Readiness(names, marked, recorded, attention)


def settle(config: Any) -> Readiness:
    """The startup probe: read, and write what a ready or empty store needs.

    A passing probe records the configured set when it changed. A store with
    no property rows at all is ready by definition: the missing markers and
    the set are written. Returns the readiness *after* those writes; a
    non-empty ``attention`` means the store is not ready. Raises ``DbError``
    when the store cannot be read or written.
    """
    names = list(dict.fromkeys(config.indexed_properties))
    backend = lookup_backend(config.database)
    state = read_readiness(config.database, names)
    if not state.attention:
        if state.set_changed:
            backend.record_configured(names)
        return state
    if properties_table_empty(config.database):
        backend.mark_backfilled(names)
        backend.record_configured(names)
        return Readiness(names, set(names), set(names), [])
    return state


# ---------------------------------------------------------------------------
# Config and table checks
# ---------------------------------------------------------------------------


def make_config() -> Any:
    """The command's config: the application's backend and indexed names."""
    from actingweb.config import Config

    return Config(
        database=os.getenv("DATABASE_BACKEND", "dynamodb"),
        unique_creator=False,
        force_email_prop_as_creator=False,
    )


def _require_tables(database: str) -> None:
    """A wrong prefix must not read as an empty store."""
    if database == "postgresql":
        from actingweb.db.postgresql.connection import get_connection

        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT to_regclass('actors'), to_regclass('properties')")
                row = cur.fetchone()
        except Exception as e:  # folds DbError: reported
            raise StoreUnavailable(f"cannot read the database: {e}") from e
        if not row or row[0] is None or row[1] is None:
            raise StoreUnavailable(
                "the actors or properties table does not exist "
                "(check PG_DB_PREFIX and run 'alembic upgrade head')"
            )
        return
    from actingweb.db.dynamodb.actor import Actor
    from actingweb.db.dynamodb.property import Property

    for model in (Actor, Property):
        try:
            present = model.exists()
        except Exception as e:  # folds DbError: reported
            raise StoreUnavailable(f"cannot read the database: {e}") from e
        if not present:
            raise StoreUnavailable(
                f"the table {model.Meta.table_name} does not exist "
                "(check AWS_DB_PREFIX)"
            )


def _ensure_lookup_table(database: str) -> None:
    """Create the DynamoDB lookup table when missing (writers only)."""
    if database == "dynamodb":
        from actingweb.db.dynamodb.property_lookup import DbPropertyLookup

        DbPropertyLookup()


# ---------------------------------------------------------------------------
# Counting (report, mark-complete guard)
# ---------------------------------------------------------------------------


@dataclass
class NameCounts:
    properties: int = 0
    lookups: int = 0


def count_rows(
    database: str, names: list[str], *, read_rcu: float | None = None
) -> dict[str, NameCounts]:
    """Property rows and lookup rows per name (``#meta`` rows excluded)."""
    counts = {n: NameCounts() for n in names}
    if not names:
        return counts
    if database == "postgresql":
        from actingweb.db.postgresql.connection import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT name, count(*) FROM properties WHERE name = ANY(%s) "
                "GROUP BY name",
                (names,),
            )
            for name, n in cur.fetchall():
                counts[name].properties = n
            cur.execute(
                "SELECT property_name, count(*) FROM property_lookup "
                "WHERE property_name = ANY(%s) GROUP BY property_name",
                (names,),
            )
            for name, n in cur.fetchall():
                counts[name].lookups = n
        return counts
    from actingweb.db.dynamodb.property import Property
    from actingweb.db.dynamodb.property_lookup import (
        LOOKUP_META_ACTOR,
        PropertyLookupV2,
    )

    wanted = set(names)
    for prop in Property.scan(attributes_to_get=["id", "name"], rate_limit=read_rcu):
        if str(prop.name) in wanted:
            counts[str(prop.name)].properties += 1
    try:
        for row in PropertyLookupV2.scan(
            PropertyLookupV2.actor_id != LOOKUP_META_ACTOR,
            attributes_to_get=["lookup_key", "property_name"],
            rate_limit=read_rcu,
        ):
            if str(row.property_name) in wanted:
                counts[str(row.property_name)].lookups += 1
    except Exception as e:  # folds DbError: reported
        from actingweb.db.dynamodb.property_lookup import is_resource_not_found

        if not is_resource_not_found(e):
            raise
    return counts


# ---------------------------------------------------------------------------
# Backfill, DynamoDB
# ---------------------------------------------------------------------------


class RateLimiter:
    """Thread-safe items/second limiter shared across segments."""

    def __init__(self, rps: float | None) -> None:
        self._interval = 1.0 / rps if rps and rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if not self._interval:
            return
        with self._lock:
            now = time.monotonic()
            wake_at = max(self._next_at, now)
            self._next_at = wake_at + self._interval
        delay = wake_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)


class Checkpoint:
    """Per-segment ``last_evaluated_key`` persistence for resume."""

    def __init__(
        self, path: str | None, total_segments: int, signature: str = ""
    ) -> None:
        self._path = path
        self._signature = signature
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any] | str] = {}
        # Collisions found before the checkpoint: a resumed run skips those
        # rows, so it must still leave their names unmarked.
        self.collisions: dict[str, list[str]] = {}
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    saved = json.load(f)
                if (
                    saved.get("total_segments") == total_segments
                    and saved.get("signature", "") == signature
                ):
                    self._state = saved.get("segments", {})
                    self.collisions = {
                        str(k): [str(d) for d in v]
                        for k, v in (saved.get("collisions") or {}).items()
                        if isinstance(v, list)
                    }
                    logger.info(f"Resuming from checkpoint {path}")
                else:
                    logger.warning(
                        "Checkpoint is for another run (segments, names or "
                        "table prefix differ); starting over"
                    )
            except Exception as e:  # folds DbError: reported
                logger.warning(f"Could not read checkpoint {path}: {e}")
        self._total_segments = total_segments

    def get(self, segment: int) -> dict[str, Any] | str | None:
        return self._state.get(str(segment))

    def note_collision(self, name: str, detail: str) -> None:
        """Remember a collision. It reaches disk with the next ``set()`` (so
        a checkpointed page never loses its collisions) or ``flush()``; a
        page that was not checkpointed is rescanned anyway."""
        with self._lock:
            details = self.collisions.setdefault(name, [])
            if detail not in details:
                details.append(detail)

    def flush(self) -> None:
        with self._lock:
            self._write()

    def set(self, segment: int, last_evaluated_key: dict[str, Any] | None) -> None:
        with self._lock:
            self._state[str(segment)] = (
                last_evaluated_key if last_evaluated_key is not None else "done"
            )
            self._write()

    def _write(self) -> None:
        """Persist the state; the caller holds the lock."""
        if not self._path:
            return
        tmp = f"{self._path}.tmp"
        with open(tmp, "w") as f:
            json.dump(
                {
                    "total_segments": self._total_segments,
                    "signature": self._signature,
                    "segments": self._state,
                    "collisions": self.collisions,
                },
                f,
            )
        os.replace(tmp, self._path)


@dataclass
class BackfillStats:
    """Outcome of one backfill pass."""

    scanned: int = 0
    matched: int = 0
    written: int = 0
    orphans: int = 0
    # name -> number of rows another actor already holds
    collisions: dict[str, int] = field(default_factory=dict)
    collision_details: list[str] = field(default_factory=list)
    faults: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, attr: str, amount: int = 1) -> None:
        with self._lock:
            setattr(self, attr, getattr(self, attr) + amount)

    def collision(self, name: str, detail: str) -> None:
        """Count one colliding row; a row seen again (a resumed run rescans
        the page that faulted) is counted once."""
        with self._lock:
            if detail in self.collision_details:
                return
            self.collisions[name] = self.collisions.get(name, 0) + 1
            self.collision_details.append(detail)

    def fault(self) -> None:
        self.bump("faults")

    def completed_names(self, names: list[str]) -> list[str]:
        """The names whose pass finished with no fault and no collision."""
        if self.faults:
            return []
        return [n for n in names if n not in self.collisions]


def _lookup_owner(key: str) -> str | None:
    """The actor holding a v2 lookup row, or None; raises ``DbError``."""
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.property_lookup import PropertyLookupV2

    try:
        row = PropertyLookupV2.get(key, consistent_read=True)
    except DoesNotExist:
        return None
    except Exception as e:
        from actingweb.db.dynamodb.property_lookup import is_resource_not_found

        # A dry run does not create tables: no lookup table yet holds nothing.
        if is_resource_not_found(e):
            return None
        raise DbError("property lookup read", None) from e
    return str(row.actor_id) if row.actor_id else None


def _put_lookup_row(lookup: Any, name: str, value: str, actor_id: str) -> bool | None:
    """True written/present, False collision, None on a write fault."""
    from actingweb.db.dynamodb.property_lookup import (
        PropertyLookupV2,
        compute_lookup_key,
    )

    key = compute_lookup_key(name, value)
    row = PropertyLookupV2(lookup_key=key, actor_id=actor_id, property_name=name)
    try:
        row.save(condition=PropertyLookupV2.lookup_key.does_not_exist())
        return True
    except Exception as e:  # folds DbError: reported
        code = getattr(e, "cause_response_code", None)
        if code != "ConditionalCheckFailedException":
            logger.error(f"LOOKUP_CREATE_FAILED: property={name} actor={actor_id}: {e}")
            return None
    # Conditional failure: identical mapping is fine, another actor is not.
    try:
        existing = PropertyLookupV2.get(key, consistent_read=True)
    except Exception as e:  # folds DbError: reported
        logger.error(f"LOOKUP_READ_FAILED: property={name} actor={actor_id}: {e}")
        return None
    return str(existing.actor_id) == actor_id


def _actor_exists(actor_id: str, stats: BackfillStats | None = None) -> bool:
    """Whether the actor row exists; a read fault counts as existing so the
    row is processed (and a write fault reported) rather than skipped. A dry
    run, which writes nothing, passes ``stats`` so the fault is counted."""
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.actor import Actor

    try:
        Actor.get(actor_id)
    except DoesNotExist:
        return False
    except Exception:  # folds DbError: reported
        if stats is not None:
            stats.fault()
        return True
    return True


def _run_segment(
    segment: int,
    total_segments: int,
    indexed: set[str],
    limiter: RateLimiter,
    checkpoint: Checkpoint,
    stats: BackfillStats,
    apply: bool,
    read_rcu: float | None,
    page_size: int = 100,
    dry_run_owners: dict[str, str] | None = None,
) -> None:
    from actingweb.db.dynamodb.property import Property
    from actingweb.db.dynamodb.property_lookup import compute_lookup_key

    if dry_run_owners is None:
        dry_run_owners = {}
    start_key = checkpoint.get(segment)
    if start_key == "done":
        logger.info(f"segment {segment}: already complete (checkpoint)")
        return
    if not isinstance(start_key, dict):
        start_key = None

    results = Property.scan(
        segment=segment,
        total_segments=total_segments,
        last_evaluated_key=start_key,
        rate_limit=read_rcu,
    )
    since_checkpoint = 0
    page_fault = False
    for item in results:
        stats.bump("scanned")
        name = str(item.name) if item.name else ""
        if name in indexed and item.value:
            stats.bump("matched")
            value = str(item.value)  # verbatim, exactly as stored
            actor_id = str(item.id)
            limiter.wait()
            if not _actor_exists(actor_id, None if apply else stats):
                # An orphaned property row (its actor is gone) would take the
                # lookup row of a user who signs up again with the same value.
                stats.bump("orphans")
                continue
            if not apply:
                # Predict what --apply would do: a row another actor holds,
                # in the table or earlier in this dry run, is a collision.
                key = compute_lookup_key(name, value)
                owner = dry_run_owners.get(key)
                if owner is None:
                    try:
                        held = _lookup_owner(key)
                    except DbError:  # folds DbError: counted as a fault
                        stats.fault()  # reported; the dry run goes on
                        continue
                    owner = dry_run_owners.setdefault(key, held or actor_id)
                if owner == actor_id:
                    stats.bump("written")
                else:
                    stats.collision(
                        name,
                        f"property={name} actor={actor_id} digest={key[:12]}",
                    )
            else:
                outcome = _put_lookup_row(None, name, value, actor_id)
                if outcome is True:
                    stats.bump("written")
                elif outcome is False:
                    detail = (
                        f"property={name} actor={actor_id} "
                        f"digest={compute_lookup_key(name, value)[:12]}"
                    )
                    checkpoint.note_collision(name, detail)
                    stats.collision(name, detail)
                else:
                    # A write fault is not a collision: do not checkpoint
                    # past this page, so a re-run retries the row.
                    stats.fault()
                    page_fault = True
        since_checkpoint += 1
        if since_checkpoint >= page_size:
            since_checkpoint = 0
            if not page_fault:
                checkpoint.set(segment, results.last_evaluated_key)
    if page_fault:
        logger.error(f"segment {segment}: incomplete (write fault); re-run to retry")
        return
    checkpoint.set(segment, None)  # done
    logger.info(f"segment {segment}: complete")


def backfill_dynamodb(
    names: list[str],
    *,
    apply: bool,
    rps: float = 25.0,
    read_rcu: float | None = None,
    segments: int = 4,
    checkpoint_file: str | None = None,
) -> BackfillStats:
    """Scan the properties table and write the missing v2 lookup rows."""
    stats = BackfillStats()
    limiter = RateLimiter(rps)
    from actingweb.db.dynamodb.property import Property

    signature = f"{Property.Meta.table_name}|{','.join(sorted(names))}"
    checkpoint = Checkpoint(checkpoint_file if apply else None, segments, signature)
    # Collisions behind the checkpoint are not seen again; carry them.
    for name, details in checkpoint.collisions.items():
        for detail in details:
            stats.collision(name, detail)
    indexed = set(names)
    # Shared by the segments; dict.setdefault is atomic under the GIL.
    dry_run_owners: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=segments) as pool:
        futures = [
            pool.submit(
                _run_segment,
                seg,
                segments,
                indexed,
                limiter,
                checkpoint,
                stats,
                apply,
                read_rcu,
                dry_run_owners=dry_run_owners,
            )
            for seg in range(segments)
        ]
    for future in futures:
        try:
            future.result()
        except Exception as e:  # folds DbError: reported
            logger.error(f"Segment failed: {e}")
            stats.fault()
    if apply and stats.faults and checkpoint_file:
        checkpoint.flush()  # the collisions of pages that were checkpointed
    # Only a fault leaves a checkpoint to resume from. After a collision the
    # operator resolves it and must re-scan: a kept "done" segment would skip
    # the rows that collided.
    if apply and not stats.faults and checkpoint_file:
        if os.path.exists(checkpoint_file):
            os.unlink(checkpoint_file)
    return stats


# ---------------------------------------------------------------------------
# Backfill, PostgreSQL
# ---------------------------------------------------------------------------


def backfill_postgresql(
    names: list[str], *, apply: bool, batch_size: int = 1000, pause: float = 0.0
) -> BackfillStats:
    """Insert the missing ``property_lookup`` rows in keyset batches.

    Each batch is bounded by the leading primary-key column and commits
    alone, so ``DbProperty.set()``'s own inserts and actor deletes wait at
    most one batch. Rows whose actor no longer exists are skipped (they would
    fail the foreign key) and counted.
    """
    from actingweb.db.postgresql.connection import get_connection

    stats = BackfillStats()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM properties p LEFT JOIN actors a "
                    "ON a.id = p.id WHERE p.name = ANY(%s) AND a.id IS NULL",
                    (names,),
                )
                row = cur.fetchone()
                stats.orphans = int(row[0]) if row else 0
                if not apply:
                    cur.execute(
                        "SELECT count(*) FROM properties p "
                        "JOIN actors a ON a.id = p.id "
                        "LEFT JOIN property_lookup l ON l.property_name = p.name "
                        "AND l.value = p.value "
                        "WHERE p.name = ANY(%s) AND l.property_name IS NULL",
                        (names,),
                    )
                    row = cur.fetchone()
                    stats.written = int(row[0]) if row else 0
                    # Two actors sharing a value with no lookup row yet:
                    # --apply gives the row to one, the rest collide.
                    cur.execute(
                        "SELECT p.name, array_agg(p.id ORDER BY p.id) "
                        "FROM properties p JOIN actors a ON a.id = p.id "
                        "LEFT JOIN property_lookup l ON l.property_name = p.name "
                        "AND l.value = p.value "
                        "WHERE p.name = ANY(%s) AND l.property_name IS NULL "
                        "GROUP BY p.name, p.value HAVING count(*) > 1",
                        (names,),
                    )
                    for name, ids in cur.fetchall():
                        for actor_id in ids[1:]:
                            stats.written -= 1
                            stats.collision(
                                name,
                                f"property={name} actor={actor_id} "
                                f"shares_with={','.join(i for i in ids if i != actor_id)}",
                            )
            conn.rollback()
            if apply:
                for after, upto in _pg_batches_conn(conn, names, batch_size):
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO property_lookup "
                            "(property_name, value, actor_id) "
                            "SELECT p.name, p.value, p.id FROM properties p "
                            "JOIN actors a ON a.id = p.id "
                            "WHERE p.name = ANY(%s) AND p.id > %s AND p.id <= %s "
                            "ON CONFLICT DO NOTHING",
                            (names, after, upto),
                        )
                        stats.written += max(cur.rowcount, 0)
                    conn.commit()
                    if pause:
                        time.sleep(pause)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT p.name, p.id, l.actor_id FROM properties p "
                    "JOIN actors a ON a.id = p.id "
                    "JOIN property_lookup l ON l.property_name = p.name "
                    "AND l.value = p.value "
                    "WHERE p.name = ANY(%s) AND l.actor_id <> p.id",
                    (names,),
                )
                for name, actor_id, holder in cur.fetchall():
                    stats.collision(
                        name, f"property={name} actor={actor_id} held_by={holder}"
                    )
            conn.rollback()
    except Exception as e:  # folds DbError: reported
        logger.error(f"PostgreSQL backfill fault: {e}")
        stats.fault()
    return stats


def _pg_batches_conn(
    conn: Any, names: list[str], batch_size: int
) -> Iterator[tuple[str, str]]:
    after = ""
    while True:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(id) FROM (SELECT id FROM properties "
                "WHERE name = ANY(%s) AND id > %s ORDER BY id LIMIT %s) t",
                (names, after, batch_size),
            )
            row = cur.fetchone()
        conn.rollback()
        upto = row[0] if row else None
        if upto is None:
            return
        yield after, upto
        after = upto


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def _names(args: argparse.Namespace, config: Any) -> list[str]:
    if args.properties:
        return list(
            dict.fromkeys(p.strip() for p in args.properties.split(",") if p.strip())
        )
    return list(dict.fromkeys(config.indexed_properties))


def _readiness_or_empty(database: str, names: list[str]) -> Readiness:
    try:
        return read_readiness(database, names)
    except DbError as e:  # folds DbError: reported
        cause = e.__cause__ or e
        print(f"{PROG}: cannot read the markers: {e} ({cause})", file=sys.stderr)
        raise StoreUnavailable(str(e)) from e


def cmd_report(args: argparse.Namespace) -> int:
    config = make_config()
    configured = list(dict.fromkeys(config.indexed_properties))
    shown = _names(args, config)
    database = config.database
    _require_tables(database)
    if not configured:
        print("No indexed properties are configured: reverse lookup is off.")
        return 0
    # The verdict is always about the whole configured set: --properties only
    # narrows what is printed, so a subset cannot read as "the check passes".
    state = _readiness_or_empty(database, sorted(set(configured) | set(shown)))
    counts = count_rows(database, shown, read_rcu=args.read_rcu)
    recorded = state.recorded
    print(
        f"Backend: {database}; configured names: {configured}; recorded name "
        f"set: {sorted(recorded) if recorded is not None else 'none'}"
    )
    for name in shown:
        c = counts[name]
        flags = ["marked" if name in state.marked else "UNMARKED"]
        if recorded is not None and name not in recorded:
            flags.append("absent from the recorded set")
        print(
            f"  {name}: property rows={c.properties} lookup rows={c.lookups} "
            f"[{', '.join(flags)}]"
        )
    refuses = [
        n
        for n in configured
        if n not in state.marked or (recorded is not None and n not in recorded)
    ]
    if refuses and properties_table_empty(database):
        print("The store holds no actor data: the first start marks every name.")
        return 0
    if refuses:
        print(
            f"The startup check would refuse: {', '.join(refuses)}. "
            f"Run '{PROG} backfill --apply'."
        )
        return 1
    print("Every configured name is marked: the startup check passes.")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    config = make_config()
    names = _names(args, config)
    database = config.database
    if not names:
        print("No indexed properties are configured: nothing to backfill.")
        return 1
    _require_tables(database)
    apply = bool(args.apply)
    if apply:
        _ensure_lookup_table(database)
    print(
        f"Backfilling {database} reverse lookup for {sorted(names)}; "
        f"{'writing' if apply else 'DRY RUN (add --apply to write)'}"
    )
    if database == "postgresql":
        stats = backfill_postgresql(
            names, apply=apply, batch_size=args.batch_size, pause=args.pause
        )
    else:
        stats = backfill_dynamodb(
            names,
            apply=apply,
            rps=args.rps,
            read_rcu=args.read_rcu,
            segments=args.segments,
            checkpoint_file=args.checkpoint_file,
        )
    print(
        f"Summary: scanned={stats.scanned} matches={stats.matched} "
        f"{'written-or-present' if apply else 'would-write'}={stats.written} "
        f"collisions={sum(stats.collisions.values())} orphans={stats.orphans} "
        f"faults={stats.faults}"
    )
    for detail in stats.collision_details:
        logger.warning(f"COLLISION (not overwritten): {detail}")
    if stats.orphans:
        print(
            f"{stats.orphans} property row(s) belong to actors that no longer "
            "exist and were skipped."
        )
    if stats.faults:
        print("The pass hit a fault: no name is marked. Re-run to resume.")
        return 1
    if not apply:
        return 1 if stats.collisions else 0
    done = stats.completed_names(names)
    backend = lookup_backend(database)
    if done:
        try:
            before = read_readiness(database, names)
            backend.mark_backfilled(done)
            base = (
                before.recorded
                if before.recorded is not None
                else set(before.marked) | set(done)
            )
            backend.record_configured(sorted(set(base) | set(done)))
        except DbError as e:  # folds DbError: reported
            print(f"Could not write the markers: {e}", file=sys.stderr)
            return 1
    skipped = [n for n in names if n not in done]
    if skipped:
        print(
            f"Left unmarked (collisions): {', '.join(skipped)}. Two actors "
            "share an indexed value; the earlier lookup row was kept. "
            "Resolve it, then re-run (idempotent). A run resumed from a "
            "checkpoint still reports collisions found before the checkpoint: "
            "after resolving them, delete the checkpoint file first."
        )
        return 1
    print(f"Marked backfill-complete: {', '.join(done)}.")
    return 0


def cmd_mark_complete(args: argparse.Namespace) -> int:
    config = make_config()
    names = _names(args, config)
    database = config.database
    if not names:
        print("No indexed properties are configured: nothing to mark.")
        return 1
    _require_tables(database)
    counts = count_rows(database, names, read_rcu=args.read_rcu)
    unsafe = [n for n in names if counts[n].properties > 0 and counts[n].lookups == 0]
    if unsafe and not args.force:
        print(
            f"Refusing: {', '.join(unsafe)} has property rows but no lookup "
            f"rows, so marking it would make the startup check pass while "
            f"lookups miss. Run '{PROG} backfill --apply', or pass --force "
            "to assert the data is ready anyway.",
            file=sys.stderr,
        )
        return 1
    for n in names:
        if 0 < counts[n].lookups < counts[n].properties:
            print(
                f"Warning: {n} has fewer lookup rows ({counts[n].lookups}) than "
                f"property rows ({counts[n].properties}); a partial backfill "
                f"would look like this. Run '{PROG} backfill --apply' unless "
                "values are shared between actors.",
                file=sys.stderr,
            )
    if not args.apply:
        print(f"Would mark: {', '.join(names)} (add --apply to write).")
        return 0
    _ensure_lookup_table(database)
    backend = lookup_backend(database)
    try:
        before = read_readiness(database, names)
        backend.mark_backfilled(names)
        base = (
            before.recorded
            if before.recorded is not None
            else set(before.marked) | set(names)
        )
        backend.record_configured(sorted(set(base) | set(names)))
    except DbError as e:  # folds DbError: reported
        print(f"Could not write the markers: {e}", file=sys.stderr)
        return 1
    print(f"Marked backfill-complete: {', '.join(names)}.")
    return 0


def cmd_unmark(args: argparse.Namespace) -> int:
    config = make_config()
    names = _names(args, config)
    database = config.database
    if not names:
        print("No indexed properties are configured: nothing to unmark.")
        return 1
    _require_tables(database)
    if not args.apply:
        print(f"Would unmark: {', '.join(names)} (add --apply to write).")
        return 0
    try:
        lookup_backend(database).unmark(names)
    except DbError as e:  # folds DbError: reported
        print(f"Could not remove the markers: {e}", file=sys.stderr)
        return 1
    print(f"Unmarked: {', '.join(names)}. The startup check refuses them.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG, description=(__doc__ or "").strip().split("\n\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, writes: bool) -> None:
        p.add_argument(
            "--properties",
            default=None,
            help="comma-separated indexed property names (default: the "
            "application's INDEXED_PROPERTIES / library default)",
        )
        if writes:
            p.add_argument(
                "--apply", action="store_true", help="write (default: dry run)"
            )

    rep = sub.add_parser("report", help="show readiness per indexed name")
    common(rep, writes=False)
    rep.add_argument("--read-rcu", type=float, default=None)

    bf = sub.add_parser("backfill", help="write missing lookup rows, then mark")
    common(bf, writes=True)
    bf.add_argument("--rps", type=float, default=25.0, help="DynamoDB writes/second")
    bf.add_argument("--read-rcu", type=float, default=None, help="DynamoDB scan RCU/s")
    bf.add_argument("--segments", type=int, default=4, help="DynamoDB scan segments")
    bf.add_argument(
        "--checkpoint-file", default=".backfill_property_lookup.checkpoint.json"
    )
    bf.add_argument("--batch-size", type=int, default=1000, help="PostgreSQL batch")
    bf.add_argument("--pause", type=float, default=0.0, help="PostgreSQL pause (s)")

    mc = sub.add_parser("mark-complete", help="mark names without a backfill")
    common(mc, writes=True)
    mc.add_argument("--read-rcu", type=float, default=None)
    mc.add_argument("--force", action="store_true")

    um = sub.add_parser("unmark", help="remove the marker of a name")
    common(um, writes=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _build_parser().parse_args(argv)
    handlers = {
        "report": cmd_report,
        "backfill": cmd_backfill,
        "mark-complete": cmd_mark_complete,
        "unmark": cmd_unmark,
    }
    try:
        return handlers[args.command](args)
    except StoreUnavailable as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
