"""
DynamoDB model for subscription suspension state.

Suspension allows temporarily disabling diff registration for specific
targets/subtargets during bulk operations (imports, migrations).
"""

import logging
import os
from datetime import UTC, datetime

from pynamodb.attributes import UnicodeAttribute, UTCDateTimeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.exceptions import DoesNotExist
from pynamodb.models import Model

from actingweb.db.dynamodb._ensure import ensure_table

logger = logging.getLogger(__name__)


class SubscriptionSuspension(Model):
    """Tracks suspended subscription targets for an actor."""

    class Meta:  # type: ignore[misc]
        table_name = (
            os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_subscription_suspensions"
        )
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    id = UnicodeAttribute(hash_key=True)  # actor_id
    target_key = UnicodeAttribute(range_key=True)  # "target" or "target:subtarget"
    target = UnicodeAttribute()
    subtarget = UnicodeAttribute(null=True)
    suspended_at = UTCDateTimeAttribute()


def _make_target_key(target: str, subtarget: str | None) -> str:
    """Create composite key for target/subtarget."""
    if subtarget:
        return f"{target}:{subtarget}"
    return target


class DbSubscriptionSuspension:
    """Database operations for subscription suspension state."""

    def __init__(self, actor_id: str) -> None:
        self._actor_id = actor_id
        ensure_table(SubscriptionSuspension)

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if a target/subtarget is currently suspended.

        Suspending a *target* cascades to every subtarget under it. Without
        that, suspending "properties" would not stop property writes at all:
        PropertyStore registers each diff with the property name as the
        subtarget, so the check would look for "properties:<name>" and never
        match the stored "properties" key — the documented bulk-import usage
        would silently do nothing.
        """
        if subtarget is None:
            try:
                SubscriptionSuspension.get(self._actor_id, target)
                return True
            except DoesNotExist:
                return False

        # One Query over this target's keys instead of two GetItems, so the
        # cascade costs no extra round trip on the per-write path.
        target_key = _make_target_key(target, subtarget)
        for item in SubscriptionSuspension.query(
            self._actor_id,
            SubscriptionSuspension.target_key.startswith(target),
        ):
            # begins_with also matches sibling targets sharing this prefix
            # (e.g. "properties_v2"), so compare exactly.
            if item.target_key in (target, target_key):
                return True
        return False

    def _is_suspended_exact(self, target: str, subtarget: str | None) -> bool:
        """Exact-key check, ignoring target-level cascade."""
        try:
            SubscriptionSuspension.get(
                self._actor_id, _make_target_key(target, subtarget)
            )
            return True
        except DoesNotExist:
            return False

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration. Returns True if newly suspended."""
        # Exact, not cascaded: a subtarget suspension under an already
        # suspended target must still be recorded, or resuming the target
        # would silently lift a suspension the caller asked for separately.
        if self._is_suspended_exact(target, subtarget):
            return False

        target_key = _make_target_key(target, subtarget)
        suspension = SubscriptionSuspension(
            id=self._actor_id,
            target_key=target_key,
            target=target,
            subtarget=subtarget,
            suspended_at=datetime.now(UTC),
        )
        suspension.save()
        logger.info(
            f"Suspended subscriptions for {self._actor_id}/{target}"
            f"{'/' + subtarget if subtarget else ''}"
        )
        return True

    def resume(self, target: str, subtarget: str | None = None) -> bool:
        """Resume diff registration. Returns True if was suspended."""
        target_key = _make_target_key(target, subtarget)
        try:
            suspension = SubscriptionSuspension.get(self._actor_id, target_key)
            suspension.delete()
            logger.info(
                f"Resumed subscriptions for {self._actor_id}/{target}"
                f"{'/' + subtarget if subtarget else ''}"
            )
            return True
        except DoesNotExist:
            return False

    def get_all_suspended(self) -> list[tuple[str, str | None]]:
        """Get all currently suspended target/subtarget pairs."""
        results: list[tuple[str, str | None]] = []
        for item in SubscriptionSuspension.query(self._actor_id):
            results.append((item.target, item.subtarget))
        return results

    def delete_all(self) -> bool:
        """Delete all suspensions for this actor (cleanup on actor delete)."""
        try:
            for item in SubscriptionSuspension.query(self._actor_id):
                item.delete()
            return True
        except Exception as e:
            logger.error(f"Error deleting suspensions for {self._actor_id}: {e}")
            return False
