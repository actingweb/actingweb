#!/usr/bin/env python3
"""
Sweep all actors' property lists for index corruption (holes, orphans,
duplicate residue) and optionally repair.

Targets the v1 (dense-integer-key) list storage format described in
thoughts/plans/2026-08-08-property-list-index-integrity.md. A list can
become unhealthy when a delete/insert shift loop is interrupted mid-way
(process death, throttle, timeout) -- see
thoughts/research/2026-08-07-property-list-index-integrity.md for the
mechanism.

Run with the SAME environment as the application (DATABASE_BACKEND and its
backend-specific connection settings), e.g.::

    poetry run python scripts/verify_property_lists.py
    poetry run python scripts/verify_property_lists.py --repair
    poetry run python scripts/verify_property_lists.py --rps 20 \\
        --checkpoint-file .verify.checkpoint.json

Dry-run (report only) by default. --repair invokes ListProperty.compact()
on every unhealthy list that has holes or orphans; it never touches a list
whose only finding is adjacent_duplicates -- compact() itself leaves
duplicate residue intact (a duplicate always means a destroyed item, and
silently collapsing one copy would bless the data loss as intentional).

Exit code 0 if every list is healthy (or was repaired to healthy) by the
end of the run, 1 if any list is still unhealthy or errored.
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from typing import Any

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("verify_property_lists")


class RateLimiter:
    """Thread-safe items/second limiter (same shape as
    backfill_property_lookup.py's), used here to bound lists checked per
    second rather than raw DB items per second."""

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
    """Set of actor IDs already swept this run, persisted for resume."""

    def __init__(self, path: str | None) -> None:
        self._path = path
        self._done: set[str] = set()
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    self._done = set(json.load(f))
                logger.info(
                    f"Resuming from checkpoint {path} "
                    f"({len(self._done)} actors already swept)"
                )
            except Exception as e:
                logger.warning(f"Could not read checkpoint {path}: {e}")

    def is_done(self, actor_id: str) -> bool:
        return actor_id in self._done

    def mark_done(self, actor_id: str) -> None:
        self._done.add(actor_id)
        if self._path:
            tmp = f"{self._path}.tmp"
            with open(tmp, "w") as f:
                json.dump(sorted(self._done), f)
            os.replace(tmp, self._path)


def sweep_actor(
    actor_id: str,
    config: Any,
    repair: bool,
    limiter: RateLimiter,
) -> tuple[int, int, int]:
    """Verify (and optionally repair) every list belonging to one actor.

    Returns (lists_checked, lists_unhealthy_after, lists_errored).
    """
    from actingweb.property import PropertyListStore
    from actingweb.property_list import ListProperty

    list_store = PropertyListStore(actor_id=actor_id, config=config)
    list_names = list_store.list_all()

    checked = 0
    unhealthy_after = 0
    errored = 0

    for name in list_names:
        limiter.wait()
        checked += 1
        list_prop = ListProperty(actor_id=actor_id, name=name, config=config)
        try:
            report = list_prop.verify()
        except Exception as e:
            logger.error(f"actor={actor_id} list={name}: verify() failed: {e}")
            errored += 1
            continue

        if report["healthy"]:
            continue

        logger.warning(
            f"actor={actor_id} list={name}: UNHEALTHY "
            f"stored_length={report['stored_length']} "
            f"readable_count={report['readable_count']} "
            f"missing_indices={report['missing_indices']} "
            f"orphan_indices={report['orphan_indices']} "
            f"adjacent_duplicates={report['adjacent_duplicates']}"
        )
        if report["adjacent_duplicates"]:
            logger.warning(
                f"actor={actor_id} list={name}: duplicate residue reported "
                f"-- --repair never rewrites this, resolve manually"
            )

        if not repair:
            unhealthy_after += 1
            continue

        if not report["missing_indices"] and not report["orphan_indices"]:
            # Only adjacent_duplicates: compact() would rewrite nothing.
            unhealthy_after += 1
            continue

        try:
            list_prop.compact()
        except Exception as e:
            logger.error(f"actor={actor_id} list={name}: compact() failed: {e}")
            errored += 1
            continue

        post = list_prop.verify()
        if post["healthy"]:
            logger.info(f"actor={actor_id} list={name}: repaired")
        else:
            unhealthy_after += 1

    return checked, unhealthy_after, errored


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sweep all actors' property lists for index corruption."
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="invoke compact() on unhealthy lists (default: dry-run report only)",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=10.0,
        help="max lists checked per second (default 10; 0 = unlimited)",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=".verify_property_lists.checkpoint.json",
        help="resume state file (default .verify_property_lists.checkpoint.json)",
    )
    args = parser.parse_args()

    from actingweb.config import Config
    from actingweb.db import get_actor_list

    config = Config()
    logger.info(
        f"Sweeping property lists on backend={config.database}; "
        f"{'REPAIR' if args.repair else 'dry-run'}; rps={args.rps}"
    )

    actors = get_actor_list(config).fetch()
    if not actors:
        logger.info("No actors found")
        return 0
    assert isinstance(actors, list)

    checkpoint = Checkpoint(args.checkpoint_file)
    limiter = RateLimiter(args.rps)

    total_checked = 0
    total_unhealthy = 0
    total_errored = 0
    actors_swept = 0

    for actor in actors:
        actor_id = actor.get("id") if isinstance(actor, dict) else None
        if not actor_id or checkpoint.is_done(actor_id):
            continue
        checked, unhealthy, errored = sweep_actor(
            actor_id, config, args.repair, limiter
        )
        total_checked += checked
        total_unhealthy += unhealthy
        total_errored += errored
        actors_swept += 1
        checkpoint.mark_done(actor_id)

    logger.info(
        f"Summary: actors_swept={actors_swept} lists_checked={total_checked} "
        f"unhealthy_remaining={total_unhealthy} errors={total_errored}"
    )
    if not args.repair and total_unhealthy:
        logger.info(
            "Re-run with --repair to close holes/orphans (duplicate residue "
            "is never auto-repaired)."
        )
    if (
        total_unhealthy == 0
        and total_errored == 0
        and os.path.exists(args.checkpoint_file)
    ):
        os.unlink(args.checkpoint_file)

    return 1 if (total_unhealthy or total_errored) else 0


if __name__ == "__main__":
    sys.exit(main())
