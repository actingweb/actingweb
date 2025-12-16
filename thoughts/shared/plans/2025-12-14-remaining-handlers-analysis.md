# Remaining Handlers Analysis

**Date**: 2025-12-14
**Status**: 🔄 ANALYSIS COMPLETE
**Handlers Analyzed**: methods.py, actions.py, callbacks.py

## Summary

Analysis of the three remaining handlers reveals:
- ✅ **MethodsHandler**: No refactoring needed (uses hooks exclusively)
- ✅ **ActionsHandler**: No refactoring needed (uses hooks exclusively)
- ⚠️ **CallbacksHandler**: Needs 2 methods in SubscriptionManager

## Detailed Analysis

### MethodsHandler ✅ CLEAN

**File**: `actingweb/handlers/methods.py`

**Direct Actor calls**: 0

**Current Implementation**:
- Already uses hooks exclusively via `self.hooks.execute_method_hooks()`
- Gets ActorInterface via `self._get_actor_interface(myself)`
- No business logic in handler
- Perfect example of clean handler pattern

**Conclusion**: ✅ No refactoring needed

---

### ActionsHandler ✅ CLEAN

**File**: `actingweb/handlers/actions.py`

**Direct Actor calls**: 0

**Current Implementation**:
- Already uses hooks exclusively via `self.hooks.execute_action_hooks()`
- Gets ActorInterface via `self._get_actor_interface(myself)`
- No business logic in handler
- Perfect example of clean handler pattern

**Conclusion**: ✅ No refactoring needed

---

### CallbacksHandler ⚠️ NEEDS REFACTORING

**File**: `actingweb/handlers/callbacks.py`

**Direct Actor calls**: 2

**Issues Found**:

**1. Line 70**: Get callback subscription object for deletion
```python
sub = myself.get_subscription_obj(peerid=peerid, subid=subid, callback=True)
if sub:
    sub.delete()
```

**2. Line 110**: Get callback subscription data for existence check
```python
sub = myself.get_subscription(peerid=peerid, subid=subid, callback=True)
if sub and len(sub) > 0:
    # ... process callback ...
```

**What These Do**:
- Both get **callback subscriptions** (outbound - we subscribed to them)
- `callback=True` means "we receive callbacks from this peer"
- Line 70: Deletes the local subscription (no peer notification)
- Line 110: Checks if subscription exists to validate incoming callback

**Current Developer API Gaps**:

1. **No method to get callback subscription specifically**
   - `get_subscription()` exists but doesn't accept `callback` parameter
   - Need: `get_callback_subscription()` or extend `get_subscription()`

2. **No method to delete callback subscription (local only)**
   - `unsubscribe()` exists but tries to notify peer (wrong for callbacks)
   - Need: `delete_callback_subscription()` for local-only deletion

## Proposed Solution

### Extend SubscriptionManager with 2 Methods

**1. get_callback_subscription(peer_id, subscription_id)**
```python
def get_callback_subscription(
    self, peer_id: str, subscription_id: str
) -> SubscriptionInfo | None:
    """
    Get a callback subscription (outbound - we subscribed to them).

    Callback subscriptions are ones we initiated - we receive callbacks from the peer.

    Args:
        peer_id: ID of the peer actor we subscribed to
        subscription_id: ID of the subscription

    Returns:
        SubscriptionInfo if found, None otherwise
    """
    sub_data = self._core_actor.get_subscription(
        peerid=peer_id, subid=subscription_id, callback=True
    )
    if sub_data and isinstance(sub_data, dict):
        return SubscriptionInfo(sub_data)
    return None
```

**2. delete_callback_subscription(peer_id, subscription_id)**
```python
def delete_callback_subscription(
    self, peer_id: str, subscription_id: str
) -> bool:
    """
    Delete a callback subscription (local only, no peer notification).

    This is used when a peer terminates our subscription to them.
    We just remove our local record without notifying the peer.

    Args:
        peer_id: ID of the peer actor
        subscription_id: ID of the subscription to delete

    Returns:
        True if deleted successfully, False otherwise
    """
    result = self._core_actor.delete_subscription(
        peerid=peer_id, subid=subscription_id, callback=True
    )
    return bool(result)
```

**Lines to Add**: ~30 lines (2 methods)

### Refactor CallbacksHandler

**Change 1 - Line 70** (delete method):
```python
# BEFORE
sub = myself.get_subscription_obj(peerid=peerid, subid=subid, callback=True)
if sub:
    sub.delete()
    self.response.set_status(204, "Deleted")
    return

# AFTER
actor_interface = self._get_actor_interface(myself)
if not actor_interface:
    if self.response:
        self.response.set_status(500, "Internal error")
    return

if actor_interface.subscriptions.delete_callback_subscription(
    peer_id=peerid, subscription_id=subid
):
    self.response.set_status(204, "Deleted")
    return
```

**Change 2 - Line 110** (post method):
```python
# BEFORE
sub = (
    myself.get_subscription(peerid=peerid, subid=subid, callback=True)
    if myself
    else None
)
if sub and len(sub) > 0:
    # ... process callback ...

# AFTER
actor_interface = self._get_actor_interface(myself) if myself else None
if not actor_interface:
    self.response.set_status(404, "Not found")
    return

sub_info = actor_interface.subscriptions.get_callback_subscription(
    peer_id=peerid, subscription_id=subid
)
if sub_info:
    # Convert to dict for hook compatibility
    sub = sub_info.to_dict()
    # ... process callback ...
```

**Lines Changed**: ~15-20 lines (2 replacements + error handling)

## Testing Strategy

### Unit Tests for New Methods

**File**: `tests/test_subscription_manager.py` (add to existing file)

**Tests to Add** (6 tests):

1. `test_get_callback_subscription_exists()`
   - Create callback subscription, verify retrieval

2. `test_get_callback_subscription_not_found()`
   - Try to get non-existent subscription, returns None

3. `test_get_callback_subscription_wrong_type()`
   - Try to get local subscription with callback method, returns None

4. `test_delete_callback_subscription_success()`
   - Delete existing callback subscription, returns True

5. `test_delete_callback_subscription_not_found()`
   - Delete non-existent subscription, returns False

6. `test_delete_callback_subscription_no_peer_notification()`
   - Verify peer is NOT notified (unlike unsubscribe)

### Integration Tests

**Use Existing Tests**: CallbacksHandler already has integration tests

Run existing callback tests to ensure no regressions:
```bash
poetry run pytest tests/integration/ -k callback -v
```

## Success Metrics

- ✅ MethodsHandler requires no changes (already clean)
- ✅ ActionsHandler requires no changes (already clean)
- [ ] 2 new SubscriptionManager methods added (~30 lines)
- [ ] CallbacksHandler refactored (2 call sites, ~15-20 lines changed)
- [ ] 6 unit tests created for new methods
- [ ] 0 type errors (pyright)
- [ ] All integration tests passing
- [ ] HTTP API contract unchanged

## Comparison: All Handlers

| Handler | Direct Actor Calls | Developer API Methods Added | Handler Changes | Unit Tests Created | Status |
|---------|-------------------|---------------------------|-----------------|-------------------|--------|
| SubscriptionHandler | 8 call sites | 2 methods + wrapper (~131 lines) | 8 methods refactored | 16 tests | ✅ COMPLETE |
| TrustHandler | 7 call sites | 4 methods (~103 lines) | 7 methods refactored | 24 tests | ✅ COMPLETE |
| PropertiesHandler | 3 call sites | 0 methods (already exist) | 3 call sites changed | 0 tests (covered) | ✅ COMPLETE |
| MethodsHandler | 0 calls | 0 methods | 0 changes | 0 tests | ✅ CLEAN |
| ActionsHandler | 0 calls | 0 methods | 0 changes | 0 tests | ✅ CLEAN |
| **CallbacksHandler** | **2 call sites** | **2 methods (~30 lines)** | **2 call sites changed** | **6 tests** | ⏸️ **READY TO REFACTOR** |

## Estimated Effort

- **Developer API Extension**: ~30 lines (2 simple methods)
- **Handler Refactoring**: ~15-20 lines (2 replacements)
- **Unit Tests**: ~100 lines (6 tests)
- **Complexity**: Low (similar to PropertyStore refactoring)
- **Duration**: 0.5 session (30 minutes)

## Next Steps

1. Add 2 methods to SubscriptionManager (~30 lines)
2. Add 6 unit tests to test_subscription_manager.py (~100 lines)
3. Refactor 2 call sites in CallbacksHandler (~15-20 lines)
4. Run type checking (expect 0 errors)
5. Run integration tests (expect all passing)
6. Document completion

## Conclusion

Out of 6 handlers analyzed:
- **2 handlers** (Methods, Actions) are already perfect - no changes needed
- **3 handlers** (Subscription, Trust, Properties) are complete
- **1 handler** (Callbacks) needs minimal refactoring

The CallbacksHandler refactoring is straightforward because:
- Only 2 call sites to change
- Only 2 simple methods to add
- No complex business logic
- Similar to PropertiesHandler (simple replacements)

After completing CallbacksHandler, **all 6 handlers will use the developer API exclusively**, achieving our goal of a full-featured developer API interface to ActingWeb!
