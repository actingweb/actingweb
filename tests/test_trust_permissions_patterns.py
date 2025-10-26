"""
Trust Permissions Pattern Tests.

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
- actingweb_mcp uses these patterns extensively for memory access control
"""

import pytest

from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp
from actingweb.trust_permissions import TrustPermissions, TrustPermissionStore


@pytest.fixture
def aw_app():
    """Create ActingWeb app for testing."""
    return ActingWebApp(
        aw_type="urn:actingweb:test:trust_permissions",
        database="dynamodb",
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def permission_store(aw_app):
    """Create TrustPermissionStore for testing."""
    config = aw_app.get_config()
    return TrustPermissionStore(config)


class TestTrustPermissionsExcludedPatterns:
    """Test excluded_patterns functionality in trust permissions."""

    def test_store_permissions_with_excluded_patterns(self, aw_app, permission_store):
        """
        Test storing trust permissions with excluded_patterns.

        actingweb_mcp stores excluded memory types for each MCP client.

        Spec: actingweb/trust_permissions.py:98-131 - store_permissions()
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user@example.com", config=config)
        actor2 = ActorInterface.create(creator="mcp_client@example.com", config=config)

        try:
            # Create permissions with excluded patterns (actingweb_mcp pattern)
            permissions = TrustPermissions(
                actor_id=actor1.id,  # type: ignore[arg-type,union-attr,attr-defined,return-value]
                peer_id=actor2.id,  # type: ignore[arg-type]
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
            stored = permission_store.get_permissions(actor1.id, actor2.id)
            assert stored is not None
            assert stored.properties is not None
            assert "memory_personal" in stored.properties["excluded_patterns"]
            assert "memory_travel" in stored.properties["excluded_patterns"]
            assert "memory_food" not in stored.properties.get("excluded_patterns", [])
        finally:
            actor1.delete()
            actor2.delete()

    def test_excluded_patterns_persist_across_restarts(self, aw_app, permission_store):
        """
        Test that excluded_patterns persist in database.

        actingweb_mcp relies on permissions persisting across app restarts.

        Spec: actingweb/trust_permissions.py:236-249 - Attribute bucket storage
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user@example.com", config=config)
        actor2 = ActorInterface.create(creator="client@example.com", config=config)

        try:
            # Store permissions
            permissions = TrustPermissions(
                actor_id=actor1.id,  # type: ignore[arg-type]
                peer_id=actor2.id,  # type: ignore[arg-type]
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
            stored = permission_store.get_permissions(actor1.id, actor2.id)
            assert stored is not None
            assert "memory_private" in stored.properties["excluded_patterns"]
            assert "memory_confidential" in stored.properties["excluded_patterns"]
        finally:
            actor1.delete()
            actor2.delete()

    def test_update_excluded_patterns(self, aw_app, permission_store):
        """
        Test updating excluded_patterns in existing permissions.

        actingweb_mcp allows users to change which memory types are excluded.

        Spec: actingweb/trust_permissions.py:225-252 - update_permissions()
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user@example.com", config=config)
        actor2 = ActorInterface.create(creator="client@example.com", config=config)

        try:
            # Create initial permissions
            permissions = TrustPermissions(
                actor_id=actor1.id,  # type: ignore[arg-type]
                peer_id=actor2.id,  # type: ignore[arg-type]
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
            stored.properties["excluded_patterns"].append("memory_travel")

            # Update
            permission_store.store_permissions(stored)

            # Verify updates persisted
            updated = permission_store.get_permissions(actor1.id, actor2.id)
            assert "memory_personal" in updated.properties["excluded_patterns"]
            assert "memory_travel" in updated.properties["excluded_patterns"]
        finally:
            actor1.delete()
            actor2.delete()

    def test_empty_excluded_patterns_allows_all(self, aw_app, permission_store):
        """
        Test that empty excluded_patterns array allows all matching patterns.

        Default behavior when no exclusions are set.

        Spec: actingweb/permission_evaluator.py:428-437 - Only checks excluded if present
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user@example.com", config=config)
        actor2 = ActorInterface.create(creator="client@example.com", config=config)

        try:
            # Create permissions with empty excluded_patterns
            permissions = TrustPermissions(
                actor_id=actor1.id,  # type: ignore[arg-type]
                peer_id=actor2.id,  # type: ignore[arg-type]
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
            stored = permission_store.get_permissions(actor1.id, actor2.id)
            assert stored.properties["excluded_patterns"] == []
        finally:
            actor1.delete()
            actor2.delete()


class TestTrustPermissionsPatternMatching:
    """Test pattern matching with wildcards."""

    def test_wildcard_pattern_matches_multiple_properties(self):
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

    def test_method_pattern_matching(self):
        """
        Test that get_* pattern matches method names.

        actingweb_mcp allows method patterns like get_*, list_*, search_*.

        Spec: actingweb_mcp uses method patterns for permission control
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

    def test_multiple_wildcard_patterns(self):
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

    def test_individual_override_replaces_trust_type_for_category(self, aw_app, permission_store):
        """
        Test that individual permissions override trust type for specific categories.

        actingweb_mcp sets per-relationship excluded_patterns.

        Spec: actingweb/trust_permissions.py:261-294 - merge_permissions()
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user@example.com", config=config)
        actor2 = ActorInterface.create(creator="client@example.com", config=config)

        try:
            # Create override with just properties, other categories use trust type defaults
            permissions = TrustPermissions(
                actor_id=actor1.id,  # type: ignore[arg-type]
                peer_id=actor2.id,  # type: ignore[arg-type]
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
            stored = permission_store.get_permissions(actor1.id, actor2.id)
            assert stored.properties is not None
            assert stored.methods is None
            assert stored.actions is None
            assert stored.tools is None
        finally:
            actor1.delete()
            actor2.delete()


class TestTrustPermissionsRetrieval:
    """Test permission retrieval operations."""

    def test_get_permissions_returns_none_if_not_found(self, aw_app, permission_store):
        """
        Test that get_permissions returns None for non-existent permissions.

        Spec: actingweb/trust_permissions.py:133-165 - get_permissions()
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user@example.com", config=config)
        actor2 = ActorInterface.create(creator="client@example.com", config=config)

        try:
            # No permissions exist yet
            result = permission_store.get_permissions(actor1.id, actor2.id)
            assert result is None
        finally:
            actor1.delete()
            actor2.delete()

    def test_list_actor_permissions(self, aw_app, permission_store):
        """
        Test listing all permission overrides for an actor.

        actingweb_mcp may need to list all client permissions.

        Spec: actingweb/trust_permissions.py:167-197 - list_actor_permissions()
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user@example.com", config=config)
        client1 = ActorInterface.create(creator="client1@example.com", config=config)
        client2 = ActorInterface.create(creator="client2@example.com", config=config)
        client3 = ActorInterface.create(creator="client3@example.com", config=config)

        try:
            # Create permissions for multiple clients
            for client in [client1, client2, client3]:
                permissions = TrustPermissions(
                    actor_id=actor1.id,  # type: ignore[arg-type]
                    peer_id=client.id,  # type: ignore[arg-type]
                    trust_type="mcp_client",
                    properties={
                        "patterns": ["memory_*"],
                        "operations": ["read"],
                        "excluded_patterns": [f"memory_private_{client.id[:8]}"]  # type: ignore[arg-type]
                    },
                    created_by="test"
                )
                permission_store.store_permissions(permissions)

            # List all permissions for actor1
            all_perms = permission_store.list_actor_permissions(actor1.id)

            assert len(all_perms) == 3
            peer_ids = [perm.peer_id for perm in all_perms]
            assert client1.id in peer_ids
            assert client2.id in peer_ids
            assert client3.id in peer_ids
        finally:
            actor1.delete()
            client1.delete()
            client2.delete()
            client3.delete()


class TestTrustPermissionsComplexScenarios:
    """Test complex permission scenarios from actingweb_mcp."""

    def test_chatgpt_gets_only_memory_personal(self, aw_app, permission_store):
        """
        Test realistic scenario: ChatGPT restricted to memory_personal only.

        This is a common actingweb_mcp configuration.

        Spec: actingweb_mcp restricts ChatGPT to specific memory types
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)
        chatgpt = ActorInterface.create(creator="chatgpt@openai.com", config=config)

        try:
            # ChatGPT gets memory_* but excludes all except memory_personal
            permissions = TrustPermissions(
                actor_id=actor.id,  # type: ignore[arg-type]
                peer_id=chatgpt.id,  # type: ignore[arg-type]
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
            stored = permission_store.get_permissions(actor.id, chatgpt.id)
            excluded = stored.properties["excluded_patterns"]

            assert "memory_travel" in excluded
            assert "memory_food" in excluded
            assert "memory_health" in excluded
            assert "memory_work" in excluded
            assert "memory_notes" in excluded
            # memory_personal should NOT be in excluded list
            assert "memory_personal" not in excluded
        finally:
            actor.delete()
            chatgpt.delete()

    def test_claude_gets_all_memory_types(self, aw_app, permission_store):
        """
        Test realistic scenario: Claude gets access to all memory types.

        Another common actingweb_mcp configuration.

        Spec: actingweb_mcp uses empty excluded_patterns for full access
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)
        claude = ActorInterface.create(creator="claude@anthropic.com", config=config)

        try:
            # Claude gets all memory types (no exclusions)
            permissions = TrustPermissions(
                actor_id=actor.id,  # type: ignore[arg-type]
                peer_id=claude.id,  # type: ignore[arg-type]
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
            stored = permission_store.get_permissions(actor.id, claude.id)
            assert stored.properties["excluded_patterns"] == []
        finally:
            actor.delete()
            claude.delete()

    def test_multiple_clients_different_permissions(self, aw_app, permission_store):
        """
        Test multiple MCP clients with different memory access.

        actingweb_mcp supports per-client customization.

        Spec: actingweb_mcp allows different excluded_patterns per client
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)
        chatgpt = ActorInterface.create(creator="chatgpt@openai.com", config=config)
        claude = ActorInterface.create(creator="claude@anthropic.com", config=config)
        cursor = ActorInterface.create(creator="cursor@cursor.sh", config=config)

        try:
            # ChatGPT: Only memory_personal and memory_work
            chatgpt_perms = TrustPermissions(
                actor_id=actor.id,  # type: ignore[arg-type]
                peer_id=chatgpt.id,  # type: ignore[arg-type]
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
                actor_id=actor.id,  # type: ignore[arg-type]
                peer_id=claude.id,  # type: ignore[arg-type]
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
                actor_id=actor.id,  # type: ignore[arg-type]
                peer_id=cursor.id,  # type: ignore[arg-type]
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
            chatgpt_stored = permission_store.get_permissions(actor.id, chatgpt.id)
            claude_stored = permission_store.get_permissions(actor.id, claude.id)
            cursor_stored = permission_store.get_permissions(actor.id, cursor.id)

            assert len(chatgpt_stored.properties["excluded_patterns"]) == 3
            assert len(claude_stored.properties["excluded_patterns"]) == 0
            assert len(cursor_stored.properties["excluded_patterns"]) == 4
        finally:
            actor.delete()
            chatgpt.delete()
            claude.delete()
            cursor.delete()
