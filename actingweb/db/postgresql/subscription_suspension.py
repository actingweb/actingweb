"""
PostgreSQL operations for subscription suspension state.

Suspension allows temporarily disabling diff registration for specific
targets/subtargets during bulk operations (imports, migrations).
"""

import logging
from datetime import UTC, datetime

from .connection import get_connection

logger = logging.getLogger(__name__)


class DbSubscriptionSuspension:
    """Database operations for subscription suspension state."""

    def __init__(self, actor_id: str) -> None:
        self._actor_id = actor_id

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if a target/subtarget is currently suspended."""
        subtarget_value = subtarget or ""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM subscription_suspensions
                        WHERE id = %s AND target = %s AND subtarget = %s
                        """,
                        (self._actor_id, target, subtarget_value),
                    )
                    return cur.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking suspension for {self._actor_id}: {e}")
            return False

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration. Returns True if newly suspended."""
        if self.is_suspended(target, subtarget):
            return False

        subtarget_value = subtarget or ""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO subscription_suspensions
                            (id, target, subtarget, suspended_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            self._actor_id,
                            target,
                            subtarget_value,
                            datetime.now(UTC),
                        ),
                    )
                conn.commit()
            logger.info(
                f"Suspended subscriptions for {self._actor_id}/{target}"
                f"{'/' + subtarget if subtarget else ''}"
            )
            return True
        except Exception as e:
            logger.error(f"Error suspending for {self._actor_id}: {e}")
            return False

    def resume(self, target: str, subtarget: str | None = None) -> bool:
        """Resume diff registration. Returns True if was suspended."""
        subtarget_value = subtarget or ""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM subscription_suspensions
                        WHERE id = %s AND target = %s AND subtarget = %s
                        """,
                        (self._actor_id, target, subtarget_value),
                    )
                    deleted = cur.rowcount > 0
                conn.commit()

            if deleted:
                logger.info(
                    f"Resumed subscriptions for {self._actor_id}/{target}"
                    f"{'/' + subtarget if subtarget else ''}"
                )
            return deleted
        except Exception as e:
            logger.error(f"Error resuming for {self._actor_id}: {e}")
            return False

    def get_all_suspended(self) -> list[tuple[str, str | None]]:
        """Get all currently suspended target/subtarget pairs."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT target, subtarget FROM subscription_suspensions
                        WHERE id = %s
                        """,
                        (self._actor_id,),
                    )
                    results: list[tuple[str, str | None]] = []
                    for row in cur.fetchall():
                        target = row[0]
                        subtarget = row[1] if row[1] else None
                        results.append((target, subtarget))
                    return results
        except Exception as e:
            logger.error(f"Error getting suspensions for {self._actor_id}: {e}")
            return []

    def delete_all(self) -> bool:
        """Delete all suspensions for this actor (cleanup on actor delete)."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM subscription_suspensions
                        WHERE id = %s
                        """,
                        (self._actor_id,),
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting suspensions for {self._actor_id}: {e}")
            return False
