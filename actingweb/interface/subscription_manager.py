"""
Simplified subscription management for ActingWeb actors.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..actor import Actor as CoreActor
from ..subscription import Subscription as CoreSubscription

if TYPE_CHECKING:
    from ..subscription_config import SubscriptionProcessingConfig

logger = logging.getLogger(__name__)


class SubscriptionInfo:
    """Represents a subscription to or from another actor."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @property
    def subscription_id(self) -> str:
        """Unique subscription ID."""
        return self._data.get("subscriptionid", "")

    @property
    def peer_id(self) -> str:
        """ID of the peer actor."""
        return self._data.get("peerid", "")

    @property
    def target(self) -> str:
        """Target being subscribed to."""
        return self._data.get("target", "")

    @property
    def subtarget(self) -> str | None:
        """Subtarget being subscribed to."""
        return self._data.get("subtarget")

    @property
    def resource(self) -> str | None:
        """Resource being subscribed to."""
        return self._data.get("resource")

    @property
    def granularity(self) -> str:
        """Granularity of notifications (high, low, none)."""
        return self._data.get("granularity", "high")

    @property
    def is_callback(self) -> bool:
        """Whether this subscription receives callbacks (we subscribed to another actor).

        When callback=True, we are the subscriber and will receive callbacks from the peer.
        When callback=False, we are the publisher and will send callbacks to the peer.
        """
        return self._data.get("callback", False)

    @property
    def is_outbound(self) -> bool:
        """Whether this is an outbound subscription (we subscribed to another actor).

        Outbound subscriptions are ones we initiated - we subscribed TO another actor.
        These have callback=True because we receive callbacks from them.
        """
        return self.is_callback

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return self._data.copy()


class SubscriptionWithDiffs:
    """
    Wrapper around a core Subscription object that provides access to diff operations.

    This class is returned by get_subscription_with_diffs() and provides methods
    to retrieve and manage subscription diffs (change notifications).
    """

    def __init__(self, core_subscription: CoreSubscription):
        """Initialize with a core Subscription object."""
        self._core_sub = core_subscription

    @property
    def subscription_info(self) -> SubscriptionInfo | None:
        """Get the subscription info as a SubscriptionInfo object."""
        sub_data = self._core_sub.get()
        if sub_data:
            return SubscriptionInfo(sub_data)
        return None

    def get_diffs(self) -> list[dict[str, Any]]:
        """
        Get all pending diffs for this subscription.

        Returns a list of diffs ordered by timestamp (oldest first).
        Each diff contains: sequence, timestamp, and diff data.
        """
        diffs = self._core_sub.get_diffs()
        if diffs is None:
            return []
        return diffs if isinstance(diffs, list) else []

    def get_diff(self, seqnr: int) -> dict[str, Any] | None:
        """
        Get a specific diff by sequence number.

        Args:
            seqnr: The sequence number of the diff to retrieve

        Returns:
            The diff data if found, None otherwise
        """
        return self._core_sub.get_diff(seqnr=seqnr)

    def clear_diffs(self, seqnr: int = 0) -> None:
        """
        Clear all diffs up to and including the specified sequence number.

        Args:
            seqnr: Clear all diffs up to this sequence number.
                   If 0, clears all diffs.
        """
        self._core_sub.clear_diffs(seqnr=seqnr)

    def clear_diff(self, seqnr: int) -> bool:
        """
        Clear a specific diff by sequence number.

        Args:
            seqnr: The sequence number of the diff to clear

        Returns:
            True if the diff was cleared successfully, False otherwise
        """
        return bool(self._core_sub.clear_diff(seqnr=seqnr))


@dataclass
class SubscriptionSyncResult:
    """Result of syncing a single subscription."""

    subscription_id: str
    success: bool
    diffs_fetched: int
    diffs_processed: int
    final_sequence: int
    error: str | None = None
    error_code: int | None = None


@dataclass
class PeerSyncResult:
    """Result of syncing all subscriptions to a peer."""

    peer_id: str
    success: bool
    subscriptions_synced: int
    total_diffs_processed: int
    subscription_results: list[SubscriptionSyncResult]
    error: str | None = None


class SubscriptionManager:
    """
    Simplified interface for managing subscriptions.

    Example usage:
        # Subscribe to another actor's data
        subscription = actor.subscriptions.subscribe_to_peer(
            peer_id="peer123",
            target="properties",
            subtarget="status"
        )

        # List all subscriptions
        for sub in actor.subscriptions.all_subscriptions:
            print(f"Subscription to {sub.peer_id}: {sub.target}")

        # Notify subscribers of changes
        actor.subscriptions.notify_subscribers(
            target="properties",
            data={"status": "active"}
        )

        # Unsubscribe
        actor.subscriptions.unsubscribe(peer_id="peer123", subscription_id="sub123")
    """

    def __init__(self, core_actor: CoreActor):
        self._core_actor = core_actor

    @property
    def all_subscriptions(self) -> list[SubscriptionInfo]:
        """Get all subscriptions (both inbound and outbound)."""
        subscriptions = self._core_actor.get_subscriptions()
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]

    @property
    def outbound_subscriptions(self) -> list[SubscriptionInfo]:
        """Get subscriptions to other actors (we subscribed to them).

        These are subscriptions we initiated - callback=True means we receive callbacks.
        """
        return [sub for sub in self.all_subscriptions if sub.is_outbound]

    @property
    def inbound_subscriptions(self) -> list[SubscriptionInfo]:
        """Get subscriptions from other actors (they subscribed to us).

        These are subscriptions others created - callback=False means we send callbacks.
        """
        return [sub for sub in self.all_subscriptions if not sub.is_callback]

    def get_subscriptions_to_peer(self, peer_id: str) -> list[SubscriptionInfo]:
        """Get all subscriptions to a specific peer."""
        subscriptions = self._core_actor.get_subscriptions(peerid=peer_id)
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]

    def get_subscriptions_for_target(
        self, target: str, subtarget: str = "", resource: str = ""
    ) -> list[SubscriptionInfo]:
        """Get all subscriptions for a specific target."""
        subscriptions = self._core_actor.get_subscriptions(
            target=target, subtarget=subtarget or None, resource=resource or None
        )
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]

    def subscribe_to_peer(
        self,
        peer_id: str,
        target: str,
        subtarget: str = "",
        resource: str = "",
        granularity: str = "high",
    ) -> str | None:
        """
        Subscribe to another actor's data.

        Returns the subscription URL if successful, None otherwise.
        """
        result = self._core_actor.create_remote_subscription(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
        )
        # Handle the case where the method returns False instead of None
        return result if result and isinstance(result, str) else None

    def unsubscribe(self, peer_id: str, subscription_id: str) -> bool:
        """Unsubscribe from a peer's data."""
        # Try to delete remote subscription first
        remote_result = self._core_actor.delete_remote_subscription(
            peerid=peer_id, subid=subscription_id
        )
        if remote_result:
            # Then delete local subscription
            local_result = self._core_actor.delete_subscription(
                peerid=peer_id, subid=subscription_id
            )
            return bool(local_result)
        return False

    def unsubscribe_from_peer(self, peer_id: str) -> bool:
        """Unsubscribe from all of a peer's data."""
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        success = True
        for sub in subscriptions:
            if not self.unsubscribe(peer_id, sub.subscription_id):
                success = False
        return success

    def notify_subscribers(
        self, target: str, data: dict[str, Any], subtarget: str = "", resource: str = ""
    ) -> None:
        """
        Notify all subscribers of changes to the specified target.

        This will trigger callbacks to all actors subscribed to this target.
        """
        import json

        blob = json.dumps(data) if isinstance(data, dict) else str(data)

        self._core_actor.register_diffs(
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            blob=blob,
        )

    def get_subscription(
        self, peer_id: str, subscription_id: str
    ) -> SubscriptionInfo | None:
        """Get a specific subscription."""
        sub_data = self._core_actor.get_subscription(
            peerid=peer_id, subid=subscription_id
        )
        if sub_data and isinstance(sub_data, dict):
            return SubscriptionInfo(sub_data)
        return None

    def get_callback_subscription(
        self, peer_id: str, subscription_id: str
    ) -> SubscriptionInfo | None:
        """
        Get a callback subscription (outbound - we subscribed to them).

        Callback subscriptions are ones we initiated - we receive callbacks from the peer.
        This is used when processing incoming callbacks to verify the subscription exists.

        Args:
            peer_id: ID of the peer actor we subscribed to
            subscription_id: ID of the subscription

        Returns:
            SubscriptionInfo if found, None otherwise

        Example:
            # In a callback handler, verify subscription exists
            sub = actor.subscriptions.get_callback_subscription(
                peer_id="peer123",
                subscription_id="sub456"
            )
            if sub:
                # Process the callback
                process_callback_data(data)
        """
        sub_data = self._core_actor.get_subscription(
            peerid=peer_id, subid=subscription_id, callback=True
        )
        if sub_data and isinstance(sub_data, dict):
            return SubscriptionInfo(sub_data)
        return None

    def delete_callback_subscription(self, peer_id: str, subscription_id: str) -> bool:
        """
        Delete a callback subscription (local only, no peer notification).

        This is used when a peer terminates our subscription to them via a callback.
        We just remove our local record without notifying the peer (they already know).

        This is different from unsubscribe() which notifies the peer first.

        Args:
            peer_id: ID of the peer actor
            subscription_id: ID of the subscription to delete

        Returns:
            True if deleted successfully, False otherwise

        Example:
            # Peer sent DELETE callback to terminate our subscription
            deleted = actor.subscriptions.delete_callback_subscription(
                peer_id="peer123",
                subscription_id="sub456"
            )
            if deleted:
                logger.info("Callback subscription removed")
        """
        result = self._core_actor.delete_subscription(
            peerid=peer_id, subid=subscription_id, callback=True
        )
        return bool(result)

    def has_subscribers_for(
        self, target: str, subtarget: str = "", resource: str = ""
    ) -> bool:
        """Check if there are any subscribers for the given target.

        Subscribers are peers who subscribed to us - their subscription records
        have callback=False (we send callbacks to them).
        """
        subscriptions = self.get_subscriptions_for_target(target, subtarget, resource)
        return len([sub for sub in subscriptions if not sub.is_callback]) > 0

    def get_subscribers_for(
        self, target: str, subtarget: str = "", resource: str = ""
    ) -> list[str]:
        """Get list of peer IDs subscribed to the given target.

        Returns peers who subscribed to us - their subscription records
        have callback=False (we send callbacks to them).
        """
        subscriptions = self.get_subscriptions_for_target(target, subtarget, resource)
        return [sub.peer_id for sub in subscriptions if not sub.is_callback]

    def cleanup_peer_subscriptions(self, peer_id: str) -> bool:
        """Remove all subscriptions related to a specific peer."""
        # This is typically called when a trust relationship is deleted
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        success = True
        for sub in subscriptions:
            result = self._core_actor.delete_subscription(
                peerid=peer_id, subid=sub.subscription_id, callback=sub.is_callback
            )
            if not result:
                success = False
        return success

    def create_local_subscription(
        self,
        peer_id: str,
        target: str,
        subtarget: str = "",
        resource: str = "",
        granularity: str = "high",
    ) -> dict[str, Any] | None:
        """
        Create a local subscription (accept an incoming subscription from a peer).

        This is used when another actor subscribes to our data. The subscription
        is stored locally and we will send callbacks to the peer when data changes.

        Args:
            peer_id: ID of the peer actor subscribing to us
            target: Target they're subscribing to (e.g., "properties")
            subtarget: Optional subtarget (e.g., specific property name)
            resource: Optional resource identifier
            granularity: Notification granularity ("high", "low", or "none")

        Returns:
            Dictionary containing subscription details if successful:
            {
                "subscriptionid": "...",
                "peerid": "...",
                "target": "...",
                "subtarget": "...",
                "resource": "...",
                "granularity": "...",
                "sequence": 1
            }
            Returns None if creation failed.
        """
        new_sub = self._core_actor.create_subscription(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
            callback=False,  # Local subscriptions have callback=False (we send callbacks)
        )
        if new_sub and isinstance(new_sub, dict):
            return new_sub
        return None

    def get_subscription_with_diffs(
        self, peer_id: str, subscription_id: str
    ) -> SubscriptionWithDiffs | None:
        """
        Get a subscription object with diff operations support.

        This returns a SubscriptionWithDiffs object that provides methods
        to retrieve and manage subscription diffs (change notifications).

        Args:
            peer_id: ID of the peer actor
            subscription_id: ID of the subscription

        Returns:
            SubscriptionWithDiffs object if subscription exists, None otherwise

        Example:
            sub_with_diffs = actor.subscriptions.get_subscription_with_diffs(
                peer_id="peer123",
                subscription_id="sub456"
            )
            if sub_with_diffs:
                # Get all pending diffs
                diffs = sub_with_diffs.get_diffs()

                # Clear diffs up to sequence 10
                sub_with_diffs.clear_diffs(seqnr=10)
        """
        core_sub = self._core_actor.get_subscription_obj(
            peerid=peer_id, subid=subscription_id
        )
        if core_sub:
            # Verify subscription exists by checking if it has data
            sub_data = core_sub.get()
            if sub_data and len(sub_data) > 0:
                return SubscriptionWithDiffs(core_sub)
        return None

    # =========================================================================
    # Subscription Suspension
    # =========================================================================

    def suspend(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration for a target/subtarget.

        While suspended:
        - Property changes will NOT register diffs
        - No subscription callbacks will be sent
        - Use resume() to lift suspension and trigger resync

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if newly suspended, False if already suspended

        Example:
            # Suspend before bulk operation
            actor.subscriptions.suspend(target="properties", subtarget="memory_travel")

            # Perform bulk updates without triggering callbacks
            for item in bulk_data:
                actor.properties["memory_travel"] = item

            # Resume and notify subscribers to resync
            callbacks_sent = actor.subscriptions.resume(
                target="properties", subtarget="memory_travel"
            )
        """
        return self._core_actor.suspend_subscriptions(target, subtarget)

    def resume(self, target: str, subtarget: str | None = None) -> int:
        """Resume diff registration and send resync callbacks.

        Sends a resync callback to ALL subscriptions matching the target/subtarget,
        telling subscribers to perform a full GET to re-sync their state.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            Number of resync callbacks sent successfully

        Example:
            # Resume after bulk operation
            callbacks_sent = actor.subscriptions.resume(
                target="properties", subtarget="memory_travel"
            )
            print(f"Notified {callbacks_sent} subscribers to resync")
        """
        return self._core_actor.resume_subscriptions(target, subtarget)

    def is_suspended(self, target: str, subtarget: str | None = None) -> bool:
        """Check if diff registration is suspended for a target/subtarget.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if suspended, False otherwise
        """
        return self._core_actor.is_subscription_suspended(target, subtarget)

    # =========================================================================
    # Pull-Based Sync API
    # =========================================================================

    def _get_peer_proxy(self, peer_id: str) -> Any:
        """Get an AwProxy for communicating with a peer.

        Args:
            peer_id: The peer actor's ID

        Returns:
            AwProxy instance or None if no trust relationship exists
        """
        from ..aw_proxy import AwProxy

        # Get the trust relationship with this peer
        config = self._core_actor.config
        peer_target = {
            "id": self._core_actor.id,
            "peerid": peer_id,
            "passphrase": None,
        }
        return AwProxy(peer_target=peer_target, config=config)

    def sync_subscription(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
    ) -> SubscriptionSyncResult:
        """
        Sync a single subscription by fetching and processing pending diffs from the peer.

        This is a pull-based sync that fetches diffs from the peer actor that
        we subscribed to, processes them, and clears them on the peer.

        Args:
            peer_id: ID of the peer actor we subscribed to
            subscription_id: ID of the subscription to sync
            config: Optional processing configuration

        Returns:
            SubscriptionSyncResult with sync outcome

        Example:
            result = actor.subscriptions.sync_subscription(
                peer_id="peer123",
                subscription_id="sub456"
            )
            if result.success:
                print(f"Processed {result.diffs_processed} diffs")
            else:
                print(f"Sync failed: {result.error}")
        """
        from ..callback_processor import CallbackProcessor, CallbackType, ProcessResult
        from ..remote_storage import RemotePeerStore
        from ..subscription_config import SubscriptionProcessingConfig

        # Use default config if not provided
        if config is None:
            config = SubscriptionProcessingConfig(enabled=True)

        # Verify local subscription exists
        sub = self.get_callback_subscription(peer_id, subscription_id)
        if not sub:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Subscription not found",
                error_code=404,
            )

        # Get proxy to peer
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="No trust relationship with peer",
                error_code=404,
            )

        # Fetch diffs from peer
        # Path: /subscriptions/{our_actor_id}/{subscription_id}
        our_actor_id = self._core_actor.id
        path = f"subscriptions/{our_actor_id}/{subscription_id}"

        response = proxy.get_resource(path=path)

        if response is None:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Failed to communicate with peer",
                error_code=proxy.last_response_code or 502,
            )

        if "error" in response:
            error_code = response["error"].get("code", 500)
            error_msg = response["error"].get("message", "Unknown error")
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error=error_msg,
                error_code=error_code,
            )

        # Parse response: {sequence: int, data: [{sequence, timestamp, data}, ...]}
        diffs = response.get("data", [])
        if not isinstance(diffs, list):
            diffs = []

        diffs_fetched = len(diffs)

        # If no diffs, fetch baseline data from target resource
        if diffs_fetched == 0 and config.auto_storage:
            # Construct full target path including subtarget and resource if present
            target_path = sub.target
            if sub.subtarget:
                target_path = f"{target_path}/{sub.subtarget}"
            if sub.resource:
                target_path = f"{target_path}/{sub.resource}"

            logger.info(
                f"No diffs for subscription {subscription_id}, fetching baseline from {target_path}"
            )

            # Add metadata parameter for properties endpoint (only for collection-level)
            if sub.target == "properties" and not sub.subtarget:
                # Request metadata to include property list information
                target_path = f"{target_path}?metadata=true"

            # Fetch baseline data from target resource
            baseline_response = proxy.get_resource(path=target_path)

            # Reconstruct path for logging (without query params)
            log_path = sub.target
            if sub.subtarget:
                log_path = f"{log_path}/{sub.subtarget}"
            if sub.resource:
                log_path = f"{log_path}/{sub.resource}"

            if baseline_response and "error" not in baseline_response:
                # For properties subscriptions, transform list metadata into actual items
                # Only needed when subscribing to full /properties endpoint (no subtarget)
                # Subtarget subscriptions (e.g., properties/list:name) already return full items
                if (
                    sub.target == "properties"
                    and not sub.subtarget
                    and not sub.resource
                ):
                    transformed_data = self._transform_baseline_list_properties(
                        baseline_data=baseline_response,
                        peer_id=peer_id,
                        target=sub.target,
                    )
                else:
                    transformed_data = baseline_response

                # Store baseline data
                from .actor_interface import ActorInterface

                actor_interface = ActorInterface(self._core_actor)
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )

                # Apply transformed baseline as resync data
                store.apply_resync_data(transformed_data)
                logger.info(
                    f"Stored baseline data for subscription {subscription_id} from {log_path}"
                )

                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=True,
                    diffs_fetched=0,
                    diffs_processed=1,  # Count baseline fetch as 1 processed item
                    final_sequence=response.get("sequence", 0),
                )
            else:
                logger.warning(
                    f"Failed to fetch baseline from {log_path} for subscription {subscription_id}"
                )
                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=True,
                    diffs_fetched=0,
                    diffs_processed=0,
                    final_sequence=response.get("sequence", 0),
                )
        elif diffs_fetched == 0:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=True,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=response.get("sequence", 0),
            )

        # Sort diffs by sequence
        diffs = sorted(diffs, key=lambda d: d.get("sequence", 0))

        # Import ActorInterface for creating the callback processor
        from .actor_interface import ActorInterface

        # Create actor interface for callback processor
        actor_interface = ActorInterface(self._core_actor)

        # Process each diff
        diffs_processed = 0
        max_sequence = 0

        # Set up handler based on config
        def process_handler(cb):
            """Handler to apply callback data to remote storage."""
            if config.auto_storage:
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )
                if cb.callback_type == CallbackType.RESYNC:
                    store.apply_resync_data(cb.data)
                else:
                    store.apply_callback_data(cb.data)

        # Create callback processor if sequence tracking is enabled
        if config.auto_sequence:
            processor = CallbackProcessor(
                actor=actor_interface,
                gap_timeout_seconds=config.gap_timeout_seconds,
                max_pending=config.max_pending,
            )

            for diff in diffs:
                seq = diff.get("sequence", 0)
                data = diff.get("data", {})
                timestamp = diff.get("timestamp", "")

                # Add timestamp to data for handler
                if timestamp and isinstance(data, dict):
                    data["timestamp"] = timestamp

                result = processor.process_callback_sync(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    sequence=seq,
                    data=data,
                    callback_type="diff",
                    handler=process_handler if config.auto_storage else None,
                )

                if result == ProcessResult.PROCESSED:
                    diffs_processed += 1

                if seq > max_sequence:
                    max_sequence = seq
        else:
            # No sequence tracking, just process all diffs
            for diff in diffs:
                seq = diff.get("sequence", 0)
                data = diff.get("data", {})

                if config.auto_storage:
                    store = RemotePeerStore(
                        actor=actor_interface,
                        peer_id=peer_id,
                        validate_peer_id=False,
                    )
                    store.apply_callback_data(data)

                diffs_processed += 1
                if seq > max_sequence:
                    max_sequence = seq

        # Clear processed diffs on peer
        if max_sequence > 0:
            clear_response = proxy.change_resource(
                path=path, params={"sequence": max_sequence}
            )
            if clear_response is None or "error" in (clear_response or {}):
                # Log warning but don't fail the sync
                logger.warning(
                    f"Failed to clear diffs on peer {peer_id} for subscription "
                    f"{subscription_id}, sequence {max_sequence}"
                )

        return SubscriptionSyncResult(
            subscription_id=subscription_id,
            success=True,
            diffs_fetched=diffs_fetched,
            diffs_processed=diffs_processed,
            final_sequence=max_sequence,
        )

    def _transform_baseline_list_properties(
        self,
        baseline_data: dict[str, Any],
        peer_id: str,
        target: str,
    ) -> dict[str, Any]:
        """
        Transform list property metadata into actual list items for baseline sync.

        When baseline fetch returns list metadata ({"_list": true, "count": N}),
        this fetches the actual items from the remote peer via ActingWeb protocol
        and transforms to the format expected by apply_resync_data().

        Args:
            baseline_data: Baseline response from remote peer (may contain list metadata)
            peer_id: ID of remote peer we're syncing from
            target: Subscription target (e.g., "properties")

        Returns:
            Transformed data with lists in format {"property_name": {"_list": true, "items": [...]}}
        """
        # Create result dict (shallow copy)
        result = dict(baseline_data)

        # Get proxy for fetching list items from remote peer
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            logger.warning(
                f"No trust with peer {peer_id}, skipping list transformation"
            )
            return baseline_data

        # Process each property in baseline data
        for property_name, value in baseline_data.items():
            # Skip if not a dict
            if not isinstance(value, dict):
                continue

            # Check for list metadata format: {"_list": true, "count": N}
            if not value.get("_list"):
                continue

            # Skip if already has items
            if "items" in value:
                continue

            # Fetch actual list items from remote peer
            try:
                list_path = f"{target}/{property_name}"
                logger.debug(
                    f"Fetching list items for {property_name} from peer {peer_id} at {list_path}"
                )

                # Fetch via ActingWeb protocol (remote peer enforces permissions)
                response = proxy.get_resource(path=list_path)

                # Validate response is a list
                if response is None:
                    logger.warning(
                        f"No response when fetching list {property_name} from peer {peer_id}"
                    )
                    continue

                if "error" in response:
                    logger.warning(
                        f"Error fetching list {property_name} from peer {peer_id}: {response.get('error')}"
                    )
                    continue

                if not isinstance(response, list):
                    logger.error(
                        f"Invalid response for list {property_name} from peer {peer_id}: "
                        f"expected list, got {type(response).__name__}"
                    )
                    continue

                # Transform to flag-based format with items
                result[property_name] = {"_list": True, "items": response}

                # Log warning for large lists
                if len(response) > 100:
                    logger.warning(
                        f"List property {property_name} from peer {peer_id} has {len(response)} items. "
                        f"Consider using subtarget subscriptions for better performance."
                    )

                logger.debug(
                    f"Successfully fetched {len(response)} items for list {property_name} from peer {peer_id}"
                )

            except Exception as e:
                # Log error but continue processing other properties
                logger.error(
                    f"Error fetching list {property_name} from peer {peer_id}: {e}",
                    exc_info=True,
                )
                # Keep metadata as-is (fail gracefully)
                continue

        return result

    async def _transform_baseline_list_properties_async(
        self,
        baseline_data: dict[str, Any],
        peer_id: str,
        target: str,
    ) -> dict[str, Any]:
        """
        Async version: Transform list property metadata into actual list items for baseline sync.

        When baseline fetch returns list metadata ({"_list": true, "count": N}),
        this fetches the actual items from the remote peer via ActingWeb protocol
        and transforms to the format expected by apply_resync_data().

        Args:
            baseline_data: Baseline response from remote peer (may contain list metadata)
            peer_id: ID of remote peer we're syncing from
            target: Subscription target (e.g., "properties")

        Returns:
            Transformed data with lists in format {"property_name": {"_list": true, "items": [...]}}
        """
        # Create result dict (shallow copy)
        result = dict(baseline_data)

        # Get proxy for fetching list items from remote peer
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            logger.warning(
                f"No trust with peer {peer_id}, skipping list transformation"
            )
            return baseline_data

        # Process each property in baseline data
        for property_name, value in baseline_data.items():
            # Skip if not a dict
            if not isinstance(value, dict):
                continue

            # Check for list metadata format: {"_list": true, "count": N}
            if not value.get("_list"):
                continue

            # Skip if already has items
            if "items" in value:
                continue

            # Fetch actual list items from remote peer
            try:
                list_path = f"{target}/{property_name}"
                logger.debug(
                    f"Fetching list items for {property_name} from peer {peer_id} at {list_path}"
                )

                # Fetch via ActingWeb protocol (remote peer enforces permissions)
                response = await proxy.get_resource_async(path=list_path)

                # Validate response is a list
                if response is None:
                    logger.warning(
                        f"No response when fetching list {property_name} from peer {peer_id}"
                    )
                    continue

                if "error" in response:
                    logger.warning(
                        f"Error fetching list {property_name} from peer {peer_id}: {response.get('error')}"
                    )
                    continue

                if not isinstance(response, list):
                    logger.error(
                        f"Invalid response for list {property_name} from peer {peer_id}: "
                        f"expected list, got {type(response).__name__}"
                    )
                    continue

                # Transform to flag-based format with items
                result[property_name] = {"_list": True, "items": response}

                # Log warning for large lists
                if len(response) > 100:
                    logger.warning(
                        f"List property {property_name} from peer {peer_id} has {len(response)} items. "
                        f"Consider using subtarget subscriptions for better performance."
                    )

                logger.debug(
                    f"Successfully fetched {len(response)} items for list {property_name} from peer {peer_id}"
                )

            except Exception as e:
                # Log error but continue processing other properties
                logger.error(
                    f"Error fetching list {property_name} from peer {peer_id}: {e}",
                    exc_info=True,
                )
                # Keep metadata as-is (fail gracefully)
                continue

        return result

    def sync_peer(
        self,
        peer_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
    ) -> PeerSyncResult:
        """
        Sync all outbound subscriptions to a peer.

        Fetches and processes pending diffs for all subscriptions where
        we subscribed to the specified peer.

        Args:
            peer_id: ID of the peer actor
            config: Optional processing configuration

        Returns:
            PeerSyncResult with aggregate sync outcome

        Example:
            result = actor.subscriptions.sync_peer("peer123")
            if result.success:
                print(f"Synced {result.subscriptions_synced} subscriptions, "
                      f"{result.total_diffs_processed} diffs total")
            else:
                for sub_result in result.subscription_results:
                    if not sub_result.success:
                        print(f"Failed: {sub_result.subscription_id}: {sub_result.error}")
        """
        # Get all outbound subscriptions to this peer
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        outbound_subs = [s for s in subscriptions if s.is_outbound]

        if not outbound_subs:
            return PeerSyncResult(
                peer_id=peer_id,
                success=True,
                subscriptions_synced=0,
                total_diffs_processed=0,
                subscription_results=[],
            )

        # Sync each subscription
        results: list[SubscriptionSyncResult] = []
        total_diffs = 0
        all_success = True

        for sub in outbound_subs:
            result = self.sync_subscription(
                peer_id=peer_id,
                subscription_id=sub.subscription_id,
                config=config,
            )
            results.append(result)
            total_diffs += result.diffs_processed
            if not result.success:
                all_success = False

        # Refresh peer profile if configured
        actor_config = self._core_actor.config
        actor_id = self._core_actor.id
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_profile_attributes", None)
        ):
            try:
                from ..peer_profile import fetch_peer_profile, get_peer_profile_store

                profile = fetch_peer_profile(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                    attributes=actor_config.peer_profile_attributes,
                )
                store = get_peer_profile_store(actor_config)
                store.store_profile(profile)
                logger.debug(f"Refreshed peer profile during sync_peer for {peer_id}")
            except Exception as e:
                logger.warning(f"Failed to refresh peer profile during sync: {e}")

        # Refresh peer capabilities if configured
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_capabilities_caching", False)
        ):
            try:
                from ..peer_capabilities import (
                    fetch_peer_methods_and_actions,
                    get_cached_capabilities_store,
                )

                capabilities = fetch_peer_methods_and_actions(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                )
                store = get_cached_capabilities_store(actor_config)
                store.store_capabilities(capabilities)
                logger.debug(
                    f"Refreshed peer capabilities during sync_peer for {peer_id}"
                )
            except Exception as e:
                logger.warning(f"Failed to refresh peer capabilities during sync: {e}")

        return PeerSyncResult(
            peer_id=peer_id,
            success=all_success,
            subscriptions_synced=len([r for r in results if r.success]),
            total_diffs_processed=total_diffs,
            subscription_results=results,
        )

    async def sync_subscription_async(
        self,
        peer_id: str,
        subscription_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
    ) -> SubscriptionSyncResult:
        """
        Async version of sync_subscription.

        Sync a single subscription by fetching and processing pending diffs from the peer.

        Args:
            peer_id: ID of the peer actor we subscribed to
            subscription_id: ID of the subscription to sync
            config: Optional processing configuration

        Returns:
            SubscriptionSyncResult with sync outcome

        Example:
            result = await actor.subscriptions.sync_subscription_async(
                peer_id="peer123",
                subscription_id="sub456"
            )
        """
        from ..callback_processor import CallbackProcessor, CallbackType, ProcessResult
        from ..remote_storage import RemotePeerStore
        from ..subscription_config import SubscriptionProcessingConfig

        # Use default config if not provided
        if config is None:
            config = SubscriptionProcessingConfig(enabled=True)

        # Verify local subscription exists
        sub = self.get_callback_subscription(peer_id, subscription_id)
        if not sub:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Subscription not found",
                error_code=404,
            )

        # Get proxy to peer
        proxy = self._get_peer_proxy(peer_id)
        if proxy is None or proxy.trust is None:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="No trust relationship with peer",
                error_code=404,
            )

        # Fetch diffs from peer (async)
        our_actor_id = self._core_actor.id
        path = f"subscriptions/{our_actor_id}/{subscription_id}"

        response = await proxy.get_resource_async(path=path)

        if response is None:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Failed to communicate with peer",
                error_code=proxy.last_response_code or 502,
            )

        if "error" in response:
            error_code = response["error"].get("code", 500)
            error_msg = response["error"].get("message", "Unknown error")
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error=error_msg,
                error_code=error_code,
            )

        # Parse response
        diffs = response.get("data", [])
        if not isinstance(diffs, list):
            diffs = []

        diffs_fetched = len(diffs)

        # If no diffs, fetch baseline data from target resource
        if diffs_fetched == 0 and config.auto_storage:
            # Construct full target path including subtarget and resource if present
            target_path = sub.target
            if sub.subtarget:
                target_path = f"{target_path}/{sub.subtarget}"
            if sub.resource:
                target_path = f"{target_path}/{sub.resource}"

            logger.info(
                f"No diffs for subscription {subscription_id}, fetching baseline from {target_path}"
            )

            # Add metadata parameter for properties endpoint (only for collection-level)
            if sub.target == "properties" and not sub.subtarget:
                # Request metadata to include property list information
                target_path = f"{target_path}?metadata=true"

            # Fetch baseline data from target resource
            baseline_response = await proxy.get_resource_async(path=target_path)

            # Reconstruct path for logging (without query params)
            log_path = sub.target
            if sub.subtarget:
                log_path = f"{log_path}/{sub.subtarget}"
            if sub.resource:
                log_path = f"{log_path}/{sub.resource}"

            if baseline_response and "error" not in baseline_response:
                # For properties subscriptions, transform list metadata into actual items
                # Only needed when subscribing to full /properties endpoint (no subtarget)
                # Subtarget subscriptions (e.g., properties/list:name) already return full items
                if (
                    sub.target == "properties"
                    and not sub.subtarget
                    and not sub.resource
                ):
                    transformed_data = await self._transform_baseline_list_properties_async(
                        baseline_data=baseline_response,
                        peer_id=peer_id,
                        target=sub.target,
                    )
                else:
                    transformed_data = baseline_response

                # Store baseline data
                from .actor_interface import ActorInterface

                actor_interface = ActorInterface(self._core_actor)
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )

                # Apply transformed baseline as resync data
                store.apply_resync_data(transformed_data)
                logger.info(
                    f"Stored baseline data for subscription {subscription_id} from {log_path}"
                )

                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=True,
                    diffs_fetched=0,
                    diffs_processed=1,  # Count baseline fetch as 1 processed item
                    final_sequence=response.get("sequence", 0),
                )
            else:
                logger.warning(
                    f"Failed to fetch baseline from {log_path} for subscription {subscription_id}"
                )
                return SubscriptionSyncResult(
                    subscription_id=subscription_id,
                    success=True,
                    diffs_fetched=0,
                    diffs_processed=0,
                    final_sequence=response.get("sequence", 0),
                )
        elif diffs_fetched == 0:
            return SubscriptionSyncResult(
                subscription_id=subscription_id,
                success=True,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=response.get("sequence", 0),
            )

        # Sort diffs by sequence
        diffs = sorted(diffs, key=lambda d: d.get("sequence", 0))

        from .actor_interface import ActorInterface

        actor_interface = ActorInterface(self._core_actor)

        diffs_processed = 0
        max_sequence = 0

        # Async handler for callback processing
        async def process_handler_async(cb):
            """Async handler to apply callback data to remote storage."""
            if config.auto_storage:
                store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )
                if cb.callback_type == CallbackType.RESYNC:
                    store.apply_resync_data(cb.data)
                else:
                    store.apply_callback_data(cb.data)

        if config.auto_sequence:
            processor = CallbackProcessor(
                actor=actor_interface,
                gap_timeout_seconds=config.gap_timeout_seconds,
                max_pending=config.max_pending,
            )

            for diff in diffs:
                seq = diff.get("sequence", 0)
                data = diff.get("data", {})
                timestamp = diff.get("timestamp", "")

                if timestamp and isinstance(data, dict):
                    data["timestamp"] = timestamp

                result = await processor.process_callback(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    sequence=seq,
                    data=data,
                    callback_type="diff",
                    handler=process_handler_async if config.auto_storage else None,
                )

                if result == ProcessResult.PROCESSED:
                    diffs_processed += 1

                if seq > max_sequence:
                    max_sequence = seq
        else:
            for diff in diffs:
                seq = diff.get("sequence", 0)
                data = diff.get("data", {})

                if config.auto_storage:
                    store = RemotePeerStore(
                        actor=actor_interface,
                        peer_id=peer_id,
                        validate_peer_id=False,
                    )
                    store.apply_callback_data(data)

                diffs_processed += 1
                if seq > max_sequence:
                    max_sequence = seq

        # Clear processed diffs on peer (async)
        if max_sequence > 0:
            clear_response = await proxy.change_resource_async(
                path=path, params={"sequence": max_sequence}
            )
            if clear_response is None or "error" in (clear_response or {}):
                logger.warning(
                    f"Failed to clear diffs on peer {peer_id} for subscription "
                    f"{subscription_id}, sequence {max_sequence}"
                )

        return SubscriptionSyncResult(
            subscription_id=subscription_id,
            success=True,
            diffs_fetched=diffs_fetched,
            diffs_processed=diffs_processed,
            final_sequence=max_sequence,
        )

    async def sync_peer_async(
        self,
        peer_id: str,
        config: "SubscriptionProcessingConfig | None" = None,
    ) -> PeerSyncResult:
        """
        Async version of sync_peer.

        Sync all outbound subscriptions to a peer.

        Args:
            peer_id: ID of the peer actor
            config: Optional processing configuration

        Returns:
            PeerSyncResult with aggregate sync outcome

        Example:
            result = await actor.subscriptions.sync_peer_async("peer123")
        """
        import asyncio

        # Get all outbound subscriptions to this peer
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        outbound_subs = [s for s in subscriptions if s.is_outbound]

        if not outbound_subs:
            return PeerSyncResult(
                peer_id=peer_id,
                success=True,
                subscriptions_synced=0,
                total_diffs_processed=0,
                subscription_results=[],
            )

        # Sync each subscription concurrently
        tasks = [
            self.sync_subscription_async(
                peer_id=peer_id,
                subscription_id=sub.subscription_id,
                config=config,
            )
            for sub in outbound_subs
        ]

        results = await asyncio.gather(*tasks)

        total_diffs = sum(r.diffs_processed for r in results)
        all_success = all(r.success for r in results)

        # Refresh peer profile if configured (async)
        # Try to use already-synced properties data first to avoid redundant fetch
        actor_config = self._core_actor.config
        actor_id = self._core_actor.id
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_profile_attributes", None)
        ):
            try:
                from datetime import UTC, datetime

                from ..peer_profile import PeerProfile, get_peer_profile_store
                from ..remote_storage import RemotePeerStore
                from .actor_interface import ActorInterface

                # Check if we have recently synced properties data
                actor_interface = ActorInterface(self._core_actor)
                remote_store = RemotePeerStore(
                    actor=actor_interface,
                    peer_id=peer_id,
                    validate_peer_id=False,
                )

                # Try to extract profile from synced properties
                profile_extracted = False
                profile = PeerProfile(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    fetched_at=datetime.now(UTC).isoformat(),
                )

                try:
                    # Get properties from remote store (properties are stored as values)
                    for attr in actor_config.peer_profile_attributes:
                        value_data = remote_store.get_value(attr)
                        if value_data is not None:
                            # Extract actual value (properties are wrapped in {"value": ...})
                            if isinstance(value_data, dict) and "value" in value_data:
                                actual_value = value_data["value"]
                            else:
                                actual_value = value_data

                            # Convert to string for standard profile attributes
                            if attr == "displayname":
                                profile.displayname = (
                                    str(actual_value)
                                    if actual_value is not None
                                    else None
                                )
                                profile_extracted = True
                            elif attr == "email":
                                profile.email = (
                                    str(actual_value)
                                    if actual_value is not None
                                    else None
                                )
                                profile_extracted = True
                            elif attr == "description":
                                profile.description = (
                                    str(actual_value)
                                    if actual_value is not None
                                    else None
                                )
                                profile_extracted = True
                            else:
                                # Store in extra_attributes (keep original type)
                                profile.extra_attributes[attr] = actual_value
                                profile_extracted = True
                except Exception:
                    # If reading from store fails, we'll fetch below
                    profile_extracted = False

                # Only fetch if we couldn't extract from synced data
                if not profile_extracted:
                    from ..peer_profile import fetch_peer_profile_async

                    profile = await fetch_peer_profile_async(
                        actor_id=actor_id,
                        peer_id=peer_id,
                        config=actor_config,
                        attributes=actor_config.peer_profile_attributes,
                    )
                    logger.debug(
                        f"Fetched peer profile (async) during sync_peer for {peer_id}"
                    )
                else:
                    logger.debug(
                        f"Extracted peer profile from synced properties for {peer_id} (avoided redundant fetch)"
                    )

                store = get_peer_profile_store(actor_config)
                store.store_profile(profile)
            except Exception as e:
                logger.warning(
                    f"Failed to refresh peer profile during sync (async): {e}"
                )

        # Refresh peer capabilities if configured (async)
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_capabilities_caching", False)
        ):
            try:
                from ..peer_capabilities import (
                    fetch_peer_methods_and_actions_async,
                    get_cached_capabilities_store,
                )

                capabilities = await fetch_peer_methods_and_actions_async(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                )
                store = get_cached_capabilities_store(actor_config)
                store.store_capabilities(capabilities)
                logger.debug(
                    f"Refreshed peer capabilities (async) during sync_peer for {peer_id}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to refresh peer capabilities during sync (async): {e}"
                )

        # Refresh peer permissions if configured (async)
        # This fetches from the peer's GET /permissions/{actor_id} endpoint
        # to establish initial permission baseline or refresh cached permissions.
        # Complements the reactive callback-based push mechanism.
        if (
            actor_config
            and actor_id
            and getattr(actor_config, "peer_permissions_caching", False)
        ):
            try:
                from ..peer_permissions import (
                    fetch_peer_permissions_async,
                    get_peer_permission_store,
                )

                permissions = await fetch_peer_permissions_async(
                    actor_id=actor_id,
                    peer_id=peer_id,
                    config=actor_config,
                )

                # Only store if fetch was successful (no error)
                # Don't overwrite callback-received permissions with empty data from 404
                if not permissions.fetch_error:
                    store = get_peer_permission_store(actor_config)
                    store.store_permissions(permissions)
                    logger.debug(
                        f"Refreshed peer permissions (async) during sync_peer for {peer_id}"
                    )
                else:
                    logger.debug(
                        f"Skipping permission storage during sync - fetch failed: {permissions.fetch_error}"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to refresh peer permissions during sync (async): {e}"
                )

        return PeerSyncResult(
            peer_id=peer_id,
            success=all_success,
            subscriptions_synced=len([r for r in results if r.success]),
            total_diffs_processed=total_diffs,
            subscription_results=list(results),
        )
