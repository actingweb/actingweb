"""Move existing actors to their stored email once, and record that it ran
(4.0): ``actingweb-unique-creators creator-to-email``.

Under ``with_email_as_creator`` a vouched actor's creator follows its stored
email where the email is written (``actingweb.creator_sync``); a load no
longer reads the email or renames anything. Actors whose stored email and
creator differ when a deployment upgrades (a period with the flag off, an
email written outside the library, a 3.15 rename that stopped half way) are
moved by this sweep, once, and the application refuses to start under the
flag until it has run.

The marker it writes means "the sweep has completed once", and nothing more
(owner, 2026-11-15): a writer that does not go through the library (a 3.15
process during the deploy, a process with the flag off, a restore) can leave
a mismatch behind the scan. Run the sweep again after the deploy and after
any such period; ``--unmark --apply`` makes flag-on starts wait for it.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from actingweb.constants import READINESS_BUCKET, READINESS_STORE
from actingweb.db.exceptions import DbError

from ..migration_guide import guide_section

logger = logging.getLogger("unique_creators")

MARKER_NAME = "email_as_creator"
COMMAND = "actingweb-unique-creators creator-to-email"
GUIDE = guide_section("The creator follows the stored email")
SYSTEM_ACTOR_PREFIX = "_actingweb_"

# Stores whose marker was seen synced in this process: a positive answer is
# kept, a negative one is read again on the next start.
_seen_synced: set[tuple[str, str]] = set()


def _store_key(config: Any) -> tuple[str, str]:
    database = getattr(config, "database", "dynamodb")
    if database == "postgresql":
        from actingweb.db.postgresql.connection import get_schema_name

        return database, get_schema_name()
    return database, os.getenv("AWS_DB_PREFIX", "demo_actingweb")


def reset_probe() -> None:
    """Forget what :func:`settle` saw (tests that swap stores)."""
    _seen_synced.clear()


def read_marker(config: Any) -> dict[str, Any] | None:
    """The marker's value, or None when there is none. Raises ``DbError``."""
    from actingweb.db import get_attribute

    row = get_attribute(config).get_attr_strict(
        READINESS_STORE, READINESS_BUCKET, MARKER_NAME
    )
    data = row.get("data") if isinstance(row, dict) else None
    return data if isinstance(data, dict) else None


def _marker_value() -> dict[str, Any]:
    return {"state": "synced", "at": datetime.now(UTC).isoformat(timespec="seconds")}


def write_marker(config: Any) -> None:
    """Record that the sweep completed. Raises ``DbError``."""
    from actingweb.db import get_attribute

    get_attribute(config).set_attr(
        READINESS_STORE, READINESS_BUCKET, MARKER_NAME, _marker_value()
    )


def delete_marker(config: Any) -> None:
    """Withdraw the marker. Raises ``DbError``."""
    from actingweb.db import get_attribute

    get_attribute(config).set_attr(READINESS_STORE, READINESS_BUCKET, MARKER_NAME, None)


def settle(config: Any) -> str | None:
    """The startup probe: None when the store is ready, else why not.

    With the flag off nothing is read or written. With it on, one strict
    point read of the marker: ``synced`` is ready (remembered for the
    process); no marker on a store with no actors is ready too, and the
    marker is written (one conditional create, so two processes starting
    at once write one); no marker otherwise is not ready. A read fault
    raises ``DbError``.
    """
    if not getattr(config, "force_email_prop_as_creator", False):
        return None
    key = _store_key(config)
    if key in _seen_synced:
        return None
    marker = read_marker(config)
    if marker and marker.get("state") == "synced":
        _seen_synced.add(key)
        return None
    from actingweb.maintenance.unique_creators import no_actors

    if no_actors(config):
        from actingweb.db import get_attribute

        get_attribute(config).create_attr_if_absent(
            READINESS_STORE, READINESS_BUCKET, MARKER_NAME, _marker_value()
        )
        _seen_synced.add(key)
        return None
    return (
        "with_email_as_creator is on, but the actors that existed before 4.0 "
        f"have not been moved to their stored email. Run '{COMMAND}', read its "
        f"dry run, then '{COMMAND} --apply' ({GUIDE}), or turn the flag off. "
        "(A store whose actor table could not be scanned to tell it empty is "
        "refused the same way: check that the role may Scan it.)"
    )


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def _in_scope(store: Any, creator: str) -> str | None:
    """The address to move the actor to, or None: vouched in the
    marker-only form, a stored email that is an address and differs from
    the creator, and a creator that is not ``trustee`` or reserved."""
    from actingweb.creator_sync import is_address
    from actingweb.db.creator_rules import is_reserved, normalise_creator
    from actingweb.oauth2 import is_vouched_store

    email = store.email
    # Vouched for its current creator: an actor renamed on purpose with
    # Actor.modify(creator=...) reads unvouched for it (its recorded address
    # and stored email name the old one) and is left alone, not moved back.
    if not is_address(email) or not is_vouched_store(store, creator):
        return None
    current = normalise_creator(creator)
    if current == "trustee" or is_reserved(creator):
        return None
    target = normalise_creator(email)
    return target if target != current else None


def _holder(
    config: Any,
    rename_config: Any,
    enforced: bool,
    target: str,
    me: str,
    *,
    repair: bool = False,
) -> str | None:
    """Another actor holding ``target`` now, or None. A holder is confirmed
    by a consistent read of its row: a record or index entry naming an actor
    that is gone, or holds another creator now, is not one (a stale record
    is released, as ``resolve`` does, but only with ``repair`` (an
    ``--apply`` run; a dry run changes nothing). Raises ``DbError``."""
    from actingweb.db import get_actor
    from actingweb.db.creator_rules import normalise_creator

    def holds(actor_id: str) -> bool:
        row = get_actor(config).get(actor_id=actor_id)
        return bool(row) and normalise_creator(row.get("creator")) == target

    if enforced:
        db = get_actor(rename_config)
        holder = db.get_creator_holder(target)
        if not holder or holder == me:
            return None
        if holds(holder):
            return holder
        if repair:
            db.release_stale_creator(target, holder)
        return None
    rows = get_actor(config).get_by_creator(creator=target, consistent=True)
    for row in rows if isinstance(rows, list) else []:
        actor_id = row.get("id")
        if actor_id and actor_id != me and holds(actor_id):
            return actor_id
    return None


def _holder_blocks(config: Any, holder: str, target: str) -> bool:
    """Whether the holder is vouched for ``target``: only then does it keep
    the marker back, and only then may ``--clear-held-email`` act. Anyone
    can become an unvouched holder of any address (the factory, a typed
    address, a trustee handoff), so such a holder must not keep a flag-on
    application from starting; it is cleaned or replaced when the
    address's owner signs in. An unreadable holder blocks."""
    from actingweb.oauth2 import classify_marker

    return classify_marker(config, holder, target) in ("vouched", None)


def sweep(
    config: Any,
    *,
    apply: bool = False,
    only: str | None = None,
    start_after: str | None = None,
    rate_limit: float | None = None,
    clear_held_email: bool = False,
    show_addresses: bool = False,
) -> dict[str, int]:
    """Move each vouched actor whose stored email differs from its creator
    to that email; write the marker after a complete clean ``--apply`` run.

    ``config`` is the command's own (uniqueness and the flag off, so reading
    an actor changes nothing). The rename goes through ``rename_creator``
    under a ``unique_creator`` config once uniqueness is enforced, so the
    record moves with it; it is conditioned on the creator, the marker and
    the email the sweep read, so a sign-in changing any of them in between
    wins and the actor is read again once.

    Counts: ``scanned``, ``moved`` (or would be, dry run), ``held`` (by a
    vouched actor: blocks the marker unless ``clear_held_email`` cleared
    it), ``squatted`` (held by an unvouched ``factory`` actor: reported, does
    not block), ``cleared``, ``changed`` (changed during the run twice:
    blocks), ``errors`` (blocks).

    Raises:
        StoreUnavailable: the actor list could not be read
    """
    from actingweb.attribute import InternalStore
    from actingweb.config import Config
    from actingweb.creator_sync import marker_of, vouch_entries
    from actingweb.db import get_actor, get_actor_list, get_attribute
    from actingweb.db.creator_rename import AttrWrite, RenameOutcome
    from actingweb.db.creator_rules import normalise_creator
    from actingweb.db.exceptions import CreatorTaken
    from actingweb.maintenance.unique_creators import (
        StoreUnavailable,
        _uniqueness_enforced,  # pyright: ignore[reportPrivateUsage]
    )

    def shown(value: str) -> str:
        return f" {value}" if show_addresses else ""

    try:
        enforced = _uniqueness_enforced(config)
        rows: list[tuple[str, str]] = []
        for row in get_actor_list(config).iter_rows(
            consistent=True, rate_limit=rate_limit
        ):
            actor_id = row.get("id")
            if not actor_id or str(actor_id).startswith(SYSTEM_ACTOR_PREFIX):
                continue
            if start_after and actor_id <= start_after:
                continue
            creator = row.get("creator") or ""
            if only is not None and normalise_creator(creator) != normalise_creator(
                only
            ):
                continue
            rows.append((actor_id, creator))
    except Exception as e:  # folds DbError: becomes StoreUnavailable (exit 2)
        raise StoreUnavailable(f"the actor list could not be read: {e}") from e

    rename_config = (
        Config(
            database=config.database,
            unique_creator=True,
            force_email_prop_as_creator=False,
        )
        if enforced
        else config
    )
    counts: dict[str, int] = dict.fromkeys(
        ("scanned", "moved", "held", "squatted", "cleared", "changed", "errors"), 0
    )
    # About four reads per actor (its row, its bucket, a holder's row and
    # bucket), under the same budget as the scan.
    pause = 4.0 / rate_limit if rate_limit else 0.0
    claimed: dict[str, str] = {}
    for actor_id, _listed in sorted(rows):
        counts["scanned"] += 1
        target: str | None = None
        for attempt in range(2):
            if pause:
                time.sleep(pause)
            try:
                handle = get_actor(rename_config)
                row = handle.get(actor_id=actor_id)
                if not row:
                    break  # deleted since the listing
                current = row.get("creator") or ""
                store = InternalStore(actor_id=actor_id, config=config)
                if not store.loaded:
                    raise DbError("bucket read", actor_id)
                target = _in_scope(store, current)
                if target is None:
                    break
                email = store.email
                holder = _holder(
                    config, rename_config, enforced, target, actor_id, repair=apply
                )
                if holder is None and target in claimed:
                    holder = claimed[target]  # moved there earlier in this run
                if holder:
                    if not _holder_blocks(config, holder, target):
                        counts["squatted"] += 1
                        logger.info(
                            f"actor={actor_id} outcome=held-by-unvouched "
                            f"holder={holder}{shown(target)}"
                        )
                    elif clear_held_email and apply:
                        # Only while it still holds what was read: a sign-in
                        # writing a proven address meanwhile keeps it.
                        if get_attribute(config).delete_attr_if_data_equals(
                            actor_id, "_internal", "email", email
                        ):
                            counts["cleared"] += 1
                            logger.info(f"actor={actor_id} outcome=email-cleared")
                        else:
                            counts["errors"] += 1
                            logger.error(
                                f"actor={actor_id} outcome=clear-not-confirmed"
                            )
                    else:
                        counts["held"] += 1
                        logger.warning(
                            f"actor={actor_id} outcome=held holder={holder}"
                            f"{shown(target)}"
                        )
                    break
                if not apply:
                    counts["moved"] += 1
                    logger.info(f"actor={actor_id} outcome=would-move{shown(target)}")
                    break
                outcome = handle.rename_creator(
                    actor_id,
                    expected=current,
                    creator=target,
                    internal=[
                        AttrWrite("email", email, "equals", email),
                        *vouch_entries(store, target),
                    ],
                    marker=marker_of(store),
                )
                if outcome is RenameOutcome.APPLIED:
                    claimed[target] = actor_id
                    counts["moved"] += 1
                    logger.info(f"actor={actor_id} outcome=moved{shown(target)}")
                    break
                if attempt == 1:
                    counts["changed"] += 1
                    logger.warning(
                        f"actor={actor_id} outcome=changed-during-the-run "
                        f"({outcome.value}); run the sweep again"
                    )
            except CreatorTaken:  # folds DbError: a held address is reported
                # Taken between the holder read and the rename: classify the
                # holder as above.
                try:
                    assert target is not None  # set before any rename
                    taker = _holder(
                        config, rename_config, enforced, target, actor_id, repair=apply
                    )
                    blocks = taker is None or _holder_blocks(config, taker, target)
                except Exception:  # folds DbError: unknown holder blocks
                    taker, blocks = None, True
                key = "held" if blocks else "squatted"
                counts[key] += 1
                logger.warning(
                    f"actor={actor_id} outcome={key} (taken meanwhile) holder={taker}"
                )
                break
            except Exception as e:  # folds DbError: counted, exit 1
                counts["errors"] += 1
                logger.error(f"actor={actor_id} outcome=error {type(e).__name__}")
                break
    complete = (
        apply
        and only is None
        and start_after is None
        and not (counts["held"] or counts["changed"] or counts["errors"])
    )
    if complete:
        try:
            write_marker(config)
        except DbError as e:  # folds DbError: becomes StoreUnavailable (exit 2)
            logger.error(
                "every actor was handled but the marker could not be written; "
                "run --apply again: " + " ".join(f"{k}={v}" for k, v in counts.items())
            )
            raise StoreUnavailable(f"the marker could not be written: {e}") from e
        logger.info(
            "marker written: the sweep has completed once. It does not prove "
            "that no mismatch exists: run it again after the deploy, and after "
            "any period with the flag off"
        )
    elif apply:
        logger.info(
            "marker not written: "
            + (
                "--creator or --start-after limits the run"
                if only is not None or start_after is not None
                else "some actors were not moved (held, changed or errors)"
            )
        )
    return counts
