#!/usr/bin/env python3
"""
Mark existing actors as vouched when upgrading to 3.16.

From 3.16 an actor whose ``auth_method`` marker is absent (an actor created
before the upgrade other than by a provider login) or ``"factory"`` is
*unvouched*: the first sign-in that proves its creator's address cleans it in place (absent marker: passphrase
rotated, trusts, subscriptions, sessions and registered OAuth2 clients
removed, data kept) or replaces it (``"factory"``: deleted and recreated with
a new id). Actors created by a provider login before 3.16 already carry
``"<provider>_oauth2"`` and are not touched. If you know the remaining actors
are legitimate, write a marker first and the sign-in leaves them alone.

A marker does not vouch for an actor whose email verification is still
pending (``email_verified == "false"``): proving the address is what that
actor is waiting for. Those are marked, counted as ``pending`` as well, and
stay unvouched until the address is proven.

The tool needs the 3.16 library. Install it, then run this before the
application serves its first sign-in, with the SAME environment as the
application (``DATABASE_BACKEND``, the database settings, ``AWS_DB_PREFIX``,
credentials)::

    actingweb-mark-actors-vouched --dry-run
    actingweb-mark-actors-vouched --marker operator
    actingweb-mark-actors-vouched --creator alice@example.com

Rules:
- Actors with a marker are never touched, except ``"factory"`` ones with
  ``--include-factory`` (a deployment that kept the actor factory open after
  upgrading and wants to vouch for what it created).
- ``--marker`` must be a vouching value; ``factory``, ``email_unverified``,
  ``creator_changed`` and the empty string are refused.
- ``--creator <address>`` restricts the run to actors with that creator.
- ``--start-after <actor id>`` resumes an interrupted run: ids are processed
  in sorted order, and a progress line every 100 actors (and the closing
  line) gives the value. After errors, re-run without it: the errored actors
  sort before that id.
- ``--dry-run`` reports what would be written without writing.
- An actor whose marker cannot be read is an error, never marked: on
  PostgreSQL a read fault looks like "no marker", and marking it could vouch
  for a ``"factory"`` actor. A write is counted only once it reads back.

The actor list is a full scan on both backends: this is maintenance, not a
serving path.

Output: one summary line, ``scanned`` (actors considered), ``marked``
(written, or would be with ``--dry-run``), ``skipped`` (already carry a
marker), ``pending`` (marked, but still waiting for email verification) and
``errors`` (could not be read or written).

Exit codes: 0 = every actor considered was handled; 1 = at least one actor
could not be marked (re-run; marked actors are skipped); 2 = the actor list
itself could not be read, so nothing was scanned -- not a report of zero
actors -- or an argument was refused (a non-vouching ``--marker``; the
message says which).
"""

import argparse
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("mark_actors_vouched")


#: A progress line, with the resume value, every this many actors scanned.
PROGRESS_EVERY = 100


class ActorListUnavailable(RuntimeError):
    """The actor list could not be read; nothing was scanned."""


def _mark_one(
    config: Any,
    actor_id: str,
    *,
    marker: str,
    dry_run: bool,
    include_factory: bool,
    counts: dict[str, int],
    creator: str = "",
) -> None:
    """Mark one actor if it qualifies, counting the outcome. The address
    the marker vouches for (``creator``, from the listing) is recorded
    first, so a rename since the listing leaves the actor unvouched."""
    from actingweb.attribute import InternalStore
    from actingweb.db.creator_rules import normalise_creator
    from actingweb.oauth2 import VOUCHED_CREATOR

    try:
        store = InternalStore(actor_id=actor_id, config=config)
        if not store.loaded:
            counts["errors"] += 1
            logger.error(f"could not read the marker of {actor_id}; not marked")
            return
        current = store.auth_method
        qualifies = not current or (include_factory and current == "factory")
        if not qualifies:
            counts["skipped"] += 1
            return
        if dry_run:
            logger.info(f"[dry-run] would mark {actor_id} ({current!r} -> {marker!r})")
        else:
            if not store.set_confirmed(
                VOUCHED_CREATOR, normalise_creator(creator)
            ) or not store.set_confirmed("auth_method", marker):
                counts["errors"] += 1
                logger.error(f"marker write for {actor_id} did not read back")
                return
            logger.info(f"marked {actor_id} ({current!r} -> {marker!r})")
        counts["marked"] += 1
        if store.email_verified == "false":
            counts["pending"] += 1
            logger.warning(
                f"{actor_id} has a pending email verification and stays "
                "unvouched until the address is proven"
            )
    except Exception as e:  # folds DbError: counted as error, exit 1
        counts["errors"] += 1
        logger.error(f"could not mark {actor_id}: {e}")


def mark_actors(
    config: Any,
    *,
    marker: str = "operator",
    include_factory: bool = False,
    creator: str | None = None,
    start_after: str | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Write ``marker`` on the actors that qualify; return the counts.

    Raises:
        ValueError: ``marker`` does not vouch.
        ActorListUnavailable: the actor list could not be read (PostgreSQL
            answers a fault with ``False``, DynamoDB raises while scanning;
            neither must read as "no actors").
    """
    from actingweb.db import get_actor_list
    from actingweb.oauth2 import UNVOUCHED_AUTH_METHODS

    if not marker or marker in UNVOUCHED_AUTH_METHODS:
        raise ValueError(f"{marker!r} does not vouch for an actor")
    try:
        rows = get_actor_list(config).fetch()
    except Exception as e:  # folds DbError: becomes ActorListUnavailable (exit 2)
        # DynamoDB's scan is lazy: a fault raises while it is iterated.
        raise ActorListUnavailable(f"the actor list could not be read: {e}") from e
    if not isinstance(rows, list):
        raise ActorListUnavailable("the actor list could not be read")
    wanted = creator.lower() if creator and "@" in creator else creator
    counts = {"scanned": 0, "marked": 0, "skipped": 0, "pending": 0, "errors": 0}
    last: str | None = None
    for row in sorted(rows, key=lambda r: r.get("id", "")):
        actor_id = row.get("id")
        if not actor_id:
            continue
        if start_after and actor_id <= start_after:
            continue
        row_creator = row.get("creator") or ""
        if (
            wanted
            and (row_creator.lower() if "@" in row_creator else row_creator) != wanted
        ):
            continue
        counts["scanned"] += 1
        last = actor_id
        _mark_one(
            config,
            actor_id,
            marker=marker,
            dry_run=dry_run,
            include_factory=include_factory,
            counts=counts,
            creator=row_creator,
        )
        # Only once the actor is handled (an interrupt skips this), so
        # resuming after it skips nothing; an interrupted run never reaches
        # the closing line.
        if counts["scanned"] % PROGRESS_EVERY == 0:
            logger.info(
                f"progress: {counts['scanned']} scanned, through {actor_id}"
                + (
                    f" (if interrupted, resume with --start-after {actor_id})"
                    if not counts["errors"]
                    else " (errors so far: re-run without --start-after)"
                )
            )
    if counts["errors"]:
        # Resuming after ``last`` would skip the actors that errored.
        logger.info(
            f"last actor handled: {last}; {counts['errors']} errored, so re-run "
            "without --start-after (marked actors are skipped)"
        )
    elif last:
        logger.info(f"last actor handled: {last} (resume with --start-after {last})")
    return counts


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--marker", default="operator", help="auth_method value to write"
    )
    parser.add_argument("--include-factory", action="store_true")
    parser.add_argument("--creator", default=None)
    parser.add_argument("--start-after", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from actingweb.config import Config

    config = Config(database=os.getenv("DATABASE_BACKEND", "dynamodb"))
    try:
        counts = mark_actors(
            config,
            marker=args.marker,
            include_factory=args.include_factory,
            creator=args.creator,
            start_after=args.start_after,
            dry_run=args.dry_run,
        )
    except ValueError as e:
        parser.error(str(e))
    except ActorListUnavailable as e:
        logger.error(f"{e}; nothing was scanned, re-run when the database answers")
        return 2
    logger.info(
        f"scanned={counts['scanned']} marked={counts['marked']} "
        f"skipped={counts['skipped']} pending={counts['pending']} "
        f"errors={counts['errors']}"
    )
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
