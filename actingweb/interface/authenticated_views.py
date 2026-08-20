"""
Authenticated views for ActingWeb actors.

Provides permission-enforced access to actor resources based on trust relationships.
"""

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Optional

from ..permission_evaluator import PermissionResult, get_permission_evaluator

if TYPE_CHECKING:
    from ..config import Config
    from .actor_interface import ActorInterface
    from .hooks import HookRegistry
    from .property_store import PropertyStore
    from .subscription_manager import SubscriptionManager


class PermissionError(Exception):
    """Raised when an operation is denied due to insufficient permissions."""

    pass


logger = logging.getLogger(__name__)


class AuthContext:
    """Authentication context for permission evaluation."""

    def __init__(
        self,
        peer_id: str = "",
        client_id: str = "",
        trust_relationship: dict[str, Any] | None = None,
    ):
        self.peer_id = peer_id
        self.client_id = client_id
        self.trust_relationship = trust_relationship or {}

    @property
    def accessor_id(self) -> str:
        """Get the accessor identifier (peer_id or client_id)."""
        return self.peer_id or self.client_id

    @property
    def is_peer(self) -> bool:
        """Check if this is a peer access (actor-to-actor)."""
        return bool(self.peer_id)

    @property
    def is_client(self) -> bool:
        """Check if this is a client access (OAuth2/MCP)."""
        return bool(self.client_id) and not self.peer_id


class AuthenticatedPropertyStore:
    """Property store wrapper that enforces permission checks.

    All operations check permissions before delegating to the underlying store.
    """

    def __init__(
        self,
        property_store: "PropertyStore",
        auth_context: AuthContext,
        actor_id: str,
        config: Optional["Config"] = None,
    ):
        self._store = property_store
        self._auth_context = auth_context
        self._actor_id = actor_id
        self._config = config

    def _check_permission(self, key: str, operation: str) -> None:
        """Check permission and raise PermissionError if denied."""
        if not self._auth_context.accessor_id:
            # No accessor - allow (owner mode fallback)
            return

        if not self._config:
            # No config - allow for backward compatibility
            return

        try:
            evaluator = get_permission_evaluator(self._config)
            result = evaluator.evaluate_property_access(
                self._actor_id,
                self._auth_context.accessor_id,
                key,
                operation,
            )

            if result == PermissionResult.DENIED:
                raise PermissionError(
                    f"Access denied: {operation} on '{key}' for {self._auth_context.accessor_id}"
                )
            # ALLOWED or NOT_FOUND (fallback to legacy) - proceed
        except PermissionError:
            raise
        except Exception as e:
            # Fail closed on permission system errors (security best practice)
            logger.error(
                f"Permission system error for {operation} on '{key}': {e}. "
                f"Denying access as security precaution."
            )
            raise PermissionError(
                f"Permission system error: unable to verify {operation} access to '{key}'"
            ) from e

    def __getitem__(self, key: str) -> Any:
        """Get property value with permission check."""
        self._check_permission(key, "read")
        return self._store[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set property value with permission check."""
        self._check_permission(key, "write")
        self._store[key] = value

    def __delitem__(self, key: str) -> None:
        """Delete property with permission check."""
        self._check_permission(key, "delete")
        del self._store[key]

    def __contains__(self, key: str) -> bool:
        """Check if property exists (requires read permission)."""
        try:
            self._check_permission(key, "read")
            return key in self._store
        except PermissionError:
            return False

    def __iter__(self) -> Iterator[str]:
        """Iterate over accessible property keys."""
        # Filter to only keys we have read access to
        for key in self._store:
            try:
                self._check_permission(key, "read")
                yield key
            except PermissionError:
                continue

    def get(self, key: str, default: Any = None) -> Any:
        """Get property value with permission check."""
        try:
            self._check_permission(key, "read")
            return self._store.get(key, default)
        except PermissionError:
            return default

    def set(self, key: str, value: Any) -> None:
        """Set property value with permission check."""
        self[key] = value

    def delete(self, key: str) -> bool:
        """Delete property with permission check."""
        try:
            del self[key]
            return True
        except (PermissionError, KeyError):
            return False

    def keys(self) -> Iterator[str]:
        """Get accessible property keys."""
        return iter(self)

    def values(self) -> Iterator[Any]:
        """Get accessible property values."""
        for key in self:
            yield self[key]

    def items(self) -> Iterator[tuple[str, Any]]:
        """Get accessible property key-value pairs."""
        for key in self:
            yield (key, self[key])

    def to_dict(self) -> dict[str, Any]:
        """Convert accessible properties to dictionary."""
        return dict(self.items())


class _PermissionEnforcingListView:
    """Per-operation permission gate around a single list's
    ``NotifyingListProperty``.

    ``AuthenticatedPropertyListStore.__getattr__`` only checks ``read``
    before handing out a list -- returning the raw ``NotifyingListProperty``
    there let a read-only accessor mutate through it (append,
    ``__setitem__``, ``__delitem__``, ...) once past that one check. This
    view re-checks permission on every mutating call instead, and delegates
    reads unconditionally: the ``read`` check already ran before this view
    was constructed.

    Its public surface mirrors ``NotifyingListProperty`` method for method
    (see ``TestPermissionProxySurface`` in the test suite, which asserts
    the two stay in sync) -- a method added to ``NotifyingListProperty``
    without a matching entry here would otherwise be unreachable through
    ``actor.property_lists.<name>``, the only path the fluent API offers.
    """

    def __init__(self, list_prop: Any, list_name: str, parent: "AuthenticatedPropertyListStore"):
        self._list_prop = list_prop
        self._list_name = list_name
        self._parent = parent

    def _check(self, operation: str) -> None:
        self._parent._check_permission(self._list_name, operation)

    # Reads -- `read` was already checked before this view was constructed.
    def __len__(self) -> int:
        return len(self._list_prop)

    def __getitem__(self, index: int) -> Any:
        return self._list_prop[index]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._list_prop)

    def get_description(self) -> str:
        return self._list_prop.get_description()

    def get_explanation(self) -> str:
        return self._list_prop.get_explanation()

    def to_list(self) -> list[Any]:
        return self._list_prop.to_list()

    def to_indexed_list(self) -> list[tuple[int, Any]]:
        return self._list_prop.to_indexed_list()

    def prime_from_rows(self, rows: dict[str, Any]) -> None:
        self._list_prop.prime_from_rows(rows)

    def to_list_from_rows(self, rows: dict[str, Any]) -> list[Any]:
        return self._list_prop.to_list_from_rows(rows)

    def slice(self, start: int, end: int) -> list[Any]:
        return self._list_prop.slice(start, end)

    def index(self, value: Any, start: int = 0, stop: int | None = None) -> int:
        return self._list_prop.index(value, start, stop)

    def count(self, value: Any) -> int:
        return self._list_prop.count(value)

    def verify(self, identity_key: str | None = None) -> dict[str, Any]:
        return self._list_prop.verify(identity_key=identity_key)

    # Mutations -- `write` by default; `delete` for __delitem__/clear/delete,
    # matching AuthenticatedPropertyStore's per-operation split.
    def __setitem__(self, index: int, value: Any) -> None:
        self._check("write")
        self._list_prop[index] = value

    def __delitem__(self, index: int) -> None:
        self._check("delete")
        del self._list_prop[index]

    def set_description(self, description: str) -> None:
        self._check("write")
        self._list_prop.set_description(description)

    def set_explanation(self, explanation: str) -> None:
        self._check("write")
        self._list_prop.set_explanation(explanation)

    def append(self, item: Any) -> None:
        self._check("write")
        self._list_prop.append(item)

    def extend(self, items: list[Any]) -> None:
        self._check("write")
        self._list_prop.extend(items)

    def clear(self) -> None:
        self._check("delete")
        self._list_prop.clear()

    def delete(self) -> None:
        self._check("delete")
        self._list_prop.delete()

    def pop(self, index: int = -1) -> Any:
        self._check("write")
        return self._list_prop.pop(index)

    def insert(self, index: int, item: Any) -> None:
        self._check("write")
        self._list_prop.insert(index, item)

    def remove(self, value: Any) -> None:
        self._check("write")
        self._list_prop.remove(value)

    def compact(self) -> dict[str, Any]:
        self._check("write")
        return self._list_prop.compact()

    def migrate_to_v2(self, allow_damaged: bool = False) -> dict[str, Any]:
        self._check("write")
        return self._list_prop.migrate_to_v2(allow_damaged=allow_damaged)


class AuthenticatedPropertyListStore:
    """Property list store wrapper that enforces permission checks."""

    def __init__(
        self,
        property_list_store: Any,  # PropertyListStore
        auth_context: AuthContext,
        actor_id: str,
        config: Optional["Config"] = None,
    ):
        self._store = property_list_store
        self._auth_context = auth_context
        self._actor_id = actor_id
        self._config = config

    def _check_permission(self, list_name: str, operation: str) -> None:
        """Check permission for list property access."""
        if not self._auth_context.accessor_id:
            return

        if not self._config:
            # No config - allow for backward compatibility
            return

        try:
            evaluator = get_permission_evaluator(self._config)
            # List properties use the same permission system as regular properties
            # No "list:" prefix - that's an internal storage detail only
            result = evaluator.evaluate_property_access(
                self._actor_id,
                self._auth_context.accessor_id,
                list_name,
                operation,
            )

            if result == PermissionResult.DENIED:
                raise PermissionError(
                    f"Access denied: {operation} on list '{list_name}' for {self._auth_context.accessor_id}"
                )
        except PermissionError:
            raise
        except Exception as e:
            # Fail closed on permission system errors (security best practice)
            logger.error(
                f"Permission system error for {operation} on list '{list_name}': {e}. "
                f"Denying access as security precaution."
            )
            raise PermissionError(
                f"Permission system error: unable to verify {operation} access to list '{list_name}'"
            ) from e

    def __getattr__(self, name: str) -> Any:
        """Get a permission-enforcing view of the named list.

        Only `read` is checked here; the returned view re-checks `write`/
        `delete` on each mutating call so a read-only accessor cannot
        mutate through the object this returns (see
        `_PermissionEnforcingListView`).
        """
        if name.startswith("_"):
            return super().__getattribute__(name)

        self._check_permission(name, "read")
        return _PermissionEnforcingListView(getattr(self._store, name), name, self)

    def exists(self, name: str) -> bool:
        """Check if list exists (requires read permission)."""
        try:
            self._check_permission(name, "read")
            return self._store.exists(name)
        except PermissionError:
            return False

    def delete(self, name: str) -> bool:
        """Delete a list (requires delete permission).

        Lists are created lazily on first write, so there is no matching
        `create()` -- one existed here previously but its arguments passed
        straight through to `PropertyListStore.__getattr__`, which resolves
        any name to a `NotifyingListProperty` and returned it uncalled;
        calling that result raised `TypeError` after the permission check
        already passed. This method had the identical bug: `self._store` is
        a `PropertyListStore`, so `self._store.delete(name)` resolved
        `delete` as a LIST NAME through `__getattr__`, not a method, and
        called `NotifyingListProperty.delete()` -- which takes no
        arguments -- with `name` as an extra positional argument.
        """
        self._check_permission(name, "delete")
        getattr(self._store, name).delete()
        return True


class AuthenticatedSubscriptionManager:
    """Subscription manager wrapper that enforces permission checks."""

    def __init__(
        self,
        subscription_manager: "SubscriptionManager",
        auth_context: AuthContext,
        actor_id: str,
        config: Optional["Config"] = None,
    ):
        self._manager = subscription_manager
        self._auth_context = auth_context
        self._actor_id = actor_id
        self._config = config

    def _check_subscription_permission(self, target: str, subtarget: str = "") -> None:
        """Check if accessor can subscribe to the given target."""
        if not self._auth_context.accessor_id:
            return

        if not self._config:
            # No config - allow for backward compatibility
            return

        try:
            evaluator = get_permission_evaluator(self._config)
            # Use property read permission as proxy for subscription permission
            property_path = f"{target}/{subtarget}" if subtarget else target
            result = evaluator.evaluate_property_access(
                self._actor_id,
                self._auth_context.accessor_id,
                property_path,
                "read",
            )

            if result == PermissionResult.DENIED:
                raise PermissionError(
                    f"Subscription denied: {self._auth_context.accessor_id} to {target}"
                )
        except PermissionError:
            raise
        except Exception as e:
            # Fail closed on permission system errors (security best practice)
            logger.error(
                f"Subscription permission check error for {target}: {e}. "
                f"Denying access as security precaution."
            )
            raise PermissionError(
                f"Permission system error: unable to verify subscription to {target}"
            ) from e

    def create_local_subscription(
        self,
        target: str,
        subtarget: str = "",
        resource: str = "",
        granularity: str = "high",
    ) -> Any:
        """Accept a subscription request from the authenticated peer/client."""
        self._check_subscription_permission(target, subtarget)

        # Create subscription with the accessor as the peer
        return self._manager._core_actor.create_subscription(
            peerid=self._auth_context.accessor_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
        )

    # Delegate read-only operations without permission checks
    @property
    def all_subscriptions(self) -> list[Any]:
        """Get all subscriptions."""
        return self._manager.all_subscriptions

    @property
    def outbound_subscriptions(self) -> list[Any]:
        """Get outbound subscriptions."""
        return self._manager.outbound_subscriptions

    @property
    def inbound_subscriptions(self) -> list[Any]:
        """Get inbound subscriptions."""
        return self._manager.inbound_subscriptions


class AuthenticatedActorView:
    """A view of an actor with enforced permission checks.

    This class wraps ActorInterface and enforces permission checks on all
    operations based on the auth_context provided at construction time.

    Three modes of operation:

    1. Owner Mode (direct ActorInterface access):
       actor.properties["key"] = value  # Full access, no checks

    2. Peer Mode (actor.as_peer()):
       peer_view = actor.as_peer(peer_id, trust)
       peer_view.properties["key"] = value  # Permission checks enforced

    3. Client Mode (actor.as_client()):
       client_view = actor.as_client(client_id, trust)
       client_view.properties["key"] = value  # Permission checks enforced
    """

    def __init__(
        self,
        actor: "ActorInterface",
        auth_context: AuthContext,
        hooks: Optional["HookRegistry"] = None,
    ):
        self._actor = actor
        self._auth_context = auth_context
        self._hooks = hooks
        self._config = getattr(actor._core_actor, "config", None)

        # Cached authenticated stores
        self._properties: AuthenticatedPropertyStore | None = None
        self._property_lists: AuthenticatedPropertyListStore | None = None
        self._subscriptions: AuthenticatedSubscriptionManager | None = None

    @property
    def id(self) -> str | None:
        """Actor ID."""
        return self._actor.id

    @property
    def creator(self) -> str | None:
        """Actor creator."""
        return self._actor.creator

    @property
    def url(self) -> str:
        """Actor URL."""
        return self._actor.url

    @property
    def auth_context(self) -> AuthContext:
        """Get the authentication context for this view."""
        return self._auth_context

    @property
    def properties(self) -> AuthenticatedPropertyStore:
        """Property store with permission checks enforced."""
        if self._properties is None:
            self._properties = AuthenticatedPropertyStore(
                self._actor.properties,
                self._auth_context,
                self._actor.id or "",
                self._config,
            )
        return self._properties

    @property
    def property_lists(self) -> AuthenticatedPropertyListStore:
        """Property list store with permission checks enforced."""
        if self._property_lists is None:
            self._property_lists = AuthenticatedPropertyListStore(
                self._actor.property_lists,
                self._auth_context,
                self._actor.id or "",
                self._config,
            )
        return self._property_lists

    @property
    def subscriptions(self) -> AuthenticatedSubscriptionManager:
        """Subscription manager with permission checks enforced."""
        if self._subscriptions is None:
            self._subscriptions = AuthenticatedSubscriptionManager(
                self._actor.subscriptions,
                self._auth_context,
                self._actor.id or "",
                self._config,
            )
        return self._subscriptions

    @property
    def trust(self):
        """Trust manager (read-only for authenticated views)."""
        # Trust management operations should go through the actor directly
        # This is exposed for reading trust relationship info
        return self._actor.trust

    def is_valid(self) -> bool:
        """Check if this actor is valid."""
        return self._actor.is_valid()

    def to_dict(self) -> dict[str, Any]:
        """Convert accessible actor data to dictionary."""
        return {
            "id": self.id,
            "creator": self.creator,
            "url": self.url,
            "properties": self.properties.to_dict(),
            "accessor": self._auth_context.accessor_id,
        }
