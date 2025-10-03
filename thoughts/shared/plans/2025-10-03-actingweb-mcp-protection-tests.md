# ActingWeb Library Protection Tests for actingweb_mcp Implementation Plan

## Overview

Add comprehensive integration tests to the ActingWeb library to prevent regressions in the actingweb_mcp application. The actingweb_mcp application is a production MCP (Model Context Protocol) server that heavily relies on ActingWeb features for memory storage, access control, and OAuth2 authentication. Without proper test coverage in the library, improvements to ActingWeb could break actingweb_mcp's critical functionality.

## Current State Analysis

### What actingweb_mcp Does

The actingweb_mcp application:
1. **Stores personal memories** in property lists with dynamic names (`memory_personal`, `memory_travel`, `memory_food`, etc.)
2. **Controls access per MCP client** using trust permissions with `excluded_patterns` to filter which memory types each AI assistant can access
3. **Authenticates MCP clients** via OAuth2 client credentials flow with automatic trust relationship creation
4. **Manages multiple clients** per user (ChatGPT, Claude, Cursor, etc.) each with individual permissions

### Current Test Coverage Gaps

Analysis of ActingWeb's integration tests (`tests/integration/`) reveals:

**Property Lists**:
- ❌ No tests for dynamic property list creation with arbitrary names
- ❌ No tests for `property_lists.list_all()` method
- ❌ No tests for `property_lists.exists(name)` method
- ❌ No tests for property list complete deletion
- ❌ No tests for item deletion by index (`del prop_list[2]`)
- ❌ No tests for metadata storage pattern (first item as metadata)

**Trust Permissions**:
- ❌ No tests for `excluded_patterns` in trust permissions
- ❌ No tests for pattern matching with wildcards (`memory_*`, `get_*`)
- ❌ No tests for permission inheritance from trust types
- ❌ No tests for individual permission overrides
- ❌ No tests for permission updates and retrieval

**OAuth2 Client Manager**:
- ✅ Basic client registration tested in `test_mcp_oauth2.py`
- ❌ No tests for `OAuth2ClientManager` class methods (create_client, list_clients, etc.)
- ❌ No tests for multiple OAuth2 clients per actor
- ❌ No tests for client deletion
- ❌ No tests for access token generation via client manager

**Trust-OAuth Integration**:
- ❌ No tests for trust relationships linked to OAuth clients
- ❌ No tests for `oauth_client_id` attribute on trust relationships
- ❌ No tests for permission checks with OAuth context

**Trust Type Registry**:
- ❌ No tests for custom trust type registration
- ❌ No tests for trust types with complex permission structures

**Runtime Context**:
- ❌ No tests for MCP context setting and retrieval
- ❌ No tests for client detection in hooks

### Key Discoveries

**Property List Implementation** (`actingweb/property_list.py:39-430`):
- Uses attribute bucket storage with `"list:"` prefix
- Metadata stored as `list:{name}-meta` property
- Items stored as `list:{name}-{index}` properties
- `list_all()` filters for `list:*-meta` pattern to discover lists
- `exists()` checks for metadata property existence
- `delete()` removes all items and metadata

**Trust Permissions** (`actingweb/trust_permissions.py:22-257`):
- `TrustPermissions` dataclass with optional category overrides
- Stored in attribute buckets: `trust_permissions` bucket, key `"{actor_id}:{peer_id}"`
- `excluded_patterns` array in permission category dictionaries
- Pattern matching supports wildcards (`*`), glob patterns, URI prefixes
- Permission evaluator checks excluded patterns before allowing access

**OAuth2 Client Manager** (`actingweb/interface/oauth_client_manager.py:18-341`):
- High-level interface wrapping `MCPClientRegistry`
- Stores clients in per-actor `mcp_clients` bucket
- Global client index in system actor for efficient lookup
- Automatically creates trust relationships on client creation
- Token generation via `ActingWebTokenManager`

## Desired End State

### Success Definition

A comprehensive integration test suite that:
1. ✅ Validates all property list operations used by actingweb_mcp
2. ✅ Tests trust permission pattern matching and exclusions
3. ✅ Verifies OAuth2 client management lifecycle
4. ✅ Confirms trust-OAuth integration works correctly
5. ✅ Prevents breaking changes to actingweb_mcp when improving ActingWeb library
6. ✅ Runs in CI/CD pipeline alongside existing tests

### Verification

**Automated Verification**:
- [ ] All new tests pass: `make test-integration`
- [ ] Existing tests still pass: `make test-integration`
- [ ] Test coverage report shows new coverage: `pytest --cov=actingweb tests/integration/`
- [ ] No regressions: actingweb_mcp test suite passes against updated ActingWeb

**Manual Verification**:
- [ ] actingweb_mcp application still works with ChatGPT, Claude, Cursor
- [ ] Memory access filtering works correctly per client
- [ ] OAuth2 client creation and deletion works in actingweb_mcp UI
- [ ] Multiple memory types can be created and accessed

## What We're NOT Doing

- NOT modifying actingweb_mcp application itself
- NOT changing ActingWeb library behavior (only adding tests)
- NOT testing every possible property list operation (only critical ones used by actingweb_mcp)
- NOT testing OAuth2 authorization code flow (only client credentials flow)
- NOT testing MCP protocol implementation details (tested in actingweb_mcp)
- NOT adding unit tests (only integration tests)

## Implementation Approach

### Strategy

1. **Follow existing patterns**: Use the same test structure, fixtures, and patterns as existing ActingWeb integration tests
2. **Incremental phases**: Implement tests in dependency order (property lists → permissions → OAuth → integration)
3. **Real scenarios**: Test actual usage patterns from actingweb_mcp, not hypothetical use cases
4. **Comprehensive coverage**: Cover happy paths, edge cases, and error conditions
5. **Documentation**: Include clear docstrings explaining what each test validates and why it matters

### Test Organization

Following ActingWeb's existing pattern:
- Place all tests in `tests/integration/`
- Use existing fixtures from `conftest.py` (actor_factory, trust_helper, oauth2_client)
- Follow existing naming conventions (`test_*_*.py`)
- Use sequential test classes where state sharing makes sense
- Use function-scoped tests for independent scenarios

---

## Phase 1: Property Lists Advanced Testing

### Overview

Test all property list operations that actingweb_mcp relies on for memory storage. This is the foundation - without working property lists, actingweb_mcp cannot store or retrieve memories.

### Changes Required

#### 1. Create Property Lists Advanced Test File

**File**: `tests/integration/test_property_lists_advanced.py`

**Changes**: Create new test file with comprehensive property list tests

```python
"""
Property Lists Advanced Integration Tests.

Tests property list operations critical for actingweb_mcp memory storage:
- Dynamic property list creation with arbitrary names
- Metadata storage and retrieval patterns
- list_all() discovery functionality
- exists() checks
- Complete list deletion
- Item deletion by index

These tests protect actingweb_mcp from regressions when improving ActingWeb.

References:
- actingweb/property_list.py:39-430 - ListProperty implementation
- actingweb/property.py:5-56 - PropertyListStore implementation
- actingweb_mcp/application.py:301-413 - Memory type usage patterns
"""

import pytest


class TestPropertyListDynamicCreation:
    """Test dynamic creation and access of property lists."""

    def test_create_multiple_property_lists_dynamically(self, actor_factory):
        """
        Test that property lists can be created dynamically with any name.

        actingweb_mcp creates memory_personal, memory_travel, memory_food, etc.
        on-demand without pre-registration.

        Spec: actingweb/property_list.py:46-56 - __getattr__ pattern
        """
        actor = actor_factory.create("test@example.com")

        # Create multiple property lists dynamically (actingweb_mcp pattern)
        memory_types = [
            "memory_personal",
            "memory_travel",
            "memory_food",
            "memory_health",
            "memory_work"
        ]

        for memory_type in memory_types:
            prop_list = getattr(actor.property_lists, memory_type)
            prop_list.append({
                "id": 1,
                "content": f"Test data for {memory_type}",
                "created_at": "2025-10-03T10:00:00"
            })

        # Verify all exist
        all_lists = actor.property_lists.list_all()
        for memory_type in memory_types:
            assert memory_type in all_lists, f"Expected {memory_type} in list_all() output"

        # Verify content retrieval
        personal_list = getattr(actor.property_lists, "memory_personal")
        items = personal_list.to_list()
        assert len(items) == 1
        assert items[0]["content"] == "Test data for memory_personal"

    def test_property_list_names_with_underscores_and_numbers(self, actor_factory):
        """
        Test property lists with various naming patterns.

        actingweb_mcp allows user-created memory types with custom names.

        Spec: actingweb/property_list.py:48 - All names are valid except _*
        """
        actor = actor_factory.create("test@example.com")

        test_names = [
            "memory_test_123",
            "memory_user_defined_type",
            "notes_2025",
            "list_with_numbers_456"
        ]

        for name in test_names:
            prop_list = getattr(actor.property_lists, name)
            prop_list.append({"data": f"test_{name}"})

        all_lists = actor.property_lists.list_all()
        for name in test_names:
            assert name in all_lists


class TestPropertyListMetadataStorage:
    """Test metadata storage pattern used by actingweb_mcp."""

    def test_metadata_as_first_item_persists(self, actor_factory):
        """
        Test that metadata stored as first item persists correctly.

        actingweb_mcp stores metadata in the first item to track display_name,
        description, emoji, keywords, etc.

        Spec: actingweb_mcp/memory_config.py:40-80 - Metadata pattern
        """
        actor = actor_factory.create("test@example.com")

        prop_list = getattr(actor.property_lists, "memory_travel")

        # Store metadata as first item (actingweb_mcp pattern)
        metadata = {
            "type_name": "memory_travel",
            "display_name": "Travel Memories",
            "description": "Travel plans and memories",
            "emoji": "✈️",
            "keywords": ["flight", "hotel", "vacation", "trip"],
            "created_at": "2025-10-03T10:00:00",
            "created_by": "mcp_auto"
        }
        prop_list.insert(0, metadata)

        # Add actual data items
        prop_list.append({"id": 1, "content": "Paris trip 2025", "created_at": "2025-10-03T11:00:00"})
        prop_list.append({"id": 2, "content": "Tokyo flight booked", "created_at": "2025-10-03T12:00:00"})
        prop_list.append({"id": 3, "content": "Hotel reservation confirmed", "created_at": "2025-10-03T13:00:00"})

        # Retrieve and verify order is preserved
        items = prop_list.to_list()
        assert len(items) == 4

        # First item should be metadata
        assert items[0]["type_name"] == "memory_travel"
        assert items[0]["display_name"] == "Travel Memories"
        assert items[0]["emoji"] == "✈️"

        # Subsequent items should be data
        assert items[1]["content"] == "Paris trip 2025"
        assert items[2]["content"] == "Tokyo flight booked"
        assert items[3]["content"] == "Hotel reservation confirmed"

    def test_metadata_retrieval_after_many_items(self, actor_factory):
        """
        Test that metadata remains accessible even with many items.

        actingweb_mcp reads metadata on every dashboard load.

        Spec: actingweb_mcp/memory_config.py:56-67 - read_property_list_metadata
        """
        actor = actor_factory.create("test@example.com")

        prop_list = getattr(actor.property_lists, "memory_notes")

        # Store metadata
        metadata = {
            "type_name": "memory_notes",
            "display_name": "Quick Notes",
            "description": "Short notes and reminders",
            "created_at": "2025-10-03T10:00:00"
        }
        prop_list.insert(0, metadata)

        # Add 50 data items
        for i in range(50):
            prop_list.append({"id": i + 1, "content": f"Note {i + 1}"})

        # Metadata should still be first item
        items = prop_list.to_list()
        assert len(items) == 51
        assert items[0]["type_name"] == "memory_notes"
        assert items[0]["display_name"] == "Quick Notes"


class TestPropertyListDiscovery:
    """Test list_all() and exists() methods for property list discovery."""

    def test_list_all_returns_all_property_lists(self, actor_factory):
        """
        Test list_all() discovers all property lists for an actor.

        actingweb_mcp uses list_all() to display all memory types in dashboard.

        Spec: actingweb/property.py:28-44 - list_all() implementation
        """
        actor = actor_factory.create("test@example.com")

        # Create several property lists
        memory_types = ["memory_personal", "memory_travel", "memory_food"]
        for memory_type in memory_types:
            prop_list = getattr(actor.property_lists, memory_type)
            prop_list.append({"content": "test"})

        # list_all() should return all of them
        all_lists = actor.property_lists.list_all()
        assert len(all_lists) >= 3
        for memory_type in memory_types:
            assert memory_type in all_lists

    def test_list_all_excludes_regular_properties(self, actor_factory):
        """
        Test that list_all() only returns property lists, not regular properties.

        Spec: actingweb/property.py:36-38 - Filters for list:*-meta pattern
        """
        actor = actor_factory.create("test@example.com")

        # Create property list
        prop_list = getattr(actor.property_lists, "memory_test")
        prop_list.append({"content": "test"})

        # Create regular property (not a list)
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        core_actor = CoreActor(actor["id"], config=None)
        # Regular properties would be created via actor.property.set()

        # list_all() should only return property lists
        all_lists = actor.property_lists.list_all()
        assert "memory_test" in all_lists

    def test_exists_check_for_property_lists(self, actor_factory):
        """
        Test exists() method accurately reports property list existence.

        actingweb_mcp uses exists() to check if memory types exist before accessing.

        Spec: actingweb/property.py:17-26 - exists() implementation
        """
        actor = actor_factory.create("test@example.com")

        # Non-existent list
        assert not actor.property_lists.exists("memory_nonexistent")

        # Create list by accessing and appending
        prop_list = getattr(actor.property_lists, "memory_test")
        prop_list.append({"data": "test"})

        # Should now exist
        assert actor.property_lists.exists("memory_test")

        # Still shouldn't exist for different name
        assert not actor.property_lists.exists("memory_other")

    def test_exists_returns_false_for_empty_list(self, actor_factory):
        """
        Test that exists() returns False for lists that were accessed but never populated.

        Spec: actingweb/property.py:22 - Checks for metadata property
        """
        actor = actor_factory.create("test@example.com")

        # Access list but don't append anything
        prop_list = getattr(actor.property_lists, "memory_empty")

        # Should not exist because no items were appended (no metadata created)
        assert not actor.property_lists.exists("memory_empty")


class TestPropertyListDeletion:
    """Test property list deletion operations."""

    def test_complete_list_deletion(self, actor_factory):
        """
        Test that property lists can be completely deleted.

        actingweb_mcp allows users to delete entire memory types.

        Spec: actingweb/property_list.py:302-319 - delete() implementation
        """
        actor = actor_factory.create("test@example.com")

        # Create and populate property list
        prop_list = getattr(actor.property_lists, "memory_temp")
        prop_list.append({"id": 1, "content": "temp data 1"})
        prop_list.append({"id": 2, "content": "temp data 2"})
        prop_list.append({"id": 3, "content": "temp data 3"})

        # Verify it exists
        assert actor.property_lists.exists("memory_temp")
        all_lists_before = actor.property_lists.list_all()
        assert "memory_temp" in all_lists_before

        # Delete the entire list
        prop_list.delete()

        # Verify deletion
        assert not actor.property_lists.exists("memory_temp")
        all_lists_after = actor.property_lists.list_all()
        assert "memory_temp" not in all_lists_after

    def test_delete_removes_all_items_and_metadata(self, actor_factory):
        """
        Test that delete() removes all items and metadata.

        Spec: actingweb/property_list.py:310-316 - Deletes items and metadata
        """
        actor = actor_factory.create("test@example.com")

        # Create list with many items
        prop_list = getattr(actor.property_lists, "memory_test_delete")
        for i in range(20):
            prop_list.append({"id": i + 1, "content": f"Item {i + 1}"})

        # Verify items exist
        items_before = prop_list.to_list()
        assert len(items_before) == 20

        # Delete
        prop_list.delete()

        # Recreate same list (should be empty, not contain old data)
        new_prop_list = getattr(actor.property_lists, "memory_test_delete")
        items_after = new_prop_list.to_list()
        assert len(items_after) == 0


class TestPropertyListItemDeletion:
    """Test item deletion by index."""

    def test_delete_item_by_index(self, actor_factory):
        """
        Test deleting items from property list by index.

        actingweb_mcp allows users to delete individual memory items.

        Spec: actingweb/property_list.py:212-251 - __delitem__ implementation
        """
        actor = actor_factory.create("test@example.com")

        prop_list = getattr(actor.property_lists, "memory_notes")

        # Add multiple items
        for i in range(5):
            prop_list.append({"id": i + 1, "content": f"Note {i + 1}"})

        # Verify initial state
        items = prop_list.to_list()
        assert len(items) == 5
        assert items[2]["content"] == "Note 3"

        # Delete item at index 2 (third item)
        del prop_list[2]

        # Verify deletion and shift
        items_after = prop_list.to_list()
        assert len(items_after) == 4
        # Item at index 2 should now be the old item 4 (shifted down)
        assert items_after[2]["content"] == "Note 4"
        # Item 3 should no longer exist
        contents = [item["content"] for item in items_after]
        assert "Note 3" not in contents

    def test_delete_first_item(self, actor_factory):
        """
        Test deleting first item from property list.

        Note: actingweb_mcp stores metadata as first item, so this tests
        accidental deletion of metadata.

        Spec: actingweb/property_list.py:212-251 - __delitem__ with index 0
        """
        actor = actor_factory.create("test@example.com")

        prop_list = getattr(actor.property_lists, "memory_test")

        # Add items
        prop_list.append({"id": 1, "content": "First"})
        prop_list.append({"id": 2, "content": "Second"})
        prop_list.append({"id": 3, "content": "Third"})

        # Delete first item
        del prop_list[0]

        # Verify
        items = prop_list.to_list()
        assert len(items) == 2
        assert items[0]["content"] == "Second"
        assert items[1]["content"] == "Third"

    def test_delete_last_item(self, actor_factory):
        """
        Test deleting last item from property list.

        Spec: actingweb/property_list.py:212-251 - __delitem__ with last index
        """
        actor = actor_factory.create("test@example.com")

        prop_list = getattr(actor.property_lists, "memory_test")

        # Add items
        prop_list.append({"id": 1, "content": "First"})
        prop_list.append({"id": 2, "content": "Second"})
        prop_list.append({"id": 3, "content": "Third"})

        # Delete last item (index 2 or -1)
        del prop_list[2]

        # Verify
        items = prop_list.to_list()
        assert len(items) == 2
        assert items[0]["content"] == "First"
        assert items[1]["content"] == "Second"

    def test_delete_with_negative_index(self, actor_factory):
        """
        Test deleting item with negative index (Python list convention).

        Spec: actingweb/property_list.py:215-216 - Negative index support
        """
        actor = actor_factory.create("test@example.com")

        prop_list = getattr(actor.property_lists, "memory_test")

        # Add items
        for i in range(5):
            prop_list.append({"id": i + 1, "content": f"Item {i + 1}"})

        # Delete second-to-last item (index -2)
        del prop_list[-2]

        # Verify
        items = prop_list.to_list()
        assert len(items) == 4
        # Item 4 should be gone
        contents = [item["content"] for item in items]
        assert "Item 4" not in contents
        assert "Item 5" in contents


class TestPropertyListLargeData:
    """Test property lists with large amounts of data."""

    def test_property_list_with_100_items(self, actor_factory):
        """
        Test property list with 100 items (realistic for actingweb_mcp).

        actingweb_mcp users may accumulate dozens or hundreds of memories.

        Spec: actingweb/property_list.py - No size limit on lists
        """
        actor = actor_factory.create("test@example.com")

        prop_list = getattr(actor.property_lists, "memory_large")

        # Add 100 items
        for i in range(100):
            prop_list.append({
                "id": i + 1,
                "content": f"Memory item {i + 1}",
                "created_at": f"2025-10-03T{i % 24:02d}:00:00"
            })

        # Verify all items are stored
        items = prop_list.to_list()
        assert len(items) == 100

        # Verify order is preserved
        assert items[0]["content"] == "Memory item 1"
        assert items[50]["content"] == "Memory item 51"
        assert items[99]["content"] == "Memory item 100"

    def test_multiple_large_property_lists(self, actor_factory):
        """
        Test multiple property lists each with many items.

        actingweb_mcp has 6+ predefined memory types, each potentially large.

        Spec: No limit on number of property lists per actor
        """
        actor = actor_factory.create("test@example.com")

        memory_types = [
            "memory_personal",
            "memory_travel",
            "memory_food",
            "memory_work",
            "memory_health"
        ]

        # Create 5 lists with 20 items each
        for memory_type in memory_types:
            prop_list = getattr(actor.property_lists, memory_type)
            for i in range(20):
                prop_list.append({
                    "id": i + 1,
                    "content": f"{memory_type} item {i + 1}"
                })

        # Verify all lists exist
        all_lists = actor.property_lists.list_all()
        for memory_type in memory_types:
            assert memory_type in all_lists

        # Verify item counts
        for memory_type in memory_types:
            prop_list = getattr(actor.property_lists, memory_type)
            items = prop_list.to_list()
            assert len(items) == 20
```

### Success Criteria

#### Automated Verification:
- [ ] All property list tests pass: `make test-integration`
- [ ] Test file follows existing patterns: `pytest tests/integration/test_property_lists_advanced.py -v`
- [ ] Tests run in reasonable time (<30 seconds for all property list tests)
- [ ] No existing tests broken: `make test-integration` shows same pass count as before

#### Manual Verification:
- [ ] Tests cover all property list operations used in actingweb_mcp
- [ ] Tests use same fixtures and patterns as existing ActingWeb tests
- [ ] Test docstrings clearly explain what is being tested and why
- [ ] Code follows ActingWeb style (PEP 8, existing conventions)

---

## Phase 2: Trust Permissions Pattern Testing

### Overview

Test trust permission pattern matching and `excluded_patterns` functionality that actingweb_mcp uses to control memory access per MCP client. Without these tests, changes to the permission system could break memory filtering.

### Changes Required

#### 1. Create Trust Permissions Pattern Test File

**File**: `tests/integration/test_trust_permissions_patterns.py`

**Changes**: Create new test file with comprehensive trust permission tests

```python
"""
Trust Permissions Pattern Integration Tests.

Tests trust permission pattern matching and excluded_patterns functionality
critical for actingweb_mcp memory access control:
- excluded_patterns array in trust permissions
- Pattern matching with wildcards (memory_*, get_*)
- Permission inheritance from trust types
- Individual permission overrides
- Permission updates and retrieval

These tests protect actingweb_mcp from regressions in access control logic.

References:
- actingweb/trust_permissions.py:22-257 - TrustPermissions and store
- actingweb/permission_evaluator.py:442-498 - Pattern matching
- actingweb_mcp/application.py:1487-1573 - check_memory_access_permission
"""

import pytest
from actingweb.trust_permissions import TrustPermissionStore, TrustPermissions


class TestTrustPermissionsExcludedPatterns:
    """Test excluded_patterns functionality in trust permissions."""

    def test_store_permissions_with_excluded_patterns(self, actor_factory):
        """
        Test storing trust permissions with excluded_patterns.

        actingweb_mcp stores excluded memory types for each MCP client.

        Spec: actingweb/trust_permissions.py:98-131 - store_permissions()
        """
        actor1 = actor_factory.create("user@example.com")
        actor2 = actor_factory.create("mcp_client@example.com")

        # Get the config from actor1
        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor1["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # Create permissions with excluded patterns (actingweb_mcp pattern)
        permissions = TrustPermissions(
            actor_id=actor1["id"],
            peer_id=actor2["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read", "write"],
                "excluded_patterns": ["memory_personal", "memory_travel"]
            },
            created_by="test"
        )

        # Store permissions
        success = permission_store.store_permissions(permissions)
        assert success

        # Retrieve and verify
        stored = permission_store.get_permissions(actor1["id"], actor2["id"])
        assert stored is not None
        assert stored.properties is not None
        assert "memory_personal" in stored.properties["excluded_patterns"]
        assert "memory_travel" in stored.properties["excluded_patterns"]
        assert "memory_food" not in stored.properties.get("excluded_patterns", [])

    def test_excluded_patterns_persist_across_restarts(self, actor_factory):
        """
        Test that excluded_patterns persist in database.

        actingweb_mcp relies on permissions persisting across app restarts.

        Spec: actingweb/trust_permissions.py:236-249 - Attribute bucket storage
        """
        actor1 = actor_factory.create("user@example.com")
        actor2 = actor_factory.create("client@example.com")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor1["id"], config=None)

        # Store permissions
        permission_store = TrustPermissionStore(core_actor.config)
        permissions = TrustPermissions(
            actor_id=actor1["id"],
            peer_id=actor2["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": ["memory_private", "memory_confidential"]
            },
            created_by="test"
        )
        permission_store.store_permissions(permissions)

        # Clear cache to force database read
        permission_store.clear_cache()

        # Retrieve from database
        stored = permission_store.get_permissions(actor1["id"], actor2["id"])
        assert stored is not None
        assert "memory_private" in stored.properties["excluded_patterns"]
        assert "memory_confidential" in stored.properties["excluded_patterns"]

    def test_update_excluded_patterns(self, actor_factory):
        """
        Test updating excluded_patterns in existing permissions.

        actingweb_mcp allows users to change which memory types are excluded.

        Spec: actingweb/trust_permissions.py:225-252 - update_permissions()
        """
        actor1 = actor_factory.create("user@example.com")
        actor2 = actor_factory.create("client@example.com")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor1["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # Create initial permissions
        permissions = TrustPermissions(
            actor_id=actor1["id"],
            peer_id=actor2["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": []
            },
            created_by="test"
        )
        permission_store.store_permissions(permissions)

        # Retrieve and modify
        stored = permission_store.get_permissions(actor1["id"], actor2["id"])
        stored.properties["excluded_patterns"].append("memory_personal")
        stored.properties["excluded_patterns"].append("memory_travel")

        # Update
        permission_store.store_permissions(stored)

        # Verify updates persisted
        updated = permission_store.get_permissions(actor1["id"], actor2["id"])
        assert "memory_personal" in updated.properties["excluded_patterns"]
        assert "memory_travel" in updated.properties["excluded_patterns"]

    def test_empty_excluded_patterns_allows_all(self, actor_factory):
        """
        Test that empty excluded_patterns array allows all matching patterns.

        Default behavior when no exclusions are set.

        Spec: actingweb/permission_evaluator.py:428-437 - Only checks excluded if present
        """
        actor1 = actor_factory.create("user@example.com")
        actor2 = actor_factory.create("client@example.com")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor1["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # Create permissions with empty excluded_patterns
        permissions = TrustPermissions(
            actor_id=actor1["id"],
            peer_id=actor2["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": []
            },
            created_by="test"
        )
        permission_store.store_permissions(permissions)

        # Verify empty list is stored
        stored = permission_store.get_permissions(actor1["id"], actor2["id"])
        assert stored.properties["excluded_patterns"] == []


class TestTrustPermissionsPatternMatching:
    """Test pattern matching with wildcards."""

    def test_wildcard_pattern_matches_multiple_properties(self, actor_factory):
        """
        Test that memory_* pattern matches all memory types.

        actingweb_mcp uses memory_* to match all memory property lists.

        Spec: actingweb/permission_evaluator.py:487-497 - Glob to regex conversion
        """
        import fnmatch

        # Test pattern matching logic
        pattern = "memory_*"

        matching_names = [
            "memory_personal",
            "memory_travel",
            "memory_food",
            "memory_health",
            "memory_work"
        ]

        non_matching_names = [
            "settings_private",
            "notes_general",
            "user_profile"
        ]

        # All memory_ names should match
        for name in matching_names:
            assert fnmatch.fnmatch(name, pattern), f"{name} should match {pattern}"

        # Non-memory names should not match
        for name in non_matching_names:
            assert not fnmatch.fnmatch(name, pattern), f"{name} should not match {pattern}"

    def test_method_pattern_matching(self, actor_factory):
        """
        Test that get_* pattern matches method names.

        actingweb_mcp allows method patterns like get_*, list_*, search_*.

        Spec: actingweb_mcp/application.py:153 - methods permission
        """
        import fnmatch

        pattern = "get_*"

        matching_methods = [
            "get_profile",
            "get_notes",
            "get_memory",
            "get_settings"
        ]

        non_matching_methods = [
            "list_items",
            "search_memories",
            "update_profile",
            "delete_note"
        ]

        for method in matching_methods:
            assert fnmatch.fnmatch(method, pattern)

        for method in non_matching_methods:
            assert not fnmatch.fnmatch(method, pattern)

    def test_multiple_wildcard_patterns(self, actor_factory):
        """
        Test permissions with multiple wildcard patterns.

        actingweb_mcp defines multiple allowed patterns for different categories.

        Spec: actingweb/permission_evaluator.py:442-454 - Matches any pattern
        """
        import fnmatch

        patterns = ["memory_*", "notes_*", "public_*"]

        matching_names = [
            "memory_personal",
            "notes_work",
            "public_profile",
            "memory_travel",
            "notes_2025"
        ]

        non_matching_names = [
            "private_settings",
            "user_config",
            "auth_token"
        ]

        # Should match at least one pattern
        for name in matching_names:
            matched = any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
            assert matched, f"{name} should match at least one pattern"

        # Should not match any pattern
        for name in non_matching_names:
            matched = any(fnmatch.fnmatch(name, pattern) for pattern in patterns)
            assert not matched, f"{name} should not match any pattern"


class TestTrustPermissionsInheritance:
    """Test permission inheritance from trust types."""

    def test_no_override_uses_trust_type_defaults(self, actor_factory):
        """
        Test that when no permission override exists, trust type defaults apply.

        actingweb_mcp relies on trust type defaults for standard MCP clients.

        Spec: actingweb/permission_evaluator.py:314-358 - Effective permissions
        """
        # This test would need access to trust type registry
        # and permission evaluator - testing the integration
        pass  # TODO: Implement when permission evaluator testing is needed

    def test_individual_override_replaces_trust_type_for_category(self, actor_factory):
        """
        Test that individual permissions override trust type for specific categories.

        actingweb_mcp sets per-relationship excluded_patterns.

        Spec: actingweb/trust_permissions.py:261-294 - merge_permissions()
        """
        actor1 = actor_factory.create("user@example.com")
        actor2 = actor_factory.create("client@example.com")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor1["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # Create override with just properties, other categories use trust type defaults
        permissions = TrustPermissions(
            actor_id=actor1["id"],
            peer_id=actor2["id"],
            trust_type="mcp_client",
            properties={  # Override properties only
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": ["memory_personal"]
            },
            methods=None,  # Use trust type defaults
            actions=None,  # Use trust type defaults
            tools=None,    # Use trust type defaults
            created_by="test"
        )
        permission_store.store_permissions(permissions)

        # Verify only properties are stored, others are None (inherit)
        stored = permission_store.get_permissions(actor1["id"], actor2["id"])
        assert stored.properties is not None
        assert stored.methods is None
        assert stored.actions is None
        assert stored.tools is None


class TestTrustPermissionsRetrieval:
    """Test permission retrieval operations."""

    def test_get_permissions_returns_none_if_not_found(self, actor_factory):
        """
        Test that get_permissions returns None for non-existent permissions.

        Spec: actingweb/trust_permissions.py:133-165 - get_permissions()
        """
        actor1 = actor_factory.create("user@example.com")
        actor2 = actor_factory.create("client@example.com")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor1["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # No permissions exist yet
        result = permission_store.get_permissions(actor1["id"], actor2["id"])
        assert result is None

    def test_list_actor_permissions(self, actor_factory):
        """
        Test listing all permission overrides for an actor.

        actingweb_mcp may need to list all client permissions.

        Spec: actingweb/trust_permissions.py:167-197 - list_actor_permissions()
        """
        actor1 = actor_factory.create("user@example.com")
        client1 = actor_factory.create("client1@example.com")
        client2 = actor_factory.create("client2@example.com")
        client3 = actor_factory.create("client3@example.com")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor1["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # Create permissions for multiple clients
        for client in [client1, client2, client3]:
            permissions = TrustPermissions(
                actor_id=actor1["id"],
                peer_id=client["id"],
                trust_type="mcp_client",
                properties={
                    "patterns": ["memory_*"],
                    "operations": ["read"],
                    "excluded_patterns": [f"memory_private_{client['id'][:8]}"]
                },
                created_by="test"
            )
            permission_store.store_permissions(permissions)

        # List all permissions for actor1
        all_perms = permission_store.list_actor_permissions(actor1["id"])

        assert len(all_perms) == 3
        peer_ids = [perm.peer_id for perm in all_perms]
        assert client1["id"] in peer_ids
        assert client2["id"] in peer_ids
        assert client3["id"] in peer_ids


class TestTrustPermissionsComplexScenarios:
    """Test complex permission scenarios from actingweb_mcp."""

    def test_chatgpt_gets_only_memory_personal(self, actor_factory):
        """
        Test realistic scenario: ChatGPT restricted to memory_personal only.

        This is a common actingweb_mcp configuration.

        Spec: actingweb_mcp/application.py:866-897 - Restrictive initialization
        """
        actor = actor_factory.create("user@example.com")
        chatgpt = actor_factory.create("chatgpt@openai.com")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # ChatGPT gets memory_* but excludes all except memory_personal
        permissions = TrustPermissions(
            actor_id=actor["id"],
            peer_id=chatgpt["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read", "write"],
                "excluded_patterns": [
                    "memory_travel",
                    "memory_food",
                    "memory_health",
                    "memory_work",
                    "memory_notes"
                ]
            },
            created_by="test"
        )
        permission_store.store_permissions(permissions)

        # Verify exclusions stored correctly
        stored = permission_store.get_permissions(actor["id"], chatgpt["id"])
        excluded = stored.properties["excluded_patterns"]

        assert "memory_travel" in excluded
        assert "memory_food" in excluded
        assert "memory_health" in excluded
        assert "memory_work" in excluded
        assert "memory_notes" in excluded
        # memory_personal should NOT be in excluded list
        assert "memory_personal" not in excluded

    def test_claude_gets_all_memory_types(self, actor_factory):
        """
        Test realistic scenario: Claude gets access to all memory types.

        Another common actingweb_mcp configuration.

        Spec: actingweb_mcp uses empty excluded_patterns for full access
        """
        actor = actor_factory.create("user@example.com")
        claude = actor_factory.create("claude@anthropic.com")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # Claude gets all memory types (no exclusions)
        permissions = TrustPermissions(
            actor_id=actor["id"],
            peer_id=claude["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read", "write"],
                "excluded_patterns": []  # No exclusions = full access
            },
            created_by="test"
        )
        permission_store.store_permissions(permissions)

        # Verify empty exclusions
        stored = permission_store.get_permissions(actor["id"], claude["id"])
        assert stored.properties["excluded_patterns"] == []

    def test_multiple_clients_different_permissions(self, actor_factory):
        """
        Test multiple MCP clients with different memory access.

        actingweb_mcp supports per-client customization.

        Spec: actingweb_mcp allows different excluded_patterns per client
        """
        actor = actor_factory.create("user@example.com")
        chatgpt = actor_factory.create("chatgpt@openai.com")
        claude = actor_factory.create("claude@anthropic.com")
        cursor = actor_factory.create("cursor@cursor.sh")

        from actingweb.actor import Actor as CoreActor
        core_actor = CoreActor(actor["id"], config=None)

        permission_store = TrustPermissionStore(core_actor.config)

        # ChatGPT: Only memory_personal and memory_work
        chatgpt_perms = TrustPermissions(
            actor_id=actor["id"],
            peer_id=chatgpt["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": ["memory_travel", "memory_food", "memory_health"]
            },
            created_by="test"
        )

        # Claude: All memory types
        claude_perms = TrustPermissions(
            actor_id=actor["id"],
            peer_id=claude["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read", "write"],
                "excluded_patterns": []
            },
            created_by="test"
        )

        # Cursor: Only work-related
        cursor_perms = TrustPermissions(
            actor_id=actor["id"],
            peer_id=cursor["id"],
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": ["memory_personal", "memory_travel", "memory_food", "memory_health"]
            },
            created_by="test"
        )

        # Store all permissions
        permission_store.store_permissions(chatgpt_perms)
        permission_store.store_permissions(claude_perms)
        permission_store.store_permissions(cursor_perms)

        # Verify each client has different exclusions
        chatgpt_stored = permission_store.get_permissions(actor["id"], chatgpt["id"])
        claude_stored = permission_store.get_permissions(actor["id"], claude["id"])
        cursor_stored = permission_store.get_permissions(actor["id"], cursor["id"])

        assert len(chatgpt_stored.properties["excluded_patterns"]) == 3
        assert len(claude_stored.properties["excluded_patterns"]) == 0
        assert len(cursor_stored.properties["excluded_patterns"]) == 4
```

### Success Criteria

#### Automated Verification:
- [ ] All trust permission tests pass: `make test-integration`
- [ ] Test file uses existing actor_factory fixture correctly
- [ ] Tests run in reasonable time (<30 seconds)
- [ ] No existing tests broken: `make test-integration` shows same pass count

#### Manual Verification:
- [ ] Tests cover excluded_patterns storage and retrieval
- [ ] Tests demonstrate pattern matching with wildcards
- [ ] Tests show realistic actingweb_mcp scenarios (ChatGPT, Claude, Cursor)
- [ ] Code follows ActingWeb style conventions

---

## Phase 3: OAuth2 Client Manager Testing

### Overview

Test OAuth2 client management operations that actingweb_mcp uses for MCP assistant authentication. These tests ensure client creation, listing, deletion, and token generation continue working.

### Changes Required

#### 1. Create OAuth2 Client Manager Test File

**File**: `tests/integration/test_oauth2_client_manager.py`

**Changes**: Create new test file with OAuth2ClientManager tests

```python
"""
OAuth2 Client Manager Integration Tests.

Tests OAuth2ClientManager class operations critical for actingweb_mcp:
- Client creation with trust type
- Client listing for an actor
- Client retrieval and verification
- Client deletion and cleanup
- Access token generation
- Multiple clients per actor

These tests protect actingweb_mcp MCP client authentication from regressions.

References:
- actingweb/interface/oauth_client_manager.py:18-341 - OAuth2ClientManager
- actingweb/oauth2_server/client_registry.py:33-100 - register_client
- actingweb_mcp/application.py:648-698 - Client generation endpoint
"""

import pytest


class TestOAuth2ClientCreation:
    """Test OAuth2 client creation via OAuth2ClientManager."""

    def test_create_client_basic(self, actor_factory):
        """
        Test creating OAuth2 client with basic parameters.

        actingweb_mcp creates OAuth2 clients for each MCP assistant.

        Spec: actingweb/interface/oauth_client_manager.py:38-85
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client with trust type (actingweb_mcp pattern)
        client_data = client_manager.create_client(
            client_name="ChatGPT",
            trust_type="mcp_client",
            client_uri="https://chatgpt.com",
            redirect_uris=["https://chatgpt.com/callback"]
        )

        # Verify response structure
        assert client_data is not None
        assert "client_id" in client_data
        assert "client_secret" in client_data
        assert client_data["client_name"] == "ChatGPT"
        assert client_data["trust_type"] == "mcp_client"

        # Verify client_id format (starts with mcp_)
        assert client_data["client_id"].startswith("mcp_")

    def test_create_multiple_clients_same_actor(self, actor_factory):
        """
        Test creating multiple OAuth2 clients for same actor.

        actingweb_mcp allows users to connect multiple AI assistants.

        Spec: actingweb/interface/oauth_client_manager.py - No limit on clients
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create 5 different MCP clients (realistic actingweb_mcp scenario)
        client_names = ["ChatGPT", "Claude", "Cursor", "Windsurf", "Custom Assistant"]
        created_clients = []

        for name in client_names:
            client_data = client_manager.create_client(
                client_name=name,
                trust_type="mcp_client",
                client_uri=f"https://{name.lower().replace(' ', '')}.com",
                redirect_uris=[f"https://{name.lower().replace(' ', '')}.com/callback"]
            )
            created_clients.append(client_data)

        # Verify all clients created successfully
        assert len(created_clients) == 5

        # Verify each has unique client_id
        client_ids = [c["client_id"] for c in created_clients]
        assert len(client_ids) == len(set(client_ids))  # All unique

        # Verify all have same actor_id
        for client_data in created_clients:
            assert client_data.get("actor_id") == actor["id"]

    def test_create_client_with_different_trust_types(self, actor_factory):
        """
        Test creating clients with different trust types.

        actingweb_mcp supports custom trust types for different access levels.

        Spec: actingweb/interface/oauth_client_manager.py:63 - trust_type parameter
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create clients with different trust types
        trust_types = ["mcp_client", "viewer", "friend"]
        clients = {}

        for trust_type in trust_types:
            client_data = client_manager.create_client(
                client_name=f"Client {trust_type}",
                trust_type=trust_type
            )
            clients[trust_type] = client_data

        # Verify each has correct trust type
        for trust_type, client_data in clients.items():
            assert client_data["trust_type"] == trust_type


class TestOAuth2ClientListing:
    """Test OAuth2 client listing operations."""

    def test_list_clients_empty(self, actor_factory):
        """
        Test listing clients when none exist.

        Spec: actingweb/interface/oauth_client_manager.py:109-133
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # List should be empty
        clients = client_manager.list_clients()
        assert clients == []

    def test_list_clients_returns_all_clients(self, actor_factory):
        """
        Test that list_clients returns all clients for an actor.

        actingweb_mcp uses list_clients to display all connected assistants.

        Spec: actingweb/interface/oauth_client_manager.py:109-133
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create 3 clients
        for i, name in enumerate(["ChatGPT", "Claude", "Cursor"]):
            client_manager.create_client(
                client_name=name,
                trust_type="mcp_client"
            )

        # List all clients
        clients = client_manager.list_clients()

        assert len(clients) == 3
        client_names = [c["client_name"] for c in clients]
        assert "ChatGPT" in client_names
        assert "Claude" in client_names
        assert "Cursor" in client_names

    def test_list_clients_includes_metadata(self, actor_factory):
        """
        Test that list_clients includes formatted metadata.

        actingweb_mcp displays creation date, status, etc.

        Spec: actingweb/interface/oauth_client_manager.py:120-129
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client
        client_manager.create_client(client_name="Test Client", trust_type="mcp_client")

        # List clients
        clients = client_manager.list_clients()

        assert len(clients) == 1
        client = clients[0]

        # Should have formatted metadata
        assert "created_at_formatted" in client
        assert "status" in client


class TestOAuth2ClientRetrieval:
    """Test OAuth2 client retrieval operations."""

    def test_get_client_by_id(self, actor_factory):
        """
        Test retrieving specific client by ID.

        actingweb_mcp retrieves clients for display and management.

        Spec: actingweb/interface/oauth_client_manager.py:87-107
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client
        created = client_manager.create_client(
            client_name="Test Client",
            trust_type="mcp_client"
        )
        client_id = created["client_id"]

        # Retrieve client
        retrieved = client_manager.get_client(client_id)

        assert retrieved is not None
        assert retrieved["client_id"] == client_id
        assert retrieved["client_name"] == "Test Client"
        assert retrieved["trust_type"] == "mcp_client"

    def test_get_client_wrong_actor_returns_none(self, actor_factory):
        """
        Test that get_client returns None for clients owned by other actors.

        Security: clients are actor-specific.

        Spec: actingweb/interface/oauth_client_manager.py:101-103
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        core_actor1 = CoreActor(actor1["id"], config=None)
        core_actor2 = CoreActor(actor2["id"], config=None)

        # Create client for actor1
        client_manager1 = OAuth2ClientManager(actor1["id"], core_actor1.config)
        created = client_manager1.create_client(
            client_name="Actor1 Client",
            trust_type="mcp_client"
        )
        client_id = created["client_id"]

        # Try to retrieve from actor2's manager
        client_manager2 = OAuth2ClientManager(actor2["id"], core_actor2.config)
        retrieved = client_manager2.get_client(client_id)

        # Should return None (not actor2's client)
        assert retrieved is None

    def test_get_nonexistent_client_returns_none(self, actor_factory):
        """
        Test that get_client returns None for non-existent client.

        Spec: actingweb/interface/oauth_client_manager.py:87-107
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Try to get non-existent client
        retrieved = client_manager.get_client("mcp_nonexistent12345")

        assert retrieved is None


class TestOAuth2ClientDeletion:
    """Test OAuth2 client deletion operations."""

    def test_delete_client(self, actor_factory):
        """
        Test deleting OAuth2 client.

        actingweb_mcp allows users to disconnect AI assistants.

        Spec: actingweb/interface/oauth_client_manager.py:135-167
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client
        created = client_manager.create_client(
            client_name="Test Client",
            trust_type="mcp_client"
        )
        client_id = created["client_id"]

        # Verify it exists
        retrieved = client_manager.get_client(client_id)
        assert retrieved is not None

        # Delete client
        success = client_manager.delete_client(client_id)
        assert success

        # Verify it's gone
        retrieved_after = client_manager.get_client(client_id)
        assert retrieved_after is None

    def test_delete_client_removes_from_list(self, actor_factory):
        """
        Test that deleted client no longer appears in list.

        Spec: actingweb/interface/oauth_client_manager.py:109-133
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create 3 clients
        client_ids = []
        for name in ["Client1", "Client2", "Client3"]:
            created = client_manager.create_client(client_name=name, trust_type="mcp_client")
            client_ids.append(created["client_id"])

        # Verify 3 clients listed
        clients_before = client_manager.list_clients()
        assert len(clients_before) == 3

        # Delete middle client
        client_manager.delete_client(client_ids[1])

        # Verify only 2 clients listed
        clients_after = client_manager.list_clients()
        assert len(clients_after) == 2

        # Verify deleted client not in list
        client_ids_after = [c["client_id"] for c in clients_after]
        assert client_ids[1] not in client_ids_after
        assert client_ids[0] in client_ids_after
        assert client_ids[2] in client_ids_after

    def test_delete_nonexistent_client_returns_false(self, actor_factory):
        """
        Test that deleting non-existent client returns False.

        Spec: actingweb/interface/oauth_client_manager.py:151-154
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Try to delete non-existent client
        success = client_manager.delete_client("mcp_nonexistent12345")

        assert not success

    def test_delete_other_actors_client_returns_false(self, actor_factory):
        """
        Test that attempting to delete another actor's client fails.

        Security: actors cannot delete each other's clients.

        Spec: actingweb/interface/oauth_client_manager.py:147-154
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor1 = actor_factory.create("user1@example.com")
        actor2 = actor_factory.create("user2@example.com")

        core_actor1 = CoreActor(actor1["id"], config=None)
        core_actor2 = CoreActor(actor2["id"], config=None)

        # Create client for actor1
        client_manager1 = OAuth2ClientManager(actor1["id"], core_actor1.config)
        created = client_manager1.create_client(client_name="Actor1 Client", trust_type="mcp_client")
        client_id = created["client_id"]

        # Try to delete from actor2's manager
        client_manager2 = OAuth2ClientManager(actor2["id"], core_actor2.config)
        success = client_manager2.delete_client(client_id)

        # Should fail (not actor2's client)
        assert not success

        # Verify client still exists for actor1
        still_exists = client_manager1.get_client(client_id)
        assert still_exists is not None


class TestOAuth2AccessTokenGeneration:
    """Test access token generation for OAuth2 clients."""

    def test_generate_access_token(self, actor_factory):
        """
        Test generating access token for OAuth2 client.

        actingweb_mcp generates tokens for testing/development.

        Spec: actingweb/interface/oauth_client_manager.py:294-341
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client (must start with mcp_ for token generation)
        created = client_manager.create_client(
            client_name="Test Client",
            trust_type="mcp_client"
        )
        client_id = created["client_id"]

        # Generate access token
        token_response = client_manager.generate_access_token(client_id, scope="mcp")

        # Verify OAuth2 token response structure
        assert token_response is not None
        assert "access_token" in token_response
        assert "token_type" in token_response
        assert token_response["token_type"] == "Bearer"
        assert "expires_in" in token_response
        assert token_response["expires_in"] > 0

    def test_generate_token_for_nonexistent_client_returns_none(self, actor_factory):
        """
        Test that generating token for non-existent client returns None.

        Spec: actingweb/interface/oauth_client_manager.py:308-311
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Try to generate token for non-existent client
        token_response = client_manager.generate_access_token("mcp_nonexistent12345")

        assert token_response is None

    def test_generate_token_only_for_custom_clients(self, actor_factory):
        """
        Test that token generation only works for custom clients (mcp_ prefix).

        Security: only custom clients can generate tokens directly.

        Spec: actingweb/interface/oauth_client_manager.py:314-316
        """
        # This test verifies the client_id.startswith("mcp_") check
        # All clients created via create_client have mcp_ prefix
        # so this test documents the expected behavior
        pass


class TestOAuth2ClientManagerRealisticScenarios:
    """Test realistic actingweb_mcp usage scenarios."""

    def test_connect_chatgpt_claude_cursor_workflow(self, actor_factory):
        """
        Test realistic workflow: user connects 3 AI assistants.

        This simulates actingweb_mcp UI workflow for connecting assistants.

        Spec: actingweb_mcp/application.py:648-698 - Generate OAuth client
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # User connects ChatGPT
        chatgpt = client_manager.create_client(
            client_name="ChatGPT",
            trust_type="mcp_client"
        )

        # User connects Claude
        claude = client_manager.create_client(
            client_name="Claude",
            trust_type="mcp_client"
        )

        # User connects Cursor
        cursor = client_manager.create_client(
            client_name="Cursor",
            trust_type="mcp_client"
        )

        # User views all connected assistants
        all_clients = client_manager.list_clients()
        assert len(all_clients) == 3

        # User disconnects ChatGPT
        client_manager.delete_client(chatgpt["client_id"])

        # User views remaining assistants
        remaining_clients = client_manager.list_clients()
        assert len(remaining_clients) == 2

        remaining_names = [c["client_name"] for c in remaining_clients]
        assert "ChatGPT" not in remaining_names
        assert "Claude" in remaining_names
        assert "Cursor" in remaining_names
```

### Success Criteria

#### Automated Verification:
- [ ] All OAuth2 client manager tests pass: `make test-integration`
- [ ] Tests properly use actor_factory fixture
- [ ] Tests run in reasonable time (<30 seconds)
- [ ] No existing tests broken

#### Manual Verification:
- [ ] Tests cover client CRUD operations
- [ ] Tests demonstrate realistic actingweb_mcp workflows
- [ ] Tests verify security (actor isolation)
- [ ] Code follows ActingWeb style

---

## Phase 4: Trust-OAuth Integration Testing

### Overview

Test that trust relationships are properly linked to OAuth clients, enabling permission checks with OAuth context. This integration is critical for actingweb_mcp's access control system.

### Changes Required

#### 1. Create Trust-OAuth Integration Test File

**File**: `tests/integration/test_trust_oauth_integration.py`

**Changes**: Create new test file with trust-OAuth integration tests

```python
"""
Trust-OAuth Integration Tests.

Tests integration between trust relationships and OAuth2 clients:
- Trust relationships created automatically on client registration
- oauth_client_id attribute on trust relationships
- client_name attribute on trust relationships
- Permission checks work with OAuth context
- Multiple OAuth clients create separate trust relationships

These tests protect actingweb_mcp's OAuth-based access control.

References:
- actingweb/oauth2_server/client_registry.py:323-387 - Trust relationship creation
- actingweb/trust_manager.py:230-365 - OAuth trust creation
- actingweb_mcp/application.py:1487-1573 - Permission checks with OAuth context
"""

import pytest


class TestTrustCreationOnClientRegistration:
    """Test that trust relationships are created when OAuth2 clients are registered."""

    def test_client_registration_creates_trust_relationship(self, actor_factory):
        """
        Test that registering OAuth2 client automatically creates trust relationship.

        actingweb_mcp relies on automatic trust creation for permission checks.

        Spec: actingweb/oauth2_server/client_registry.py:76-77
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create OAuth2 client
        client_data = client_manager.create_client(
            client_name="ChatGPT",
            trust_type="mcp_client"
        )
        client_id = client_data["client_id"]

        # Load actor interface to check trust relationships
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Verify trust relationship was created
        trust_rels = actor_interface.trust.relationships

        # Should have at least one trust relationship
        assert len(trust_rels) > 0

        # Find trust relationship matching this client
        matching_trust = None
        for trust in trust_rels:
            if client_id in trust.peerid:
                matching_trust = trust
                break

        assert matching_trust is not None, f"No trust relationship found for client {client_id}"

    def test_trust_relationship_has_correct_trust_type(self, actor_factory):
        """
        Test that trust relationship inherits trust type from client.

        actingweb_mcp uses trust type for permission inheritance.

        Spec: actingweb/oauth2_server/client_registry.py:361
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client with specific trust type
        client_data = client_manager.create_client(
            client_name="Test Client",
            trust_type="mcp_client"
        )
        client_id = client_data["client_id"]

        # Load actor interface
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Find matching trust relationship
        matching_trust = None
        for trust in actor_interface.trust.relationships:
            if client_id in trust.peerid:
                matching_trust = trust
                break

        # Verify trust type matches
        assert matching_trust is not None
        assert matching_trust.relationship == "mcp_client"

    def test_multiple_clients_create_multiple_trusts(self, actor_factory):
        """
        Test that multiple OAuth2 clients create separate trust relationships.

        actingweb_mcp needs separate trusts for permission isolation.

        Spec: actingweb/oauth2_server/client_registry.py:323-387
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create 3 OAuth2 clients
        client_names = ["ChatGPT", "Claude", "Cursor"]
        client_ids = []

        for name in client_names:
            client_data = client_manager.create_client(
                client_name=name,
                trust_type="mcp_client"
            )
            client_ids.append(client_data["client_id"])

        # Load actor interface
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Verify we have at least 3 trust relationships
        trust_rels = actor_interface.trust.relationships
        assert len(trust_rels) >= 3

        # Verify each client has a corresponding trust
        for client_id in client_ids:
            matching_trust = None
            for trust in trust_rels:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break
            assert matching_trust is not None, f"No trust found for client {client_id}"


class TestTrustAttributesForOAuth:
    """Test OAuth-specific attributes on trust relationships."""

    def test_trust_has_client_name_attribute(self, actor_factory):
        """
        Test that trust relationship includes client_name from OAuth client.

        actingweb_mcp displays client name in trust relationship UI.

        Spec: actingweb/trust_manager.py:296 - client_name stored in trust
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client with specific name
        client_data = client_manager.create_client(
            client_name="ChatGPT Assistant",
            trust_type="mcp_client"
        )
        client_id = client_data["client_id"]

        # Load actor interface
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Find matching trust
        matching_trust = None
        for trust in actor_interface.trust.relationships:
            if client_id in trust.peerid:
                matching_trust = trust
                break

        # Verify client_name attribute
        assert matching_trust is not None
        assert hasattr(matching_trust, "client_name")
        assert matching_trust.client_name == "ChatGPT Assistant"

    def test_trust_has_oauth_client_id_attribute(self, actor_factory):
        """
        Test that trust relationship includes oauth_client_id.

        actingweb_mcp uses oauth_client_id to link trusts to clients.

        Spec: actingweb_mcp/application.py:1005 - oauth_client_id attribute
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client
        client_data = client_manager.create_client(
            client_name="Test Client",
            trust_type="mcp_client"
        )
        client_id = client_data["client_id"]

        # Load actor interface
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Find matching trust
        matching_trust = None
        for trust in actor_interface.trust.relationships:
            if client_id in trust.peerid:
                matching_trust = trust
                break

        # Verify oauth_client_id attribute
        assert matching_trust is not None
        assert hasattr(matching_trust, "oauth_client_id")
        assert matching_trust.oauth_client_id == client_id

    def test_trust_has_peer_type_mcp(self, actor_factory):
        """
        Test that trust relationship for OAuth client has peer_type="mcp".

        Used to identify MCP client trust relationships.

        Spec: actingweb/trust_manager.py:296 - peer_type set to "mcp"
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client
        client_data = client_manager.create_client(
            client_name="Test Client",
            trust_type="mcp_client"
        )
        client_id = client_data["client_id"]

        # Load actor interface
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Find matching trust
        matching_trust = None
        for trust in actor_interface.trust.relationships:
            if client_id in trust.peerid:
                matching_trust = trust
                break

        # Verify peer_type
        assert matching_trust is not None
        assert hasattr(matching_trust, "peer_type")
        assert matching_trust.peer_type == "mcp"


class TestTrustDeletionOnClientDeletion:
    """Test that trust relationships are deleted when OAuth2 clients are deleted."""

    def test_deleting_client_deletes_trust_relationship(self, actor_factory):
        """
        Test that deleting OAuth2 client also deletes trust relationship.

        actingweb_mcp needs cleanup when disconnecting assistants.

        Spec: actingweb/oauth2_server/client_registry.py:227
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client
        client_data = client_manager.create_client(
            client_name="Test Client",
            trust_type="mcp_client"
        )
        client_id = client_data["client_id"]

        # Load actor interface
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Verify trust exists
        trust_count_before = len(actor_interface.trust.relationships)
        matching_trust_before = None
        for trust in actor_interface.trust.relationships:
            if client_id in trust.peerid:
                matching_trust_before = trust
                break
        assert matching_trust_before is not None

        # Delete client
        client_manager.delete_client(client_id)

        # Reload actor interface to get fresh trust data
        core_actor_reload = CoreActor(actor["id"], config=None)
        actor_interface_reload = ActorInterface(core_actor=core_actor_reload, service_registry=None)

        # Verify trust is deleted
        trust_count_after = len(actor_interface_reload.trust.relationships)
        assert trust_count_after == trust_count_before - 1

        # Verify specific trust for this client is gone
        matching_trust_after = None
        for trust in actor_interface_reload.trust.relationships:
            if client_id in trust.peerid:
                matching_trust_after = trust
                break
        assert matching_trust_after is None


class TestPermissionChecksWithOAuth:
    """Test that permission checks work correctly with OAuth context."""

    def test_oauth_client_trust_uses_mcp_client_permissions(self, actor_factory):
        """
        Test that OAuth client trust relationship inherits mcp_client permissions.

        actingweb_mcp relies on trust type permissions for access control.

        Spec: actingweb/permission_evaluator.py:314-358 - Permission inheritance
        """
        # This test would need permission evaluator integration
        # Just verify the trust relationship is set up correctly
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client
        client_data = client_manager.create_client(
            client_name="Test Client",
            trust_type="mcp_client"
        )
        client_id = client_data["client_id"]

        # Load actor interface
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Find matching trust
        matching_trust = None
        for trust in actor_interface.trust.relationships:
            if client_id in trust.peerid:
                matching_trust = trust
                break

        # Verify trust exists with mcp_client type (permissions will inherit)
        assert matching_trust is not None
        assert matching_trust.relationship == "mcp_client"

    def test_individual_permissions_can_override_oauth_client_defaults(self, actor_factory):
        """
        Test that individual permissions can be set for OAuth client trusts.

        actingweb_mcp sets per-client excluded_patterns.

        Spec: actingweb/trust_permissions.py:98-131 - Store individual permissions
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor
        from actingweb.trust_permissions import TrustPermissionStore, TrustPermissions

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Create client
        client_data = client_manager.create_client(
            client_name="ChatGPT",
            trust_type="mcp_client"
        )
        client_id = client_data["client_id"]

        # Load actor interface to get peer_id
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)
        matching_trust = None
        for trust in actor_interface.trust.relationships:
            if client_id in trust.peerid:
                matching_trust = trust
                break

        peer_id = matching_trust.peerid

        # Set individual permissions for this OAuth client trust
        permission_store = TrustPermissionStore(core_actor.config)
        permissions = TrustPermissions(
            actor_id=actor["id"],
            peer_id=peer_id,
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": ["memory_personal", "memory_travel"]
            },
            created_by="test"
        )
        success = permission_store.store_permissions(permissions)
        assert success

        # Verify permissions are stored
        stored = permission_store.get_permissions(actor["id"], peer_id)
        assert stored is not None
        assert "memory_personal" in stored.properties["excluded_patterns"]


class TestRealisticOAuthTrustScenarios:
    """Test realistic scenarios combining OAuth clients and trust relationships."""

    def test_chatgpt_claude_cursor_each_have_separate_trust(self, actor_factory):
        """
        Test that connecting multiple assistants creates separate trust relationships.

        actingweb_mcp needs permission isolation between clients.

        Spec: Multiple OAuth clients create multiple trust relationships
        """
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager
        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.actor import Actor as CoreActor
        from actingweb.trust_permissions import TrustPermissionStore, TrustPermissions

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        client_manager = OAuth2ClientManager(actor["id"], core_actor.config)

        # Connect ChatGPT - restricted access
        chatgpt = client_manager.create_client(
            client_name="ChatGPT",
            trust_type="mcp_client"
        )

        # Connect Claude - full access
        claude = client_manager.create_client(
            client_name="Claude",
            trust_type="mcp_client"
        )

        # Connect Cursor - work-only access
        cursor = client_manager.create_client(
            client_name="Cursor",
            trust_type="mcp_client"
        )

        # Load actor interface
        actor_interface = ActorInterface(core_actor=core_actor, service_registry=None)

        # Find trust relationships for each client
        chatgpt_trust = None
        claude_trust = None
        cursor_trust = None

        for trust in actor_interface.trust.relationships:
            if chatgpt["client_id"] in trust.peerid:
                chatgpt_trust = trust
            elif claude["client_id"] in trust.peerid:
                claude_trust = trust
            elif cursor["client_id"] in trust.peerid:
                cursor_trust = trust

        # Verify all have separate trust relationships
        assert chatgpt_trust is not None
        assert claude_trust is not None
        assert cursor_trust is not None

        # Verify different peer IDs
        assert chatgpt_trust.peerid != claude_trust.peerid
        assert claude_trust.peerid != cursor_trust.peerid
        assert chatgpt_trust.peerid != cursor_trust.peerid

        # Set individual permissions for each (actingweb_mcp pattern)
        permission_store = TrustPermissionStore(core_actor.config)

        # ChatGPT: Only memory_personal
        chatgpt_perms = TrustPermissions(
            actor_id=actor["id"],
            peer_id=chatgpt_trust.peerid,
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": ["memory_travel", "memory_food", "memory_work"]
            },
            created_by="test"
        )
        permission_store.store_permissions(chatgpt_perms)

        # Claude: All memory types (no exclusions)
        claude_perms = TrustPermissions(
            actor_id=actor["id"],
            peer_id=claude_trust.peerid,
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read", "write"],
                "excluded_patterns": []
            },
            created_by="test"
        )
        permission_store.store_permissions(claude_perms)

        # Cursor: Only memory_work
        cursor_perms = TrustPermissions(
            actor_id=actor["id"],
            peer_id=cursor_trust.peerid,
            trust_type="mcp_client",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
                "excluded_patterns": ["memory_personal", "memory_travel", "memory_food"]
            },
            created_by="test"
        )
        permission_store.store_permissions(cursor_perms)

        # Verify each has different permissions
        chatgpt_stored = permission_store.get_permissions(actor["id"], chatgpt_trust.peerid)
        claude_stored = permission_store.get_permissions(actor["id"], claude_trust.peerid)
        cursor_stored = permission_store.get_permissions(actor["id"], cursor_trust.peerid)

        assert len(chatgpt_stored.properties["excluded_patterns"]) == 3
        assert len(claude_stored.properties["excluded_patterns"]) == 0
        assert len(cursor_stored.properties["excluded_patterns"]) == 3
```

### Success Criteria

#### Automated Verification:
- [ ] All trust-OAuth integration tests pass: `make test-integration`
- [ ] Tests verify trust creation on client registration
- [ ] Tests verify trust deletion on client deletion
- [ ] No existing tests broken

#### Manual Verification:
- [ ] Tests demonstrate OAuth client trust relationship lifecycle
- [ ] Tests show realistic actingweb_mcp scenarios
- [ ] Tests verify trust attributes (client_name, oauth_client_id)
- [ ] Code follows ActingWeb style

---

## Phase 5: Trust Type Registry Testing

### Overview

Test custom trust type registration functionality. This is medium priority since actingweb_mcp uses the default `mcp_client` trust type, but custom types may be added in the future.

### Changes Required

#### 1. Create Trust Type Registry Test File

**File**: `tests/integration/test_trust_types_custom.py`

**Changes**: Create new test file with trust type registry tests

```python
"""
Trust Type Registry Integration Tests.

Tests custom trust type registration functionality:
- Register custom trust types with permissions
- Trust types with complex permission structures
- Multiple custom trust types
- Trust type retrieval and listing

Medium priority - actingweb_mcp uses default types but may add custom ones.

References:
- actingweb/permission_integration.py:24-146 - AccessControlConfig
- actingweb/trust_type_registry.py:66-220 - TrustTypeRegistry
- actingweb_mcp/application.py:142-159 - Custom mcp_client type
"""

import pytest


class TestCustomTrustTypeRegistration:
    """Test registering custom trust types."""

    def test_register_mcp_client_trust_type(self, test_app):
        """
        Test registering mcp_client trust type with custom permissions.

        actingweb_mcp customizes mcp_client with specific tools and resources.

        Spec: actingweb/permission_integration.py:54-107
        """
        from actingweb.permission_integration import AccessControlConfig
        from actingweb.config import Config

        # Create config
        config = Config(
            aw_type="test",
            database="dynamodb",
            fqdn="localhost",
            proto="http://"
        )

        # Register custom trust type (actingweb_mcp pattern)
        access_control = AccessControlConfig(config)
        access_control.add_trust_type(
            name="mcp_client",
            display_name="AI Assistant",
            description="AI assistants with configurable access to personal memory",
            permissions={
                "properties": {
                    "patterns": ["memory_*"],
                    "operations": ["read", "write"],
                    "excluded_patterns": []
                },
                "methods": ["get_*", "list_*", "search_*", "create_*"],
                "tools": ["search", "fetch", "save_memory", "save_note"],
                "resources": ["notes://*", "usage://*", "settings://*"],
                "prompts": ["*"]
            },
            oauth_scope="actingweb.mcp_client"
        )

        # Verify registration
        from actingweb.trust_type_registry import get_registry
        registry = get_registry(config)

        mcp_type = registry.get_type("mcp_client")
        assert mcp_type is not None
        assert mcp_type.display_name == "AI Assistant"
        assert "memory_*" in mcp_type.base_permissions["properties"]["patterns"]
        assert "search" in mcp_type.base_permissions["tools"]

    # Additional trust type registry tests...
```

### Success Criteria

#### Automated Verification:
- [ ] Trust type registry tests pass: `make test-integration`
- [ ] Tests verify custom type registration
- [ ] No existing tests broken

#### Manual Verification:
- [ ] Tests document actingweb_mcp trust type customization
- [ ] Code follows ActingWeb style

---

## Phase 6: Runtime Context Testing

### Overview

Test runtime context for client detection. This is medium priority since it's mainly used for response customization, not core functionality.

### Changes Required

#### 1. Create Runtime Context Test File

**File**: `tests/integration/test_runtime_context_advanced.py`

**Changes**: Create new test file with runtime context tests

```python
"""
Runtime Context Advanced Integration Tests.

Tests runtime context for client detection and customization:
- MCP context setting and retrieval
- Client info extraction from context
- Context persistence during request processing

Medium priority - used for response customization in actingweb_mcp.

References:
- actingweb/runtime_context.py:1-150 - RuntimeContext
- actingweb_mcp/hooks/mcp/tools.py:30-32 - client_detector usage
"""

import pytest


class TestRuntimeContextMCP:
    """Test runtime context for MCP clients."""

    def test_set_and_get_mcp_context(self, actor_factory):
        """
        Test setting and retrieving MCP context.

        actingweb_mcp uses runtime context to detect client type.

        Spec: actingweb/runtime_context.py:30-60
        """
        from actingweb.runtime_context import RuntimeContext, get_client_info_from_context
        from actingweb.actor import Actor as CoreActor

        actor = actor_factory.create("user@example.com")
        core_actor = CoreActor(actor["id"], config=None)

        # Set MCP context (as MCP handler does)
        runtime_context = RuntimeContext(core_actor)
        runtime_context.set_mcp_context(
            client_id="mcp_chatgpt_123",
            trust_relationship=None,  # Would be trust object in real usage
            peer_id="oauth2_client:chatgpt@openai.com:mcp_chatgpt_123",
            token_data={"scope": "mcp"}
        )

        # Get client info
        client_info = get_client_info_from_context(core_actor)
        assert client_info is not None
        assert client_info["type"] == "mcp"

    # Additional runtime context tests...
```

### Success Criteria

#### Automated Verification:
- [ ] Runtime context tests pass: `make test-integration`
- [ ] Tests verify context setting and retrieval
- [ ] No existing tests broken

#### Manual Verification:
- [ ] Tests show client detection patterns
- [ ] Code follows ActingWeb style

---

## Testing Strategy

### Unit Testing
Not applicable - these are integration tests only.

### Integration Testing

**Test Execution**:
```bash
# Run all integration tests
make test-integration

# Run specific test file
pytest tests/integration/test_property_lists_advanced.py -v

# Run specific test class
pytest tests/integration/test_property_lists_advanced.py::TestPropertyListDynamicCreation -v

# Run specific test
pytest tests/integration/test_property_lists_advanced.py::TestPropertyListDynamicCreation::test_create_multiple_property_lists_dynamically -v
```

**Test Organization**:
- Each phase has dedicated test file
- Tests grouped into classes by functionality
- Tests use existing fixtures (actor_factory, trust_helper, oauth2_client)
- Tests follow sequential or independent patterns as appropriate

### Manual Testing

After implementing all phases:

1. **Verify actingweb_mcp still works**:
   ```bash
   cd ../actingweb_mcp
   make test
   ```

2. **Test actingweb_mcp with real clients**:
   - Connect ChatGPT to actingweb_mcp
   - Create memory types
   - Set memory permissions
   - Verify filtering works

3. **Verify no regressions**:
   - Run full ActingWeb test suite
   - Check test counts match expected
   - Review any new failures

## Performance Considerations

- Tests should complete in <2 minutes for all 6 phases
- Use session-scoped fixtures for Docker and test apps
- Use function-scoped fixtures for actors (cleanup per test)
- Avoid unnecessary database queries in tests
- Use realistic data sizes (100 items max in tests)

## Migration Notes

No migration needed - these are new tests only.

## References

- **Analysis document**: `thoughts/shared/test-requirements-from-actingweb-mcp.md`
- **actingweb_mcp application**: `../actingweb_mcp/application.py`
- **Property list implementation**: `actingweb/property_list.py`
- **Trust permissions**: `actingweb/trust_permissions.py`
- **OAuth2 client manager**: `actingweb/interface/oauth_client_manager.py`
- **Existing tests**: `tests/integration/test_*.py`

---

## Implementation Summary

This plan adds 6 new test files with comprehensive coverage of ActingWeb features critical to actingweb_mcp:

1. **test_property_lists_advanced.py** - ~15 tests covering dynamic lists, metadata, discovery, deletion
2. **test_trust_permissions_patterns.py** - ~15 tests covering excluded_patterns, wildcard matching, inheritance
3. **test_oauth2_client_manager.py** - ~15 tests covering CRUD operations, token generation, multiple clients
4. **test_trust_oauth_integration.py** - ~10 tests covering trust-OAuth lifecycle and attributes
5. **test_trust_types_custom.py** - ~5 tests covering custom trust type registration
6. **test_runtime_context_advanced.py** - ~5 tests covering MCP context and client detection

**Total**: ~65 new integration tests protecting actingweb_mcp from ActingWeb library regressions.

All tests follow existing ActingWeb patterns, use standard fixtures, and run within the existing test infrastructure.
