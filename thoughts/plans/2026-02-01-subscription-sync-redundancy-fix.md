# Subscription Sync Redundancy Fix

**Date**: 2026-02-01 (Updated: 2026-02-02)
**Status**: Phase 0 & 0.5 Complete - Critical Bugs Fixed, New Critical Bug Found (Permission Diff), Performance Optimizations Pending
**Priority**: HIGH - Correctness + Performance Impact

## Overview

This plan addresses two critical issues discovered through log analysis:

1. **Performance**: Excessive HTTP request redundancy - 7 unnecessary HTTP requests per trust + permission grant cycle
2. **Critical Bug**: Profile data (displayname, email) not being stored in RemotePeerStore despite successful baseline fetches

**Performance Impact**: Each permission grant triggers ~8 HTTP requests when only 1-2 are needed (43% overhead).

**Data Loss Impact**: Simple properties are not persisted during baseline sync, requiring redundant fetches and causing missing data in RemotePeerStore.

### Important Notes

1. **Property names are application-specific**: Throughout this document, property names like `memory_travel`, `displayname`, `email` are examples from a specific application's logs. The ActingWeb library does not define or mandate specific property names - each application defines its own domain model. List properties, simple properties, and nested properties can have any names chosen by the application developer.

2. **Auto-subscription is application behavior**: The library does not automatically create subscriptions when trust is established. In the observed logs, subscription creation was triggered by the application's `trust_fully_approved_remote` hook. Applications can choose to create zero, one, or multiple subscriptions based on their needs.

---

## What's Working vs What's Broken

### ✅ Working Correctly

- **Trust establishment** - Creates reciprocal trust relationships properly
- **Subscription creation** - POST creates subscriptions successfully
- **List property storage** - List properties ARE stored in RemotePeerStore (verified with app-specific example)
- **Permission caching** - Permissions ARE stored in PeerPermissionsStore
- **Capability caching** - Methods and actions ARE stored in PeerCapabilitiesStore
- **Permission evaluation** - Access control works correctly
- **Callbacks** - Permission callbacks trigger and execute properly

### ❌ Broken / Inefficient

- ~~**Profile data storage** - displayname/email NOT stored in RemotePeerStore~~ **✅ FIXED (2026-02-02)**
- ~~**Profile extraction failure** - Falls back to separate fetch despite data being in baseline~~ **✅ FIXED (2026-02-02)**
- **Duplicate property fetches** - Baseline fetched twice (with/without metadata) - STILL NEEDS FIX
- **Full re-sync on permission grant** - Refetches entire baseline instead of just new properties - STILL NEEDS FIX
- **No capability cache staleness check** - Capabilities refetched every sync despite being static - STILL NEEDS FIX
- **Redundant permission fetch** - Fetches permissions immediately after receiving via callback - STILL NEEDS FIX

---

## Expected Flow (Based on Spec and Plans)

### 1. Trust Establishment & Subscription Creation

Based on:
- `docs/protocol/actingweb-spec.rst` - ActingWeb protocol v1.4
- `thoughts/shared/plans/2026-01-20-auto-subscription-handling.md` - Subscription processing
- `thoughts/shared/plans/2026-01-23-refactor_unified_permission_handling.md` - Permission handling

**Important**: Auto-subscription is an **application-level decision**, not library behavior. The ActingWeb library does not automatically create subscriptions on trust establishment. In the observed flow, subscription creation was triggered by the application's `trust_fully_approved_remote` hook.

**Expected sequence (when app creates subscription):**

```
1. Trust Established
   └─ trust_fully_approved_remote hook triggered (APP LEVEL)
      └─ Application decides to subscribe to peer properties (OPTIONAL)

2. Create Subscription (IF app chooses to)
   └─ POST /{peer_id}/subscriptions/{actor_id}
      Response: {subscriptionid, target, sequence}

3. Initial Baseline Sync (sync_peer_async) - ONCE (IF subscription created)
   ├─ GET /{peer_id}/properties?metadata=true
   │  └─ Fetch ALL properties + metadata (displayname, email, created_at, etc.)
   │     └─ Store in RemotePeerStore
   │        └─ Extract peer profile (displayname, email) from baseline data
   │
   ├─ GET /{peer_id}/methods
   │  └─ Fetch peer capabilities (methods)
   │
   ├─ GET /{peer_id}/actions
   │  └─ Fetch peer capabilities (actions)
   │     └─ Cache in PeerCapabilitiesStore
   │
   └─ GET /{peer_id}/permissions/{actor_id}
      └─ Fetch what peer granted us access to
         └─ Cache in PeerPermissionsStore

Total: 1 subscription creation + 4 GET requests = 5 HTTP requests
```

**Key principles:**
- **Baseline includes profile data**: Properties with `?metadata=true` returns displayname/email
- **Extract, don't re-fetch**: Profile extracted from baseline, not fetched separately
- **One-time metadata fetch**: Profile, capabilities, permissions fetched once and cached
- **Capabilities are static**: Methods/actions don't change frequently, cache aggressively

---

### 2. Permission Grant Flow

**Expected sequence (using application-specific property as example):**

```
1. User Grants Permission (e.g., access to a list property)
   └─ PUT /{peer_id}/trust/{relationship}/{actor_id}/permissions
      └─ Update TrustPermissions with new granted patterns

2. Auto-Notify Peer (if notify_peer_on_change=true)
   └─ POST /{actor_id}/callbacks/permissions/{peer_id}
      Payload: {
        type: "permission",
        data: {
          properties: {patterns: ["displayname", "email", "some_list_property"], ...}
        }
      }

3. Permission Callback Handler (on receiving actor)
   ├─ Store permissions in PeerPermissionsStore
   ├─ Detect changes: granted=["some_list_property"], revoked=[]
   │
   └─ Auto-Sync ONLY Newly Granted Data (incremental)
      └─ GET /{peer_id}/properties/some_list_property
         └─ Fetch ONLY the newly accessible property
            └─ Store in RemotePeerStore

Total: 1 PUT + 1 POST callback + 1 GET (new property) = 3 HTTP requests
```

**Note**: In the observed logs, the application granted access to a property named `memory_travel`. This is application-specific - the pattern applies to any property name.

**Key principles:**
- **Incremental sync**: Only fetch newly granted properties, not entire baseline
- **Skip cached metadata**: Don't re-fetch profile (already cached)
- **Skip capabilities**: Methods/actions unchanged by permission grant
- **Skip permission re-fetch**: Just received via callback, already fresh

---

## Actual Observed Behavior (From Log Analysis)

### Phase 1: Initial Trust & Subscription (20:44:07 - 20:44:08)

```
20:44:07.468 | POST /69fce.../subscriptions/a1263...               ✅ Create subscription
20:44:07.686 | GET /69fce.../properties?metadata=true              ✅ Fetch baseline
20:44:07.839 |   └─ 200 OK - returns displayname, email + all properties
             |
20:44:07.936 | GET /69fce.../properties                            ❌ DUPLICATE #1
20:44:08.100 |   └─ 200 OK - fetches displayname, email AGAIN      (Profile redundancy)
             |
20:44:08.212 | GET /69fce.../methods                               ✅ Fetch capabilities
20:44:08.401 | GET /69fce.../actions                               ✅ Fetch capabilities
20:44:08.621 | GET /69fce.../permissions/a1263...                  ✅ Fetch permissions
```

**Result**: 6 requests instead of 5 (1 duplicate property fetch)

**Root cause**: Profile extraction from baseline fails → fallback to separate fetch

---

### Phase 2: Permission Grant Auto-Sync (20:44:09 - 20:44:10)

**Context**: User grants permission to access an application-specific list property via web UI.

```
User grants permission to list property via web UI
↓
20:44:09.035 | PUT /{peer_id}/api/trust/.../memory-access          ✅ Grant permission
20:44:09.047 |   └─ Auto-notify peer (async)
             |
20:44:09.193 | POST /{actor_id}/callbacks/permissions/{peer_id}    ✅ Callback received
20:44:09.193 |   └─ Store permissions in PeerPermissionsStore
20:44:09.193 |   └─ Detect: granted=["memory_travel"]
20:44:09.193 |   └─ Trigger auto-sync via sync_peer()
             |
20:44:09.197 | GET /{peer_id}/subscriptions/.../69e964a4...        ❌ REDUNDANT #1
             |   └─ Check for diffs (unnecessary - just want new property)
             |
20:44:09.375 | GET /{peer_id}/properties?metadata=true             ❌ REDUNDANT #2
20:44:09.519 |   └─ Fetch ENTIRE baseline AGAIN                    (Full baseline refetch)
             |      (Already have displayname, email, etc.)
             |
20:44:09.575 | GET /{peer_id}/properties/memory_travel             ✅ Fetch new property
20:44:09.724 |   └─ 200 OK - fetch the newly accessible list
             |
20:44:09.806 | GET /{peer_id}/properties                           ❌ DUPLICATE #2
20:44:09.959 |   └─ Fetch profile AGAIN                            (Profile redundancy)
             |
20:44:10.038 | GET /{peer_id}/methods                              ❌ WASTEFUL #1
20:44:10.223 | GET /{peer_id}/actions                              ❌ WASTEFUL #2
             |   └─ Refetch capabilities (unchanged!)              (Capabilities don't change!)
             |
             | (Skipped: GET /{peer_id}/permissions/{actor_id})   ✅ CORRECT
             |   └─ Already stored from callback                  (Would be REDUNDANT #3)
```

**Result**: 6 unnecessary requests during auto-sync
- Should be: 1 GET (only `memory_travel`)
- Actually: 7 GET requests (subscription check + full baseline + profile + capabilities + new property)

**Root causes**:
1. Auto-sync calls full `sync_peer()` instead of incremental fetch
2. Capabilities always refetched (no cache staleness check)
3. Profile extraction fails → duplicate fetch
4. Subscription diff check unnecessary when we know what changed

---

## Root Cause Analysis

### 1. Profile Extraction Timing Issue

**Location**: `actingweb/interface/subscription_manager.py:2467-2556`

**The problem**:
```python
# Line 2467: After subscription sync completes
# Try to extract profile from RemotePeerStore
profile_extracted = False
try:
    for attr in actor_config.peer_profile_attributes:
        value_data = remote_store.get_value(attr)  # ❌ Fails to find data
        if value_data is not None:
            # Extract displayname, email...
            profile_extracted = True
except Exception:
    profile_extracted = False

# Line 2541: Fallback - fetch profile separately
if not profile_extracted:
    profile = await fetch_peer_profile_async(...)  # ❌ Fetches /properties again!
    logger.debug("Fetched peer profile (async) during sync_peer for {peer_id}")
```

**Why extraction fails**:
- The baseline data (`?metadata=true`) is fetched and stored in `sync_subscription_async()`
- Returns to `sync_peer_async()` which tries to extract profile
- Extraction code tries `remote_store.get_value(attr)` but may be looking in wrong format
- Properties are stored as `{"value": "Greger Teigre Wedel", "metadata": {...}}`
- Extraction code handles this (line 2505-2508) BUT may still fail silently

**Evidence from logs**:
```
20:44:07.913 | Get trust peer resource async response: 200
               ↓ Should have displayname="Greger Teigre Wedel", email="greger@teigre.com"
20:44:07.936 | Fetching peer resource async from .../properties
               ↓ Fallback fetch triggered - extraction failed!
```

**Impact**: 1 extra HTTP request per subscription creation

---

### 2. Full Re-Sync on Permission Grant

**Location**: `actingweb/handlers/callbacks.py:219-238`

**The problem**:
```python
# Line 219: Auto-sync when new permissions are granted
if (
    permission_changes.get("granted_patterns")
    and subscription_config
    and subscription_config.enabled
    and subscription_config.auto_storage
):
    logger.info(
        f"Auto-syncing peer {granting_actor_id} after permissions granted: "
        f"{permission_changes['granted_patterns']}"
    )
    try:
        # ❌ Calls FULL sync_peer() - refetches EVERYTHING
        sync_result = actor_interface.subscriptions.sync_peer(
            granting_actor_id, config=subscription_config
        )
```

**What `sync_peer()` does**:
1. Syncs ALL subscriptions → checks for diffs → fetches full baseline if no diffs
2. Refetches profile (already cached)
3. **Always** refetches capabilities (methods + actions) - even though capabilities are independent of permissions
4. **Always** refetches permissions (would duplicate callback data, but currently skipped due to fetch_error handling)

**What it should do**:
```python
# Only fetch newly granted properties, not entire baseline
for granted_pattern in permission_changes["granted_patterns"]:
    # Fetch just this property from peer
    # e.g., GET /{peer_id}/properties/memory_travel
    # Store in RemotePeerStore
```

**Impact**: 5-6 extra HTTP requests per permission grant

---

### 3. No Capability Cache Staleness Check

**Location**: `actingweb/interface/subscription_manager.py:2565-2590`

**The problem**:
```python
# Line 2565: ALWAYS fetch capabilities during sync_peer
if (
    actor_config
    and actor_id
    and getattr(actor_config, "peer_capabilities_caching", False)
):
    try:
        # ❌ No cache staleness check - fetches every time!
        capabilities = await fetch_peer_methods_and_actions_async(
            actor_id=actor_id,
            peer_id=peer_id,
            config=actor_config,
        )
        store = get_cached_capabilities_store(actor_config)
        store.store_capabilities(capabilities)  # Overwrites cache
```

**Why capabilities don't change**:
- Methods and actions are **static features** of the peer actor
- They don't change when:
  - Permissions change ❌
  - Properties change ❌
  - Trust relationship updates ❌
- They only change when:
  - Peer deploys new code ✅ (rare)
  - Peer adds/removes features ✅ (rare)

**What it should do**:
```python
# Check cache first
cached = store.get_capabilities(actor_id, peer_id)
if cached and not is_stale(cached.fetched_at, max_age_seconds=3600):
    logger.debug(f"Using cached capabilities for {peer_id} (age: {age}s)")
    return  # Skip fetch

# Only fetch if stale or missing
capabilities = await fetch_peer_methods_and_actions_async(...)
```

**Impact**: 2 extra HTTP requests per permission grant (methods + actions)

---

### 4. Redundant Permission Fetch After Callback

**Location**: `actingweb/interface/subscription_manager.py:2592-2628`

**The problem**:
```python
# Line 2592: Fetch permissions during sync_peer
if (
    actor_config
    and actor_id
    and getattr(actor_config, "peer_permissions_caching", False)
):
    try:
        # ❌ We JUST received these via callback 100ms ago!
        permissions = await fetch_peer_permissions_async(
            actor_id=actor_id,
            peer_id=peer_id,
            config=actor_config,
        )

        # Line 2615: Only store if fetch was successful
        if not permissions.fetch_error:
            store = get_peer_permission_store(actor_config)
            store.store_permissions(permissions)  # Overwrites callback data
```

**Context**:
1. Permission callback arrives at 20:44:09.193
2. Permissions stored at line 201 in `callbacks.py`
3. Auto-sync triggered immediately
4. `sync_peer_async()` fetches permissions AGAIN at 20:44:09.xxx

**Why it's redundant**:
- Permissions were JUST received via callback (push model)
- Callback data is authoritative and fresh
- Fetch would return identical data (or stale data if eventual consistency lag)

**Current mitigation**:
- Actually, the logs show this fetch is NOT happening in Phase 2
- Likely because `fetch_peer_permissions_async()` returned an error (404 or similar)
- But the fetch is still attempted - wastes time even if it fails

**Impact**: Potential 1 extra HTTP request (currently mitigated by error handling)

---

## Priority: Fix Profile Data Bug FIRST

**CRITICAL**: Before implementing any performance optimizations, we MUST fix the profile data storage bug. This is a data loss issue that affects application functionality.

**Action**: Run the debugging steps in the "Critical Bug" section to identify why displayname/email are not being stored in RemotePeerStore.

**Timeline**: Debug and fix immediately, before proceeding to performance optimizations.

---

## Implementation Plan

### Phase 0: Debug and Fix Profile Data Bug (CRITICAL - DO FIRST)

**Goal**: Identify why simple properties (displayname, email) are not being stored in RemotePeerStore during baseline sync.

#### Step 0.1: Add Diagnostic Logging

Add logging at 4 critical points to trace data flow from fetch to storage:

**Logging Point 1: Before apply_resync_data**

**File**: `actingweb/interface/subscription_manager.py:~1723` (after baseline transformation)

```python
# After _fetch_and_transform_baseline_async returns
transformed_data = await self._fetch_and_transform_baseline_async(...)

# NEW: Log what's in transformed data
logger.info(
    f"DEBUG: Transformed data for {peer_id}: "
    f"keys={list(transformed_data.keys())}, "
    f"displayname_present={'displayname' in transformed_data}, "
    f"email_present={'email' in transformed_data}, "
    f"list_props={[k for k,v in transformed_data.items() if isinstance(v, dict) and v.get('_list')]}"
)

# Apply to store
results = remote_store.apply_resync_data(transformed_data)
```

**Logging Point 2: In apply_resync_data loop**

**File**: `actingweb/remote_storage.py:~363` (start of apply_resync_data)

```python
# After sanitization, before delete_all
data = sanitize_json_data(data, log_source=f"peer:{self._peer_id}:resync")

# NEW: Log input data structure
logger.info(f"DEBUG: apply_resync_data for {self._peer_id}: keys={list(data.keys())}")
for k, v in data.items():
    is_list = isinstance(v, dict) and v.get("_list") is True
    has_items = isinstance(v, dict) and "items" in v
    has_value = isinstance(v, dict) and "value" in v
    logger.info(
        f"  - {k}: type={type(v).__name__}, "
        f"is_list={is_list}, has_items={has_items}, has_value={has_value}"
    )

results: dict[str, Any] = {}

# Delete existing data first
self.delete_all()
```

**Logging Point 3: At simple property storage**

**File**: `actingweb/remote_storage.py:~424` (simple property storage line)

```python
elif isinstance(value, dict):
    self.set_value(key, value)
    # NEW: Log when simple properties are stored
    logger.info(f"DEBUG: Stored simple property '{key}' in remote:{self._peer_id}")
    results[key] = {"operation": "resync", "success": True}
```

**Logging Point 4: After apply_resync_data**

**File**: `actingweb/interface/subscription_manager.py:~1725` (after apply_resync_data)

```python
# After applying resync data
results = remote_store.apply_resync_data(transformed_data)

# NEW: Verify storage worked
logger.info(f"DEBUG: Checking RemotePeerStore after baseline storage:")
try:
    dn = remote_store.get_value("displayname")
    em = remote_store.get_value("email")
    logger.info(f"  displayname: {dn}")
    logger.info(f"  email: {em}")
except Exception as e:
    logger.error(f"  Error reading from store: {e}")
```

#### Step 0.2: Run Test Scenario

Execute the trust + subscription flow with logging enabled:

```bash
# Enable debug logging
export LOGLEVEL=DEBUG

# Trigger trust + subscription creation flow
# 1. Create trust between two actors
# 2. Auto-subscribe (if configured)
# 3. Grant permission to additional property

# Check logs for diagnostic output
grep "DEBUG:" logs/server.log
```

#### Step 0.3: Analyze Logs

Look for these patterns in the logs:

**If working correctly:**
```
DEBUG: Transformed data for 69fce...: keys=['displayname', 'email', 'memory_travel'], displayname_present=True, email_present=True
DEBUG: apply_resync_data for 69fce...: keys=['displayname', 'email', 'memory_travel']
  - displayname: type=dict, is_list=False, has_items=False, has_value=True
  - email: type=dict, is_list=False, has_items=False, has_value=True
  - memory_travel: type=dict, is_list=True, has_items=True, has_value=False
DEBUG: Stored simple property 'displayname' in remote:69fce...
DEBUG: Stored simple property 'email' in remote:69fce...
DEBUG: Checking RemotePeerStore after baseline storage:
  displayname: {'value': 'Greger Teigre Wedel', 'metadata': {...}}
  email: {'value': 'greger@teigre.com', 'metadata': {...}}
```

**If transformation is dropping data:**
```
DEBUG: Transformed data for 69fce...: keys=['memory_travel'], displayname_present=False, email_present=False
  ← BUG: Simple properties lost during transformation
```

**If storage loop is skipping data:**
```
DEBUG: apply_resync_data for 69fce...: keys=['displayname', 'email', 'memory_travel']
  - displayname: type=dict, is_list=False, has_items=False, has_value=True
  - email: type=dict, is_list=False, has_items=False, has_value=True
  (No "Stored simple property 'displayname'" log)
  ← BUG: Storage line not executing for simple properties
```

**If data not readable after storage:**
```
DEBUG: Stored simple property 'displayname' in remote:69fce...
DEBUG: Stored simple property 'email' in remote:69fce...
DEBUG: Checking RemotePeerStore after baseline storage:
  displayname: None
  email: None
  ← BUG: Data stored but not readable (key mismatch or format issue)
```

#### Step 0.4: Implement Fix Based on Findings

**If transformation is dropping data:**
- Review `_transform_baseline_list_properties_async` (subscription_manager.py:1250-1349)
- Ensure `result = dict(baseline_data)` at line 1272 preserves all keys
- Verify loop at line 1283 only transforms lists, doesn't remove other keys

**If storage loop is skipping data:**
- Review conditional logic in `apply_resync_data` (remote_storage.py:371-433)
- Check if `isinstance(value, dict)` at line 424 is being reached
- Add explicit handling for metadata-wrapped simple properties

**If data not readable after storage:**
- Review key format in `set_value` vs `get_value`
- Check if bucket isolation is working correctly
- Verify Attributes API is storing/retrieving correctly

#### Step 0.5: Verify Fix

Run the baseline storage integration test (see "Fix C" in "Potential Fixes" section) to ensure:
- displayname IS stored in RemotePeerStore
- email IS stored in RemotePeerStore
- List properties ARE stored in RemotePeerStore (any application-specific names)
- Data is readable via `remote_store.get_value()`

**Success criteria:**
```python
remote_store = RemotePeerStore(actor=actor_a, peer_id=peer_b_id)
assert remote_store.get_value("displayname") is not None
assert remote_store.get_value("email") is not None
assert len(remote_store.get_list("test_items")) > 0  # Any list property name
```

**Only proceed to performance optimizations after this bug is fixed.**

---

### Phase 1: Fix Permission Grant Auto-Sync (HIGH PRIORITY)

**Goal**: Reduce permission grant auto-sync from 7 requests to 1-2 requests

#### Step 1.1: Implement Incremental Property Sync

**File**: `actingweb/handlers/callbacks.py`

**Changes**:
```python
# Line 219: Replace full sync_peer() with incremental sync
if (
    permission_changes.get("granted_patterns")
    and subscription_config
    and subscription_config.enabled
    and subscription_config.auto_storage
):
    granted_patterns = permission_changes["granted_patterns"]
    logger.info(
        f"Auto-syncing peer {granting_actor_id} after permissions granted: "
        f"{granted_patterns}"
    )
    try:
        # NEW: Incremental sync - only fetch newly granted properties
        from ..remote_storage import RemotePeerStore

        remote_store = RemotePeerStore(
            actor=actor_interface,
            peer_id=granting_actor_id,
            validate_peer_id=False,
        )

        # Fetch each newly granted property pattern
        for pattern in granted_patterns:
            # For exact property names (not wildcards), fetch directly
            # Examples: "displayname", "email", "user_preferences", "task_list"
            if not has_wildcard(pattern):
                await self._fetch_and_store_property_async(
                    actor_interface=actor_interface,
                    peer_id=granting_actor_id,
                    property_name=pattern,
                    remote_store=remote_store,
                )
            else:
                # For wildcard patterns, fetch properties endpoint and filter
                # Examples: "memory_*", "profile/*", "task_*"
                # This is still better than full sync - only fetches property list
                await self._fetch_and_store_wildcard_properties_async(
                    actor_interface=actor_interface,
                    peer_id=granting_actor_id,
                    pattern=pattern,
                    remote_store=remote_store,
                )

        logger.info(
            f"Auto-sync completed for {granting_actor_id}: "
            f"{len(granted_patterns)} pattern(s) synced"
        )
    except Exception as sync_error:
        logger.error(
            f"Error during incremental sync for {granting_actor_id}: {sync_error}",
            exc_info=True,
        )
```

#### Step 1.2: Add Helper Methods

**File**: `actingweb/handlers/callbacks.py`

```python
async def _fetch_and_store_property_async(
    self,
    actor_interface: "ActorInterface",
    peer_id: str,
    property_name: str,
    remote_store: "RemotePeerStore",
) -> None:
    """
    Fetch a single property from peer and store it.

    Handles both simple properties and list properties.
    """
    from ..aw_proxy import AwProxy

    # Get proxy to peer
    proxy = AwProxy(
        peer_target={
            "id": actor_interface.actor_id,
            "peerid": peer_id,
            "passphrase": None,
        },
        config=actor_interface._core_actor.config,
    )

    if not proxy.trust:
        logger.warning(f"Cannot fetch property {property_name}: no trust with {peer_id}")
        return

    # Fetch property from peer
    try:
        response = await proxy.get_resource_async(path=f"properties/{property_name}")

        if response and "error" not in response:
            # Check if this is a list property
            if isinstance(response, dict) and "_list" in response:
                # It's a list - store list metadata and items
                remote_store.apply_list_data(property_name, response)
                logger.debug(
                    f"Stored list property {property_name} from {peer_id}: "
                    f"{response.get('_count', 0)} items"
                )
            else:
                # It's a simple property - store value
                remote_store.set_value(property_name, response)
                logger.debug(f"Stored property {property_name} from {peer_id}")
        else:
            logger.warning(
                f"Failed to fetch property {property_name} from {peer_id}: "
                f"{response.get('error') if response else 'empty response'}"
            )
    except Exception as e:
        logger.error(
            f"Error fetching property {property_name} from {peer_id}: {e}",
            exc_info=True,
        )

async def _fetch_and_store_wildcard_properties_async(
    self,
    actor_interface: "ActorInterface",
    peer_id: str,
    pattern: str,
    remote_store: "RemotePeerStore",
) -> None:
    """
    Fetch properties matching a wildcard pattern from peer.

    Example patterns:
    - "memory_*" → fetch all properties starting with "memory_"
    - "profile/*" → fetch all nested properties under "profile/"
    """
    from ..aw_proxy import AwProxy
    import fnmatch

    # Get proxy to peer
    proxy = AwProxy(
        peer_target={
            "id": actor_interface.actor_id,
            "peerid": peer_id,
            "passphrase": None,
        },
        config=actor_interface._core_actor.config,
    )

    if not proxy.trust:
        logger.warning(f"Cannot fetch wildcard properties {pattern}: no trust with {peer_id}")
        return

    # Fetch property list from peer (without metadata to get just names)
    try:
        response = await proxy.get_resource_async(path="properties")

        if not response or "error" in response:
            logger.warning(
                f"Failed to fetch property list from {peer_id}: "
                f"{response.get('error') if response else 'empty response'}"
            )
            return

        # Filter properties matching the pattern
        if isinstance(response, dict):
            matching_props = [
                prop_name
                for prop_name in response.keys()
                if fnmatch.fnmatch(prop_name, pattern)
            ]

            logger.debug(
                f"Found {len(matching_props)} properties matching pattern '{pattern}' "
                f"on peer {peer_id}"
            )

            # Fetch each matching property
            for prop_name in matching_props:
                await self._fetch_and_store_property_async(
                    actor_interface=actor_interface,
                    peer_id=peer_id,
                    property_name=prop_name,
                    remote_store=remote_store,
                )

    except Exception as e:
        logger.error(
            f"Error fetching wildcard properties {pattern} from {peer_id}: {e}",
            exc_info=True,
        )

def has_wildcard(pattern: str) -> bool:
    """Check if a pattern contains wildcard characters."""
    return "*" in pattern or "?" in pattern or "[" in pattern
```

**Benefits**:
- Eliminates 5-6 unnecessary HTTP requests
- Only fetches what's newly accessible
- Handles both exact matches and wildcards
- Much faster for single property grants (common case)

---

### Phase 2: Add Capability Cache Staleness Check (MEDIUM PRIORITY)

**Goal**: Avoid refetching capabilities when cached data is fresh

#### Step 2.1: Add Staleness Check

**File**: `actingweb/interface/subscription_manager.py`

**Changes**:
```python
# Line 2565: Add cache staleness check before fetching
if (
    actor_config
    and actor_id
    and getattr(actor_config, "peer_capabilities_caching", False)
):
    try:
        from ..peer_capabilities import get_cached_capabilities_store
        from datetime import UTC, datetime

        store = get_cached_capabilities_store(actor_config)

        # Check if we have fresh cached data
        cached = store.get_capabilities(actor_id, peer_id)
        max_age_seconds = 3600  # 1 hour default

        if cached and cached.fetched_at:
            # Parse fetched_at timestamp
            try:
                fetched_time = datetime.fromisoformat(cached.fetched_at)
                age_seconds = (datetime.now(UTC) - fetched_time).total_seconds()

                if age_seconds < max_age_seconds:
                    logger.debug(
                        f"Using cached capabilities for {peer_id} "
                        f"(age: {age_seconds:.0f}s, max: {max_age_seconds}s)"
                    )
                    # Skip fetch - cache is fresh
                    continue  # Skip to next section
                else:
                    logger.debug(
                        f"Cached capabilities for {peer_id} are stale "
                        f"(age: {age_seconds:.0f}s, max: {max_age_seconds}s) - refetching"
                    )
            except Exception as parse_error:
                logger.debug(f"Error parsing capability cache timestamp: {parse_error}")

        # Fetch capabilities (cache miss or stale)
        from ..peer_capabilities import fetch_peer_methods_and_actions_async

        capabilities = await fetch_peer_methods_and_actions_async(
            actor_id=actor_id,
            peer_id=peer_id,
            config=actor_config,
        )
        store.store_capabilities(capabilities)
        logger.debug(
            f"Refreshed peer capabilities (async) during sync_peer for {peer_id}"
        )
    except Exception as e:
        logger.warning(
            f"Failed to refresh peer capabilities during sync (async): {e}"
        )
```

#### Step 2.2: Make Max Age Configurable (Optional)

**File**: `actingweb/config.py`

```python
# Add to Config class
self.peer_capabilities_max_age_seconds: int = 3600  # 1 hour
```

**File**: `actingweb/interface/app.py`

```python
def with_peer_capabilities(
    self,
    enable: bool = True,
    max_age_seconds: int = 3600,  # NEW parameter
) -> "ActingWebApp":
    """
    Enable peer capabilities caching.

    Args:
        enable: Whether to enable capability caching
        max_age_seconds: Maximum age in seconds before refetching (default: 3600 = 1 hour)
    """
    self._config.peer_capabilities_caching = enable
    self._config.peer_capabilities_max_age_seconds = max_age_seconds
    return self
```

**Benefits**:
- Eliminates 2 HTTP requests per auto-sync when cache is fresh
- Capabilities rarely change - 1 hour cache is very conservative
- Configurable for different use cases

---

### Phase 3: Skip Permission Fetch in Callback Context (MEDIUM PRIORITY)

**Goal**: Avoid redundant permission fetch when called from permission callback

#### Step 3.1: Add Skip Flag to sync_peer_async

**File**: `actingweb/interface/subscription_manager.py`

```python
# Line 2269: Add parameter to skip permission fetch
async def sync_peer_async(
    self,
    peer_id: str,
    config: "SubscriptionProcessingConfig | None" = None,
    _skip_revocation_detection: bool = False,
    _skip_permission_fetch: bool = False,  # NEW parameter
) -> PeerSyncResult:
    """
    Async version of sync_peer.

    Sync all outbound subscriptions to a peer.

    Args:
        peer_id: ID of the peer actor
        config: Optional processing configuration
        _skip_revocation_detection: Internal parameter to skip trust revocation
            detection during initial subscription sync
        _skip_permission_fetch: Internal parameter to skip permission fetch
            when called from permission callback (already have fresh data)

    Returns:
        PeerSyncResult with aggregate sync outcome
    """
    # ... existing code ...

    # Line 2592: Add skip check
    if (
        not _skip_permission_fetch  # NEW: Skip if called from permission callback
        and actor_config
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
            # ... rest of existing code ...
```

#### Step 3.2: Update Callback Handler

**File**: `actingweb/handlers/callbacks.py`

```python
# Line 236: Pass skip flag when calling from permission callback
sync_result = actor_interface.subscriptions.sync_peer(
    granting_actor_id,
    config=subscription_config,
    _skip_permission_fetch=True,  # NEW: We just received permissions via callback
)
```

**Note**: This is only relevant if Phase 1 is NOT implemented. If Phase 1 (incremental sync) is implemented, this callback won't call `sync_peer()` at all, making this phase unnecessary.

**Benefits**:
- Eliminates 1 potential HTTP request (currently mitigated by error handling)
- Cleaner semantics - explicit about callback context
- Prevents race condition where fetch might get stale data

---

### Phase 4: Debug Profile Extraction (LOW PRIORITY)

**Goal**: Understand why profile extraction fails and fix it

#### Step 4.1: Add Detailed Logging

**File**: `actingweb/interface/subscription_manager.py`

```python
# Line 2492: Add detailed logging to profile extraction
try:
    # Get properties from remote store
    logger.debug(
        f"Attempting to extract peer profile for {peer_id} from remote store"
    )

    for attr in actor_config.peer_profile_attributes:
        value_data = remote_store.get_value(attr)

        logger.debug(
            f"  Profile attribute '{attr}': "
            f"found={value_data is not None}, "
            f"type={type(value_data).__name__ if value_data else 'None'}, "
            f"has_value_key={isinstance(value_data, dict) and 'value' in value_data if value_data else False}"
        )

        if value_data is not None:
            # Extract actual value
            if isinstance(value_data, dict) and "value" in value_data:
                actual_value = value_data["value"]
                logger.debug(f"    Extracted value from dict: {actual_value}")
            else:
                actual_value = value_data
                logger.debug(f"    Using value directly: {actual_value}")

            # Convert to string for standard profile attributes
            if attr == "displayname":
                profile.displayname = (
                    str(actual_value) if actual_value is not None else None
                )
                profile_extracted = True
                logger.debug(f"    Set displayname: {profile.displayname}")
            # ... rest of extraction logic ...

except Exception as e:
    # Enhanced error logging
    logger.warning(
        f"Profile extraction failed for {peer_id}: {e}",
        exc_info=True,  # Add full traceback
    )
    profile_extracted = False
```

#### Step 4.2: Investigate Remote Store State

Add logging to understand what's in RemotePeerStore after baseline fetch:

```python
# After baseline fetch and store (in sync_subscription_async)
logger.debug(
    f"DEBUG: RemotePeerStore state after baseline for {peer_id}:"
)
# List all keys in store
try:
    all_values = remote_store.list_values()
    logger.debug(f"  Found {len(all_values)} values in store")
    for key in all_values[:5]:  # Log first 5
        logger.debug(f"    Key: {key}")
except Exception as e:
    logger.debug(f"  Error listing values: {e}")
```

#### Step 4.3: Potential Fix Hypothesis

If extraction consistently fails, the issue might be:

1. **Timing**: Baseline stored async, extraction happens before commit?
   - **Test**: Add small delay before extraction
   - **Fix**: Ensure storage is awaited/committed before extraction

2. **Key mismatch**: Properties stored with different keys than expected?
   - **Test**: Log all keys in remote_store after baseline
   - **Fix**: Adjust extraction key format

3. **Format mismatch**: Properties not in expected `{"value": ...}` format?
   - **Test**: Log actual format of stored data
   - **Fix**: Adjust extraction logic

**Benefits**:
- Eliminates 1 HTTP request during initial subscription
- Better code reliability
- Cleaner logs (no fallback messages)

---

## Testing Strategy

### Unit Tests

**New test file**: `tests/test_subscription_sync_optimization.py`

```python
import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

class TestCapabilityCacheStaleness:
    """Test capability cache staleness checks."""

    def test_fresh_cache_skips_fetch(self):
        """Fresh cached capabilities should skip fetch."""
        # Setup: cached capabilities from 30 minutes ago
        cached = PeerCapabilities(
            actor_id="actor1",
            peer_id="peer1",
            methods=["test"],
            actions=["test"],
            fetched_at=(datetime.now(UTC) - timedelta(minutes=30)).isoformat(),
        )

        # Should skip fetch (age < 1 hour)
        pass

    def test_stale_cache_triggers_fetch(self):
        """Stale cached capabilities should trigger fetch."""
        # Setup: cached capabilities from 2 hours ago
        cached = PeerCapabilities(
            actor_id="actor1",
            peer_id="peer1",
            methods=["test"],
            actions=["test"],
            fetched_at=(datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        )

        # Should fetch (age > 1 hour)
        pass

class TestIncrementalPropertySync:
    """Test incremental property sync on permission grant."""

    async def test_single_property_grant_fetch(self):
        """Granting single property should only fetch that property."""
        # Grant "memory_travel" permission
        # Should only GET /properties/memory_travel
        # Should NOT GET /properties?metadata=true
        pass

    async def test_wildcard_pattern_grant_fetch(self):
        """Granting wildcard pattern should fetch matching properties."""
        # Grant "memory_*" permission
        # Should GET /properties (list)
        # Should GET each matching property (memory_travel, memory_food, etc.)
        pass

class TestProfileExtraction:
    """Test profile extraction from baseline data."""

    def test_extract_from_baseline_success(self):
        """Profile should be extracted from baseline without separate fetch."""
        # Baseline contains displayname, email
        # Should extract without calling fetch_peer_profile_async
        pass

    def test_extract_handles_missing_attributes(self):
        """Missing profile attributes should trigger fetch."""
        # Baseline missing displayname
        # Should call fetch_peer_profile_async as fallback
        pass
```

---

### Integration Tests

**New test file**: `tests/integration/test_subscription_sync_performance.py`

```python
import pytest
from tests.integration.test_harness import ActingWebTestHarness

class TestSubscriptionSyncPerformance:
    """Integration tests for subscription sync performance."""

    @pytest.mark.asyncio
    async def test_initial_subscription_request_count(self):
        """Initial subscription should make minimal HTTP requests."""
        harness = ActingWebTestHarness()

        # Create two actors
        actor_a = await harness.create_actor()
        actor_b = await harness.create_actor()

        # Establish trust with auto-subscription
        with harness.count_http_requests() as counter:
            await harness.create_trust(actor_a, actor_b, auto_subscribe=True)

        # Should be: 1 POST (subscription) + 4 GET (baseline, methods, actions, permissions)
        assert counter.total <= 5, f"Expected ≤5 requests, got {counter.total}"
        assert counter.get_count("/properties") == 1, "Should only fetch properties once"

    @pytest.mark.asyncio
    async def test_permission_grant_request_count(self):
        """Permission grant should only fetch newly granted properties."""
        harness = ActingWebTestHarness()

        # Setup: actors with subscription
        actor_a = await harness.create_actor()
        actor_b = await harness.create_actor()
        await harness.create_trust(actor_a, actor_b, auto_subscribe=True)

        # Grant permission for single property
        with harness.count_http_requests() as counter:
            await harness.grant_permission(
                actor=actor_b,
                peer=actor_a,
                patterns=["memory_travel"],
            )

        # Should be: 1 PUT (grant) + 1 POST (callback) + 1 GET (new property)
        assert counter.total <= 3, f"Expected ≤3 requests, got {counter.total}"
        assert counter.get_count("/methods") == 0, "Should not refetch capabilities"
        assert counter.get_count("/actions") == 0, "Should not refetch capabilities"

    @pytest.mark.asyncio
    async def test_capability_cache_effectiveness(self):
        """Capabilities should be cached and not refetched on sync."""
        harness = ActingWebTestHarness()

        # Setup: actors with subscription
        actor_a = await harness.create_actor()
        actor_b = await harness.create_actor()
        await harness.create_trust(actor_a, actor_b, auto_subscribe=True)

        # First sync - should fetch capabilities
        with harness.count_http_requests() as counter1:
            await actor_a.subscriptions.sync_peer(actor_b.id)

        # Second sync within cache lifetime - should NOT refetch
        with harness.count_http_requests() as counter2:
            await actor_a.subscriptions.sync_peer(actor_b.id)

        # First sync fetches, second sync uses cache
        assert counter1.get_count("/methods") >= 1
        assert counter2.get_count("/methods") == 0, "Should use cached capabilities"
```

---

### Manual Verification

1. **Enable debug logging**:
   ```python
   configure_actingweb_logging(logging.DEBUG)
   ```

2. **Monitor HTTP requests** during:
   - Initial trust + subscription creation
   - Permission grant with auto-sync

3. **Expected outcomes**:
   ```
   Initial subscription: ≤5 HTTP requests
   Permission grant: ≤3 HTTP requests (vs current ~8)
   ```

4. **Verify logs show**:
   - "Using cached capabilities" messages
   - "Incremental sync" messages (not "fetching baseline")
   - No "Fetched peer profile (async)" after baseline sync

---

## Rollout Plan

### Phase 1: Implement Incremental Sync (Week 1)

**Priority**: HIGH - Biggest impact

**Tasks**:
1. Implement `_fetch_and_store_property_async()` helper
2. Implement `_fetch_and_store_wildcard_properties_async()` helper
3. Update permission callback handler to use incremental sync
4. Add unit tests for incremental sync
5. Add integration tests for request counting

**Success criteria**:
- Permission grant triggers ≤3 HTTP requests (vs current ~8)
- All existing tests pass
- New tests pass

---

### Phase 2: Add Capability Caching (Week 1-2)

**Priority**: MEDIUM - Good optimization

**Tasks**:
1. Add staleness check to capability fetch
2. Add configuration for max_age_seconds
3. Add unit tests for cache staleness
4. Add integration tests for cache effectiveness

**Success criteria**:
- Capabilities refetched only when stale (>1 hour by default)
- Cache hit logs visible
- All tests pass

---

### Phase 3: Debug Profile Extraction (Week 2)

**Priority**: LOW - Minor improvement

**Tasks**:
1. Add detailed logging to profile extraction
2. Run tests with logging enabled
3. Identify root cause of extraction failures
4. Implement fix based on findings
5. Verify no fallback fetches occur

**Success criteria**:
- Profile extracted from baseline 100% of time
- No "Fetched peer profile (async)" logs after baseline sync
- 1 fewer HTTP request during initial subscription

---

## Metrics & Success Criteria

### Performance Metrics

**Before optimization**:
- Initial subscription: 6 HTTP requests (1 duplicate)
- Permission grant: 8 HTTP requests (6 redundant)
- **Total per cycle**: 14 HTTP requests

**After optimization**:
- Initial subscription: 5 HTTP requests (0 duplicates)
- Permission grant: 3 HTTP requests (0 redundant)
- **Total per cycle**: 8 HTTP requests

**Improvement**: 43% reduction in HTTP requests

---

### Quality Metrics

**Code quality**:
- ✅ All existing tests pass
- ✅ New tests added for each optimization
- ✅ Pyright passes with 0 errors
- ✅ Ruff passes with 0 warnings

**Documentation**:
- ✅ Update `docs/guides/subscriptions.rst` with optimization notes
- ✅ Update CHANGELOG.rst with performance improvements
- ✅ Add comments explaining cache staleness checks

---

## Risks & Mitigations

### Risk 1: Breaking Existing Behavior

**Mitigation**:
- Comprehensive test coverage before changes
- Make changes additive (incremental sync is NEW path)
- Keep existing `sync_peer()` unchanged as fallback
- Feature flag for incremental sync if needed

### Risk 2: Cache Staleness Issues

**Mitigation**:
- Conservative 1-hour default for capabilities
- Make max_age configurable
- Force refresh option for testing
- Monitor cache hit/miss rates

### Risk 3: Wildcard Pattern Edge Cases

**Mitigation**:
- Thorough testing of wildcard patterns
- Fallback to full sync if pattern matching fails
- Clear error logging for debugging

---

## Related Documents

- `docs/protocol/actingweb-spec.rst` - ActingWeb protocol specification
- `thoughts/shared/plans/2026-01-20-auto-subscription-handling.md` - Subscription processing implementation
- `thoughts/shared/plans/2026-01-23-refactor_unified_permission_handling.md` - Permission handling refactor
- `docs/guides/subscriptions.rst` - Subscription usage guide
- `docs/guides/trust-relationships.rst` - Trust and permissions guide

---

## Critical Bug: Profile Data Not Stored in RemotePeerStore

### Observed Behavior

After the full trust + subscription + permission grant flow:
- ✅ **List property data** - STORED in RemotePeerStore (e.g., application-specific `memory_travel` list)
- ✅ **Permissions** - STORED in PeerPermissionsStore
- ✅ **Methods and actions** - STORED in PeerCapabilitiesStore
- ❌ **Simple property data** - NOT STORED in RemotePeerStore (e.g., `displayname`, `email`)

**Note**: `memory_travel` is an application-specific property list name used in this particular app. Other applications will have different property names based on their domain model.

This is a **data loss bug** - simple properties (displayname, email) are not being persisted during baseline sync, despite being fetched multiple times.

---

### Root Cause Analysis

The issue occurs in the baseline data transformation and storage pipeline:

#### Step 1: Baseline Fetch (`sync_subscription_async:1699-1724`)

```python
# Fetch baseline with metadata
transformed_data = await self._fetch_and_transform_baseline_async(
    peer_id=peer_id,
    target=sub.target,  # "properties"
    subtarget=sub.subtarget,
    resource=sub.resource,
)
```

The baseline response from `GET /properties?metadata=true` returns (example from observed logs):
```json
{
  "displayname": {
    "value": "Greger Teigre Wedel",
    "metadata": {
      "created_at": "...",
      "modified_at": "..."
    }
  },
  "email": {
    "value": "greger@teigre.com",
    "metadata": {...}
  },
  "memory_travel": {
    "_list": true,
    "_count": 0
  }
}
```

**Note**: `memory_travel` is this application's domain-specific property list. Other apps will have different property names (e.g., `tasks`, `notes`, `contacts`, `inventory_items`, etc.).

#### Step 2: Transform List Properties (`_transform_baseline_list_properties_async:1250-1349`)

```python
# Line 1272: Shallow copy includes ALL properties
result = dict(baseline_data)

# Line 1283-1347: Loop only processes list properties
for property_name, value in baseline_data.items():
    if not isinstance(value, dict):
        continue
    if not value.get("_list"):  # ← displayname/email skip here
        continue
    # ... fetch list items and transform to {"_list": True, "items": [...]}

return result  # Still contains displayname/email in original format
```

**After transformation:**
```json
{
  "displayname": {
    "value": "Greger Teigre Wedel",
    "metadata": {...}
  },  // ← UNCHANGED (simple property)
  "email": {
    "value": "greger@teigre.com",
    "metadata": {...}
  },  // ← UNCHANGED (simple property)
  "memory_travel": {
    "_list": True,
    "items": []
  }  // ← TRANSFORMED (list property - app-specific name)
}
```

#### Step 3: Store in RemotePeerStore (`apply_resync_data:347-427`)

```python
# Line 368: DELETE ALL existing data first!
self.delete_all()

# Line 371: Apply all new data
for key, value in data.items():
    # Line 374: Is it a list with _list flag and items?
    if isinstance(value, dict) and value.get("_list") is True:
        if "items" in value:
            self.set_list(key, items, metadata=metadata)  # ← memory_travel stored ✅

    # Line 406: Is it legacy "list:" format?
    elif key.startswith("list:") and isinstance(value, list):
        # ... (not our case)

    # Line 424: Is it a dict?
    elif isinstance(value, dict):
        self.set_value(key, value)  # ← Stores ENTIRE metadata wrapper ✅
        # Stores: displayname → {"value": "...", "metadata": {...}}

    else:
        self.set_value(key, value)
```

**Result in RemotePeerStore:**
```json
{
  "displayname": {"value": "Greger Teigre Wedel", "metadata": {...}},  // Wrapped!
  "email": {"value": "greger@teigre.com", "metadata": {...}},  // Wrapped!
  "some_list_property": [item1, item2, ...]  // List items (unwrapped - app-specific name)
}
```

#### Step 4: Profile Extraction Attempts Read (`sync_peer_async:2499-2538`)

```python
# Try to extract profile from remote store
for attr in actor_config.peer_profile_attributes:  # ["displayname", "email"]
    value_data = remote_store.get_value(attr)
    # Gets: {"value": "Greger Teigre Wedel", "metadata": {...}}

    if isinstance(value_data, dict) and "value" in value_data:
        actual_value = value_data["value"]  # ← Should extract "Greger..." ✅
        profile.displayname = str(actual_value)
        profile_extracted = True
```

**This SHOULD work** - the extraction code handles the wrapped format!

---

### Hypothesis: Why Profile Data Is Missing

Based on the user's observation that profile data is NOT in RemotePeerStore, one of these must be true:

#### Hypothesis A: Baseline Not Including Simple Properties (Most Likely)

The `_transform_baseline_list_properties_async` might be **discarding** simple properties instead of preserving them:

**Potential bug locations:**
1. Line 1272: `result = dict(baseline_data)` creates shallow copy
2. But maybe the result is being overwritten instead of updated?
3. Or maybe only list properties are being returned?

**Test**: Add logging at line 1349:
```python
logger.info(
    f"Transformed baseline for {peer_id}: "
    f"simple_props={[k for k,v in result.items() if not (isinstance(v, dict) and v.get('_list'))]}, "
    f"list_props={[k for k,v in result.items() if isinstance(v, dict) and v.get('_list')]}"
)
return result
```

#### Hypothesis B: Permission Filtering Removing Properties

The permission evaluation might be filtering out displayname/email from the baseline response before it reaches apply_resync_data.

**Evidence from logs:**
```
20:44:09.531 | Bulk property evaluation: 5 properties: 2 allowed, 3 denied
20:44:09.531 | Base permissions: patterns=['displayname', 'email']  // No memory_travel yet!
```

This shows only 2 allowed, which should be displayname and email. But later:

```
20:44:09.978 | Bulk property evaluation: 5 properties: 2 allowed, 3 denied
20:44:09.978 | Base permissions: patterns=['displayname', 'email', 'memory_travel']  // Now includes memory_travel
```

Still only 2 allowed despite 3 patterns! This suggests:
- The bulk evaluation is counting metadata properties (created_at, mcp_usage_count, oauth_success_at) as the 5 total
- Only displayname and email match the patterns → 2 allowed
- The other 3 are denied (created_at, mcp_usage_count, oauth_success_at)

**But where's memory_travel?** The 5 properties should be: displayname, email, memory_travel, created_at, mcp_usage_count. That's 5 total, 3 match patterns (displayname, email, memory_travel), but only 2 are being allowed.

This suggests memory_travel exists as metadata-only `{"_list": true, "_count": 0}` which might be getting filtered differently.

#### Hypothesis C: Delete-All Timing Issue

The `delete_all()` at line 368 wipes ALL peer data before applying resync. If the resync data is incomplete (missing displayname/email), they'd be deleted and not restored.

**Potential scenarios:**
1. Phase 1 stores displayname, email, (no memory_travel yet)
2. Phase 2 auto-sync calls delete_all()
3. Phase 2 resync data only includes memory_travel (permissions filtered?)
4. Result: displayname/email DELETED, memory_travel ADDED

---

### Debugging Steps (URGENT - See Phase 0 for Full Details)

The detailed diagnostic logging approach is documented in **Phase 0: Step 0.1** above. Here's a quick summary:

**Add 4 critical logging points:**

1. **Before apply_resync_data** (subscription_manager.py:~1723)
   - Log what keys are in transformed data
   - Verify displayname and email are present

2. **Inside apply_resync_data** (remote_storage.py:~363)
   - Log each property's type and structure
   - Identify which properties have `_list`, `items`, `value` flags

3. **At storage line** (remote_storage.py:~424)
   - Log when simple properties are stored
   - Confirm storage operations execute

4. **After apply_resync_data** (subscription_manager.py:~1725)
   - Attempt to read back displayname and email
   - Verify data is retrievable

**Run test scenario:**
```bash
export LOGLEVEL=DEBUG
# Trigger trust + subscription + permission grant flow
grep "DEBUG:" logs/server.log
```

**Look for these patterns:**
- ✅ displayname_present=True, email_present=True
- ✅ "Stored simple property 'displayname'" log appears
- ✅ displayname: {'value': '...', 'metadata': {...}} readable after storage

**If any of these fail, you've identified the bug location.**

See **Phase 0** for complete diagnostic code and analysis patterns.

---

### Expected Log Output (If Working Correctly)

Example from observed logs (property names are application-specific):
```
INFO: Fetched baseline for 69fce...: simple_props=['displayname', 'email'], list_props=['some_list_property']
INFO: Transformed baseline for 69fce...: simple_props=['displayname', 'email'], list_props=['some_list_property'], total_keys=3
INFO: Applying resync data for peer 69fce...: keys=['displayname', 'email', 'some_list_property'], simple_props=['displayname', 'email'], list_props=['some_list_property']
INFO: Stored simple property 'displayname' for peer 69fce...
INFO: Stored simple property 'email' for peer 69fce...
INFO: Stored list property 'some_list_property' for peer 69fce... (N items)
```

**Note**: List property names are application-specific. The pattern applies to any property name defined by the application.

---

### Potential Fixes

#### Fix A: Ensure Transformation Preserves Simple Properties

**File**: `actingweb/interface/subscription_manager.py:1272-1349`

```python
# Line 1272: Explicit shallow copy
result = {}
for key, value in baseline_data.items():
    result[key] = value

# Or ensure loop doesn't modify original keys
# Current code SHOULD work, but verify in logs
```

#### Fix B: Add Simple Property Normalization

If simple properties are stored with metadata wrapper, normalize them during storage:

**File**: `actingweb/remote_storage.py:424-426`

```python
elif isinstance(value, dict):
    # Check if this is a property with metadata wrapper
    if "value" in value and "metadata" in value:
        # Store unwrapped value for consistency with how lists are stored
        self.set_value(key, value["value"])
        logger.debug(f"Stored simple property '{key}' (unwrapped value)")
    else:
        # Store dict as-is
        self.set_value(key, value)
        logger.debug(f"Stored dict property '{key}'")
    results[key] = {"operation": "resync", "success": True}
```

This ensures displayname is stored as `"Greger Teigre Wedel"` instead of `{"value": "...", "metadata": {...}}`.

#### Fix C: Add Baseline Verification Test

**New test**: `tests/integration/test_subscription_baseline_storage.py`

```python
@pytest.mark.asyncio
async def test_baseline_stores_simple_and_list_properties():
    """Baseline sync should store both simple and list properties."""
    harness = ActingWebTestHarness()

    actor_a = await harness.create_actor()
    actor_b = await harness.create_actor()

    # Set properties on actor_b (using generic test property names)
    await actor_b.properties.set("displayname", "Test User")
    await actor_b.properties.set("email", "test@example.com")

    # Create a test list property (application-specific name)
    await actor_b.properties.append_list("test_items", "Item 1")

    # Create trust and subscription from actor_a to actor_b
    await harness.create_trust(actor_a, actor_b, auto_subscribe=True)

    # Wait for baseline sync
    await harness.wait_for_baseline_sync()

    # Verify RemotePeerStore has all data
    remote_store = RemotePeerStore(
        actor=actor_a,
        peer_id=actor_b.id,
        validate_peer_id=False,
    )

    # Check simple properties (standard library patterns)
    displayname = remote_store.get_value("displayname")
    assert displayname is not None, "displayname should be stored"
    assert displayname == "Test User", f"Expected 'Test User', got {displayname}"

    email = remote_store.get_value("email")
    assert email is not None, "email should be stored"
    assert email == "test@example.com", f"Expected 'test@example.com', got {email}"

    # Check list property (application-specific, any name is valid)
    items = remote_store.get_list("test_items")
    assert items is not None, "List property should be stored"
    assert len(items) == 1, f"Expected 1 item, got {len(items)}"
    assert items[0] == "Item 1", f"Expected 'Item 1', got {items[0]}"
```

---

## Status Updates

**2026-02-01**: Initial analysis complete, plan documented

**2026-02-01 (URGENT)**: Critical bug identified - profile data not stored in RemotePeerStore despite successful baseline fetch. Added debugging steps and potential fixes. This bug must be resolved before implementing performance optimizations.

**2026-02-01 (CLARIFICATIONS)**:
- Methods and actions data ARE correctly stored (user confirmed)
- Auto-subscription is application-level behavior, not library default
- Focus: (1) Fix profile data bug FIRST, (2) Then optimize performance

**2026-02-02 (DIAGNOSTIC APPROACH ADDED)**:
- Enhanced Phase 0 with detailed diagnostic logging instructions
- Added 4 specific logging points to trace data flow from fetch to storage
- Documented expected vs problematic log patterns for each scenario
- Provided clear analysis steps to identify bug location
- Ready to implement diagnostic logging and run test scenario

**2026-02-02 (PHASE 0 COMPLETED - BUGS IDENTIFIED AND FIXED)**:

### Root Cause Analysis Complete

Identified and fixed TWO critical bugs blocking profile extraction:

#### Bug 1: Double-Wrapping of Properties ✅ FIXED
**Location**: `actingweb/remote_storage.py:435-442`

**Root Cause**: Properties fetched with `?metadata=true` return format `{"value": {...}, "_list": False}` (API metadata wrapper). This wrapper was stored directly, causing double-wrapping:
- Properties stored internally: `{"value": "Test User B"}`
- API returns: `{"value": {"value": "Test User B"}, "_list": False}`
- Stored as-is → double-wrapped: `{"value": {"value": "Test User B"}, "_list": False}`
- Reading back: `get_value("displayname")` returns `{"value": {"value": "Test User B"}, "_list": False}`

**Impact**: Profile extraction code expected `{"value": "Test User B"}` but got nested structure, breaking extraction.

**Fix Applied** (`remote_storage.py:435-449`):
```python
elif isinstance(value, dict):
    # Check if this is the API metadata format: {"value": ..., "_list": False}
    # The properties API returns this format with ?metadata=true
    if "_list" in value and "value" in value and value.get("_list") is False:
        # Extract the inner value (unwrap API format)
        inner_value = value["value"]
        self.set_value(key, inner_value)
        logger.info(
            f"DEBUG: Unwrapped and stored property '{key}' from API metadata format"
        )
    else:
        # Store dict as-is (not API metadata format)
        self.set_value(key, value)
    results[key] = {"operation": "resync", "success": True}
```

**Verification**: After fix, properties stored correctly:
```
displayname: {'value': 'Test User B'}  // ✓ Single wrapping (correct)
email: {'value': 'user_b@example.com'} // ✓ Single wrapping (correct)
```

#### Bug 2: Profile Extraction Never Executing ✅ FIXED
**Location**: `actingweb/interface/subscription_manager.py:1566-1587`

**Root Cause**: `sync_peer()` unconditionally called `fetch_peer_profile()` after syncing subscriptions, bypassing the profile extraction code that reads from RemotePeerStore. The extraction logic existed at lines 2539-2578 but was **only in the async version** (`sync_peer_async`), not in the synchronous version.

**Impact**:
- Profile always fetched from peer over network (redundant)
- Extraction from RemotePeerStore never attempted
- Diagnostic logs from extraction code never appeared

**Fix Applied**: Created shared helper method and updated both sync versions

**New Helper Method** (`subscription_manager.py:2262-2378`):
```python
def _extract_profile_from_remote_store(
    self,
    peer_id: str,
    actor_id: str,
    actor_config: Any,
) -> tuple[Any, bool]:
    """
    Extract peer profile from already-synced properties in RemotePeerStore.

    This avoids redundant network fetches by using data already synced during
    subscription baseline sync.

    Returns:
        Tuple of (PeerProfile, success_flag)
    """
    # Check RemotePeerStore for synced properties
    # Extract displayname, email from {"value": "..."} format
    # Build PeerProfile object
    # Return (profile, True) if extraction succeeded
    # Return (profile, False) if data missing or error
```

**Updated sync_peer()** (`subscription_manager.py:1566-1620`):
```python
# Try to extract profile from synced properties
profile, profile_extracted = self._extract_profile_from_remote_store(
    peer_id=peer_id,
    actor_id=actor_id,
    actor_config=actor_config,
)

# Only fetch if we couldn't extract from synced data
if not profile_extracted:
    profile = fetch_peer_profile(...)  # Fallback
    logger.info("DEBUG: Fetched peer profile - FALLBACK used")
else:
    logger.info("DEBUG: Extracted peer profile from synced properties (avoided redundant fetch)")
```

**Updated sync_peer_async()**: Uses same `_extract_profile_from_remote_store()` helper

**Verification**: Extraction now works correctly:
- Diagnostic logs show: "Attempting profile extraction for {peer_id}"
- Properties successfully extracted from RemotePeerStore
- No redundant fetch to peer
- Profile stored in PeerProfileStore with correct values

### Tests Created and Passing ✅

**Test 1**: `tests/integration/test_peer_profile_extraction.py`
- Creates actors with properties
- Establishes trust and subscription
- Syncs peer (triggers profile extraction)
- Verifies RemotePeerStore has properties with correct format
- Verifies PeerProfileStore has extracted profile
- **Status**: ✅ PASSING

**Test 2**: `tests/integration/test_subscription_baseline_storage.py`
- Verifies baseline sync stores both simple and list properties
- Checks RemotePeerStore contains displayname, email, and list properties
- Validates profile extraction and storage
- **Status**: ✅ PASSING

### Code Quality ✅

- **Pyright**: 0 errors, 0 warnings
- **Ruff**: All checks passed
- **Refactoring**: Eliminated code duplication by creating shared `_extract_profile_from_remote_store()` helper

### Files Modified

1. **actingweb/remote_storage.py**
   - Fixed double-wrapping bug in `apply_resync_data()`
   - Unwraps API metadata format before storage

2. **actingweb/interface/subscription_manager.py**
   - Created `_extract_profile_from_remote_store()` helper method
   - Updated `sync_peer()` to use extraction before fallback
   - Updated `sync_peer_async()` to use extraction before fallback
   - Added comprehensive diagnostic logging

3. **tests/integration/test_peer_profile_extraction.py** (NEW)
   - Integration test verifying profile extraction during sync

4. **tests/integration/test_subscription_baseline_storage.py** (existing)
   - Validates baseline storage of simple and list properties

### Performance Impact

**Before fixes**:
- Profile always fetched from peer (redundant network call)
- ~7-8 HTTP requests per peer sync

**After fixes**:
- Profile extracted from already-synced RemotePeerStore data
- 1 fewer HTTP request during peer sync (profile fetch eliminated)
- Faster sync times (no network round-trip for profile)

### Next Steps

**Phase 0 and 0.5: COMPLETE** ✅
- ✅ Bug 1 (double-wrapping) identified and fixed
- ✅ Bug 2 (extraction bypass) identified and fixed
- ✅ Tests created and passing
- ✅ Code refactored to eliminate duplication
- ✅ All quality checks passing

**Ready for Phase 1** (Performance Optimizations):
- Implement incremental sync on permission grant
- Add capability cache staleness checks
- Further reduce redundant HTTP requests

**2026-02-02 (PERMISSION NORMALIZATION REMOVED - NEVER NEEDED)**:

### Re-evaluation: Permission "Normalization" Was Based on Wrong Assumption ✅ REMOVED

User correctly challenged the permission normalization changes, pointing out that:
1. The ActingWeb spec defines the wire format (callbacks, API)
2. We shouldn't change what the permission evaluator expects
3. There's no "shorthand" format in the spec

#### The Mistake

**What we did wrong**:
- Assumed there was a "shorthand" format `["a", "b"]` that needed normalization to `{"patterns": ["a", "b"]}`
- Added normalization in multiple places (`create_permission_override()`, `update_permissions()`)
- This was solving a problem that **didn't actually exist**

#### What the Spec Actually Says

**ActingWeb spec (actingweb-spec.rst, lines 2907-2928)** clearly defines the wire format:

```json
{
  "data": {
    "properties": {
      "patterns": ["memory_*", "profile/*"],
      "operations": ["read", "subscribe"],
      "excluded_patterns": ["memory_private_*"]
    },
    "methods": {
      "allowed": ["sync_*"],
      "denied": []
    }
  }
}
```

**There is NO shorthand format.** The format is always the full dict structure.

#### What the Permission Evaluator Expects

**permission_evaluator.py:489-545** expects EITHER:
1. Simple format: `{"allowed": [...], "denied": [...]}`
2. Full format: `{"patterns": [...], "operations": [...], "excluded_patterns": [...]}`

Both are dict formats, **not list shorthand**.

#### What We Actually Fixed

**Removed all normalization code** from:
1. `create_permission_override()` - Removed `_normalize_perm_field()` helper
2. `update_permissions()` - Removed list-to-dict conversion
3. `callbacks.py` - Already removed in previous iteration

#### Verification

**Tests still pass** without any normalization:
- ✅ `test_peer_profile_extraction.py` - PASSING
- ✅ `test_subscription_baseline_storage.py` - PASSING
- ✅ Pyright: 0 errors, 0 warnings
- ✅ Ruff: All checks passed

This confirms that **the code was already using the correct ActingWeb spec format**. The normalization was never needed.

#### Root Cause of Confusion

The normalization was added during this session based on an incorrect assumption about a `'list' object has no attribute 'get'` error. But:
1. We never actually reproduced this error
2. Tests pass without normalization
3. All test fixtures use the spec format

**Conclusion**: The error likely came from a different source (if it existed at all), and the normalization was solving a non-existent problem.

#### Files Modified (Reverted)

1. **actingweb/trust_permissions.py**:
   - Removed `_normalize_perm_field()` from `create_permission_override()`
   - Removed list-to-dict conversion from `update_permissions()`
   - Updated docstrings to clarify spec format required

2. **actingweb/handlers/callbacks.py**:
   - Already clean (normalization was removed)

#### Key Takeaway

**Always verify assumptions against the spec.** The ActingWeb spec is the source of truth for wire formats and data structures. When in doubt, check:
1. `docs/protocol/actingweb-spec.rst` for wire format
2. Permission evaluator code for expected internal format
3. Test fixtures for actual usage patterns

---

## Scenario Evaluation (2026-02-02)

Before implementing performance optimizations, each proposed change was evaluated against all individual operations that can happen independently. This ensures optimizations don't break correctness when steps occur in isolation rather than as part of the end-to-end flow observed in the original log analysis.

### Scenarios Considered

| # | Scenario | Description |
|---|----------|-------------|
| 1 | Trust only, no subscription | Just a trust is established — peer profile, permissions, capabilities should be fetched |
| 2 | Subscription created independently | A subscription on `/properties` or a subtarget like `/properties/my_list` — baseline should be created if auto_storage |
| 3 | Permission granted (more access) | Within an existing subscription or outside — should sync newly accessible data |
| 4 | Permission revoked | Should clear matching data from RemotePeerStore |
| 5 | Manual sync trigger | Developer API triggers `sync_peer()` — should do a complete refresh |
| 6 | Callback out of sync | Gap in sequence numbers — needs full baseline resync |

### Critical Bug Found: Permission Diff Asymmetry ("2 revoked" issue)

**Priority**: CRITICAL — Blocks Phase 1 (incremental sync), causes potential data loss

**Root Cause**: The initial permission fetch and the permission callback use different data scopes:

1. **Initial fetch** (`_refresh_peer_metadata` → `GET /permissions/{actor_id}`): The `PermissionsHandler.get()` at `handlers/permissions.py:99-143` uses an either/or approach — returns custom overrides if they exist, otherwise returns base trust-type defaults. On first subscription, no overrides exist, so it returns base defaults (e.g. `patterns=["displayname", "email"]`). This gets cached in `PeerPermissionStore`.

2. **Permission callback** (`_build_callback_data` at `trust_permissions.py:389-411`): Sends **only** the `TrustPermissions` override fields. When an override grants `["memory_travel"]`, only that is sent — base patterns are **not** included.

3. **Diff detection** (`detect_permission_changes` at `peer_permissions.py:631-674`): Compares old cached `patterns=["displayname", "email"]` against new callback `patterns=["memory_travel"]`. Set difference yields:
   - `revoked_patterns = ["displayname", "email"]` — **INCORRECT**, these were never revoked
   - `granted_patterns = ["memory_travel"]` — correct

**Impact**:
- `_delete_revoked_peer_data()` may delete displayname/email from RemotePeerStore
- The subsequent full `sync_peer()` call currently masks this by re-fetching everything (accidental safety net)
- If Phase 1 (incremental sync) is implemented without fixing this, the deleted data would NOT be restored — making the data loss permanent

**Fix options**:

**Option A (Fix the sender)**: `_build_callback_data()` should merge overrides with base trust-type permissions before sending. The callback payload would then contain the full effective permission set. This is the cleanest fix because it makes the callback self-contained.

**Option B (Fix the receiver)**: The callback handler fetches the full merged permissions from the peer via `GET /permissions/{actor_id}` instead of relying on the callback body for comparison. More network requests but no change to the wire format.

**Option C (Fix the comparison)**: `detect_permission_changes()` fetches the full effective permissions for comparison rather than using the cached value directly. Similar to Option B but contained in one function.

**Recommended**: Option A — the sender should always send the complete effective permissions, not just the overrides.

### Scenario Evaluation Results

#### Scenario 1: Trust only, no subscription

- **Current behavior**: Trust handler fires lifecycle hooks. Application decides what to do. No subscription/sync code runs unless the app initiates it.
- **Impact of proposed changes**: None. All proposed changes are in subscription/callback paths that don't run without a subscription.
- **Assessment**: Safe.

#### Scenario 2: Subscription created independently

- **Current behavior**: `subscribe_to_peer()` creates the subscription, fetches baseline, calls `_refresh_peer_metadata()` for profile/capabilities/permissions.
- **Impact of Phase 1 (incremental sync)**: Phase 1 only changes the permission callback auto-sync path in `callbacks.py:222-258`. The initial subscription path is untouched.
- **Impact of Phase 2 (capability staleness)**: The staleness check would be in `sync_peer()`, not in `_refresh_peer_metadata()`. Initial subscription always fetches fresh.
- **Assessment**: Safe.

#### Scenario 3: Permission granted (more access)

- **Current behavior**: Permission callback calls full `sync_peer()` which re-fetches everything.
- **Impact of Phase 1**: Replaces full sync with incremental fetch of only granted patterns. Correct for the common case (grant access to a specific property). **BUT**: depends on the permission diff being correct. With the "2 revoked" bug, `_delete_revoked_peer_data()` runs first (line 210-217) and may delete valid data, then incremental sync only fetches the new property — the deleted data is not restored.
- **Assessment**: Phase 1 is sound in principle but **MUST NOT be implemented until the permission diff bug is fixed**. Currently, the full `sync_peer()` accidentally compensates for the diff bug by re-fetching everything.

#### Scenario 4: Permission revoked

- **Current behavior**: `_delete_revoked_peer_data()` deletes matching lists from RemotePeerStore. Uses `fnmatch` pattern matching against stored list names.
- **Impact of proposed changes**: Phase 1 does not change the revocation path (lines 210-217). Only the "granted" path (lines 222+) is affected.
- **Concern**: The "2 revoked" bug can cause false revocations. This is a pre-existing bug that Phase 1 doesn't worsen but also doesn't fix.
- **Assessment**: No new issues, but the diff bug needs fixing.

#### Scenario 5: Manual sync trigger

- **Current behavior**: Calls `sync_peer()` directly from the developer API. Does a full sync including capabilities and permissions.
- **Impact of Phase 2 (capability staleness)**: Would skip capability re-fetch if cache is <1 hour old. This is wrong for manual sync — a developer explicitly requesting sync expects a complete refresh.
- **Assessment**: Phase 2 needs a `force_refresh` parameter. Manual/developer triggers should pass `force_refresh=True` to bypass staleness checks. Automatic syncs (from callbacks) use default `False`.

#### Scenario 6: Callback out of sync

- **Current behavior**: `sync_subscription()` detects sequence gaps, falls back to full baseline via `_fetch_and_transform_baseline()` + `apply_resync_data()`. Includes `delete_all()` + full re-store.
- **Impact of proposed changes**: None of the proposed phases touch this path.
- **Assessment**: Safe.

### The `delete_all` Safety Concern

`apply_resync_data()` at `remote_storage.py:475` calls `self.delete_all()` before re-storing. If the baseline response is incomplete (transient permission issue, network timeout, partial response), previously stored data is lost.

This is **not addressed by any proposed phase** and is a separate correctness concern. However:
- Phase 1 (incremental sync) **reduces** exposure because permission grants no longer trigger full resyncs with delete_all
- A full fix would involve compare-and-update semantics instead of wipe-and-replace, or at minimum validating that the new data is non-empty before wiping

**Recommendation**: Track as a separate future improvement. The incremental sync in Phase 1 is a partial mitigation since it reduces how often `delete_all` runs.

---

## Revised Phase Ordering

Based on the scenario evaluation, the phases are re-ordered to address correctness before performance:

```
Phase 1: Fix permission diff asymmetry (CRITICAL - correctness bug)
Phase 2: Incremental sync on permission grant (HIGH - biggest performance win)
Phase 3: Capability cache staleness with force_refresh (MEDIUM - performance)
Phase 4: Skip permission fetch in callback context (LOW - moot if Phase 2 done)
```

Phase 3 (old) about skipping permission fetch is effectively eliminated by Phase 2 since the callback handler would no longer call `sync_peer()` at all.

---

## Phase 1: Fix Permission Diff Asymmetry (CRITICAL)

**Goal**: Ensure `detect_permission_changes()` correctly identifies grants and revocations

**Root cause**: `_build_callback_data()` sends override-only permissions, but `PeerPermissionStore` caches the full effective permissions (base defaults or overrides). Set difference between these produces false revocations.

### Step 1.1: Fix `_build_callback_data()` to Send Full Effective Permissions

**File**: `actingweb/trust_permissions.py`

The `_build_callback_data()` method at line 389 currently sends the raw `TrustPermissions` fields (override-only). It should merge with base trust-type permissions so the callback contains the complete effective permission set.

**Changes needed**:

1. `_build_callback_data()` needs access to the trust type's base permissions
2. For each permission category (properties, methods, etc.), if the override field is set, send it; if not, send the base trust-type default
3. The `PermissionsHandler.get()` already implements this either/or logic (lines 99-143) — `_build_callback_data()` should follow the same pattern

```python
def _build_callback_data(self, permissions: TrustPermissions) -> dict[str, Any]:
    # Get base permissions from trust type
    base_permissions = self._get_base_permissions(
        permissions.actor_id, permissions.peer_id
    )

    # Build effective permissions: override if set, else base
    effective = {}
    for category in ["properties", "methods", "actions", "tools", "resources", "prompts"]:
        override_value = getattr(permissions, category, None)
        if override_value is not None:
            effective[category] = override_value
        elif base_permissions:
            effective[category] = base_permissions.get(category, {})
        else:
            effective[category] = {}

    return {
        "id": permissions.actor_id,
        "target": "permissions",
        "type": "permission",
        "timestamp": datetime.now(UTC).isoformat(),
        "data": effective,
    }
```

### Step 1.2: Add `_get_base_permissions()` Helper

**File**: `actingweb/trust_permissions.py`

```python
def _get_base_permissions(
    self, actor_id: str, peer_id: str
) -> dict[str, Any] | None:
    """Get base trust-type permissions for a trust relationship."""
    from .trust import Trust
    from .trust_type_registry import get_registry

    trust = Trust(actor_id=actor_id, peerid=peer_id, config=self.config)
    trust.get()

    if not trust or not trust.get("relationship"):
        return None

    registry = get_registry(self.config)
    trust_type = registry.get_type(trust["relationship"])

    if not trust_type:
        return None

    return trust_type.base_permissions
```

### Step 1.3: Update Tests

- Test that callback payload contains base patterns when override doesn't set properties
- Test that callback payload contains override patterns when override sets properties
- Test that `detect_permission_changes()` produces correct results with the fixed callback data:
  - Old: `patterns=["displayname", "email"]` (from initial fetch of base defaults)
  - New: `patterns=["displayname", "email", "memory_travel"]` (merged in callback)
  - Expected: `granted=["memory_travel"]`, `revoked=[]`

### Step 1.4: Alternative Consideration

**If the callback wire format should not change** (backward compatibility concern): Instead of fixing the sender, fix the receiver. The callback handler could re-fetch `GET /permissions/{actor_id}` from the peer before running the diff. This adds 1 request but avoids changing the callback format. However, this is less clean and adds latency.

**Recommendation**: Fix the sender (Option A). The callback format is internal between ActingWeb actors — there are no third-party consumers to worry about.

---

## Phase 2: Incremental Sync on Permission Grant (HIGH)

**Goal**: Reduce permission grant auto-sync from 7 requests to 1-2 requests

**Prerequisite**: Phase 1 (permission diff fix) MUST be complete. Without it, `_delete_revoked_peer_data()` may incorrectly delete data, and incremental sync would not restore it.

**Changes**: Same as previously documented (old Phase 1) — replace full `sync_peer()` call in `callbacks.py:236` with targeted property fetches for only the newly granted patterns.

The implementation in the original plan (Step 1.1 and Step 1.2 of old Phase 1) remains valid. Key points:

- For exact property names: fetch `GET /properties/{name}` and store in RemotePeerStore
- For wildcard patterns: fetch `GET /properties` to list, filter with `fnmatch`, then fetch each match
- No subscription check, no baseline refetch, no capabilities refetch, no permissions refetch

---

## Phase 3: Capability Cache Staleness with Force Refresh (MEDIUM)

**Goal**: Avoid refetching capabilities when cached data is fresh, but allow explicit refresh

**Changes from original plan**: Add a `force_refresh` parameter to `sync_peer()`.

### Step 3.1: Add `force_refresh` Parameter

**File**: `actingweb/interface/subscription_manager.py`

```python
def sync_peer(
    self,
    peer_id: str,
    config: "SubscriptionProcessingConfig | None" = None,
    _skip_revocation_detection: bool = False,
    force_refresh: bool = False,  # NEW
) -> PeerSyncResult:
```

And the async version:

```python
async def sync_peer_async(
    self,
    peer_id: str,
    config: "SubscriptionProcessingConfig | None" = None,
    _skip_revocation_detection: bool = False,
    force_refresh: bool = False,  # NEW
) -> PeerSyncResult:
```

### Step 3.2: Staleness Check with Force Bypass

In the capability fetch section of `sync_peer()` / `sync_peer_async()`:

```python
if (
    actor_config
    and actor_id
    and getattr(actor_config, "peer_capabilities_caching", False)
):
    store = get_cached_capabilities_store(actor_config)

    # Skip fetch if cache is fresh AND not force-refreshing
    if not force_refresh:
        cached = store.get_capabilities(actor_id, peer_id)
        max_age = getattr(actor_config, "peer_capabilities_max_age_seconds", 3600)
        if cached and cached.fetched_at:
            age = (datetime.now(UTC) - datetime.fromisoformat(cached.fetched_at)).total_seconds()
            if age < max_age:
                logger.debug(f"Using cached capabilities for {peer_id} (age: {age:.0f}s)")
                # Skip fetch
                ...

    # Fetch if cache miss, stale, or force_refresh
    capabilities = await fetch_peer_methods_and_actions_async(...)
    store.store_capabilities(capabilities)
```

### Step 3.3: Developer API Passes force_refresh=True

The developer API sync endpoint should pass `force_refresh=True` so manual triggers always do a complete refresh.

### Step 3.4: Make Max Age Configurable

Same as original plan — add `peer_capabilities_max_age_seconds` config option with 3600 default.

---

## Action Items Summary

### ✅ COMPLETED (Phase 0 & 0.5)

1. **✅ Debug profile data storage bug** - COMPLETE (2026-02-02)
   - ✅ Added diagnostic logging at 4 key points
   - ✅ Ran test scenarios with detailed logging
   - ✅ Identified Bug 1: Double-wrapping of properties in API metadata format
   - ✅ Identified Bug 2: Profile extraction never executing (only in async version)
   - ✅ Fixed Bug 1: Unwrap API metadata format in `remote_storage.py`
   - ✅ Fixed Bug 2: Created shared extraction helper, updated sync_peer() and sync_peer_async()
   - ✅ Verified with integration tests
   - ✅ All tests passing, code quality checks passing

### Next: Phase 1 (CRITICAL — Correctness Bug)

2. **Fix permission diff asymmetry** — "2 revoked" bug
   - `_build_callback_data()` sends override-only data but `PeerPermissionStore` caches full effective permissions
   - Causes false revocations and potential data loss via `_delete_revoked_peer_data()`
   - Fix: merge base trust-type permissions into callback payload
   - **MUST be done before Phase 2** — currently full `sync_peer()` masks the bug
   - Status: NOT STARTED

### Then: Phase 2 (HIGH — Performance)

3. **Implement incremental sync on permission grant**
   - Replace full `sync_peer()` with targeted property fetches
   - Biggest impact: 6 fewer HTTP requests per permission grant
   - Blocked by: Phase 1 (without correct diffs, incremental sync makes data loss permanent)
   - Status: NOT STARTED

### Then: Phase 3 (MEDIUM — Performance)

4. **Add capability cache staleness checks with force_refresh**
   - Only refetch if >1 hour old (configurable)
   - Add `force_refresh` parameter to `sync_peer()` for manual/developer triggers
   - Impact: 2 fewer HTTP requests per auto-sync
   - Status: NOT STARTED

### Future (LOW — Separate Concern)

5. **Investigate `delete_all` safety in `apply_resync_data()`**
   - Current wipe-and-replace can lose data if baseline response is incomplete
   - Consider compare-and-update semantics or non-empty validation before wiping
   - Phase 2 partially mitigates this by reducing how often `apply_resync_data()` runs
   - Status: NOT STARTED

### Current State (as of 2026-02-02)

**What's working now:**
- ✅ Properties stored correctly without double-wrapping
- ✅ Profile extraction from RemotePeerStore (no redundant fetch)
- ✅ RemotePeerStore contains displayname, email, list properties
- ✅ PeerProfileStore contains extracted profile
- ✅ 1 fewer HTTP request per peer sync (profile fetch eliminated)

**What needs fixing (correctness):**
- ❌ Permission diff asymmetry causes false revocations ("2 revoked" bug)
- ❌ `_delete_revoked_peer_data()` may delete valid data based on false diffs

**What still needs optimization (performance):**
- ❌ Permission grant triggers full sync (7 requests instead of 1-2)
- ❌ Capabilities refetched every sync (no staleness check)
- ❌ Full baseline refetch on permission grant (should be incremental)
- ❌ Manual sync has no way to bypass future staleness cache

---

## Key Takeaways

1. ~~**Profile data not being stored is the critical bug**~~ **✅ FIXED - Root cause was double-wrapping from API metadata format**
2. **Permission diff asymmetry is a correctness bug** — callback sends override-only data, diff compares against full cached permissions, produces false revocations
3. **Incremental sync depends on correct diffs** — must fix the diff bug before removing full `sync_peer()` as the auto-sync path (it accidentally compensates for false revocations)
4. **Manual sync needs force_refresh** — capability staleness check should not apply to developer-triggered syncs
5. **`delete_all` in resync is a separate safety concern** — wipe-and-replace risks data loss on incomplete responses
6. **Performance can improve 43%** — from 14 to 8 HTTP requests per cycle (1 request saved so far, 6 more to go)
7. **Auto-subscription is application choice** — library doesn't force it on trust establishment
8. **Diagnostic logging approach successful** — Adding targeted logs at 4 critical points identified both bugs

---

## Implementation Summary (2026-02-02)

### Diagnostic Approach That Worked

The systematic diagnostic logging approach (Phase 0, Step 0.1) successfully identified both bugs:

1. **Logged data flow at 4 critical points:**
   - Before `apply_resync_data`: Showed properties present in transformed data
   - Inside `apply_resync_data`: Revealed `_list: False` metadata wrapper
   - At storage line: Confirmed storage operations executed
   - After storage: Detected double-wrapped structure when reading back

2. **Key diagnostic log that revealed Bug 1:**
   ```
   displayname: {'value': {'value': 'Test User B'}, '_list': False}
   ```
   This immediately showed the double-wrapping issue.

3. **Key diagnostic observation that revealed Bug 2:**
   - Profile extraction diagnostic logs (lines 2543-2620) **never appeared**
   - Confirmed extraction code was being bypassed entirely
   - Found extraction only existed in async version, not sync version

### Fixes Applied

**Bug 1 Fix (Double-Wrapping)**:
- Location: `actingweb/remote_storage.py:435-449`
- Solution: Detect API metadata format `{"value": ..., "_list": False}` and unwrap before storage
- Result: Properties stored correctly with single wrapping

**Bug 2 Fix (Extraction Bypass)**:
- Location: `actingweb/interface/subscription_manager.py:1566-1620, 2262-2378, 2650-2711`
- Solution: Created shared `_extract_profile_from_remote_store()` helper, updated both sync/async versions
- Result: Profile extracted from RemotePeerStore, no redundant fetch

### Verification

- Created `test_peer_profile_extraction.py` - verifies extraction works correctly
- Updated `test_subscription_baseline_storage.py` - validates storage of all property types
- Both tests **passing** ✅
- Pyright: 0 errors ✅
- Ruff: All checks passed ✅

### Performance Improvement

**Before**:
- Profile fetched from peer every sync (1 redundant HTTP request)
- 7-8 requests per peer sync

**After**:
- Profile extracted from RemotePeerStore (0 requests)
- 6-7 requests per peer sync (1 request saved)

**Remaining Opportunities (Phases 1-2)**:
- Incremental sync on permission grant: Save 6 requests
- Capability cache staleness: Save 2 requests
- **Total potential**: 8 requests saved (43% reduction)

### Lessons Learned

1. **Targeted diagnostic logging is extremely effective** - Adding logs at just 4 strategic points quickly identified both bugs
2. **API format assumptions can break** - The `?metadata=true` wrapper wasn't being handled correctly
3. **Async/sync duplication creates bugs** - Bug 2 existed because extraction logic was only in async version
4. **Refactoring pays off** - Creating shared helper eliminated duplication and prevented future bugs
5. **Tests catch real issues** - Integration tests immediately validated the fixes work correctly
