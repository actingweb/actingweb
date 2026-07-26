"""
Improved Actor interface that wraps the core Actor class.

Provides a clean, intuitive interface for working with ActingWeb actors.
"""

from typing import TYPE_CHECKING, Any, Optional

from ..actor import Actor as CoreActor
from ..deletion import DeletionStatus, get_deletion_status
from .property_store import PropertyStore
from .subscription_manager import SubscriptionManager
from .trust_manager import TrustManager

if TYPE_CHECKING:
    from ..config import Config
    from .authenticated_views import AuthenticatedActorView
    from .hooks import HookRegistry


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

    def __init__(
        self,
        core_actor: CoreActor,
        service_registry=None,
        hooks: Optional["HookRegistry"] = None,
    ):
        self._core_actor = core_actor
        self._property_store: PropertyStore | None = None
        self._property_list_store = None  # Will be initialized on first access
        self._trust_manager: TrustManager | None = None
        self._subscription_manager: SubscriptionManager | None = None

        # Get hooks from parameter, config, or None
        if hooks is not None:
            self._hooks = hooks
        else:
            config = getattr(core_actor, "config", None)
            self._hooks = getattr(config, "_hooks", None) if config else None

        if service_registry is not None:
            self._service_registry = service_registry
        else:
            config = getattr(core_actor, "config", None)
            registry_from_config = (
                getattr(config, "service_registry", None)
                if config is not None
                else None
            )
            self._service_registry = registry_from_config
        self._services = None  # Will be initialized on first access

    @classmethod
    def create(
        cls,
        creator: str,
        config: "Config",
        actor_id: str | None = None,
        passphrase: str | None = None,
        delete_existing: bool = False,
        trustee_root: str | None = None,
        hooks: Any = None,
        service_registry=None,
    ) -> "ActorInterface":
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
            hooks=hooks,
        )

        if not success:
            raise RuntimeError(f"Failed to create actor for creator: {creator}")

        return cls(core_actor, service_registry)

    @classmethod
    def get_by_id(
        cls, actor_id: str, config: "Config", service_registry=None
    ) -> Optional["ActorInterface"]:
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
    def get_deletion_status(cls, actor_id: str, config: "Config") -> DeletionStatus:
        """
        Whether an actor has been deleted — or whether that cannot be determined.

        Prefer this over ``get_by_id(...) is None`` for any guard of the form
        "do not do this work if the actor is gone". Two reasons, both of which
        make the absence check wrong rather than merely weaker:

        - ``get_by_id()`` keeps returning an actor for the whole of
          :meth:`delete`, because the actor row is removed last. The absence
          check fails **open** exactly in the window it exists for.
        - ``get_by_id()`` returns ``None`` for a deleted actor *and* for a
          failed read. A guard that skips on ``None`` also skips on a DynamoDB
          throttle — silently. For a paid-subscription webhook that means the
          customer paid and never got access.

        This call answers with three values instead of two, from a tombstone
        written before the wipe begins. Treat ``UNKNOWN`` as "proceed": the
        worst case is one orphan row an operator sweep can find, whereas
        treating it as "deleted" drops real work.

        Costs one strongly-consistent point read.

        .. code-block:: python

            from actingweb.interface import ActorInterface, DeletionStatus

            status = ActorInterface.get_deletion_status(actor_id, config)
            if status == DeletionStatus.DELETED:
                return  # late provider callback for a deleted account
            # NOT_DELETED and UNKNOWN both proceed

        Args:
            actor_id: Actor ID
            config: ActingWeb Config object

        Returns:
            :class:`~actingweb.deletion.DeletionStatus`

        See Also:
            :mod:`actingweb.deletion` for the full rationale, and the
            ``actor_deleted_complete`` lifecycle hook for cleanup that must run
            after the wipe rather than racing it.
        """
        return get_deletion_status(actor_id, config)

    @classmethod
    def get_by_creator(
        cls, creator: str, config: "Config", service_registry=None
    ) -> Optional["ActorInterface"]:
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
    def get_by_property(
        cls,
        property_name: str,
        property_value: str,
        config: "Config",
        service_registry=None,
    ) -> Optional["ActorInterface"]:
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
            if (
                not hasattr(self._core_actor, "property")
                or self._core_actor.property is None
            ):
                raise RuntimeError(
                    "Actor properties not available - actor may not be properly initialized"
                )
            self._property_store = PropertyStore(
                self._core_actor.property,
                actor=self._core_actor,
                hooks=self._hooks,
                config=getattr(self._core_actor, "config", None),
            )
        return self._property_store

    @property
    def property_lists(self):
        """Actor property lists for distributed storage with subscription notifications."""
        if self._property_list_store is None:
            # Import here to avoid circular imports
            from ..property import PropertyListStore as CorePropertyListStore
            from .property_store import PropertyListStore

            # Create the core store
            core_store = CorePropertyListStore(
                actor_id=self.id, config=self._core_actor.config
            )
            # Wrap with notification support
            self._property_list_store = PropertyListStore(core_store, self._core_actor)
        return self._property_list_store

    @property
    def trust(self) -> TrustManager:
        """Trust relationship manager."""
        if self._trust_manager is None:
            self._trust_manager = TrustManager(self._core_actor, hooks=self._hooks)
        return self._trust_manager

    @property
    def subscriptions(self) -> SubscriptionManager:
        """Subscription manager."""
        if self._subscription_manager is None:
            self._subscription_manager = SubscriptionManager(
                self._core_actor, hooks=self._hooks
            )
        return self._subscription_manager

    @property
    def services(self):
        """Third-party service client manager."""
        if self._services is None:
            if self._service_registry is None:
                raise RuntimeError(
                    "No service registry available. Configure services using ActingWebApp.add_service() methods."
                )
            # Import fixed after removing init_actingweb
            try:
                from .services.service_registry import ActorServices

                self._services = ActorServices(self, self._service_registry)
            except ImportError as e:
                raise RuntimeError(
                    "ActorServices not available. Service registry functionality requires proper installation."
                ) from e
        return self._services

    @property
    def core_actor(self) -> CoreActor:
        """Access to underlying core actor (for advanced use)."""
        return self._core_actor

    @property
    def config(self):
        """Get the ActingWeb configuration object.

        Returns:
            ActingWeb configuration instance

        Raises:
            RuntimeError: If config is not available
        """
        if not hasattr(self._core_actor, "config") or self._core_actor.config is None:
            raise RuntimeError("Actor config not available")
        return self._core_actor.config

    def delete(self) -> None:
        """Delete this actor and all associated data.

        Note that this does **not** run lifecycle hooks — neither
        ``actor_deleted`` nor ``actor_deleted_complete``. Only the HTTP
        ``DELETE /<actor_id>`` path fires those, so an application deleting an
        actor programmatically owns its own cleanup. A deletion tombstone *is*
        written either way (see :meth:`get_deletion_status`).
        """
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

    def as_peer(
        self, peer_id: str, trust_relationship: dict[str, Any] | None = None
    ) -> "AuthenticatedActorView":
        """Create a view of this actor as seen by a peer.

        All operations on this view will have permission checks enforced
        based on the peer's trust relationship.

        Args:
            peer_id: The peer actor's ID
            trust_relationship: Optional trust relationship data

        Returns:
            AuthenticatedActorView with permission enforcement

        Example:
            peer_view = actor.as_peer("peer123", trust_data)
            peer_view.properties["shared_data"] = value  # Permission checked
        """
        from .authenticated_views import AuthContext, AuthenticatedActorView

        auth_context = AuthContext(
            peer_id=peer_id,
            trust_relationship=trust_relationship,
        )
        return AuthenticatedActorView(self, auth_context, self._hooks)

    def as_client(
        self, client_id: str, trust_relationship: dict[str, Any] | None = None
    ) -> "AuthenticatedActorView":
        """Create a view of this actor as seen by an OAuth2/MCP client.

        All operations on this view will have permission checks enforced
        based on the client's trust relationship.

        Args:
            client_id: The OAuth2/MCP client ID
            trust_relationship: Optional trust relationship data

        Returns:
            AuthenticatedActorView with permission enforcement

        Example:
            client_view = actor.as_client("mcp_client_123", trust_data)
            client_view.properties["user_data"] = value  # Permission checked
        """
        from .authenticated_views import AuthContext, AuthenticatedActorView

        auth_context = AuthContext(
            client_id=client_id,
            trust_relationship=trust_relationship,
        )
        return AuthenticatedActorView(self, auth_context, self._hooks)

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
            "subscriptions": len(self.subscriptions.all_subscriptions),
        }

    def __str__(self) -> str:
        """String representation of actor."""
        return f"Actor(id={self.id}, creator={self.creator})"

    def __repr__(self) -> str:
        """Detailed representation of actor."""
        return f"ActorInterface(id={self.id}, creator={self.creator}, url={self.url})"
