#!/usr/bin/env python3
"""
Sweep all actors' property lists for index corruption (holes, orphans,
duplicate residue) or rank-key bloat, and optionally repair.

Handles both list storage formats described in
thoughts/plans/2026-08-08-property-list-index-integrity.md:
- v1 (dense-integer-key): can develop holes/orphans when a delete/insert
  shift loop is interrupted mid-way (process death, throttle, timeout) --
  see thoughts/research/2026-08-07-property-list-index-integrity.md.
- v2 (fractional rank key): cannot have holes/orphans by construction;
  "unhealthy" here means rank keys have grown long from repeated
  insert-between operations and are approaching the length cap.

Run with the SAME environment as the application (DATABASE_BACKEND and its
backend-specific connection settings), e.g.::

    poetry run python scripts/verify_property_lists.py
    poetry run python scripts/verify_property_lists.py --repair
    poetry run python scripts/verify_property_lists.py --rps 20 \\
        --checkpoint-file .verify.checkpoint.json

Dry-run (report only) by default. --repair invokes ListProperty.compact()
on every unhealthy v1 list that has holes or orphans, and on every
unhealthy v2 list (rank rebalance); it never touches a list whose only
finding is adjacent_duplicates -- compact() itself leaves duplicate
residue intact (a duplicate always means a destroyed item, and silently
collapsing one copy would bless the data loss as intentional).

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


def _log_target(config: Any, mode: str, rps: float) -> None:
    """Say out loud which deployment is about to be swept.

    The library defaults AWS_DB_PREFIX to "demo_actingweb", and a real
    populated demo deployment exists -- so running this without the
    environment the application uses silently sweeps the WRONG data and
    reports it clean. A clean report from the wrong table is worse than an
    error, because nothing about it looks wrong. Print the target, and warn
    when the prefix is the default that nobody sets deliberately.
    """
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
                "If your deployment uses a different prefix you are about to "
                "sweep the wrong tables and get a clean report from them. Set "
                "the same environment the application runs with."
            )
    logger.info(f"Target: backend={backend} {target}")
    logger.info(f"Mode: {mode}; rps={rps}")


def sweep_actor(
    actor_id: str,
    config: Any,
    repair: bool,
    limiter: RateLimiter,
    identity_key: str | None = None,
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
            # verify() fetches the actor's whole property partition, so this
            # is one dump per list. That is inherent to checking integrity
            # (which is this script's job) -- unlike the migrate script,
            # which only needs the format and uses storage_format().
            report = list_prop.verify(identity_key=identity_key)
        except Exception as e:
            logger.error(f"actor={actor_id} list={name}: verify() failed: {e}")
            errored += 1
            continue

        if report["healthy"]:
            continue

        # Report shape depends on storage format -- v1 lists can have
        # holes/orphans (a stored length disagreeing with what's actually
        # present); v2 lists structurally cannot (position is always
        # derived from what's present), so their report carries rank-length
        # info instead. See ListProperty.verify()/._v2_verify().
        is_v2 = report.get("format") == 2

        if is_v2:
            logger.warning(
                f"actor={actor_id} list={name}: UNHEALTHY (v2) "
                f"length={report['length']} "
                f"max_rank_length={report['max_rank_length']} "
                f"adjacent_duplicates={report['adjacent_duplicates']}"
            )
        else:
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
        if (
            identity_key
            and report.get("identity_checked_count") == 0
            and (report.get("length") or report.get("readable_count"))
        ):
            logger.warning(
                f"actor={actor_id} list={name}: NO row carries "
                f"'{identity_key}' -- the identity duplicate check compared "
                f"nothing. A clean result here means 'not checked', not "
                f"'no duplicates'. Check the field name."
            )
        if report.get("duplicate_identities"):
            for identity, positions in sorted(
                report["duplicate_identities"].items(), key=lambda kv: str(kv[0])
            ):
                logger.warning(
                    f"actor={actor_id} list={name}: {identity_key}={identity} "
                    f"appears at positions {positions} -- --repair never "
                    f"rewrites this, resolve manually"
                )

        if not repair:
            unhealthy_after += 1
            continue

        if is_v2:
            # compact() under v2 rebalances rank keys and nothing else. A
            # list flagged unhealthy ONLY for duplicate identities is not
            # something it can fix, so running it would rewrite every row
            # -- including the documented interrupted-compaction exposure
            # -- and leave the list just as unhealthy afterwards.
            needs_repair = bool(report["needs_rebalance"])
        else:
            needs_repair = bool(report["missing_indices"] or report["orphan_indices"])

        if not needs_repair:
            # v1, only adjacent_duplicates: compact() would rewrite nothing.
            unhealthy_after += 1
            continue

        try:
            list_prop.compact()
        except Exception as e:
            logger.error(f"actor={actor_id} list={name}: compact() failed: {e}")
            errored += 1
            continue

        post = list_prop.verify(identity_key=identity_key)
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
        "--identity-key",
        default=None,
        help=(
            "field name identifying an item (e.g. 'id'). Duplicate "
            "detection defaults to comparing raw stored bytes, which STOPS "
            "finding a duplicate once either copy is edited -- pass this if "
            "your items have an identifying field"
        ),
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
    _log_target(config, "REPAIR" if args.repair else "dry-run", args.rps)

    actors = get_actor_list(config).fetch()
    if not actors:
        logger.info("No actors found")
        return 0
    assert isinstance(actors, list)

    checkpoint = Checkpoint(args.checkpoint_file if args.repair else None)
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
            actor_id, config, args.repair, limiter, args.identity_key
        )
        total_checked += checked
        total_unhealthy += unhealthy
        total_errored += errored
        actors_swept += 1
        # Only checkpoint an actor left fully healthy. Marking a
        # still-unhealthy or errored actor done would let the next --repair
        # run skip it and report clean over unrepaired corruption. Lists
        # that --repair deliberately never fixes (duplicate residue) keep
        # the actor out of the checkpoint until an operator resolves them,
        # which is the intended nag.
        if not errored and not unhealthy:
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
    # Gate on --repair, matching the sibling migrate script. A read-only
    # run has no business deleting the resume state of an interrupted
    # --repair: it did not create that file and cannot know the repair run
    # had finished with it.
    if (
        args.repair
        and total_unhealthy == 0
        and total_errored == 0
        and os.path.exists(args.checkpoint_file)
    ):
        os.unlink(args.checkpoint_file)

    return 1 if (total_unhealthy or total_errored) else 0


if __name__ == "__main__":
    sys.exit(main())
