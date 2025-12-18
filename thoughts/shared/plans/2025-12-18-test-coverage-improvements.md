# Test Coverage Improvements Implementation Plan

## Overview

This plan implements the test coverage improvements identified in `thoughts/shared/research/2025-12-18-test-coverage-improvement-priorities.md`. The goal is to add approximately 171 new unit tests across 11 new test files, targeting modules with zero or minimal unit test coverage.

## Current State Analysis

### Current Test Suite
- Total Test Files: 60
- Total Test Functions: ~879
- All tests passing (100%)
- Pyright: 0 errors

### Key Gaps Identified
- `auth.py`: 940 lines, 0 unit tests
- `trust.py`: 332 lines, 0 unit tests
- `subscription.py`: 214 lines, 0 unit tests
- Interface components (`app.py`, `base_integration.py`, `flask_integration.py`): 0 unit tests
- `aw_proxy.py`: 670 lines, 0 unit tests
- `attribute.py`: 189 lines, 0 unit tests

## Desired End State

After implementation:
- Total Tests: ~1,050 (+171)
- Core Module Coverage: ~75% (up from ~40%)
- Interface Component Coverage: ~85% (up from ~60%)
- All 11 new test files passing with pyright

### Verification
```bash
poetry run pytest tests/test_auth.py tests/test_trust_core.py tests/test_subscription_core.py tests/test_base_integration.py tests/test_flask_integration.py tests/test_actingweb_app.py tests/test_aw_proxy.py tests/test_attribute.py -v
poetry run pyright tests/
```

## What We're NOT Doing

- Integration tests (already covered well)
- Database layer tests (tested via integration)
- Handler tests (deferred to Phase 5, lower priority)

## Completed: Code Coverage CI Integration

Code coverage CI integration has been implemented:

- **Codecov Integration**: Added `codecov/codecov-action@v4` to `.github/workflows/tests.yml`
- **Codecov Configuration**: Created `codecov.yml` with:
  - Project coverage target: 50%
  - Patch coverage target: 60% (new code should have higher coverage)
  - Component tracking for core, interface, handlers, and oauth modules
  - Ignored paths for tests, deprecated code, and docs
- **README Badges**: Added badges for Tests, Coverage, PyPI, and Documentation
- **Coverage Config**: Enhanced `pyproject.toml` with:
  - Branch coverage enabled
  - Excluded patterns for TYPE_CHECKING, NotImplementedError, etc.
  - Removed `--cov-fail-under` from default pytest options (Codecov handles thresholds)

**Setup Required**: Repository owner needs to:
1. Sign up at [codecov.io](https://codecov.io) and add the repository
2. Add `CODECOV_TOKEN` secret to GitHub repository settings

## Implementation Approach

All tests will use `unittest.mock` to mock database and external dependencies. Each test file follows the established pattern from `tests/test_actor.py` and `tests/test_config.py`:
- Class-based test organization
- Descriptive test method names
- Type hints where applicable
- Comprehensive docstrings

---

## Phase 1: Critical - Authentication Module (auth.py)

### Overview
Create comprehensive unit tests for the largest untested module (940 lines).

### Changes Required

#### 1. Create `tests/test_auth.py`

**File**: `tests/test_auth.py`
**Tests**: ~30

```python
# Key test classes to implement:

class TestAuthClassInitialization:
    """Test Auth class initialization."""
    def test_auth_init_with_valid_actor_id()
    def test_auth_init_with_nonexistent_actor()
    def test_auth_init_with_basic_type()
    def test_auth_init_default_response_values()
    def test_auth_init_default_acl_values()

class TestBasicAuthentication:
    """Test basic auth methods."""
    def test_check_basic_auth_creator_success()
    def test_check_basic_auth_wrong_username()
    def test_check_basic_auth_wrong_password()
    def test_check_basic_auth_missing_header()
    def test_check_basic_auth_non_basic_header()

class TestTokenAuthentication:
    """Test token/bearer auth methods."""
    def test_check_token_auth_with_valid_bearer()
    def test_check_token_auth_missing_header()
    def test_check_token_auth_invalid_format()
    def test_check_token_auth_expired_token()
    def test_check_token_auth_with_trustee_passphrase()

class TestOAuth2Authentication:
    """Test OAuth2-specific methods."""
    def test_looks_like_oauth2_token_hex_trust_secret()
    def test_looks_like_oauth2_token_github_prefix()
    def test_looks_like_oauth2_token_jwt_format()
    def test_looks_like_oauth2_token_short_token()
    def test_looks_like_oauth2_token_long_token()
    def test_check_oauth2_token_disabled()
    def test_check_spa_token_valid()
    def test_check_spa_token_invalid()

class TestAuthorisation:
    """Test authorisation/ACL methods."""
    def test_check_authorisation_creator_access()
    def test_check_authorisation_peer_access()
    def test_check_authorisation_denied_unapproved()
    def test_check_authorisation_allows_trust_delete()
    def test_connection_hint_from_path_mcp()
    def test_connection_hint_from_path_trust()

class TestHelperFunctions:
    """Test module-level helper functions."""
    def test_add_auth_response_sets_headers()
    def test_add_auth_response_handles_redirect()
    def test_check_and_verify_auth_success()
    def test_check_and_verify_auth_actor_not_found()
```

### Success Criteria

#### Automated Verification:
- [ ] Tests pass: `poetry run pytest tests/test_auth.py -v`
- [ ] Type checking passes: `poetry run pyright tests/test_auth.py`
- [ ] Linting passes: `poetry run ruff check tests/test_auth.py`

#### Manual Verification:
- [ ] Test count is approximately 30
- [ ] All Auth class methods have at least one test
- [ ] Edge cases for token detection are covered

---

## Phase 2: High - Core Trust/Subscription Modules

### Overview
Add unit tests for fundamental ActingWeb operations.

### Changes Required

#### 1. Create `tests/test_trust_core.py`

**File**: `tests/test_trust_core.py`
**Tests**: ~20

```python
class TestCanonicalConnectionMethod:
    """Test canonical_connection_method function."""
    def test_oauth2_variants_normalize_to_oauth()
    def test_known_methods_pass_through()
    def test_unknown_methods_returned_as_is()
    def test_none_input_returns_none()
    def test_empty_string_returns_none()
    def test_non_string_input_returns_none()

class TestTrustClassInitialization:
    """Test Trust class initialization."""
    def test_trust_init_with_actor_and_peerid()
    def test_trust_init_with_actor_and_token()
    def test_trust_init_no_actor_id()
    def test_trust_init_no_peerid_or_token()

class TestTrustCRUD:
    """Test Trust CRUD operations."""
    def test_trust_get_returns_relationship()
    def test_trust_get_nonexistent_returns_none()
    def test_trust_create_establishes_relationship()
    def test_trust_delete_removes_relationship()
    def test_trust_modify_updates_fields()
    def test_trust_delete_cleans_oauth2_client()

class TestTrustsCollection:
    """Test Trusts collection class."""
    def test_trusts_fetch_retrieves_all()
    def test_trusts_delete_removes_all()
    def test_trusts_init_without_actor_id()
```

#### 2. Create `tests/test_subscription_core.py`

**File**: `tests/test_subscription_core.py`
**Tests**: ~15

```python
class TestSubscriptionClassInitialization:
    """Test Subscription class initialization."""
    def test_subscription_init_with_all_params()
    def test_subscription_init_minimal()
    def test_subscription_init_no_actor_id()

class TestSubscriptionCRUD:
    """Test Subscription CRUD operations."""
    def test_subscription_get_returns_subscription()
    def test_subscription_get_empty_when_not_found()
    def test_subscription_create_success()
    def test_subscription_create_fails_when_exists()
    def test_subscription_delete_success()

class TestSubscriptionDiffs:
    """Test diff management methods."""
    def test_subscription_increase_seq()
    def test_subscription_add_diff()
    def test_subscription_get_diff()
    def test_subscription_get_diffs()
    def test_subscription_clear_diff()
    def test_subscription_clear_diffs()

class TestSubscriptionsCollection:
    """Test Subscriptions collection class."""
    def test_subscriptions_fetch_retrieves_all()
    def test_subscriptions_delete_removes_all_with_diffs()
```

### Success Criteria

#### Automated Verification:
- [ ] Tests pass: `poetry run pytest tests/test_trust_core.py tests/test_subscription_core.py -v`
- [ ] Type checking passes: `poetry run pyright tests/test_trust_core.py tests/test_subscription_core.py`
- [ ] Linting passes: `poetry run ruff check tests/test_trust_core.py tests/test_subscription_core.py`

---

## Phase 3: High - Framework Integration Tests

### Overview
Add unit tests for the new architecture's interface layer.

### Changes Required

#### 1. Create `tests/test_base_integration.py`

**File**: `tests/test_base_integration.py`
**Tests**: ~15

```python
class TestBaseActingWebIntegrationInit:
    """Test initialization."""
    def test_init_with_actingweb_app()

class TestGetHandlerClass:
    """Test handler selection logic."""
    def test_get_handler_class_root()
    def test_get_handler_class_meta()
    def test_get_handler_class_properties()
    def test_get_handler_class_properties_metadata()
    def test_get_handler_class_properties_items()
    def test_get_handler_class_trust()
    def test_get_handler_class_subscriptions()

class TestTrustHandlerSelection:
    """Test trust handler selection."""
    def test_trust_root_handler()
    def test_trust_relationship_handler()
    def test_trust_peer_handler()
    def test_trust_permissions_handler()
    def test_trust_shared_properties_handler()
    def test_trust_method_override_handling()

class TestSubscriptionHandlerSelection:
    """Test subscription handler selection."""
    def test_subscription_root_handler()
    def test_subscription_relationship_handler()
    def test_subscription_handler()
    def test_subscription_diff_handler()

class TestStaticMethods:
    """Test static utility methods."""
    def test_get_oauth_discovery_metadata()
    def test_normalize_http_method()
    def test_build_error_response()
    def test_build_success_response()
```

#### 2. Create `tests/test_flask_integration.py`

**File**: `tests/test_flask_integration.py`
**Tests**: ~10

```python
class TestFlaskIntegrationInit:
    """Test Flask integration initialization."""
    def test_init_with_flask_app()
    def test_inherits_base_integration()

class TestNormalizeRequest:
    """Test request normalization."""
    def test_normalize_request_basic()
    def test_normalize_request_with_cookies()
    def test_normalize_request_oauth_cookie_to_bearer()
    def test_normalize_request_form_data()

class TestCreateFlaskResponse:
    """Test response creation."""
    def test_create_response_basic()
    def test_create_response_redirect()
    def test_create_response_with_cookies()
```

#### 3. Create `tests/test_actingweb_app.py`

**File**: `tests/test_actingweb_app.py`
**Tests**: ~20

```python
class TestActingWebAppInit:
    """Test ActingWebApp initialization."""
    def test_init_minimal()
    def test_init_with_all_params()
    def test_default_values()

class TestOAuthConfiguration:
    """Test OAuth configuration."""
    def test_with_oauth_sets_config()
    def test_with_oauth_sets_www_auth()
    def test_with_oauth_applies_to_existing_config()

class TestFeatureToggles:
    """Test feature enable/disable."""
    def test_with_web_ui_enable()
    def test_with_web_ui_disable()
    def test_with_devtest_enable()
    def test_with_devtest_disable()
    def test_with_mcp_enable()
    def test_with_mcp_disable()
    def test_with_unique_creator()
    def test_with_email_as_creator()

class TestBotConfiguration:
    """Test bot configuration."""
    def test_with_bot_sets_config()
    def test_with_bot_from_env()

class TestActorTypes:
    """Test actor type management."""
    def test_add_actor_type()
    def test_default_myself_actor_type()

class TestServiceRegistry:
    """Test service registry."""
    def test_get_service_registry()
    def test_add_service()
    def test_add_dropbox()
    def test_add_gmail()
    def test_add_github()
    def test_add_box()

class TestHookDecorators:
    """Test hook registration decorators."""
    def test_property_hook_decorator()
    def test_callback_hook_decorator()
    def test_app_callback_hook_decorator()
    def test_lifecycle_hook_decorator()
    def test_method_hook_decorator()
    def test_action_hook_decorator()

class TestGetConfig:
    """Test config retrieval."""
    def test_get_config_creates_config()
    def test_get_config_returns_same_instance()
    def test_get_config_adds_default_actor_type()
```

### Success Criteria

#### Automated Verification:
- [ ] Tests pass: `poetry run pytest tests/test_base_integration.py tests/test_flask_integration.py tests/test_actingweb_app.py -v`
- [ ] Type checking passes: `poetry run pyright tests/test_base_integration.py tests/test_flask_integration.py tests/test_actingweb_app.py`
- [ ] Linting passes: `poetry run ruff check tests/test_base_integration.py tests/test_flask_integration.py tests/test_actingweb_app.py`

---

## Phase 4: Medium - AwProxy and Attribute Modules

### Overview
Add unit tests for peer communication and internal storage.

### Changes Required

#### 1. Create `tests/test_aw_proxy.py`

**File**: `tests/test_aw_proxy.py`
**Tests**: ~15

```python
class TestAwProxyInit:
    """Test AwProxy initialization."""
    def test_init_with_trust_target()
    def test_init_with_peer_target()
    def test_init_with_peer_passphrase()

class TestSyncMethods:
    """Test synchronous HTTP methods."""
    def test_get_resource_success()
    def test_get_resource_no_path()
    def test_get_resource_no_trust()
    def test_create_resource_success()
    def test_change_resource_success()
    def test_delete_resource_success()
    def test_retry_with_basic_auth()
    def test_connection_error_handling()

class TestAsyncMethods:
    """Test asynchronous HTTP methods."""
    def test_get_resource_async_success()
    def test_create_resource_async_success()
    def test_change_resource_async_success()
    def test_delete_resource_async_success()
    def test_async_timeout_handling()
    def test_async_connection_error_handling()
```

#### 2. Create `tests/test_attribute.py`

**File**: `tests/test_attribute.py`
**Tests**: ~10

```python
class TestInternalStore:
    """Test InternalStore class."""
    def test_init_loads_bucket()
    def test_prop_notation_get()
    def test_prop_notation_set()
    def test_item_notation_get()
    def test_item_notation_set()
    def test_delete_attribute()

class TestAttributes:
    """Test Attributes class."""
    def test_get_bucket()
    def test_get_attr()
    def test_set_attr()
    def test_delete_attr()
    def test_delete_bucket()

class TestBuckets:
    """Test Buckets collection class."""
    def test_fetch()
    def test_fetch_timestamps()
    def test_delete()
```

### Success Criteria

#### Automated Verification:
- [ ] Tests pass: `poetry run pytest tests/test_aw_proxy.py tests/test_attribute.py -v`
- [ ] Type checking passes: `poetry run pyright tests/test_aw_proxy.py tests/test_attribute.py`
- [ ] Linting passes: `poetry run ruff check tests/test_aw_proxy.py tests/test_attribute.py`

---

## Phase 5: Handler Direct Tests (Deferred)

### Overview
Handler tests are lower priority since handlers are tested via integration tests. This phase is documented but deferred.

### Files to Create (Future)
- `tests/test_callbacks_handler.py` (~8 tests)
- `tests/test_actions_handler.py` (~8 tests)
- `tests/test_methods_handler.py` (~8 tests)

---

## Phase 6: Cleanup - Complete Placeholder Tests (Deferred)

### Overview
Complete placeholder tests in existing files. This phase is documented but deferred.

### Files to Update
- `tests/test_oauth2_spa.py` - Implement 3 token delivery mode tests
- `tests/integration/test_oauth2_security.py` - Provider ID mode test
- `tests/integration/test_property_list_notifications.py` - 7 Phase 3 tests

---

## Testing Strategy

### Unit Tests
- Mock all database operations using `unittest.mock`
- Test each method's logic in isolation
- Cover edge cases and error conditions
- Use fixtures for common mock setups

### Test Organization
```text
tests/
├── test_auth.py              # Phase 1
├── test_trust_core.py        # Phase 2
├── test_subscription_core.py # Phase 2
├── test_base_integration.py  # Phase 3
├── test_flask_integration.py # Phase 3
├── test_actingweb_app.py     # Phase 3
├── test_aw_proxy.py          # Phase 4
└── test_attribute.py         # Phase 4
```

## References

- Original research: `thoughts/shared/research/2025-12-18-test-coverage-improvement-priorities.md`
- Test patterns: `tests/test_actor.py`, `tests/test_config.py`
- Handler refactoring: `thoughts/shared/completed/2025-12-14-handler-refactoring-initiative-complete.md`
