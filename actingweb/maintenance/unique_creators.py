#!/usr/bin/env python3
"""
Find and resolve duplicate creators, and turn creator uniqueness on or off.

``with_unique_creator()`` makes the database hold one actor per creator: a
``creators`` table on DynamoDB, the partial unique index ``ux_actors_creator``
on PostgreSQL. Neither can be switched on while actors already share a
creator, and the application refuses to start with the flag on until this
command has run ``enable``. Run it with the SAME environment as the
application (``DATABASE_BACKEND``, the database settings, ``AWS_DB_PREFIX``,
credentials)::

    actingweb-unique-creators report
    actingweb-unique-creators resolve            # dry run: prints decisions
    actingweb-unique-creators resolve --apply
    actingweb-unique-creators enable --apply
    actingweb-unique-creators disable --apply    # the rollback

Rollout order for a deployment turning the flag on: ``report``; ``resolve``,
then ``resolve --apply``; ``enable --apply``; deploy with the flag on;
``enable --apply`` again (it picks up actors old processes created during
the deploy); ``report``.

Subcommands:

- ``report [--creator X]``: groups of actors sharing a creator (exact, and
  ``@`` addresses that differ only by case), actors already renamed by
  ``resolve`` (``#dup-``), and on DynamoDB ``creators`` records whose actor is
  missing or holds another creator, and (once enabled) actors with no record;
  each of these is confirmed by a consistent read of the actor or record, so
  an actor created or renamed during the scan is not listed.
  Also ``@`` addresses stored with capitals: lookups use the lowercase value,
  so such an actor would not be found once the flag is on.
- ``resolve [--apply] [--keep ID]``: keeps one actor per group and renames the
  others to ``{creator}#dup-{hash}``, clearing their stored ``email`` so the
  ``force_email_prop_as_creator`` rewrite cannot undo the rename. No user data
  is deleted. The kept actor is the best by marker (vouched, then unvouched,
  then ``factory``), then the oldest (PostgreSQL's ``created_at``; on DynamoDB
  the ``created_at`` the OAuth path stores, unknown ages last), then the lowest
  id. ``--keep`` overrides the rule for its group. A group with an actor whose
  marker cannot be read is skipped and reported. On DynamoDB a record naming
  a renamed actor moves to the kept actor, and a stale record is removed
  only once a consistent read confirms it (safe against live traffic). It
  also lowercases addresses stored with capitals. A renamed actor no longer opens
  with its old creator (basic auth, OAuth): swap which actor is kept with
  ``--keep``.
- ``enable [--apply]``: refuses while duplicates, orphaned records or
  addresses stored with capitals remain. DynamoDB: scans consistently,
  creates the ``creators`` table, re-reads each actor consistently and writes
  its record (a record naming the same actor counts as done; a record naming
  another actor is listed and the run goes on), then, if nothing was listed,
  the backfill-complete item. ``--creator`` is refused.
  PostgreSQL: builds ``ux_actors_creator``
  ``CONCURRENTLY`` on a separate autocommit connection, dropping an INVALID
  one a failed run left, and checks it is valid. Re-running is safe.
- ``disable [--apply]``: PostgreSQL drops the index; DynamoDB deletes every
  record and the backfill-complete item, so a later ``enable`` starts from
  the actors, not from records that went stale while the flag was off (the
  empty table can be dropped by hand). Run it only after every process with
  the flag on has stopped; re-running finishes a partial run.


``resolve``, ``enable`` and ``disable`` only print what they would do unless
``--apply`` is given.

Output: one ``key=value`` summary line per run, after one line per decision.

Exit codes: 0 = clean (or done); 1 = duplicates, orphans or skipped groups
found, or ``enable`` refused; 2 = the store could not be read or written, or
an argument was refused.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from actingweb.db.creator_rules import (
    BACKFILL_KEY,
    DUP_MARKER,
    UNIQUE_INDEX_NAME,
    UNIQUE_INDEX_PREDICATE,
    dup_value,
    is_exempt,
    normalise_creator,
)
from actingweb.db.exceptions import DbError

logger = logging.getLogger("unique_creators")

RANK = {"vouched": 0, "unvouched": 1, "replace": 2}


class StoreUnavailable(RuntimeError):
    """The store could not be read or written; the run stopped."""


@dataclass
class Report:
    """What ``report`` found."""

    scanned: int = 0
    # creator -> ids sharing it exactly
    exact: dict[str, list[str]] = field(default_factory=dict)
    # lower(creator) -> ids whose creators differ only by case
    case_only: dict[str, list[str]] = field(default_factory=dict)
    dup_actors: list[str] = field(default_factory=list)
    # DynamoDB: (creator, actor_id, "missing" | "mismatch")
    orphans: list[tuple[str, str, str]] = field(default_factory=list)
    # DynamoDB, once enabled: (actor_id, creator) with no record
    unrecorded: list[tuple[str, str]] = field(default_factory=list)
    # (actor_id, creator): an @ address stored with capitals, in no group
    unnormalised: list[tuple[str, str]] = field(default_factory=list)
    creators: dict[str, str] = field(default_factory=dict)  # id -> creator

    @property
    def groups(self) -> dict[str, list[str]]:
        """Every group ``resolve`` acts on: exact and case-only, keyed by the
        lowercased value for ``@`` addresses."""
        merged: dict[str, set[str]] = {}
        for creator, ids in self.exact.items():
            merged.setdefault(normalise_creator(creator), set()).update(ids)
        for key, ids in self.case_only.items():
            merged.setdefault(key, set()).update(ids)
        return {k: sorted(v) for k, v in sorted(merged.items())}

    @property
    def clean(self) -> bool:
        return not (
            self.exact
            or self.case_only
            or self.orphans
            or self.unrecorded
            or self.unnormalised
        )


def make_config() -> Any:
    """The command's own config: the application's backend, and no
    ``force_email_prop_as_creator`` rewrite while it reads actors.

    ``unique_creator`` stays off here: the command writes the DynamoDB
    records itself (``enable``), and a ``#dup-`` value is never recorded, so
    ``resolve``'s renames are plain creator changes (the PostgreSQL index,
    when it exists, still checks them). They then work before ``enable``,
    with no ``creators`` table yet, and after it, leaving the kept actor's
    record alone.
    """
    from actingweb.config import Config

    return Config(
        database=os.getenv("DATABASE_BACKEND", "dynamodb"),
        unique_creator=False,
        force_email_prop_as_creator=False,
    )


def _wanted(creator: str | None, only: str | None) -> bool:
    if only is None:
        return True
    return normalise_creator(creator).lower() == normalise_creator(only).lower()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _dynamodb_actor_rows(
    *, rate_limit: float | None, consistent: bool
) -> Iterator[tuple[str, str]]:
    from actingweb.db.dynamodb.actor import Actor

    for row in Actor.scan(
        attributes_to_get=["id", "creator"],
        rate_limit=rate_limit,
        consistent_read=consistent,
    ):
        yield str(row.id), str(row.creator or "")


def _postgresql_collect(only: str | None, report: Report) -> None:
    """Exact groups, case-only groups and ``#dup-`` actors, grouped by the
    database rather than in memory; only their creators are loaded."""
    from actingweb.db.postgresql.connection import get_connection

    exact: dict[str, list[str]] = {}
    case_only: dict[str, list[str]] = {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM actors")
            count_row = cur.fetchone()
            report.scanned = int(count_row[0]) if count_row else 0
            cur.execute(
                "SELECT creator, array_agg(id ORDER BY id) FROM actors "
                f"WHERE {UNIQUE_INDEX_PREDICATE} "
                "GROUP BY creator HAVING count(*) > 1"
            )
            for creator, ids in cur.fetchall():
                if _wanted(creator, only):
                    exact[str(creator)] = [str(i) for i in ids]
            # Provider ids never go through lower(): only @ values.
            cur.execute(
                "SELECT lower(creator), array_agg(id ORDER BY id) FROM actors "
                f"WHERE position('@' in creator) > 0 AND {UNIQUE_INDEX_PREDICATE} "
                "GROUP BY lower(creator) HAVING count(DISTINCT creator) > 1"
            )
            for key, ids in cur.fetchall():
                if _wanted(key, only):
                    case_only[str(key)] = [str(i) for i in ids]
            cur.execute(
                "SELECT id FROM actors WHERE position(%s in creator) > 0 ORDER BY id",
                (DUP_MARKER,),
            )
            report.dup_actors = [str(r[0]) for r in cur.fetchall()]
            report.exact, report.case_only = exact, case_only
            ids = sorted(
                {i for g in (*exact.values(), *case_only.values()) for i in g}
                | set(report.dup_actors)
            )
            cur.execute(
                "SELECT id, creator FROM actors WHERE id = ANY(%s)", (ids or [""],)
            )
            report.creators = {str(r[0]): str(r[1] or "") for r in cur.fetchall()}
            cur.execute(
                "SELECT id, creator FROM actors WHERE position('@' in creator) > 0 "
                "AND creator <> lower(creator) ORDER BY id"
            )
            grouped = {i for g in report.groups.values() for i in g}
            report.unnormalised = [
                (str(i), str(c))
                for i, c in cur.fetchall()
                if str(i) not in grouped and _wanted(c, only)
            ]


def _group_in_memory(rows: dict[str, str], only: str | None, report: Report) -> None:
    by_value: dict[str, list[str]] = {}
    by_lower: dict[str, dict[str, list[str]]] = {}
    for actor_id, creator in rows.items():
        if DUP_MARKER in creator:
            report.dup_actors.append(actor_id)
            continue
        if is_exempt(creator) or not _wanted(creator, only):
            continue
        by_value.setdefault(creator, []).append(actor_id)
        if "@" in creator:
            by_lower.setdefault(creator.lower(), {}).setdefault(creator, []).append(
                actor_id
            )
    report.exact = {c: sorted(i) for c, i in sorted(by_value.items()) if len(i) > 1}
    report.case_only = {
        k: sorted(i for ids in v.values() for i in ids)
        for k, v in sorted(by_lower.items())
        if len(v) > 1
    }
    report.dup_actors.sort()
    grouped = {i for g in report.groups.values() for i in g}
    report.unnormalised = sorted(
        (i, c)
        for i, c in rows.items()
        if DUP_MARKER not in c
        and c != normalise_creator(c)
        and i not in grouped
        and _wanted(c, only)
    )


def backfill_complete() -> bool:
    """Whether the DynamoDB backfill-complete item exists (False when the
    table does not). Raises on a read fault."""
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.creator import Creator

    if not Creator.exists():
        return False
    try:
        Creator.get(BACKFILL_KEY, consistent_read=True)
    except DoesNotExist:
        return False
    return True


def _dynamodb_records(
    *, rate_limit: float | None, consistent: bool
) -> Iterator[tuple[str, str]]:
    from actingweb.db.dynamodb.creator import Creator

    if not Creator.exists():
        return
    for record in Creator.scan(rate_limit=rate_limit, consistent_read=consistent):
        if record.creator == BACKFILL_KEY:
            continue
        yield str(record.creator), str(record.actor_id or "")


def _record_problem(creator: str, actor_id: str) -> str | None:
    """Why the record ``creator → actor_id`` is stale on a consistent read of
    the actor (``"missing"`` or ``"mismatch"``), or None when it is true."""
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.actor import Actor

    try:
        row = Actor.get(actor_id, consistent_read=True)
    except DoesNotExist:
        return "missing"
    return None if normalise_creator(row.creator) == creator else "mismatch"


def _unrecorded_now(creator: str, actor_id: str) -> bool:
    """Whether the actor still lacks its record on a consistent read (one
    created after the record scan has it)."""
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.creator import Creator

    try:
        return Creator.get(creator, consistent_read=True).actor_id != actor_id
    except DoesNotExist:
        return True


def collect(
    config: Any,
    *,
    only: str | None = None,
    rate_limit: float | None = None,
    consistent: bool = False,
) -> Report:
    """Read the store and return what it holds. Raises ``StoreUnavailable``."""
    report = Report()
    try:
        if config.database == "postgresql":
            _postgresql_collect(only, report)
            return report
        from actingweb.db.dynamodb.actor import Actor

        if not Actor.exists():
            # A wrong AWS_DB_PREFIX must not read as an empty, clean store.
            raise StoreUnavailable(
                f"the actor table {Actor.Meta.table_name} does not exist "
                "(check AWS_DB_PREFIX)"
            )
        report.creators = dict(
            _dynamodb_actor_rows(rate_limit=rate_limit, consistent=consistent)
        )
        report.scanned = len(report.creators)
        _group_in_memory(report.creators, only, report)
        recorded: set[str] = set()
        for creator, actor_id in _dynamodb_records(
            rate_limit=rate_limit, consistent=consistent
        ):
            if not _wanted(creator, only):
                continue
            recorded.add(actor_id)
            held = report.creators.get(actor_id)
            if held is not None and normalise_creator(held) == creator:
                continue
            # The two scans can disagree with no damage at all (an actor
            # created or renamed between them): confirm on the row itself.
            why = _record_problem(creator, actor_id)
            if why is not None:
                report.orphans.append((creator, actor_id, why))
        if backfill_complete():
            report.unrecorded = sorted(
                (i, c)
                for i, c in report.creators.items()
                if not is_exempt(c)
                and DUP_MARKER not in c
                and i not in recorded
                and _wanted(c, only)
                and _unrecorded_now(normalise_creator(c), i)
            )
    except StoreUnavailable:
        raise
    except Exception as e:  # folds DbError: becomes StoreUnavailable (exit 2)
        raise StoreUnavailable(f"the store could not be read: {e}") from e
    return report


def print_report(report: Report) -> None:
    for creator, ids in report.exact.items():
        logger.info(f"duplicate creator={creator!r} ids={','.join(ids)}")
    for key, ids in report.case_only.items():
        logger.info(f"case-only duplicate creator={key!r} ids={','.join(ids)}")
    for actor_id in report.dup_actors:
        logger.info(
            f"renamed actor id={actor_id} creator={report.creators.get(actor_id)!r}"
        )
    for creator, actor_id, why in report.orphans:
        logger.info(f"orphaned record creator={creator!r} actor={actor_id} ({why})")
    for actor_id, creator in report.unnormalised:
        logger.info(
            f"address with capitals id={actor_id} creator={creator!r} "
            "(resolve --apply lowercases it)"
        )
    for actor_id, creator in report.unrecorded:
        logger.info(
            f"unrecorded actor id={actor_id} creator={creator!r} "
            "(run enable --apply again)"
        )
    logger.info(
        f"scanned={report.scanned} exact_groups={len(report.exact)} "
        f"case_groups={len(report.case_only)} renamed={len(report.dup_actors)} "
        f"orphans={len(report.orphans)} unrecorded={len(report.unrecorded)} "
        f"capitals={len(report.unnormalised)}"
    )


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


def _created_at(config: Any, actor_id: str) -> float | None:
    """When the actor was created, if the store records it."""
    if config.database == "postgresql":
        from actingweb.db.postgresql.connection import get_connection

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT created_at FROM actors WHERE id = %s", (actor_id,))
                row = cur.fetchone()
        return row[0].timestamp() if row and row[0] else None
    from actingweb.attribute import InternalStore

    store = InternalStore(actor_id=actor_id, config=config)
    value = store.created_at if store.loaded else None
    try:
        return float(value) if value else None
    except (TypeError, ValueError):
        return None


def choose_keep(
    config: Any, ids: list[str], keep: str | None = None
) -> tuple[str, str] | None:
    """The id to keep in a group and why; None when a marker is unreadable.

    Raises ``DbError`` when an age cannot be read.
    """
    from actingweb.oauth2 import classify_marker

    if keep is not None and keep in ids:
        return keep, "--keep"
    ranked: list[tuple[int, bool, float, str]] = []
    for actor_id in ids:
        marker = classify_marker(config, actor_id)
        if marker is None:
            return None
        created = _created_at(config, actor_id)
        ranked.append(
            (RANK[marker], created is None, created or 0.0, actor_id),
        )
    ranked.sort()
    best = ranked[0]
    if len(ranked) > 1 and ranked[1][0] == best[0]:
        runner = ranked[1]
        decided = "age" if (runner[1], runner[2]) != (best[1], best[2]) else "lowest id"
        kind = {0: "vouched", 1: "unvouched", 2: "factory"}[best[0]]
        return best[3], f"{kind}, {decided} decided"
    return best[3], {0: "vouched", 1: "unvouched", 2: "factory"}[best[0]]


def _rename(config: Any, actor_id: str, target: str) -> bool:
    """Rename one actor's creator. Moving it to another value (a ``#dup-``
    rename) also clears its stored email; only lowercasing keeps it. The
    record is settled for the whole group first (:func:`_settle_record`).
    """
    from actingweb.actor import Actor
    from actingweb.db import get_actor

    # Each listed row re-read consistently: the index can still list an
    # actor just renamed away from the target (the losers of a case group).
    held = get_actor(config).get_by_creator(creator=target, consistent=True)
    rows = held if isinstance(held, list) else []
    if any(r.get("id") != actor_id and r.get("creator") == target for r in rows):
        logger.error(f"rename target {target!r} for {actor_id} is taken; skipped")
        return False
    actor = Actor(config=config)
    if not actor.get(actor_id=actor_id) or not actor.store:
        logger.error(f"actor {actor_id} is gone; skipped")
        return False
    old = actor.creator or ""
    if not actor.modify(creator=target):
        logger.error(f"rename of {actor_id} did not land; skipped")
        return False
    if normalise_creator(old) == target:
        return True  # lowercased only: same address, same record
    if actor.store.email is not None and not actor.store.set_confirmed("email", None):
        logger.error(f"renamed {actor_id} but its stored email could not be cleared")
        return False
    return True


def _repair_record(creator: str, actor_id: str) -> bool:
    """Delete a stale DynamoDB record, only if a consistent read still shows
    its actor gone or holding another creator (a live actor listed through
    scan skew keeps it). True when deleted."""
    from actingweb.db.dynamodb.actor import release_stale_record

    return release_stale_record(creator, actor_id)


def _settle_record(key: str, kept: str, ids: list[str]) -> str:
    """Before a group's renames: make the record of ``key`` name the kept
    actor, so a sign-in during the renames loads it (amended rule 2 of the
    invariant audit). A record naming one of the group is moved, and so is
    a stale record naming another actor (in one step with its check); a
    missing one is written. Each write commits only while the kept actor is as read
    (rule 9).

    Returns ``"settled"`` (the record names the kept actor), ``"skip"``
    (no ``creators`` table yet, or the kept actor no longer holds ``key``:
    the renames go ahead and the old fallback runs after them) or
    ``"conflict"`` (another live actor holds the record, or something
    changed meanwhile: renaming now could leave a sign-in a gap, so the
    group is skipped and counted).
    """
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.actor import (
        Actor,
        move_stale_record,
        record_for_actor_as_read,
    )
    from actingweb.db.dynamodb.creator import Creator

    if not Creator.exists():
        return "skip"  # before enable: it writes the records
    try:
        kept_row = Actor.get(kept, consistent_read=True)
    except DoesNotExist:
        kept_row = None
    if kept_row is None or normalise_creator(kept_row.creator) != key:
        return "skip"
    try:
        named: str | None = Creator.get(key, consistent_read=True).actor_id or ""
    except DoesNotExist:
        named = None
    if named == kept:
        return "settled"
    if named is not None and named not in ids:
        # Moved in one step: a release and then a write would leave a sign-in
        # in between no record, and it would create another actor.
        if not move_stale_record(key, named, kept_row):
            logger.error(
                f"the record of {key!r} names {named}, a live holder outside "
                "the group, or it changed; run report again"
            )
            return "conflict"
        logger.info(f"moved the stale record of {key!r} from {named} to {kept}")
        return "settled"
    if not record_for_actor_as_read(key, kept_row, moving_from=named):
        logger.error(f"the record of {key!r} or actor {kept} changed; run again")
        return "conflict"
    if named is None:
        logger.info(f"wrote the record of {key!r} for {kept}")
    else:
        logger.info(f"moved the record of {key!r} from {named} to {kept}")
    return "settled"


def _release_losers_record(key: str, kept: str, ids: list[str]) -> None:
    """After the renames of a group whose record could not be settled: a
    record still naming one of the renamed actors is removed as stale."""
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.actor import release_stale_record
    from actingweb.db.dynamodb.creator import Creator

    if not Creator.exists():
        return
    try:
        named = Creator.get(key, consistent_read=True).actor_id or ""
    except DoesNotExist:
        return
    if named and named != kept and named in ids:
        release_stale_record(key, named)


def resolve(
    config: Any,
    report: Report,
    *,
    apply: bool = False,
    keep: str | None = None,
) -> dict[str, int]:
    """Keep one actor per group and rename the others; repair orphans."""
    counts = {"groups": 0, "renamed": 0, "skipped": 0, "repaired": 0, "errors": 0}
    prefix = "" if apply else "[dry-run] "
    for key, ids in report.groups.items():
        counts["groups"] += 1
        try:
            picked = choose_keep(config, ids, keep)
        except DbError as e:  # folds DbError: the group is skipped, exit 1
            logger.error(f"group {key!r}: an age could not be read ({e}); skipped")
            counts["skipped"] += 1
            continue
        if picked is None:
            logger.error(
                f"group {key!r} ids={','.join(ids)}: a marker could not be "
                "read; skipped"
            )
            counts["skipped"] += 1
            continue
        kept, why = picked
        logger.info(f"{prefix}keep creator={key!r} id={kept} ({why})")
        settled = "skip"
        if apply and config.database != "postgresql":
            try:
                settled = _settle_record(key, kept, ids)
            except Exception as e:  # folds DbError: the group is skipped, exit 1
                logger.error(f"the record of {key!r} could not be settled: {e}")
                settled = "conflict"
            if settled == "conflict":
                # Renaming with the record unsettled lets a sign-in create a
                # third actor beside the kept one.
                counts["errors"] += 1
                continue
        for actor_id in ids:
            if actor_id == kept:
                continue
            target = dup_value(
                normalise_creator(report.creators.get(actor_id, key)), actor_id
            )
            logger.info(f"{prefix}rename id={actor_id} to={target!r}")
            if not apply:
                counts["renamed"] += 1
                continue
            try:
                if _rename(config, actor_id, target):
                    counts["renamed"] += 1
                else:
                    counts["errors"] += 1
            except Exception as e:  # folds DbError: counted as error, exit 1
                logger.error(f"rename of {actor_id} failed: {e}")
                counts["errors"] += 1
        kept_creator = report.creators.get(kept, key)
        if apply and kept_creator != normalise_creator(kept_creator):
            # A case-only group, after the others gave up the lowercase
            # value: the record and the index then match lookups.
            try:
                if not _rename(config, kept, normalise_creator(kept_creator)):
                    counts["errors"] += 1
            except Exception as e:  # folds DbError: counted as error, exit 1
                logger.error(f"lowercasing {kept} failed: {e}")
                counts["errors"] += 1
        if apply and config.database != "postgresql" and settled == "skip":
            try:
                _release_losers_record(key, kept, ids)
            except Exception as e:  # folds DbError: counted as error, exit 1
                logger.error(f"the record of {key!r} could not be released: {e}")
                counts["errors"] += 1
    for actor_id, creator in report.unnormalised:
        target = normalise_creator(creator)
        logger.info(f"{prefix}lowercase id={actor_id} to={target!r}")
        if not apply:
            continue
        try:
            if not _rename(config, actor_id, target):
                counts["errors"] += 1
        except Exception as e:  # folds DbError: counted as error, exit 1
            logger.error(f"lowercasing {actor_id} failed: {e}")
            counts["errors"] += 1
    for creator, actor_id, why in report.orphans:
        logger.info(f"{prefix}remove orphaned record creator={creator!r} ({why})")
        if not apply:
            counts["repaired"] += 1
            continue
        try:
            repaired = _repair_record(creator, actor_id)
        except Exception as e:  # folds DbError: counted as error, exit 1
            logger.error(f"the record of {creator!r} could not be removed: {e}")
            counts["errors"] += 1
            continue
        if not repaired:
            logger.info(f"kept the record of {creator!r}: it is true now")
            continue
        counts["repaired"] += 1
        try:
            # A live actor holding the address without a record would
            # otherwise wait for the next enable, and a sign-in in between
            # creates a second actor.
            _record_lone_holder(config, creator, report)
        except Exception as e:  # folds DbError: counted as error, exit 1
            logger.error(
                f"removed the record of {creator!r}, but its holder's record "
                f"could not be written: {e}; run enable --apply"
            )
            counts["errors"] += 1
    return counts


def _record_lone_holder(config: Any, key: str, report: Report) -> None:
    """Write the record of ``key`` for its one holder, if exactly one actor
    holds it now (read consistently) and the record is absent; rule 9.

    Candidates are the scan's actors with that creator, the same run's
    renames included (``collect`` saw their old value, which normalises to
    ``key``), plus what the creator index lists: the index lags, and alone
    it misses an actor renamed to the key a moment ago.
    """
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db import get_actor
    from actingweb.db.dynamodb.actor import Actor, record_for_actor_as_read

    key = normalise_creator(key)
    listed = get_actor(config).get_by_creator(creator=key, consistent=True) or []
    rows: list[dict[str, Any]] = [listed] if isinstance(listed, dict) else listed
    candidates = {str(r["id"]) for r in rows if r and r.get("id")}
    candidates |= {i for i, c in report.creators.items() if normalise_creator(c) == key}
    holders: list[Any] = []
    for actor_id in sorted(candidates):
        try:
            current = Actor.get(actor_id, consistent_read=True)
        except DoesNotExist:
            continue
        if normalise_creator(current.creator) == key:
            holders.append(current)
    if len(holders) != 1:
        if not holders:
            logger.info(f"no actor holds {key!r} now; its record stays absent")
        return  # none, or a group: report and resolve settle it
    if record_for_actor_as_read(key, holders[0]):
        logger.info(f"wrote the record of {key!r} for {holders[0].id}")


# ---------------------------------------------------------------------------
# enable / disable
# ---------------------------------------------------------------------------


def _pg_admin_connection() -> Any:
    """An autocommit connection outside the pool (``CONCURRENTLY`` cannot
    run in a transaction, and must not hold a pooled connection for its
    whole build)."""
    import psycopg

    from actingweb.db.postgresql.connection import get_connection_string

    return psycopg.connect(get_connection_string(), autocommit=True)


def postgresql_index_state() -> str:
    """``"valid"``, ``"invalid"`` or ``"missing"``. Raises on a fault."""
    from actingweb.db.postgresql.connection import get_connection, get_schema_name

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relname = %s AND n.nspname = %s",
                (UNIQUE_INDEX_NAME, get_schema_name()),
            )
            row = cur.fetchone()
    if not row:
        return "missing"
    return "valid" if row[0] else "invalid"


def _enable_postgresql(apply: bool, lock_timeout: str) -> str:
    from psycopg import sql

    from actingweb.db.postgresql.connection import get_schema_name

    state = postgresql_index_state()
    if state == "valid":
        logger.info(f"{UNIQUE_INDEX_NAME} exists and is valid; nothing to do")
        return "present"
    if not apply:
        logger.info(
            f"[dry-run] would build {UNIQUE_INDEX_NAME} CONCURRENTLY"
            + (" after dropping the INVALID one" if state == "invalid" else "")
        )
        return "would-build"
    schema = get_schema_name()
    index = sql.Identifier(schema, UNIQUE_INDEX_NAME)
    with _pg_admin_connection() as conn:
        conn.execute("SET statement_timeout = 0")
        conn.execute(sql.SQL("SET lock_timeout = {}").format(sql.Literal(lock_timeout)))
        if state == "invalid":
            logger.info(f"dropping the INVALID {UNIQUE_INDEX_NAME} a failed run left")
            conn.execute(sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(index))
        conn.execute(
            sql.SQL(
                "CREATE UNIQUE INDEX CONCURRENTLY {} ON {} (creator) WHERE "
                + UNIQUE_INDEX_PREDICATE
            ).format(
                sql.Identifier(UNIQUE_INDEX_NAME), sql.Identifier(schema, "actors")
            )
        )
    if postgresql_index_state() != "valid":
        raise StoreUnavailable(f"{UNIQUE_INDEX_NAME} was built but is not valid")
    logger.info(f"built {UNIQUE_INDEX_NAME}")
    return "built"


def _enable_dynamodb(config: Any, report: Report, apply: bool) -> tuple[str, int]:
    """Backfill the ``creators`` table. Returns the outcome and the number
    of records written (or that would be)."""
    from pynamodb.exceptions import DoesNotExist

    from actingweb.db.dynamodb.actor import Actor, record_for_actor_as_read
    from actingweb.db.dynamodb.creator import Creator

    pending = sorted(
        (normalise_creator(c), i)
        for i, c in report.creators.items()
        if not is_exempt(c) and DUP_MARKER not in c
    )
    if not apply:
        logger.info(f"[dry-run] would write up to {len(pending)} creator records")
        return "would-backfill", len(pending)
    if not Creator.exists():
        Creator.create_table(wait=True)
    written = 0
    collisions = 0
    for creator, actor_id in pending:
        # Re-read consistently: live traffic may have renamed or deleted the
        # actor since the scan, and a record written from the scan would
        # then name the wrong actor or a missing one.
        try:
            current = Actor.get(actor_id, consistent_read=True)
        except DoesNotExist:
            continue
        if normalise_creator(current.creator) != creator:
            continue  # renamed since the scan; its own write recorded it

        # Committed only while the actor is as just read (rule 9): a rename
        # or delete in between would leave the record stale.
        if record_for_actor_as_read(creator, current):
            written += 1
        else:
            # Which condition failed, confirmed by reads: the actor changed
            # (its own write recorded it), or the record exists.
            try:
                current = Actor.get(actor_id, consistent_read=True)
            except DoesNotExist:
                continue
            if normalise_creator(current.creator) != creator:
                continue
            try:
                holder = Creator.get(creator, consistent_read=True).actor_id
            except DoesNotExist:
                holder = None
            if holder != actor_id:
                # Two actors with this creator (a replacement in flight, or
                # a duplicate an old process made): listed, and the run goes
                # on; report and resolve --apply settle it.
                logger.error(
                    f"creator {creator!r} of {actor_id} is recorded for {holder}; "
                    "run report and resolve --apply, then enable again"
                )
                collisions += 1
    if collisions:
        logger.error(
            f"wrote {written} creator records; {collisions} collisions, so the "
            "backfill-complete item was not written"
        )
        return "collision", written
    Creator(creator=BACKFILL_KEY).save()
    logger.info(f"wrote {written} creator records and the backfill-complete item")
    return "backfilled", written


def enable(
    config: Any, report: Report, *, apply: bool = False, lock_timeout: str = "10s"
) -> str:
    """Turn enforcement on in the store. Returns the outcome; ``"refused"``
    while duplicates remain."""
    if report.exact or report.case_only or report.orphans or report.unnormalised:
        logger.error(
            f"{len(report.exact)} exact and {len(report.case_only)} case-only "
            f"duplicate groups, {len(report.orphans)} orphaned records and "
            f"{len(report.unnormalised)} addresses with capitals remain; run "
            "resolve --apply first"
        )
        return "refused"
    try:
        if config.database == "postgresql":
            return _enable_postgresql(apply, lock_timeout)
        outcome, _ = _enable_dynamodb(config, report, apply)
        return outcome
    except StoreUnavailable:
        raise
    except Exception as e:  # folds DbError: becomes StoreUnavailable (exit 2)
        raise StoreUnavailable(f"enable failed: {e}") from e


def disable(config: Any, *, apply: bool = False) -> str:
    """Turn enforcement off in the store (the application's flag first)."""
    try:
        if config.database == "postgresql":
            from psycopg import sql

            from actingweb.db.postgresql.connection import get_schema_name

            if postgresql_index_state() == "missing":
                logger.info(f"{UNIQUE_INDEX_NAME} does not exist; nothing to do")
                return "absent"
            if not apply:
                logger.info(f"[dry-run] would drop {UNIQUE_INDEX_NAME}")
                return "would-drop"
            with _pg_admin_connection() as conn:
                conn.execute(
                    sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(
                        sql.Identifier(get_schema_name(), UNIQUE_INDEX_NAME)
                    )
                )
            logger.info(f"dropped {UNIQUE_INDEX_NAME}")
            return "dropped"
        from actingweb.db.dynamodb.creator import Creator

        if not Creator.exists():
            logger.info(f"{Creator.Meta.table_name} does not exist; nothing to do")
            return "absent"
        if not apply:
            logger.info(
                "[dry-run] would delete every creator record and the "
                "backfill-complete item"
            )
            return "would-drop"
        # Run only once every flag-on process has stopped: one still serving
        # would find no holder for anybody. The marker first (from here the
        # startup check refuses the flag), then every record, since with the
        # flag off deletes and renames no longer keep them and a later
        # enable must start from the actors. Re-running finishes a partial
        # run: deleting a missing item is not an error.
        Creator(creator=BACKFILL_KEY).delete()
        removed = 0
        for record in Creator.scan(attributes_to_get=["creator"]):
            record.delete()
            removed += 1
        if next(iter(Creator.scan(consistent_read=True, limit=1)), None):
            raise StoreUnavailable(
                "records remain after the delete; run disable --apply again"
            )
        logger.info(
            f"deleted the backfill-complete item and {removed} records; the "
            f"empty table ({Creator.Meta.table_name}) can be dropped by hand"
        )
        return "dropped"

    except Exception as e:  # folds DbError: becomes StoreUnavailable (exit 2)
        raise StoreUnavailable(f"disable failed: {e}") from e


# ---------------------------------------------------------------------------
# The startup check
# ---------------------------------------------------------------------------


def missing_enforcement(config: Any) -> str | None:
    """Why enforcement is not in place, or None when it is.

    Definite absence only: the DynamoDB ``creators`` table or its
    backfill-complete item is missing, or the PostgreSQL index is missing or
    INVALID. A fault while probing raises (the caller logs and continues).
    """
    if config.database == "postgresql":
        state = postgresql_index_state()
        if state == "missing":
            return f"the PostgreSQL index {UNIQUE_INDEX_NAME} does not exist"
        if state == "invalid":
            return f"the PostgreSQL index {UNIQUE_INDEX_NAME} is INVALID"
        return None
    from actingweb.db.dynamodb.creator import Creator

    if not Creator.exists():
        return f"the DynamoDB table {Creator.Meta.table_name} does not exist"
    if not backfill_complete():
        return f"the DynamoDB table {Creator.Meta.table_name} is not backfilled"
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="actingweb-unique-creators",
        description=(__doc__ or "").strip().split("\n\n")[0],
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("report", "resolve", "enable", "disable"):
        p = sub.add_parser(name)
        p.add_argument("--creator", default=None, help="only this creator")
        p.add_argument(
            "--rate-limit",
            type=float,
            default=None,
            help="DynamoDB scan: read capacity units per second",
        )
        p.add_argument(
            "--consistent", action="store_true", help="DynamoDB: consistent scans"
        )
        if name != "report":
            p.add_argument("--apply", action="store_true", help="write")
        if name == "resolve":
            p.add_argument("--keep", default=None, help="keep this actor id")
        if name == "enable":
            p.add_argument(
                "--lock-timeout",
                default="10s",
                help="PostgreSQL lock_timeout for the index build",
            )
    args = parser.parse_args(argv)
    if args.command in ("enable", "disable") and args.creator:
        # Both act on the whole store: enable writes the backfill-complete
        # item for every creator, disable deletes every record.
        parser.error(f"--creator is not supported by {args.command}")

    config = make_config()
    if config.database not in ("dynamodb", "postgresql"):
        parser.error(f"unsupported DATABASE_BACKEND={config.database}")
    try:
        return _run(args, parser, config)
    finally:
        if config.database == "postgresql":
            # Before interpreter shutdown, which cannot join the pool's
            # worker threads.
            from actingweb.db.postgresql.connection import close_pool

            close_pool()


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser, config: Any) -> int:
    try:
        if args.command == "disable":
            outcome = disable(config, apply=args.apply)
            logger.info(f"command=disable outcome={outcome}")
            return 0
        report = collect(
            config,
            only=args.creator,
            rate_limit=args.rate_limit,
            # enable writes from what it reads: never from a lagging scan.
            consistent=args.consistent or args.command == "enable",
        )

        if args.command == "report":
            print_report(report)
            return 0 if report.clean else 1
        if args.command == "resolve":
            if args.keep and not any(
                args.keep in ids for ids in report.groups.values()
            ):
                parser.error(f"--keep {args.keep} is in no duplicate group")
            counts = resolve(config, report, apply=args.apply, keep=args.keep)
            logger.info(
                f"command=resolve apply={args.apply} groups={counts['groups']} "
                f"renamed={counts['renamed']} skipped={counts['skipped']} "
                f"repaired={counts['repaired']} errors={counts['errors']}"
            )
            return 1 if counts["skipped"] or counts["errors"] else 0
        outcome = enable(
            config, report, apply=args.apply, lock_timeout=args.lock_timeout
        )
        logger.info(f"command=enable apply={args.apply} outcome={outcome}")
        return 1 if outcome in ("refused", "collision") else 0
    except StoreUnavailable as e:
        logger.error(f"{e}; re-run when the database answers")
        return 2


if __name__ == "__main__":
    sys.exit(main())
