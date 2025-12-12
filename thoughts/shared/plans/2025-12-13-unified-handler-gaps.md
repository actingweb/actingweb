# Gap Implementation Plan: Unified Handler Architecture (Full Scope)

## Overview

This plan addresses ALL gaps between the research document (`2025-12-12-unified-handler-architecture.md`) and the implementation that was executed. This includes the full scope: tests, documentation restructuring, handler refactoring, and Flask/FastAPI code sharing.

## Gaps Identified

### Gap Category 1: Missing Unit Tests

| Test File | Purpose | Status |
|-----------|---------|--------|
| `tests/test_authenticated_views.py` | Test AuthenticatedActorView, permission enforcement | NOT CREATED |
| `tests/test_property_store_notifications.py` | Test register_diffs on PropertyStore operations | NOT CREATED |
| `tests/test_trust_manager_hooks.py` | Test lifecycle hook execution | NOT CREATED |
| `tests/test_property_list_notifications.py` | Test register_diffs on list operations | NOT CREATED |

### Gap Category 2: Missing Integration/HTTP API Tests

| Test File | Purpose | Status |
|-----------|---------|--------|
| `tests/integration/test_property_notifications.py` | Verify PUT/DELETE triggers subscription diffs | NOT CREATED |
| `tests/integration/test_trust_lifecycle.py` | Verify trust operations trigger lifecycle hooks | NOT CREATED |
| `tests/integration/test_authenticated_access.py` | Verify permission enforcement via HTTP | NOT CREATED |
| `tests/integration/test_property_list_notifications.py` | Verify list operations trigger diffs | NOT CREATED |
| `tests/integration/test_async_operations.py` | Verify async peer communication completes quickly | NOT CREATED |

### Gap Category 3: Documentation Not Restructured

Current state: 34 rst files in flat structure mixing audiences.
Target state: Four-audience organization as specified in research.

| New Structure | Purpose | Status |
|---------------|---------|--------|
| `docs/protocol/` | Protocol implementers | NOT CREATED |
| `docs/quickstart/` | App developers getting started | NOT CREATED |
| `docs/guides/` | App developers deep topics | NOT CREATED |
| `docs/sdk/` | SDK developers / advanced | NOT CREATED |
| `docs/reference/` | API reference | PARTIAL |
| `docs/contributing/` | Contributors | NOT CREATED |

### Gap Category 4: Handlers Not Refactored

| Handler File | Size | Business Logic to Extract | Status |
|--------------|------|--------------------------|--------|
| `properties.py` | 60KB | Permission checks, hooks, register_diffs | NOT REFACTORED |
| `trust.py` | 41KB | Lifecycle hooks, verification protocol | NOT REFACTORED |
| `subscription.py` | 15KB | Permission checks, diff management | NOT REFACTORED |
| `methods.py` | 12KB | Permission checks, hooks | NOT REFACTORED |
| `actions.py` | 11KB | Permission checks, hooks | NOT REFACTORED |
| `callbacks.py` | 7KB | Hook execution | NOT REFACTORED |

### Gap Category 5: Flask/FastAPI Code Not Shared

| File | Lines | Duplicate Code |
|------|-------|----------------|
| `flask_integration.py` | 1670 | ~90% shared logic |
| `fastapi_integration.py` | 2496 | ~90% shared logic |

Should extract to `base_integration.py` with framework-specific subclasses.

### Gap Category 6: Missing Async Variants in Actor Class

| Method | Async Variant Needed | Status |
|--------|---------------------|--------|
| `get_peer_info()` | `get_peer_info_async()` | NOT CREATED |
| `modify_trust_and_notify()` | `modify_trust_and_notify_async()` | NOT CREATED |
| `create_reciprocal_trust()` | `create_reciprocal_trust_async()` | NOT CREATED |
| `create_verified_trust()` | `create_verified_trust_async()` | NOT CREATED |
| `delete_reciprocal_trust()` | `delete_reciprocal_trust_async()` | NOT CREATED |
| `create_remote_subscription()` | `create_remote_subscription_async()` | NOT CREATED |
| `delete_remote_subscription()` | `delete_remote_subscription_async()` | NOT CREATED |
| `callback_subscription()` | `callback_subscription_async()` | NOT CREATED |

---

## Phase 1: Create Unit Tests

### 1.1 Create test_authenticated_views.py

**File**: `tests/test_authenticated_views.py`

Test cases:
- `test_as_peer_creates_authenticated_view`
- `test_as_client_creates_authenticated_view`
- `test_authenticated_property_read_checks_permission`
- `test_authenticated_property_write_checks_permission`
- `test_authenticated_property_delete_checks_permission`
- `test_permission_error_raised_when_denied`
- `test_owner_mode_has_no_permission_checks`
- `test_authenticated_view_filters_iterable_properties`
- `test_auth_context_accessor_id_returns_peer_or_client`
- `test_auth_context_is_peer_and_is_client_properties`

### 1.2 Create test_property_store_notifications.py

**File**: `tests/test_property_store_notifications.py`

Test cases:
- `test_setitem_calls_register_diffs`
- `test_delitem_calls_register_diffs`
- `test_set_calls_register_diffs`
- `test_delete_calls_register_diffs`
- `test_update_calls_register_diffs_for_each_key`
- `test_clear_calls_register_diffs`
- `test_set_without_notification_does_not_register_diff`
- `test_hook_executed_before_store`
- `test_hook_can_transform_value`
- `test_hook_can_reject_value_returning_none`

### 1.3 Create test_trust_manager_hooks.py

**File**: `tests/test_trust_manager_hooks.py`

Test cases:
- `test_approve_relationship_triggers_trust_approved_hook`
- `test_approve_relationship_hook_only_fires_when_both_approved`
- `test_delete_relationship_triggers_trust_deleted_hook`
- `test_delete_relationship_hook_fires_before_deletion`
- `test_hooks_not_called_when_no_hook_registry`
- `test_lifecycle_hook_receives_correct_parameters`

### 1.4 Create test_property_list_notifications.py

**File**: `tests/test_property_list_notifications.py`

Test cases:
- `test_append_calls_register_diffs`
- `test_insert_calls_register_diffs`
- `test_setitem_calls_register_diffs`
- `test_delitem_calls_register_diffs`
- `test_pop_calls_register_diffs`
- `test_clear_calls_register_diffs`
- `test_delete_calls_register_diffs`
- `test_delete_does_not_query_length_after_delete`
- `test_diff_contains_operation_type`

### Success Criteria Phase 1
- [x] All new unit tests pass
- [x] Type checking passes: `poetry run pyright tests/`
- [ ] Coverage for new classes > 80% (will improve with integration tests)

---

## Phase 2: Create Integration Tests

### 2.1 Create test_property_notifications.py

**File**: `tests/integration/test_property_notifications.py`

Test cases:
- `test_put_property_triggers_subscription_diff`
- `test_delete_property_triggers_subscription_diff`
- `test_post_properties_triggers_subscription_diff`
- `test_put_nested_property_triggers_diff`
- `test_diff_contains_correct_subtarget_and_blob`
- `test_multiple_puts_create_multiple_diffs`
- `test_diff_cleared_after_retrieval`

### 2.2 Create test_trust_lifecycle.py

**File**: `tests/integration/test_trust_lifecycle.py`

Test cases:
- `test_trust_approval_triggers_trust_approved_hook`
- `test_trust_deletion_triggers_trust_deleted_hook`
- `test_hook_receives_correct_peer_id_and_relationship`
- `test_hook_can_set_property_on_actor`
- `test_hook_not_triggered_on_partial_approval`

### 2.3 Create test_authenticated_access.py

**File**: `tests/integration/test_authenticated_access.py`

Test cases:
- `test_peer_without_write_permission_gets_403_on_put`
- `test_peer_without_read_permission_gets_403_on_get`
- `test_peer_with_write_permission_succeeds`
- `test_peer_can_only_read_permitted_properties`
- `test_get_properties_filters_to_accessible_only`
- `test_mcp_client_respects_trust_permissions`

### 2.4 Create test_property_list_notifications.py

**File**: `tests/integration/test_property_list_notifications.py`

Test cases:
- `test_list_add_triggers_diff`
- `test_list_update_triggers_diff`
- `test_list_delete_triggers_diff`
- `test_list_metadata_update_triggers_diff`
- `test_diff_format_for_list_add`
- `test_diff_format_for_list_update`
- `test_diff_format_for_list_delete`

### 2.5 Create test_async_operations.py

**File**: `tests/integration/test_async_operations.py`

Test cases:
- `test_trust_creation_to_peer_completes_within_timeout`
- `test_subscription_to_peer_completes_within_timeout`
- `test_trust_deletion_with_peer_notify_completes_within_timeout`
- `test_concurrent_requests_do_not_block`
- `test_two_actor_trust_handshake_completes`

### Success Criteria Phase 2
- [x] Property notification integration tests pass (7/7)
- [x] Core integration test infrastructure created
- [ ] All new integration tests pass (some need Phase 3/4 implementations)
- [ ] Existing tests still pass: `make test-integration`

---

## Phase 3: Add register_diffs to Property List Handlers

### 3.1 Update PropertyListItemsHandler.post()

**File**: `actingweb/handlers/properties.py`

Add `register_diffs` calls after successful add/update/delete operations.

### 3.2 Update PropertyMetadataHandler.put()

**File**: `actingweb/handlers/properties.py`

Add `register_diffs` call after metadata update.

### Success Criteria Phase 3
- [x] register_diffs added to PropertyListItemsHandler (add, update, delete actions)
- [x] register_diffs added to PropertyMetadataHandler (metadata updates)
- [x] Type checking passes: `poetry run pyright actingweb/handlers/properties.py`
- [ ] Integration tests for list notifications pass (requires full test suite run)

---

## Phase 4: Add Proper Async Variants to Actor Class

### 4.1 Add async methods to Actor class

**File**: `actingweb/actor.py`

Add these methods using `AwProxy` async methods:
- `get_peer_info_async()`
- `modify_trust_and_notify_async()`
- `create_reciprocal_trust_async()`
- `create_verified_trust_async()`
- `delete_reciprocal_trust_async()`
- `create_remote_subscription_async()`
- `delete_remote_subscription_async()`
- `callback_subscription_async()`

### 4.2 Update TrustManager async methods

**File**: `actingweb/interface/trust_manager.py`

Update async methods to use new Actor async methods instead of `run_in_executor`.

### 4.3 Add async methods to SubscriptionManager

**File**: `actingweb/interface/subscription_manager.py`

Add:
- `subscribe_to_peer_async()`
- `unsubscribe_async()`

### Success Criteria Phase 4
- [x] All 8 async methods added to Actor class
- [x] get_peer_info_async, modify_trust_and_notify_async, create_reciprocal_trust_async (use AwProxy)
- [x] create_verified_trust_async, delete_reciprocal_trust_async, create_remote_subscription_async, delete_remote_subscription_async, callback_subscription_async (use asyncio.to_thread)
- [x] Type checking passes: `poetry run pyright actingweb/actor.py` (0 errors)
- [ ] Async integration tests pass with timeouts (requires full test suite run)

---

## Phase 5: Extract Flask/FastAPI Shared Code

### 5.1 Create base_integration.py

**File**: `actingweb/interface/integrations/base_integration.py`

Extract shared logic:
- Handler dictionary definitions
- Handler selection logic
- Argument building logic
- Error handling patterns
- Template mappings
- Request normalization helpers
- Response building helpers

```python
class BaseActingWebIntegration:
    """Base class for framework integrations with shared handler logic."""

    # Shared handler mappings
    HANDLER_MAP = {
        "properties": {"handler": PropertiesHandler, "methods": ["get", "put", "post", "delete"]},
        "trust": {"handler": TrustHandler, "methods": ["get", "put", "post", "delete"]},
        # ... etc
    }

    def __init__(self, app: ActingWebApp):
        self.app = app
        self.config = app.get_config()
        self.hooks = getattr(self.config, "_hooks", None)

    def _build_handler_args(self, request, actor_id: str, path: str, name: str = "") -> dict:
        """Build arguments for handler invocation."""
        # Shared logic for building webobj, etc.
        pass

    def _invoke_handler(self, handler_class, method: str, actor_id: str, name: str = "") -> Any:
        """Invoke a handler method."""
        # Shared logic for handler invocation
        pass

    def _build_response(self, webobj) -> Any:
        """Build framework-specific response from webobj."""
        # Override in subclass
        raise NotImplementedError
```

### 5.2 Refactor flask_integration.py

**File**: `actingweb/interface/integrations/flask_integration.py`

Inherit from `BaseActingWebIntegration`, override only Flask-specific parts:
- Response building
- Request extraction
- Route registration

### 5.3 Refactor fastapi_integration.py

**File**: `actingweb/interface/integrations/fastapi_integration.py`

Inherit from `BaseActingWebIntegration`, override only FastAPI-specific parts:
- Async wrapper for sync handlers
- Response building
- Request extraction
- Route registration

### Success Criteria Phase 5
- [x] base_integration.py created with shared handler selection logic
- [x] Type checking passes: `poetry run pyright actingweb/interface/integrations/base_integration.py` (0 errors)
- [ ] Flask routes refactored to use base class (requires modifying flask_integration.py)
- [ ] FastAPI routes refactored to use base class (requires modifying fastapi_integration.py)
- [ ] All existing tests pass after integration

---

## Phase 6: Refactor ALL Handlers to Use Developer API

### 6.1 Refactor PropertiesHandler

**File**: `actingweb/handlers/properties.py` (60KB)

Methods to refactor:
- `get()` - Use `actor.properties[name]` or `auth_view.properties[name]`
- `put()` - Use `actor.properties[name] = value`
- `post()` - Use `actor.properties.update(data)`
- `delete()` - Use `del actor.properties[name]`
- `listall()` - Use `actor.properties.to_dict()`

Remove:
- `_check_property_permission()` - Handled by AuthenticatedPropertyStore
- Direct `register_diffs()` calls - Handled by PropertyStore
- Direct hook execution - Handled by PropertyStore

### 6.2 Refactor TrustHandler

**File**: `actingweb/handlers/trust.py` (41KB)

Methods to refactor:
- `get()` - Use `actor.trust.get_relationship(peer_id)`
- `put()` - Use `actor.trust.approve_relationship(peer_id)`
- `post()` - Use `actor.trust.create_relationship(peer_url)`
- `delete()` - Use `actor.trust.delete_relationship(peer_id)`

Remove:
- Direct lifecycle hook execution - Handled by TrustManager
- Manual `trust_approved`/`trust_deleted` hook calls

### 6.3 Refactor SubscriptionHandler

**File**: `actingweb/handlers/subscription.py` (15KB)

Methods to refactor:
- `get()` - Use `actor.subscriptions.get_subscription()`
- `post()` - Use `auth_view.subscriptions.create_local_subscription()`
- `delete()` - Use `actor.subscriptions.unsubscribe()`

### 6.4 Refactor MethodsHandler

**File**: `actingweb/handlers/methods.py` (12KB)

Methods to refactor:
- `post()` - Use `actor.methods.execute()` (via hooks)
- Permission checks via AuthenticatedActorView

### 6.5 Refactor ActionsHandler

**File**: `actingweb/handlers/actions.py` (11KB)

Methods to refactor:
- `post()` - Use `actor.actions.execute()` (via hooks)
- Permission checks via AuthenticatedActorView

### 6.6 Refactor CallbacksHandler

**File**: `actingweb/handlers/callbacks.py` (7KB)

Methods to refactor:
- `post()` - Use hook registry directly
- App-level callbacks via `app_callback_hook`

### Success Criteria Phase 6
- [ ] All handlers use developer API
- [ ] No direct `register_diffs()` calls in handlers (except where needed)
- [ ] No direct lifecycle hook calls in handlers
- [ ] Permission checks delegated to AuthenticatedActorView
- [ ] All integration tests pass
- [ ] HTTP API contract unchanged (same responses)

---

## Phase 7: Restructure Documentation

### 7.1 Create new directory structure

```
docs/
├── index.rst                    # Landing page with audience selector
│
├── protocol/                    # Audience: Protocol Implementers
│   ├── index.rst
│   ├── actingweb-spec.rst      # Move from docs/actingweb-spec.rst
│   └── protocol-overview.rst   # Extract from overview.rst
│
├── quickstart/                  # Audience: App Developers (Flask/FastAPI)
│   ├── index.rst
│   ├── overview.rst            # Refactor from docs/overview.rst
│   ├── getting-started.rst     # Move from docs/getting-started.rst
│   ├── local-dev-setup.rst     # Move from docs/local-dev-setup.rst
│   ├── configuration.rst       # Move from docs/configuration.rst
│   └── deployment.rst          # Move from docs/deployment.rst
│
├── guides/                      # Audience: App Developers (deeper topics)
│   ├── index.rst
│   ├── authentication.rst      # Consolidate auth docs
│   ├── oauth2-setup.rst        # From oauth2-client-management.rst
│   ├── spa-authentication.rst  # Move from docs/spa-authentication.rst
│   ├── trust-relationships.rst # From developers/trust-manager.rst
│   ├── subscriptions.rst       # From developers/subscriptions.rst
│   ├── property-lists.rst      # From developers/property-lists.rst
│   ├── hooks.rst               # From developers/hooks.rst
│   ├── mcp-applications.rst    # Move from docs/mcp-applications.rst
│   ├── mcp-quickstart.rst      # Move from docs/mcp-quickstart.rst
│   ├── web-ui.rst              # From www-handler-templates.rst
│   ├── service-integration.rst # Move from docs/service-integration.rst
│   └── troubleshooting.rst     # Move from docs/troubleshooting.rst
│
├── sdk/                         # Audience: SDK Developers (advanced)
│   ├── index.rst
│   ├── developer-api.rst       # NEW: ActorInterface, managers
│   ├── authenticated-views.rst # NEW: as_peer, as_client, permissions
│   ├── custom-framework.rst    # NEW: Using with Django, etc.
│   ├── handler-architecture.rst # NEW: How handlers work
│   ├── async-operations.rst    # NEW: Async peer communication
│   ├── advanced-topics.rst     # From developers/advanced-topics.rst
│   └── attributes-buckets.rst  # From developers/attributes-and-buckets.rst
│
├── reference/                   # API Reference (all audiences)
│   ├── index.rst
│   ├── interface-api.rst       # Expand existing
│   ├── hooks-reference.rst     # Move from docs/hooks-reference.rst
│   ├── handlers.rst            # From actingweb.handlers.rst
│   ├── config-options.rst      # Extract from configuration.rst
│   ├── routing-overview.rst    # Move from docs/routing-overview.rst
│   └── security.rst            # From security-cheatsheet.rst
│
├── migration/                   # Migration guides
│   ├── index.rst
│   ├── v3.1.rst                # From migration-v3.1.rst
│   └── common-pitfalls.rst     # From common-pitfalls.rst
│
└── contributing/                # Audience: Contributors
    ├── index.rst
    ├── architecture.rst        # NEW: Codebase overview
    ├── testing.rst             # Move from docs/testing.rst
    └── style-guide.rst         # NEW: Code style
```

### 7.2 Create new documentation files

**New files to create**:
1. `docs/sdk/developer-api.rst` - ActorInterface, PropertyStore, TrustManager, SubscriptionManager
2. `docs/sdk/authenticated-views.rst` - as_peer(), as_client(), AuthenticatedActorView, permission enforcement
3. `docs/sdk/custom-framework.rst` - AWWebObj, handler invocation, Django/Starlette examples
4. `docs/sdk/handler-architecture.rst` - How handlers work, refactoring guide
5. `docs/sdk/async-operations.rst` - Async variants, AwProxy async methods
6. `docs/contributing/architecture.rst` - Codebase overview, module responsibilities
7. `docs/contributing/style-guide.rst` - Code style, type annotations, testing conventions

### 7.3 Move and refactor existing files

Move files to new locations per structure above. Update cross-references.

### 7.4 Update index.rst with audience selector

Create landing page that directs users to appropriate section based on their role:
- "I want to build an app with ActingWeb" → quickstart/
- "I want to understand the ActingWeb protocol" → protocol/
- "I want to extend ActingWeb or use with other frameworks" → sdk/
- "I want to contribute to ActingWeb" → contributing/

### 7.5 Update CLAUDE.md

Expand documentation with comprehensive examples for:
- All three access modes (Owner, Peer, Client)
- Handler integration patterns
- Permission evaluation
- Subscription notifications
- Hook execution
- Async operations

### Success Criteria Phase 7
- [ ] Documentation builds: `cd docs && make html`
- [ ] No broken links (test with `sphinx-build -b linkcheck`)
- [ ] All code examples are syntactically correct
- [ ] Each audience has clear path through docs
- [ ] Cross-references updated

---

## Implementation Order

1. **Phase 1**: Unit tests (establishes test coverage for existing implementation)
2. **Phase 2**: Integration tests (validates end-to-end behavior)
3. **Phase 3**: Handler register_diffs (fixes property list gap)
4. **Phase 4**: Async variants (enables proper async in handlers)
5. **Phase 5**: Flask/FastAPI code sharing (reduces duplication before handler refactor)
6. **Phase 6**: Handler refactoring (all handlers use developer API)
7. **Phase 7**: Documentation restructuring (captures new architecture)

## Dependencies

- Phase 6 depends on Phase 4 (async variants needed for handlers)
- Phase 6 depends on Phase 5 (shared code simplifies handler changes)
- Phase 7 should be done after Phase 6 (documents final architecture)

## Estimated Effort

| Phase | Estimated Lines | Complexity | Duration |
|-------|-----------------|------------|----------|
| Phase 1 | ~500 lines | Medium | 1 session |
| Phase 2 | ~600 lines | Medium | 1 session |
| Phase 3 | ~100 lines | Low | 0.5 session |
| Phase 4 | ~400 lines | High | 1 session |
| Phase 5 | ~800 lines | High | 2 sessions |
| Phase 6 | ~2000 lines (mostly deletions) | High | 3 sessions |
| Phase 7 | ~3000 lines docs | Medium | 2 sessions |

**Total**: ~7400 lines, ~10.5 sessions

## Risk Mitigation

### Handler Refactoring Risks

1. **HTTP API contract changes**: Run full integration test suite after each handler
2. **Edge cases in permission logic**: Comprehensive unit tests before refactoring
3. **Performance regression**: Profile before/after for key operations

### Documentation Risks

1. **Broken cross-references**: Use Sphinx linkcheck
2. **Missing content during move**: Create mapping spreadsheet tracking all files
3. **Audience confusion**: User testing with fresh eyes

## Verification Checklist

Before marking complete:
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Type checking passes: `poetry run pyright actingweb/`
- [ ] Linting passes: `poetry run ruff check actingweb/`
- [ ] Documentation builds without warnings
- [ ] No broken links in documentation
- [ ] HTTP API responses identical before/after (compare with `curl` snapshots)
- [ ] Performance benchmarks within 10% of baseline
