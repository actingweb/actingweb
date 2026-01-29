"""
Callback processor for subscription callbacks.

Handles sequencing, deduplication, and resync per ActingWeb protocol v1.4.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


class ProcessResult(Enum):
    """Result of processing a callback."""

    PROCESSED = "processed"  # Callback was processed successfully
    DUPLICATE = "duplicate"  # Callback was a duplicate (already processed)
    PENDING = "pending"  # Callback stored in pending queue (gap detected)
    RESYNC_TRIGGERED = "resync_triggered"  # Gap timeout exceeded, resync needed
    REJECTED = "rejected"  # Callback rejected (back-pressure)


class CallbackType(Enum):
    """Type of callback."""

    DIFF = "diff"
    RESYNC = "resync"
    PERMISSION = "permission"  # Permission update callback (no sequencing)


@dataclass
class ProcessedCallback:
    """Represents a processed callback ready for the handler."""

    peer_id: str
    subscription_id: str
    sequence: int
    callback_type: CallbackType
    data: dict[str, Any]
    timestamp: str


class CallbackProcessor:
    """
    Processes inbound subscription callbacks per ActingWeb protocol v1.4.

    Handles:
    - Sequence tracking and gap detection
    - Duplicate filtering
    - Resync callback processing
    - Back-pressure via pending queue limits

    Storage: Uses actor's internal attributes (bucket: _callback_state).
    """

    def __init__(
        self,
        actor: "ActorInterface",
        gap_timeout_seconds: float = 5.0,
        max_pending: int = 100,
        max_retries: int = 3,
        retry_backoff_base: float = 0.5,
    ) -> None:
        """
        Initialize callback processor.

        Args:
            actor: The actor receiving callbacks
            gap_timeout_seconds: Time before triggering resync on sequence gap
            max_pending: Max pending callbacks before rejecting (back-pressure)
            max_retries: Max retries for optimistic locking conflicts
            retry_backoff_base: Base delay for exponential backoff
        """
        self._actor = actor
        self._gap_timeout = gap_timeout_seconds
        self._max_pending = max_pending
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff_base
        self._state_bucket = "_callback_state"

    def _get_state_key(self, peer_id: str, subscription_id: str) -> str:
        """Get attribute key for callback state."""
        return f"state:{peer_id}:{subscription_id}"

    def _get_pending_key(self, peer_id: str, subscription_id: str) -> str:
        """Get attribute key for pending callbacks."""
        return f"pending:{peer_id}:{subscription_id}"

    def _get_last_seq(self, peer_id: str, subscription_id: str) -> int:
        """Get last processed sequence from subscription record (single source of truth).

        Returns:
            Last processed sequence number, or 0 if subscription doesn't exist
        """
        from .subscription import Subscription

        sub = Subscription(
            actor_id=self._actor.id,
            peerid=peer_id,
            subid=subscription_id,
            callback=True,
            config=self._actor.config,
        )

        if not sub.handle:
            return 0

        # Get subscription data from the Subscription object
        sub_data = sub.get()
        return sub_data.get("sequence", 0)

    def _get_state(self, peer_id: str, subscription_id: str) -> dict[str, Any]:
        """Get callback state from storage.

        Note: last_seq is now read from subscription record, not stored here.
        This method returns only CallbackProcessor-specific state.
        """
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        attr = db.get_attr(name=self._get_state_key(peer_id, subscription_id))
        # get_attr returns {"data": ..., "timestamp": ...} or None
        state = attr.get("data") if attr else None
        return state or {"version": 0, "resync_pending": False}

    def _update_last_seq(self, peer_id: str, subscription_id: str, new_seq: int) -> bool:
        """Update subscription sequence (single source of truth for last processed seq).

        Returns:
            True if update succeeded, False otherwise
        """
        from .subscription import Subscription

        try:
            sub = Subscription(
                actor_id=self._actor.id,
                peerid=peer_id,
                subid=subscription_id,
                callback=True,
                config=self._actor.config,
            )

            if not sub.handle:
                logger.warning(
                    f"Cannot update sequence for non-existent subscription {subscription_id}"
                )
                return False

            sub.handle.modify(seqnr=new_seq)
            logger.debug(
                f"Updated subscription {subscription_id} sequence to {new_seq} "
                f"(via CallbackProcessor)"
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to update subscription {subscription_id} sequence: {e}"
            )
            return False

    def _set_state(
        self,
        peer_id: str,
        subscription_id: str,
        state: dict[str, Any],
        expected_version: int | None = None,
    ) -> bool:
        """Set callback state with optimistic locking.

        Note: last_seq is no longer stored here - it's read/written from subscription record.
        """
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )

        if expected_version is not None:
            # Check current version
            attr = db.get_attr(name=self._get_state_key(peer_id, subscription_id))
            current = attr.get("data") if attr else None
            current_version = (current or {}).get("version", 0)
            if current_version != expected_version:
                return False  # Version conflict

        # Increment version
        state["version"] = state.get("version", 0) + 1

        db.set_attr(name=self._get_state_key(peer_id, subscription_id), data=state)
        return True

    def _get_pending(self, peer_id: str, subscription_id: str) -> list[dict[str, Any]]:
        """Get pending callbacks from storage."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        attr = db.get_attr(name=self._get_pending_key(peer_id, subscription_id))
        pending = attr.get("data") if attr else None
        return pending.get("callbacks", []) if pending else []

    def _set_pending(
        self, peer_id: str, subscription_id: str, callbacks: list[dict[str, Any]]
    ) -> None:
        """Set pending callbacks in storage."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        db.set_attr(
            name=self._get_pending_key(peer_id, subscription_id),
            data={"callbacks": callbacks},
        )

    def _add_pending(
        self, peer_id: str, subscription_id: str, callback: dict[str, Any]
    ) -> bool:
        """Add callback to pending queue. Returns False if queue full."""
        pending = self._get_pending(peer_id, subscription_id)

        if len(pending) >= self._max_pending:
            return False  # Back-pressure

        # Add with timestamp for gap timeout detection
        callback["_received_at"] = time.time()
        pending.append(callback)
        pending.sort(key=lambda c: c.get("sequence", 0))

        self._set_pending(peer_id, subscription_id, pending)
        return True

    def _remove_pending(
        self, peer_id: str, subscription_id: str, sequence: int
    ) -> None:
        """Remove callback from pending by sequence."""
        pending = self._get_pending(peer_id, subscription_id)
        pending = [c for c in pending if c.get("sequence") != sequence]
        self._set_pending(peer_id, subscription_id, pending)

    def _clear_pending(self, peer_id: str, subscription_id: str) -> None:
        """Clear all pending callbacks."""
        self._set_pending(peer_id, subscription_id, [])

    def _check_gap_timeout(self, pending: list[dict[str, Any]]) -> bool:
        """Check if oldest pending callback has exceeded gap timeout."""
        if not pending:
            return False

        oldest = min(c.get("_received_at", time.time()) for c in pending)
        return (time.time() - oldest) > self._gap_timeout

    async def process_callback(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: dict[str, Any],
        callback_type: str = "diff",
        handler: Callable[[ProcessedCallback], Awaitable[None]] | None = None,
    ) -> ProcessResult:
        """
        Process a callback with automatic sequencing.

        Args:
            peer_id: ID of the peer sending the callback
            subscription_id: Subscription identifier
            sequence: Sequence number from callback
            data: Callback data payload
            callback_type: "diff" or "resync"
            handler: Optional async handler to invoke for valid callbacks

        Returns:
            ProcessResult indicating what happened
        """
        # Handle resync callbacks specially
        if callback_type == "resync":
            return await self._handle_resync(
                peer_id, subscription_id, sequence, data, handler
            )

        # Handle permission callbacks - bypass sequencing entirely
        if callback_type == "permission":
            return await self._handle_permission(peer_id, data, handler)

        # Retry loop for optimistic locking
        for attempt in range(self._max_retries):
            state = self._get_state(peer_id, subscription_id)
            last_seq = self._get_last_seq(peer_id, subscription_id)
            version = state.get("version", 0)

            # Check for duplicate
            if sequence <= last_seq:
                logger.debug(
                    f"Duplicate callback: seq={sequence} <= last_seq={last_seq}"
                )
                return ProcessResult.DUPLICATE

            # Check for gap
            if sequence > last_seq + 1:
                # Gap detected - add to pending
                pending = self._get_pending(peer_id, subscription_id)

                # Check gap timeout on existing pending
                if self._check_gap_timeout(pending):
                    logger.warning(
                        f"Gap timeout exceeded for {peer_id}:{subscription_id}, "
                        f"triggering resync"
                    )
                    # Mark resync pending and clear queue
                    state["resync_pending"] = True
                    self._set_state(peer_id, subscription_id, state, version)
                    # Reset sequence to 0 to accept any sequence after resync
                    self._update_last_seq(peer_id, subscription_id, 0)
                    self._clear_pending(peer_id, subscription_id)
                    return ProcessResult.RESYNC_TRIGGERED

                # Add to pending queue
                callback_data = {
                    "sequence": sequence,
                    "data": data,
                    "callback_type": callback_type,
                }
                if not self._add_pending(peer_id, subscription_id, callback_data):
                    logger.warning(
                        f"Pending queue full for {peer_id}:{subscription_id}"
                    )
                    return ProcessResult.REJECTED

                logger.debug(
                    f"Gap detected: seq={sequence}, last_seq={last_seq}, "
                    f"added to pending"
                )
                return ProcessResult.PENDING

            # Sequence is correct (last_seq + 1)
            # Process this callback and any consecutive pending
            callbacks_to_process = [
                ProcessedCallback(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    sequence=sequence,
                    callback_type=CallbackType.DIFF,
                    data=data,
                    timestamp=data.get("timestamp", ""),
                )
            ]

            # Check pending for consecutive sequences
            pending = self._get_pending(peer_id, subscription_id)
            next_seq = sequence + 1
            while pending:
                next_callback = next(
                    (c for c in pending if c.get("sequence") == next_seq), None
                )
                if not next_callback:
                    break
                callbacks_to_process.append(
                    ProcessedCallback(
                        peer_id=peer_id,
                        subscription_id=subscription_id,
                        sequence=next_seq,
                        callback_type=CallbackType.DIFF,
                        data=next_callback["data"],
                        timestamp=next_callback["data"].get("timestamp", ""),
                    )
                )
                self._remove_pending(peer_id, subscription_id, next_seq)
                pending = self._get_pending(peer_id, subscription_id)
                next_seq += 1

            # Update CallbackProcessor-specific state FIRST (optimistic lock)
            state["resync_pending"] = False
            if not self._set_state(peer_id, subscription_id, state, version):
                # Version conflict - retry
                logger.debug(f"Version conflict, retrying (attempt {attempt + 1})")
                time.sleep(self._retry_backoff * (2**attempt))
                continue

            # Invoke handler for all callbacks in order
            if handler:
                for cb in callbacks_to_process:
                    try:
                        await handler(cb)
                    except Exception as e:
                        # Log with full traceback for debugging, but continue
                        # processing - at-most-once semantics means we don't retry
                        logger.error(
                            f"Handler error for seq={cb.sequence}: {e}", exc_info=True
                        )

            # Update sequence in subscription record AFTER successful processing
            # This prevents duplicate detection on retry and ensures sequence only
            # advances after the callback has been fully processed
            new_last_seq = callbacks_to_process[-1].sequence
            if not self._update_last_seq(peer_id, subscription_id, new_last_seq):
                # Failed to update subscription - this is critical but we've already
                # processed the callback, so log error but don't retry
                logger.error(
                    f"Failed to update sequence to {new_last_seq} after processing - "
                    f"callback may be reprocessed on next invocation"
                )

            return ProcessResult.PROCESSED

        # Exhausted retries
        logger.error(f"Failed to process callback after {self._max_retries} retries")
        return ProcessResult.REJECTED

    async def _handle_resync(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: dict[str, Any],
        handler: Callable[[ProcessedCallback], Awaitable[None]] | None,
    ) -> ProcessResult:
        """Handle a resync callback from the protocol."""
        logger.info(f"Processing resync callback for {peer_id}:{subscription_id}")

        # Clear pending queue
        self._clear_pending(peer_id, subscription_id)

        # Reset CallbackProcessor-specific state
        state = {
            "version": 0,
            "resync_pending": False,
        }
        self._set_state(peer_id, subscription_id, state, expected_version=None)

        # Invoke handler with resync data
        if handler:
            callback = ProcessedCallback(
                peer_id=peer_id,
                subscription_id=subscription_id,
                sequence=sequence,
                callback_type=CallbackType.RESYNC,
                data=data,
                timestamp=data.get("timestamp", ""),
            )
            try:
                await handler(callback)
            except Exception as e:
                # Log with full traceback for debugging
                logger.error(f"Resync handler error: {e}", exc_info=True)

        # Update subscription sequence AFTER successful processing
        self._update_last_seq(peer_id, subscription_id, sequence)

        return ProcessResult.PROCESSED

    async def _handle_permission(
        self,
        peer_id: str,
        data: dict[str, Any],
        handler: Callable[[ProcessedCallback], Awaitable[None]] | None,
    ) -> ProcessResult:
        """Handle a permission callback.

        Permission callbacks bypass sequencing entirely - they are stateless
        and idempotent, containing the full current permissions.
        """
        logger.info(f"Processing permission callback from {peer_id}")

        # Invoke handler with permission data
        if handler:
            callback = ProcessedCallback(
                peer_id=peer_id,
                subscription_id="",  # Not used for permissions
                sequence=0,  # Not used for permissions
                callback_type=CallbackType.PERMISSION,
                data=data,
                timestamp=data.get("timestamp", ""),
            )
            try:
                await handler(callback)
            except Exception as e:
                logger.error(f"Permission handler error: {e}", exc_info=True)

        return ProcessResult.PROCESSED

    def get_state_info(self, peer_id: str, subscription_id: str) -> dict[str, Any]:
        """Get current state information for debugging."""
        state = self._get_state(peer_id, subscription_id)
        pending = self._get_pending(peer_id, subscription_id)
        return {
            "last_seq": self._get_last_seq(peer_id, subscription_id),
            "version": state.get("version", 0),
            "resync_pending": state.get("resync_pending", False),
            "pending_count": len(pending),
            "pending_sequences": [c.get("sequence") for c in pending],
        }

    def clear_state(self, peer_id: str, subscription_id: str) -> None:
        """Clear all state for a subscription (e.g., when trust deleted)."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        db.delete_attr(name=self._get_state_key(peer_id, subscription_id))
        db.delete_attr(name=self._get_pending_key(peer_id, subscription_id))

    def clear_all_state_for_peer(self, peer_id: str) -> None:
        """Clear all callback state for a peer (when trust deleted)."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )

        # Get all attributes in bucket and delete those for this peer
        all_attrs = db.get_bucket() or {}
        for attr_name in list(all_attrs.keys()):
            if f":{peer_id}:" in attr_name:
                db.delete_attr(name=attr_name)

    def process_callback_sync(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: dict[str, Any],
        callback_type: str = "diff",
        handler: Callable[[ProcessedCallback], None] | None = None,
    ) -> ProcessResult:
        """
        Synchronous version of process_callback.

        Args:
            peer_id: ID of the peer sending the callback
            subscription_id: Subscription identifier
            sequence: Sequence number from callback
            data: Callback data payload
            callback_type: "diff" or "resync"
            handler: Optional sync handler to invoke for valid callbacks

        Returns:
            ProcessResult indicating what happened
        """
        # Handle resync callbacks specially
        if callback_type == "resync":
            return self._handle_resync_sync(
                peer_id, subscription_id, sequence, data, handler
            )

        # Handle permission callbacks - bypass sequencing entirely
        if callback_type == "permission":
            return self._handle_permission_sync(peer_id, data, handler)

        # Retry loop for optimistic locking
        for attempt in range(self._max_retries):
            state = self._get_state(peer_id, subscription_id)
            last_seq = self._get_last_seq(peer_id, subscription_id)
            version = state.get("version", 0)

            # Check for duplicate
            if sequence <= last_seq:
                logger.debug(
                    f"Duplicate callback: seq={sequence} <= last_seq={last_seq}"
                )
                return ProcessResult.DUPLICATE

            # Check for gap
            if sequence > last_seq + 1:
                # Gap detected - add to pending
                pending = self._get_pending(peer_id, subscription_id)

                # Check gap timeout on existing pending
                if self._check_gap_timeout(pending):
                    logger.warning(
                        f"Gap timeout exceeded for {peer_id}:{subscription_id}, "
                        f"triggering resync"
                    )
                    # Mark resync pending and clear queue
                    state["resync_pending"] = True
                    self._set_state(peer_id, subscription_id, state, version)
                    # Reset sequence to 0 to accept any sequence after resync
                    self._update_last_seq(peer_id, subscription_id, 0)
                    self._clear_pending(peer_id, subscription_id)
                    return ProcessResult.RESYNC_TRIGGERED

                # Add to pending queue
                callback_data = {
                    "sequence": sequence,
                    "data": data,
                    "callback_type": callback_type,
                }
                if not self._add_pending(peer_id, subscription_id, callback_data):
                    logger.warning(
                        f"Pending queue full for {peer_id}:{subscription_id}"
                    )
                    return ProcessResult.REJECTED

                logger.debug(
                    f"Gap detected: seq={sequence}, last_seq={last_seq}, "
                    f"added to pending"
                )
                return ProcessResult.PENDING

            # Sequence is correct (last_seq + 1)
            # Process this callback and any consecutive pending
            callbacks_to_process = [
                ProcessedCallback(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    sequence=sequence,
                    callback_type=CallbackType.DIFF,
                    data=data,
                    timestamp=data.get("timestamp", ""),
                )
            ]

            # Check pending for consecutive sequences
            pending = self._get_pending(peer_id, subscription_id)
            next_seq = sequence + 1
            while pending:
                next_callback = next(
                    (c for c in pending if c.get("sequence") == next_seq), None
                )
                if not next_callback:
                    break
                callbacks_to_process.append(
                    ProcessedCallback(
                        peer_id=peer_id,
                        subscription_id=subscription_id,
                        sequence=next_seq,
                        callback_type=CallbackType.DIFF,
                        data=next_callback["data"],
                        timestamp=next_callback["data"].get("timestamp", ""),
                    )
                )
                self._remove_pending(peer_id, subscription_id, next_seq)
                pending = self._get_pending(peer_id, subscription_id)
                next_seq += 1

            # Update CallbackProcessor-specific state FIRST (optimistic lock)
            state["resync_pending"] = False
            if not self._set_state(peer_id, subscription_id, state, version):
                # Version conflict - retry
                logger.debug(f"Version conflict, retrying (attempt {attempt + 1})")
                time.sleep(self._retry_backoff * (2**attempt))
                continue

            # Invoke handler for all callbacks in order
            if handler:
                for cb in callbacks_to_process:
                    try:
                        handler(cb)
                    except Exception as e:
                        # Log with full traceback for debugging, but continue
                        # processing - at-most-once semantics means we don't retry
                        logger.error(
                            f"Handler error for seq={cb.sequence}: {e}", exc_info=True
                        )

            # Update sequence in subscription record AFTER successful processing
            # This prevents duplicate detection on retry and ensures sequence only
            # advances after the callback has been fully processed
            new_last_seq = callbacks_to_process[-1].sequence
            if not self._update_last_seq(peer_id, subscription_id, new_last_seq):
                # Failed to update subscription - this is critical but we've already
                # processed the callback, so log error but don't retry
                logger.error(
                    f"Failed to update sequence to {new_last_seq} after processing - "
                    f"callback may be reprocessed on next invocation"
                )

            return ProcessResult.PROCESSED

        # Exhausted retries
        logger.error(f"Failed to process callback after {self._max_retries} retries")
        return ProcessResult.REJECTED

    def _handle_resync_sync(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: dict[str, Any],
        handler: Callable[[ProcessedCallback], None] | None,
    ) -> ProcessResult:
        """Handle a resync callback from the protocol (sync version)."""
        logger.info(f"Processing resync callback for {peer_id}:{subscription_id}")

        # Clear pending queue
        self._clear_pending(peer_id, subscription_id)

        # Reset CallbackProcessor-specific state
        state = {
            "version": 0,
            "resync_pending": False,
        }
        self._set_state(peer_id, subscription_id, state, expected_version=None)

        # Invoke handler with resync data
        if handler:
            callback = ProcessedCallback(
                peer_id=peer_id,
                subscription_id=subscription_id,
                sequence=sequence,
                callback_type=CallbackType.RESYNC,
                data=data,
                timestamp=data.get("timestamp", ""),
            )
            try:
                handler(callback)
            except Exception as e:
                # Log with full traceback for debugging
                logger.error(f"Resync handler error: {e}", exc_info=True)

        # Update subscription sequence AFTER successful processing
        self._update_last_seq(peer_id, subscription_id, sequence)

        return ProcessResult.PROCESSED

    def _handle_permission_sync(
        self,
        peer_id: str,
        data: dict[str, Any],
        handler: Callable[[ProcessedCallback], None] | None,
    ) -> ProcessResult:
        """Handle a permission callback (sync version).

        Permission callbacks bypass sequencing entirely - they are stateless
        and idempotent, containing the full current permissions.
        """
        logger.info(f"Processing permission callback from {peer_id}")

        # Invoke handler with permission data
        if handler:
            callback = ProcessedCallback(
                peer_id=peer_id,
                subscription_id="",  # Not used for permissions
                sequence=0,  # Not used for permissions
                callback_type=CallbackType.PERMISSION,
                data=data,
                timestamp=data.get("timestamp", ""),
            )
            try:
                handler(callback)
            except Exception as e:
                logger.error(f"Permission handler error: {e}", exc_info=True)

        return ProcessResult.PROCESSED
