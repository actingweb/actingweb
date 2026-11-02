"""
Callback processor for subscription callbacks.

Handles sequencing, deduplication, and resync per ActingWeb protocol v1.4.
"""

import asyncio
import copy
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from .db.exceptions import DbError

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
    # Another delivery holds a live claim on this sequence and is running its
    # handler: not handled yet, so the caller must not acknowledge (clear) it.
    IN_PROGRESS = "in_progress"


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

    # How long a claim on a batch (see ``_claim``) keeps other deliveries of
    # its sequences out. A delivery that crashed while holding one is taken
    # over after this by the next delivery of those sequences (a poll or a
    # gap resync), so they are not hidden for good. Limits: the lease is not
    # renewed, so a handler that runs longer can overlap a second delivery
    # of its batch; and it compares the reading process's clock with the
    # claiming one's, so the processes need synchronised clocks.
    CLAIM_LEASE_SECONDS = 60.0

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

    def _read_state_row(
        self, peer_id: str, subscription_id: str
    ) -> dict[str, Any] | None:
        """The state row exactly as stored (a deep copy), or ``None`` when
        there is none. The compare-and-swap compares against this, never
        against a defaulted or modified dict. Raises ``DbError`` on a fault."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        attr = db.get_attr(name=self._get_state_key(peer_id, subscription_id))
        data = attr.get("data") if attr else None
        return copy.deepcopy(data) if isinstance(data, dict) else None

    def _cas_state(
        self,
        peer_id: str,
        subscription_id: str,
        read_row: dict[str, Any] | None,
        new_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Replace the state row ``read_row`` with ``new_state``, atomically.

        Returns the row written (with its per-write ``nonce``) when this call
        won, ``None`` when another writer changed the row first. The nonce
        makes two identical writes distinct (``create_attr_if_absent`` lets
        identical data both win). ``conditional_update_attr`` answers False
        for a lost race and for a fault alike, so a False is re-read
        strictly: the row this call wrote means a retried write that landed,
        another row means a lost race, the row as read means neither (a
        fault). Raises ``DbError`` on a fault.
        """
        from .attribute import Attributes

        name = self._get_state_key(peer_id, subscription_id)
        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        written = {**new_state, "nonce": uuid.uuid4().hex}
        if read_row is None:
            # Raises DbError on a fault; False when a row exists now.
            return (
                written if db.create_attr_if_absent(name=name, data=written) else None
            )
        if db.conditional_update_attr(name=name, old_data=read_row, new_data=written):
            return written
        backend = db.dbprop
        if backend is None:
            raise DbError("callback state", self._actor.id)
        row = backend.get_attr_strict(
            actor_id=self._actor.id, bucket=self._state_bucket, name=name
        )
        current = row.get("data") if isinstance(row, dict) else None
        if current == written:
            return written
        if current != read_row:
            return None
        raise DbError("callback state", self._actor.id)

    def _claim(
        self,
        peer_id: str,
        subscription_id: str,
        read_row: dict[str, Any] | None,
        through_seq: int,
    ) -> dict[str, Any] | None:
        """Claim the sequences up to ``through_seq`` for this delivery: a
        concurrent delivery of any of them then reads them as handled."""
        state = dict(read_row or {})
        state["version"] = int(state.get("version", 0) or 0) + 1
        state["resync_pending"] = False
        state["claimed_seq"] = through_seq
        state["claimed_at"] = time.time()
        return self._cas_state(peer_id, subscription_id, read_row, state)

    def precheck(
        self, peer_id: str, subscription_id: str, sequence: int
    ) -> ProcessResult | None:
        """``DUPLICATE`` for a sequence already handled, ``IN_PROGRESS`` for
        one inside another delivery's live claim, else None. Read-only: a
        caller about to fetch a low-granularity diff (which the publisher
        deletes on the fetch) asks first. Raises ``DbError`` on a fault."""
        row = self._read_state_row(peer_id, subscription_id)
        last_seq = self._get_last_seq(peer_id, subscription_id)
        if sequence <= last_seq:
            return ProcessResult.DUPLICATE
        if sequence <= self._live_claim(dict(row or {}), last_seq):
            return ProcessResult.IN_PROGRESS
        return None

    def _live_claim(self, state: dict[str, Any], last_seq: int) -> int:
        """The sequence another delivery has claimed beyond ``last_seq`` and
        may still be handling, or 0 when there is none (or its lease ran
        out: the delivery that took it is treated as gone)."""
        claimed = int(state.get("claimed_seq", 0) or 0)
        if claimed <= last_seq:
            return 0
        claimed_at = state.get("claimed_at")
        if not isinstance(claimed_at, int | float):
            return 0
        if time.time() - claimed_at >= self.CLAIM_LEASE_SECONDS:
            return 0
        return claimed

    def _release_claim(
        self,
        peer_id: str,
        subscription_id: str,
        claimed_row: dict[str, Any],
        last_seq: int,
    ) -> None:
        """Hand back a claim whose handler raised ``DbError``, so the next
        delivery of the batch (a poll, a gap resync) runs the handler again.
        Best effort: a claim left behind holds its sequences until its lease
        runs out."""
        state = dict(claimed_row)
        state.pop("nonce", None)
        state["version"] = int(state.get("version", 0) or 0) + 1
        state["claimed_seq"] = last_seq
        try:
            if self._cas_state(peer_id, subscription_id, claimed_row, state) is None:
                logger.error(
                    f"Releasing the claim on {peer_id}:{subscription_id} lost a "
                    "race; its sequences wait for a resync"
                )
        except DbError as e:  # folds DbError: best effort; caller re-raises
            logger.error(
                f"Releasing the claim on {peer_id}:{subscription_id} faulted: {e}"
            )

    def _update_last_seq(
        self, peer_id: str, subscription_id: str, new_seq: int
    ) -> bool:
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
        except DbError:
            raise
        except Exception as e:
            logger.error(
                f"Failed to update subscription {subscription_id} sequence: {e}"
            )
            return False

    def _reset_state(
        self, peer_id: str, subscription_id: str, state: dict[str, Any]
    ) -> None:
        """Replace the state row unconditionally (the resync reset). The
        version still only grows and ``claimed_seq`` goes back to 0, so a
        compare-and-swap that read the row before the reset loses; every
        other write goes through :meth:`_cas_state`."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        attr = db.get_attr(name=self._get_state_key(peer_id, subscription_id))
        current = attr.get("data") if attr else None
        state["version"] = int((current or {}).get("version", 0) or 0) + 1
        state["claimed_seq"] = 0
        state["nonce"] = uuid.uuid4().hex
        db.set_attr(name=self._get_state_key(peer_id, subscription_id), data=state)

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
        self,
        peer_id: str,
        subscription_id: str,
        callback: dict[str, Any],
        after_seq: int | None = None,
    ) -> bool:
        """Add callback to pending queue. Returns False if queue full.

        ``after_seq``: the last processed sequence; entries at or below it are
        processed leftovers and neither count toward the limit nor stay.
        """
        pending = self._get_pending(peer_id, subscription_id)
        if after_seq is not None:
            pending = [c for c in pending if (c.get("sequence") or 0) > after_seq]

        if len(pending) >= self._max_pending:
            return False  # Back-pressure

        # Add with timestamp for gap timeout detection
        callback["_received_at"] = time.time()
        pending.append(callback)
        pending.sort(key=lambda c: c.get("sequence", 0))

        self._set_pending(peer_id, subscription_id, pending)
        return True

    def _prune_pending(
        self, peer_id: str, subscription_id: str, through_seq: int
    ) -> None:
        """Remove every pending callback at or below ``through_seq`` in one
        write: they are processed, and the sequence record says so."""
        pending = self._get_pending(peer_id, subscription_id)
        kept = [c for c in pending if (c.get("sequence") or 0) > through_seq]
        if len(kept) != len(pending):
            self._set_pending(peer_id, subscription_id, kept)

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
            row = self._read_state_row(peer_id, subscription_id)
            state = dict(row) if row else {"version": 0, "resync_pending": False}
            last_seq = self._get_last_seq(peer_id, subscription_id)
            # A delivery that won the claim and is still running its handler
            # has claimed sequences above last_seq.
            claimed = self._live_claim(state, last_seq)

            # Check for duplicate
            if sequence <= last_seq:
                logger.debug(
                    f"Duplicate callback: seq={sequence} <= last_seq={last_seq}"
                )
                return ProcessResult.DUPLICATE
            if sequence <= claimed:
                # Not handled yet: the other delivery may still fail. The
                # caller answers so that the publisher keeps the diff.
                logger.debug(
                    f"Callback in progress: seq={sequence} <= claimed={claimed}"
                )
                return ProcessResult.IN_PROGRESS

            # Check for gap
            if sequence > last_seq + 1:
                # Gap detected - add to pending
                pending = [
                    c
                    for c in self._get_pending(peer_id, subscription_id)
                    # Entries at or below last_seq are processed leftovers.
                    if (c.get("sequence") or 0) > last_seq
                ]

                # Check gap timeout on existing pending. Not while another
                # delivery holds a live claim: its sequence write is the
                # progress the gap is waiting for.
                if not claimed and self._check_gap_timeout(pending):
                    logger.warning(
                        f"Gap timeout exceeded for {peer_id}:{subscription_id}, "
                        f"triggering resync"
                    )
                    # Mark resync pending and clear queue. A lost race means
                    # another delivery changed the state: read it again.
                    marked = dict(state)
                    marked["version"] = int(state.get("version", 0) or 0) + 1
                    marked["resync_pending"] = True
                    marked["claimed_seq"] = 0
                    if self._cas_state(peer_id, subscription_id, row, marked) is None:
                        await asyncio.sleep(self._retry_backoff * (2**attempt))
                        continue
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
                if not self._add_pending(
                    peer_id, subscription_id, callback_data, after_seq=last_seq
                ):
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

            # Check pending for consecutive sequences. The drained ones are
            # collected here and removed from pending only after the state
            # write below succeeds: removing them first lost them when that
            # write faulted or lost the optimistic lock and retried.
            pending = [
                c
                for c in self._get_pending(peer_id, subscription_id)
                # Entries at or below last_seq are processed leftovers.
                if (c.get("sequence") or 0) > last_seq
            ]
            by_seq = {c.get("sequence"): c for c in pending}
            next_seq = sequence + 1
            drained: list[int] = []
            while next_seq in by_seq:
                next_callback = by_seq[next_seq]
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
                drained.append(next_seq)
                next_seq += 1

            # Claim the batch FIRST (a compare-and-swap on the state row): a
            # concurrent delivery of any of these sequences then reads them
            # as handled instead of running the handler a second time.
            claimed_row = self._claim(
                peer_id, subscription_id, row, callbacks_to_process[-1].sequence
            )
            if claimed_row is None:
                # Another delivery changed the state first - read it again
                logger.debug(f"Version conflict, retrying (attempt {attempt + 1})")
                await asyncio.sleep(self._retry_backoff * (2**attempt))
                continue

            # Invoke handler for all callbacks in order
            if handler:
                for cb in callbacks_to_process:
                    try:
                        await handler(cb)
                    except DbError:
                        self._release_claim(
                            peer_id, subscription_id, claimed_row, last_seq
                        )
                        # The library's own storage write (auto-storage in the
                        # handler) faulted, and the sequence has not advanced.
                        # The 503 leaves the diff uncleared on the publisher,
                        # which does not retry (the protocol's at-most-once
                        # rule): it comes back through a poll or a gap resync,
                        # which runs the handler again, so data the handler
                        # wrote before the fault can be applied twice. The
                        # consumer data hooks inside the handler fold their own
                        # errors; a legacy callback hook's DbError arrives
                        # here too and aborts the rest of the batch.
                        raise
                    except Exception as e:  # folds DbError: handled by the clause above
                        # Log with full traceback for debugging, but continue
                        # processing - at-most-once semantics means we don't retry
                        logger.error(
                            f"Handler error for seq={cb.sequence}: {e}", exc_info=True
                        )

            # Update sequence in subscription record AFTER successful processing
            # This prevents duplicate detection on retry and ensures sequence only
            # advances after the callback has been fully processed
            new_last_seq = callbacks_to_process[-1].sequence
            try:
                recorded = self._update_last_seq(peer_id, subscription_id, new_last_seq)
            except DbError as e:  # folds DbError: at-most-once: handlers already ran
                # The handlers have run: a 503 now would leave the diff
                # uncleared, and the next poll or resync would run them again.
                # Keep at-most-once delivery: log it and answer PROCESSED. The
                # stale sequence makes the next callback look like a gap,
                # which the gap timeout resyncs; a subscription with no next
                # callback waits until one arrives.
                logger.error(
                    f"Sequence write to {new_last_seq} faulted after processing: {e}"
                )
                recorded = True
            if recorded:
                # The drained callbacks are processed: they leave pending in
                # one write, best effort. A later read skips them only if the
                # sequence write above landed; if both faulted they can run
                # again (filed in the subscriber hardening todo).
                if drained:
                    try:
                        self._prune_pending(peer_id, subscription_id, new_last_seq)
                    except DbError as e:  # folds DbError: best-effort prune
                        logger.error(f"Pruning processed callbacks faulted: {e}")
            else:
                # Failed to update subscription - this is critical but we've already
                # processed the callback, so log error but don't retry. The
                # claim stays (at-most-once, as for a fault above): until its
                # lease runs out a redelivery is answered as in progress
                # instead of running the handlers again.
                logger.error(
                    f"Failed to update sequence to {new_last_seq} after processing - "
                    f"the batch may run again once its claim expires"
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

        # Reset CallbackProcessor-specific state. The version grows (see
        # _reset_state), so a delivery that read the state before the reset
        # loses its compare-and-swap. A resync carries a full baseline, so a
        # second concurrent resync applies the same state again.
        state: dict[str, Any] = {
            "resync_pending": False,
        }
        self._reset_state(peer_id, subscription_id, state)

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
            except DbError:
                raise
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
            except DbError:
                raise
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
        """Clear all state for a subscription (e.g., when subscription/trust deleted).

        Note: We don't reset the subscription sequence here because:
        - If called from Subscription.delete(), the subscription is about to be deleted
        - If called from trust deletion, subscriptions are already deleted
        """
        from .attribute import Attributes

        # Clear callback state attributes
        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        db.delete_attr(name=self._get_state_key(peer_id, subscription_id))
        db.delete_attr(name=self._get_pending_key(peer_id, subscription_id))

    def clear_all_state_for_peer(self, peer_id: str) -> None:
        """Clear all callback state for a peer (when trust deleted).

        Note: We don't reset subscription sequences here because subscriptions
        are deleted before this method is called in delete_reciprocal_trust().
        """
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )

        # Get all attributes in bucket and delete those for this peer
        all_attrs = db.get_bucket(strict=False) or {}
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
            row = self._read_state_row(peer_id, subscription_id)
            state = dict(row) if row else {"version": 0, "resync_pending": False}
            last_seq = self._get_last_seq(peer_id, subscription_id)
            # A delivery that won the claim and is still running its handler
            # has claimed sequences above last_seq.
            claimed = self._live_claim(state, last_seq)

            # Check for duplicate
            if sequence <= last_seq:
                logger.debug(
                    f"Duplicate callback: seq={sequence} <= last_seq={last_seq}"
                )
                return ProcessResult.DUPLICATE
            if sequence <= claimed:
                # Not handled yet: the other delivery may still fail. The
                # caller answers so that the publisher keeps the diff.
                logger.debug(
                    f"Callback in progress: seq={sequence} <= claimed={claimed}"
                )
                return ProcessResult.IN_PROGRESS

            # Check for gap
            if sequence > last_seq + 1:
                # Gap detected - add to pending
                pending = [
                    c
                    for c in self._get_pending(peer_id, subscription_id)
                    # Entries at or below last_seq are processed leftovers.
                    if (c.get("sequence") or 0) > last_seq
                ]

                # Check gap timeout on existing pending. Not while another
                # delivery holds a live claim: its sequence write is the
                # progress the gap is waiting for.
                if not claimed and self._check_gap_timeout(pending):
                    logger.warning(
                        f"Gap timeout exceeded for {peer_id}:{subscription_id}, "
                        f"triggering resync"
                    )
                    # Mark resync pending and clear queue. A lost race means
                    # another delivery changed the state: read it again.
                    marked = dict(state)
                    marked["version"] = int(state.get("version", 0) or 0) + 1
                    marked["resync_pending"] = True
                    marked["claimed_seq"] = 0
                    if self._cas_state(peer_id, subscription_id, row, marked) is None:
                        time.sleep(self._retry_backoff * (2**attempt))
                        continue
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
                if not self._add_pending(
                    peer_id, subscription_id, callback_data, after_seq=last_seq
                ):
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

            # Check pending for consecutive sequences. The drained ones are
            # collected here and removed from pending only after the state
            # write below succeeds: removing them first lost them when that
            # write faulted or lost the optimistic lock and retried.
            pending = [
                c
                for c in self._get_pending(peer_id, subscription_id)
                # Entries at or below last_seq are processed leftovers.
                if (c.get("sequence") or 0) > last_seq
            ]
            by_seq = {c.get("sequence"): c for c in pending}
            next_seq = sequence + 1
            drained: list[int] = []
            while next_seq in by_seq:
                next_callback = by_seq[next_seq]
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
                drained.append(next_seq)
                next_seq += 1

            # Claim the batch FIRST (a compare-and-swap on the state row): a
            # concurrent delivery of any of these sequences then reads them
            # as handled instead of running the handler a second time.
            claimed_row = self._claim(
                peer_id, subscription_id, row, callbacks_to_process[-1].sequence
            )
            if claimed_row is None:
                # Another delivery changed the state first - read it again
                logger.debug(f"Version conflict, retrying (attempt {attempt + 1})")
                time.sleep(self._retry_backoff * (2**attempt))
                continue

            # Invoke handler for all callbacks in order
            if handler:
                for cb in callbacks_to_process:
                    try:
                        handler(cb)
                    except DbError:
                        self._release_claim(
                            peer_id, subscription_id, claimed_row, last_seq
                        )
                        # The library's own storage write (auto-storage in the
                        # handler) faulted, and the sequence has not advanced.
                        # The 503 leaves the diff uncleared on the publisher,
                        # which does not retry (the protocol's at-most-once
                        # rule): it comes back through a poll or a gap resync,
                        # which runs the handler again, so data the handler
                        # wrote before the fault can be applied twice. The
                        # consumer data hooks inside the handler fold their own
                        # errors; a legacy callback hook's DbError arrives
                        # here too and aborts the rest of the batch.
                        raise
                    except Exception as e:  # folds DbError: handled by the clause above
                        # Log with full traceback for debugging, but continue
                        # processing - at-most-once semantics means we don't retry
                        logger.error(
                            f"Handler error for seq={cb.sequence}: {e}", exc_info=True
                        )

            # Update sequence in subscription record AFTER successful processing
            # This prevents duplicate detection on retry and ensures sequence only
            # advances after the callback has been fully processed
            new_last_seq = callbacks_to_process[-1].sequence
            try:
                recorded = self._update_last_seq(peer_id, subscription_id, new_last_seq)
            except DbError as e:  # folds DbError: at-most-once: handlers already ran
                # The handlers have run: a 503 now would leave the diff
                # uncleared, and the next poll or resync would run them again.
                # Keep at-most-once delivery: log it and answer PROCESSED. The
                # stale sequence makes the next callback look like a gap,
                # which the gap timeout resyncs; a subscription with no next
                # callback waits until one arrives.
                logger.error(
                    f"Sequence write to {new_last_seq} faulted after processing: {e}"
                )
                recorded = True
            if recorded:
                # The drained callbacks are processed: they leave pending in
                # one write, best effort. A later read skips them only if the
                # sequence write above landed; if both faulted they can run
                # again (filed in the subscriber hardening todo).
                if drained:
                    try:
                        self._prune_pending(peer_id, subscription_id, new_last_seq)
                    except DbError as e:  # folds DbError: best-effort prune
                        logger.error(f"Pruning processed callbacks faulted: {e}")
            else:
                # Failed to update subscription - this is critical but we've already
                # processed the callback, so log error but don't retry. The
                # claim stays (at-most-once, as for a fault above): until its
                # lease runs out a redelivery is answered as in progress
                # instead of running the handlers again.
                logger.error(
                    f"Failed to update sequence to {new_last_seq} after processing - "
                    f"the batch may run again once its claim expires"
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

        # Reset CallbackProcessor-specific state. The version grows (see
        # _reset_state), so a delivery that read the state before the reset
        # loses its compare-and-swap. A resync carries a full baseline, so a
        # second concurrent resync applies the same state again.
        state: dict[str, Any] = {
            "resync_pending": False,
        }
        self._reset_state(peer_id, subscription_id, state)

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
            except DbError:
                raise
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
            except DbError:
                raise
            except Exception as e:
                logger.error(f"Permission handler error: {e}", exc_info=True)

        return ProcessResult.PROCESSED
