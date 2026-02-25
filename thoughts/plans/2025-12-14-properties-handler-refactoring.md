# PropertiesHandler Refactoring Plan

**Date**: 2025-12-14
**Status**: 🔄 IN PROGRESS
**Pattern**: Following handler-refactoring-pattern.md (5 steps)

## Overview

Refactor PropertiesHandler to eliminate remaining direct Actor calls. Most of the handler already uses the developer API (ActorInterface, hooks), but 3 direct Actor method calls remain.

## Analysis Results

### Current State

**Good**: PropertiesHandler already uses modern patterns
- ✅ Uses `self._get_actor_interface(myself)` for hook execution
- ✅ Uses custom `_check_property_permission()` for permission checks
- ✅ Uses hook system for property operations
- ✅ Uses `register_diffs()` for subscription notifications (added in Phase 3)

**Needs Refactoring**: 3 direct Actor method calls
- ❌ Line 287: `properties = myself.get_properties()` → Use `actor.properties.to_dict()`
- ❌ Line 870: `myself.get_properties()` (in hook execution) → Use `actor.properties.to_dict()`
- ❌ Line 875: `myself.delete_properties()` → Use `actor.properties.clear()`

### Developer API Already Available

PropertyStore already provides the needed methods:
- `PropertyStore.to_dict()` - Returns all properties as dict (line 197)
- `PropertyStore.clear()` - Clears all properties with diff registration (line 187)

**No new developer API methods needed!**

## Refactoring Steps (Following Pattern)

### Step 1: Identify Missing Developer API Methods ✅ COMPLETE

**Result**: No new methods needed. PropertyStore already has:
- `to_dict()` - replacement for `get_properties()`
- `clear()` - replacement for `delete_properties()`

### Step 2: Design Developer API Extensions ✅ COMPLETE

**Result**: Skip - no new methods needed

### Step 3: Create Wrapper Classes When Needed ✅ COMPLETE

**Result**: Skip - PropertyStore is already sufficient

### Step 4: Refactor Handlers to Use Developer API

**Changes Required:**

**4.1. Line 287** - `listall()` method:
```python
# BEFORE
properties = myself.get_properties()

# AFTER
actor_interface = self._get_actor_interface(myself)
if not actor_interface:
    if self.response:
        self.response.set_status(500, "Internal error")
    return
properties = actor_interface.properties.to_dict()
```

**4.2. Line 870** - `delete()` method (hook execution):
```python
# BEFORE
result = self.hooks.execute_property_hooks(
    "*", "delete", actor_interface, myself.get_properties(), path
)

# AFTER
result = self.hooks.execute_property_hooks(
    "*", "delete", actor_interface, actor_interface.properties.to_dict(), path
)
```

**4.3. Line 875** - `delete()` method:
```python
# BEFORE
myself.delete_properties()

# AFTER
actor_interface.properties.clear()
```

### Step 5a: Type Check

```bash
poetry run pyright actingweb/handlers/properties.py
# Expected: 0 errors, 0 warnings
```

### Step 5b: Create Unit Tests for Developer API Methods

**Result**: Skip - `to_dict()` and `clear()` are already tested in existing PropertyStore tests

**Verification**:
```bash
# Confirm existing tests cover these methods
poetry run pytest tests/ -k "test_property" --collect-only | grep -E "to_dict|clear"
```

### Step 5c: Run Integration Tests

```bash
# Run all property-related integration tests
poetry run pytest tests/integration/test_property_notifications.py -v
poetry run pytest tests/integration/test_authenticated_access.py -v
poetry run pytest tests/integration/test_property_list_notifications.py -v

# Expected: All tests pass, no regressions
```

## Files Modified

1. `actingweb/handlers/properties.py`
   - Line 287: Replace `myself.get_properties()` with `actor_interface.properties.to_dict()`
   - Line 870: Replace `myself.get_properties()` with `actor_interface.properties.to_dict()`
   - Line 875: Replace `myself.delete_properties()` with `actor_interface.properties.clear()`
   - **Estimated**: ~10 lines changed (simple replacements)

## Success Metrics

- ✅ No new developer API methods needed (already available)
- [ ] 0 type errors (pyright)
- [ ] All integration tests passing (no regressions)
- [ ] Handler code reduced by ~10 lines
- [ ] No direct Actor calls remaining in PropertiesHandler
- [ ] Clear separation: HTTP ↔ PropertyStore ↔ Core Actor

## Benefits

1. **Consistency**: Uses same PropertyStore API as other code
2. **Maintainability**: All property operations go through PropertyStore
3. **Type Safety**: Full type checking on all operations
4. **Simplicity**: Minimal changes required (only 3 call sites)

## Comparison with Other Handlers

| Handler | Developer API Methods Added | Handler Changes | Unit Tests Created |
|---------|---------------------------|-----------------|-------------------|
| SubscriptionHandler | 2 methods + wrapper (~131 lines) | 8 methods refactored | 16 tests |
| TrustHandler | 4 methods (~103 lines) | 7 methods refactored | 24 tests |
| **PropertiesHandler** | **0 methods (already exist)** | **3 call sites changed** | **0 tests (already covered)** |

PropertiesHandler is the **simplest refactoring** because the developer API already provides all needed functionality!

## Estimated Effort

- **Lines to change**: ~10-15 (3 simple replacements)
- **Complexity**: Low (no new API methods, no new tests)
- **Duration**: 0.25 session (15-20 minutes)

## Next Steps

1. Make the 3 code changes in properties.py
2. Run type checking
3. Run integration tests
4. Document completion
5. Move to MethodsHandler/ActionsHandler/CallbacksHandler analysis
