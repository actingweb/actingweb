"""
Simplified subscription management for ActingWeb actors.
"""

from typing import Any

from ..actor import Actor as CoreActor
from ..subscription import Subscription as CoreSubscription


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

    def delete_callback_subscription(
        self, peer_id: str, subscription_id: str
    ) -> bool:
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
