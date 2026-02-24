# Fix Subscription Baseline Sync for List Properties

## Updated Problem Analysis

After reviewing the ActingWeb specification and architecture, I now have a complete understanding of the subscription sync flow:

### Subscription Sync Flow (ActingWeb Protocol)

1. **Local actor** (B) has subscription to **remote peer** (A)
2. When `sync_subscription()` is called with no diffs available:
   - Constructs target path (e.g., `properties`)
   - Adds `?metadata=true` parameter for properties endpoint
   - Calls `proxy.get_resource(path)` to **fetch from remote peer A** via ActingWeb REST protocol
3. **Remote peer A** (via its properties handler):
   - Returns list properties in minimal format: `{"memory_travel": {"_list": true, "count": 3}}`
   - This is metadata only, no actual list items
4. **Local actor B** receives baseline response:
   - Passes to `RemotePeerStore.apply_resync_data()`
   - Expects format: `{"list:memory_travel": [items]}`
   - **Mismatch**: Gets metadata `{"_list": true}` instead of `"list:"` prefix with items

### Root Cause

The baseline fetch is a **cross-actor protocol operation**, not an internal database operation:

1. `subscription_manager.py:708` - Adds `?metadata=true` when fetching baseline from remote peer
2. Remote peer's `properties.py:408-414` - Returns `{"_list": true, "count": N}` for lists (metadata only)
3. `remote_storage.py:328-336` - Expects `{"list:name": [items]}` format
4. **Result**: List properties stored as scalar metadata, not actual lists

## Solution: Proper Baseline Fetch with Permission-Aware Item Retrieval

The fix must transform the baseline data **after** receiving it from the remote peer, by:
1. Detecting list metadata in the response
2. Fetching actual list items from **remote peer** via `proxy.get_resource()`
3. Applying permission filtering (property-level permissions)
4. Transforming to the format expected by `apply_resync_data()`

### Why We Can't Just Change the Remote Peer's Response

The remote peer's `?metadata=true` format serves a legitimate purpose:
- Allows discovery of list properties without fetching all items
- Prevents accidental large data transfers
- Supports permission-aware responses (peer may not have access to items)

The fix must be on the **receiving side** (subscription sync), not the sending side.

## Implementation Plan

### Step 1: Create Baseline Transformation Helper

**Location**: `actingweb/interface/subscription_manager.py` (after line 860)

**Method**:
```python
def _transform_baseline_list_properties(
    self,
    baseline_data: dict[str, Any],
    peer_id: str,
    target: str,
) -> dict[str, Any]:
    """
    Transform list property metadata into actual list items for baseline sync.

    When baseline fetch returns list metadata ({"_list": true, "count": N}),
    this fetches the actual items from the remote peer via ActingWeb protocol
    and transforms to the format expected by apply_resync_data().

    Args:
        baseline_data: Baseline response from remote peer (may contain list metadata)
        peer_id: ID of remote peer we're syncing from
        target: Subscription target (e.g., "properties")

    Returns:
        Transformed data with lists in format {"property_name": {"_list": true, "items": [...]}}
    """
```

**Implementation**:
1. Create result dict (shallow copy of baseline_data)
2. Get proxy using existing `_get_peer_proxy()` method:
   ```python
   proxy = self._get_peer_proxy(peer_id)
   if proxy is None or proxy.trust is None:
       logger.warning(f"No trust with peer {peer_id}, skipping list transformation")
       return baseline_data
   ```
3. Iterate through baseline_data items:
   - Skip if not a list metadata dict: `not isinstance(value, dict) or not value.get("_list")`
   - Skip if already has items: `"items" in value`
   - For list metadata without items:
     - Construct path: `{target}/{property_name}` (e.g., `properties/memory_travel`)
     - Fetch via `proxy.get_resource(path)` (ActingWeb protocol GET to remote peer)
     - Remote peer's handler returns JSON array: `[{...}, {...}]` (with permissions enforced)
     - Validate response is a list
     - Transform: `result[property_name] = {"_list": True, "items": response}`
     - Log warning if list has >100 items
     - On error (404, 403, timeout, invalid response):
       - Log warning with details
       - Keep metadata as-is (don't crash, fail gracefully)
4. Return transformed dict

**Error handling**:
- 404 Not Found: Property doesn't exist or peer deleted it → skip, log warning
- 403 Forbidden: No permission to access → skip, log warning
- Timeout/network error: Remote peer unreachable → skip, log error
- Invalid response (not a list): Unexpected format → skip, log error
- All errors are non-fatal: transformation continues for other properties

**Key points**:
- Uses ActingWeb protocol to fetch items from remote peer via AwProxy
- Permission filtering happens automatically:
  - Remote peer enforces permissions via property hooks
  - Returns 404 if peer doesn't have access
  - Returns only items peer is allowed to see
- Fails closed: excludes lists on error, doesn't crash sync
- Each list property requires one additional GET request to remote peer

### Step 2: Update apply_resync_data() for Flag-Based Lists

**Location**: `actingweb/remote_storage.py:328-336`

**Current code**:
```python
if key.startswith("list:") and isinstance(value, list):
    list_name = key[5:]
    self.set_list(list_name, value)
```

**New code**:
```python
# Check for flag-based list format (preferred)
if isinstance(value, dict) and value.get("_list") is True:
    # Extract items from flag-based format
    items = value.get("items", [])
    self.set_list(key, items)
    results[key] = {
        "operation": "resync",
        "items": len(items),
        "success": True,
    }
# Keep "list:" prefix detection for backward compatibility
elif key.startswith("list:") and isinstance(value, list):
    list_name = key[5:]
    self.set_list(list_name, value)
    results[list_name] = {
        "operation": "resync",
        "items": len(value),
        "success": True,
    }
```

**Rationale**:
- Detect lists via `_list` flag (not "list:" prefix in key name)
- Extract items from `value["items"]`
- `set_list()` internally uses "list:" prefix for storage (implementation detail)
- Keep "list:" prefix support for backward compatibility

### Step 3: Integrate Transformation in sync_subscription()

**Location**: `actingweb/interface/subscription_manager.py:720-732`

**Modification**:
```python
if baseline_response and "error" not in baseline_response:
    # For properties subscriptions, transform list metadata into actual items
    # Only needed when subscribing to full /properties endpoint (no subtarget)
    # Subtarget subscriptions (e.g., properties/list:name) already return full items
    if sub.target == "properties" and not sub.subtarget and not sub.resource:
        transformed_data = self._transform_baseline_list_properties(
            baseline_data=baseline_response,
            peer_id=peer_id,
            target=sub.target,
        )
    else:
        transformed_data = baseline_response

    # Store baseline data
    from .actor_interface import ActorInterface

    actor_interface = ActorInterface(self._core_actor)
    store = RemotePeerStore(
        actor=actor_interface,
        peer_id=peer_id,
        validate_peer_id=False,
    )

    # Apply transformed baseline as resync data
    store.apply_resync_data(transformed_data)
```

**Why only for full properties subscriptions**:
- Condition: `sub.target == "properties" and not sub.subtarget and not sub.resource`
- List properties only appear as metadata in full `/properties` GET responses
- Subtarget subscriptions (`properties/list:memory`) already get full items directly
- Resource subscriptions (`properties/data/item`) don't involve list properties
- Transformation only needed when baseline fetch uses `?metadata=true`

### Step 4: Unit Tests

**Location**: `tests/test_subscription_manager.py`

**Test cases**:
1. `test_transform_baseline_list_metadata()` - Transform list metadata to items
2. `test_transform_baseline_mixed_properties()` - Mix of scalar and list properties
3. `test_transform_baseline_empty_list()` - Handle empty lists
4. `test_transform_baseline_permission_denied()` - Handle 403 from remote peer
5. `test_transform_baseline_fetch_error()` - Handle network/protocol errors

**Location**: `tests/test_remote_storage.py`

**Test cases**:
1. `test_apply_resync_data_flag_based_list()` - New `{"_list": true, "items": [...]}` format
2. `test_apply_resync_data_legacy_list_prefix()` - Backward compat: `{"list:name": [...]}`
3. `test_apply_resync_data_mixed_format()` - Both formats work together

### Step 5: Integration Tests

**Location**: `tests/integration/test_property_lists_advanced.py`

**Test cases**:
1. `test_subscription_baseline_sync_with_lists()` - End-to-end baseline sync
   - Create Actor A with list property containing 3 items
   - Create Actor B, establish trust relationship A→B
   - Actor B creates subscription to A's properties (outbound subscription)
   - Call `actor_b.subscriptions.sync_subscription(peer_id=actor_a.id, subscription_id=...)`
   - Verify:
     - Baseline fetch made HTTP GET to A's /properties?metadata=true
     - Transformation detected list metadata
     - Made additional GET to A's /properties/{list_name}
     - B's RemotePeerStore has all 3 list items
     - Scalar properties also synced correctly

2. `test_subscription_baseline_sync_permission_filtered()` - Permission filtering
   - Actor A has list property with 5 items
   - Set permission on A to only allow peer B to read 3 items (via property hook)
   - Actor B syncs subscription
   - Verify B's RemotePeerStore only has 3 items (remote peer enforced permissions)

3. `test_subscription_baseline_sync_large_list_warning()` - Large list handling
   - Actor A has list property with 150 items
   - Actor B syncs subscription
   - Verify warning logged about large list (>100 items)
   - Verify all 150 items still synced (warning only, not error)

4. `test_subscription_baseline_sync_mixed_properties()` - Mixed content
   - Actor A has: 2 scalar properties, 1 empty list, 1 list with items
   - Actor B syncs subscription
   - Verify all properties synced correctly with appropriate formats

5. `test_subscription_baseline_sync_list_permission_denied()` - Permission denied handling
   - Actor A has list property
   - Set permission to deny peer B access to that specific list
   - Actor B syncs subscription
   - Verify:
     - List property not in B's RemotePeerStore
     - Warning logged about 403 error
     - Other properties still synced successfully

## Edge Cases

- **Empty lists**: Fetched as `[]`, stored correctly
- **Large lists**: Log warning if >100 items (recommend subtarget subscriptions)
- **Missing lists**: Remote returns 404, skip property (logged)
- **Permission denied**: Remote returns 403, skip property (logged)
- **Protocol errors**: Network/timeout errors skip property (logged)
- **Malformed responses**: Validation errors skip property (logged)

## Backward Compatibility

✅ **New format**: `{"memory": {"_list": true, "items": [...]}}`
✅ **Legacy format**: `{"list:memory": [...]}` still supported
✅ **Protocol compatibility**: Uses standard ActingWeb GET requests
✅ **No breaking changes**: Existing subscriptions continue to work
✅ **Diff operations**: Already work correctly (unchanged)

## Performance Considerations

- **Network requests**: N+1 requests for N list properties in baseline (acceptable for initial sync)
- **Recommendation**: Document that subtarget subscriptions (`list:property_name`) are more efficient
- **Mitigation**: Baseline sync is infrequent (only when no diffs available)
- **Future**: Could batch list fetches in a single protocol request (out of scope)

## Critical Files to Modify

1. **actingweb/interface/subscription_manager.py** (lines 690-860)
   - Add `_transform_baseline_list_properties()` method
   - Modify `sync_subscription()` to call transformation

2. **actingweb/remote_storage.py** (lines 311-347)
   - Update `apply_resync_data()` to detect `_list` flag
   - Keep "list:" prefix support for backward compatibility

3. **tests/test_subscription_manager.py**
   - Add 5 unit tests for transformation

4. **tests/test_remote_storage.py**
   - Add 3 unit tests for flag-based lists

5. **tests/integration/test_property_lists_advanced.py**
   - Add 5 integration tests for end-to-end verification

## Verification Steps

1. **Run unit tests**:
   ```bash
   poetry run pytest tests/test_subscription_manager.py -v -k transform
   poetry run pytest tests/test_remote_storage.py -v -k resync
   ```

2. **Run integration tests**:
   ```bash
   poetry run pytest tests/integration/test_property_lists_advanced.py -v -k baseline
   ```

3. **Manual verification**:
   - Create two actors with trust relationship
   - Actor A: Add 3 items to list property
   - Actor B: Subscribe to A's properties
   - Sync subscription (triggers baseline fetch)
   - Verify B has all 3 items in RemotePeerStore

4. **Full test suite**:
   ```bash
   make test-all-parallel
   ```

5. **Type checking**:
   ```bash
   poetry run pyright actingweb tests
   ```

6. **Linting**:
   ```bash
   poetry run ruff check actingweb tests
   ```

## Protocol Compliance

This fix aligns with ActingWeb specification v1.3+:
- Uses standard GET requests to fetch list items
- Respects permission model (remote peer enforces access)
- Supports both metadata discovery (`?metadata=true`) and full item fetch
- Compatible with list property subscription diff format
