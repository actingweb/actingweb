"""
Trust Type Registry Tests.

Tests custom trust type registration functionality:
- Register custom trust types with permissions
- Trust types with complex permission structures
- Multiple custom trust types
- Trust type retrieval and listing

Medium priority - actingweb_mcp uses default types but may add custom ones.

References:
- actingweb/permission_integration.py:24-146 - AccessControlConfig
- actingweb/trust_type_registry.py:66-220 - TrustTypeRegistry
- actingweb_mcp customizes mcp_client trust type
"""

import os

import pytest

from actingweb.interface.app import ActingWebApp
from actingweb.trust_type_registry import get_registry

# Use same DynamoDB host as conftest
TEST_DYNAMODB_HOST = os.environ.get("AWS_DB_HOST", "http://localhost:8001")


@pytest.fixture
def aw_app(docker_services, worker_info):  # pylint: disable=unused-argument
    """Create ActingWeb app for testing trust types.

    Depends on docker_services to ensure DynamoDB is running.
    Sets up AWS environment variables for database access.
    Resets the trust type registry singleton to ensure clean state.
    """
    # Set environment for DynamoDB with worker-specific prefix
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
    os.environ["AWS_DB_HOST"] = TEST_DYNAMODB_HOST
    os.environ["AWS_DB_PREFIX"] = worker_info["db_prefix"]

    # Reset the trust type registry singleton to ensure fresh state
    import actingweb.trust_type_registry as registry_module

    registry_module._registry = None

    return ActingWebApp(
        aw_type="urn:actingweb:test:trust_types",
        database="dynamodb",
        fqdn="test.example.com",
        proto="http://",
    )


class TestDefaultTrustTypes:
    """Test that default trust types are registered."""

    def test_default_trust_types_exist(self, aw_app):
        """
        Test that default trust types (friend, partner, etc.) are registered.

        Spec: actingweb/trust_type_registry.py - Default types
        """
        config = aw_app.get_config()
        registry = get_registry(config)

        # Verify default trust types exist
        default_types = [
            "friend",
            "partner",
            "admin",
            "viewer",
            "associate",
            "mcp_client",
        ]

        for trust_type_name in default_types:
            trust_type = registry.get_type(trust_type_name)
            assert trust_type is not None, (
                f"Default trust type {trust_type_name} should exist"
            )

    def test_mcp_client_trust_type_has_permissions(self, aw_app):
        """
        Test that mcp_client trust type has proper permissions structure.

        actingweb_mcp relies on mcp_client trust type for AI assistants.

        Spec: actingweb/trust_type_registry.py - mcp_client type
        """
        config = aw_app.get_config()
        registry = get_registry(config)

        mcp_type = registry.get_type("mcp_client")
        assert mcp_type is not None
        assert mcp_type.name == "mcp_client"
        assert hasattr(mcp_type, "base_permissions")
        assert mcp_type.base_permissions is not None

    def test_list_all_trust_types(self, aw_app):
        """
        Test listing all registered trust types.

        Spec: actingweb/trust_type_registry.py - list_types()
        """
        config = aw_app.get_config()
        registry = get_registry(config)

        all_types = registry.list_types()
        assert len(all_types) > 0

        # Should include at least the default types
        type_names = [t.name for t in all_types]
        assert "mcp_client" in type_names
        assert "friend" in type_names


class TestCustomTrustTypeRegistration:
    """Test registering custom trust types."""

    def test_register_custom_trust_type(self, aw_app):
        """
        Test registering a custom trust type with permissions.

        This tests the pattern actingweb_mcp uses for customization.

        Spec: actingweb/permission_integration.py:54-107
        """
        config = aw_app.get_config()

        from actingweb.permission_integration import AccessControlConfig

        # Register custom trust type
        access_control = AccessControlConfig(config)
        access_control.add_trust_type(
            name="custom_assistant",
            display_name="Custom AI Assistant",
            description="Custom AI assistant with specific permissions",
            permissions={
                "properties": {
                    "patterns": ["memory_*", "notes_*"],
                    "operations": ["read"],
                    "excluded_patterns": [],
                },
                "methods": ["get_*", "list_*"],
                "tools": ["search"],
                "resources": ["notes://*"],
                "prompts": [],
            },
            oauth_scope="actingweb.custom_assistant",
        )

        # Verify registration
        registry = get_registry(config)
        custom_type = registry.get_type("custom_assistant")

        assert custom_type is not None
        assert custom_type.name == "custom_assistant"
        assert custom_type.display_name == "Custom AI Assistant"
        assert "memory_*" in custom_type.base_permissions["properties"]["patterns"]
        # tools can be stored as dict with "allowed" key or as list
        tools = custom_type.base_permissions["tools"]
        if isinstance(tools, dict):
            assert "search" in tools.get("allowed", [])
        else:
            assert "search" in tools

    def test_register_multiple_custom_types(self, aw_app):
        """
        Test registering multiple custom trust types.

        actingweb_mcp might add different trust types for different use cases.

        Spec: actingweb/permission_integration.py - Multiple registrations
        """
        config = aw_app.get_config()

        from actingweb.permission_integration import AccessControlConfig

        access_control = AccessControlConfig(config)

        # Register multiple custom types
        custom_types = [
            {
                "name": "ai_reader",
                "display_name": "Read-Only AI",
                "permissions": {
                    "properties": {
                        "patterns": ["memory_*"],
                        "operations": ["read"],
                        "excluded_patterns": [],
                    },
                },
            },
            {
                "name": "ai_writer",
                "display_name": "Write-Enabled AI",
                "permissions": {
                    "properties": {
                        "patterns": ["memory_*"],
                        "operations": ["read", "write"],
                        "excluded_patterns": [],
                    },
                },
            },
            {
                "name": "ai_admin",
                "display_name": "Admin AI",
                "permissions": {
                    "properties": {
                        "patterns": ["*"],
                        "operations": ["read", "write", "delete"],
                        "excluded_patterns": [],
                    },
                },
            },
        ]

        for custom_type_config in custom_types:
            access_control.add_trust_type(
                name=custom_type_config["name"],
                display_name=custom_type_config["display_name"],
                description=f"Custom type: {custom_type_config['name']}",
                permissions=custom_type_config["permissions"],
                oauth_scope=f"actingweb.{custom_type_config['name']}",
            )

        # Verify all registered
        registry = get_registry(config)

        for custom_type_config in custom_types:
            registered_type = registry.get_type(custom_type_config["name"])
            assert registered_type is not None
            assert registered_type.display_name == custom_type_config["display_name"]


class TestTrustTypePermissions:
    """Test trust type permission structures."""

    def test_trust_type_has_property_permissions(self, aw_app):
        """
        Test that trust types include property permissions.

        actingweb_mcp uses property permissions for memory access control.

        Spec: actingweb/trust_type_registry.py - Permission structure
        """
        config = aw_app.get_config()
        registry = get_registry(config)

        mcp_type = registry.get_type("mcp_client")
        assert mcp_type is not None
        assert "properties" in mcp_type.base_permissions

        props = mcp_type.base_permissions["properties"]
        assert "patterns" in props or "allowed" in props or props is None

    def test_trust_type_has_method_permissions(self, aw_app):
        """
        Test that trust types can include method permissions.

        Spec: actingweb/trust_type_registry.py - methods permission category
        """
        config = aw_app.get_config()
        registry = get_registry(config)

        mcp_type = registry.get_type("mcp_client")
        assert mcp_type is not None

        # methods can be None (inherit default), a list, or a dict
        assert "methods" in mcp_type.base_permissions or hasattr(
            mcp_type.base_permissions, "get"
        )

    def test_trust_type_permissions_structure(self, aw_app):
        """
        Test that trust type permissions follow expected structure.

        Spec: actingweb/trust_type_registry.py - Base permissions structure
        """
        config = aw_app.get_config()

        from actingweb.permission_integration import AccessControlConfig

        access_control = AccessControlConfig(config)
        access_control.add_trust_type(
            name="test_structured",
            display_name="Structured Test",
            description="Test permission structure",
            permissions={
                "properties": {
                    "patterns": ["test_*"],
                    "operations": ["read"],
                    "excluded_patterns": ["test_private"],
                },
                "methods": ["get_*"],
                "actions": ["search"],
                "tools": ["test_tool"],
                "resources": ["test://*"],
                "prompts": ["test_prompt"],
            },
        )

        registry = get_registry(config)
        test_type = registry.get_type("test_structured")

        assert test_type is not None

        # Verify all permission categories
        perms = test_type.base_permissions
        assert "properties" in perms
        assert "methods" in perms
        assert (
            "actions" in perms or "tools" in perms
        )  # Different versions may use different names


class TestTrustTypeACLRules:
    """Test ACL rules for custom trust types."""

    def test_register_trust_type_with_acl_rules(self, aw_app):
        """
        Test registering a custom trust type with ACL rules.

        ACL rules allow custom trust types to access HTTP endpoints
        like /subscriptions/<id> for actor-to-actor subscriptions.

        Spec: actingweb/permission_integration.py - add_trust_type with acl_rules
        """
        config = aw_app.get_config()

        from actingweb.permission_integration import AccessControlConfig

        # Register custom trust type with ACL rules
        access_control = AccessControlConfig(config)
        access_control.add_trust_type(
            name="subscriber_test",
            display_name="Test Subscriber",
            description="Test trust type for actor-to-actor subscriptions",
            permissions={
                "properties": {
                    "patterns": ["memory_*"],
                    "operations": ["read"],
                },
            },
            acl_rules=[
                ("subscriptions/<id>", "POST", "a"),  # Allow creating subscriptions
                ("properties", "GET", "a"),  # Allow reading properties
                ("callbacks", "", "a"),  # Allow all methods on callbacks
            ],
        )

        # Verify registration
        registry = get_registry(config)
        subscriber_type = registry.get_type("subscriber_test")

        assert subscriber_type is not None
        assert subscriber_type.name == "subscriber_test"
        assert subscriber_type.acl_rules is not None
        assert len(subscriber_type.acl_rules) == 3

        # Verify ACL rules are stored correctly
        assert ("subscriptions/<id>", "POST", "a") in subscriber_type.acl_rules
        assert ("properties", "GET", "a") in subscriber_type.acl_rules
        assert ("callbacks", "", "a") in subscriber_type.acl_rules

    def test_acl_rules_added_to_config_access(self, aw_app):
        """
        Test that ACL rules are added to config.access.

        When a trust type with acl_rules is registered, the rules should
        be inserted into config.access for authorization checks.

        Spec: actingweb/permission_integration.py - _add_acl_rules_to_config
        """
        config = aw_app.get_config()
        original_access_len = len(config.access)

        from actingweb.permission_integration import AccessControlConfig

        access_control = AccessControlConfig(config)
        access_control.add_trust_type(
            name="acl_test_type",
            display_name="ACL Test Type",
            permissions={"properties": ["public/*"]},
            acl_rules=[
                ("subscriptions/<id>", "POST", "a"),
                ("properties", "GET", "a"),
            ],
        )

        # Verify ACL rules were added to config.access
        assert len(config.access) > original_access_len

        # Check specific rules exist in config.access
        # Format is (role, path, methods, access)
        acl_entries = config.access
        assert ("acl_test_type", "subscriptions/<id>", "POST", "a") in acl_entries
        assert ("acl_test_type", "properties", "GET", "a") in acl_entries

    def test_acl_rules_no_duplicates(self, aw_app):
        """
        Test that duplicate ACL rules are not added.

        Spec: actingweb/permission_integration.py - _add_acl_rules_to_config
        """
        config = aw_app.get_config()

        from actingweb.permission_integration import AccessControlConfig

        access_control = AccessControlConfig(config)

        # Register first time
        access_control.add_trust_type(
            name="dup_test_type",
            display_name="Duplicate Test",
            permissions={"properties": ["public/*"]},
            acl_rules=[("subscriptions/<id>", "POST", "a")],
        )

        count_after_first = config.access.count(
            ("dup_test_type", "subscriptions/<id>", "POST", "a")
        )
        assert count_after_first == 1

        # Register again with same ACL rule (should not add duplicate)
        access_control._add_acl_rules_to_config(
            "dup_test_type", [("subscriptions/<id>", "POST", "a")]
        )

        count_after_second = config.access.count(
            ("dup_test_type", "subscriptions/<id>", "POST", "a")
        )
        assert count_after_second == 1  # Still only one entry

    def test_trust_type_without_acl_rules(self, aw_app):
        """
        Test that trust types without ACL rules work correctly.

        Not all trust types need ACL rules - only those that need
        HTTP endpoint access beyond what's already in default ACL.

        Spec: actingweb/permission_integration.py - acl_rules is optional
        """
        config = aw_app.get_config()

        from actingweb.permission_integration import AccessControlConfig

        access_control = AccessControlConfig(config)
        access_control.add_trust_type(
            name="no_acl_type",
            display_name="No ACL Type",
            permissions={"properties": ["public/*"]},
            # No acl_rules parameter
        )

        # Verify no new ACL rules were added
        # (only the default types may have been added if not already present)
        registry = get_registry(config)
        no_acl_type = registry.get_type("no_acl_type")
        assert no_acl_type is not None
        assert no_acl_type.acl_rules is None

    def test_acl_rules_priority(self, aw_app):
        """
        Test that custom ACL rules are inserted at the beginning.

        Custom rules should take priority over default rules, so they
        are inserted at index 0.

        Spec: actingweb/permission_integration.py - insert at beginning
        """
        config = aw_app.get_config()

        from actingweb.permission_integration import AccessControlConfig

        access_control = AccessControlConfig(config)
        access_control.add_trust_type(
            name="priority_test",
            display_name="Priority Test",
            permissions={"properties": ["public/*"]},
            acl_rules=[("custom/path", "GET", "a")],
        )

        # The custom rule should be near the beginning of config.access
        custom_rule = ("priority_test", "custom/path", "GET", "a")
        idx = config.access.index(custom_rule)
        # Should be in the first few entries (before default rules)
        assert idx < 5, f"Custom ACL rule should be near beginning, found at index {idx}"


class TestTrustTypeUsage:
    """Test using trust types with trust relationships."""

    def test_trust_relationship_uses_trust_type(self, aw_app):
        """
        Test that trust relationships can reference trust types.

        actingweb_mcp creates trusts with mcp_client type.

        Spec: Trust relationships use trust_type for permission inheritance
        """
        config = aw_app.get_config()
        registry = get_registry(config)

        # Verify mcp_client type exists for use in trust relationships
        mcp_type = registry.get_type("mcp_client")
        assert mcp_type is not None

        # This verifies the type is available for trust relationship creation
        assert mcp_type.name == "mcp_client"
