#!/usr/bin/env python3
"""
Bulk-migrate v1 (dense-integer) property lists to v2 (fractional rank key)
storage -- see thoughts/plans/2026-08-08-property-list-index-integrity.md,
Phase 5.

Lazy migration is OFF by default (ACTINGWEB_LAZY_MIGRATION_MAX_LENGTH=0),
so out of the box this script is the only thing that converts an existing
list. Where an operator has turned it on, it still only covers lists at or
under that item count that get mutated -- this script is for the rest, and
for a one-time upgrade sweep across an existing deployment at a rate and a
time of the operator's choosing (migration is inline and synchronous, so
one append() to a 40-item v1 list would otherwise do the whole migration
inside a user's request).

**Damaged lists are refused, by this script and by migrate_to_v2()
itself.** Migration renumbers the surviving rows, so a hole does not
survive it -- and neither does the evidence: the migrated list verifies
healthy afterwards with no record of what went missing. Repair first
(actingweb-verify-property-lists --repair, or ListProperty.compact()),
then migrate. --migrate-damaged overrides this for an operator who has
looked at the damage and decided to move on; the dry run names the lists
that need it either way.

Duplicate residue does NOT block migration: it stays visible afterwards
(v2's verify() reports duplicates just as v1's does), so migrating it
destroys no evidence. It is reported, not refused.

Run with the SAME environment as the application (DATABASE_BACKEND and its
backend-specific connection settings), e.g.::

    poetry run python scripts/migrate_property_lists.py
    poetry run python scripts/migrate_property_lists.py --migrate
    poetry run python scripts/migrate_property_lists.py --migrate --rps 20 \\
        --checkpoint-file .migrate.checkpoint.json
    poetry run python scripts/migrate_property_lists.py --downgrade ACTOR_ID/list_name

Dry-run (report only) by default -- reports what WOULD be migrated, what
would be refused (names containing '#', and lists with holes or orphans),
and duplicate residue, without writing anything. It exits 1 when anything
would be refused, so "exit 0" means the migration has nothing to trip
over. --migrate performs the migration via ListProperty.migrate_to_v2()
(idempotent, safe to interrupt and re-run).

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

ORDER MATTERS: roll the application back to the pre-v2 release FIRST, then
run --downgrade against the database. Where lazy migration has been turned
on, a downgraded list at or under its item limit is a lazy-migration
candidate again the instant it's v1 -- if the current (v2-aware)
application is still running against it, its very next append/insert/
setitem/delitem migrates it straight back to v2, silently undoing the
downgrade. Rolling the application back first also removes that race,
which is the other reason to do it in that order.

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


def migrate_actor(
    actor_id: str,
    config: Any,
    migrate: bool,
    limiter: RateLimiter,
    identity_key: str | None = None,
    allow_damaged: bool = False,
) -> tuple[int, int, int, list[tuple[str, str]]]:
    """Migrate (or dry-run report on) every v1 list belonging to one actor.

    Returns (lists_checked, lists_migrated_or_would_migrate, lists_errored,
    refusals), where each refusal is a ``(actor_id/list_name, reason)``
    pair -- ``"rename required"`` for a '#'-named list, ``"repair
    required"`` for one with holes or orphans.
    """
    from actingweb.property import PropertyListStore
    from actingweb.property_list import ListProperty

    list_store = PropertyListStore(actor_id=actor_id, config=config)
    list_names = list_store.list_all()

    checked = 0
    migrated = 0
    errored = 0
    refused: list[tuple[str, str]] = []

    for name in list_names:
        limiter.wait()
        list_prop = ListProperty(actor_id=actor_id, name=name, config=config)
        try:
            # One point read of the meta row. verify() would fetch the
            # actor's whole property partition per list purely to learn the
            # format -- ~13 partition dumps per actor on a typical one.
            already_v2 = list_prop.storage_format() == 2
        except Exception as e:
            logger.error(f"actor={actor_id} list={name}: format check failed: {e}")
            errored += 1
            continue

        if already_v2:
            # Reading as v2 is also what a migration interrupted between
            # its metadata flip and its v1 cleanup looks like, and this
            # branch is why re-running the script did not converge: it
            # skips the list without ever calling migrate_to_v2(), so the
            # cleanup that method now performs on the already_v2 path was
            # unreachable from the command operators actually run.
            if migrate:
                try:
                    swept = list_prop.sweep_foreign_format_rows()
                except Exception as e:
                    logger.error(
                        f"actor={actor_id} list={name}: sweeping leftover v1 "
                        f"rows failed: {e}"
                    )
                    errored += 1
                    continue
                if swept:
                    logger.warning(
                        f"actor={actor_id} list={name}: already v2; swept "
                        f"{swept} v1 row(s) left by an interrupted migration"
                    )
            continue

        checked += 1

        if "#" in name:
            refused.append((f"{actor_id}/{name}", "rename required"))
            logger.warning(
                f"actor={actor_id} list={name}: REFUSED -- name contains "
                f"'#', rename before migrating; keeps working as v1"
            )
            continue

        if not migrate:
            report = list_prop.verify(identity_key=identity_key)
            # Holes and orphans first: migration closes them, and unlike
            # duplicates they leave nothing behind for a later verify() to
            # find. A dry run that mentions only duplicates is how an
            # operator gets a clean-looking report over damaged data and
            # migrates it away without ever seeing it.
            if report["missing_indices"] or report["orphan_indices"]:
                if not allow_damaged:
                    refused.append((f"{actor_id}/{name}", "repair required"))
                    logger.warning(
                        f"actor={actor_id} list={name}: WOULD REFUSE -- "
                        f"missing_indices={report['missing_indices']} "
                        f"orphan_indices={report['orphan_indices']}. "
                        f"Migration closes holes in flight and the damage "
                        f"stops being reportable; repair first with "
                        f"actingweb-verify-property-lists --repair, or pass "
                        f"--migrate-damaged to migrate and accept the loss"
                    )
                    continue
                # --migrate-damaged was passed, so predict what the real
                # run will do rather than refusing: a dry run that reports
                # a refusal the actual migration would not perform is
                # useless as the gate the docs tell operators to use.
                logger.warning(
                    f"actor={actor_id} list={name}: would migrate and CLOSE "
                    f"missing_indices={report['missing_indices']} "
                    f"orphan_indices={report['orphan_indices']} "
                    f"(--migrate-damaged) -- the damage stops being "
                    f"reportable once this runs"
                )
            if report["adjacent_duplicates"]:
                logger.warning(
                    f"actor={actor_id} list={name}: would migrate "
                    f"{report['readable_count']} items with "
                    f"{len(report['adjacent_duplicates'])} duplicate "
                    f"pair(s) preserved as-is"
                )
            for identity, positions in sorted(
                (report.get("duplicate_identities") or {}).items(),
                key=lambda kv: str(kv[0]),
            ):
                logger.warning(
                    f"actor={actor_id} list={name}: would migrate with "
                    f"{identity_key}={identity} duplicated at positions "
                    f"{positions} -- migration preserves both copies"
                )
            migrated += 1
            continue

        try:
            result = list_prop.migrate_to_v2(allow_damaged=allow_damaged)
        except Exception as e:
            logger.error(f"actor={actor_id} list={name}: migrate_to_v2() failed: {e}")
            errored += 1
            continue

        if result["migrated"]:
            migrated += 1
            level = logger.warning if result["had_holes"] else logger.info
            level(
                f"actor={actor_id} list={name}: migrated "
                f"({result['item_count']} items, "
                f"had_holes={result['had_holes']}, "
                f"duplicates={result['duplicate_count']})"
            )
        elif result.get("reason") == "damaged":
            # Only reachable without --migrate-damaged. migrate_to_v2()
            # has already logged the detail; record it as a refusal so the
            # run exits non-zero and the actor stays out of the
            # checkpoint, exactly like a '#'-named list.
            refused.append((f"{actor_id}/{name}", "repair required"))
        elif result.get("reason") == "already_v2":
            # Not a refusal: migrate_to_v2() re-reads the stored format
            # itself, so a list that another request lazily migrated between
            # our verify() above and that read lands here. The list IS in the
            # requested format, which is success -- counting it as refused
            # would fail the run and (since only clean actors are
            # checkpointed) make the sweep re-do this actor forever.
            logger.info(f"actor={actor_id} list={name}: already migrated concurrently")
        elif result.get("reason") == "deleted_concurrently":
            # The list was deleted while we were copying it, and
            # migrate_to_v2() rolled its own writes back. Nothing is left to
            # migrate and nothing needs an operator, so this must not be a
            # refusal: refusing would fail the run and keep the actor out of
            # the checkpoint forever over a list that no longer exists.
            logger.info(f"actor={actor_id} list={name}: deleted while migrating")
        else:
            # "name_contains_hash" -- needs an operator rename before this
            # list can ever migrate.
            refused.append((f"{actor_id}/{name}", "rename required"))

    return checked, migrated, errored, refused


def downgrade_to_v1(actor_id: str, list_name: str, config: Any) -> dict[str, Any]:
    """EMERGENCY v2 -> v1 converter. See the module docstring's warning --
    this is not a normal operation, has no locking, and is meant for a
    single manual invocation during an incident, not routine use."""
    from actingweb.db import get_property
    from actingweb.property_list import ListProperty

    list_prop = ListProperty(actor_id=actor_id, name=list_name, config=config)
    if list_prop.storage_format() != 2:
        # Reading as v1 is also what a downgrade interrupted between its
        # metadata flip and its v2 cleanup looks like. Re-running is the
        # documented remedy, so finish the cleanup here rather than
        # returning from a state a second run will decline just as fast.
        swept = list_prop.sweep_foreign_format_rows()
        if swept:
            logger.warning(
                f"{actor_id}/{list_name}: already v1; swept {swept} v2 row(s) "
                f"left by an interrupted downgrade"
            )
        return {"downgraded": False, "reason": "not_v2", "swept_v2_rows": swept}

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
    # Phase 12 (thoughts/plans/2026-08-20-v2-positional-access-cost.md):
    # this list has now crossed formats, so sweep_foreign_format_rows()
    # can no longer skip its range query on the strength of this metadata.
    meta["format_ever_changed"] = True
    save_db = get_property(config)
    if not save_db.set(
        actor_id=actor_id, name=f"list:{list_name}-meta", value=json.dumps(meta)
    ):
        raise RuntimeError(f"list metadata write failed for '{list_name}'")

    # Delete the v2 rows. Go through _v2_item_names_in_range() rather than
    # reading the byte range directly: the range alone also covers a legacy
    # '#'-named sibling list's rows (a list named "foo-#bar" stores
    # "list:foo-#bar-0", which sorts inside list "foo"'s bounds), and this
    # loop deletes everything it is handed. The helper applies the rank-shape
    # filter that keeps the two apart.
    v2_rows = list_prop._v2_item_names_in_range()  # noqa: SLF001 -- emergency tool
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
        "--identity-key",
        default=None,
        help=(
            "field name identifying an item (e.g. 'id'). The dry run's "
            "duplicate warning otherwise compares raw stored bytes, which "
            "misses a duplicate whose copies have been edited since, and "
            "only looks at neighbouring rows"
        ),
    )
    parser.add_argument(
        "--migrate-damaged",
        action="store_true",
        help=(
            "also migrate lists with holes or orphans, CLOSING them: the "
            "lost items stay lost and stop being reported (default: refuse "
            "them and report a repair is needed)"
        ),
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

    _log_target(config, "MIGRATE" if args.migrate else "dry-run", args.rps)

    if args.migrate_damaged:
        logger.warning(
            "--migrate-damaged: lists with holes or orphans WILL be "
            "migrated. Migration renumbers the survivors, so the damage is "
            "closed and stops being reportable -- the migrated lists verify "
            "healthy afterwards with no record of what went missing."
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
    total_refused: list[tuple[str, str]] = []
    actors_swept = 0

    for actor in actors:
        actor_id = actor.get("id") if isinstance(actor, dict) else None
        if not actor_id or checkpoint.is_done(actor_id):
            continue
        checked, migrated, errored, refused = migrate_actor(
            actor_id,
            config,
            args.migrate,
            limiter,
            args.identity_key,
            args.migrate_damaged,
        )
        total_checked += checked
        total_migrated += migrated
        total_errored += errored
        total_refused.extend(refused)
        actors_swept += 1
        # Only checkpoint an actor whose lists ALL came through cleanly.
        # Marking a partially-failed actor done would let the next run skip
        # it, observe zero new errors, delete the checkpoint and exit 0 --
        # reporting success over lists that were never migrated. A refused
        # ('#'-named) list needs an operator rename, so such an actor is
        # deliberately re-reported on every run until that happens.
        if not errored and not refused:
            checkpoint.mark_done(actor_id)

    logger.info(
        f"Summary: actors_swept={actors_swept} v1_lists_checked={total_checked} "
        f"{'migrated' if args.migrate else 'would_migrate'}={total_migrated} "
        f"refused={len(total_refused)} errors={total_errored}"
    )
    for name, reason in total_refused:
        logger.warning(
            f"{'REFUSED' if args.migrate else 'WOULD REFUSE'} ({reason}): {name}"
        )
    if not args.migrate and total_checked:
        logger.info("Re-run with --migrate to perform the migration.")
    if args.migrate and not total_refused and not total_errored:
        if os.path.exists(args.checkpoint_file):
            os.unlink(args.checkpoint_file)

    return 1 if (total_refused or total_errored) else 0


if __name__ == "__main__":
    sys.exit(main())
