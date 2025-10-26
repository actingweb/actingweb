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
- actingweb_mcp uses OAuth clients with trust relationships for access control
"""

import pytest

from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp
from actingweb.interface.oauth_client_manager import OAuth2ClientManager
from actingweb.trust_permissions import TrustPermissions, TrustPermissionStore


@pytest.fixture
def aw_app():
    """Create ActingWeb app with OAuth2 and MCP enabled."""
    return (
        ActingWebApp(
            aw_type="urn:actingweb:test:trust_oauth",
            database="dynamodb",
            fqdn="test.example.com",
            proto="http://",
        )
        .with_oauth(
            client_id="test-client-id",
            client_secret="test-client-secret",
            scope="openid email profile",
            auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
            token_uri="https://oauth2.googleapis.com/token",
            redirect_uri="http://test.example.com/oauth/callback",
        )
        .with_mcp(enable=True)
    )


class TestTrustCreationOnClientRegistration:
    """Test that trust relationships are created when OAuth2 clients are registered."""

    def test_client_registration_creates_trust_relationship(self, aw_app):
        """
        Test that registering OAuth2 client automatically creates trust relationship.

        actingweb_mcp relies on automatic trust creation for permission checks.

        Spec: actingweb/oauth2_server/client_registry.py:76-77
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type,union-attr,attr-defined,return-value]

            # Create OAuth2 client
            client_data = client_manager.create_client(
                client_name="ChatGPT",
                trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Verify trust relationship was created
            trust_rels = actor.trust.relationships

            # Should have at least one trust relationship
            assert len(trust_rels) > 0

            # Find trust relationship matching this client
            matching_trust = None
            for trust in trust_rels:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break

            assert matching_trust is not None, f"No trust relationship found for client {client_id}"
        finally:
            actor.delete()

    def test_trust_relationship_has_correct_trust_type(self, aw_app):
        """
        Test that trust relationship inherits trust type from client.

        actingweb_mcp uses trust type for permission inheritance.

        Spec: actingweb/oauth2_server/client_registry.py:361
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

            # Create client with specific trust type
            client_data = client_manager.create_client(
                client_name="Test Client",
                trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Find matching trust relationship
            matching_trust = None
            for trust in actor.trust.relationships:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break

            # Verify trust type matches
            assert matching_trust is not None
            assert matching_trust.relationship == "mcp_client"
        finally:
            actor.delete()

    def test_multiple_clients_create_multiple_trusts(self, aw_app):
        """
        Test that multiple OAuth2 clients create separate trust relationships.

        actingweb_mcp needs separate trusts for permission isolation.

        Spec: actingweb/oauth2_server/client_registry.py:323-387
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

            # Create 3 OAuth2 clients
            client_names = ["ChatGPT", "Claude", "Cursor"]
            client_ids = []

            for name in client_names:
                client_data = client_manager.create_client(
                    client_name=name,
                    trust_type="mcp_client"
                )
                client_ids.append(client_data["client_id"])

            # Verify we have at least 3 trust relationships
            trust_rels = actor.trust.relationships
            assert len(trust_rels) >= 3

            # Verify each client has a corresponding trust
            for client_id in client_ids:
                matching_trust = None
                for trust in trust_rels:
                    if client_id in trust.peerid:
                        matching_trust = trust
                        break
                assert matching_trust is not None, f"No trust found for client {client_id}"
        finally:
            actor.delete()


class TestTrustAttributesForOAuth:
    """Test OAuth-specific attributes on trust relationships."""

    def test_trust_has_client_name_attribute(self, aw_app):
        """
        Test that trust relationship includes client_name from OAuth client.

        actingweb_mcp displays client name in trust relationship UI.

        Spec: actingweb/trust_manager.py:296 - client_name stored in trust
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

            # Create client with specific name
            client_data = client_manager.create_client(
                client_name="ChatGPT Assistant",
                trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Find matching trust
            matching_trust = None
            for trust in actor.trust.relationships:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break

            # Verify client_name attribute
            assert matching_trust is not None
            assert hasattr(matching_trust, "client_name")
            assert matching_trust.client_name == "ChatGPT Assistant"
        finally:
            actor.delete()

    def test_trust_has_oauth_client_id_attribute(self, aw_app):
        """
        Test that trust relationship includes oauth_client_id.

        actingweb_mcp uses oauth_client_id to link trusts to clients.

        Spec: actingweb_mcp uses oauth_client_id attribute
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

            # Create client
            client_data = client_manager.create_client(
                client_name="Test Client",
                trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Find matching trust
            matching_trust = None
            for trust in actor.trust.relationships:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break

            # Verify oauth_client_id attribute
            assert matching_trust is not None
            assert hasattr(matching_trust, "oauth_client_id")
            assert matching_trust.oauth_client_id == client_id
        finally:
            actor.delete()

    def test_trust_has_peer_type_mcp(self, aw_app):
        """
        Test that trust relationship for OAuth client has peer_type="mcp".

        Used to identify MCP client trust relationships.

        Spec: actingweb/trust_manager.py:296 - peer_type set to "mcp"
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

            # Create client
            client_data = client_manager.create_client(
                client_name="Test Client",
                trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Find matching trust
            matching_trust = None
            for trust in actor.trust.relationships:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break

            # Verify peer_type
            assert matching_trust is not None
            assert hasattr(matching_trust, "peer_type")
            assert matching_trust.peer_type == "mcp"
        finally:
            actor.delete()


class TestTrustDeletionOnClientDeletion:
    """Test that trust relationships are deleted when OAuth2 clients are deleted."""

    def test_deleting_client_deletes_trust_relationship(self, aw_app):
        """
        Test that deleting OAuth2 client also deletes trust relationship.

        actingweb_mcp needs cleanup when disconnecting assistants.

        Spec: actingweb/oauth2_server/client_registry.py:227
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

            # Create client
            client_data = client_manager.create_client(
                client_name="Test Client",
                trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Verify trust exists
            trust_count_before = len(actor.trust.relationships)
            matching_trust_before = None
            for trust in actor.trust.relationships:
                if client_id in trust.peerid:
                    matching_trust_before = trust
                    break
            assert matching_trust_before is not None

            # Delete client
            client_manager.delete_client(client_id)

            # Reload actor to get fresh trust data
            actor_reload = ActorInterface.get_by_id(actor.id, config)  # type: ignore[arg-type]

            # Verify trust is deleted
            trust_count_after = len(actor_reload.trust.relationships)  # type: ignore[arg-type]
            assert trust_count_after == trust_count_before - 1

            # Verify specific trust for this client is gone
            matching_trust_after = None
            for trust in actor_reload.trust.relationships:  # type: ignore[arg-type]
                if client_id in trust.peerid:
                    matching_trust_after = trust
                    break
            assert matching_trust_after is None
        finally:
            actor.delete()


class TestPermissionChecksWithOAuth:
    """Test that permission checks work correctly with OAuth context."""

    def test_oauth_client_trust_uses_mcp_client_permissions(self, aw_app):
        """
        Test that OAuth client trust relationship inherits mcp_client permissions.

        actingweb_mcp relies on trust type permissions for access control.

        Spec: actingweb/permission_evaluator.py:314-358 - Permission inheritance
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type,union-attr,attr-defined,return-value]

            # Create client
            client_data = client_manager.create_client(
                client_name="Test Client",
                trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Find matching trust
            matching_trust = None
            for trust in actor.trust.relationships:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break

            # Verify trust exists with mcp_client type (permissions will inherit)
            assert matching_trust is not None
            assert matching_trust.relationship == "mcp_client"
        finally:
            actor.delete()

    def test_individual_permissions_can_override_oauth_client_defaults(self, aw_app):
        """
        Test that individual permissions can be set for OAuth client trusts.

        actingweb_mcp sets per-client excluded_patterns.

        Spec: actingweb/trust_permissions.py:98-131 - Store individual permissions
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

            # Create client
            client_data = client_manager.create_client(
                client_name="ChatGPT",
                trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Find trust relationship to get peer_id
            matching_trust = None
            for trust in actor.trust.relationships:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break

            peer_id = matching_trust.peerid  # type: ignore[arg-type]

            # Set individual permissions for this OAuth client trust
            permission_store = TrustPermissionStore(config)
            permissions = TrustPermissions(
                actor_id=actor.id,  # type: ignore[arg-type]
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
            stored = permission_store.get_permissions(actor.id, peer_id)  # type: ignore[arg-type]
            assert stored is not None
            assert "memory_personal" in stored.properties["excluded_patterns"]  # type: ignore[arg-type]
        finally:
            actor.delete()


class TestRealisticOAuthTrustScenarios:
    """Test realistic scenarios combining OAuth clients and trust relationships."""

    def test_chatgpt_claude_cursor_each_have_separate_trust(self, aw_app):
        """
        Test that connecting multiple assistants creates separate trust relationships.

        actingweb_mcp needs permission isolation between clients.

        Spec: Multiple OAuth clients create multiple trust relationships
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

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

            # Find trust relationships for each client
            chatgpt_trust = None
            claude_trust = None
            cursor_trust = None

            for trust in actor.trust.relationships:
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
            permission_store = TrustPermissionStore(config)

            # ChatGPT: Only memory_personal
            chatgpt_perms = TrustPermissions(
                actor_id=actor.id,  # type: ignore[arg-type]
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
                actor_id=actor.id,  # type: ignore[arg-type]
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
                actor_id=actor.id,  # type: ignore[arg-type]
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
            chatgpt_stored = permission_store.get_permissions(actor.id, chatgpt_trust.peerid)  # type: ignore[arg-type]
            claude_stored = permission_store.get_permissions(actor.id, claude_trust.peerid)  # type: ignore[arg-type]
            cursor_stored = permission_store.get_permissions(actor.id, cursor_trust.peerid)  # type: ignore[arg-type]

            assert len(chatgpt_stored.properties["excluded_patterns"]) == 3  # type: ignore[arg-type]
            assert len(claude_stored.properties["excluded_patterns"]) == 0  # type: ignore[arg-type]
            assert len(cursor_stored.properties["excluded_patterns"]) == 3  # type: ignore
        finally:
            actor.delete()
