"""
OAuth2 Client Manager Tests.

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
- actingweb_mcp uses these patterns for MCP assistant authentication
"""

import pytest
from actingweb.interface.app import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.oauth_client_manager import OAuth2ClientManager


@pytest.fixture
def aw_app():
    """Create ActingWeb app with OAuth2 enabled."""
    return (
        ActingWebApp(
            aw_type="urn:actingweb:test:oauth_clients",
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


class TestOAuth2ClientCreation:
    """Test OAuth2 client creation via OAuth2ClientManager."""

    def test_create_client_basic(self, aw_app):
        """
        Test creating OAuth2 client with basic parameters.

        actingweb_mcp creates OAuth2 clients for each MCP assistant.

        Spec: actingweb/interface/oauth_client_manager.py:38-85
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
        finally:
            actor.delete()

    def test_create_multiple_clients_same_actor(self, aw_app):
        """
        Test creating multiple OAuth2 clients for same actor.

        actingweb_mcp allows users to connect multiple AI assistants.

        Spec: actingweb/interface/oauth_client_manager.py - No limit on clients
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
                assert client_data.get("actor_id") == actor.id
        finally:
            actor.delete()

    def test_create_client_with_different_trust_types(self, aw_app):
        """
        Test creating clients with different trust types.

        actingweb_mcp supports custom trust types for different access levels.

        Spec: actingweb/interface/oauth_client_manager.py:63 - trust_type parameter
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
        finally:
            actor.delete()


class TestOAuth2ClientListing:
    """Test OAuth2 client listing operations."""

    def test_list_clients_empty(self, aw_app):
        """
        Test listing clients when none exist.

        Spec: actingweb/interface/oauth_client_manager.py:109-133
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

            # List should be empty
            clients = client_manager.list_clients()
            assert clients == []
        finally:
            actor.delete()

    def test_list_clients_returns_all_clients(self, aw_app):
        """
        Test that list_clients returns all clients for an actor.

        actingweb_mcp uses list_clients to display all connected assistants.

        Spec: actingweb/interface/oauth_client_manager.py:109-133
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
        finally:
            actor.delete()

    def test_list_clients_includes_metadata(self, aw_app):
        """
        Test that list_clients includes formatted metadata.

        actingweb_mcp displays creation date, status, etc.

        Spec: actingweb/interface/oauth_client_manager.py:120-129
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

            # Create client
            client_manager.create_client(client_name="Test Client", trust_type="mcp_client")

            # List clients
            clients = client_manager.list_clients()

            assert len(clients) == 1
            client = clients[0]

            # Should have formatted metadata
            assert "created_at_formatted" in client
            assert "status" in client
        finally:
            actor.delete()


class TestOAuth2ClientRetrieval:
    """Test OAuth2 client retrieval operations."""

    def test_get_client_by_id(self, aw_app):
        """
        Test retrieving specific client by ID.

        actingweb_mcp retrieves clients for display and management.

        Spec: actingweb/interface/oauth_client_manager.py:87-107
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
        finally:
            actor.delete()

    def test_get_client_wrong_actor_returns_none(self, aw_app):
        """
        Test that get_client returns None for clients owned by other actors.

        Security: clients are actor-specific.

        Spec: actingweb/interface/oauth_client_manager.py:101-103
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user1@example.com", config=config)
        actor2 = ActorInterface.create(creator="user2@example.com", config=config)

        try:
            # Create client for actor1
            client_manager1 = OAuth2ClientManager(actor1.id, config)
            created = client_manager1.create_client(
                client_name="Actor1 Client",
                trust_type="mcp_client"
            )
            client_id = created["client_id"]

            # Try to retrieve from actor2's manager
            client_manager2 = OAuth2ClientManager(actor2.id, config)
            retrieved = client_manager2.get_client(client_id)

            # Should return None (not actor2's client)
            assert retrieved is None
        finally:
            actor1.delete()
            actor2.delete()

    def test_get_nonexistent_client_returns_none(self, aw_app):
        """
        Test that get_client returns None for non-existent client.

        Spec: actingweb/interface/oauth_client_manager.py:87-107
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

            # Try to get non-existent client
            retrieved = client_manager.get_client("mcp_nonexistent12345")

            assert retrieved is None
        finally:
            actor.delete()


class TestOAuth2ClientDeletion:
    """Test OAuth2 client deletion operations."""

    def test_delete_client(self, aw_app):
        """
        Test deleting OAuth2 client.

        actingweb_mcp allows users to disconnect AI assistants.

        Spec: actingweb/interface/oauth_client_manager.py:135-167
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
        finally:
            actor.delete()

    def test_delete_client_removes_from_list(self, aw_app):
        """
        Test that deleted client no longer appears in list.

        Spec: actingweb/interface/oauth_client_manager.py:109-133
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
        finally:
            actor.delete()

    def test_delete_nonexistent_client_returns_false(self, aw_app):
        """
        Test that deleting non-existent client returns False.

        Spec: actingweb/interface/oauth_client_manager.py:151-154
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

            # Try to delete non-existent client
            success = client_manager.delete_client("mcp_nonexistent12345")

            assert not success
        finally:
            actor.delete()

    def test_delete_other_actors_client_returns_false(self, aw_app):
        """
        Test that attempting to delete another actor's client fails.

        Security: actors cannot delete each other's clients.

        Spec: actingweb/interface/oauth_client_manager.py:147-154
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user1@example.com", config=config)
        actor2 = ActorInterface.create(creator="user2@example.com", config=config)

        try:
            # Create client for actor1
            client_manager1 = OAuth2ClientManager(actor1.id, config)
            created = client_manager1.create_client(client_name="Actor1 Client", trust_type="mcp_client")
            client_id = created["client_id"]

            # Try to delete from actor2's manager
            client_manager2 = OAuth2ClientManager(actor2.id, config)
            success = client_manager2.delete_client(client_id)

            # Should fail (not actor2's client)
            assert not success

            # Verify client still exists for actor1
            still_exists = client_manager1.get_client(client_id)
            assert still_exists is not None
        finally:
            actor1.delete()
            actor2.delete()


class TestOAuth2AccessTokenGeneration:
    """Test access token generation for OAuth2 clients."""

    def test_generate_access_token(self, aw_app):
        """
        Test generating access token for OAuth2 client.

        actingweb_mcp generates tokens for testing/development.

        Spec: actingweb/interface/oauth_client_manager.py:294-341
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
        finally:
            actor.delete()

    def test_generate_token_for_nonexistent_client_returns_none(self, aw_app):
        """
        Test that generating token for non-existent client returns None.

        Spec: actingweb/interface/oauth_client_manager.py:308-311
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

            # Try to generate token for non-existent client
            token_response = client_manager.generate_access_token("mcp_nonexistent12345")

            assert token_response is None
        finally:
            actor.delete()


class TestOAuth2ClientManagerRealisticScenarios:
    """Test realistic actingweb_mcp usage scenarios."""

    def test_connect_chatgpt_claude_cursor_workflow(self, aw_app):
        """
        Test realistic workflow: user connects 3 AI assistants.

        This simulates actingweb_mcp UI workflow for connecting assistants.

        Spec: actingweb_mcp uses this workflow for connecting assistants
        """
        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)

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
        finally:
            actor.delete()
