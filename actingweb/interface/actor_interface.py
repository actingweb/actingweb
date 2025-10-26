"""
Improved Actor interface that wraps the core Actor class.

Provides a clean, intuitive interface for working with ActingWeb actors.
"""

from typing import TYPE_CHECKING, Any, Optional

from ..actor import Actor as CoreActor
from .property_store import PropertyStore
from .subscription_manager import SubscriptionManager
from .trust_manager import TrustManager

if TYPE_CHECKING:
    from ..config import Config


class ActorInterface:
    """
    Clean interface for ActingWeb actors.

    This class wraps the core Actor class and provides a more intuitive
    interface for developers.

    Example usage:

    .. code-block:: python

        # Create new actor
        actor = ActorInterface.create(
            creator="user@example.com",
            config=config,
        )

        # Access properties
        actor.properties.email = "user@example.com"
        actor.properties["settings"] = {"theme": "dark"}

        # Manage trust relationships
        peer = actor.trust.create_relationship(
            peer_url="https://peer.example.com/actor123",
            relationship="friend",
        )

        # Handle subscriptions
        actor.subscriptions.subscribe_to_peer(
            peer_id="peer123",
            target="properties",
        )

        # Notify subscribers
        actor.subscriptions.notify_subscribers(
            target="properties",
            data={"status": "active"},
        )
    """

    def __init__(self, core_actor: CoreActor, service_registry=None):
        self._core_actor = core_actor
        self._property_store: PropertyStore | None = None
        self._property_list_store = None  # Will be initialized on first access
        self._trust_manager: TrustManager | None = None
        self._subscription_manager: SubscriptionManager | None = None
        if service_registry is not None:
            self._service_registry = service_registry
        else:
            config = getattr(core_actor, "config", None)
            registry_from_config = getattr(config, "service_registry", None) if config is not None else None
            self._service_registry = registry_from_config
        self._services = None  # Will be initialized on first access

    @classmethod
    def create(cls, creator: str, config: 'Config', actor_id: str | None = None,
               passphrase: str | None = None, delete_existing: bool = False,
               trustee_root: str | None = None, hooks: Any = None, service_registry=None) -> 'ActorInterface':
        """
        Create a new actor.

        Args:
            creator: Creator identifier (usually email)
            config: ActingWeb Config object
            actor_id: Optional custom actor ID
            passphrase: Optional custom passphrase
            delete_existing: Whether to delete existing actor with same creator
            trustee_root: Optional trustee root URL to set on the actor
            hooks: Optional hook registry for executing lifecycle hooks
            service_registry: Optional service registry for third-party service access

        Returns:
            New ActorInterface instance
        """
        core_actor = CoreActor(config=config)

        if service_registry is None:
            service_registry = getattr(config, "service_registry", None)

        if not passphrase:
            passphrase = config.new_token() if config else ""

        success = core_actor.create(
            url=config.root if config else "",
            creator=creator,
            passphrase=passphrase,
            actor_id=actor_id,
            delete=delete_existing,
            trustee_root=trustee_root,
            hooks=hooks
        )

        if not success:
            raise RuntimeError(f"Failed to create actor for creator: {creator}")

        return cls(core_actor, service_registry)

    @classmethod
    def get_by_id(cls, actor_id: str, config: 'Config', service_registry=None) -> Optional['ActorInterface']:
        """
        Get an existing actor by ID.

        Args:
            actor_id: Actor ID
            config: ActingWeb Config object
            service_registry: Optional service registry for third-party service access

        Returns:
            ActorInterface instance or None if not found
        """
        core_actor = CoreActor(actor_id=actor_id, config=config)
        if service_registry is None:
            service_registry = getattr(config, "service_registry", None)
        if core_actor.id:
            return cls(core_actor, service_registry)
        return None

    @classmethod
    def get_by_creator(cls, creator: str, config: 'Config', service_registry=None) -> Optional['ActorInterface']:
        """
        Get an existing actor by creator.

        Args:
            creator: Creator identifier
            config: ActingWeb Config object
            service_registry: Optional service registry for third-party service access

        Returns:
            ActorInterface instance or None if not found
        """
        core_actor = CoreActor(config=config)
        if service_registry is None:
            service_registry = getattr(config, "service_registry", None)
        if core_actor.get_from_creator(creator=creator):
            return cls(core_actor, service_registry)
        return None

    @classmethod
    def get_by_property(cls, property_name: str, property_value: str, config: 'Config', service_registry=None) -> Optional['ActorInterface']:
        """
        Get an existing actor by property value.

        Args:
            property_name: Property name to search
            property_value: Property value to match
            config: ActingWeb Config object
            service_registry: Optional service registry for third-party service access

        Returns:
            ActorInterface instance or None if not found
        """
        core_actor = CoreActor(config=config)
        if service_registry is None:
            service_registry = getattr(config, "service_registry", None)
        core_actor.get_from_property(name=property_name, value=property_value)
        if core_actor.id:
            return cls(core_actor, service_registry)
        return None

    @property
    def id(self) -> str | None:
        """Actor ID."""
        return self._core_actor.id

    @property
    def creator(self) -> str | None:
        """Actor creator."""
        return self._core_actor.creator

    @property
    def passphrase(self) -> str | None:
        """Actor passphrase."""
        return self._core_actor.passphrase

    @property
    def url(self) -> str:
        """Actor URL."""
        if self._core_actor.config and self.id:
            return f"{self._core_actor.config.root}{self.id}"
        return ""

    @property
    def properties(self) -> PropertyStore:
        """Actor properties."""
        if self._property_store is None:
            if not hasattr(self._core_actor, 'property') or self._core_actor.property is None:
                raise RuntimeError("Actor properties not available - actor may not be properly initialized")
            self._property_store = PropertyStore(self._core_actor.property)
        return self._property_store

    @property
    def property_lists(self):
        """Actor property lists for distributed storage."""
        if self._property_list_store is None:
            # Import here to avoid circular imports
            from ..property import PropertyListStore
            self._property_list_store = PropertyListStore(actor_id=self.id, config=self._core_actor.config)
        return self._property_list_store

    @property
    def trust(self) -> TrustManager:
        """Trust relationship manager."""
        if self._trust_manager is None:
            self._trust_manager = TrustManager(self._core_actor)
        return self._trust_manager

    @property
    def subscriptions(self) -> SubscriptionManager:
        """Subscription manager."""
        if self._subscription_manager is None:
            self._subscription_manager = SubscriptionManager(self._core_actor)
        return self._subscription_manager

    @property
    def services(self):
        """Third-party service client manager."""
        if self._services is None:
            if self._service_registry is None:
                raise RuntimeError("No service registry available. Configure services using ActingWebApp.add_service() methods.")
            # Import fixed after removing init_actingweb
            try:
                from .services.service_registry import ActorServices
                self._services = ActorServices(self, self._service_registry)
            except ImportError as e:
                raise RuntimeError("ActorServices not available. Service registry functionality requires proper installation.") from e
        return self._services

    @property
    def core_actor(self) -> CoreActor:
        """Access to underlying core actor (for advanced use)."""
        return self._core_actor

    def delete(self) -> None:
        """Delete this actor and all associated data."""
        self._core_actor.delete()

    def modify_creator(self, new_creator: str) -> bool:
        """
        Modify the creator of this actor.

        Args:
            new_creator: New creator identifier

        Returns:
            True if successful, False otherwise
        """
        return self._core_actor.modify(creator=new_creator)

    def is_valid(self) -> bool:
        """Check if this actor is valid (has ID and exists)."""
        return self.id is not None and len(self.id) > 0

    def is_owner(self) -> bool:
        """Check if current user is the owner of this actor."""
        # This is a placeholder implementation
        # In a real implementation, this would check authentication context
        return True

    def refresh(self) -> bool:
        """Refresh actor data from storage."""
        if self.id is None:
            return False
        actor_data = self._core_actor.get(actor_id=self.id)
        return actor_data is not None and len(actor_data) > 0

    def get_peer_info(self, peer_url: str) -> dict[str, Any]:
        """
        Get information about a peer actor.

        Args:
            peer_url: URL of the peer actor

        Returns:
            Dictionary with peer information
        """
        return self._core_actor.get_peer_info(peer_url)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert actor to dictionary representation.

        Returns:
            Dictionary with actor data
        """
        return {
            "id": self.id,
            "creator": self.creator,
            "url": self.url,
            "properties": self.properties.to_dict(),
            "trust_relationships": len(self.trust.relationships),
            "subscriptions": len(self.subscriptions.all_subscriptions)
        }

    def __str__(self) -> str:
        """String representation of actor."""
        return f"Actor(id={self.id}, creator={self.creator})"

    def __repr__(self) -> str:
        """Detailed representation of actor."""
        return f"ActorInterface(id={self.id}, creator={self.creator}, url={self.url})"
