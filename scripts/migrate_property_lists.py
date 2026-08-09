#!/usr/bin/env python3
"""
Bulk-migrate v1 (dense-integer) property lists to v2 (fractional rank key)
storage -- see thoughts/plans/2026-08-08-property-list-index-integrity.md,
Phase 5.

Small lists (<= 50 items) already migrate lazily on their next mutation
(append/insert/__setitem__/__delitem__) -- this script is for lists too
large or too idle to reach that trigger on their own, and for a one-time
upgrade sweep across an existing deployment.

Run with the SAME environment as the application (DATABASE_BACKEND and its
backend-specific connection settings), e.g.::

    poetry run python scripts/migrate_property_lists.py
    poetry run python scripts/migrate_property_lists.py --migrate
    poetry run python scripts/migrate_property_lists.py --migrate --rps 20 \\
        --checkpoint-file .migrate.checkpoint.json
    poetry run python scripts/migrate_property_lists.py --downgrade ACTOR_ID/list_name

Dry-run (report only) by default -- reports what WOULD be migrated,
including refused names (containing '#') and duplicate residue, without
writing anything. --migrate performs the migration via
ListProperty.migrate_to_v2() (idempotent, safe to interrupt and re-run).

Unlike scripts/backfill_property_lookup.py, this uses a single
per-actor-at-a-time model (matching scripts/verify_property_lists.py)
rather than DynamoDB parallel-scan segments, because it must work
identically against both backends -- PostgreSQL has no equivalent to
DynamoDB's segmented Scan API.

--downgrade ACTOR_ID/list_name is an EMERGENCY v2 -> v1 converter, for the
rare case where a bug in the v2 code path forces a rollback to a released
version that only understands v1. It is NOT a normal operation: run it
only against a list the application is not concurrently writing to (no
locking is taken), and only as a last resort -- there is no forward path
back to v2 other than a fresh migration.

Exit code 0 if every eligible list was migrated (or already was) by the
end of the run, 1 if any list was refused or errored.
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
logger = logging.getLogger("migrate_property_lists")


class RateLimiter:
    """Thread-safe items/second limiter (same shape as the sibling
    scripts'), used here to bound lists migrated per second."""

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


def migrate_actor(
    actor_id: str,
    config: Any,
    migrate: bool,
    limiter: RateLimiter,
) -> tuple[int, int, int, list[str]]:
    """Migrate (or dry-run report on) every v1 list belonging to one actor.

    Returns (lists_checked, lists_migrated_or_would_migrate, lists_errored,
    refused_names).
    """
    from actingweb.property import PropertyListStore
    from actingweb.property_list import ListProperty

    list_store = PropertyListStore(actor_id=actor_id, config=config)
    list_names = list_store.list_all()

    checked = 0
    migrated = 0
    errored = 0
    refused: list[str] = []

    for name in list_names:
        limiter.wait()
        list_prop = ListProperty(actor_id=actor_id, name=name, config=config)
        try:
            already_v2 = list_prop.verify().get("format") == 2
        except Exception as e:
            logger.error(f"actor={actor_id} list={name}: verify() failed: {e}")
            errored += 1
            continue

        if already_v2:
            continue

        checked += 1

        if "#" in name:
            refused.append(f"{actor_id}/{name}")
            logger.warning(
                f"actor={actor_id} list={name}: REFUSED -- name contains "
                f"'#', rename before migrating; keeps working as v1"
            )
            continue

        if not migrate:
            report = list_prop.verify()
            if report["adjacent_duplicates"]:
                logger.warning(
                    f"actor={actor_id} list={name}: would migrate "
                    f"{report['readable_count']} items with "
                    f"{len(report['adjacent_duplicates'])} duplicate "
                    f"pair(s) preserved as-is"
                )
            migrated += 1
            continue

        try:
            result = list_prop.migrate_to_v2()
        except Exception as e:
            logger.error(f"actor={actor_id} list={name}: migrate_to_v2() failed: {e}")
            errored += 1
            continue

        if result["migrated"]:
            migrated += 1
            logger.info(
                f"actor={actor_id} list={name}: migrated "
                f"({result['item_count']} items, "
                f"had_holes={result['had_holes']}, "
                f"duplicates={result['duplicate_count']})"
            )
        else:
            # Only "name_contains_hash" reaches here (already_v2 was
            # filtered above) -- defensive, since the "#" check above
            # already refuses before calling migrate_to_v2().
            refused.append(f"{actor_id}/{name}")

    return checked, migrated, errored, refused


def downgrade_to_v1(actor_id: str, list_name: str, config: Any) -> dict[str, Any]:
    """EMERGENCY v2 -> v1 converter. See the module docstring's warning --
    this is not a normal operation, has no locking, and is meant for a
    single manual invocation during an incident, not routine use."""
    from actingweb.db import get_property
    from actingweb.property_list import ListProperty

    list_prop = ListProperty(actor_id=actor_id, name=list_name, config=config)
    if list_prop.verify().get("format") != 2:
        return {"downgraded": False, "reason": "not_v2"}

    items = list_prop.to_list()  # one range query, in order

    db = get_property(config)
    for i, item in enumerate(items):
        value = json.dumps(item)
        if not db.set(actor_id=actor_id, name=f"list:{list_name}-{i}", value=value):
            raise RuntimeError(f"list item write failed for '{list_name}'[{i}]")

    meta_db = get_property(config)
    meta_str = meta_db.get(actor_id=actor_id, name=f"list:{list_name}-meta")
    meta = json.loads(meta_str) if meta_str else {}
    meta.pop("format", None)
    meta["length"] = len(items)
    meta.setdefault("item_type", "json")
    meta.setdefault("chunk_size", 1)
    meta.setdefault("version", "1.0")
    meta.setdefault("description", "")
    meta.setdefault("explanation", "")
    save_db = get_property(config)
    if not save_db.set(
        actor_id=actor_id, name=f"list:{list_name}-meta", value=json.dumps(meta)
    ):
        raise RuntimeError(f"list metadata write failed for '{list_name}'")

    # Delete the v2 rows.
    lower, upper = list_prop._v2_bounds()  # noqa: SLF001 -- emergency tool
    range_db = get_property(config)
    v2_rows = range_db.get_range(
        actor_id=actor_id, lower=lower, upper=upper, keys_only=True
    )
    for v2_name in v2_rows:
        del_db = get_property(config)
        if not del_db.set(actor_id=actor_id, name=v2_name, value=None):
            raise RuntimeError(
                f"list item write failed for '{list_name}' during downgrade cleanup"
            )

    return {"downgraded": True, "item_count": len(items)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bulk-migrate v1 property lists to v2 storage format."
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="perform the migration (default: dry-run report only)",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=10.0,
        help="max lists processed per second (default 10; 0 = unlimited)",
    )
    parser.add_argument(
        "--checkpoint-file",
        default=".migrate_property_lists.checkpoint.json",
        help="resume state file (default .migrate_property_lists.checkpoint.json)",
    )
    parser.add_argument(
        "--downgrade",
        metavar="ACTOR_ID/LIST_NAME",
        default=None,
        help="EMERGENCY: downgrade one v2 list back to v1 (see module "
        "docstring -- not for routine use)",
    )
    args = parser.parse_args()

    from actingweb.config import Config
    from actingweb.db import get_actor_list

    config = Config()

    if args.downgrade:
        if "/" not in args.downgrade:
            logger.error("--downgrade requires ACTOR_ID/LIST_NAME")
            return 1
        actor_id, list_name = args.downgrade.split("/", 1)
        logger.warning(
            f"EMERGENCY DOWNGRADE: {actor_id}/{list_name} -- v2 -> v1. "
            f"This is not a routine operation."
        )
        result = downgrade_to_v1(actor_id, list_name, config)
        logger.info(f"Result: {result}")
        return 0 if result.get("downgraded") else 1

    logger.info(
        f"Migrating property lists on backend={config.database}; "
        f"{'MIGRATE' if args.migrate else 'dry-run'}; rps={args.rps}"
    )

    actors = get_actor_list(config).fetch()
    if not actors:
        logger.info("No actors found")
        return 0
    assert isinstance(actors, list)

    checkpoint = Checkpoint(args.checkpoint_file if args.migrate else None)
    limiter = RateLimiter(args.rps)

    total_checked = 0
    total_migrated = 0
    total_errored = 0
    total_refused: list[str] = []
    actors_swept = 0

    for actor in actors:
        actor_id = actor.get("id") if isinstance(actor, dict) else None
        if not actor_id or checkpoint.is_done(actor_id):
            continue
        checked, migrated, errored, refused = migrate_actor(
            actor_id, config, args.migrate, limiter
        )
        total_checked += checked
        total_migrated += migrated
        total_errored += errored
        total_refused.extend(refused)
        actors_swept += 1
        checkpoint.mark_done(actor_id)

    logger.info(
        f"Summary: actors_swept={actors_swept} v1_lists_checked={total_checked} "
        f"{'migrated' if args.migrate else 'would_migrate'}={total_migrated} "
        f"refused={len(total_refused)} errors={total_errored}"
    )
    for name in total_refused:
        logger.warning(f"REFUSED (rename required): {name}")
    if not args.migrate and total_checked:
        logger.info("Re-run with --migrate to perform the migration.")
    if args.migrate and not total_refused and not total_errored:
        if os.path.exists(args.checkpoint_file):
            os.unlink(args.checkpoint_file)

    return 1 if (total_refused or total_errored) else 0


if __name__ == "__main__":
    sys.exit(main())
