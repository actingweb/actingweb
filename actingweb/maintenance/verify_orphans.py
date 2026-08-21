#!/usr/bin/env python3
"""
Sweep property, attribute and trust rows across the WHOLE table (not one
actor's partition) for rows whose actor id is absent from the actor table --
residue an interrupted ``Actor.delete()`` or a caller writing actor-scoped
data for an id that never existed can leave behind.

See thoughts/plans/2026-08-20-v2-positional-access-cost.md Phase 13 and
docs/reference/actor-deletion.rst "Finding orphaned rows" for the four edge
cases this module exists to get right -- each is worth reading before
touching this file, because each is a way to delete live data by mistake:

1. An empty or failed actor-id read must never be treated as "zero
   actors" -- that makes every row in every table look orphaned. Refuse to
   sweep and exit 2 instead.
2. Reserved ids (the ``_actingweb_`` prefix) are matched by prefix, not by
   the closed list in constants.py, and are reported separately -- never as
   orphans, live actor or not.
3. Reads must be consistent. DynamoDB's default Scan is eventually
   consistent, and a seconds-old actor absent from a stale read would be
   misclassified as the thing this tool exists to find.
4. Report only. There is no ``--delete`` flag and no code path in this
   module deletes a row (tests/test_verify_orphans.py asserts this
   structurally, by parsing the module's AST). Classification is safe
   because ``Actor.create()`` writes the actor row first and
   ``Actor.delete()`` removes it last, so an actor mid-create or mid-delete
   always still has its row -- but it is still a point-in-time judgement
   about rows another process may be writing. Review the report, then
   delete reviewed rows with your own tooling.

Run under the SAME environment as the application (``DATABASE_BACKEND`` and
its backend-specific connection settings) but under an OPERATOR credential,
not the application's runtime role: the full-table scans here need
Scan/Query read permission on the actor, property, attribute and trust
tables, which a locked-down serving-path role deliberately lacks. This is a
long-running, checkpointed CLI for a persistent shell -- not something to
invoke inside a lambda-like runtime.

    poetry run python scripts/verify_orphans.py
    poetry run python scripts/verify_orphans.py --rps 200 \\
        --checkpoint-file .verify_orphans.checkpoint.json

This tool classifies orphans; it does not replace
``actingweb-verify-property-lists`` (per-actor list index integrity) or any
consumer-side integrity sweep.

Exit codes: 0 = clean (no orphans, nothing errored); 1 = orphans found
and/or a table's sweep errored; 2 = the actor-id read itself failed or came
back empty -- refused to sweep at all, not a report of zero orphans;
3 = nothing was scanned because every table was already complete in the
checkpoint file -- the printed report is a REPLAY of the earlier scan, not
the database's current state. Delete the checkpoint file and re-run for a
fresh scan (in particular after removing reported rows).
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterable, Iterator
from typing import Any

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("verify_orphans")

RESERVED_ACTOR_ID_PREFIX = "_actingweb_"

ROW_TYPES = ("property", "attribute", "trust")


class RateLimiter:
    """Thread-safe items/second limiter (same shape as
    verify_property_lists.py's), used here to bound rows scanned per second
    rather than lists checked per second."""

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
    """Resume state for a possibly-interrupted sweep, at whole-table
    granularity (property/attribute/trust).

    Unlike verify_property_lists.py's per-actor Checkpoint, a single table
    scanned here can be the entire cost of a run by itself, so "this table
    is fully scanned" is the unit worth not repeating -- not "this row is
    done" within one. A table is marked done once its sweep completes
    without raising, regardless of whether it found orphans: there is no
    --repair step here that would make re-checking it later meaningful, so
    the only reason to ever re-scan a table is deleting this checkpoint
    file and starting over.
    """

    def __init__(self, path: str | None) -> None:
        self._path = path
        self._tables_done: set[str] = set()
        self._orphans: dict[str, list[list[str]]] = {t: [] for t in ROW_TYPES}
        self._reserved: dict[str, list[list[str]]] = {t: [] for t in ROW_TYPES}
        self._counts: dict[str, int] = dict.fromkeys(ROW_TYPES, 0)
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                self._tables_done = set(data.get("tables_done", []))
                for t in ROW_TYPES:
                    self._orphans[t] = data.get("orphans", {}).get(t, [])
                    self._reserved[t] = data.get("reserved", {}).get(t, [])
                    self._counts[t] = data.get("counts", {}).get(t, 0)
                logger.info(
                    f"Resuming from checkpoint {path} (tables already "
                    f"swept: {sorted(self._tables_done) or 'none'})"
                )
            except Exception as e:
                logger.warning(f"Could not read checkpoint {path}: {e}")

    def is_table_done(self, table: str) -> bool:
        return table in self._tables_done

    def mark_table_done(self, table: str, result: dict[str, Any]) -> None:
        self._tables_done.add(table)
        self._orphans[table] = [list(x) for x in result["orphans"].get(table, [])]
        self._reserved[table] = [list(x) for x in result["reserved"].get(table, [])]
        self._counts[table] = result["counts"].get(table, 0)
        self._save()

    def merged(self) -> dict[str, Any]:
        return {
            "orphans": {t: [tuple(x) for x in v] for t, v in self._orphans.items()},
            "reserved": {t: [tuple(x) for x in v] for t, v in self._reserved.items()},
            "counts": dict(self._counts),
        }

    def clear(self) -> None:
        if self._path and os.path.exists(self._path):
            os.unlink(self._path)

    def _save(self) -> None:
        if not self._path:
            return
        tmp = f"{self._path}.tmp"
        data = {
            "tables_done": sorted(self._tables_done),
            "orphans": self._orphans,
            "reserved": self._reserved,
            "counts": self._counts,
        }
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self._path)


def classify_rows(
    actor_ids: set[str], rows: Iterable[tuple[str, str, str]]
) -> dict[str, Any]:
    """Pure classification: no I/O, no backend, no config.

    ``rows`` is an iterable of ``(row_type, actor_id, row_name)``.
    ``actor_ids`` must already be the actor table's current, consistently
    read, full id set -- this function has no way to distinguish "genuinely
    zero actors" from "the caller passed an empty set because the read
    failed", so it does not try. That distinction belongs to the caller,
    made BEFORE calling this function: an empty or failed actor read must
    never reach here as an empty set standing in for "everything is
    orphaned".

    Reserved ids (``RESERVED_ACTOR_ID_PREFIX``) are matched before the
    orphan check and never fall into the orphan bucket, live actor or not --
    some reserved ids are real rows in the actor table
    (``ACTINGWEB_SYSTEM_ACTOR``, ``OAUTH2_SYSTEM_ACTOR``) and some
    deliberately never are (``DELETED_ACTORS_STORE``, a consumer's own
    reserved ids) -- the prefix is the only thing that reliably identifies
    either kind.

    Returns ``{"orphans": {row_type: [(actor_id, row_name), ...]},
    "reserved": {row_type: [...]}, "counts": {row_type: total_seen}}``.
    """
    orphans: dict[str, list[tuple[str, str]]] = {t: [] for t in ROW_TYPES}
    reserved: dict[str, list[tuple[str, str]]] = {t: [] for t in ROW_TYPES}
    counts: dict[str, int] = dict.fromkeys(ROW_TYPES, 0)

    for row_type, actor_id, row_name in rows:
        counts[row_type] = counts.get(row_type, 0) + 1
        if actor_id.startswith(RESERVED_ACTOR_ID_PREFIX):
            reserved.setdefault(row_type, []).append((actor_id, row_name))
        elif actor_id not in actor_ids:
            orphans.setdefault(row_type, []).append((actor_id, row_name))

    return {"orphans": orphans, "reserved": reserved, "counts": counts}


def _dynamodb_actor_ids() -> set[str]:
    """Deliberately NOT ``get_actor_list(config).fetch()``: that convenience
    wrapper's ``Actor.scan()`` has no ``consistent_read``, so a seconds-old
    actor could be absent from the very set this whole sweep classifies
    against -- the one read in this module where staleness is a data-loss
    bug (case 3 above), not the usual eventual-consistency cost tradeoff.
    Scan the model directly with ``consistent_read=True`` instead."""
    from actingweb.db.dynamodb.actor import Actor

    return {
        item.id for item in Actor.scan(consistent_read=True, attributes_to_get=["id"])
    }


def _postgresql_actor_ids() -> set[str]:
    """PostgreSQL reads are always a consistent MVCC snapshot -- there is no
    DynamoDB-style eventually-consistent read mode to opt out of here."""
    from actingweb.db.postgresql.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM actors")
        return {row[0] for row in cur.fetchall()}


def _dynamodb_rows(table: str, limiter: RateLimiter) -> Iterator[tuple[str, str, str]]:
    if table == "property":
        from actingweb.db.dynamodb.property import Property

        # Property and PropertyLegacy map to the SAME table with the same
        # (id, name) key schema -- scanning Property alone covers every
        # property row, including list:-prefixed ones, regardless of which
        # model wrote it.
        for item in Property.scan(
            consistent_read=True, attributes_to_get=["id", "name"]
        ):
            limiter.wait()
            yield ("property", item.id, item.name)
    elif table == "attribute":
        from actingweb.db.dynamodb.attribute import Attribute

        for item in Attribute.scan(
            consistent_read=True, attributes_to_get=["id", "bucket_name"]
        ):
            limiter.wait()
            yield ("attribute", item.id, item.bucket_name)
    elif table == "trust":
        from actingweb.db.dynamodb.trust import Trust

        # The base Trust table, never SecretIndex -- a GSI read cannot be
        # consistent (case 3).
        for item in Trust.scan(
            consistent_read=True, attributes_to_get=["id", "peerid"]
        ):
            limiter.wait()
            yield ("trust", item.id, item.peerid)
    else:
        raise ValueError(f"unknown table {table!r}")


_POSTGRESQL_TABLES = {
    "property": ("properties", "name"),
    "attribute": ("attributes", "bucket_name"),
    "trust": ("trusts", "peerid"),
}


def _postgresql_rows(
    table: str, limiter: RateLimiter
) -> Iterator[tuple[str, str, str]]:
    sql_table, column = _POSTGRESQL_TABLES[table]

    from actingweb.db.postgresql.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id, {column} FROM {sql_table}")  # nosec: fixed identifiers, not user input
        for row in cur.fetchall():
            limiter.wait()
            yield (table, row[0], row[1])


def _rows_for(
    backend: str, table: str, limiter: RateLimiter
) -> Iterator[tuple[str, str, str]]:
    if backend == "postgresql":
        return _postgresql_rows(table, limiter)
    return _dynamodb_rows(table, limiter)


def _read_actor_ids(backend: str) -> set[str]:
    if backend == "postgresql":
        return _postgresql_actor_ids()
    return _dynamodb_actor_ids()


def _log_target(config: Any, rps: float) -> None:
    """Say out loud which deployment is about to be swept -- see the
    matching function in verify_property_lists.py for why this matters: a
    clean report from the wrong tables looks identical to a clean report
    from the right ones."""
    backend = getattr(config, "database", "unknown")
    if backend == "postgresql":
        target = (
            f"host={os.getenv('PG_DB_HOST', 'localhost')} "
            f"db={os.getenv('PG_DB_NAME', 'actingweb')} "
            f"schema={os.getenv('PG_DB_SCHEMA', 'public')} "
            f"prefix={os.getenv('PG_DB_PREFIX', '') or '(none)'}"
        )
    else:
        prefix = os.getenv("AWS_DB_PREFIX", "demo_actingweb")
        target = (
            f"region={os.getenv('AWS_DEFAULT_REGION', '(default)')} "
            f"prefix={prefix} "
            f"endpoint={os.getenv('AWS_DB_HOST', '(aws)')}"
        )
        if not os.getenv("AWS_DB_PREFIX"):
            logger.warning(
                "AWS_DB_PREFIX is not set -- defaulting to 'demo_actingweb'. "
                "If your deployment uses a different prefix this sweeps the "
                "wrong tables and reports clean, because there is nothing "
                "there to find. Set the same environment the application "
                "runs with."
            )
    logger.info(f"Target: backend={backend} {target}")
    logger.info(f"Mode: report-only (no --delete exists); rps={rps}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep property, attribute and trust rows for actor ids absent "
            "from the actor table. Report only -- never deletes."
        )
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=10.0,
        help="max rows scanned per second (default 10; 0 = unlimited)",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=".verify_orphans.checkpoint.json",
        help="resume state file (default .verify_orphans.checkpoint.json)",
    )
    args = parser.parse_args()

    from actingweb.config import Config

    config = Config()
    backend = getattr(config, "database", "dynamodb")
    _log_target(config, args.rps)

    try:
        actor_ids = _read_actor_ids(backend)
    except Exception as e:
        logger.error(f"Actor-id read failed: {e}")
        actor_ids = set()

    if not actor_ids:
        logger.error(
            "Actor-id read returned no ids (or failed). Refusing to sweep: "
            "treating an empty actor set as ground truth would make every "
            "row in every table look orphaned. This is NOT a report of "
            "zero orphans -- fix the read (credentials, table, region or "
            "schema) and re-run."
        )
        return 2

    checkpoint = Checkpoint(args.checkpoint_file)
    limiter = RateLimiter(args.rps)

    had_error = False
    tables_swept_this_run = 0
    for table in ROW_TYPES:
        if checkpoint.is_table_done(table):
            logger.info(f"{table}: already swept (checkpoint) -- skipping")
            continue
        logger.info(f"{table}: sweeping...")
        try:
            rows = _rows_for(backend, table, limiter)
            result = classify_rows(actor_ids, rows)
        except Exception as e:
            logger.error(f"{table}: sweep failed: {e}")
            had_error = True
            continue
        tables_swept_this_run += 1
        checkpoint.mark_table_done(table, result)
        logger.info(
            f"{table}: {result['counts'].get(table, 0)} row(s) scanned, "
            f"{len(result['orphans'].get(table, []))} orphan(s), "
            f"{len(result['reserved'].get(table, []))} reserved"
        )

    report = checkpoint.merged()
    total_orphans = sum(len(v) for v in report["orphans"].values())
    total_reserved = sum(len(v) for v in report["reserved"].values())

    # Every table was already marked complete in the checkpoint file, so
    # this run scanned NOTHING -- everything below is a replay of the
    # earlier scan's findings, not the database's current state. Without
    # this guard, an operator who deleted the reported rows and re-ran
    # would get the ORIGINAL counts and orphan list reprinted, exit 1, and
    # no way to tell it from a fresh scan -- the same trust failure shape
    # as case 1 in the module docstring.
    pure_replay = tables_swept_this_run == 0 and not had_error
    if pure_replay:
        logger.warning(
            f"REPLAYED FROM CHECKPOINT -- no rows were scanned in this run: "
            f"every table is already marked complete in "
            f"{args.checkpoint_file}. The report below repeats that earlier "
            f"scan's findings and says nothing about the database's current "
            f"state. If you have removed the reported rows since, delete "
            f"the checkpoint file and re-run for a fresh scan."
        )

    if total_orphans:
        logger.warning(f"ORPHANED ROWS FOUND: {total_orphans}")
        for t in ROW_TYPES:
            for actor_id, name in report["orphans"][t]:
                logger.warning(f"orphan {t}: actor_id={actor_id} name={name}")

    if total_reserved:
        logger.info(f"Reserved rows (never orphans): {total_reserved}")
        for t in ROW_TYPES:
            for actor_id, name in report["reserved"][t]:
                logger.info(f"reserved {t}: actor_id={actor_id} name={name}")

    logger.info(
        f"Summary: actors={len(actor_ids)} "
        f"rows_scanned={sum(report['counts'].values())} "
        f"orphans={total_orphans} reserved={total_reserved} "
        f"errors={had_error}"
    )
    logger.info(
        "Report only -- this tool never deletes. Review the orphan list "
        "above, then remove reviewed rows with your own tooling."
    )

    if not had_error and total_orphans == 0 and not pure_replay:
        checkpoint.clear()

    if pure_replay:
        return 3
    if had_error:
        return 1
    return 1 if total_orphans else 0


if __name__ == "__main__":
    sys.exit(main())
