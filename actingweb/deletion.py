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
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .constants import (
    DELETED_ACTORS_BUCKET,
    DELETED_ACTORS_STORE,
    DELETION_TOMBSTONE_TTL,
)
from .db import get_attribute

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

__all__ = [
    "DeletionStatus",
    "mark_actor_deleted",
    "clear_actor_tombstone",
    "get_deletion_status",
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
) -> bool:
    """Write a deletion tombstone for ``actor_id``.

    Called at the very start of :meth:`actingweb.actor.Actor.delete`, before any
    data is removed, so the tombstone is readable throughout the wipe.

    Failure is logged at ERROR but not raised: a user asking to delete their
    account must not be blocked by the bookkeeping. The ERROR matters because a
    missing tombstone reopens the race for that actor.

    Args:
        actor_id: The actor being deleted.
        config: ActingWeb configuration.
        ttl_seconds: Override the default retention.

    Returns:
        True if the tombstone was written.
    """
    if not actor_id or not config:
        return False
    try:
        db = get_attribute(config)
        return bool(
            db.set_attr(
                actor_id=DELETED_ACTORS_STORE,
                bucket=DELETED_ACTORS_BUCKET,
                name=actor_id,
                data={
                    "actor_id": actor_id,
                    "deleted_at": datetime.datetime.now(datetime.UTC).isoformat(),
                },
                ttl_seconds=(
                    DELETION_TOMBSTONE_TTL if ttl_seconds is None else ttl_seconds
                ),
            )
        )
    except Exception as e:
        logger.error(
            f"Failed to write deletion tombstone for actor {actor_id}: {e}. "
            "Deletion will proceed, but late writes for this actor cannot be "
            "suppressed by a tombstone check."
        )
        return False


def clear_actor_tombstone(actor_id: str | None, config: Config | None) -> bool:
    """Remove any tombstone for ``actor_id``.

    Called on actor creation. Actor ids are normally generated and never reused,
    but ``Actor.create(actor_id=...)`` accepts a caller-supplied id; without
    this, re-creating such an id would leave it permanently reported as
    ``DELETED`` and every write for the live actor suppressed.

    Args:
        actor_id: The actor being created.
        config: ActingWeb configuration.

    Returns:
        True if the delete was issued (including when there was nothing there).
    """
    if not actor_id or not config:
        return False
    try:
        db = get_attribute(config)
        return bool(
            db.delete_attr(
                actor_id=DELETED_ACTORS_STORE,
                bucket=DELETED_ACTORS_BUCKET,
                name=actor_id,
            )
        )
    except Exception as e:
        logger.error(f"Failed to clear deletion tombstone for actor {actor_id}: {e}")
        return False


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
        db = get_attribute(config)
        row: dict[str, Any] | None = db.get_attr_strict(
            actor_id=DELETED_ACTORS_STORE,
            bucket=DELETED_ACTORS_BUCKET,
            name=actor_id,
        )
    except Exception as e:
        logger.error(
            f"Could not read deletion tombstone for actor {actor_id}: {e}. "
            "Reporting UNKNOWN; callers must not read this as 'not deleted'."
        )
        return DeletionStatus.UNKNOWN
    return DeletionStatus.DELETED if row else DeletionStatus.NOT_DELETED
