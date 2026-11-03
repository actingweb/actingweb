"""Deletion tombstones: positive, durable evidence that an actor is gone.

Why this exists
---------------

``Actor.delete()`` removes the actor row **last**, after wiping properties,
subscriptions, trusts and attribute buckets. For the whole of that wipe the
actor still resolves, so a consumer's "is this actor still there?" check answers
*yes* while the actor's data is being erased underneath it. Existence checks
fail **open** exactly in the window where they matter.

That window is entered deliberately by the documented pattern. The
``actor_deleted`` hook is where an application cancels an external subscription,
and cancelling triggers an asynchronous provider webhook that arrives straight
back into the window — and writes rows for an actor that no longer exists.

Checking existence harder is not the fix, because ``get_by_id()`` returns
``None`` for "deleted" *and* for "the read failed". A guard that skips work on
``None`` also skips it on a throttle, silently. For a paid-subscription webhook
that means the customer paid and never got access.

The design
----------

A tombstone inverts the polarity of the check. It is *positive* evidence,
written **before** the wipe begins and outliving it by
:data:`~actingweb.constants.DELETION_TOMBSTONE_TTL`, and reads answer with three
values rather than two:

- :attr:`DeletionStatus.DELETED` — confirmed gone. Suppress the write.
- :attr:`DeletionStatus.NOT_DELETED` — confirmed no tombstone. Proceed.
- :attr:`DeletionStatus.UNKNOWN` — the store could not be read. Proceed.

``UNKNOWN`` resolving to "proceed" is the whole point: the worst case is one
orphan row, which an operator sweep can find, whereas the reverse costs a paying
customer their access with nothing logged. A guard keyed on absence has no such
safe direction available, which is why it cannot be written correctly.

Usage::

    from actingweb.interface import ActorInterface, DeletionStatus

    if ActorInterface.get_deletion_status(actor_id, config) == DeletionStatus.DELETED:
        return  # late provider callback for a deleted account

The read is a single strongly-consistent point read (one DynamoDB ``GetItem`` /
one indexed PostgreSQL ``SELECT``), so it is cheap enough for a webhook path.

Storage lives under :data:`~actingweb.constants.DELETED_ACTORS_STORE`, an id
that is never itself an actor — a marker inside the deleted actor's own bucket
would be destroyed by the very wipe it is meant to describe.
"""

from __future__ import annotations

import datetime
import logging
import math
import secrets
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .constants import (
    DELETED_ACTORS_BUCKET,
    DELETED_ACTORS_STORE,
    DELETION_LEASE,
    DELETION_TOMBSTONE_TTL,
)
from .db import get_attribute
from .db.exceptions import DbError, DeletionInProgress

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

__all__ = [
    "DeletionStatus",
    "mark_actor_deleted",
    "clear_actor_tombstone",
    "get_deletion_status",
    "read_tombstone",
    "is_resumable",
    "lease_remaining",
]


class DeletionStatus(StrEnum):
    """Tri-state answer to "has this actor been deleted?".

    A ``StrEnum`` so it logs and serialises as its value.
    """

    DELETED = "deleted"
    """A tombstone was found: the actor has been deleted."""

    NOT_DELETED = "not_deleted"
    """The tombstone store was read and holds no tombstone for this actor."""

    UNKNOWN = "unknown"
    """The tombstone store could not be read. Treat as "proceed", not "deleted"."""


def mark_actor_deleted(
    actor_id: str | None,
    config: Config | None,
    ttl_seconds: int | None = None,
    *,
    reason: str | None = None,
    notify_peers: bool = True,
    hook_kwargs: dict[str, Any] | None = None,
    client_ids: list[str] | None = None,
    hook_fired: bool = False,
) -> bool:
    """Write a deletion tombstone for ``actor_id``.

    Without ``reason`` this is the plain tombstone earlier releases wrote,
    with the retention TTL. With ``reason`` it is a resumable tombstone
    (:mod:`actingweb.deletion_finish`): it records why it was written
    (``deleted`` or ``replaced_at_adoption``), whether the wipe notifies
    peers, the ``actor_deleted`` kwargs, the actor's OAuth2 client ids and
    whether ``actor_deleted`` has run, and it carries **no** TTL until the
    wipe is confirmed finished (:func:`mark_finished`), so a stalled wipe
    never ages out of ``actingweb-deletions report``.

    Failure is logged at ERROR but not raised: a user asking to delete their
    account must not be blocked by the bookkeeping. The ERROR matters because a
    missing tombstone reopens the race for that actor. A backend fault
    (``DbError``) is the exception: it is raised, before anything is removed.

    Args:
        actor_id: The actor being deleted.
        config: ActingWeb configuration.
        ttl_seconds: Override the default retention (plain tombstones only,
            unless given explicitly).
        reason: Why the actor is deleted; makes the tombstone resumable.
        notify_peers: Whether the wipe sends peers a DELETE.
        hook_kwargs: The kwargs ``actor_deleted`` is fired with.
        client_ids: The actor's OAuth2 client ids, read before any bucket
            goes, so a resumed wipe can still remove their index rows.
        hook_fired: Whether ``actor_deleted`` has already run.

    Returns:
        True if the tombstone was written.
    """
    if not actor_id or not config:
        return False
    data: dict[str, Any] = {
        "actor_id": actor_id,
        "deleted_at": _now().isoformat(),
    }
    if reason is not None:
        data.update(
            {
                "reason": reason,
                "notify_peers": bool(notify_peers),
                "hook_kwargs": dict(hook_kwargs or {}),
                "client_ids": sorted(set(client_ids or [])),
                "hook_fired": bool(hook_fired),
            }
        )
    if ttl_seconds is None and reason is None:
        ttl_seconds = DELETION_TOMBSTONE_TTL
    try:
        db = get_attribute(config)
        return bool(
            db.set_attr(
                actor_id=DELETED_ACTORS_STORE,
                bucket=DELETED_ACTORS_BUCKET,
                name=actor_id,
                data=data,
                ttl_seconds=ttl_seconds,
            )
        )
    except DbError:
        raise
    except Exception as e:
        logger.error(
            f"Failed to write deletion tombstone for actor {actor_id}: {e}. "
            "Deletion will proceed, but late writes for this actor cannot be "
            "suppressed by a tombstone check."
        )
        return False


def clear_actor_tombstone(
    actor_id: str | None, config: Config | None, *, strict: bool = False
) -> bool:
    """Remove any tombstone for ``actor_id``.

    Called on actor creation. Actor ids are normally generated and never reused,
    but ``Actor.create(actor_id=...)`` accepts a caller-supplied id; without
    this, re-creating such an id would leave it permanently reported as
    ``DELETED`` and every write for the live actor suppressed.

    ``strict=True`` (a caller-supplied id) confirms the removal with a
    strict read and raises ``DbError`` on a fault or when the tombstone is
    still there, so the create can fail instead of leaving a live actor
    tombstoned.

    Args:
        actor_id: The actor being created.
        config: ActingWeb configuration.
        strict: Confirm the removal; raise instead of folding a fault.

    Returns:
        True if the delete was issued (including when there was nothing there).
    """
    if not actor_id or not config:
        return False
    if strict:
        db = get_attribute(config)
        db.delete_attr(
            actor_id=DELETED_ACTORS_STORE,
            bucket=DELETED_ACTORS_BUCKET,
            name=actor_id,
        )
        if (
            db.get_attr_strict(
                actor_id=DELETED_ACTORS_STORE,
                bucket=DELETED_ACTORS_BUCKET,
                name=actor_id,
            )
            is not None
        ):
            raise DbError("deletion tombstone clear", actor_id)
        return True
    try:
        db = get_attribute(config)
        return bool(
            db.delete_attr(
                actor_id=DELETED_ACTORS_STORE,
                bucket=DELETED_ACTORS_BUCKET,
                name=actor_id,
            )
        )
    except Exception as e:  # folds DbError: non-strict clear only (a generated id, which no tombstone can name); strict=True raises
        logger.error(f"Failed to clear deletion tombstone for actor {actor_id}: {e}")
        return False


def read_tombstone(
    actor_id: str | None, config: Config | None
) -> tuple[DeletionStatus, dict[str, Any] | None]:
    """The deletion status and the tombstone's data, from one strict read.

    Expired rows are hidden by ``get_attr_strict`` on both backends.

    Raises:
        DbError: when the tombstone store cannot be read. Callers that fail
            closed (a sign-in, ``DELETE``, the MCP bridge) let it propagate;
            :func:`get_deletion_status` folds it into ``UNKNOWN``.
    """
    if not actor_id or not config:
        raise DbError("actor deletion status", actor_id)
    db = get_attribute(config)
    row: dict[str, Any] | None = db.get_attr_strict(
        actor_id=DELETED_ACTORS_STORE,
        bucket=DELETED_ACTORS_BUCKET,
        name=actor_id,
    )
    if not row:
        return DeletionStatus.NOT_DELETED, None
    data = row.get("data")
    return DeletionStatus.DELETED, dict(data) if isinstance(data, dict) else {}


def get_deletion_status(actor_id: str | None, config: Config | None) -> DeletionStatus:
    """Whether ``actor_id`` has been deleted, or whether that is unknowable.

    One strongly-consistent point read. See the module docstring for why the
    third state exists and why callers should treat it as "proceed".

    Args:
        actor_id: The actor to check.
        config: ActingWeb configuration.

    Returns:
        :class:`DeletionStatus`. ``UNKNOWN`` when the store is unreachable —
        never as a stand-in for "not deleted".
    """
    if not actor_id or not config:
        return DeletionStatus.UNKNOWN
    try:
        status, _ = read_tombstone(actor_id, config)
    except Exception as e:  # folds DbError: UNKNOWN by design; callers proceed or fail closed (see module docstring)
        logger.error(
            f"Could not read deletion tombstone for actor {actor_id}: {e}. "
            "Reporting UNKNOWN; callers must not read this as 'not deleted'."
        )
        return DeletionStatus.UNKNOWN
    return status


def is_resumable(data: dict[str, Any] | None) -> bool:
    """Whether a tombstone records why it was written (a ``reason``).

    A tombstone without one was written by a release before resumable
    deletion, or by a caller of :func:`mark_actor_deleted` without
    ``reason``; a sign-in leaves a vouched actor carrying one untouched.
    """
    return bool(data) and isinstance(data, dict) and bool(data.get("reason"))


def lease_remaining(
    data: dict[str, Any] | None, now: datetime.datetime | None = None
) -> int:
    """Whole seconds left on a tombstone's lease, 0 when there is none."""
    if not data:
        return 0
    until = _parse_time(data.get("claimed_until"))
    if until is None:
        return 0
    left = (until - (now or _now())).total_seconds()
    return max(0, math.ceil(left))


def update_tombstone(
    actor_id: str,
    config: Config,
    current: dict[str, Any],
    changes: dict[str, Any],
    *,
    ttl_seconds: int | None = None,
) -> dict[str, Any] | None:
    """Change fields of a tombstone, conditioned on it holding ``current``.

    Returns the new data, or None when another writer changed the row first
    (the caller re-reads). The conditional write answers False on a fault as
    well as on a lost condition, so a False is followed by a strict read:
    a row that already holds the new data counts as written (an SDK retry
    that landed), a fault raises ``DbError``.
    """
    new = {**current, **changes}
    db = get_attribute(config)
    if db.conditional_update_attr(
        actor_id=DELETED_ACTORS_STORE,
        bucket=DELETED_ACTORS_BUCKET,
        name=actor_id,
        old_data=current,
        new_data=new,
        ttl_seconds=ttl_seconds,
    ):
        return new
    _, now_data = read_tombstone(actor_id, config)
    if now_data == new:
        return new
    return None


def claim_lease(
    actor_id: str,
    config: Config,
    data: dict[str, Any],
    *,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Take the tombstone's lease for one finisher; return the new data.

    Raises:
        DeletionInProgress: another finisher holds a live lease, or took it
            between the read and this write.
        DbError: on a fault.
    """
    moment = now or _now()
    remaining = lease_remaining(data, moment)
    if remaining > 0:
        raise DeletionInProgress(actor_id, remaining)
    claimed = update_tombstone(
        actor_id,
        config,
        data,
        {
            "claimed_until": (
                moment + datetime.timedelta(seconds=DELETION_LEASE)
            ).isoformat(),
            "lease_id": secrets.token_hex(8),
        },
    )
    if claimed is None:
        _, latest = read_tombstone(actor_id, config)
        raise DeletionInProgress(
            actor_id, lease_remaining(latest, moment) or DELETION_LEASE
        )
    return claimed


def create_leased_tombstone(
    actor_id: str,
    config: Config,
    *,
    reason: str,
    notify_peers: bool,
    hook_kwargs: dict[str, Any],
    client_ids: list[str],
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Write a resumable tombstone holding this finisher's lease, only if none
    exists; return its data.

    One conditional create, so two first finishers at once (two ``DELETE``
    requests) cannot both run: the loser meets the winner's lease.

    Raises:
        DeletionInProgress: another finisher wrote the tombstone first and
            holds its lease.
        DbError: on a fault.
    """
    moment = now or _now()
    data: dict[str, Any] = {
        "actor_id": actor_id,
        "deleted_at": moment.isoformat(),
        "reason": reason,
        "notify_peers": bool(notify_peers),
        "hook_kwargs": dict(hook_kwargs),
        "client_ids": sorted(set(client_ids)),
        "hook_fired": False,
        "claimed_until": (
            moment + datetime.timedelta(seconds=DELETION_LEASE)
        ).isoformat(),
        "lease_id": secrets.token_hex(8),
    }
    db = get_attribute(config)
    if db.create_attr_if_absent(
        actor_id=DELETED_ACTORS_STORE,
        bucket=DELETED_ACTORS_BUCKET,
        name=actor_id,
        data=data,
    ):
        return data
    _, existing = read_tombstone(actor_id, config)
    if existing is None:
        raise DbError("deletion tombstone write", actor_id)
    return claim_lease(actor_id, config, existing, now=moment)


def release_lease(actor_id: str, config: Config, data: dict[str, Any]) -> None:
    """Give a lease back after a failed attempt (best effort, logged).

    The row is read afresh (``Actor.delete``'s re-stamp changes it under the
    lease), and released only while it still holds this finisher's lease.
    """
    lease_id = data.get("lease_id")
    try:
        for _ in range(3):
            _, current = read_tombstone(actor_id, config)
            if current is None or not lease_id or current.get("lease_id") != lease_id:
                return
            if (
                update_tombstone(
                    actor_id,
                    config,
                    current,
                    {"claimed_until": None, "lease_id": None},
                )
                is not None
            ):
                return
    except Exception as e:  # folds DbError: best-effort release; the lease lapses on its own after DELETION_LEASE
        logger.warning(
            f"Could not release the deletion lease for actor {actor_id}: {e}; "
            f"it lapses within {DELETION_LEASE} s"
        )


def restamp(actor_id: str | None, config: Config | None, notify_peers: bool) -> bool:
    """``Actor.delete``'s own tombstone write; return the ``notify_peers`` to use.

    The deliberate second write: it moves ``deleted_at`` to the start of the
    wipe so late-write suppression runs from the wipe, not from before a
    possibly long ``actor_deleted`` hook. It changes ``deleted_at`` only and
    never what the first write recorded (``reason``, ``notify_peers``, the
    hook kwargs, the client ids, ``hook_fired``), so a stalled replacement
    stays a replacement. With no tombstone (a programmatic ``Actor.delete()``,
    which fires no hooks) it writes a resumable one with ``hook_fired=True``.

    Returns:
        ``notify_peers and`` what the tombstone recorded: a re-call of
        ``Actor.delete()`` cannot notify the peers of a replacement victim.
    """
    if not actor_id or not config:
        return notify_peers
    _, data = read_tombstone(actor_id, config)
    if data is None:
        mark_actor_deleted(
            actor_id,
            config,
            reason="deleted",
            notify_peers=notify_peers,
            hook_fired=True,
        )
        return notify_peers
    recorded = data.get("notify_peers")
    effective = notify_peers and (recorded is not False)
    for _ in range(2):
        changed = update_tombstone(
            actor_id,
            config,
            data,
            {"deleted_at": _now().isoformat()},
            ttl_seconds=None if is_resumable(data) else DELETION_TOMBSTONE_TTL,
        )
        if changed is not None:
            return effective
        _, data = read_tombstone(actor_id, config)
        if data is None:
            break
        recorded = data.get("notify_peers")
        effective = notify_peers and (recorded is not False)
    logger.warning(
        f"Deletion tombstone for actor {actor_id} changed under the re-stamp; "
        "deleted_at was left as the first write set it"
    )
    return effective


def lease_fields(now: datetime.datetime | None = None) -> dict[str, Any]:
    """A renewed lease's ``claimed_until`` (the ``lease_id`` is kept)."""
    moment = now or _now()
    return {
        "claimed_until": (
            moment + datetime.timedelta(seconds=DELETION_LEASE)
        ).isoformat()
    }


def mark_finished(actor_id: str, config: Config, data: dict[str, Any] | None) -> bool:
    """Record a confirmed wipe and start the retention TTL; return whether
    this finisher announces it (``actor_deleted_complete``).

    Until this runs a resumable tombstone has no TTL. The row is read
    afresh (``Actor.delete``'s re-stamp changed it). When it no longer holds
    this finisher's lease (``data``'s ``lease_id``), another finisher took a
    lapsed lease and finishes too; this one does not announce, so the
    completion is announced once. A fault is logged and answers True: the
    actor row is already gone, and the tombstone stays (it suppresses late
    writes, which is its job) without a TTL.
    """
    lease_id = (data or {}).get("lease_id")
    try:
        for _ in range(3):
            _, current = read_tombstone(actor_id, config)
            if current is None:
                return True
            if lease_id and current.get("lease_id") not in (lease_id, None):
                return False
            if current.get("finished_at"):
                return False
            if (
                update_tombstone(
                    actor_id,
                    config,
                    current,
                    {
                        "finished_at": _now().isoformat(),
                        "claimed_until": None,
                        "lease_id": None,
                    },
                    ttl_seconds=DELETION_TOMBSTONE_TTL,
                )
                is not None
            ):
                return True
        return False
    except Exception as e:  # folds DbError: bookkeeping after the actor row is gone; a raise would fail a finished deletion
        logger.error(
            f"Deletion of actor {actor_id} finished, but its tombstone could not "
            f"be marked finished: {e}"
        )
        return True


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _parse_time(value: Any) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed
