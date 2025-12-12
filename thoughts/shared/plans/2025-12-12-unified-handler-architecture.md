# Unified Handler Architecture Implementation Plan

## Overview

Refactor ActingWeb to ensure consistent behavior whether actor operations are triggered via HTTP handlers (Flask/FastAPI) or the developer API. This involves moving business logic (permissions, hooks, subscription notifications) into the developer API and introducing an "authenticated views" pattern for permission enforcement.

## Current State Analysis

### The Problem

Currently, there's a split architecture where:

1. **Handlers** contain business logic:
   - Permission checks (`_check_property_permission`)
   - Hook execution (`execute_property_hooks`, `execute_lifecycle_hooks`)
   - Subscription notifications (`register_diffs`)

2. **Developer API** bypasses this logic:
   - `PropertyStore.__setitem__` just delegates to core store
   - `TrustManager.approve_relationship` doesn't trigger `trust_approved` hook
   - `TrustManager.delete_relationship` doesn't trigger `trust_deleted` hook
   - Property list operations don't call `register_diffs`

### Key Files Affected

| File | Current Role | Changes Needed |
|------|-------------|----------------|
| `actingweb/interface/actor_interface.py` | Actor wrapper | Add `as_peer()`, `as_client()`, wire hooks |
| `actingweb/interface/property_store.py` | Thin wrapper | Add hooks + `register_diffs` |
| `actingweb/interface/trust_manager.py` | Thin wrapper | Add lifecycle hooks |
| `actingweb/interface/subscription_manager.py` | Has `notify_subscribers` | Add permission checks |
| `actingweb/property_list.py` | List storage | Add `register_diffs` to mutations |
| `actingweb/handlers/properties.py` | Full business logic | Refactor to use developer API |
| `actingweb/handlers/trust.py` | Full business logic | Refactor to use developer API |

## Desired End State

After implementation:

1. **Same operation, same behavior** - whether via HTTP or developer API
2. **Three access modes**:
   - Owner mode: `actor.properties["key"] = value` (full access, no permission checks)
   - Peer mode: `actor.as_peer(peer_id, trust).properties["key"] = value` (permission checks)
   - Client mode: `actor.as_client(client_id, trust).properties["key"] = value` (permission checks)
3. **Automatic notifications**: All property mutations trigger `register_diffs`
4. **Automatic hooks**: All lifecycle events trigger appropriate hooks
5. **Thin handlers**: HTTP handlers only do request parsing and response building

### Verification

- All existing tests pass
- New unit tests for authenticated views
- Integration tests verify subscription notifications work via developer API
- Handlers produce identical results to direct API calls

## What We're NOT Doing

- Changing the HTTP API contract
- Breaking backward compatibility for existing applications
- Modifying the core Actor class significantly
- Changing database schema
- Refactoring Flask/FastAPI integrations to share code (future work)

## Testing Environment

**Prerequisites**: DynamoDB is running locally via Docker Compose throughout implementation.

```bash
# Start DynamoDB before beginning implementation
docker-compose -f docker-compose.test.yml up -d

# Verify DynamoDB is running
curl http://localhost:8001

# Keep running throughout all phases - stop only when completely done
docker-compose -f docker-compose.test.yml down -v
```

**Validation Strategy**: Use HTTP API integration tests to validate behavior at every phase. The existing integration test suite (`tests/integration/`) tests the full HTTP API and must pass throughout implementation. Run after each significant change:

```bash
# Run integration tests (requires DynamoDB)
make test-integration

# Or manually:
poetry run pytest tests/integration/ -v --tb=short
```

## Implementation Approach

We'll implement in layers from bottom to top:

1. Enhance base stores with hooks and notifications
2. Create authenticated view wrappers
3. Wire hooks through ActorInterface
4. Refactor handlers to use developer API
5. Fix property list notification gap
6. Add async variants where needed
7. Update documentation

---

## Phase 1: Enhance PropertyStore with Hooks and Notifications [COMPLETED]

### Overview

Add hook execution and `register_diffs` calls to `PropertyStore` so all property mutations automatically trigger the appropriate side effects.

### Changes Required

#### 1. PropertyStore Enhancement

**File**: `actingweb/interface/property_store.py`

**Changes**:
- Accept `actor`, `hooks`, and `config` in constructor
- Add `register_diffs` calls to `__setitem__`, `__delitem__`, `set`, `delete`, `update`, `clear`
- Execute property hooks before storing values

```python
"""
Simplified property store interface for ActingWeb actors.
"""

import json
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Optional

from ..property import PropertyStore as CorePropertyStore

if TYPE_CHECKING:
    from ..actor import Actor as CoreActor
    from ..config import Config
    from .hooks import HookRegistry


class PropertyStore:
    """
    Clean interface for actor property management.

    Provides dictionary-like access to actor properties with automatic
    subscription notifications and hook execution.

    Example usage:
        actor.properties.email = "user@example.com"
        actor.properties["config"] = {"theme": "dark"}

        if "email" in actor.properties:
            print(actor.properties.email)

        for key, value in actor.properties.items():
            print(f"{key}: {value}")
    """

    def __init__(
        self,
        core_store: CorePropertyStore,
        actor: Optional["CoreActor"] = None,
        hooks: Optional["HookRegistry"] = None,
        config: Optional["Config"] = None,
    ):
        self._core_store = core_store
        self._actor = actor
        self._hooks = hooks
        self._config = config

    def _execute_property_hook(
        self, key: str, operation: str, value: Any, path: list[str]
    ) -> Any:
        """Execute property hook and return transformed value (or original if no hook)."""
        if not self._hooks or not self._actor:
            return value

        try:
            from .actor_interface import ActorInterface

            # Create ActorInterface wrapper for hook execution
            actor_interface = ActorInterface(self._actor)

            # Execute hook - returns transformed value or None if rejected
            result = self._hooks.execute_property_hooks(
                key, operation, actor_interface, value, path
            )
            return result if result is not None else value
        except Exception as e:
            logging.warning(f"Error executing property hook for {key}: {e}")
            return value

    def _register_diff(self, key: str, value: Any, resource: str = "") -> None:
        """Register a diff for subscription notifications."""
        if not self._actor:
            return

        try:
            blob = json.dumps(value) if value is not None else ""
            self._actor.register_diffs(
                target="properties",
                subtarget=key,
                resource=resource or None,
                blob=blob,
            )
        except Exception as e:
            logging.warning(f"Error registering diff for {key}: {e}")

    def __getitem__(self, key: str) -> Any:
        """Get property value by key."""
        return self._core_store[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Set property value by key with hook execution and diff registration."""
        # Execute pre-store hook
        transformed = self._execute_property_hook(key, "put", value, [key])

        # Store the value
        self._core_store[key] = transformed

        # Register diff for subscribers
        self._register_diff(key, transformed)

    def __delitem__(self, key: str) -> None:
        """Delete property by key with diff registration."""
        self._core_store[key] = None
        self._register_diff(key, "")

    def __contains__(self, key: str) -> bool:
        """Check if property exists."""
        try:
            return self._core_store[key] is not None
        except (KeyError, AttributeError):
            return False

    def __iter__(self) -> Iterator[str]:
        """Iterate over property keys."""
        try:
            if hasattr(self._core_store, "get_all"):
                all_props = self._core_store.get_all()
                if isinstance(all_props, dict):
                    return iter(all_props.keys())
            return iter([])
        except (AttributeError, TypeError):
            return iter([])

    def __getattr__(self, key: str) -> Any:
        """Get property value as attribute."""
        try:
            return self._core_store[key]
        except (KeyError, AttributeError) as err:
            raise AttributeError(f"Property '{key}' not found") from err

    def __setattr__(self, key: str, value: Any) -> None:
        """Set property value as attribute."""
        if key.startswith("_"):
            super().__setattr__(key, value)
        else:
            if hasattr(self, "_core_store") and self._core_store is not None:
                self[key] = value  # Use __setitem__ for hooks/diffs

    def get(self, key: str, default: Any = None) -> Any:
        """Get property value with default."""
        try:
            value = self._core_store[key]
            return value if value is not None else default
        except (KeyError, AttributeError):
            return default

    def set(self, key: str, value: Any) -> None:
        """Set property value with hooks and diff registration."""
        self[key] = value  # Delegate to __setitem__

    def set_without_notification(self, key: str, value: Any) -> None:
        """Set property value without triggering subscription notifications.

        Use this for internal operations where notifications are not desired.
        """
        self._core_store[key] = value

    def delete(self, key: str) -> bool:
        """Delete property and return True if it existed."""
        try:
            if key in self:
                del self[key]  # Use __delitem__ for diff registration
                return True
            return False
        except (KeyError, AttributeError):
            return False

    def keys(self) -> Iterator[str]:
        """Get all property keys."""
        return iter(self)

    def values(self) -> Iterator[Any]:
        """Get all property values."""
        for key in self:
            yield self[key]

    def items(self) -> Iterator[tuple[str, Any]]:
        """Get all property key-value pairs."""
        for key in self:
            yield (key, self[key])

    def update(self, other: dict[str, Any]) -> None:
        """Update properties from dictionary with hooks and diff registration."""
        for key, value in other.items():
            self[key] = value

    def clear(self) -> None:
        """Clear all properties with diff registration."""
        keys = list(self.keys())
        for key in keys:
            del self[key]

        # Also register a "clear all" diff
        if self._actor and keys:
            self._actor.register_diffs(
                target="properties", subtarget=None, blob=""
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return dict(self.items())

    @property
    def core_store(self) -> CorePropertyStore:
        """Access underlying core property store."""
        return self._core_store
```

### Success Criteria

#### Automated Verification:
- [ ] All existing property store tests pass: `poetry run pytest tests/test_property_store.py -v`
- [ ] Type checking passes: `poetry run pyright actingweb/interface/property_store.py`
- [ ] Linting passes: `poetry run ruff check actingweb/interface/property_store.py`
- [ ] Integration tests pass (no regression): `make test-integration`

#### HTTP API Tests (add to `tests/integration/test_property_notifications.py`):
- [ ] `PUT /{actor_id}/properties/{name}` triggers subscription diff (verify via `GET /{actor_id}/subscriptions/{subid}/diffs`)
- [ ] `DELETE /{actor_id}/properties/{name}` triggers subscription diff
- [ ] `POST /{actor_id}/properties` triggers subscription diff for created properties
- [ ] Property hooks are executed when setting properties via HTTP (test with a hook that transforms values)

---

## Phase 2: Enhance TrustManager with Lifecycle Hooks [COMPLETED]

### Overview

Add lifecycle hook execution to `TrustManager` for trust approval and deletion.

### Changes Required

#### 1. TrustManager Enhancement

**File**: `actingweb/interface/trust_manager.py`

**Changes**:
- Accept `hooks` parameter in constructor
- Add `_execute_lifecycle_hook` helper method
- Call `trust_approved` hook in `approve_relationship()`
- Call `trust_deleted` hook in `delete_relationship()`
- Add async variants for methods that make outbound HTTP calls

Add to the `TrustManager` class:

```python
def __init__(self, core_actor: CoreActor, hooks: Optional["HookRegistry"] = None):
    self._core_actor = core_actor
    self._hooks = hooks

def _execute_lifecycle_hook(
    self, event: str, peer_id: str = "", relationship: str = "", trust_data: dict = None
) -> None:
    """Execute a lifecycle hook."""
    if not self._hooks:
        return

    try:
        from .actor_interface import ActorInterface

        actor_interface = ActorInterface(self._core_actor)
        self._hooks.execute_lifecycle_hooks(
            event,
            actor=actor_interface,
            peer_id=peer_id,
            relationship=relationship,
            trust_data=trust_data or {},
        )
        logging.debug(f"Lifecycle hook '{event}' executed for peer {peer_id}")
    except Exception as e:
        logging.error(f"Error executing lifecycle hook '{event}': {e}")

def approve_relationship(self, peer_id: str) -> bool:
    """Approve a trust relationship with lifecycle hook execution."""
    relationship = self.get_relationship(peer_id)
    if not relationship:
        return False

    result = self._core_actor.modify_trust_and_notify(
        peerid=peer_id, relationship=relationship.relationship, approved=True
    )

    if result:
        # Get updated trust data and trigger lifecycle hook
        updated_trust = self.get_relationship(peer_id)
        if updated_trust and updated_trust.approved and updated_trust.peer_approved:
            self._execute_lifecycle_hook(
                "trust_approved",
                peer_id=peer_id,
                relationship=relationship.relationship,
                trust_data=updated_trust.to_dict(),
            )

    return bool(result)

def delete_relationship(self, peer_id: str) -> bool:
    """Delete a trust relationship with lifecycle hook execution.

    Note: Associated permissions are automatically deleted by the core
    delete_reciprocal_trust method.
    """
    # Get relationship data before deletion for the hook
    relationship = self.get_relationship(peer_id)

    # Execute lifecycle hook BEFORE deletion
    if relationship:
        self._execute_lifecycle_hook(
            "trust_deleted",
            peer_id=peer_id,
            relationship=relationship.relationship,
        )

    result = self._core_actor.delete_reciprocal_trust(
        peerid=peer_id, delete_peer=True
    )
    return bool(result)

# Async variants
async def create_relationship_async(
    self,
    peer_url: str,
    relationship: str = "friend",
    secret: str = "",
    description: str = "",
) -> TrustRelationship | None:
    """Create a new trust relationship with another actor (async)."""
    if not secret:
        secret = (
            self._core_actor.config.new_token() if self._core_actor.config else ""
        )

    # Use async variant if available
    if hasattr(self._core_actor, "create_reciprocal_trust_async"):
        rel_data = await self._core_actor.create_reciprocal_trust_async(
            url=peer_url, secret=secret, desc=description, relationship=relationship
        )
    else:
        # Fall back to sync
        rel_data = self._core_actor.create_reciprocal_trust(
            url=peer_url, secret=secret, desc=description, relationship=relationship
        )

    if rel_data and isinstance(rel_data, dict):
        return TrustRelationship(rel_data)
    return None

async def approve_relationship_async(self, peer_id: str) -> bool:
    """Approve a trust relationship (async) with lifecycle hook execution."""
    relationship = self.get_relationship(peer_id)
    if not relationship:
        return False

    # Use async variant if available
    if hasattr(self._core_actor, "modify_trust_and_notify_async"):
        result = await self._core_actor.modify_trust_and_notify_async(
            peerid=peer_id, relationship=relationship.relationship, approved=True
        )
    else:
        result = self._core_actor.modify_trust_and_notify(
            peerid=peer_id, relationship=relationship.relationship, approved=True
        )

    if result:
        updated_trust = self.get_relationship(peer_id)
        if updated_trust and updated_trust.approved and updated_trust.peer_approved:
            self._execute_lifecycle_hook(
                "trust_approved",
                peer_id=peer_id,
                relationship=relationship.relationship,
                trust_data=updated_trust.to_dict(),
            )

    return bool(result)

async def delete_relationship_async(self, peer_id: str) -> bool:
    """Delete a trust relationship (async) with lifecycle hook execution."""
    relationship = self.get_relationship(peer_id)

    if relationship:
        self._execute_lifecycle_hook(
            "trust_deleted",
            peer_id=peer_id,
            relationship=relationship.relationship,
        )

    if hasattr(self._core_actor, "delete_reciprocal_trust_async"):
        result = await self._core_actor.delete_reciprocal_trust_async(
            peerid=peer_id, delete_peer=True
        )
    else:
        result = self._core_actor.delete_reciprocal_trust(
            peerid=peer_id, delete_peer=True
        )
    return bool(result)
```

### Success Criteria

#### Automated Verification:
- [ ] All existing trust manager tests pass: `poetry run pytest tests/test_trust_manager.py -v`
- [ ] Type checking passes: `poetry run pyright actingweb/interface/trust_manager.py`
- [ ] Linting passes: `poetry run ruff check actingweb/interface/trust_manager.py`
- [ ] Integration tests pass (no regression): `make test-integration`

#### HTTP API Tests (add to `tests/integration/test_trust_lifecycle.py`):
- [ ] `POST /{actor_id}/trust` with approval triggers `trust_approved` hook (verify hook was called via test hook that sets a property)
- [ ] `DELETE /{actor_id}/trust/{peer_id}` triggers `trust_deleted` hook (verify via test hook)
- [ ] Trust approval via peer notification (`POST /{actor_id}/trust/{peer_id}` with `approved=true`) triggers lifecycle hook
- [ ] Async trust operations complete without blocking (verify response time < 5s for peer communication)

---

## Phase 3: Create Authenticated Views [COMPLETED]

### Overview

Create `AuthenticatedActorView` and related classes that wrap the developer API with permission enforcement.

### Changes Required

#### 1. New File: Authenticated Views

**File**: `actingweb/interface/authenticated_views.py`

**Changes**: Create new file with `AuthenticatedActorView`, `AuthenticatedPropertyStore`, `AuthenticatedPropertyListStore`, `AuthenticatedSubscriptionManager`

```python
"""
Authenticated views for ActingWeb actors.

Provides permission-enforced access to actor resources based on trust relationships.
"""

import logging
from typing import TYPE_CHECKING, Any, Iterator, Optional

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


class AuthContext:
    """Authentication context for permission evaluation."""

    def __init__(
        self,
        peer_id: str = "",
        client_id: str = "",
        trust_relationship: Optional[dict[str, Any]] = None,
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
            logging.warning(f"Permission check error for {key}: {e}")
            # On error, allow for backward compatibility

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

        try:
            evaluator = get_permission_evaluator(self._config)
            # List properties use the same permission system as regular properties
            result = evaluator.evaluate_property_access(
                self._actor_id,
                self._auth_context.accessor_id,
                f"list:{list_name}",
                operation,
            )

            if result == PermissionResult.DENIED:
                raise PermissionError(
                    f"Access denied: {operation} on list '{list_name}' for {self._auth_context.accessor_id}"
                )
        except PermissionError:
            raise
        except Exception as e:
            logging.warning(f"Permission check error for list {list_name}: {e}")

    def __getattr__(self, name: str) -> Any:
        """Get list property with permission check."""
        if name.startswith("_"):
            return super().__getattribute__(name)

        self._check_permission(name, "read")
        return getattr(self._store, name)

    def exists(self, name: str) -> bool:
        """Check if list exists (requires read permission)."""
        try:
            self._check_permission(name, "read")
            return self._store.exists(name)
        except PermissionError:
            return False

    def create(self, name: str, **kwargs) -> Any:
        """Create a new list (requires write permission)."""
        self._check_permission(name, "write")
        return self._store.create(name, **kwargs)

    def delete(self, name: str) -> bool:
        """Delete a list (requires delete permission)."""
        self._check_permission(name, "delete")
        return self._store.delete(name)


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
            logging.warning(f"Subscription permission check error: {e}")

    def create_local_subscription(
        self, target: str, subtarget: str = "", resource: str = "", granularity: str = "high"
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
    def all_subscriptions(self):
        return self._manager.all_subscriptions

    @property
    def outbound_subscriptions(self):
        return self._manager.outbound_subscriptions

    @property
    def inbound_subscriptions(self):
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
        self._properties: Optional[AuthenticatedPropertyStore] = None
        self._property_lists: Optional[AuthenticatedPropertyListStore] = None
        self._subscriptions: Optional[AuthenticatedSubscriptionManager] = None

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
```

#### 2. Update ActorInterface

**File**: `actingweb/interface/actor_interface.py`

**Changes**: Add `as_peer()` and `as_client()` methods, wire hooks through to managers

```python
# Add imports at top
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .authenticated_views import AuthenticatedActorView, AuthContext
    from .hooks import HookRegistry

# Add to __init__:
def __init__(self, core_actor: CoreActor, service_registry=None, hooks: Optional["HookRegistry"] = None):
    self._core_actor = core_actor
    self._hooks = hooks or getattr(getattr(core_actor, "config", None), "_hooks", None)
    # ... rest of existing init ...

# Add new methods:
def as_peer(
    self, peer_id: str, trust_relationship: Optional[dict[str, Any]] = None
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
    self, client_id: str, trust_relationship: Optional[dict[str, Any]] = None
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

# Update properties property to pass hooks:
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

# Update trust property to pass hooks:
@property
def trust(self) -> TrustManager:
    """Trust relationship manager."""
    if self._trust_manager is None:
        self._trust_manager = TrustManager(self._core_actor, hooks=self._hooks)
    return self._trust_manager
```

#### 3. Update Module Exports

**File**: `actingweb/interface/__init__.py`

**Changes**: Export the new classes

```python
from .authenticated_views import (
    AuthContext,
    AuthenticatedActorView,
    AuthenticatedPropertyStore,
    AuthenticatedPropertyListStore,
    AuthenticatedSubscriptionManager,
    PermissionError,
)
```

### Success Criteria

#### Automated Verification:
- [ ] New unit tests for authenticated views pass: `poetry run pytest tests/test_authenticated_views.py -v`
- [ ] Type checking passes: `poetry run pyright actingweb/interface/authenticated_views.py`
- [ ] Linting passes: `poetry run ruff check actingweb/interface/`
- [ ] Integration tests pass (no regression): `make test-integration`

#### HTTP API Tests (add to `tests/integration/test_authenticated_views.py`):
- [ ] `PUT /{actor_id}/properties/{name}` with peer auth returns 403 when peer lacks write permission
- [ ] `GET /{actor_id}/properties/{name}` with peer auth returns 403 when peer lacks read permission
- [ ] `PUT /{actor_id}/properties/{name}` with peer auth succeeds when peer has write permission
- [ ] `GET /{actor_id}/properties` with peer auth filters properties to only those peer can read
- [ ] MCP client (`Authorization: Bearer` with MCP token) respects client trust permissions

---

## Phase 4: Fix Property List Notification Gap [COMPLETED]

### Overview

Add `register_diffs` calls to property list operations in handlers and the `ListProperty` class.

### Changes Required

#### 1. Update PropertyListItemsHandler

**File**: `actingweb/handlers/properties.py`

**Changes**: Add `register_diffs` calls to the `PropertyListItemsHandler.post()` method for add/update/delete actions

Find the `PropertyListItemsHandler` class and update the `post` method to call `register_diffs` after each operation:

```python
# After successful add operation:
myself.register_diffs(
    target="properties",
    subtarget=name,
    blob=json.dumps({"action": "add", "index": len(list_prop) - 1, "value": item_value}),
)

# After successful update operation:
myself.register_diffs(
    target="properties",
    subtarget=name,
    blob=json.dumps({"action": "update", "index": index, "value": item_value}),
)

# After successful delete operation:
myself.register_diffs(
    target="properties",
    subtarget=name,
    blob=json.dumps({"action": "delete", "index": index}),
)
```

#### 2. Update PropertyMetadataHandler

**File**: `actingweb/handlers/properties.py`

**Changes**: Add `register_diffs` call to `PropertyMetadataHandler.put()`:

```python
# After successful metadata update:
myself.register_diffs(
    target="properties",
    subtarget=name,
    blob=json.dumps({"action": "metadata", **metadata_dict}),
)
```

#### 3. Update ListProperty Class

**File**: `actingweb/property_list.py`

**Changes**: Add `register_diffs` calls to mutation methods. The `ListProperty` class needs access to the actor to call `register_diffs`.

Add to `ListProperty.__init__`:
```python
def __init__(self, ..., actor=None):
    # ... existing init ...
    self._actor = actor
```

Add helper method:
```python
def _register_diff(self, action: str, index: int = -1, value: Any = None) -> None:
    """Register a diff for subscription notifications."""
    if not self._actor:
        return

    import json
    diff_data = {"action": action}
    if index >= 0:
        diff_data["index"] = index
    if value is not None:
        diff_data["value"] = value

    try:
        self._actor.register_diffs(
            target="properties",
            subtarget=self._name,
            blob=json.dumps(diff_data),
        )
    except Exception as e:
        import logging
        logging.warning(f"Error registering list diff: {e}")
```

Update mutation methods to call `_register_diff`:

```python
def append(self, item: Any) -> None:
    # ... existing implementation ...
    self._register_diff("add", index=len(self) - 1, value=item)

def insert(self, index: int, item: Any) -> None:
    # ... existing implementation ...
    self._register_diff("add", index=index, value=item)

def __setitem__(self, index: int, value: Any) -> None:
    # ... existing implementation ...
    self._register_diff("update", index=index, value=value)

def __delitem__(self, index: int) -> None:
    # ... existing implementation ...
    self._register_diff("delete", index=index)

def pop(self, index: int = -1) -> Any:
    actual_index = index if index >= 0 else len(self) + index
    # ... existing implementation ...
    self._register_diff("delete", index=actual_index)
    return item

def clear(self) -> None:
    # ... existing implementation ...
    self._register_diff("clear")
```

#### 4. Update PropertyListStore to Pass Actor

**File**: `actingweb/property.py`

**Changes**: Update `PropertyListStore` to pass actor reference when creating `ListProperty` instances.

### Success Criteria

#### Automated Verification:
- [ ] Property list tests pass: `poetry run pytest tests/test_property_list.py -v`
- [ ] Handler tests pass: `poetry run pytest tests/ -k "property" -v`
- [ ] Type checking passes: `poetry run pyright actingweb/property_list.py`
- [ ] Integration tests pass (no regression): `make test-integration`

#### HTTP API Tests (add to `tests/integration/test_property_list_notifications.py`):
- [ ] `POST /{actor_id}/properties/{list_name}/items` with action=add triggers subscription diff with `{"action": "add", "index": N, "value": ...}`
- [ ] `POST /{actor_id}/properties/{list_name}/items` with action=update triggers subscription diff with `{"action": "update", "index": N, "value": ...}`
- [ ] `POST /{actor_id}/properties/{list_name}/items` with action=delete triggers subscription diff with `{"action": "delete", "index": N}`
- [ ] `PUT /{actor_id}/properties/{list_name}/metadata` triggers subscription diff with `{"action": "metadata", ...}`
- [ ] Verify diffs via `GET /{actor_id}/subscriptions/{subid}/diffs` after list operations

---

## Phase 5: Refactor Handlers to Use Developer API [COMPLETED]

### Overview

Refactor HTTP handlers to use the developer API with authenticated views instead of implementing business logic directly.

### Changes Required

#### 1. Update PropertiesHandler

**File**: `actingweb/handlers/properties.py`

**Changes**: Refactor `put`, `post`, `delete` methods to use authenticated views.

Example refactor for `put` method:

```python
def put(self, actor_id, name):
    """Handle PUT request for property."""
    auth_result = self.authenticate_actor(actor_id, "properties", subpath=name)
    if not auth_result.success:
        return

    myself = auth_result.actor
    check = auth_result.auth_obj

    # Create authenticated view based on auth type
    from actingweb.interface.actor_interface import ActorInterface
    actor = ActorInterface(myself, hooks=self.hooks)

    # Get accessor info from auth
    peer_id = check.acl.get("peerid", "") if hasattr(check, "acl") else ""

    if peer_id:
        # Peer access - use authenticated view
        trust_data = myself.get_trust_relationship(peerid=peer_id)
        view = actor.as_peer(peer_id, trust_data)
    else:
        # Owner access - use actor directly
        view = actor

    # Parse request body
    body = self.request.body
    if isinstance(body, bytes):
        body = body.decode("utf-8", "ignore")

    try:
        # Set property - permission checks and notifications automatic
        view.properties[name] = body
        self.response.set_status(204)
    except PermissionError as e:
        self.response.set_status(403)
        self.response.write(json.dumps({"error": str(e)}))
    except Exception as e:
        self.response.set_status(500)
        self.response.write(json.dumps({"error": str(e)}))
```

#### 2. Update TrustHandler

**File**: `actingweb/handlers/trust.py`

**Changes**: Refactor to delegate lifecycle hook execution to TrustManager instead of handling directly.

The handlers should call:
- `actor.trust.approve_relationship(peer_id)` instead of `myself.modify_trust_and_notify()` + manual hook
- `actor.trust.delete_relationship(peer_id)` instead of `myself.delete_reciprocal_trust()` + manual hook

### Success Criteria

#### Automated Verification:
- [ ] All handler tests pass: `poetry run pytest tests/ -k "handler" -v`
- [ ] Integration tests pass: `make test-integration`
- [ ] Type checking passes: `poetry run pyright actingweb/handlers/`

#### HTTP API Tests (regression suite - all existing tests must pass):
- [ ] All existing `tests/integration/test_properties.py` tests pass with identical responses
- [ ] All existing `tests/integration/test_trust.py` tests pass with identical responses
- [ ] All existing `tests/integration/test_subscriptions.py` tests pass with identical responses
- [ ] Response codes unchanged: 200/201/204 for success, 400/403/404 for errors
- [ ] Response body format unchanged for all endpoints

#### HTTP API Tests (behavioral verification):
- [ ] `PUT /{actor_id}/properties/{name}` via handler triggers same subscription diff as developer API
- [ ] `DELETE /{actor_id}/trust/{peer_id}` via handler triggers same lifecycle hook as `TrustManager.delete_relationship()`
- [ ] Verify handler refactor doesn't duplicate notifications (only one diff per operation)

---

## Phase 6: Add Async Variants [COMPLETED]

### Overview

Ensure async variants exist for all methods that make outbound HTTP calls.

### Changes Required

#### 1. Verify Existing Async Methods

**Files to check**:
- `actingweb/actor.py` - Check for async variants of peer communication methods
- `actingweb/aw_proxy.py` - Already has async methods

#### 2. Add Missing Async Variants to Actor

**File**: `actingweb/actor.py`

If not already present, add async variants for:
- `get_peer_info_async()`
- `modify_trust_and_notify_async()`
- `create_reciprocal_trust_async()`
- `delete_reciprocal_trust_async()`
- `create_remote_subscription_async()`
- `delete_remote_subscription_async()`

These should use `AwProxy` async methods internally.

#### 3. Add Async Variants to SubscriptionManager

**File**: `actingweb/interface/subscription_manager.py`

```python
async def subscribe_to_peer_async(
    self,
    peer_id: str,
    target: str,
    subtarget: str = "",
    resource: str = "",
    granularity: str = "high",
) -> str | None:
    """Subscribe to another actor's data (async)."""
    if hasattr(self._core_actor, "create_remote_subscription_async"):
        result = await self._core_actor.create_remote_subscription_async(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
        )
    else:
        result = self._core_actor.create_remote_subscription(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
        )
    return result if result and isinstance(result, str) else None

async def unsubscribe_async(self, peer_id: str, subscription_id: str) -> bool:
    """Unsubscribe from a peer's data (async)."""
    if hasattr(self._core_actor, "delete_remote_subscription_async"):
        remote_result = await self._core_actor.delete_remote_subscription_async(
            peerid=peer_id, subid=subscription_id
        )
    else:
        remote_result = self._core_actor.delete_remote_subscription(
            peerid=peer_id, subid=subscription_id
        )

    if remote_result:
        local_result = self._core_actor.delete_subscription(
            peerid=peer_id, subid=subscription_id
        )
        return bool(local_result)
    return False
```

### Success Criteria

#### Automated Verification:
- [ ] Async tests pass: `poetry run pytest tests/ -k "async" -v`
- [ ] Type checking passes: `poetry run pyright actingweb/`
- [ ] Integration tests pass (no regression): `make test-integration`

#### HTTP API Tests (add to `tests/integration/test_async_operations.py`):
- [ ] `POST /{actor_id}/trust` to peer actor completes within 5s (async peer communication)
- [ ] `POST /{actor_id}/subscriptions` to peer actor completes within 5s
- [ ] `DELETE /{actor_id}/trust/{peer_id}` with `delete_peer=true` completes within 5s
- [ ] FastAPI endpoint `/` (factory) handles concurrent requests without blocking (test with 10 parallel requests)
- [ ] Two-actor trust establishment via HTTP completes full handshake (test_app on 5555 + peer_app on 5556)

---

## Phase 7: Documentation Updates [COMPLETED]

### Overview

Update documentation to reflect the new architecture and authenticated views pattern.

### Changes Required

#### 1. Update CLAUDE.md

**File**: `CLAUDE.md`

Add section on authenticated views pattern:

```markdown
## Authenticated Views Pattern

ActingWeb provides three modes of access to actor data:

### Owner Mode (Direct Access)
```python
actor = ActorInterface.get_by_id(actor_id, config)
actor.properties["key"] = value  # Full access, no permission checks
```

### Peer Mode (Actor-to-Actor)
```python
actor = ActorInterface.get_by_id(actor_id, config)
peer_view = actor.as_peer(peer_id, trust_relationship)
peer_view.properties["key"] = value  # Permission checks enforced
```

### Client Mode (OAuth2/MCP)
```python
actor = ActorInterface.get_by_id(actor_id, config)
client_view = actor.as_client(client_id, trust_relationship)
client_view.properties["key"] = value  # Permission checks enforced
```

### Automatic Subscription Notifications

All property mutations through the developer API now automatically trigger
subscription notifications via `register_diffs()`. You no longer need to
call `actor.subscriptions.notify_subscribers()` manually after property changes.

#### 2. Create SDK Documentation

**File**: `docs/sdk/developer-api.rst`

Document:
- `ActorInterface` methods including `as_peer()`, `as_client()`
- `AuthenticatedActorView` and permission enforcement
- `PropertyStore` automatic notifications
- `TrustManager` lifecycle hooks
- Async variants

#### 3. Create Custom Framework Guide

**File**: `docs/sdk/custom-framework.rst`

Document how to integrate ActingWeb with frameworks other than Flask/FastAPI:
- Request normalization via `AWWebObj`
- Handler invocation patterns
- Response handling
- Authentication helpers

#### 4. Update API Reference

**File**: `docs/reference/interface-api.rst`

Add reference documentation for:
- `AuthContext`
- `AuthenticatedActorView`
- `AuthenticatedPropertyStore`
- `AuthenticatedPropertyListStore`
- `AuthenticatedSubscriptionManager`
- `PermissionError`

### Success Criteria

#### Automated Verification:
- [ ] Documentation builds: `cd docs && make html`
- [ ] No broken links in documentation
- [ ] Integration tests pass (final verification): `make test-integration`
- [ ] All unit tests pass: `poetry run pytest tests/ --ignore=tests/integration -v`

#### Documentation Verification (can be automated via doc tests):
- [ ] Code examples in CLAUDE.md are syntactically correct (can be verified via `python -m py_compile`)
- [ ] API reference matches actual class signatures (verify via sphinx autodoc)

---

## Testing Strategy

**Key Principle**: All verification is done via HTTP API integration tests against a running FastAPI server with local DynamoDB. This ensures we test the complete stack and catch regressions in the HTTP API contract.

### Test Environment Setup

```bash
# Start DynamoDB (keep running throughout)
docker-compose -f docker-compose.test.yml up -d

# Run all tests (unit + integration)
make test-integration

# Run only integration tests
poetry run pytest tests/integration/ -v --tb=short

# Run specific test file
poetry run pytest tests/integration/test_property_notifications.py -v
```

### Unit Tests (without DynamoDB)

Create new test files that use mocks for database operations:

1. **`tests/test_authenticated_views.py`**:
   - Test `AuthenticatedActorView` creation via `as_peer()`, `as_client()`
   - Test permission enforcement on property access (mock permission evaluator)
   - Test `PermissionError` is raised when access denied

2. **`tests/test_property_store_notifications.py`**:
   - Test `register_diffs` is called on `__setitem__` (mock actor)
   - Test `register_diffs` is called on `__delitem__`
   - Test `set_without_notification` does NOT call `register_diffs`

3. **`tests/test_trust_manager_hooks.py`**:
   - Test `trust_approved` hook fires on `approve_relationship()` (mock hooks)
   - Test `trust_deleted` hook fires on `delete_relationship()`

4. **`tests/test_property_list_notifications.py`**:
   - Test `register_diffs` is called on list mutations (mock actor)

### HTTP API Integration Tests (with DynamoDB)

These are the primary validation mechanism. Add to `tests/integration/`:

#### 1. `test_property_notifications.py` - Subscription diffs via HTTP

```python
"""Test property mutations trigger subscription notifications via HTTP API."""

def test_put_property_triggers_diff(actor_factory, http_client, trust_helper):
    """PUT /{actor_id}/properties/{name} triggers subscription diff."""
    # Create two actors
    actor1 = actor_factory.create("subscriber@example.com")
    actor2 = actor_factory.create("publisher@example.com")

    # Establish trust
    trust = trust_helper.establish(actor1, actor2, "friend")

    # Actor1 subscribes to actor2's properties
    response = http_client.post(
        f"/{actor2['id']}/subscriptions",
        json={"target": "properties", "peerid": actor1["id"]},
        auth=(actor1["id"], actor1["passphrase"])
    )
    assert response.status_code == 201
    sub_id = response.json()["subscriptionid"]

    # Actor2 modifies a property
    response = http_client.put(
        f"/{actor2['id']}/properties/status",
        json="active",
        auth=(actor2["id"], actor2["passphrase"])
    )
    assert response.status_code == 204

    # Verify diff was registered
    response = http_client.get(
        f"/{actor2['id']}/subscriptions/{actor1['id']}/{sub_id}/diffs",
        auth=(actor1["id"], actor1["passphrase"])
    )
    assert response.status_code == 200
    diffs = response.json()
    assert len(diffs) > 0
    assert diffs[0]["subtarget"] == "status"
```

#### 2. `test_trust_lifecycle.py` - Lifecycle hooks via HTTP

```python
"""Test trust lifecycle hooks fire via HTTP API."""

def test_trust_deletion_triggers_hook(actor_factory, http_client, trust_helper, hook_tracker):
    """DELETE /{actor_id}/trust/{peer_id} triggers trust_deleted hook."""
    # Create actors with hook tracking
    actor1 = actor_factory.create("user1@example.com")
    actor2 = actor_factory.create("user2@example.com")

    # Establish trust
    trust = trust_helper.establish(actor1, actor2, "friend")

    # Delete trust via HTTP
    response = http_client.delete(
        f"/{actor1['id']}/trust/{actor2['id']}",
        auth=(actor1["id"], actor1["passphrase"])
    )
    assert response.status_code == 204

    # Verify hook was called (check via property set by test hook)
    response = http_client.get(
        f"/{actor1['id']}/properties/_trust_deleted_hook_called",
        auth=(actor1["id"], actor1["passphrase"])
    )
    assert response.status_code == 200
    assert response.json() == "true"
```

#### 3. `test_authenticated_access.py` - Permission enforcement via HTTP

```python
"""Test permission enforcement via HTTP API with different auth methods."""

def test_peer_without_permission_gets_403(actor_factory, http_client, trust_helper):
    """Peer without write permission gets 403 on PUT."""
    actor1 = actor_factory.create("owner@example.com")
    actor2 = actor_factory.create("peer@example.com")

    # Establish trust with read-only relationship
    trust = trust_helper.establish(actor1, actor2, "reader")  # reader = read-only

    # Peer tries to write - should fail
    response = http_client.put(
        f"/{actor1['id']}/properties/secret",
        json="should_fail",
        auth=(actor2["id"], trust["secret"])
    )
    assert response.status_code == 403
```

#### 4. `test_property_list_notifications.py` - List operation diffs

```python
"""Test property list operations trigger subscription notifications."""

def test_list_add_triggers_diff(actor_factory, http_client, trust_helper):
    """POST /{actor_id}/properties/{list}/items triggers diff."""
    actor = actor_factory.create("user@example.com")

    # Create list property
    http_client.post(
        f"/{actor['id']}/properties/tasks",
        json={"_list": True, "items": []},
        auth=(actor["id"], actor["passphrase"])
    )

    # Add item to list
    response = http_client.post(
        f"/{actor['id']}/properties/tasks/items",
        json={"action": "add", "value": {"title": "Task 1"}},
        auth=(actor["id"], actor["passphrase"])
    )
    assert response.status_code == 201

    # Verify diff format
    # ... (verify diff contains {"action": "add", "index": 0, "value": ...})
```

#### 5. `test_async_operations.py` - Async peer communication

```python
"""Test async operations complete without blocking."""
import asyncio
import time

def test_trust_creation_completes_quickly(test_app, peer_app, http_client):
    """Trust creation to peer completes within timeout."""
    # test_app runs on 5555, peer_app on 5556

    # Create actor on each server
    actor1 = http_client.post("http://localhost:5555/", json={"creator": "a@example.com"})
    actor2 = http_client.post("http://localhost:5556/", json={"creator": "b@example.com"})

    # Measure trust creation time
    start = time.time()
    response = http_client.post(
        f"http://localhost:5555/{actor1.json()['id']}/trust",
        json={
            "url": f"http://localhost:5556/{actor2.json()['id']}",
            "relationship": "friend"
        },
        auth=(actor1.json()["id"], actor1.json()["passphrase"])
    )
    elapsed = time.time() - start

    assert response.status_code == 201
    assert elapsed < 5.0, f"Trust creation took {elapsed}s, expected < 5s"
```

### Regression Test Suite

Before and after each phase, run the full integration test suite to ensure no regressions:

```bash
# Full regression check
make test-integration

# Quick smoke test
poetry run pytest tests/integration/test_properties.py tests/integration/test_trust.py -v --tb=short
```

### Test Fixtures (in `tests/integration/conftest.py`)

The integration tests use these existing fixtures:
- `docker_services` - Starts DynamoDB via Docker Compose
- `test_app` - FastAPI server on port 5555
- `peer_app` - Second FastAPI server on port 5556 for peer tests
- `actor_factory` - Creates test actors with cleanup
- `http_client` - Configured HTTP client
- `trust_helper` - Establishes trust relationships

Add new fixtures:
- `hook_tracker` - Registers test hooks that set properties to verify hook execution

---

## Performance Considerations

1. **Hook execution overhead**: Hooks add a small overhead to every property mutation. Ensure hooks are efficient.

2. **Permission evaluation caching**: The permission evaluator should cache compiled patterns. Verify caching is working.

3. **Diff registration**: `register_diffs` makes database calls. Consider batching for bulk operations.

4. **Authenticated view creation**: Creating views is lightweight (no database calls). Views can be created per-request without concern.

---

## Migration Notes

### For Existing Applications

1. **No breaking changes**: Direct `actor.properties["key"] = value` continues to work as owner mode.

2. **New behavior**: Property mutations now automatically trigger subscription notifications. If your application was manually calling `notify_subscribers()`, you may get duplicate notifications. Remove manual calls.

3. **Hook execution**: If you have property hooks registered, they will now be executed on developer API mutations as well as HTTP mutations.

### Deprecation Warnings

Consider adding deprecation warnings for:
- Direct handler instantiation outside of integrations
- Manual `register_diffs` calls when using developer API

---

## References

- Original research: `thoughts/shared/research/2025-12-12-unified-handler-architecture.md`
- Permission evaluator: `actingweb/permission_evaluator.py`
- Hook registry: `actingweb/interface/hooks.py`
- Trust type registry: `actingweb/trust_type_registry.py`
