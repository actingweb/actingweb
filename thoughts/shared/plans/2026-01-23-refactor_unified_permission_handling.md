# Refactoring Plan: Unified Permission Handling in ActingWeb

## Overview

Add library-level permission caching infrastructure to ActingWeb:
1. Moving permission caching to library (following peer_profile/peer_capabilities pattern)
2. Adding "permission" callback type for reactive permission synchronization
3. Fixing "list:" prefix leakage in all contexts
4. Ensuring subscription creation establishes permission baseline

## Goals

1. **Library-level permission caching**: Store remote peer's granted permissions in `peer_permissions` bucket using TrustPermissions format
2. **Generic permission callbacks**: Standard callback type for permission notifications
3. **Fix list: prefix leakage**: Ensure internal implementation detail never exposed via HTTP or callbacks
4. **Automatic baseline**: Subscription creation fetches initial permission state from peer
5. **Clean architecture**: Permission changes flow through standard callback processor

---

## Implementation Status Summary

### COMPLETED

| Phase | Task | Status | Notes |
|-------|------|--------|-------|
| 1.1 | Create `peer_permissions.py` module | ✅ DONE | PeerPermissions dataclass, PeerPermissionStore, fetch functions |
| 1.2 | Add bucket constant `PEER_PERMISSIONS_BUCKET` | ✅ DONE | Added to constants.py with `_` prefix |
| 2.1 | Auto-fetch permissions in `sync_peer_async()` | ✅ DONE | Added to subscription_manager.py |
| 2.2 | Add `with_peer_permissions()` config method | ✅ DONE | Added to interface/app.py |
| 3.1 | Add `CallbackType.PERMISSION` | ✅ DONE | Added to callback_processor.py |
| 3.2 | Add permission callback handler | ✅ DONE | Added to handlers/callbacks.py |
| 3.3 | Add `apply_permission_data()` method | ✅ DONE | Added to remote_storage.py |
| - | Bucket naming convention (_prefix) | ✅ DONE | All library buckets renamed |
| - | Unit tests for peer_permissions | ✅ DONE | 45 tests in test_peer_permissions_unit.py |
| - | CHANGELOG.rst updated | ✅ DONE | Breaking changes + features documented |

### PARTIALLY COMPLETE

| Phase | Task | Status | Notes |
|-------|------|--------|-------|
| 4.1 | Fix subscription diff callbacks (list: prefix) | ⬜ TODO | `interface/property_store.py:269` uses `subtarget=f"list:{name}"` |
| 4.2 | Block GET /properties/list:* access | ✅ DONE | `handlers/properties.py:154` blocks access |
| 4.4 | Reject list: keys in Property class | ✅ DONE | `property.py:75-88` raises ValueError |
| - | Additional library tests | ⬜ TODO | test_callback_processor.py, test_remote_storage.py |

### NOT STARTED - Required for actingweb_mcp Migration

| Phase | Task | Status | Notes |
|-------|------|--------|-------|
| 5.1 | Add `notify_peer_on_change` config option | ⬜ TODO | Add to Config class and with_peer_permissions() |
| 5.2 | Auto-notify peer in TrustPermissionStore.store_permissions() | ⬜ TODO | Call _notify_peer() when configured |
| 5.3 | Add _notify_peer() method to TrustPermissionStore | ⬜ TODO | Fire-and-forget POST to /callbacks/permissions |
| 5.4 | Add async variants: store_permissions_async(), _notify_peer_async() | ⬜ TODO | Non-blocking versions |

### DOCUMENTATION NOT STARTED

| File | Task | Status | Notes |
|------|------|--------|-------|
| `docs/migration/v3.10.rst` | Add bucket naming breaking change | ⬜ TODO | Document `_` prefix migration |
| `docs/migration/v3.10.rst` | Add peer permissions caching section | ⬜ TODO | Document `with_peer_permissions()` |
| `docs/protocol/actingweb-spec.rst` | Add Permission Callback section | ⬜ TODO | New callback type for v1.4/v1.5 |
| `docs/quickstart/configuration.rst` | Add `with_peer_permissions()` | ⬜ TODO | Matches `with_peer_capabilities()` docs |
| `docs/guides/trust-relationships.rst` | Add peer permissions caching | ⬜ TODO | Matches `with_peer_capabilities()` docs |
| `docs/sdk/actor-interface.rst` | Add PeerPermissionStore usage | ⬜ TODO | Matches peer_capabilities docs |

---

## Implementation Phases

### Phase 1: Library - Add Permission Caching Infrastructure ✅ COMPLETE

#### 1.1 Create peer_permissions.py Module ✅

**File**: `actingweb/peer_permissions.py`

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
    # Uses bucket: PEER_PERMISSIONS_BUCKET = "_peer_permissions"
    # Key format: "{actor_id}:{peer_id}"
    # Singleton pattern with _instance class variable
```

**Implementation details**:
- Use `PEER_PERMISSIONS_BUCKET = "_peer_permissions"` constant in `constants.py`
- Methods: `store_permissions()`, `get_permissions()`, `delete_permissions()`
- In-memory cache with `_cache: dict[str, PeerPermissions]`
- Validation via `validate()` method
- JSON serialization via `to_dict()` and `from_dict()`

#### 1.2 Add Fetch Functions ✅

**File**: `actingweb/peer_permissions.py`

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

### Phase 2: Library - Subscription Baseline Integration ✅ COMPLETE

#### 2.1 Auto-fetch Permissions During Subscription Creation ✅

**File**: `actingweb/interface/subscription_manager.py`

In `sync_peer_async()` method, add after peer profile/capabilities fetching:

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

#### 2.2 Add Config Flag ✅

**File**: `actingweb/interface/app.py`

```python
.with_peer_permissions(enable=True)  # Enable permission caching
```

### Phase 3: Library - Permission Callback Type ✅ COMPLETE

#### 3.1 Add CallbackType.PERMISSION ✅

**File**: `actingweb/callback_processor.py`

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

#### 3.2 Add Permission Data Handler ✅

**File**: `actingweb/remote_storage.py`

```python
def apply_permission_data(self, permissions: dict[str, Any]) -> dict[str, Any]:
    """Apply permission update from peer.

    Stores what the REMOTE peer has granted US access to.
    Uses PeerPermissionStore in peer_permissions bucket.
    """
```

### Phase 4: Fix "list:" Prefix Leakage ⬜ NOT STARTED

#### 4.1 Subscription Diff Callbacks

**File**: `actingweb/actor.py` (or wherever diffs are registered)

When registering diffs for list properties, ensure the key sent in callback does NOT include "list:" prefix.

Current behavior may send: `{"list:memory_travel": {...}}`
Fixed behavior should send: `{"memory_travel": {...}, "_is_list": true}`

Review `register_diffs()` method and property change detection.

#### 4.2 Properties GET Endpoint - Prevent list: Access

**File**: `actingweb/handlers/properties.py`

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
- `actingweb/property.py` - Ensure get/set methods reject "list:" prefixed keys
- `actingweb/property_list.py` - Document "list:" as internal only

Add validation in Property class:
```python
def __getitem__(self, key: str) -> Any:
    if key.startswith("list:"):
        raise ValueError("Cannot access list properties via [] operator. Use property_lists instead.")
    # ... existing code
```

---

## Testing & Verification

### Unit Tests

**New test file**: `tests/test_peer_permissions_unit.py` ✅ DONE (45 tests)

Test cases:
- PeerPermissions dataclass creation and validation
- PeerPermissionStore store/get/delete operations
- fetch_peer_permissions_async() with mocked HTTP
- Singleton store behavior

**Modify**: `tests/test_callback_processor.py` ⬜ TODO

Add test cases:
- CallbackType.PERMISSION enum value
- Permission callbacks bypass sequencing
- Permission callbacks are idempotent

**Modify**: `tests/test_remote_storage.py` ⬜ TODO

Add test cases:
- apply_permission_data() stores in PeerPermissionStore
- Permission data format validation

### Manual Verification Steps

1. **Verify "list:" prefix is not exposed**
   ```bash
   # Should return 404
   curl "http://localhost:5000/{actor_a}/properties/list:memory_travel"

   # Should work (without prefix)
   curl "http://localhost:5000/{actor_a}/properties/memory_travel"
   ```

2. **Verify subscription baseline includes permissions**
   - Delete trust and recreate
   - Check that permissions are fetched during `sync_peer_async()`
   - Verify PeerPermissionStore populated without manual sync

---

## Critical Files Summary

**NEW** (created):
- `actingweb/peer_permissions.py` - Permission caching module (263 lines)
- `tests/test_peer_permissions_unit.py` - Unit tests (45 tests)

**MODIFIED** (completed):
- `actingweb/constants.py` - Bucket naming + PEER_PERMISSIONS_BUCKET
- `actingweb/callback_processor.py` - Add CallbackType.PERMISSION
- `actingweb/handlers/callbacks.py` - Add `permissions` callback type handling
- `actingweb/remote_storage.py` - Add apply_permission_data() method
- `actingweb/interface/subscription_manager.py` - Fetch permissions in sync_peer_async()
- `actingweb/interface/app.py` - Add with_peer_permissions() config method
- `actingweb/config.py` - Add peer_permissions_caching attribute
- `CHANGELOG.rst` - Document breaking changes + features

**TO MODIFY** (remaining code):
- `actingweb/handlers/properties.py` - Add list: prefix validation in get() method
- `actingweb/property.py` - Reject list: prefixed keys in __getitem__
- `actingweb/actor.py` - Review register_diffs() for list property handling

**TO MODIFY** (remaining documentation):
- `docs/migration/v3.10.rst` - Add bucket naming breaking change + peer permissions caching
- `docs/protocol/actingweb-spec.rst` - Add Permission Callback section
- `docs/quickstart/configuration.rst` - Add with_peer_permissions() configuration
- `docs/guides/trust-relationships.rst` - Add peer permissions caching guide
- `docs/sdk/actor-interface.rst` - Add PeerPermissionStore usage

---

## Distributed Systems Design Details

### Bucket Naming Convention

**Decision**: All library-internal buckets MUST use `_` prefix to avoid namespace collisions with user-defined buckets.

**Updated constants.py** (breaking change in v3.10):

```python
# Library-internal buckets (prefixed with "_")
TRUST_TYPES_BUCKET = "_trust_types"
TRUST_PERMISSIONS_BUCKET = "_trust_permissions"
PEER_PROFILES_BUCKET = "_peer_profiles"
PEER_CAPABILITIES_BUCKET = "_peer_capabilities"
PEER_PERMISSIONS_BUCKET = "_peer_permissions"  # NEW

# OAuth2 index buckets (also internal)
AUTH_CODE_INDEX_BUCKET = "_auth_code_index"
ACCESS_TOKEN_INDEX_BUCKET = "_access_token_index"
REFRESH_TOKEN_INDEX_BUCKET = "_refresh_token_index"
CLIENT_INDEX_BUCKET = "_client_index"
OAUTH_SESSION_BUCKET = "_oauth_sessions"
```

### Permission Callback URL Format

**Callback URL**: `/callbacks/permissions/{granting_actor_id}`

**Rationale**: Unlike subscription callbacks (`/callbacks/subscriptions/{peer_id}/{sub_id}`), permission callbacks omit subscription_id because:
1. Permissions are tied to trust relationships, not subscriptions
2. Each trust relationship has exactly one set of permissions
3. The granting actor's ID uniquely identifies the permission source

**Comparison with subscription callbacks**:

| Callback Type  | URL Pattern                                    |
|----------------|------------------------------------------------|
| Subscription   | `/callbacks/subscriptions/{peer_id}/{sub_id}`  |
| Permission     | `/callbacks/permissions/{granting_actor_id}`   |

### Permission Callback Handler ✅ IMPLEMENTED

Added to `actingweb/handlers/callbacks.py`:

```python
def post(self, actor_id, name):
    path = name.split("/")

    if path[0] == "permissions":
        # Permission callback handling
        granting_actor_id = path[1]

        # Verify trust relationship exists with granting actor
        if not check or not check.check_authorisation(
            path="callbacks",
            subpath="permissions",
            method="POST",
            peerid=granting_actor_id,
        ):
            self.response.set_status(403, "Forbidden")
            return

        # Parse permission data and store in PeerPermissionStore
        # ... (library handles storage automatically)

        # Execute permission callback hook for app-specific handling
        if self.hooks:
            hook_data = params.copy()
            hook_data["granting_actor_id"] = granting_actor_id
            self.hooks.execute_callback_hooks("permissions", actor_interface, hook_data)

        self.response.set_status(204, "No Content")
        return

    if path[0] == "subscriptions":
        # Existing subscription callback handling...
        pass
```

### Permission Wire Format

**Full callback payload**:

```json
POST /{receiving_actor_id}/callbacks/permissions/{granting_actor_id}
Content-Type: application/json
Authorization: Bearer {bearer_token}

{
  "id": "granting_actor_id",
  "target": "permissions",
  "timestamp": "2026-01-15T12:00:00.000000Z",
  "type": "permission",
  "data": {
    "properties": {
      "patterns": ["memory_*", "profile/*"],
      "operations": ["read", "write", "subscribe", "delete"],
      "excluded_patterns": ["memory_private_*"]
    },
    "methods": {
      "allowed": ["sync_*", "get_*"],
      "denied": ["delete_*"]
    },
    "actions": {
      "allowed": ["refresh", "export"],
      "denied": []
    },
    "tools": {
      "allowed": ["search", "fetch", "create_note"],
      "denied": ["delete_*"]
    },
    "resources": {
      "allowed": ["data://*", "memory://*"],
      "denied": []
    },
    "prompts": {
      "allowed": ["*"]
    }
  }
}
```

**Permission evaluation semantics**:
1. Check if explicitly denied → DENY
2. Check if explicitly allowed → ALLOW
3. Check trust type defaults → use default
4. Otherwise → DENY

**Glob pattern syntax**:
- `*` matches any characters (zero or more)
- `?` matches single character
- `[abc]` matches character class

### Diff Format: NOT Required

Permission callbacks use **full replacement** only, NOT incremental diffs.

**Rationale**:
1. Permission structures are small (<2KB) - diff overhead unjustified
2. Full replacement is naturally idempotent
3. Recovery is simple: re-fetch via `GET /permissions/{actor_id}`
4. Matches existing pattern for `peer_profile` and `peer_capabilities`

### Callback Ordering ✅ IMPLEMENTED

**Risk**: Multiple permission changes could arrive out of order.

**Mitigation**: Timestamp comparison - accept only if `fetched_at` > cached `fetched_at`:

```python
def store_permissions(self, permissions: PeerPermissions) -> bool:
    existing = self.get_permissions(permissions.actor_id, permissions.peer_id)
    if existing and existing.fetched_at and permissions.fetched_at:
        if permissions.fetched_at < existing.fetched_at:
            logger.debug("Ignoring older permission update")
            return False
    return self._store(permissions)
```

---

## Protocol Spec Updates Required ⬜ NOT STARTED

### Add to actingweb-spec.rst v1.4

Add new section "Permission Callback (OPTIONAL)" after "Resync Callback (OPTIONAL)":

1. **Callback URL pattern**: `/callbacks/permissions/{granting_actor_id}`
2. **Payload format**: Full permissions structure with `type: "permission"`
3. **Key characteristics**:
   - No sequence numbers (idempotent, full replacement)
   - `data` contains FULL current permissions, not diff
   - Receivers replace cached permissions entirely
4. **Triggering events**: Permission modify via PUT, trust type changes, explicit revocation
5. **Receiver behavior**: Store, trigger app reactions, respond 204
6. **Option tag**: `permissioncallback`

### Existing /trust/.../permissions Documentation

The spec already documents the `/trust/{relationship}/{peerid}/permissions` endpoint (GET, PUT, DELETE) adequately.

**No additional updates needed** for the REST endpoint itself.

**Add cross-reference** from Permission Callback section to the existing `/trust/.../permissions` documentation for the authoritative permission source.

---

## Remaining Work Summary

### Priority 1: Fix "list:" Prefix Leakage (Phase 4.1)

**File**: `actingweb/interface/property_store.py:267-272`

The `NotifyingListProperty._register_diff()` method currently uses the `list:` prefix in the subtarget:

```python
# CURRENT (leaks prefix)
self._actor.register_diffs(
    target="properties",
    subtarget=f"list:{self._list_name}",  # ⚠️ Leaks "list:" prefix
    ...
)

# FIXED (clean subtarget)
self._actor.register_diffs(
    target="properties",
    subtarget=self._list_name,  # Clean name - diff_info already has "list" key
    ...
)
```

**Note**: The diff blob already contains `"list": self._list_name` (line 253), so receivers can identify this as a list operation without the subtarget containing the prefix.

**Already done**:
- ✅ `handlers/properties.py:154`: Blocks `GET /properties/list:*` with 404
- ✅ `property.py:75-88`: Raises error for `list:` prefixed keys in `__getitem__` and `__setitem__`

### Priority 2: Automatic Peer Notification (Phase 5 - NEW)

Required to support actingweb_mcp migration. See: `actingweb_mcp/thoughts/shared/plans/2026-01-23-unified-permission-handling-migration.md`

**5.1 Add Config Option**

**File**: `actingweb/config.py` (after line 83)

```python
# When True, automatically notify peers when their permissions change
# Only applies when peer_permissions_caching is enabled
self.notify_peer_on_change: bool = True
```

**File**: `actingweb/interface/app.py` - Update `with_peer_permissions()`:

```python
def with_peer_permissions(
    self,
    enable: bool = True,
    auto_delete_on_revocation: bool = False,
    notify_peer_on_change: bool = True,  # NEW parameter
) -> "ActingWebApp":
```

**5.2 & 5.3 Auto-Notify Peer in TrustPermissionStore**

**File**: `actingweb/trust_permissions.py`

```python
def store_permissions(self, permissions: TrustPermissions) -> bool:
    """Store trust relationship permissions.

    If notify_peer_on_change is enabled (default), automatically sends
    a permission callback to the affected peer.
    """
    # ... existing validation and storage code ...

    if success:
        self._cache[cache_key] = permissions
        logger.info(f"Stored trust permissions: {cache_key}")

        # Auto-notify peer if configured
        if getattr(self.config, "notify_peer_on_change", True):
            self._notify_peer(permissions)

        return True
    return False

def _notify_peer(self, permissions: TrustPermissions) -> None:
    """Send permission callback to the affected peer.

    This is fire-and-forget - failures are logged but don't affect storage.
    """
    try:
        from datetime import UTC, datetime
        from .aw_proxy import AwProxy

        proxy = AwProxy(
            peer_target={
                "id": permissions.actor_id,
                "peerid": permissions.peer_id,
                "passphrase": None,
            },
            config=self.config,
        )

        if not proxy.trust:
            logger.warning(f"Cannot notify peer {permissions.peer_id}: no trust")
            return

        callback_data = {
            "id": permissions.actor_id,
            "target": "permissions",
            "type": "permission",
            "timestamp": datetime.now(UTC).isoformat(),
            "data": {
                "properties": permissions.properties,
                "methods": permissions.methods,
                "actions": permissions.actions,
                "tools": permissions.tools,
                "resources": permissions.resources,
                "prompts": permissions.prompts,
            },
        }

        # POST to peer's /callbacks/permissions/{our_actor_id}
        response = proxy.create_resource(
            path=f"callbacks/permissions/{permissions.actor_id}",
            data=callback_data,
        )

        if response and "error" not in response:
            logger.debug(f"Notified peer {permissions.peer_id} of permission change")
        else:
            logger.warning(f"Failed to notify peer {permissions.peer_id}: {response}")

    except Exception as e:
        logger.warning(f"Error notifying peer {permissions.peer_id}: {e}")
```

**5.4 Add Async Variants**

Add `store_permissions_async()` and `_notify_peer_async()` using httpx for non-blocking operations.

### Priority 3: Documentation Updates

1. **docs/migration/v3.10.rst**:
   - Add "Breaking Change: Bucket Naming Convention" section documenting `_` prefix
   - Add "Peer Permissions Caching" section documenting `with_peer_permissions()`

2. **docs/protocol/actingweb-spec.rst**:
   - Add "Permission Callback (OPTIONAL)" section
   - Update changelog for v1.4 or v1.5

3. **docs/quickstart/configuration.rst**:
   - Add `with_peer_permissions()` configuration example (matches existing `with_peer_capabilities()`)

4. **docs/guides/trust-relationships.rst**:
   - Add peer permissions caching documentation (matches existing peer_capabilities section)

5. **docs/sdk/actor-interface.rst**:
   - Add PeerPermissionStore usage examples

### Priority 3: Additional Tests

1. **tests/test_callback_processor.py**: Permission callback bypasses sequencing
2. **tests/test_remote_storage.py**: `apply_permission_data()` tests

---

## Success Criteria

- ✅ PeerPermissionStore successfully caches full TrustPermissions structure
- ✅ Permission changes flow through subscription callback system
- ⬜ "list:" prefix never exposed via HTTP or callbacks (Phase 4.1 - diff subtarget still uses prefix)
- ✅ Subscription creation automatically fetches permission baseline
- ✅ Unit tests pass (45 tests)
- ⬜ Automatic peer notification when permissions change (Phase 5 - required for actingweb_mcp)
- ⬜ Async variants for permission storage and notification (Phase 5.4)
