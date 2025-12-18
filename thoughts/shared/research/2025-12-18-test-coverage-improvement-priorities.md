---
date: 2025-12-18T08:03:16Z
researcher: Claude
git_commit: 619d025f117bad951ade42b74f2d15d9cdb6b800
branch: permission_merge_fix
repository: actingweb
topic: "Test Coverage Improvement Priorities After Handler Refactoring"
tags: [research, testing, coverage, refactoring, unit-tests, integration-tests]
status: complete
last_updated: 2025-12-18
last_updated_by: Claude
---

# Research: Test Coverage Improvement Priorities After Handler Refactoring

**Date**: 2025-12-18T08:03:16Z
**Researcher**: Claude
**Git Commit**: 619d025f117bad951ade42b74f2d15d9cdb6b800
**Branch**: permission_merge_fix
**Repository**: actingweb

## Research Question

Identify the most useful ways to increase test coverage after the major refactoring into the new architecture (unified handler architecture with developer API).

## Summary

After analyzing the current test suite (879 tests across 60 files), the handler refactoring completion documents, and the actingweb_mcp test requirements, I've identified that:

1. **The actingweb_mcp requirements are FULLY COVERED** - All five critical areas (property lists, trust permissions, OAuth2 client manager, trust type registry, runtime context) have comprehensive tests.

2. **Major gaps exist in core module unit tests** - Several fundamental modules have NO dedicated unit tests and rely solely on indirect integration test coverage.

3. **Interface components lack dedicated tests** - The new architecture's framework integrations (Flask, FastAPI, base) have no unit tests.

4. **Some handlers have no direct tests** - Despite refactoring, several handlers lack direct test coverage.

## Detailed Findings

### Current Test Suite Metrics

| Category | Count | Status |
|----------|-------|--------|
| Total Test Files | 60 | - |
| Unit Test Files | 30 | - |
| Integration Test Files | 27 | - |
| Total Test Functions | ~879 | - |
| Type Safety | 0 errors | Pyright passing |
| Test Pass Rate | 100% | All tests passing |

### Test Coverage by Component Category

#### 1. Core Modules (`actingweb/*.py`) - MAJOR GAPS

| Module | Lines | Dedicated Tests | Priority |
|--------|-------|-----------------|----------|
| `auth.py` | ~940 | **NONE** | **CRITICAL** |
| `trust.py` | ~500 | **NONE** | **HIGH** |
| `subscription.py` | ~200 | **NONE** | **HIGH** |
| `aw_proxy.py` | ~250 | **NONE** | **MEDIUM** |
| `attribute.py` | ~150 | **NONE** | **MEDIUM** |
| `peertrustee.py` | ~80 | **NONE** | **MEDIUM** |
| `property.py` | ~150 | Partial | LOW |
| `actor.py` | ~350 | Partial (19 tests) | LOW |
| `config.py` | ~300 | Good (17 tests) | DONE |

#### 2. Interface Components (`actingweb/interface/`) - SIGNIFICANT GAPS

| Component | Lines | Dedicated Tests | Priority |
|-----------|-------|-----------------|----------|
| `FlaskIntegration` | ~300 | **NONE** | **HIGH** |
| `BaseActingWebIntegration` | ~200 | **NONE** | **HIGH** |
| `ActingWebApp` | ~500 | **NONE** | **HIGH** |
| `FastAPIIntegration` | ~900 | Integration only | MEDIUM |
| `HookRegistry` (method/action) | ~650 | Indirect only | MEDIUM |
| `AuthenticatedViews` | ~200 | Good (16 tests) | DONE |
| `PropertyStore` | ~300 | Good (11 tests) | DONE |
| `SubscriptionManager` | ~400 | Good (27 tests) | DONE |
| `TrustManager` | ~400 | Good (36 tests) | DONE |

#### 3. Handlers (`actingweb/handlers/`) - SOME GAPS

| Handler | Lines | Direct Tests | Priority |
|---------|-------|--------------|----------|
| `callbacks.py` | ~200 | **NONE** | **MEDIUM** |
| `actions.py` | ~280 | **NONE** | **MEDIUM** |
| `methods.py` | ~300 | **NONE** | **MEDIUM** |
| `bot.py` | ~150 | **NONE** | **LOW** |
| `resources.py` | ~100 | **NONE** | **LOW** |
| `email_verification.py` | ~100 | **NONE** | **LOW** |
| `mcp.py` | ~500 | Good (multiple files) | DONE |
| `devtest.py` | ~300 | Good (41 tests) | DONE |

#### 4. actingweb_mcp Requirements - FULLY COVERED

All areas specified in `thoughts/shared/test-requirements-from-actingweb-mcp.md` are now covered:

| Requirement | Test File | Tests |
|-------------|-----------|-------|
| Property Lists Advanced | `tests/integration/test_property_lists_advanced.py` | 23 |
| Trust Permissions Patterns | `tests/integration/test_trust_permissions_patterns.py` | 14 |
| Trust Permissions Unit | `tests/test_trust_permissions_unit.py` | 15 |
| OAuth2 Client Manager | `tests/integration/test_oauth2_client_manager.py` | 29 |
| Trust Type Registry | `tests/test_trust_type_registry.py` | 12 |
| Runtime Context | `tests/integration/test_runtime_context_advanced.py` | 20 |
| Trust-OAuth Integration | `tests/integration/test_trust_oauth_integration.py` | 16 |

### Incomplete/Placeholder Tests Found

| File | Issue | Count |
|------|-------|-------|
| `tests/test_oauth2_spa.py` | Empty `pass` implementations | 3 |
| `tests/integration/test_oauth2_security.py` | Config-dependent empty test | 1 |
| `tests/integration/test_property_list_notifications.py` | Phase 3 placeholders | 7 |
| `tests/integration/test_subscription_flow.py` | Conditional skips | 8 |

## Prioritized Recommendations

### Priority 1: Critical - Core Authentication Module (auth.py)

**Impact**: Highest - auth.py is 940 lines with zero unit tests

**Recommended Test File**: `tests/test_auth.py`

**Key Methods to Test**:
```python
# tests/test_auth.py - ~30 tests needed
class TestAuthClass:
    def test_check_authentication_with_basic_auth()
    def test_check_authentication_with_bearer_token()
    def test_check_authentication_with_oauth2_token()
    def test_check_authentication_with_spa_token()
    def test_check_token_auth_valid_token()
    def test_check_token_auth_expired_token()
    def test_check_token_auth_invalid_format()
    def test_check_authorisation_with_acl_access()
    def test_check_authorisation_denied()
    def test_looks_like_oauth2_token_detection()
    def test_check_oauth2_token_validation()
    def test_check_spa_token_validation()

class TestAuthHelperFunctions:
    def test_add_auth_response_sets_headers()
    def test_check_and_verify_auth_complete_flow()
    def test_check_and_verify_auth_async_complete_flow()
```

**Effort**: ~2 sessions (400 lines)

### Priority 2: High - Core Trust/Subscription Modules

**Impact**: High - These are fundamental ActingWeb operations

**Recommended Test Files**:

```python
# tests/test_trust_core.py - ~20 tests needed
class TestTrustClass:
    def test_trust_get_returns_relationship()
    def test_trust_get_nonexistent_returns_none()
    def test_trust_create_establishes_relationship()
    def test_trust_delete_removes_relationship()
    def test_trust_modify_updates_relationship()
    def test_canonical_connection_method_normalization()

# tests/test_subscription_core.py - ~15 tests needed
class TestSubscriptionClass:
    def test_subscription_get_returns_subscription()
    def test_subscription_create_establishes_subscription()
    def test_subscription_delete_removes_subscription()
    def test_subscription_increase_seq()
    def test_subscription_add_diff()
    def test_subscription_clear_diffs()
```

**Effort**: ~1.5 sessions (300 lines)

### Priority 3: High - Framework Integration Unit Tests

**Impact**: High - Validates the new architecture's framework layer

**Recommended Test Files**:

```python
# tests/test_base_integration.py - ~15 tests needed
class TestBaseActingWebIntegration:
    def test_get_base_routes_returns_all_routes()
    def test_handler_map_contains_all_handlers()
    def test_get_handler_class_for_properties()
    def test_get_handler_class_for_trust()
    def test_get_handler_class_for_subscription()
    def test_get_oauth_discovery_metadata()
    def test_normalize_http_method()
    def test_build_error_response()
    def test_build_success_response()

# tests/test_flask_integration.py - ~10 tests needed
class TestFlaskIntegration:
    def test_route_registration()
    def test_request_handling_adaptation()
    def test_response_building()

# tests/test_actingweb_app.py - ~20 tests needed
class TestActingWebAppConfiguration:
    def test_with_oauth_configuration()
    def test_with_web_ui_enable_disable()
    def test_with_devtest_enable_disable()
    def test_with_mcp_enable_disable()
    def test_with_bot_configuration()
    def test_add_actor_type()
    def test_with_custom_trust_types()
    def test_get_config_returns_valid_config()
    def test_invalid_configuration_raises_error()
```

**Effort**: ~2 sessions (400 lines)

### Priority 4: Medium - AwProxy and Attribute Modules

**Impact**: Medium - Important for peer communication and storage

**Recommended Test Files**:

```python
# tests/test_aw_proxy.py - ~15 tests needed
class TestAwProxy:
    def test_get_resource_sync()
    def test_create_resource_sync()
    def test_change_resource_sync()
    def test_delete_resource_sync()
    def test_get_resource_async()
    def test_create_resource_async()
    def test_error_handling_on_connection_failure()
    def test_authentication_header_setting()

# tests/test_attribute.py - ~10 tests needed
class TestInternalStore:
    def test_prop_notation_access()
    def test_attribute_storage_and_retrieval()
    def test_attribute_deletion()
```

**Effort**: ~1 session (200 lines)

### Priority 5: Medium - Handler Direct Tests

**Impact**: Medium - Validates HTTP behavior for specific endpoints

**Recommended Test Files**:

```python
# tests/test_callbacks_handler.py - ~8 tests needed
class TestCallbacksHandler:
    def test_callback_invocation()
    def test_callback_with_subscription()
    def test_callback_without_subscription()
    def test_callback_permission_check()

# tests/test_actions_handler.py - ~8 tests needed
class TestActionsHandler:
    def test_action_hook_execution()
    def test_action_permission_check()
    def test_action_with_data()
    def test_unknown_action_returns_404()

# tests/test_methods_handler.py - ~8 tests needed
class TestMethodsHandler:
    def test_method_hook_execution()
    def test_method_permission_check()
    def test_method_with_params()
    def test_unknown_method_returns_404()
```

**Effort**: ~1 session (200 lines)

### Priority 6: Low - Complete Placeholder Tests

**Impact**: Low - These are edge cases or config-specific

**Files to Complete**:
- `tests/test_oauth2_spa.py` - Implement 3 token delivery mode tests
- `tests/integration/test_oauth2_security.py` - Provider ID mode test
- `tests/integration/test_property_list_notifications.py` - 7 Phase 3 tests

**Effort**: ~0.5 sessions (100 lines)

## Implementation Plan

### Phase 1: Critical Coverage (Priority 1)
- [ ] Create `tests/test_auth.py` with ~30 unit tests
- [ ] Achieve >60% coverage on `auth.py`

### Phase 2: Core Module Coverage (Priority 2)
- [ ] Create `tests/test_trust_core.py` with ~20 unit tests
- [ ] Create `tests/test_subscription_core.py` with ~15 unit tests

### Phase 3: Framework Integration Coverage (Priority 3)
- [ ] Create `tests/test_base_integration.py` with ~15 unit tests
- [ ] Create `tests/test_flask_integration.py` with ~10 unit tests
- [ ] Create `tests/test_actingweb_app.py` with ~20 unit tests

### Phase 4: Secondary Module Coverage (Priority 4)
- [ ] Create `tests/test_aw_proxy.py` with ~15 unit tests
- [ ] Create `tests/test_attribute.py` with ~10 unit tests

### Phase 5: Handler Coverage (Priority 5)
- [ ] Create `tests/test_callbacks_handler.py` with ~8 unit tests
- [ ] Create `tests/test_actions_handler.py` with ~8 unit tests
- [ ] Create `tests/test_methods_handler.py` with ~8 unit tests

### Phase 6: Cleanup (Priority 6)
- [ ] Complete placeholder tests in existing files

## Expected Outcomes

| Metric | Current | After Implementation |
|--------|---------|---------------------|
| Total Tests | ~879 | ~1,050 (+171) |
| Core Module Coverage | ~40% | ~75% |
| Interface Component Coverage | ~60% | ~85% |
| Handler Direct Coverage | ~50% | ~80% |
| Placeholder Tests | 11 | 0 |

## Code References

### Files Needing Tests (By Priority)

**Critical**:
- `actingweb/auth.py` - Authentication/authorization (940 lines, 0 tests)

**High**:
- `actingweb/trust.py` - Trust relationships (500 lines, 0 unit tests)
- `actingweb/subscription.py` - Subscriptions (200 lines, 0 unit tests)
- `actingweb/interface/integrations/flask_integration.py` - Flask routes (300 lines, 0 tests)
- `actingweb/interface/integrations/base_integration.py` - Base routes (200 lines, 0 tests)
- `actingweb/interface/app.py` - App configuration (500 lines, 0 tests)

**Medium**:
- `actingweb/aw_proxy.py` - Peer communication (250 lines, 0 tests)
- `actingweb/attribute.py` - Internal storage (150 lines, 0 tests)
- `actingweb/handlers/callbacks.py` - Callback handling (200 lines, 0 direct tests)
- `actingweb/handlers/actions.py` - Action handling (280 lines, 0 direct tests)
- `actingweb/handlers/methods.py` - Method handling (300 lines, 0 direct tests)

### Files with Good Coverage (Reference)

- `tests/test_authenticated_views.py` - 16 tests
- `tests/test_subscription_manager.py` - 27 tests
- `tests/test_trust_manager_new_methods.py` - 29 tests
- `tests/integration/test_oauth2_client_manager.py` - 29 tests
- `tests/integration/test_property_lists_advanced.py` - 23 tests

## Historical Context (from thoughts/)

The handler refactoring initiative (`thoughts/shared/completed/2025-12-14-handler-refactoring-initiative-complete.md`) established a clean four-tier architecture:

```
HTTP Handler (HTTP concerns only)
    ↓
Developer API (business logic)
    ↓
Core Actor (data access)
    ↓
Database
```

This refactoring:
- Extended developer API by +382 lines
- Created 46 unit tests for new methods
- Maintained 79+ integration tests
- Achieved 0 type errors

The current test gaps are primarily in the **HTTP Handler** and **Core Actor** tiers, while the **Developer API** tier has excellent coverage.

## Related Research

- `thoughts/shared/completed/2025-12-14-handler-refactoring-initiative-complete.md` - Refactoring completion
- `thoughts/shared/test-requirements-from-actingweb-mcp.md` - MCP test requirements (now covered)
- `thoughts/shared/patterns/handler-refactoring-pattern.md` - Testing guidelines

## Open Questions

1. **Should we add code coverage metrics to CI?** - Currently no coverage reporting in CI pipeline
2. **Should Flask integration tests mirror FastAPI tests?** - FastAPI has integration coverage via test harness, Flask does not
3. **Is the current `pytest.skip()` pattern acceptable?** - 9 conditional skips in integration tests may hide failures

## Conclusion

The most impactful test coverage improvements would be:

1. **auth.py unit tests** - Single largest untested module (940 lines)
2. **trust.py and subscription.py unit tests** - Core ActingWeb functionality
3. **Framework integration tests** - Validates new architecture layer

These three areas would provide the highest ROI for test coverage investment after the handler refactoring.
