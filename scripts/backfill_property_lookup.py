#!/usr/bin/env python3
"""
Backfill the v2 property lookup table from the properties table.

The properties table is the source of truth: this script scans it for
indexed properties and writes v2 digest-keyed lookup rows
(sha256(name + NUL + value)). v1 lookup rows are never read as input.
Values are copied VERBATIM — no re-encoding, no normalisation, no
lowercasing — because runtime lookups are exact-match against the stored
string.

Run it with the SAME environment as the application (AWS_DB_PREFIX,
AWS_DEFAULT_REGION, AWS_DB_HOST, INDEXED_PROPERTIES, credentials), e.g.::

    poetry run python scripts/backfill_property_lookup.py --dry-run
    poetry run python scripts/backfill_property_lookup.py --rps 50

Features:
- streaming (never accumulates the table in memory)
- --rps rate limit (items/second across all segments; a full-table scan
  against production must not brown-out serving traffic or run up an
  unbounded on-demand bill)
- --segments N parallel scan segments
- checkpointed resume: per-segment last_evaluated_key persisted to
  --checkpoint-file after every page; re-running continues where it left
  off
- idempotent: conditional puts — an identical existing mapping counts as
  ok; a row owned by a DIFFERENT actor is reported as a collision and NOT
  overwritten (resolve manually, then re-run)
- --dry-run reports what would be written without writing

Exit code 0 on success with no collisions/errors, 1 otherwise.
After a clean run, verify reverse lookups resolve without deprecation
warnings, then drop the v1 ``<prefix>_property_lookup`` table.
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("backfill_property_lookup")


class RateLimiter:
    """Simple thread-safe items/second limiter shared across segments."""

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
    """Per-segment last_evaluated_key persistence for resume."""

    def __init__(self, path: str | None, total_segments: int) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._state: dict[str, object] = {}
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    saved = json.load(f)
                if saved.get("total_segments") == total_segments:
                    self._state = saved.get("segments", {})
                    logger.info(f"Resuming from checkpoint {path}")
                else:
                    logger.warning("Checkpoint segment count mismatch — starting over")
            except Exception as e:
                logger.warning(f"Could not read checkpoint {path}: {e}")
        self._total_segments = total_segments

    def get(self, segment: int):
        return self._state.get(str(segment))

    def set(self, segment: int, last_evaluated_key) -> None:
        with self._lock:
            self._state[str(segment)] = (
                last_evaluated_key if last_evaluated_key is not None else "done"
            )
            if self._path:
                tmp = f"{self._path}.tmp"
                with open(tmp, "w") as f:
                    json.dump(
                        {
                            "total_segments": self._total_segments,
                            "segments": self._state,
                        },
                        f,
                    )
                os.replace(tmp, self._path)


class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.scanned = 0
        self.matched = 0
        self.written = 0
        self.collisions: list[str] = []
        self.errors = 0

    def bump(self, field: str, amount: int = 1) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + amount)

    def collision(self, detail: str) -> None:
        with self._lock:
            self.collisions.append(detail)


def run_segment(
    segment: int,
    total_segments: int,
    indexed: set[str],
    limiter: RateLimiter,
    checkpoint: Checkpoint,
    stats: Stats,
    dry_run: bool,
) -> None:
    # Imported here so env validation in main() runs first
    from actingweb.db.dynamodb.property import Property
    from actingweb.db.dynamodb.property_lookup import (
        DbPropertyLookup,
        compute_lookup_key,
    )

    start_key = checkpoint.get(segment)
    if start_key == "done":
        logger.info(f"segment {segment}: already complete (checkpoint)")
        return
    if not isinstance(start_key, dict):
        start_key = None

    lookup = DbPropertyLookup() if not dry_run else None
    results = Property.scan(
        segment=segment,
        total_segments=total_segments,
        last_evaluated_key=start_key,
    )
    pages_since_checkpoint = 0
    for item in results:
        stats.bump("scanned")
        name = str(item.name) if item.name else ""
        if name in indexed and item.value:
            stats.bump("matched")
            value = str(item.value)  # verbatim — exactly as stored
            actor_id = str(item.id)
            limiter.wait()
            if dry_run:
                stats.bump("written")
            else:
                assert lookup is not None
                if lookup.create(property_name=name, value=value, actor_id=actor_id):
                    stats.bump("written")
                else:
                    # create() logs LOOKUP_COLLISION or LOOKUP_CREATE_FAILED
                    stats.collision(
                        f"property={name} actor={actor_id} "
                        f"digest={compute_lookup_key(name, value)[:12]}"
                    )
        pages_since_checkpoint += 1
        if pages_since_checkpoint >= 100:
            pages_since_checkpoint = 0
            checkpoint.set(segment, results.last_evaluated_key)
    checkpoint.set(segment, None)  # done
    logger.info(f"segment {segment}: complete")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill the v2 property lookup table from properties."
    )
    parser.add_argument("--dry-run", action="store_true", help="count, do not write")
    parser.add_argument(
        "--rps",
        type=float,
        default=25.0,
        help="max indexed items processed per second across all segments "
        "(default 25; 0 = unlimited)",
    )
    parser.add_argument(
        "--segments",
        type=int,
        default=4,
        help="parallel scan segments (default 4)",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=".backfill_property_lookup.checkpoint.json",
        help="resume state file (default .backfill_property_lookup.checkpoint.json)",
    )
    parser.add_argument(
        "--properties",
        default=None,
        help="comma-separated indexed property names (default: resolved "
        "from INDEXED_PROPERTIES env or the library default)",
    )
    args = parser.parse_args()

    if args.properties:
        indexed = {p.strip() for p in args.properties.split(",") if p.strip()}
    else:
        from actingweb.config import Config

        indexed = set(Config(database="dynamodb").indexed_properties)
    if not indexed:
        logger.error("No indexed properties configured — nothing to backfill")
        return 1

    prefix = os.getenv("AWS_DB_PREFIX", "demo_actingweb")
    logger.info(
        f"Backfilling {prefix}_property_lookup_v2 from {prefix}_properties; "
        f"indexed properties: {sorted(indexed)}; "
        f"{'DRY RUN' if args.dry_run else 'writing'}; "
        f"rps={args.rps} segments={args.segments}"
    )

    limiter = RateLimiter(args.rps)
    checkpoint = Checkpoint(
        args.checkpoint_file if not args.dry_run else None, args.segments
    )
    stats = Stats()

    with ThreadPoolExecutor(max_workers=args.segments) as pool:
        futures = [
            pool.submit(
                run_segment,
                seg,
                args.segments,
                indexed,
                limiter,
                checkpoint,
                stats,
                args.dry_run,
            )
            for seg in range(args.segments)
        ]
        for future in futures:
            try:
                future.result()
            except Exception as e:
                logger.error(f"Segment failed: {e}")
                stats.bump("errors")

    logger.info(
        f"Summary: scanned={stats.scanned} indexed-matches={stats.matched} "
        f"{'would-write' if args.dry_run else 'written-or-present'}="
        f"{stats.written} collisions={len(stats.collisions)} "
        f"segment-errors={stats.errors}"
    )
    for detail in stats.collisions:
        logger.warning(f"COLLISION (not overwritten): {detail}")
    if stats.collisions:
        logger.warning(
            "Collisions mean two actors share an indexed value; the earlier "
            "lookup row was kept. Resolve manually, then re-run (idempotent)."
        )
    if not args.dry_run and not stats.collisions and not stats.errors:
        logger.info(
            "Backfill complete. Verify reverse lookups resolve without "
            "deprecation warnings, then drop the v1 "
            f"{prefix}_property_lookup table."
        )
        if os.path.exists(args.checkpoint_file):
            os.unlink(args.checkpoint_file)
    return 1 if (stats.collisions or stats.errors) else 0


if __name__ == "__main__":
    sys.exit(main())
