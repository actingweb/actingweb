"""
DynamoDB model for subscription suspension state.

Suspension allows temporarily disabling diff registration for specific
targets/subtargets during bulk operations (imports, migrations).
"""

import logging
import os
from datetime import UTC, datetime

from pynamodb.attributes import UnicodeAttribute, UTCDateTimeAttribute
from pynamodb.exceptions import DoesNotExist
from pynamodb.models import Model

logger = logging.getLogger(__name__)


class SubscriptionSuspension(Model):
    """Tracks suspended subscription targets for an actor."""

    class Meta:  # type: ignore[misc]
        table_name = (
            os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_subscription_suspensions"
        )
        read_capacity_units = 2
        write_capacity_units = 1
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

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if a target/subtarget is currently suspended."""
        target_key = _make_target_key(target, subtarget)
        try:
            SubscriptionSuspension.get(self._actor_id, target_key)
            return True
        except DoesNotExist:
            return False

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration. Returns True if newly suspended."""
        if self.is_suspended(target, subtarget):
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
