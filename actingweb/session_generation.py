"""The session generation: which credentials survive the clean in place.

When a sign-in adopts an unvouched actor in place (``oauth2._adopt_actor``,
the clean), it revokes the actor's tokens twice, before and after it wipes
the actor's relationships. A grant that loaded its credential before the
clean and writes its token after the second revoke would still mint a live
token for whoever held the actor before.

The clean therefore writes a new **generation** into the actor's
``_internal`` bucket before it rotates the passphrase. Every credential a
later grant mints from records the generation when it is issued: an MCP
authorization code, an MCP refresh-token row, an SPA refresh-token row, and
an MCP client registration (for the client-credentials grant). The grant
writes its new token, then compares the credential's stamp with a strict
read of the current generation; a mismatch revokes what it just wrote and
fails the grant. A credential issued before 3.16 has no stamp and matches
only an actor whose generation was never written.

Not covered: access tokens. The clean's revokes remove them, but another
worker process can keep serving a cached access token for its cache TTL
(``handlers/mcp.py``, five minutes). Grants that mint from a fresh provider
assertion (the OAuth callback, the SPA authorization code, JWT bearer, the
mobile ticket) are not stamped either: they prove the creator anew.

This is not the MCP handler's process-wide cache generation
(``generation_at_read`` in ``handlers/mcp.py``), which is a different thing.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .db import get_attribute
from .db.exceptions import DbError

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

__all__ = ["STAMP_FIELD", "current", "bump", "matches", "guard"]

#: The field a credential records its generation in.
STAMP_FIELD = "session_generation"

_BUCKET = "_internal"
_NAME = "session_generation"


def current(actor_id: str, config: Config) -> str | None:
    """The actor's current generation, ``None`` when it was never written.

    One strict point read (``get_attr_strict``), not through
    ``InternalStore``, which would load the whole bucket first.

    Raises:
        DbError: on a read fault.
    """
    row = get_attribute(config).get_attr_strict(
        actor_id=actor_id, bucket=_BUCKET, name=_NAME
    )
    if not row:
        return None
    data = row.get("data")
    return str(data) if data else None


def bump(actor_id: str, config: Config) -> str:
    """Write a new generation; every credential stamped before it stops
    minting. Returns the value now stored.

    The conditional writes never raise (a fault reads as a lost race), so
    the write is confirmed by a strict read-back: the bump holds when the
    stored value differs from the one read before, whoever wrote it (a
    concurrent bump invalidates the same stamps).

    Raises:
        DbError: when the new value cannot be confirmed.
    """
    db = get_attribute(config)
    before = current(actor_id, config)
    new = secrets.token_hex(16)
    if before is None:
        db.create_attr_if_absent(
            actor_id=actor_id, bucket=_BUCKET, name=_NAME, data=new
        )
    else:
        db.conditional_update_attr(
            actor_id=actor_id,
            bucket=_BUCKET,
            name=_NAME,
            old_data=before,
            new_data=new,
        )
    after = current(actor_id, config)
    if after is None or after == before:
        raise DbError("session generation write", actor_id)
    return after


def matches(stamped: Any, actor_id: str, config: Config) -> bool:
    """Whether a credential stamped ``stamped`` may still mint.

    Raises:
        DbError: on a read fault.
    """
    now = current(actor_id, config)
    stamp = str(stamped) if stamped else None
    return stamp == now


def guard(
    actor_id: str,
    config: Config,
    stamped: Any,
    revoke: Callable[[], None],
) -> bool:
    """After a grant wrote its token: True when the credential's stamp still
    matches. On a mismatch, or when the generation cannot be read, the
    token just written is revoked first; a read fault then raises.

    Raises:
        DbError: the generation could not be read (the token is revoked).
    """
    try:
        ok = matches(stamped, actor_id, config)
    except DbError:
        _revoke(revoke, actor_id)
        raise
    if not ok:
        logger.warning(
            f"A grant for actor {actor_id} minted from a credential issued before "
            "the actor was adopted; revoking what it wrote"
        )
        _revoke(revoke, actor_id)
    return ok


def _revoke(revoke: Callable[[], None], actor_id: str) -> None:
    try:
        revoke()
    except Exception as e:  # folds DbError: the caller fails the grant either way; logged so the token can be found
        logger.error(
            f"Could not revoke a token minted for actor {actor_id} after a "
            f"session-generation check failed: {e}"
        )
