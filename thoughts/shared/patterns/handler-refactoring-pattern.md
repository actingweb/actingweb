# Handler Refactoring Pattern

## Overview

This document describes the established pattern for refactoring HTTP handlers to use the developer API instead of directly accessing the core Actor class. This pattern was established during the SubscriptionHandler refactoring and should be reused for TrustHandler, PropertiesHandler, and future handlers.

## Goal

Move 75% of business logic FROM handlers INTO developer API, leaving handlers as thin HTTP wrappers that:
- Handle HTTP request/response formatting
- Perform authentication and authorization
- Delegate business logic to developer API
- Return HTTP responses

## Architecture Layers

```
HTTP Request
    ↓
Handler (25% - HTTP concerns)
    ↓
Developer API (75% - business logic)
    ↓
Core Actor (data layer)
```

## The Pattern

### Step 1: Identify Missing Developer API Methods

Review handler code and identify operations not available in the developer API. Look for:
- Direct calls to `actor.method()` instead of `actor_interface.manager.method()`
- Operations on objects returned by `actor.get_*_obj()`
- Complex data transformations done in handlers

**Example from SubscriptionHandler:**
```python
# Handler was doing this directly:
sub = myself.get_subscription_obj(peerid=peerid, subid=subid)
diffs = sub.get_diffs()
sub.clear_diffs(seqnr=seqnr)

# Needed developer API equivalent
```

### Step 2: Design Developer API Extensions

Create clean, high-level methods in the appropriate manager class:
- Use clear, descriptive method names
- Accept simple parameters (strings, ints, bools)
- Return high-level objects or simple types
- Hide core Actor implementation details

**Example - SubscriptionManager Extensions:**
```python
class SubscriptionManager:
    def create_local_subscription(
        self,
        peer_id: str,
        target: str,
        subtarget: str = "",
        resource: str = "",
        granularity: str = "high",
    ) -> dict[str, Any] | None:
        """Create a local subscription (accept incoming subscription from peer)."""
        # Delegates to core Actor
        new_sub = self._core_actor.create_subscription(
            peerid=peer_id,
            target=target,
            subtarget=subtarget or None,
            resource=resource or None,
            granularity=granularity,
            callback=False,
        )
        if new_sub and isinstance(new_sub, dict):
            return new_sub
        return None

    def get_subscription_with_diffs(
        self, peer_id: str, subscription_id: str
    ) -> SubscriptionWithDiffs | None:
        """Get subscription object with diff operations support."""
        core_sub = self._core_actor.get_subscription_obj(
            peerid=peer_id, subid=subscription_id
        )
        if core_sub:
            sub_data = core_sub.get()
            if sub_data and len(sub_data) > 0:
                return SubscriptionWithDiffs(core_sub)
        return None
```

### Step 3: Create Wrapper Classes When Needed

If core objects have multiple operations, create wrapper classes in the developer API:
- Wrap the core object
- Provide clean, type-safe methods
- Hide implementation details
- Return high-level types

**Example - SubscriptionWithDiffs Wrapper:**
```python
class SubscriptionWithDiffs:
    """Wrapper around core Subscription object with diff operations."""

    def __init__(self, core_subscription: CoreSubscription):
        self._core_sub = core_subscription

    @property
    def subscription_info(self) -> SubscriptionInfo | None:
        """Get subscription info as SubscriptionInfo object."""
        sub_data = self._core_sub.get()
        if sub_data:
            return SubscriptionInfo(sub_data)
        return None

    def get_diffs(self) -> list[dict[str, Any]]:
        """Get all pending diffs ordered by timestamp."""
        diffs = self._core_sub.get_diffs()
        if diffs is None:
            return []
        return diffs if isinstance(diffs, list) else []

    def clear_diffs(self, seqnr: int = 0) -> None:
        """Clear all diffs up to sequence number."""
        self._core_sub.clear_diffs(seqnr=seqnr)

    def get_diff(self, seqnr: int) -> dict[str, Any] | None:
        """Get specific diff by sequence number."""
        return self._core_sub.get_diff(seqnr=seqnr)

    def clear_diff(self, seqnr: int) -> bool:
        """Clear specific diff by sequence number."""
        return bool(self._core_sub.clear_diff(seqnr=seqnr))
```

### Step 4: Refactor Handlers to Use Developer API

Update handler methods to:
1. Get ActorInterface using `self._get_actor_interface(actor)`
2. Use manager methods instead of direct Actor calls
3. Remove complex business logic
4. Focus on HTTP concerns only

**Before (handler has business logic):**
```python
def get(self, actor_id, peerid, subid):
    myself = self.require_authenticated_actor(actor_id, "subscriptions", "GET")
    if not myself:
        return

    # Handler doing business logic directly
    sub = myself.get_subscription_obj(peerid=peerid, subid=subid)
    if not sub:
        self.response.set_status(404, "Subscription does not exist")
        return

    sub_data = sub.get()
    diffs = sub.get_diffs()

    # ... process diffs ...
```

**After (handler delegates to developer API):**
```python
def get(self, actor_id, peerid, subid):
    auth_result = self.authenticate_actor(
        actor_id, "subscriptions", subpath=peerid + "/" + subid
    )
    if not auth_result.success:
        return
    myself = auth_result.actor
    if not auth_result.authorize("GET", "subscriptions", "<id>/<id>"):
        return

    # Use developer API - ActorInterface with SubscriptionManager
    actor_interface = self._get_actor_interface(myself)
    if not actor_interface:
        if self.response:
            self.response.set_status(500, "Internal error")
        return

    # Use SubscriptionManager to get subscription with diff operations
    sub_with_diffs = actor_interface.subscriptions.get_subscription_with_diffs(
        peer_id=peerid, subscription_id=subid
    )
    if not sub_with_diffs:
        if self.response:
            self.response.set_status(404, "Subscription does not exist")
        return

    sub_info = sub_with_diffs.subscription_info
    diffs = sub_with_diffs.get_diffs()

    # ... format HTTP response ...
```

### Step 5: Type Check and Test

#### 5a. Type Checking

Run type checking on both handlers and developer API:
```bash
# Type check
poetry run pyright actingweb/handlers/subscription.py
poetry run pyright actingweb/interface/subscription_manager.py
```

**Expected Result**: 0 errors, 0 warnings

#### 5b. Create Unit Tests for Developer API Methods

**CRITICAL**: Create dedicated unit tests for each new developer API method. Integration tests validate end-to-end behavior through HTTP, but unit tests verify developer API methods work correctly in isolation.

**Why Unit Tests Matter:**
- **Fast**: No HTTP layer, no database setup
- **Focused**: Test one method at a time
- **Comprehensive**: Test edge cases, error conditions, multiple scenarios
- **Documentation**: Show how to use the developer API correctly
- **Confidence**: Prove methods work before handler refactoring

**Test Structure Pattern:**

1. **Create Mock Objects** - Minimal fakes for core Actor, Store, and domain objects:
```python
class FakeConfig:
    def __init__(self) -> None:
        self.root = "https://example.com/"

class FakeStore:
    def __init__(self) -> None:
        self._trustee_root: str | None = None

    @property
    def trustee_root(self) -> str | None:
        return self._trustee_root

    @trustee_root.setter
    def trustee_root(self, value: str | None) -> None:
        self._trustee_root = value

class FakeCoreActor:
    def __init__(self) -> None:
        self.id = "actor_1"
        self.config = FakeConfig()
        self.store = FakeStore()
```

2. **Test Each New Method** - Organize by method with multiple scenarios:
```python
class TestSubscriptionManagerCreateLocal:
    """Tests for SubscriptionManager.create_local_subscription()."""

    def test_create_local_subscription_basic(self):
        """Test creating a basic local subscription."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.create_local_subscription(
            peer_id="peer_1",
            target="properties",
            granularity="high",
        )

        assert result is not None
        assert result["peerid"] == "peer_1"
        assert result["target"] == "properties"

    def test_create_local_subscription_with_empty_subtarget(self):
        """Test creating subscription with empty subtarget."""
        # ... test empty string handling ...

    def test_create_local_subscription_multiple_peers(self):
        """Test creating subscriptions for multiple peers."""
        # ... test multiple operations ...
```

3. **Test Wrapper Classes** - Verify all wrapper operations:
```python
class TestSubscriptionWithDiffs:
    """Tests for SubscriptionWithDiffs wrapper class."""

    def test_get_diffs_empty(self):
        """Test getting diffs when none exist."""
        # ...

    def test_get_diffs_with_data(self):
        """Test getting diffs when they exist."""
        # ...

    def test_clear_diffs_all(self):
        """Test clearing all diffs."""
        # ...
```

4. **Integration Tests** - Combine multiple operations:
```python
class TestSubscriptionManagerIntegration:
    """Integration tests combining multiple operations."""

    def test_subscription_diff_workflow(self):
        """Test complete diff workflow: create, add diffs, clear."""
        # ... multi-step test ...
```

**Test Files to Create:**

For SubscriptionHandler refactoring:
- `tests/test_subscription_manager.py` (16 tests)
  - 4 tests for `create_local_subscription()`
  - 2 tests for `get_subscription_with_diffs()`
  - 8 tests for `SubscriptionWithDiffs` wrapper
  - 2 integration tests

For TrustHandler refactoring:
- `tests/test_trust_manager_new_methods.py` (24 tests)
  - 4 tests for `create_verified_trust()`
  - 7 tests for `modify_and_notify()`
  - 4 tests for `delete_peer_trust()`
  - 6 tests for `trustee_root` property
  - 3 integration tests

**Run Unit Tests:**
```bash
# Run new unit tests only (fast, no database)
poetry run pytest tests/test_subscription_manager.py -v --no-cov
poetry run pytest tests/test_trust_manager_new_methods.py -v --no-cov

# Expected: All tests pass
```

#### 5c. Run Integration Tests

Validate end-to-end behavior through HTTP API:
```bash
# Integration tests (require database)
poetry run pytest tests/integration/test_property_notifications.py -v
poetry run pytest tests/integration/test_trust_lifecycle.py -v

# Expected: All tests pass, no regressions
```

## Key Principles

### 1. Clean Separation of Concerns
- **Handlers**: HTTP request/response, authentication, authorization
- **Developer API**: Business logic, data operations, validation
- **Core Actor**: Data persistence, low-level operations

### 2. High-Level Abstractions
Developer API should provide:
- Descriptive method names (`create_local_subscription` vs `create_subscription`)
- Simple parameters (no nested dicts or complex objects)
- Clear return types (use wrapper classes, not raw dicts)
- Comprehensive docstrings

### 3. Type Safety
- Full type annotations on all methods
- Use `| None` for optional returns
- Create typed wrapper classes for complex objects
- Maintain 0 type errors (pyright)

### 4. Incremental Refactoring
- Start with smallest handler (SubscriptionHandler: 5 occurrences)
- Extend developer API incrementally
- Test after each handler refactoring
- Document patterns for next handler

## Applying to Other Handlers

### Next: TrustHandler (~15 occurrences)

**Missing TrustManager methods needed:**
1. `create_verified_trust()` - Create trust with ActingWeb verification callback
2. `trustee_root` property - Get/set trustee root URL
3. `get_shared_properties()` - Query properties shared based on permissions

**Wrapper class needed:**
- `TrustWithPermissions` - Wrap trust object with permission operations

### Future: PropertiesHandler (~58 occurrences)

**Missing PropertyStore methods needed:**
1. `get_properties_filtered()` - Get properties with permission filtering
2. `set_property_with_notification()` - Set property and trigger subscriptions
3. `delete_property_with_notification()` - Delete property and trigger subscriptions

**Note**: Much of this already exists via AuthenticatedActorView pattern

## Benefits of This Pattern

1. **Maintainability**: Business logic in one place (developer API)
2. **Testability**: Can test business logic without HTTP layer
3. **Consistency**: Same operations available across Flask, FastAPI, direct usage
4. **Type Safety**: Full type checking prevents runtime errors
5. **Documentation**: Developer API serves as contract/documentation
6. **Extensibility**: Easy to add new operations without modifying handlers

## Success Metrics

For each refactored handler:
- ✅ 0 type errors (pyright)
- ✅ Unit tests created for all new developer API methods
- ✅ All unit tests passing (16-24 tests per handler)
- ✅ All integration tests passing (no regressions)
- ✅ Handler code reduced by ~50-75%
- ✅ Business logic moved to developer API
- ✅ Clear separation: HTTP ↔ Manager ↔ Core

## Example: SubscriptionHandler Refactoring

**Stats:**
- Files modified: 2 (subscription.py, subscription_manager.py)
- Lines added to SubscriptionManager: ~131 (SubscriptionWithDiffs + 2 methods)
- Lines removed from handlers: ~80 (business logic)
- Type errors: 0
- Unit tests created: 16 tests in `tests/test_subscription_manager.py`
- Integration tests: 6/6 passing (test_property_notifications.py)
- Pattern established: ✅ Ready for TrustHandler

**Files involved:**
- `actingweb/interface/subscription_manager.py` - Developer API extensions
- `actingweb/handlers/subscription.py` - Refactored handlers
- `tests/test_subscription_manager.py` - Unit tests for new methods

**Verification:**
```bash
# Type checking
poetry run pyright actingweb/handlers/subscription.py
poetry run pyright actingweb/interface/subscription_manager.py
# Output: 0 errors, 0 warnings, 0 informations

# Unit tests
poetry run pytest tests/test_subscription_manager.py -v --no-cov
# Output: 16 passed in 0.32s

# Integration tests
poetry run pytest tests/integration/test_property_notifications.py -v
# Output: 6 passed
```

## Example: TrustHandler Refactoring

**Stats:**
- Files modified: 2 (trust.py, trust_manager.py)
- Lines added to TrustManager: ~103 (4 new methods including property)
- Lines removed from handlers: ~60 (business logic)
- Type errors: 0
- Unit tests created: 24 tests in `tests/test_trust_manager_new_methods.py`
- Integration tests: 7/7 passing (test_trust_lifecycle.py)
- Pattern validated: ✅ Ready for PropertiesHandler

**Files involved:**
- `actingweb/interface/trust_manager.py` - Developer API extensions
- `actingweb/handlers/trust.py` - Refactored handlers
- `tests/test_trust_manager_new_methods.py` - Unit tests for new methods

**Verification:**
```bash
# Type checking
poetry run pyright actingweb/handlers/trust.py
poetry run pyright actingweb/interface/trust_manager.py
# Output: 0 errors

# Unit tests
poetry run pytest tests/test_trust_manager_new_methods.py -v --no-cov
# Output: 24 passed in 0.37s

# Integration tests
poetry run pytest tests/integration/test_trust_lifecycle.py -v
# Output: 7 passed
```

## Conclusion

This pattern provides a systematic approach to refactoring handlers and extending the developer API. By following these 5 steps (including comprehensive unit testing), we can incrementally migrate handlers to use the developer API while maintaining type safety and test coverage.

**Pattern Status:**
- ✅ **SubscriptionHandler** - Complete (16 unit tests, 6 integration tests)
- ✅ **TrustHandler** - Complete (24 unit tests, 7 integration tests)
- ⏸️ **PropertiesHandler** - Next target (~58 occurrences to review)

**Key Success Factors:**
1. **Unit tests are mandatory** - They catch issues early and document API usage
2. **Type safety prevents regressions** - 0 errors maintained throughout
3. **Integration tests validate behavior** - End-to-end HTTP testing ensures no breakage
4. **Incremental approach works** - One handler at a time, validate before moving forward
5. **Pattern is reusable** - Same 5 steps apply to every handler

The pattern has been successfully applied to two handlers (Subscription + Trust) with 100% test pass rates. Ready to continue with PropertiesHandler and remaining handlers.
