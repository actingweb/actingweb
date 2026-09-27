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
import secrets
import time
from typing import TYPE_CHECKING, Any, Literal

from .constants import REFRESH_TOKEN_GRACE_DEFAULT, REFRESH_TOKEN_GRACE_MAX

if TYPE_CHECKING:
    from . import config as config_class

logger = logging.getLogger(__name__)


def validate_refresh_token_grace(value: object) -> int:
    """Return ``value`` if it is a valid refresh-token grace period.

    Raises:
        ValueError: ``value`` is not an integer from 0 to
            ``REFRESH_TOKEN_GRACE_MAX``. A ``bool`` is refused, not read as
            0 or 1.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= REFRESH_TOKEN_GRACE_MAX
    ):
        raise ValueError(
            f"Refresh token grace period must be an integer from 0 to "
            f"{REFRESH_TOKEN_GRACE_MAX} seconds, got {value!r}"
        )
    return value


def refresh_token_grace(config: "config_class.Config") -> int:
    """The grace period a refresh ladder applies, in seconds.

    ``Config.refresh_token_grace_period`` is a validating property, so a
    real ``Config`` always holds a valid value. This is defence in depth for
    any other config object: a value outside ``[0,
    REFRESH_TOKEN_GRACE_MAX]`` is clamped and a non-integer falls back to the
    default, instead of disabling reuse detection or failing the request.
    """
    value = getattr(config, "refresh_token_grace_period", REFRESH_TOKEN_GRACE_DEFAULT)
    if isinstance(value, bool) or not isinstance(value, int):
        logger.warning(
            f"refresh_token_grace_period is not an integer ({value!r}); "
            f"using {REFRESH_TOKEN_GRACE_DEFAULT} s"
        )
        return REFRESH_TOKEN_GRACE_DEFAULT
    return min(max(value, 0), REFRESH_TOKEN_GRACE_MAX)


def classify_reuse(
    age: int, grace: int, reuse_window: int
) -> Literal["grace", "theft", "expired"]:
    """Judge a consumed refresh token presented again ``age`` seconds after
    it was consumed.

    - ``"grace"``: within a non-zero grace period; rotate again in the same
      chain. A grace of 0 is no grace at all, so a reuse in the same second
      (age 0, or negative from clock skew between workers) is theft.
    - ``"theft"``: within the reuse window; revoke the chain.
    - ``"expired"``: past the window; refuse without revoking (the row only
      outlived it because storage TTLs lag).
    """
    if grace > 0 and age <= grace:
        return "grace"
    if age <= reuse_window:
        return "theft"
    return "expired"


class StoreFault(Exception):
    """The store could not confirm a single-use consume either way.

    Raised when the compare-and-swap failed and a strict re-read either
    faulted too or found the record still unused: no competing consume
    happened, so the failure was the store's. The record is untouched and the
    caller should answer "retry", never "already used". Each token store
    translates it into its own error.
    """


def consume_once(
    config: "config_class.Config",
    actor_id: str,
    bucket: str,
    name: str,
    record: dict[str, Any],
    *,
    consumed_ttl: int | None = None,
    stamp: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    """Atomically mark a single-use record (a code or a refresh token) used.

    The ``used`` pre-check comes first: without it an already-used row
    matches itself in the compare-and-swap and would be consumed again. The
    swap runs on a copy of the loaded row, so only a caller that read the
    unused row can win.

    Both backends answer ``False`` from the swap for a lost race *and* for a
    fault (a throttle, a dropped connection). The loser therefore re-reads
    strictly: a row that is now used means another caller won; a row that is
    still unused, or a read that faults too, means the store failed and
    :class:`StoreFault` is raised. Reading a fault as "already used" would
    make a caller discard a record nobody consumed.

    Args:
        config: ActingWeb configuration
        actor_id: The actor whose bucket holds the record
        bucket: The bucket name
        name: The record's attribute name (the token or code)
        record: The record as loaded
        consumed_ttl: When given, the swap itself sets the consumed row's
            storage TTL, in the same conditional write. It never re-creates a
            row a concurrent revocation deleted, as a separate upsert would.
        stamp: Extra fields written into the consumed row with ``used``, never
            into the swap's expected value.

    Returns:
        ``(True, new_record)`` for the caller that consumed it;
        ``(False, current_record)`` when it was already used, with the current
        row (``None`` when the row is gone or expired).

    Raises:
        StoreFault: the store could not confirm the consume either way.
    """
    # Imported here, as the token stores do: attribute sits below them and
    # importing it at module load from this low-level module invites cycles.
    from . import attribute
    from .db import get_attribute

    if record.get("used"):
        return (False, record)

    store = attribute.Attributes(actor_id=actor_id, bucket=bucket, config=config)
    old_data = copy.deepcopy(record)
    new_data = copy.deepcopy(record)
    new_data.update(stamp or {})
    new_data["used"] = True
    new_data["used_at"] = int(time.time())
    # Identifies this call's write: a swap that landed but whose response
    # was lost (both backends answer False then) is recognised as ours.
    new_data["consume_id"] = secrets.token_hex(8)

    if store.conditional_update_attr(
        name=name, old_data=old_data, new_data=new_data, ttl_seconds=consumed_ttl
    ):
        return (True, new_data)

    # Lost the race, or the store failed: a strict read (no instance cache,
    # faults raise) tells them apart.
    try:
        row = get_attribute(config).get_attr_strict(
            actor_id=actor_id, bucket=bucket, name=name
        )
    except Exception as e:
        raise StoreFault(f"Could not confirm consume in {bucket}") from e
    current = row.get("data") if isinstance(row, dict) else None
    if not isinstance(current, dict):
        return (False, None)
    if current.get("consume_id") == new_data["consume_id"]:
        logger.warning(
            f"Compare-and-swap in {bucket} for actor {actor_id} reported failure "
            f"but its write landed; treating the consume as ours"
        )
        return (True, current)
    if not current.get("used"):
        logger.error(
            f"Compare-and-swap in {bucket} for actor {actor_id} (record "
            f"{_mask(name)}) failed with no competing consume; treating it as a "
            f"store fault"
        )
        raise StoreFault(f"Consume in {bucket} failed without a competing write")
    return (False, current)


def _mask(name: str) -> str:
    """The first eight characters of a token or code name, for logs."""
    if not name or len(name) < 8:
        return "***"
    return f"{name[:8]}..."


def delete_confirmed(
    config: "config_class.Config", actor_id: str, bucket: str, name: str
) -> bool:
    """Delete one row and confirm it is gone.

    ``delete_attr`` cannot be trusted to report a fault: PostgreSQL answers
    False, but DynamoDB swallows the error and answers True. This uses the
    conditional delete (True only when this call removed the row) and, when
    that answers False, a strict read to tell "already gone" from "still
    there" or "could not look".

    Returns:
        True when the row is gone (removed now, earlier, or expired); False
        when it is still there or the store could not confirm either way.
    """
    from .db import get_attribute

    db = get_attribute(config)
    try:
        if db.delete_attr_conditional(actor_id=actor_id, bucket=bucket, name=name):
            return True
        return db.get_attr_strict(actor_id=actor_id, bucket=bucket, name=name) is None
    except Exception as e:
        logger.warning(f"Could not confirm a delete in {bucket}: {e}")
        return False


class PurgeThrottle:
    """Process-local "at most once per interval" gate for an opportunistic purge.

    Lock-free on purpose: two threads racing past it both run the purge,
    which is an idempotent delete of already-expired rows. A fresh process
    (a serverless cold start) has never purged and purges on its first call.
    The throttle is per process, so N workers purge up to N times per
    interval. Time is monotonic: a wall clock stepped back would otherwise
    stop the purge until it caught up.
    """

    def __init__(self) -> None:
        # time.monotonic() of the last claim; None until the first.
        self.last_attempt: float | None = None

    def claim(self, interval: float) -> bool:
        """True when a purge is due; claims the slot before the work runs."""
        now = time.monotonic()
        if self.last_attempt is not None and now - self.last_attempt < interval:
            return False
        self.last_attempt = now
        return True
