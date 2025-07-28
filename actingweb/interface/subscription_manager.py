"""
Simplified subscription management for ActingWeb actors.
"""

from typing import List, Dict, Any, Optional
from ..actor import Actor as CoreActor


class SubscriptionInfo:
    """Represents a subscription to or from another actor."""
    
    def __init__(self, data: Dict[str, Any]):
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
    def subtarget(self) -> Optional[str]:
        """Subtarget being subscribed to."""
        return self._data.get("subtarget")
        
    @property
    def resource(self) -> Optional[str]:
        """Resource being subscribed to."""
        return self._data.get("resource")
        
    @property
    def granularity(self) -> str:
        """Granularity of notifications (high, low, none)."""
        return self._data.get("granularity", "high")
        
    @property
    def is_callback(self) -> bool:
        """Whether this is a callback subscription (from another actor)."""
        return self._data.get("callback", False)
        
    @property
    def is_outbound(self) -> bool:
        """Whether this is an outbound subscription (to another actor)."""
        return not self.is_callback
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return self._data.copy()


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
    def all_subscriptions(self) -> List[SubscriptionInfo]:
        """Get all subscriptions (both inbound and outbound)."""
        subscriptions = self._core_actor.get_subscriptions()
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]
        
    @property
    def outbound_subscriptions(self) -> List[SubscriptionInfo]:
        """Get subscriptions to other actors."""
        return [sub for sub in self.all_subscriptions if sub.is_outbound]
        
    @property
    def inbound_subscriptions(self) -> List[SubscriptionInfo]:
        """Get subscriptions from other actors."""
        return [sub for sub in self.all_subscriptions if sub.is_callback]
        
    def get_subscriptions_to_peer(self, peer_id: str) -> List[SubscriptionInfo]:
        """Get all subscriptions to a specific peer."""
        subscriptions = self._core_actor.get_subscriptions(peerid=peer_id)
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]
        
    def get_subscriptions_for_target(self, target: str, subtarget: str = "", 
                                   resource: str = "") -> List[SubscriptionInfo]:
        """Get all subscriptions for a specific target."""
        subscriptions = self._core_actor.get_subscriptions(
            target=target, 
            subtarget=subtarget or None,
            resource=resource or None
        )
        if subscriptions is None:
            return []
        return [SubscriptionInfo(sub) for sub in subscriptions if isinstance(sub, dict)]
        
    def subscribe_to_peer(self, peer_id: str, target: str, subtarget: str = "",
                         resource: str = "", granularity: str = "high") -> Optional[str]:
        """
        Subscribe to another actor's data.
        
        Returns the subscription URL if successful, None otherwise.
        """
        result = self._core_actor.create_remote_subscription(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity
        )
        # Handle the case where the method returns False instead of None
        return result if result and isinstance(result, str) else None
        
    def unsubscribe(self, peer_id: str, subscription_id: str) -> bool:
        """Unsubscribe from a peer's data."""
        # Try to delete remote subscription first
        remote_result = self._core_actor.delete_remote_subscription(peerid=peer_id, subid=subscription_id)
        if remote_result:
            # Then delete local subscription
            local_result = self._core_actor.delete_subscription(peerid=peer_id, subid=subscription_id)
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
        
    def notify_subscribers(self, target: str, data: Dict[str, Any], 
                         subtarget: str = "", resource: str = "") -> None:
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
            blob=blob
        )
        
    def get_subscription(self, peer_id: str, subscription_id: str) -> Optional[SubscriptionInfo]:
        """Get a specific subscription."""
        sub_data = self._core_actor.get_subscription(peerid=peer_id, subid=subscription_id)
        if sub_data and isinstance(sub_data, dict):
            return SubscriptionInfo(sub_data)
        return None
        
    def has_subscribers_for(self, target: str, subtarget: str = "", resource: str = "") -> bool:
        """Check if there are any subscribers for the given target."""
        subscriptions = self.get_subscriptions_for_target(target, subtarget, resource)
        return len([sub for sub in subscriptions if sub.is_callback]) > 0
        
    def get_subscribers_for(self, target: str, subtarget: str = "", resource: str = "") -> List[str]:
        """Get list of peer IDs subscribed to the given target."""
        subscriptions = self.get_subscriptions_for_target(target, subtarget, resource)
        return [sub.peer_id for sub in subscriptions if sub.is_callback]
        
    def cleanup_peer_subscriptions(self, peer_id: str) -> bool:
        """Remove all subscriptions related to a specific peer."""
        # This is typically called when a trust relationship is deleted
        subscriptions = self.get_subscriptions_to_peer(peer_id)
        success = True
        for sub in subscriptions:
            result = self._core_actor.delete_subscription(
                peerid=peer_id, 
                subid=sub.subscription_id,
                callback=sub.is_callback
            )
            if not result:
                success = False
        return success