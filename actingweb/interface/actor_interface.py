"""
Improved Actor interface that wraps the core Actor class.

Provides a clean, intuitive interface for working with ActingWeb actors.
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

from ..actor import Actor as CoreActor
from ..deletion import DeletionStatus, get_deletion_status
from .property_store import PropertyStore
from .subscription_manager import SubscriptionManager
from .trust_manager import TrustManager

if TYPE_CHECKING:
    from ..attribute import InternalStore
    from ..config import Config
    from .authenticated_views import AuthenticatedActorView
    from .hooks import HookRegistry

logger = logging.getLogger(__name__)


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
        *,
        auth_method: str = "app",
        replace_holder: str | None = None,
    ) -> "ActorInterface":
        """
        Create a new actor.

        Args:
            creator: Creator identifier (usually email)
            config: ActingWeb Config object
            actor_id: Optional custom actor ID. Must not contain ``$``
                (reserved for the actor's property-list side partition) or
                be longer than 251 characters.
            passphrase: Optional custom passphrase
            delete_existing: Delete the existing actors with the same creator
                first (not atomic)
            trustee_root: Optional trustee root URL to set on the actor
            hooks: Optional hook registry for executing lifecycle hooks
            service_registry: Optional service registry for third-party service access
            auth_method: How the actor came to exist, a trust assertion about
                ``creator``. ``"app"`` (the default) means the application
                vouches for the creator. Pass ``"factory"`` for anything
                created from unauthenticated input: such an actor is replaced
                when a sign-in later proves the address. Written before
                ``actor_created`` fires.
            replace_holder: With ``with_unique_creator()``, the id of the
                actor that holds ``creator`` now. The creator moves to the new
                actor in the same backend step as the create; the caller
                removes the old actor afterwards.

        Returns:
            New ActorInterface instance

        Raises:
            CreatorTaken: with ``with_unique_creator()``, another actor holds
                ``creator`` (the integrations answer it with 409)
            DbError: on a backend fault (503)
            ValueError: ``actor_id`` contains ``$`` or is over 251
                characters; nothing was written
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
            auth_method=auth_method,
            replace_holder=replace_holder,
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
        ``DELETE /<actor_id>`` path fires those, and the replacement of an
        unvouched actor at sign-in (``reason="replaced_at_adoption"``), so an
        application deleting an actor programmatically owns its own cleanup. A deletion tombstone *is*
        written either way (see :meth:`get_deletion_status`).
        """
        self._core_actor.delete()

    def modify_creator(self, new_creator: str, *, unvouch: bool = False) -> bool:
        """
        Modify the creator of this actor.

        By default the application vouches for ``new_creator``: the
        ``auth_method`` marker is left as it is. Pass ``unvouch=True`` for an
        address nobody proved (user input): the change then follows
        ``PUT /<id>/trust/trustee``'s rules
        (:meth:`actingweb.actor.Actor.modify_creator_unvouched`), including the
        ``force_email_prop_as_creator`` pin, which refuses (returns False) an
        address other than the stored email.

        Args:
            new_creator: New creator identifier
            unvouch: Unvouch the actor unless the change hands it to nobody new

        Returns:
            True if successful, False otherwise, including for a reserved
            value (``#…``, ``#dup-``; with ``unvouch=True`` also ``system``
            and ``oauth2-system``)

        Raises:
            CreatorTaken: with ``with_unique_creator()``, another actor holds
                ``new_creator`` (the integrations answer it with 409)
        """
        from ..db.creator_rules import is_reserved

        if unvouch:
            return self._core_actor.modify_creator_unvouched(new_creator)
        if is_reserved(new_creator):
            # The uniqueness bookkeeping's values; only
            # actingweb-unique-creators writes them, through Actor.modify.
            return False
        return self._rename_vouched(new_creator)

    def _rename_vouched(self, new_creator: str) -> bool:
        """Rename and move a vouched actor's recorded address with it.

        The ``_internal`` bucket is read afresh, then the writes, in order
        (each confirmed with a strict read-back):

        0. ``vouched_creator`` := the current creator, when the actor is
           vouched for it only another way (its stored email, after the pin
           moved a provider-id creator; or a pending value) — a fault
           refuses the rename;
        1. ``vouched_creator_pending`` := the new address, when the actor is
           vouched with a recorded address (a fault refuses the rename);
        2. under ``force_email_prop_as_creator`` with a stored email, the
           email := the new address. This is the commit point: each load
           moves the creator to the stored email, so from here the rename
           completes even if this call stops;
        3. the creator;
        4. ``vouched_creator`` := the new address, then the pending value is
           removed.

        A sign-in at any point finds the actor vouched under the old creator
        (the recorded address) and under the new one (the pending address,
        and under the pin the stored email). Returns True once the creator
        is renamed; a fault in step 4 is logged and leaves the pending value
        vouching for the new creator. Returns False, with nothing moved but a
        pending value (which names only an address this application chose,
        and the next ``modify_creator`` overwrites), when the rename does not
        land; under the pin, when the stored email cannot be moved, or when
        the creator does not follow it (the email is then put back while it
        still holds the new address). Raises ``CreatorTaken`` (the email put
        back) and ``DbError``; after a ``DbError`` past step 2 the next load,
        or the same call again, completes the rename.

        Refused (False): the ``_internal`` bucket could not be read (unread,
        a vouched actor would look unvouched and its vouch would not move),
        and under the pin a creator that is not an address. An actor that is
        unvouched, or vouched before 3.16 (no recorded address), is renamed
        as it is. Concurrent renames of one actor are not serialised.
        """
        from ..attribute import InternalStore
        from ..db.creator_rules import normalise_creator
        from ..oauth2 import VOUCHED_CREATOR, VOUCHED_CREATOR_PENDING, is_vouched_store

        config = self._core_actor.config
        if not self.id or config is None or self._core_actor.store is None:
            return self._core_actor.modify(creator=new_creator)
        # Read afresh: a sign-in since this actor was loaded may have vouched
        # it, and a cached copy would rename it without moving that vouch.
        store = InternalStore(actor_id=self.id, config=config)
        self._core_actor.store = store
        if not store.loaded:
            logger.error(
                f"Actor {self.id}: its _internal bucket could not be read; "
                "rename refused"
            )
            return False
        bound = (
            is_vouched_store(store)
            and getattr(store, VOUCHED_CREATOR, None) is not None
        )
        target = normalise_creator(new_creator)
        current = self._core_actor.creator
        if (
            bound
            and isinstance(current, str)
            and normalise_creator(getattr(store, VOUCHED_CREATOR)) != current
            and is_vouched_store(store, current)
            and not store.set_confirmed(VOUCHED_CREATOR, current)
        ):
            # The current creator is vouched another way (the stored email,
            # or a pending value a faulted rename left): the pending and
            # email writes below would take that away while the creator is
            # still the current one, so record it first.
            logger.error(
                f"Actor {self.id}: the vouch for the current creator could not "
                "be recorded; rename refused"
            )
            return False
        current_email = store.email
        pinned = (
            current_email
            if config.force_email_prop_as_creator
            and isinstance(current_email, str)
            and current_email
            else None
        )
        if pinned is not None and "@" not in target:
            logger.error(
                f"Actor {self.id}: {target} is not an address and the creator is "
                "pinned to the stored email; rename refused"
            )
            return False
        if bound and not store.set_confirmed(VOUCHED_CREATOR_PENDING, target):
            logger.error(
                f"Actor {self.id}: the pending vouch for {target} did not "
                "land; rename refused"
            )
            return False
        if pinned is None:
            if not self._core_actor.modify(creator=new_creator):
                return False
        elif not self._rename_pinned(store, target, pinned, new_creator):
            return False
        if not bound:
            return True
        if not store.set_confirmed(VOUCHED_CREATOR, target):
            logger.warning(
                f"Actor {self.id}: renamed to {target}, but the recorded vouch "
                "could not be moved; the pending value still vouches for it"
            )
        elif not store.set_confirmed(VOUCHED_CREATOR_PENDING, None):
            logger.warning(
                f"Actor {self.id}: the pending vouch could not be removed after "
                "the rename; it names the current creator"
            )
        return True

    def _rename_pinned(
        self, store: "InternalStore", target: str, pinned: str, new_creator: str
    ) -> bool:
        """Steps 2 and 3 of :meth:`_rename_vouched` under the email pin: move
        the stored email (the commit point), then the creator. True once the
        creator is ``target``."""
        from ..db.exceptions import CreatorTaken

        moved = pinned.lower() != target
        if (
            moved
            and not store.set_confirmed("email", target)
            and store.read_strict("email") != target
        ):
            # Not moved (a lost acknowledgement of a write that landed reads
            # as moved and goes on); a read fault raises DbError.
            logger.error(
                f"Actor {self.id}: the stored email could not be moved to "
                f"{target}; rename refused"
            )
            return False
        try:
            renamed = self._core_actor.modify(creator=new_creator)
        except CreatorTaken:
            # Definite: another actor holds the address, so no load moves the
            # creator to it.
            if moved:
                self._restore_email(store, target, pinned)
            raise
        if renamed:
            return True
        # The conditional rename lost: a load that ran since this actor was
        # read may already have moved the creator to the new email. Load it
        # afresh (the load itself moves it, if it can) and look.
        fresh = CoreActor(actor_id=self.id, config=self._core_actor.config)
        if fresh.creator == target:
            # Take the fresh handle too: a later modify on this interface is
            # conditioned on the creator its handle was loaded with.
            self._core_actor.handle = fresh.handle
            self._core_actor.actor = fresh.actor
            self._core_actor.creator = target
            return True
        if moved:
            self._restore_email(store, target, pinned)
        return False

    def _restore_email(
        self, store: "InternalStore", moved_to: str, original: str
    ) -> None:
        """Put the stored email back after a rename that definitely did not
        land, only while it still holds the address this rename wrote: a
        concurrent rename's email is left alone. Never raises."""
        try:
            if store.replace_if_equal("email", moved_to, original):
                return
            still_moved = store.read_strict("email") == moved_to
        except Exception:  # folds DbError: best effort; the caller's outcome stands
            still_moved = True
        if still_moved:
            logger.error(
                f"Actor {self.id}: the rename did not land and the stored email "
                f"could not be put back to {original}"
            )

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
