"""Primitives shared by the two token stores that rotate refresh tokens.

The SPA session store (``oauth_session.OAuth2SessionManager``) and the MCP
token manager (``oauth2_server.token_manager.ActingWebTokenManager``) keep
their records in different buckets and actors, but consume a single-use
record and throttle their expired-row purge the same way. Both live here so a
fix to either reaches both stores.

Internal: not part of the public API.
"""

import copy
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import config as config_class

logger = logging.getLogger(__name__)


def consume_once(
    config: "config_class.Config",
    actor_id: str,
    bucket: str,
    name: str,
    record: dict[str, Any],
    *,
    restamp_ttl: int | None = None,
    stamp: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Atomically mark a single-use record (a code or a refresh token) used.

    The ``used`` pre-check comes first: without it an already-used row
    matches itself in the compare-and-swap and would be consumed again. The
    swap runs on a copy of the loaded row, so only a caller that read the
    unused row can win.

    Args:
        config: ActingWeb configuration
        actor_id: The actor whose bucket holds the record
        bucket: The bucket name
        name: The record's attribute name (the token or code)
        record: The record as loaded
        restamp_ttl: When given, the winner rewrites the consumed row with this
            storage TTL. Best effort: on failure the row keeps its original
            TTL, which is harmless because a used row can never be consumed
            again. If a concurrent revocation deleted the row between the swap
            and this write, the write re-creates it used and short-lived, which
            is equally harmless.
        stamp: Extra fields written into the consumed row with ``used``, never
            into the swap's expected value.

    Returns:
        ``(True, new_record)`` for the caller that consumed it;
        ``(False, current_record)`` when it was already used, with the current
        row (``None`` when the row is gone).
    """
    # Imported here, as the token stores do: attribute sits below them and
    # importing it at module load from this low-level module invites cycles.
    from . import attribute

    if record.get("used"):
        return (False, record)

    store = attribute.Attributes(actor_id=actor_id, bucket=bucket, config=config)
    old_data = copy.deepcopy(record)
    new_data = copy.deepcopy(record)
    new_data.update(stamp or {})
    new_data["used"] = True
    new_data["used_at"] = int(time.time())

    if store.conditional_update_attr(name=name, old_data=old_data, new_data=new_data):
        if restamp_ttl:
            try:
                store.set_attr(name=name, data=new_data, ttl_seconds=restamp_ttl)
            except Exception as e:
                logger.debug(f"Could not shorten consumed record TTL: {e}")
        return (True, new_data)

    # Lost the race: re-read through a fresh instance (no instance cache) to
    # see the winner's used_at.
    fresh = attribute.Attributes(actor_id=actor_id, bucket=bucket, config=config)
    current = fresh.get_attr(name=name)
    if current and isinstance(current.get("data"), dict):
        return (False, current["data"])
    return (False, None)


class PurgeThrottle:
    """Process-local "at most once per interval" gate for an opportunistic purge.

    Lock-free on purpose: two threads racing past it both run the purge,
    which is an idempotent delete of already-expired rows. A fresh process
    (a serverless cold start) starts at 0 and purges on its first call. The
    throttle is per process, so N workers purge up to N times per interval.
    """

    def __init__(self) -> None:
        self.last_attempt: float = 0.0

    def claim(self, interval: float) -> bool:
        """True when a purge is due; claims the slot before the work runs."""
        now = time.time()
        if now - self.last_attempt < interval:
            return False
        self.last_attempt = now
        return True
