"""The creator follows the stored email where the email is written (3.16).

Under ``with_email_as_creator`` (``config.force_email_prop_as_creator``) a
vouched actor's creator equals its stored ``_internal`` email. Before 3.16
every load read the bucket and renamed the creator when they differed; now a
write of the email to a different address renames the creator in the same
atomic backend operation (``DbActor.rename_creator``), and a load is one
read.

:func:`write_stored_email` is called by the four ``InternalStore`` methods
that write a key, for the key ``email``. It answers None when the write is
a plain one (the link does not apply), so the method runs its own code.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from actingweb.db.creator_rename import (
    INTERNAL_BUCKET,
    MARKER_NAME,
    AttrWrite,
    RenameOutcome,
)
from actingweb.db.creator_rules import is_reserved, normalise_creator
from actingweb.db.exceptions import CreatorTaken, DbError

if TYPE_CHECKING:
    from actingweb.attribute import InternalStore

logger = logging.getLogger(__name__)

EMAIL = "email"


def is_address(value: Any) -> bool:
    """The test the load's gate used: a non-empty string with an ``@``."""
    return isinstance(value, str) and "@" in value


def vouch_entries(store: InternalStore, target: str) -> list[AttrWrite]:
    """The writes that move a vouch with the creator: the recorded address
    (when the actor has one) to ``target``, and a 3.15 pending value
    removed (when present)."""
    from actingweb.oauth2 import VOUCHED_CREATOR, VOUCHED_CREATOR_PENDING

    writes: list[AttrWrite] = []
    recorded = getattr(store, VOUCHED_CREATOR, None)
    if isinstance(recorded, str) and recorded:
        writes.append(AttrWrite(VOUCHED_CREATOR, target))
    if getattr(store, VOUCHED_CREATOR_PENDING, None) is not None:
        writes.append(AttrWrite(VOUCHED_CREATOR_PENDING, None))
    return writes


def marker_of(store: InternalStore) -> str | None:
    """The ``auth_method`` value a rename is conditioned on, or None."""
    value = getattr(store, MARKER_NAME, None)
    return value if isinstance(value, str) and value else None


def applies(store: InternalStore, value: Any) -> bool:
    """Whether a write of ``value`` to this store's ``email`` may move the
    creator, before any read: the ``_internal`` bucket, the flag on, an
    address, and not the shortcut of a store created with its actor in this
    call chain writing that actor's own creator."""
    db = store.__dict__["_db"]
    config = db.config
    if db.bucket != INTERNAL_BUCKET or not db.actor_id or config is None:
        return False
    if not getattr(config, "force_email_prop_as_creator", False):
        return False
    if not is_address(value):
        return False
    # The shortcut holds for the first email write of a store created with
    # its actor, not for the life of the instance.
    created_for = store.__dict__.pop("_created_for", None)
    if created_for is not None and normalise_creator(value) == created_for:
        return False
    return True


def write_stored_email(store: InternalStore, write: AttrWrite) -> RenameOutcome | None:
    """Write the stored email through one conditional backend operation,
    moving the creator with it when the link applies.

    None: the link does not apply (see :func:`applies`) or the actor row is
    gone; the caller writes as it always has. Otherwise the actor row and
    the bucket are read afresh, strictly, and one ``rename_creator`` writes
    the email (with ``write``'s own condition) under the creator and the
    marker just read. For a vouched actor whose creator is not ``trustee``
    or reserved and differs from the address, the same operation moves the
    creator, its record and the vouch; for any other the creator stays,
    but the write is still conditioned on it, so a rename that commits
    between the read and the write is not undone by it. A row or marker
    that changed is read once more; the second attempt's outcome is
    returned. After a fault whose outcome is unknown the row and the email
    are read back strictly, and a write that landed answers ``APPLIED``.

    Raises:
        CreatorTaken: another actor holds the address (logged)
        AttributeKeyCollision: another bucket holds the key
        DbError: a fault, including a bucket that could not be read
    """
    from actingweb.attribute import InternalStore
    from actingweb.db import get_actor
    from actingweb.db.exceptions import AttributeKeyCollision
    from actingweb.oauth2 import is_vouched_store

    if not applies(store, write.value):
        return None
    db = store.__dict__["_db"]
    config = db.config
    actor_id = db.actor_id
    target = normalise_creator(write.value)
    outcome: RenameOutcome | None = None
    for _attempt in range(2):
        handle = get_actor(config)
        row = handle.get(actor_id=actor_id)
        if not row or not isinstance(row.get("creator"), str):
            return None
        fresh = InternalStore(actor_id=actor_id, config=config)
        if not fresh.loaded:
            # A store fault would read as "unvouched" and the email would
            # land without the creator; nothing heals that any more.
            raise DbError("stored email write", actor_id)
        current: str = row["creator"]
        current_n = normalise_creator(current)
        moves = (
            is_vouched_store(fresh)
            and current_n != "trustee"
            and not is_reserved(current)
            and current_n != target
        )
        new_creator = target if moves else current
        # The email as the caller wrote it; the creator as stored (lower case).
        internal = [write, *(vouch_entries(fresh, target) if moves else [])]
        try:
            outcome = handle.rename_creator(
                actor_id,
                expected=current,
                creator=new_creator,
                internal=internal,
                marker=marker_of(fresh),
            )
        except CreatorTaken:
            logger.warning(
                f"Actor {actor_id}: the stored email was not changed, because "
                "another actor holds that address as its creator "
                "(with_email_as_creator links the two)"
            )
            raise
        except AttributeKeyCollision:
            raise
        except DbError:
            landed = _landed(config, actor_id, new_creator, write.value)
            if landed is not None:
                after_rename(store, landed, internal, new_creator)
                return RenameOutcome.APPLIED
            raise
        if outcome is RenameOutcome.APPLIED:
            after_rename(store, handle, internal, new_creator)
            return outcome
        if outcome not in (RenameOutcome.ROW_CHANGED, RenameOutcome.MARKER_CHANGED):
            return outcome
    return outcome


def _landed(config: Any, actor_id: str, creator: str, email: Any) -> Any | None:
    """After a fault: whether the operation committed, read strictly (it is
    atomic, so the creator and the email together say). The backend handle
    that read the row when it did, else None. A read fault raises
    ``DbError``."""
    from actingweb.db import get_actor, get_attribute

    handle = get_actor(config)
    row = handle.get(actor_id=actor_id)
    if not row or normalise_creator(row.get("creator")) != normalise_creator(creator):
        return None
    stored = get_attribute(config).get_attr_strict(actor_id, INTERNAL_BUCKET, EMAIL)
    if isinstance(stored, dict) and stored.get("data") == email:
        return handle
    return None


def after_rename(
    store: InternalStore, handle: Any, internal: list[AttrWrite], target: str
) -> None:
    """Bring the store, its ``Attributes`` cache and its owning actor in
    line with what the rename committed."""
    cache = store.__dict__["_db"]
    for w in internal:
        if w.value is None:
            store.__dict__.pop(w.name, None)
            cache.data.pop(w.name, None)
        else:
            store.__dict__[w.name] = w.value
            cache.data[w.name] = {"data": w.value, "timestamp": None}
    adopt_rename(store._owning_actor(), handle, normalise_creator(target))


def adopt_rename(actor: Any, handle: Any, target: str) -> None:
    """Point an ``Actor`` at a rename that ran on ``handle``: its creator,
    its row copy and its backend handle. Without the handle a later
    ``modify`` on the same instance is conditioned on the old creator and
    answers False."""
    if actor is None:
        return
    actor.creator = target
    if isinstance(getattr(actor, "actor", None), dict):
        actor.actor["creator"] = target
    actor.handle = handle
