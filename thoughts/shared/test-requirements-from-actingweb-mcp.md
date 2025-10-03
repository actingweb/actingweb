---
date: 2025-10-03
author: Claude
topic: "ActingWeb Library Test Requirements Based on actingweb_mcp Usage"
tags: [testing, actingweb_mcp, permissions, trust, property-lists, mcp]
status: analysis
---

# ActingWeb Library Test Requirements Based on actingweb_mcp Usage

## Overview

This document analyzes the actingweb_mcp application to identify critical functionality that the ActingWeb library test suite must validate to prevent regressions when improving the library.

## actingweb_mcp Architecture Summary

The actingweb_mcp application is an MCP (Model Context Protocol) server that:

1. **Exposes personal memory storage** via MCP tools (`search`, `fetch`, `save_memory`, `save_note`)
2. **Uses property lists** to store different memory types (`memory_personal`, `memory_travel`, `memory_food`, etc.)
3. **Controls access per relationship** using ActingWeb's trust permission system
4. **Filters memory types per MCP client** using `excluded_patterns` in trust permissions

### Key Permission Pattern

```python
# Example from application.py:1487-1573
def check_memory_access_permission(actor, peerid, relationship, memory_type):
    """Check if MCP client can access specific memory type"""
    # 1. Get trust relationship
    trust = actor.trust.get_relationship(peerid)

    # 2. Check individual permission overrides
    permission_store = TrustPermissionStore(config)
    stored_permissions = permission_store.get_permissions(actor.id, peerid)

    if stored_permissions and stored_permissions.properties:
        excluded_patterns = stored_permissions.properties.get("excluded_patterns", [])
        # If memory type is in excluded patterns, deny access
        if memory_type in excluded_patterns:
            return False

    # 3. Fall back to trust type defaults
    registry = get_registry(config)
    trust_type = registry.get_type(relationship)
    if trust_type and trust_type.base_permissions:
        patterns = trust_type.base_permissions["properties"]["patterns"]
        if fnmatch.fnmatch(memory_type, pattern):
            return True

    return False
```

## Critical Test Requirements for ActingWeb Library

### 1. **Property List Core Functionality**

**Why Critical**: actingweb_mcp stores all memory in property lists with dynamic names

**Required Tests**:

```python
# Test: Dynamic property list creation and access
def test_property_list_dynamic_creation(actor_factory):
    """Test that property lists can be created dynamically with any name."""
    actor = actor_factory.create("test@example.com")

    # Create multiple property lists dynamically
    memory_types = ["memory_personal", "memory_travel", "memory_food", "memory_health"]

    for memory_type in memory_types:
        prop_list = getattr(actor.property_lists, memory_type)
        prop_list.append({"id": 1, "content": "test data", "created_at": "2025-10-03"})

    # Verify all exist
    all_lists = actor.property_lists.list_all()
    assert all(mt in all_lists for mt in memory_types)

    # Verify content retrieval
    personal_list = getattr(actor.property_lists, "memory_personal")
    items = personal_list.to_list()
    assert len(items) == 1
    assert items[0]["content"] == "test data"

# Test: Property list metadata storage and retrieval
def test_property_list_metadata_persistence(actor_factory):
    """Test that metadata stored in first item persists correctly."""
    actor = actor_factory.create("test@example.com")

    prop_list = getattr(actor.property_lists, "memory_travel")

    # Store metadata as first item (actingweb_mcp pattern)
    metadata = {
        "type_name": "memory_travel",
        "display_name": "Travel Memories",
        "description": "Travel plans and memories",
        "emoji": "✈️",
        "keywords": ["flight", "hotel", "vacation"],
        "created_at": "2025-10-03T10:00:00",
        "created_by": "mcp_auto"
    }
    prop_list.insert(0, metadata)

    # Add actual data items
    prop_list.append({"id": 1, "content": "Paris trip 2025"})
    prop_list.append({"id": 2, "content": "Tokyo flight booked"})

    # Retrieve and verify
    items = prop_list.to_list()
    assert len(items) == 3
    assert items[0]["type_name"] == "memory_travel"
    assert items[1]["content"] == "Paris trip 2025"

# Test: Property list deletion
def test_property_list_complete_deletion(actor_factory):
    """Test that property lists can be completely deleted."""
    actor = actor_factory.create("test@example.com")

    # Create and populate
    prop_list = getattr(actor.property_lists, "memory_temp")
    prop_list.append({"content": "temp data"})
    assert actor.property_lists.exists("memory_temp")

    # Delete
    prop_list.delete()

    # Verify deletion
    assert not actor.property_lists.exists("memory_temp")
    all_lists = actor.property_lists.list_all()
    assert "memory_temp" not in all_lists

# Test: Property list exists() check
def test_property_list_exists_check(actor_factory):
    """Test exists() method for property lists."""
    actor = actor_factory.create("test@example.com")

    # Non-existent list
    assert not actor.property_lists.exists("memory_nonexistent")

    # Create list by accessing it
    prop_list = getattr(actor.property_lists, "memory_test")
    prop_list.append({"data": "test"})

    # Should now exist
    assert actor.property_lists.exists("memory_test")

# Test: Property list item indexing and deletion
def test_property_list_item_deletion_by_index(actor_factory):
    """Test deleting items from property list by index."""
    actor = actor_factory.create("test@example.com")

    prop_list = getattr(actor.property_lists, "memory_notes")

    # Add multiple items
    for i in range(5):
        prop_list.append({"id": i+1, "content": f"Note {i+1}"})

    # Delete item at index 2 (third item)
    del prop_list[2]

    items = prop_list.to_list()
    assert len(items) == 4
    # Verify the right item was deleted
    assert {"id": 3, "content": "Note 3"} not in items
```

### 2. **Trust Permissions with Pattern Matching**

**Why Critical**: actingweb_mcp uses pattern-based permissions to control memory access

**Required Tests**:

```python
# Test: Trust permissions with excluded_patterns
def test_trust_permissions_excluded_patterns(actor_factory, trust_helper):
    """Test that excluded_patterns in trust permissions work correctly."""
    actor1 = actor_factory.create("user@example.com")
    actor2 = actor_factory.create("mcp_client@example.com")

    # Establish trust with mcp_client relationship
    trust = trust_helper.establish(actor2, actor1, "mcp_client", approve=True)

    # Create memory types
    for memory_type in ["memory_personal", "memory_travel", "memory_food"]:
        prop_list = getattr(actor1.property_lists, memory_type)
        prop_list.append({"content": "test data"})

    # Set up permissions: allow memory_* but exclude memory_personal and memory_travel
    from actingweb.trust_permissions import TrustPermissionStore, TrustPermissions

    permission_store = TrustPermissionStore(actor1.config)
    permissions = TrustPermissions(
        actor_id=actor1.id,
        peer_id=actor2.id,
        trust_type="mcp_client",
        properties={
            "patterns": ["memory_*"],
            "operations": ["read", "write"],
            "excluded_patterns": ["memory_personal", "memory_travel"]
        },
        created_by="test"
    )
    permission_store.store_permissions(permissions)

    # Verify permissions
    stored = permission_store.get_permissions(actor1.id, actor2.id)
    assert "memory_personal" in stored.properties["excluded_patterns"]
    assert "memory_travel" in stored.properties["excluded_patterns"]
    assert "memory_food" not in stored.properties["excluded_patterns"]

# Test: Pattern matching with wildcards
def test_trust_permissions_wildcard_patterns(actor_factory):
    """Test that wildcard patterns match correctly."""
    actor = actor_factory.create("test@example.com")

    # Create various memory types
    memory_types = [
        "memory_personal",
        "memory_travel_plans",
        "memory_food_preferences",
        "settings_private"  # Should not match memory_*
    ]

    for mt in memory_types:
        prop_list = getattr(actor.property_lists, mt)
        prop_list.append({"data": "test"})

    # Test pattern matching
    import fnmatch
    pattern = "memory_*"

    matching = [mt for mt in memory_types if fnmatch.fnmatch(mt, pattern)]
    assert len(matching) == 3
    assert "memory_personal" in matching
    assert "memory_travel_plans" in matching
    assert "memory_food_preferences" in matching
    assert "settings_private" not in matching

# Test: Trust permissions inheritance and overrides
def test_trust_permissions_inheritance_from_trust_type(actor_factory):
    """Test that individual permissions can override trust type defaults."""
    actor = actor_factory.create("user@example.com")

    # Trust type "mcp_client" has default permissions for memory_*
    # Individual relationship can override with excluded_patterns

    # This should be testable by:
    # 1. Getting trust type default permissions
    # 2. Setting individual permissions with exclusions
    # 3. Verifying individual permissions take precedence

# Test: Permission updates and retrieval
def test_trust_permissions_update_and_retrieve(actor_factory):
    """Test updating existing trust permissions."""
    actor1 = actor_factory.create("user@example.com")
    actor2 = actor_factory.create("client@example.com")

    from actingweb.trust_permissions import TrustPermissionStore, TrustPermissions

    permission_store = TrustPermissionStore(actor1.config)

    # Create initial permissions
    permissions = TrustPermissions(
        actor_id=actor1.id,
        peer_id=actor2.id,
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
    stored = permission_store.get_permissions(actor1.id, actor2.id)
    stored.properties["excluded_patterns"].append("memory_personal")
    stored.properties["operations"].append("write")

    # Update
    permission_store.store_permissions(stored)

    # Verify updates persisted
    updated = permission_store.get_permissions(actor1.id, actor2.id)
    assert "memory_personal" in updated.properties["excluded_patterns"]
    assert "write" in updated.properties["operations"]
```

### 3. **Trust Type Registry with Custom Types**

**Why Critical**: actingweb_mcp defines custom trust type "mcp_client" with specific permissions

**Required Tests**:

```python
# Test: Custom trust type registration
def test_custom_trust_type_registration():
    """Test registering custom trust types with permissions."""
    from actingweb.permission_integration import AccessControlConfig
    from actingweb.config import Config

    config = Config(
        aw_type="test",
        database="dynamodb",
        fqdn="localhost",
        proto="http://"
    )

    access_control = AccessControlConfig(config)

    # Register custom trust type (like actingweb_mcp does)
    access_control.add_trust_type(
        name="mcp_client",
        display_name="AI Assistant",
        description="AI assistants with configurable access",
        permissions={
            "properties": {
                "patterns": ["memory_*"],
                "operations": ["read", "write"],
                "excluded_patterns": []
            },
            "methods": ["get_*", "list_*", "search_*"],
            "tools": ["search", "fetch", "save_memory"],
            "resources": ["notes://*", "usage://*"],
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

# Test: Trust type default permissions
def test_trust_type_default_permissions():
    """Test that trust type default permissions are applied correctly."""
    # When no individual permissions exist, trust type defaults should apply
    pass

# Test: Multiple custom trust types
def test_multiple_custom_trust_types():
    """Test registering multiple custom trust types."""
    # actingweb_mcp could define: mcp_client, mcp_power_user, mcp_demo
    pass
```

### 4. **OAuth2 Client Manager Integration**

**Why Critical**: actingweb_mcp generates OAuth2 clients for MCP assistants

**Required Tests**:

```python
# Test: OAuth2 client creation via client manager
def test_oauth2_client_creation_with_trust_type(actor_factory):
    """Test creating OAuth2 client with specific trust type."""
    from actingweb.interface.oauth_client_manager import OAuth2ClientManager

    actor = actor_factory.create("user@example.com")

    client_manager = OAuth2ClientManager(actor.id, actor.config)

    # Create client with mcp_client trust type
    client_data = client_manager.create_client(
        client_name="ChatGPT",
        trust_type="mcp_client",
        client_uri="https://chatgpt.com",
        redirect_uris=["https://chatgpt.com/callback"]
    )

    assert client_data is not None
    assert client_data["client_name"] == "ChatGPT"
    assert client_data["trust_type"] == "mcp_client"
    assert "client_id" in client_data
    assert "client_secret" in client_data

# Test: OAuth2 client listing
def test_oauth2_client_listing(actor_factory):
    """Test listing OAuth2 clients for an actor."""
    actor = actor_factory.create("user@example.com")

    from actingweb.interface.oauth_client_manager import OAuth2ClientManager
    client_manager = OAuth2ClientManager(actor.id, actor.config)

    # Create multiple clients
    for name in ["ChatGPT", "Claude", "Cursor"]:
        client_manager.create_client(
            client_name=name,
            trust_type="mcp_client",
            client_uri=f"https://{name.lower()}.com",
            redirect_uris=[f"https://{name.lower()}.com/callback"]
        )

    # List clients
    clients = client_manager.list_clients()
    assert len(clients) == 3
    client_names = [c["client_name"] for c in clients]
    assert "ChatGPT" in client_names
    assert "Claude" in client_names

# Test: OAuth2 client deletion
def test_oauth2_client_deletion(actor_factory):
    """Test deleting OAuth2 clients."""
    actor = actor_factory.create("user@example.com")

    from actingweb.interface.oauth_client_manager import OAuth2ClientManager
    client_manager = OAuth2ClientManager(actor.id, actor.config)

    # Create client
    client_data = client_manager.create_client(
        client_name="Test Client",
        trust_type="mcp_client",
        client_uri="https://test.com",
        redirect_uris=["https://test.com/callback"]
    )

    client_id = client_data["client_id"]

    # Verify exists
    retrieved = client_manager.get_client(client_id)
    assert retrieved is not None

    # Delete
    success = client_manager.delete_client(client_id)
    assert success

    # Verify deleted
    retrieved = client_manager.get_client(client_id)
    assert retrieved is None

# Test: OAuth2 access token generation
def test_oauth2_access_token_generation(actor_factory):
    """Test generating access tokens for OAuth2 clients."""
    actor = actor_factory.create("user@example.com")

    from actingweb.interface.oauth_client_manager import OAuth2ClientManager
    client_manager = OAuth2ClientManager(actor.id, actor.config)

    # Create client
    client_data = client_manager.create_client(
        client_name="Test Client",
        trust_type="mcp_client",
        client_uri="https://test.com",
        redirect_uris=["https://test.com/callback"]
    )

    # Generate access token
    token_response = client_manager.generate_access_token(
        client_data["client_id"],
        scope="mcp"
    )

    assert token_response is not None
    assert "access_token" in token_response
    assert "token_type" in token_response
    assert token_response["token_type"] == "Bearer"
    assert "expires_in" in token_response
```

### 5. **Trust Relationship with OAuth Client Integration**

**Why Critical**: MCP clients create both trust relationships and OAuth clients

**Required Tests**:

```python
# Test: Trust relationship linked to OAuth client
def test_trust_relationship_with_oauth_client_id(actor_factory, trust_helper):
    """Test that trust relationships can be linked to OAuth clients."""
    actor1 = actor_factory.create("user@example.com")
    actor2 = actor_factory.create("chatgpt@openai.com")

    # Create OAuth client
    from actingweb.interface.oauth_client_manager import OAuth2ClientManager
    client_manager = OAuth2ClientManager(actor1.id, actor1.config)

    client_data = client_manager.create_client(
        client_name="ChatGPT",
        trust_type="mcp_client",
        client_uri="https://chatgpt.com",
        redirect_uris=["https://chatgpt.com/callback"]
    )

    # Establish trust
    trust = trust_helper.establish(actor2, actor1, "mcp_client", approve=True)

    # Link OAuth client to trust (this happens in actingweb_mcp)
    # The trust relationship should have oauth_client_id attribute
    trust_rel = actor1.trust.get_relationship(actor2.id)

    # Verify trust relationship attributes
    assert hasattr(trust_rel, "client_name")
    assert hasattr(trust_rel, "oauth_client_id")
    assert hasattr(trust_rel, "peer_identifier")

# Test: Multiple OAuth clients per actor
def test_multiple_oauth_clients_per_actor(actor_factory):
    """Test that one actor can have multiple OAuth clients."""
    actor = actor_factory.create("user@example.com")

    from actingweb.interface.oauth_client_manager import OAuth2ClientManager
    client_manager = OAuth2ClientManager(actor.id, actor.config)

    # Create 5 different MCP clients
    clients = []
    for i, name in enumerate(["ChatGPT", "Claude", "Cursor", "Windsurf", "Custom"]):
        client_data = client_manager.create_client(
            client_name=name,
            trust_type="mcp_client",
            client_uri=f"https://{name.lower()}.com",
            redirect_uris=[f"https://{name.lower()}.com/callback"]
        )
        clients.append(client_data)

    # Verify all exist
    all_clients = client_manager.list_clients()
    assert len(all_clients) == 5

    # Each should have unique client_id
    client_ids = [c["client_id"] for c in all_clients]
    assert len(client_ids) == len(set(client_ids))  # All unique
```

### 6. **Runtime Context for Client Detection**

**Why Critical**: actingweb_mcp customizes responses based on client type

**Required Tests**:

```python
# Test: Runtime context MCP client info
def test_runtime_context_mcp_client_info(actor_factory):
    """Test that runtime context captures MCP client information."""
    from actingweb.runtime_context import RuntimeContext, get_client_info_from_context

    actor = actor_factory.create("user@example.com")

    # Set MCP context (as MCP handler does)
    runtime_context = RuntimeContext(actor)
    runtime_context.set_mcp_context(
        client_id="mcp_chatgpt_123",
        trust_relationship=None,  # Would be trust object in real usage
        peer_id="oauth2_client:chatgpt@openai.com:mcp_chatgpt_123",
        token_data={"scope": "mcp"}
    )

    # Get client info
    client_info = get_client_info_from_context(actor)
    assert client_info is not None
    assert client_info["type"] == "mcp"
    assert client_info["name"]  # Should have client name

# Test: Runtime context persists across hook calls
def test_runtime_context_persistence_in_request(actor_factory):
    """Test that runtime context persists during request processing."""
    # This is critical for actingweb_mcp to detect client type in tool hooks
    pass
```

## Priority Test Additions

### High Priority (Critical for actingweb_mcp)

1. **Property Lists** - Dynamic creation, metadata storage, deletion, exists() checks
2. **Trust Permissions** - Pattern matching, excluded_patterns, inheritance
3. **OAuth2 Client Manager** - Client CRUD operations, token generation
4. **Trust with OAuth** - Linking trust relationships to OAuth clients

### Medium Priority (Important for reliability)

5. **Trust Type Registry** - Custom type registration, permission defaults
6. **Runtime Context** - MCP client detection and context passing

### Low Priority (Nice to have)

7. **Advanced pattern matching** - Complex glob patterns, regex support
8. **Permission audit trails** - Tracking permission changes

## Recommended Test File Structure

```
tests/integration/
├── test_property_lists_advanced.py (NEW)
│   - Dynamic creation and deletion
│   - Metadata storage patterns
│   - list_all() functionality
│   - exists() checks
│
├── test_trust_permissions_patterns.py (NEW)
│   - excluded_patterns functionality
│   - Pattern matching with wildcards
│   - Permission inheritance
│   - Individual permission overrides
│
├── test_oauth2_client_manager.py (NEW)
│   - Client CRUD operations
│   - Token generation
│   - Multiple clients per actor
│   - Client listing and filtering
│
├── test_trust_oauth_integration.py (NEW)
│   - Trust relationships with OAuth clients
│   - client_name, oauth_client_id attributes
│   - Permission checks with OAuth context
│
└── test_runtime_context_advanced.py (NEW)
    - MCP context setting and retrieval
    - Client detection in hooks
    - Context persistence
```

## Breaking Changes to Watch For

### Property Lists

- **Change**: Modifying how property lists store items internally
- **Risk**: Could break metadata storage pattern (first item as metadata)
- **Test**: Verify first item metadata pattern works

### Trust Permissions

- **Change**: Changing permission schema or pattern matching logic
- **Risk**: Could break memory access filtering in actingweb_mcp
- **Test**: Verify excluded_patterns are honored correctly

### OAuth2 Client Manager

- **Change**: Changing client_id format or storage
- **Risk**: Could break OAuth client linking to trust relationships
- **Test**: Verify client creation and retrieval works

### Trust Type Registry

- **Change**: Changing how custom trust types are registered
- **Risk**: Could break mcp_client trust type configuration
- **Test**: Verify custom trust type registration and retrieval

## Conclusion

The actingweb_mcp application heavily relies on:

1. **Property lists** with dynamic names and metadata storage
2. **Trust permissions** with pattern-based filtering
3. **OAuth2 client management** for MCP assistant authentication
4. **Runtime context** for client-specific behavior

Adding comprehensive tests for these features in the ActingWeb library will ensure that actingweb_mcp continues to work correctly as the library evolves.

## Next Steps

1. Review this analysis with maintainers
2. Prioritize which tests to implement first
3. Create test implementations following ActingWeb test patterns
4. Run actingweb_mcp test suite against modified ActingWeb library
5. Add these tests to CI/CD pipeline
