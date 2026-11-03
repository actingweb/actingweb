"""Signing in again by an emailed code, for a user whose provider has no
verified address.

Such a user reaches the email form after the provider sign-in, types their
address, and proves it once with the emailed verification link. The next
sign-in with the same provider account again finds no verified address and
reaches the form again, where the address now has an actor. Without this the
form answers 409 and the user cannot get in.

With the ``email_sign_in_code_required`` lifecycle hook registered, the form
answers that case with a one-time code instead:

1. It creates a challenge (an id and a six-digit code, ten minutes, five
   tries) for the actor whose verified address was typed, and fires the hook
   with the code. The application sends it, as it sends the verification
   link through ``email_verification_required``.
2. The challenge id goes back only to the page that asked (the form or the
   SPA). The page posts the id and the code the user read in their mail.
3. A matching code signs that page in to the actor: the person who typed the
   address and the person who read the mailbox are then the same.

The code is stored as a digest bound to its challenge id, consumed with one
conditional delete, and a wrong code counts against the tries. An attacker
who types a victim's address gets a challenge only on their own page, and
the code only in the victim's mailbox.

Without the hook nothing changes: the form keeps its 409.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

from .constants import ACTINGWEB_SYSTEM_ACTOR
from .db import get_attribute
from .db.exceptions import DbError

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

__all__ = [
    "HOOK",
    "CODE_TTL",
    "MAX_TRIES",
    "start_challenge",
    "redeem",
    "hook_registered",
]

#: The lifecycle hook that sends the code: ``func(actor, email, code,
#: expires_in)``.
HOOK = "email_sign_in_code_required"
#: Seconds a code stays valid.
CODE_TTL = 600
#: Wrong codes a challenge tolerates before it is spent.
MAX_TRIES = 5
#: Challenges one actor can be sent per hour.
MAX_CHALLENGES_PER_HOUR = 5
#: The browser cookie that binds a web challenge to the browser that asked.
BINDING_COOKIE = "aw_sign_in_binding"

_BUCKET = "_email_sign_in_codes"


def _digest(challenge_id: str, code: str) -> str:
    return hashlib.sha256(f"{challenge_id}:{code}".encode()).hexdigest()


class TooManyChallenges(Exception):
    """An actor asked for more than :data:`MAX_CHALLENGES_PER_HOUR` codes."""


def start_challenge(
    config: Config, actor_id: str, email: str, binding: str | None = None
) -> tuple[str, str]:
    """Create a challenge for ``actor_id``; return ``(challenge_id, code)``.

    The code is returned so the caller can hand it to the hook; it is stored
    only as a digest. ``binding`` (the browser cookie the web form sets) is
    stored as a digest too; a redemption that names one must match it. One
    challenge per actor is live: a new one removes the previous one, and at
    most :data:`MAX_CHALLENGES_PER_HOUR` are created per actor per hour, so
    the five tries cannot be renewed at will and the mailbox is not flooded.

    Raises:
        TooManyChallenges: the hourly limit is reached.
        DbError: the challenge cannot be stored.
    """
    db = get_attribute(config)
    now = int(time.time())
    meta_name = f"actor:{actor_id}"
    row = db.get_attr_strict(
        actor_id=ACTINGWEB_SYSTEM_ACTOR, bucket=_BUCKET, name=meta_name
    )
    meta = row.get("data") if row else None
    if not isinstance(meta, dict) or now - int(meta.get("window_start") or 0) >= 3600:
        meta = {"window_start": now, "count": 0, "current": None}
    if int(meta.get("count") or 0) >= MAX_CHALLENGES_PER_HOUR:
        raise TooManyChallenges(actor_id)
    if meta.get("current"):
        db.delete_attr(
            actor_id=ACTINGWEB_SYSTEM_ACTOR, bucket=_BUCKET, name=str(meta["current"])
        )
    challenge_id = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(10**6):06d}"
    stored = db.set_attr(
        actor_id=ACTINGWEB_SYSTEM_ACTOR,
        bucket=_BUCKET,
        name=challenge_id,
        data={
            "actor_id": actor_id,
            "email": email.lower(),
            "digest": _digest(challenge_id, code),
            "binding": _digest(challenge_id, binding) if binding else None,
            "tries": 0,
            "expires_at": now + CODE_TTL,
        },
        ttl_seconds=CODE_TTL,
    )
    if not stored:
        raise DbError("email sign-in code store", actor_id)
    db.set_attr(
        actor_id=ACTINGWEB_SYSTEM_ACTOR,
        bucket=_BUCKET,
        name=meta_name,
        data={
            "window_start": meta["window_start"],
            "count": int(meta.get("count") or 0) + 1,
            "current": challenge_id,
        },
        ttl_seconds=3600,
    )
    return challenge_id, code


def redeem(
    config: Config, challenge_id: str, code: str, binding: str | None = None
) -> str | None:
    """The actor id a correct code signs in to, or None.

    Every attempt is counted before the code is compared: the try counter is
    raised with a conditional write on the row as read, and an attempt whose
    increment cannot land (it lost to concurrent attempts three times) is
    refused, so parallel guesses cannot skip the count. The attempt that
    reaches :data:`MAX_TRIES` spends the challenge. A correct code is consumed
    with a conditional delete, so of two concurrent redemptions one signs in.
    None for an unknown, expired or spent challenge and for a wrong code.
    Raises ``DbError`` on a store fault.
    """
    if not challenge_id or not code:
        return None
    db = get_attribute(config)
    data: dict[str, Any] | None = None
    for _ in range(3):
        row = db.get_attr_strict(
            actor_id=ACTINGWEB_SYSTEM_ACTOR, bucket=_BUCKET, name=challenge_id
        )
        current = row.get("data") if row else None
        if not isinstance(current, dict):
            return None
        if int(current.get("expires_at") or 0) < int(time.time()):
            return None
        tries = int(current.get("tries") or 0)
        if tries >= MAX_TRIES:
            return None
        counted = {**current, "tries": tries + 1}
        if db.conditional_update_attr(
            actor_id=ACTINGWEB_SYSTEM_ACTOR,
            bucket=_BUCKET,
            name=challenge_id,
            old_data=current,
            new_data=counted,
        ):
            data = counted
            break
    if data is None:
        logger.warning("Email sign-in code: attempt not counted; refused")
        return None
    expected_binding = data.get("binding")
    bound_ok = not expected_binding or (
        bool(binding)
        and hmac.compare_digest(
            str(expected_binding), _digest(challenge_id, str(binding))
        )
    )
    if not bound_ok or not hmac.compare_digest(
        str(data.get("digest") or ""), _digest(challenge_id, code.strip())
    ):
        if int(data["tries"]) >= MAX_TRIES:
            db.delete_attr(
                actor_id=ACTINGWEB_SYSTEM_ACTOR, bucket=_BUCKET, name=challenge_id
            )
            logger.warning("Email sign-in code: too many wrong codes; challenge spent")
        return None
    if not db.delete_attr_conditional(
        actor_id=ACTINGWEB_SYSTEM_ACTOR, bucket=_BUCKET, name=challenge_id
    ):
        return None  # consumed by a concurrent redemption
    actor_id = data.get("actor_id")
    return str(actor_id) if actor_id else None


def hook_registered(hooks: Any) -> bool:
    """Whether the application registered :data:`HOOK`."""
    registered = getattr(hooks, "_lifecycle_hooks", None)
    return bool(isinstance(registered, dict) and registered.get(HOOK))
