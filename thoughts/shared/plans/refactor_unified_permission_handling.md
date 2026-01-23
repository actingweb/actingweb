# Refactoring Plan: Unified Permission Handling in ActingWeb

## Overview

Unify permission handling between actingweb_mcp (app-level) and actingweb (library-level) by:
1. Moving permission caching from app to library (following peer_profile/peer_capabilities pattern)
2. Adding "permission" callback type to replace custom method handler
3. Fixing "list:" prefix leakage in all contexts
4. Ensuring subscription creation establishes permission baseline

## Goals

1. **Library-level permission caching**: Store remote peer's granted permissions in `peer_permissions` bucket using TrustPermissions format
2. **Generic permission callbacks**: Replace app-level `handle_memory_access_update` method with subscription callback system
3. **Fix list: prefix leakage**: Ensure internal implementation detail never exposed via HTTP or callbacks
4. **Automatic baseline**: Subscription creation fetches initial permission state from peer
5. **Clean architecture**: Permission changes flow through standard callback processor with sequencing/deduplication

## Implementation Phases

### Phase 1: Library - Add Permission Caching Infrastructure

#### 1.1 Create peer_permissions.py Module

**File**: `/Users/wedel/actingweb/actingweb/actingweb/peer_permissions.py`

Pattern: Follow `peer_profile.py` design exactly

```python
@dataclass
class PeerPermissions:
    """Cached permissions from peer actor (what peer granted us access to)."""
    actor_id: str  # Actor storing this cache
    peer_id: str   # Peer who granted permissions

    # Full TrustPermissions structure
    properties: dict[str, Any] | None = None  # {patterns: [], operations: [], excluded_patterns: []}
    methods: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None

    # Metadata
    fetched_at: str | None = None
    fetch_error: str | None = None

class PeerPermissionStore:
    """Storage for peer permission caching."""
    # Uses bucket: PEER_PERMISSIONS_BUCKET = "peer_permissions"
    # Key format: "{actor_id}:{peer_id}"
    # Singleton pattern with _instance class variable
```

**Implementation details**:
- Use `PEER_PERMISSIONS_BUCKET = "peer_permissions"` constant (add to `constants.py`)
- Methods: `store_permissions()`, `get_permissions()`, `delete_permissions()`
- In-memory cache with `_cache: dict[str, PeerPermissions]`
- Validation via `validate()` method
- JSON serialization via `to_dict()` and `from_dict()`

#### 1.2 Add Fetch Functions

**File**: `/Users/wedel/actingweb/actingweb/actingweb/peer_permissions.py`

```python
async def fetch_peer_permissions_async(
    actor_id: str,
    peer_id: str,
    config: Config,
) -> PeerPermissions:
    """Fetch permissions from peer's /permissions/{actor_id} endpoint."""
    # GET /permissions/{actor_id} on peer
    # Parse response into PeerPermissions format
    # Set fetched_at timestamp
```

Add singleton accessor:
```python
def get_peer_permission_store(config: Config) -> PeerPermissionStore:
    """Get singleton PeerPermissionStore instance."""
```

### Phase 2: Library - Subscription Baseline Integration

#### 2.1 Auto-fetch Permissions During Subscription Creation

**File**: `/Users/wedel/actingweb/actingweb/actingweb/interface/subscription_manager.py`

In `sync_peer_async()` method (around line 1204), add after peer profile/capabilities fetching:

```python
# Refresh peer permissions if configured
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
        store = get_peer_permission_store(actor_config)
        store.store_permissions(permissions)
        logger.debug(
            f"Refreshed peer permissions (async) during sync_peer for {peer_id}"
        )
    except Exception as e:
        logger.warning(
            f"Failed to refresh peer permissions during sync (async): {e}"
        )
```

#### 2.2 Add Config Flag

**File**: `/Users/wedel/actingweb/actingweb_mcp/application.py`

Add to ActingWebConfig:
```python
.with_peer_permissions(enable=True)  # NEW: Enable permission caching
```

This requires adding `with_peer_permissions()` method to ActingWebConfig in actingweb library.

### Phase 3: Library - Permission Callback Type

#### 3.1 Add CallbackType.PERMISSION

**File**: `/Users/wedel/actingweb/actingweb/actingweb/callback_processor.py`

```python
class CallbackType(Enum):
    DIFF = "diff"
    RESYNC = "resync"
    PERMISSION = "permission"  # NEW
```

**Processing strategy**:
- Permission callbacks are NOT sequenced (always processed immediately)
- CallbackProcessor doesn't store them in pending queue
- They're idempotent (safe to apply multiple times)
- Bypass sequence checking for CallbackType.PERMISSION

#### 3.2 Add Permission Data Handler

**File**: `/Users/wedel/actingweb/actingweb/actingweb/remote_storage.py`

```python
def apply_permission_data(self, permissions: dict[str, Any]) -> dict[str, Any]:
    """Apply permission update from peer.

    Stores what the REMOTE peer has granted US access to.
    Uses PeerPermissionStore in peer_permissions bucket.

    Args:
        permissions: Permission grant data {
            "properties": {"patterns": [...], "operations": [...], "excluded_patterns": [...]},
            "methods": {...},
            "actions": {...},
            "tools": {...},
            "resources": {...},
            "prompts": {...}
        }

    Returns:
        Result dict with success status
    """
    from .peer_permissions import get_peer_permission_store, PeerPermissions

    store = get_peer_permission_store(self._actor.config)

    peer_perms = PeerPermissions(
        actor_id=self._actor.id,
        peer_id=self._peer_id,
        properties=permissions.get("properties"),
        methods=permissions.get("methods"),
        actions=permissions.get("actions"),
        tools=permissions.get("tools"),
        resources=permissions.get("resources"),
        prompts=permissions.get("prompts"),
        fetched_at=datetime.now(UTC).isoformat(),
    )

    success = store.store_permissions(peer_perms)
    return {"operation": "permission_update", "success": success}
```

### Phase 4: Fix "list:" Prefix Leakage

#### 4.1 Subscription Diff Callbacks

**File**: `/Users/wedel/actingweb/actingweb/actingweb/actor.py` (or wherever diffs are registered)

When registering diffs for list properties, ensure the key sent in callback does NOT include "list:" prefix.

Current behavior may send: `{"list:memory_travel": {...}}`
Fixed behavior should send: `{"memory_travel": {...}, "_is_list": true}`

Review `register_diffs()` method and property change detection.

#### 4.2 Properties GET Endpoint - Prevent list: Access

**File**: `/Users/wedel/actingweb/actingweb/actingweb/handlers/properties.py`

In `get()` method (around line 140-150), add validation:

```python
# Reject direct access to list: prefixed properties
if name and name.startswith("list:"):
    if self.response:
        self.response.set_status(404, "Not found")
    return
```

This prevents `GET /properties/list:something` from working.

#### 4.3 Properties Listall - Already Correct

**Verification**: The `listall()` method (line 285+) already:
- Gets list names via `property_lists.list_all()` which returns clean names
- Returns `{"memory_travel": {"_list": true, "count": 5}}` without prefix
- ✅ No changes needed here

#### 4.4 Review Property Access Methods

**Files to review**:
- `/Users/wedel/actingweb/actingweb/actingweb/property.py` - Ensure get/set methods reject "list:" prefixed keys
- `/Users/wedel/actingweb/actingweb/actingweb/property_list.py` - Document "list:" as internal only

Add validation in Property class:
```python
def __getitem__(self, key: str) -> Any:
    if key.startswith("list:"):
        raise ValueError("Cannot access list properties via [] operator. Use property_lists instead.")
    # ... existing code
```

### Phase 5: App - Migrate to Callback System

#### 5.1 Remove Old Permission Infrastructure

**Files to DELETE**:
- `/Users/wedel/actingweb/actingweb_mcp/hooks/actingweb/permission_methods.py`
- `/Users/wedel/actingweb/actingweb_mcp/helpers/permission_cache.py`

**Files to MODIFY**:
- `/Users/wedel/actingweb/actingweb_mcp/helpers/permission_notification.py`
- `/Users/wedel/actingweb/actingweb_mcp/api/trust.py`
- `/Users/wedel/actingweb/actingweb_mcp/repositories/remote_attribute_store.py`

#### 5.2 Add Permission Callback Hook

**File**: `/Users/wedel/actingweb/actingweb_mcp/hooks/actingweb/callback_hooks.py`

Add new hook (similar to `on_property_change`):

```python
@app.subscription_data_hook("permissions")
async def on_permission_change(
    actor: ActorInterface,
    peer_id: str,
    target: str,
    data: dict[str, Any],
    sequence: int,
    callback_type: str,
) -> None:
    """Handle permission update callbacks from peer.

    Library has already stored permission data in PeerPermissionStore.

    This hook handles app-specific actions:
    1. Check what permissions were granted/revoked
    2. Trigger data sync for newly granted permissions
    3. Delete data for revoked permissions
    4. Send WebSocket notifications to frontend

    Args:
        actor: Actor receiving permission update
        peer_id: Peer who granted/revoked permissions
        target: "permissions" (callback target)
        data: Permission data (already applied to PeerPermissionStore by library)
        sequence: Callback sequence (not used for permissions)
        callback_type: "permission"
    """
    logger.info(f"Permission update from {peer_id} for actor {actor.id}")

    # Get updated permissions from library store
    from actingweb.peer_permissions import get_peer_permission_store
    store = get_peer_permission_store(actor.config)
    peer_perms = store.get_permissions(actor.id, peer_id)

    if not peer_perms:
        logger.warning(f"No permissions found for {peer_id} after update")
        return

    # Determine what changed by comparing with previous state
    # (Implementation specific - may need to track previous state)

    # Auto-sync for granted permissions
    if peer_perms.properties:
        patterns = peer_perms.properties.get("patterns", [])
        memory_types = [p for p in patterns if p.startswith("memory_")]

        if memory_types:
            logger.info(f"Auto-syncing {len(memory_types)} memory types from {peer_id}")
            # Trigger sync for each granted memory type
            # ... implementation ...

    # WebSocket notification to frontend
    from helpers.websocket import notify_permission_updated
    if actor.id:
        notify_permission_updated(
            actor_id=actor.id,
            peer_id=peer_id,
            granted_count=len(patterns) if peer_perms.properties else 0,
        )
```

#### 5.3 Update Permission Notification Sender

**File**: `/Users/wedel/actingweb/actingweb_mcp/helpers/permission_notification.py`

Replace method-based notification with callback-based:

**OLD** (DELETE):
```python
async def notify_peer_permission_change_async(...):
    # POST to /methods/memory_access_update
```

**NEW**:
```python
async def notify_peer_permission_change_async(
    actor: ActorInterface,
    peer_id: str,
    permissions: dict[str, Any],  # Full TrustPermissions format
) -> bool:
    """Notify peer of permission change via subscription callback.

    Args:
        actor: Actor granting/revoking permissions
        peer_id: Peer receiving notification
        permissions: Full permission structure {
            "properties": {"patterns": [...], "operations": [...], "excluded_patterns": [...]},
            "methods": {...},
            ...
        }

    Returns:
        True if notification sent successfully
    """
    from actingweb.aw_proxy import AwProxy

    proxy = AwProxy(
        peer_target={"id": actor.id, "peerid": peer_id, "passphrase": None},
        config=actor.config,
    )

    if not proxy.trust:
        logger.error(f"No trust relationship with {peer_id}")
        return False

    # Send permission callback to peer's subscription endpoint
    # Path: /callbacks/{our_actor_id}/permissions
    callback_data = {
        "sequence": 0,  # Permissions don't use sequencing
        "callback_type": "permission",
        "data": permissions,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    response = await proxy.create_resource_async(
        path=f"callbacks/{actor.id}/permissions",
        data=callback_data,
    )

    return response is not None and "error" not in response
```

#### 5.4 Update API Endpoints

**File**: `/Users/wedel/actingweb/actingweb_mcp/api/trust.py`

Update permission grant/revoke endpoints:

```python
@fastapi_app.put("/{actor_id}/api/trust/{peerid}/{relationship}/memory-access")
async def update_memory_access(...):
    # 1. Update TrustPermissions (library-level grant)
    success = set_memory_access_permission(...)

    # 2. Get full permission structure
    from actingweb.trust_permissions import get_trust_permission_store
    perm_store = get_trust_permission_store(actor.config)
    trust_perms = perm_store.get_permissions(actor.id, peerid)

    # 3. Notify peer via callback (not method)
    from helpers.permission_notification import notify_peer_permission_change_async
    await notify_peer_permission_change_async(
        actor=actor,
        peer_id=peerid,
        permissions=trust_perms.to_dict() if trust_perms else {},
    )
```

Update subscription-access endpoint to read from library cache:

```python
@fastapi_app.get("/{actor_id}/api/trust/{peerid}/{relationship}/subscription-access")
async def get_subscription_access(...):
    # OLD: get_permission_cache(actor, peerid)
    # NEW: Read from library's PeerPermissionStore
    from actingweb.peer_permissions import get_peer_permission_store

    perm_store = get_peer_permission_store(actor.config)
    peer_perms = perm_store.get_permissions(actor.id, peerid)

    if not peer_perms or not peer_perms.properties:
        return {"peer_id": peerid, "granted_memory_types": []}

    # Extract memory_* patterns from properties
    patterns = peer_perms.properties.get("patterns", [])
    memory_types = [p for p in patterns if p.startswith("memory_")]

    return {
        "peer_id": peerid,
        "granted_memory_types": memory_types,
        "fetched_at": peer_perms.fetched_at,
    }
```

#### 5.5 Remove App-Level Permission Cache

**File**: `/Users/wedel/actingweb/actingweb_mcp/repositories/remote_attribute_store.py`

Delete methods:
- `get_permissions()`
- `set_permissions()`

These are now handled by library's `PeerPermissionStore`.

### Phase 6: Configuration & Registration

#### 6.1 Register Permission Callback Hook

**File**: `/Users/wedel/actingweb/actingweb_mcp/application.py`

Ensure the new `on_permission_change` hook is registered:

```python
.with_subscription_processing(
    auto_sequence=True,
    auto_storage=True,
    auto_cleanup=True,
    gap_timeout_seconds=5.0,
    max_pending=100,
    # Permission callbacks bypass sequencing (always applied immediately)
)
```

Note: Hook registration happens automatically via `@app.subscription_data_hook("permissions")` decorator.

#### 6.2 Enable Permission Caching

**File**: `/Users/wedel/actingweb/actingweb_mcp/application.py`

Add configuration (requires library support):

```python
.with_peer_permissions(enable=True)  # Enable automatic permission caching
```

## Testing & Verification

### Unit Tests (actingweb library)

**New test file**: `/Users/wedel/actingweb/actingweb/tests/test_peer_permissions.py`

Test cases:
- PeerPermissions dataclass creation and validation
- PeerPermissionStore store/get/delete operations
- fetch_peer_permissions_async() with mocked HTTP
- Singleton store behavior

**Modify**: `/Users/wedel/actingweb/actingweb/tests/test_callback_processor.py`

Add test cases:
- CallbackType.PERMISSION enum value
- Permission callbacks bypass sequencing
- Permission callbacks are idempotent

**Modify**: `/Users/wedel/actingweb/actingweb/tests/test_remote_storage.py`

Add test cases:
- apply_permission_data() stores in PeerPermissionStore
- Permission data format validation

### Integration Tests (actingweb_mcp)

**File**: `/Users/wedel/actingweb/actingweb_mcp/tests/test_permission_callbacks.py` (NEW)

Test cases:
- End-to-end permission grant flow via callback
- Permission revoke triggers data deletion
- WebSocket notifications sent to frontend
- Auto-sync triggered on permission grant

### Manual Verification Steps

1. **Create trust relationship between two actors**
   ```bash
   # Start server
   poetry run uvicorn application:fastapi_app --port=5000 --reload

   # Use frontend to create trust (both directions)
   ```

2. **Grant memory access from Actor A to Actor B**
   ```bash
   curl -X PUT "http://localhost:5000/{actor_a}/api/trust/{actor_b}/subscriber/memory-access" \
     -H "Content-Type: application/json" \
     -d '{"memory_type": "memory_travel", "has_access": true}'
   ```

3. **Verify Actor B receives permission callback**
   - Check logs for "Permission update from {actor_a}"
   - Verify PeerPermissionStore has cached permissions
   - Check frontend receives WebSocket notification

4. **Verify Actor B can access Actor A's data**
   ```bash
   curl "http://localhost:5000/{actor_b}/api/memory/peers/{actor_a}/memory_travel/items"
   ```

5. **Verify "list:" prefix is not exposed**
   ```bash
   # Should return 404
   curl "http://localhost:5000/{actor_a}/properties/list:memory_travel"

   # Should work (without prefix)
   curl "http://localhost:5000/{actor_a}/properties/memory_travel"
   ```

6. **Verify subscription baseline includes permissions**
   - Delete trust and recreate
   - Check that permissions are fetched during `sync_peer_async()`
   - Verify PeerPermissionStore populated without manual sync

## Critical Files Summary

### Library Files (../actingweb/actingweb/)

**NEW**:
- `actingweb/peer_permissions.py` - Permission caching module (200 lines, pattern: peer_profile.py)
- `constants.py` - Add `PEER_PERMISSIONS_BUCKET = "peer_permissions"`

**MODIFY**:
- `callback_processor.py` - Add CallbackType.PERMISSION
- `remote_storage.py` - Add apply_permission_data() method
- `interface/subscription_manager.py` - Fetch permissions in sync_peer_async()
- `handlers/properties.py` - Add list: prefix validation in get() method
- `property.py` - Reject list: prefixed keys in __getitem__
- `actor.py` - Review register_diffs() for list property handling

### App Files (actingweb_mcp/)

**DELETE**:
- `hooks/actingweb/permission_methods.py` (entire file)
- `helpers/permission_cache.py` (entire file)

**MODIFY**:
- `hooks/actingweb/callback_hooks.py` - Add on_permission_change() hook
- `helpers/permission_notification.py` - Replace method with callback notification
- `api/trust.py` - Update to use PeerPermissionStore, send callback notifications
- `repositories/remote_attribute_store.py` - Remove get/set_permissions methods
- `application.py` - Add .with_peer_permissions(enable=True)

### Test Files

**NEW**:
- `../actingweb/tests/test_peer_permissions.py`
- `tests/test_permission_callbacks.py`

**MODIFY**:
- `../actingweb/tests/test_callback_processor.py`
- `../actingweb/tests/test_remote_storage.py`

## Migration Notes

**No backward compatibility** - Old `/methods/memory_access_update` is removed entirely.

**Data migration**: Existing permission caches in RemoteAttributeStore will become stale. They'll be repopulated on next:
1. Subscription sync (sync_peer_async fetches baseline)
2. Permission callback from peer (when permissions change)

No explicit migration script needed - data refetches automatically.

## Rollout Strategy

1. **Phase 1-4**: Complete library changes (peer_permissions, callbacks, list: fixes)
2. **Test library** with unit tests
3. **Phase 5-6**: Update app to use new library features
4. **Test app** with integration tests
5. **Deploy**: Both library and app must be deployed together (breaking change)

## Success Criteria

- ✅ PeerPermissionStore successfully caches full TrustPermissions structure
- ✅ Permission changes flow through subscription callback system
- ✅ "list:" prefix never exposed via HTTP or callbacks
- ✅ Subscription creation automatically fetches permission baseline
- ✅ All existing permission grant/revoke functionality works via new system
- ✅ No app-level permission caching code remains
- ✅ Unit and integration tests pass
