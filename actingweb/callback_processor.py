"""
Callback processor for subscription callbacks.

Handles sequencing, deduplication, and resync per ActingWeb protocol v1.4.
"""

import asyncio
import copy
import json
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


def _deleted_names(data: Any) -> list[str]:
    """The names a target-level diff deletes: a key whose value is empty,
    or a list's ``delete_all``."""
    if not isinstance(data, dict):
        return []
    names: list[str] = []
    for key, value in data.items():
        name = key[5:] if isinstance(key, str) and key.startswith("list:") else key
        if value == "" or value is None:
            names.append(str(name))
        elif isinstance(value, dict) and value.get("operation") == "delete_all":
            names.append(str(name))
    return names


class ProcessResult(Enum):
    """Result of processing a callback."""

    PROCESSED = "processed"  # Callback was processed successfully
    DUPLICATE = "duplicate"  # Callback was a duplicate (already processed)
    PENDING = "pending"  # Callback stored in pending queue (gap detected)
    RESYNC_TRIGGERED = "resync_triggered"  # Gap timeout exceeded, resync needed
    REJECTED = "rejected"  # Callback rejected (back-pressure)
    # A list diff could not be applied and a rebuild is due: the sequence
    # advanced, the rest of the drained batch was dropped, and the caller
    # runs SubscriptionManager.rebuild_subscription().
    REBUILD = "rebuild"
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
    # An object at target level; a subtarget's value as sent (text, a
    # number, a boolean or "" as well) at subtarget level.
    data: Any
    timestamp: str
    # Set by the handler when the replica could not apply a list diff in
    # this callback (RemotePeerStore's ``out_of_step`` result).
    out_of_step: dict[str, Any] | None = None


class CallbackProcessor:
    """
    Processes inbound subscription callbacks per ActingWeb protocol v1.4.

    Handles:
    - Sequence tracking and gap detection
    - Duplicate filtering
    - Resync callback processing
    - Back-pressure via pending queue limits
    - Callbacks queued behind a delivery in progress: the delivery that
      records its sequence takes them (``_drain``)

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
    # At most one rebuild of a subscription's replica per this many seconds;
    # inside it a further out-of-step diff is logged and the rebuild stays
    # owed.
    REBUILD_INTERVAL_SECONDS = 60.0
    # State-row fields a resync's reset keeps.
    _REBUILD_FIELDS = ("rebuild_owed", "rebuild_lists", "rebuilt_at")
    # A delivery that recorded its sequence takes the callbacks queued behind
    # its claim (``_drain``), one claim and one sequence write per callback:
    # always the first, then at most this many in all and none once this
    # much time has passed since the drain started. The publisher is waiting
    # for the delivery's answer (its read timeout for a diff is 10 seconds):
    # a slow handler plus the drain can pass it, and the publisher then
    # counts a callback that was applied as missed, which a duplicate
    # answers later. What is left stays queued for the next delivery.
    DRAIN_MAX_CALLBACKS = 20
    DRAIN_SECONDS = 5.0
    # Tries of the queue row's compare-and-swap before it is a fault.
    _PENDING_SWAP_TRIES = 5

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
        # The sequence the last batch applied through: a batch stopped for
        # a rebuild drops the callbacks after it, possibly the delivered one.
        self.applied_through: int | None = None

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
        # An owed rebuild and its interval survive a resync (the resync's
        # handler settles them; a reset must not forget them).
        for field in self._REBUILD_FIELDS:
            if isinstance(current, dict) and field in current and field not in state:
                state[field] = current[field]
        state["version"] = int((current or {}).get("version", 0) or 0) + 1
        state["claimed_seq"] = 0
        state["nonce"] = uuid.uuid4().hex
        if not db.set_attr(
            name=self._get_state_key(peer_id, subscription_id), data=state
        ):
            raise DbError("callback state reset", self._actor.id)

    # -- the owed rebuild -----------------------------------------------------

    def _rebuild_due(self, state: dict[str, Any]) -> bool:
        """An owed rebuild whose interval has passed."""
        if not state.get("rebuild_owed"):
            return False
        rebuilt_at = state.get("rebuilt_at")
        if not isinstance(rebuilt_at, int | float):
            return True
        return time.time() - rebuilt_at >= self.REBUILD_INTERVAL_SECONDS

    def _mark_out_of_step(
        self,
        peer_id: str,
        subscription_id: str,
        claimed_row: dict[str, Any],
        through_seq: int,
        lists: list[str],
    ) -> dict[str, Any] | None:
        """Record an owed rebuild from the claimed row in one
        compare-and-swap (modelled on ``_release_claim``): the claim ends at
        ``through_seq`` and the out-of-step lists join the owed ones. Returns
        the row written, or None when the write lost or faulted (logged; the
        next out-of-step diff marks it again)."""
        state = dict(claimed_row)
        state.pop("nonce", None)
        state["version"] = int(state.get("version", 0) or 0) + 1
        state["claimed_seq"] = through_seq
        state["rebuild_owed"] = True
        state["rebuild_lists"] = sorted(
            set(state.get("rebuild_lists") or []) | {n for n in lists if n}
        )
        try:
            written = self._cas_state(peer_id, subscription_id, claimed_row, state)
        except DbError as e:  # folds DbError: best effort, logged
            logger.error(
                f"Recording the owed rebuild of {peer_id}:{subscription_id} "
                f"faulted: {e}"
            )
            return None
        if written is None:
            logger.error(
                f"Recording the owed rebuild of {peer_id}:{subscription_id} lost "
                "a race; the next out-of-step diff records it again"
            )
        return written

    def _whole_target(self, peer_id: str, subscription_id: str) -> bool:
        """Whether the subscription is to the whole target (its diffs are
        keyed by replica name). A read fault answers False: nothing is owed
        from the dropped batch, the rebuild still runs."""
        try:
            sub = self._actor.subscriptions.get_callback_subscription(
                peer_id, subscription_id
            )
        except Exception as e:  # folds DbError: only narrows what is owed
            logger.warning(f"Reading subscription {subscription_id}: {e}")
            return False
        return bool(sub) and not sub.subtarget and not sub.resource

    def _mark_or_owe(
        self,
        peer_id: str,
        subscription_id: str,
        claimed_row: dict[str, Any],
        through_seq: int,
        lists: list[str],
    ) -> bool:
        """Record an owed rebuild; True when one is due now. A mark that lost
        its compare-and-swap or faulted is retried from a fresh read
        (``settle_rebuild``); if that faults too the rebuild runs anyway when
        the claimed row allows (the rebuild settles its own state), so an
        out-of-step replica is never left unmarked and unrebuilt."""
        marked = self._mark_out_of_step(
            peer_id, subscription_id, claimed_row, through_seq, lists
        )
        if marked is not None:
            return self._rebuild_due(marked)
        try:
            self.settle_rebuild(
                peer_id,
                subscription_id,
                rebuilt=False,
                lists=lists,
                claimed_seq=through_seq,
                held_claim=claimed_row.get("claimed_seq"),
            )
            return self._rebuild_due(
                self._read_state_row(peer_id, subscription_id) or {}
            )
        except DbError as e:  # folds DbError: the rebuild below settles it
            logger.error(
                f"Recording the owed rebuild of {peer_id}:{subscription_id} "
                f"faulted again: {e}; rebuilding without the record"
            )
            return self._rebuild_due({**claimed_row, "rebuild_owed": True})

    def begin_rebuild(
        self, peer_id: str, subscription_id: str, *, force: bool = False
    ) -> bool:
        """Reserve a rebuild attempt: one compare-and-swap that sets
        ``rebuilt_at`` to now, whether the attempt then succeeds or not, so a
        failed rebuild is throttled like a successful one and two concurrent
        deliveries do not both rebuild. False when another attempt started
        inside the interval (or won the race); ``force`` reserves regardless
        of the interval. Raises ``DbError`` on a fault."""
        for _ in range(self._max_retries):
            row = self._read_state_row(peer_id, subscription_id)
            if not force and not self._rebuild_due(
                {**(row or {}), "rebuild_owed": True}
            ):
                return False
            state: dict[str, Any] = dict(row or {"version": 0, "resync_pending": False})
            state.pop("nonce", None)
            state["version"] = int(state.get("version", 0) or 0) + 1
            state["rebuild_owed"] = True
            state["rebuilt_at"] = time.time()
            if self._cas_state(peer_id, subscription_id, row, state) is not None:
                return True
            force = False  # a concurrent attempt reserved first
        return False

    def rebuild_state(self, peer_id: str, subscription_id: str) -> dict[str, Any]:
        """``{"owed": bool, "lists": [...], "rebuilt_at": float | None}`` for
        a subscription's replica. Raises ``DbError`` on a fault."""
        row = self._read_state_row(peer_id, subscription_id) or {}
        return {
            "owed": bool(row.get("rebuild_owed")),
            "lists": list(row.get("rebuild_lists") or []),
            "rebuilt_at": row.get("rebuilt_at"),
        }

    def settle_rebuild(
        self,
        peer_id: str,
        subscription_id: str,
        *,
        rebuilt: bool,
        restart_interval: bool = True,
        lists: list[str] | None = None,
        claimed_seq: int | None = None,
        held_claim: int | None = None,
    ) -> bool:
        """After a rebuild (or a resync): ``rebuilt`` clears the owed rebuild
        and, with ``restart_interval``, sets ``rebuilt_at``; otherwise it is
        marked owed (``lists`` join the owed ones). ``claimed_seq`` ends a
        claim there (a batch stopped for the rebuild) when the row still holds
        ``held_claim``, the claim that batch took. Retries a lost
        compare-and-swap a few times. Raises ``DbError`` on a fault."""
        for _ in range(self._max_retries):
            row = self._read_state_row(peer_id, subscription_id)
            state: dict[str, Any] = dict(row or {"version": 0, "resync_pending": False})
            state.pop("nonce", None)
            state["version"] = int(state.get("version", 0) or 0) + 1
            if claimed_seq is not None and (row or {}).get("claimed_seq") == held_claim:
                # Only the claim this batch held (another delivery's claim is
                # not this one's to end).
                state["claimed_seq"] = claimed_seq
            if rebuilt:
                state["rebuild_owed"] = False
                state["rebuild_lists"] = []
                if restart_interval:
                    state["rebuilt_at"] = time.time()
            else:
                state["rebuild_owed"] = True
                if lists:
                    state["rebuild_lists"] = sorted(
                        set(state.get("rebuild_lists") or []) | {n for n in lists if n}
                    )
            if self._cas_state(peer_id, subscription_id, row, state) is not None:
                return True
        return False

    def _settle_after_resync(
        self, peer_id: str, subscription_id: str, *, rebuilt: bool
    ) -> None:
        """A resync's handler returned (``rebuilt``) or failed: settle the
        owed rebuild, best effort, without restarting its interval."""
        try:
            row = self._read_state_row(peer_id, subscription_id) or {}
            if rebuilt and not row.get("rebuild_owed"):
                return
            self.settle_rebuild(
                peer_id, subscription_id, rebuilt=rebuilt, restart_interval=False
            )
        except DbError as e:  # folds DbError: best effort, logged
            logger.error(
                f"Settling the owed rebuild of {peer_id}:{subscription_id} after a "
                f"resync faulted: {e}"
            )

    def _read_pending_row(self, peer_id: str, subscription_id: str) -> Any:
        """The queue row's data exactly as stored (a deep copy), or ``None``
        when there is no row. The compare-and-swap compares against this."""
        from .attribute import Attributes

        db = Attributes(
            actor_id=self._actor.id,
            bucket=self._state_bucket,
            config=self._actor.config,
        )
        attr = db.get_attr(name=self._get_pending_key(peer_id, subscription_id))
        return copy.deepcopy(attr.get("data")) if attr else None

    def _get_pending(self, peer_id: str, subscription_id: str) -> list[dict[str, Any]]:
        """Get pending callbacks from storage."""
        row = self._read_pending_row(peer_id, subscription_id)
        return (row.get("callbacks") or []) if isinstance(row, dict) else []

    def _set_pending(
        self, peer_id: str, subscription_id: str, callbacks: list[dict[str, Any]]
    ) -> None:
        """Replace the queue unconditionally (a resync clears it). A change
        to a queue that is in use goes through :meth:`_swap_pending`."""
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

    def _swap_pending(
        self,
        peer_id: str,
        subscription_id: str,
        change: Callable[[list[dict[str, Any]]], list[dict[str, Any]] | None],
    ) -> None:
        """Change the queue by compare-and-swap. ``change`` gets the stored
        callbacks and returns the new list, or ``None`` to leave the row as
        it is; it is called again on a fresh read when another delivery
        wrote the row first (one delivery queues while another prunes).
        Raises ``DbError`` when the write keeps losing or faults."""
        from .attribute import Attributes

        name = self._get_pending_key(peer_id, subscription_id)
        for _ in range(self._PENDING_SWAP_TRIES):
            row = self._read_pending_row(peer_id, subscription_id)
            stored = (row.get("callbacks") or []) if isinstance(row, dict) else []
            callbacks = change(list(stored))
            if callbacks is None:
                return
            db = Attributes(
                actor_id=self._actor.id,
                bucket=self._state_bucket,
                config=self._actor.config,
            )
            written = {"callbacks": callbacks}
            if row is None:
                # Raises DbError on a fault; False when a row exists now.
                if db.create_attr_if_absent(name=name, data=written):
                    return
            elif db.conditional_update_attr(name=name, old_data=row, new_data=written):
                return
        raise DbError("callback pending queue", self._actor.id)

    def _add_pending(
        self,
        peer_id: str,
        subscription_id: str,
        callback: dict[str, Any],
        after_seq: int | None = None,
    ) -> bool:
        """Add callback to pending queue. Returns False if queue full, or
        the callback carries a non-finite number. A sequence already queued
        is left as it is.

        ``after_seq``: the last processed sequence; entries at or below it are
        processed leftovers and neither count toward the limit nor stay.
        Raises ``DbError`` when the write could not be made.
        """
        try:
            # A NaN or an infinity never compares equal to itself once stored:
            # every later compare-and-swap of the row would lose.
            json.dumps(callback, allow_nan=False)
        except ValueError:
            logger.warning(
                f"Callback seq={callback.get('sequence')} for "
                f"{peer_id}:{subscription_id} carries a number that is not "
                "finite; not queued"
            )
            return False
        # Add with timestamp for gap timeout detection
        callback["_received_at"] = time.time()
        full = False

        def add(pending: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
            nonlocal full
            if after_seq is not None:
                pending = [c for c in pending if (c.get("sequence") or 0) > after_seq]
            if any(c.get("sequence") == callback.get("sequence") for c in pending):
                # Queued already (a redelivery, or this call's own write
                # that landed although it was reported lost): one copy.
                full = False
                return None
            full = len(pending) >= self._max_pending
            if full:
                return None  # Back-pressure
            pending.append(callback)
            pending.sort(key=lambda c: c.get("sequence", 0))
            return pending

        self._swap_pending(peer_id, subscription_id, add)
        return not full

    def _prune_pending(
        self, peer_id: str, subscription_id: str, through_seq: int
    ) -> None:
        """Remove every pending callback at or below ``through_seq`` in one
        write: they are processed, and the sequence record says so."""

        def prune(pending: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
            kept = [c for c in pending if (c.get("sequence") or 0) > through_seq]
            return kept if len(kept) != len(pending) else None

        self._swap_pending(peer_id, subscription_id, prune)

    def _clear_pending(self, peer_id: str, subscription_id: str) -> None:
        """Clear all pending callbacks."""
        self._set_pending(peer_id, subscription_id, [])

    def _check_gap_timeout(self, pending: list[dict[str, Any]]) -> bool:
        """Check if oldest pending callback has exceeded gap timeout."""
        if not pending:
            return False

        oldest = min(c.get("_received_at", time.time()) for c in pending)
        return (time.time() - oldest) > self._gap_timeout

    def _claim_queued(
        self,
        peer_id: str,
        subscription_id: str,
        after_seq: int | None,
    ) -> tuple[list[ProcessedCallback], dict[str, Any], int] | None:
        """Claim the one callback queued next in line: ``([callback], claimed
        row, last sequence)``, or ``None`` when nothing is next, another
        delivery holds a live claim, or the claim was lost (the other
        delivery has it). One callback per claim: its sequence is recorded
        before the next is claimed, so a fault or a lease that runs out
        costs one callback, never a batch.

        ``after_seq`` is the sequence the caller just recorded: with nothing
        queued right after it, the queue is the only read. Otherwise the
        state row, then the sequence, then the queue are read here, in the
        order the in-order path reads them (a resync resets the row before
        it clears the queue, so a claim on a row read first loses to it),
        and the claim is made on that row, never on what the caller read
        earlier. A ``DbError`` is logged and answers ``None``."""
        try:
            if after_seq is not None and after_seq + 1 not in {
                c.get("sequence") for c in self._get_pending(peer_id, subscription_id)
            }:
                return None
            row = self._read_state_row(peer_id, subscription_id)
            last_seq = self._get_last_seq(peer_id, subscription_id)
            if self._live_claim(dict(row or {}), last_seq):
                return None
            entry = next(
                (
                    c
                    for c in self._get_pending(peer_id, subscription_id)
                    if c.get("sequence") == last_seq + 1
                ),
                None,
            )
            if entry is None:
                return None
            data = entry.get("data")
            callback = ProcessedCallback(
                peer_id=peer_id,
                subscription_id=subscription_id,
                sequence=last_seq + 1,
                callback_type=CallbackType.DIFF,
                data=data,
                timestamp=data.get("timestamp", "") if isinstance(data, dict) else "",
            )
            claimed_row = self._claim(peer_id, subscription_id, row, callback.sequence)
        except DbError as e:  # folds DbError: the queue waits for the next delivery
            logger.error(
                f"Reading the queued callbacks of {peer_id}:{subscription_id} "
                f"faulted: {e}"
            )
            return None
        if claimed_row is None:
            return None
        return [callback], claimed_row, last_seq

    def _finish_batch(
        self,
        peer_id: str,
        subscription_id: str,
        batch: list[ProcessedCallback],
        claimed_row: dict[str, Any],
        out_of_step_lists: list[str],
        stop_at: int | None,
        *,
        prune: bool,
    ) -> tuple[ProcessResult, bool]:
        """After a claimed batch's handlers ran: record the sequence, prune
        the queue (``prune``: the batch took callbacks from it) and settle
        what was out of step. Returns the result, and whether the delivery
        may go on to the queue: the sequence write landed, the batch ran
        through and no rebuild is due."""
        # Update sequence in subscription record AFTER successful processing
        # This prevents duplicate detection on retry and ensures sequence only
        # advances after the callback has been fully processed. A batch
        # stopped for a rebuild advances through the callback that stopped
        # it; the rest of it is pruned (the rebuild supersedes it).
        new_last_seq = stop_at if stop_at is not None else batch[-1].sequence
        self.applied_through = new_last_seq
        written = False
        try:
            recorded = self._update_last_seq(peer_id, subscription_id, new_last_seq)
            written = recorded
        except DbError as e:  # folds DbError: at-most-once: handlers already ran
            # The handlers have run: a 503 now would leave the diff
            # uncleared, and the next poll or resync would run them again.
            # Keep at-most-once delivery: log it and answer PROCESSED. The
            # stale sequence makes the next callback look like a gap, which
            # the gap timeout resyncs; a subscription with no next callback
            # waits until one arrives.
            logger.error(
                f"Sequence write to {new_last_seq} faulted after processing: {e}"
            )
            recorded = True
        if recorded:
            # The callbacks taken from the queue are processed: they leave it
            # in one write, best effort. A later read skips them only if the
            # sequence write above landed; if both faulted they can run again
            # (filed in the subscriber hardening todo).
            if prune:
                try:
                    # Through the whole batch: a batch stopped for a rebuild
                    # drops the rest (the rebuild supersedes it; a rebuild
                    # that fails leaves a gap the gap timeout resyncs, as
                    # kept entries would wait for it too).
                    self._prune_pending(peer_id, subscription_id, batch[-1].sequence)
                except DbError as e:  # folds DbError: best-effort prune
                    logger.error(f"Pruning processed callbacks faulted: {e}")
        else:
            # Failed to update subscription - this is critical but we've already
            # processed the callback, so log error but don't retry. The claim
            # stays (at-most-once, as for a fault above): until its lease runs
            # out a redelivery is answered as in progress instead of running
            # the handlers again.
            logger.error(
                f"Failed to update sequence to {new_last_seq} after processing - "
                f"the batch may run again once its claim expires"
            )

        if stop_at is not None and self._whole_target(peer_id, subscription_id):
            # The rest of the batch is dropped (the rebuild supersedes it):
            # what it deleted is owed too, so the rebuild deletes it even
            # where it cannot sweep the bucket. Target-level data only: below
            # it, a diff's keys are not replica names.
            for dropped in batch:
                if dropped.sequence > stop_at:
                    out_of_step_lists.extend(_deleted_names(dropped.data))
        if out_of_step_lists:
            if self._mark_or_owe(
                peer_id,
                subscription_id,
                claimed_row,
                new_last_seq,
                out_of_step_lists,
            ):
                return ProcessResult.REBUILD, False
        elif claimed_row.get("rebuild_owed") and self._rebuild_due(claimed_row):
            # Owed from before (an out-of-step diff inside the interval, a
            # resync whose fetch failed, a behind poll's failed rebuild): the
            # next callback after it rebuilds.
            return ProcessResult.REBUILD, False

        return ProcessResult.PROCESSED, written and stop_at is None

    async def _run_handlers(
        self,
        peer_id: str,
        subscription_id: str,
        batch: list[ProcessedCallback],
        claimed_row: dict[str, Any],
        last_seq: int,
        handler: Callable[[ProcessedCallback], Awaitable[None]] | None,
    ) -> tuple[list[str], int | None]:
        """Invoke the handler for a claimed batch, in order. Returns the
        lists that were out of step, and the sequence the batch stopped at
        because a rebuild is due (``None``: it ran through; the rebuild
        supersedes the rest). A ``DbError`` hands the claim back to
        ``last_seq`` and is raised."""
        out_of_step_lists: list[str] = []
        if not handler:
            return out_of_step_lists, None
        for cb in batch:
            try:
                await handler(cb)
            except DbError:
                self._release_claim(peer_id, subscription_id, claimed_row, last_seq)
                # The library's own storage write (auto-storage in the
                # handler) faulted, and the sequence has not advanced. The
                # 503 leaves the diff uncleared on the publisher, which does
                # not retry (the protocol's at-most-once rule): it comes back
                # through a poll or a gap resync, which runs the handler
                # again, so data the handler wrote before the fault can be
                # applied twice. The consumer data hooks inside the handler
                # fold their own errors; a legacy callback hook's DbError
                # arrives here too and aborts the rest of the batch.
                raise
            except Exception as e:  # folds DbError: handled by the clause above
                # Log with full traceback for debugging, but continue
                # processing - at-most-once semantics means we don't retry
                logger.error(f"Handler error for seq={cb.sequence}: {e}", exc_info=True)
                continue
            if not cb.out_of_step:
                continue
            # A callback whose list diff the replica could not apply marks
            # the rebuild owed.
            out_of_step_lists.append(str(cb.out_of_step.get("list") or ""))
            if self._rebuild_due({**claimed_row, "rebuild_owed": True}):
                return out_of_step_lists, cb.sequence
            logger.warning(
                f"Out-of-step diff seq={cb.sequence} for "
                f"{peer_id}:{subscription_id} inside the "
                "rebuild interval: the rebuild stays owed"
            )
        return out_of_step_lists, None

    async def _drain(
        self,
        peer_id: str,
        subscription_id: str,
        handler: Callable[[ProcessedCallback], Awaitable[None]] | None,
        after_seq: int | None,
    ) -> tuple[bool, int]:
        """Process the callbacks queued next in line, for a delivery that
        has done its own work: one that recorded its sequence (a callback
        that met its live claim was queued behind it), or one that queued
        its callback (the delivery it waited for may have finished between
        this one's read and its write).

        Each round claims on a fresh state row and sequence
        (:meth:`_claim_queued`), so a callback another delivery took is not
        run again. The first is always taken (a callback queued behind a
        slow handler is the one most likely to be there); after it the drain
        is bounded by ``DRAIN_MAX_CALLBACKS`` and ``DRAIN_SECONDS``, and the
        rest stays queued. Nothing here raises: a
        ``DbError`` from a handler leaves that callback queued with its claim
        handed back, and ends the drain (the caller's own callback is done
        and is answered so).

        Returns ``(rebuild, through)``: whether a rebuild is due, and the
        last sequence processed here (0: nothing was)."""
        taken = 0
        through = 0
        drain_started = time.monotonic()
        while taken == 0 or (
            taken < self.DRAIN_MAX_CALLBACKS
            and time.monotonic() - drain_started < self.DRAIN_SECONDS
        ):
            step = self._claim_queued(peer_id, subscription_id, after_seq)
            if step is None:
                break
            batch, claimed_row, last_seq = step
            try:
                out_of_step_lists, stop_at = await self._run_handlers(
                    peer_id, subscription_id, batch, claimed_row, last_seq, handler
                )
            except DbError as e:  # folds DbError: the callback stays queued
                logger.error(
                    f"Queued callback of {peer_id}:{subscription_id} after "
                    f"seq={last_seq} faulted and stays queued: {e}"
                )
                break
            result, more = self._finish_batch(
                peer_id,
                subscription_id,
                batch,
                claimed_row,
                out_of_step_lists,
                stop_at,
                prune=True,
            )
            taken += len(batch)
            through = batch[-1].sequence
            if result == ProcessResult.REBUILD:
                return True, through
            if not more:
                break
            after_seq = through
        return False, through

    async def process_callback(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: Any,
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
                # progress the gap is waiting for. And not while the next
                # callback in line is itself queued (left by a bounded or
                # faulted drain): there is no gap, and the drain below takes
                # it; a resync here would clear callbacks already answered.
                head_queued = any(c.get("sequence") == last_seq + 1 for c in pending)
                if not claimed and not head_queued and self._check_gap_timeout(pending):
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
                        f"Callback seq={sequence} for {peer_id}:{subscription_id} not "
                        "queued: the pending queue is full, or the callback was "
                        "refused"
                    )
                    return ProcessResult.REJECTED

                logger.debug(
                    f"Gap detected: seq={sequence}, last_seq={last_seq}, "
                    f"added to pending"
                )
                # The delivery this one waited for may have recorded its
                # sequence between this delivery's read and its write to the
                # queue, and has then looked at the queue already: look once
                # at what is next in line now.
                rebuild, through = await self._drain(
                    peer_id, subscription_id, handler, None
                )
                if rebuild:
                    return ProcessResult.REBUILD
                if through >= sequence:
                    return ProcessResult.PROCESSED
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
                    timestamp=data.get("timestamp", "")
                    if isinstance(data, dict)
                    else "",
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
                        timestamp=next_callback["data"].get("timestamp", "")
                        if isinstance(next_callback["data"], dict)
                        else "",
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

            out_of_step_lists, stop_at = await self._run_handlers(
                peer_id,
                subscription_id,
                callbacks_to_process,
                claimed_row,
                last_seq,
                handler,
            )
            result, more = self._finish_batch(
                peer_id,
                subscription_id,
                callbacks_to_process,
                claimed_row,
                out_of_step_lists,
                stop_at,
                # Its own entry too, when an earlier delivery of it was queued.
                prune=bool(drained) or sequence in by_seq,
            )
            if more:
                # A callback that arrived while this one was being processed
                # met its claim and was queued: nothing else takes it.
                rebuild, _through = await self._drain(
                    peer_id, subscription_id, handler, callbacks_to_process[-1].sequence
                )
                if rebuild:
                    return ProcessResult.REBUILD
            return result

        # Exhausted retries
        logger.error(f"Failed to process callback after {self._max_retries} retries")
        return ProcessResult.REJECTED

    async def _handle_resync(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: Any,
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
                timestamp=data.get("timestamp", "") if isinstance(data, dict) else "",
            )
            failed = False
            try:
                await handler(callback)
            except DbError:
                self._settle_after_resync(peer_id, subscription_id, rebuilt=False)
                raise
            except Exception as e:
                # Log with full traceback for debugging
                logger.error(f"Resync handler error: {e}", exc_info=True)
                failed = True
            # A resync that applied cleanly settles an owed rebuild; one that
            # failed (softly or with a list it could not store) leaves or
            # sets it, and does not restart the rebuild interval.
            self._settle_after_resync(
                peer_id,
                subscription_id,
                rebuilt=not failed and not callback.out_of_step,
            )

        # Update subscription sequence AFTER successful processing
        self._update_last_seq(peer_id, subscription_id, sequence)

        return ProcessResult.PROCESSED

    async def _handle_permission(
        self,
        peer_id: str,
        data: Any,
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
                timestamp=data.get("timestamp", "") if isinstance(data, dict) else "",
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

        # Get all attributes in bucket and delete those for this peer. Strict:
        # a fault raises DbError, so the trust deletion answers 503 and is
        # retried, instead of leaving this peer's state behind.
        all_attrs = db.get_bucket() or {}
        for attr_name in list(all_attrs.keys()):
            # Keys are "state:{peer_id}:{subscription_id}" and
            # "pending:{peer_id}:{subscription_id}", and a peer id may contain
            # ":" (a subscription id never does): compare the peer segment,
            # never a substring, or ending trust with peer "b" would clear
            # peer "a:b"'s state ("state:a:b:<sub>").
            head, sep, _sub = attr_name.rpartition(":")
            if sep and head in (f"state:{peer_id}", f"pending:{peer_id}"):
                db.delete_attr(name=attr_name)

    def _run_handlers_sync(
        self,
        peer_id: str,
        subscription_id: str,
        batch: list[ProcessedCallback],
        claimed_row: dict[str, Any],
        last_seq: int,
        handler: Callable[[ProcessedCallback], None] | None,
    ) -> tuple[list[str], int | None]:
        """Invoke the handler for a claimed batch, in order. Returns the
        lists that were out of step, and the sequence the batch stopped at
        because a rebuild is due (``None``: it ran through; the rebuild
        supersedes the rest). A ``DbError`` hands the claim back to
        ``last_seq`` and is raised."""
        out_of_step_lists: list[str] = []
        if not handler:
            return out_of_step_lists, None
        for cb in batch:
            try:
                handler(cb)
            except DbError:
                self._release_claim(peer_id, subscription_id, claimed_row, last_seq)
                # The library's own storage write (auto-storage in the
                # handler) faulted, and the sequence has not advanced. The
                # 503 leaves the diff uncleared on the publisher, which does
                # not retry (the protocol's at-most-once rule): it comes back
                # through a poll or a gap resync, which runs the handler
                # again, so data the handler wrote before the fault can be
                # applied twice. The consumer data hooks inside the handler
                # fold their own errors; a legacy callback hook's DbError
                # arrives here too and aborts the rest of the batch.
                raise
            except Exception as e:  # folds DbError: handled by the clause above
                # Log with full traceback for debugging, but continue
                # processing - at-most-once semantics means we don't retry
                logger.error(f"Handler error for seq={cb.sequence}: {e}", exc_info=True)
                continue
            if not cb.out_of_step:
                continue
            # A callback whose list diff the replica could not apply marks
            # the rebuild owed.
            out_of_step_lists.append(str(cb.out_of_step.get("list") or ""))
            if self._rebuild_due({**claimed_row, "rebuild_owed": True}):
                return out_of_step_lists, cb.sequence
            logger.warning(
                f"Out-of-step diff seq={cb.sequence} for "
                f"{peer_id}:{subscription_id} inside the "
                "rebuild interval: the rebuild stays owed"
            )
        return out_of_step_lists, None

    def _drain_sync(
        self,
        peer_id: str,
        subscription_id: str,
        handler: Callable[[ProcessedCallback], None] | None,
        after_seq: int | None,
    ) -> tuple[bool, int]:
        """:meth:`_drain` for a synchronous handler."""
        taken = 0
        through = 0
        drain_started = time.monotonic()
        while taken == 0 or (
            taken < self.DRAIN_MAX_CALLBACKS
            and time.monotonic() - drain_started < self.DRAIN_SECONDS
        ):
            step = self._claim_queued(peer_id, subscription_id, after_seq)
            if step is None:
                break
            batch, claimed_row, last_seq = step
            try:
                out_of_step_lists, stop_at = self._run_handlers_sync(
                    peer_id, subscription_id, batch, claimed_row, last_seq, handler
                )
            except DbError as e:  # folds DbError: the callback stays queued
                logger.error(
                    f"Queued callback of {peer_id}:{subscription_id} after "
                    f"seq={last_seq} faulted and stays queued: {e}"
                )
                break
            result, more = self._finish_batch(
                peer_id,
                subscription_id,
                batch,
                claimed_row,
                out_of_step_lists,
                stop_at,
                prune=True,
            )
            taken += len(batch)
            through = batch[-1].sequence
            if result == ProcessResult.REBUILD:
                return True, through
            if not more:
                break
            after_seq = through
        return False, through

    def process_callback_sync(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: Any,
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
                # progress the gap is waiting for. And not while the next
                # callback in line is itself queued (left by a bounded or
                # faulted drain): there is no gap, and the drain below takes
                # it; a resync here would clear callbacks already answered.
                head_queued = any(c.get("sequence") == last_seq + 1 for c in pending)
                if not claimed and not head_queued and self._check_gap_timeout(pending):
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
                        f"Callback seq={sequence} for {peer_id}:{subscription_id} not "
                        "queued: the pending queue is full, or the callback was "
                        "refused"
                    )
                    return ProcessResult.REJECTED

                logger.debug(
                    f"Gap detected: seq={sequence}, last_seq={last_seq}, "
                    f"added to pending"
                )
                # The delivery this one waited for may have recorded its
                # sequence between this delivery's read and its write to the
                # queue, and has then looked at the queue already: look once
                # at what is next in line now.
                rebuild, through = self._drain_sync(
                    peer_id, subscription_id, handler, None
                )
                if rebuild:
                    return ProcessResult.REBUILD
                if through >= sequence:
                    return ProcessResult.PROCESSED
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
                    timestamp=data.get("timestamp", "")
                    if isinstance(data, dict)
                    else "",
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
                        timestamp=next_callback["data"].get("timestamp", "")
                        if isinstance(next_callback["data"], dict)
                        else "",
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

            out_of_step_lists, stop_at = self._run_handlers_sync(
                peer_id,
                subscription_id,
                callbacks_to_process,
                claimed_row,
                last_seq,
                handler,
            )
            result, more = self._finish_batch(
                peer_id,
                subscription_id,
                callbacks_to_process,
                claimed_row,
                out_of_step_lists,
                stop_at,
                # Its own entry too, when an earlier delivery of it was queued.
                prune=bool(drained) or sequence in by_seq,
            )
            if more:
                # A callback that arrived while this one was being processed
                # met its claim and was queued: nothing else takes it.
                rebuild, _through = self._drain_sync(
                    peer_id, subscription_id, handler, callbacks_to_process[-1].sequence
                )
                if rebuild:
                    return ProcessResult.REBUILD
            return result

        # Exhausted retries
        logger.error(f"Failed to process callback after {self._max_retries} retries")
        return ProcessResult.REJECTED

    def _handle_resync_sync(
        self,
        peer_id: str,
        subscription_id: str,
        sequence: int,
        data: Any,
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
                timestamp=data.get("timestamp", "") if isinstance(data, dict) else "",
            )
            failed = False
            try:
                handler(callback)
            except DbError:
                self._settle_after_resync(peer_id, subscription_id, rebuilt=False)
                raise
            except Exception as e:
                # Log with full traceback for debugging
                logger.error(f"Resync handler error: {e}", exc_info=True)
                failed = True
            # A resync that applied cleanly settles an owed rebuild; one that
            # failed (softly or with a list it could not store) leaves or
            # sets it, and does not restart the rebuild interval.
            self._settle_after_resync(
                peer_id,
                subscription_id,
                rebuilt=not failed and not callback.out_of_step,
            )

        # Update subscription sequence AFTER successful processing
        self._update_last_seq(peer_id, subscription_id, sequence)

        return ProcessResult.PROCESSED

    def _handle_permission_sync(
        self,
        peer_id: str,
        data: Any,
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
                timestamp=data.get("timestamp", "") if isinstance(data, dict) else "",
            )
            try:
                handler(callback)
            except DbError:
                raise
            except Exception as e:
                logger.error(f"Permission handler error: {e}", exc_info=True)

        return ProcessResult.PROCESSED
