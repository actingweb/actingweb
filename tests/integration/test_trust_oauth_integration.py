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

import os

import pytest

from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp
from actingweb.interface.oauth_client_manager import OAuth2ClientManager
from actingweb.trust_permissions import TrustPermissions, TrustPermissionStore

# Get database backend from environment (set by conftest.py)
DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")

# Quarantine lifted 2026-08-15. From PR #105 until now the two deletion assertions
# below were skipped on postgresql: under the parallel postgresql CI matrix a
# per-actor attribute DELETE during OAuth2-client/trust deletion intermittently did
# not persist, so the client stayed listable (`assert 1 == 0`).
#
# Both mechanisms the investigation ranked highest have since been removed by
# unrelated work, which is why these run again rather than because anyone
# reproduced a fix:
#
#   * `DbPropertyLookup.create()` was the one INSERT that could raise
#     `duplicate key value violates unique constraint "property_lookup_pkey"` and
#     abort a pooled connection's transaction — the leading hypothesis. It gained
#     `ON CONFLICT` in #115, after the quarantine went in.
#   * `get_pool()` now tracks the schema a pool was built for and rebuilds rather
#     than serving a mix of connections bound to different `search_path`s (#117),
#     which was hypothesis 2.
#
# If the flake returns, the run will say which mechanism it is: set
# ACTINGWEB_PG_DELETE_DIAGNOSTICS=1 (already on in the CI matrix) and grep the job
# log for PG_DELETE_DIAG — rowcount, the deleting connection's schema, and a
# post-commit re-read on a fresh connection. The investigation record is the
# retired todo, readable with:
#   git show aaf101f:thoughts/todo/2026-06-15-postgres-parallel-delete-not-persisting.md


@pytest.fixture
def aw_app(docker_services, setup_database, worker_info):  # noqa: ARG001
    """Create ActingWeb app with OAuth2 and MCP enabled.

    Depends on setup_database to ensure schema exists and worker_info
    for proper database isolation in parallel tests.
    """
    # Set up environment for PostgreSQL schema isolation
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    return (
        ActingWebApp(
            aw_type="urn:actingweb:test:trust_oauth",
            database=DATABASE_BACKEND,
            fqdn="test.example.com",
            proto="http://",
        )
        .with_unique_creator(False)
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
                client_name="ChatGPT", trust_type="mcp_client"
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

            assert matching_trust is not None, (
                f"No trust relationship found for client {client_id}"
            )
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
                client_name="Test Client", trust_type="mcp_client"
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
                    client_name=name, trust_type="mcp_client"
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
                assert matching_trust is not None, (
                    f"No trust found for client {client_id}"
                )
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
                client_name="ChatGPT Assistant", trust_type="mcp_client"
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
                client_name="Test Client", trust_type="mcp_client"
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
                client_name="Test Client", trust_type="mcp_client"
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
                client_name="Test Client", trust_type="mcp_client"
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

    def test_deleting_trust_deletes_client_and_revokes_tokens(self, aw_app):
        """
        Test that deleting a trust relationship also deletes the OAuth2 client and revokes tokens.

        This is the reverse flow: when user deletes trust from the UI or API,
        the client should be cleaned up and all tokens should be revoked.

        Spec: actingweb/trust.py:72-128 - Trust deletion with client cleanup
        """
        from actingweb.oauth2_server.token_manager import get_actingweb_token_manager

        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]
            token_manager = get_actingweb_token_manager(config)

            # Create client
            client_data = client_manager.create_client(
                client_name="Test Client", trust_type="mcp_client"
            )
            client_id = client_data["client_id"]

            # Create a token for the client
            token_response = token_manager.create_access_token(
                actor_id=actor.id,  # type: ignore[arg-type]
                client_id=client_id,
                scope="mcp",
                trust_type="mcp_client",
                grant_type="client_credentials",
            )
            assert token_response is not None
            access_token = token_response["access_token"]

            # Verify token is valid before deletion
            token_validation = token_manager.validate_access_token(access_token)
            assert token_validation is not None

            # Find the trust relationship
            matching_trust = None
            for trust in actor.trust.relationships:
                if client_id in trust.peerid:
                    matching_trust = trust
                    break
            assert matching_trust is not None
            peer_id = matching_trust.peerid

            # Verify client exists
            clients_before = client_manager.list_clients()
            assert len(clients_before) == 1

            # Delete trust relationship (should also delete client and revoke tokens)
            success = actor.trust.delete_relationship(peer_id)
            assert success

            # Reload actor to get fresh data
            actor_reload = ActorInterface.get_by_id(actor.id, config)  # type: ignore[arg-type]

            # Verify trust is deleted
            matching_trust_after = None
            for trust in actor_reload.trust.relationships:  # type: ignore[arg-type]
                if client_id in trust.peerid:
                    matching_trust_after = trust
                    break
            assert matching_trust_after is None, "Trust relationship should be deleted"

            # Verify client is deleted. Deletion must succeed even when the shared
            # global client index is transiently unreadable under concurrent load
            # (the trust passes the authoritative actor_id to delete_client).
            assert len(client_manager.list_clients()) == 0, (
                "OAuth2 client should be deleted after trust deletion"
            )

            # Verify token is revoked
            token_validation_after = token_manager.validate_access_token(access_token)
            assert token_validation_after is None, (
                "Token should be revoked after trust deletion"
            )
        finally:
            actor.delete()

    def test_delete_client_succeeds_when_global_index_missing(self, aw_app):
        """Regression: client deletion must succeed even if the shared global
        client index entry is unreadable.

        The global ``CLIENT_INDEX_BUCKET`` (under ``OAUTH2_SYSTEM_ACTOR``) is a
        best-effort lookup optimization. Under heavy concurrent load (the postgres
        CI matrix) its entry could be transiently unreadable at delete time, which
        previously made ``delete_client`` bail before removing the client from the
        actor's own bucket — orphaning it (still listable after trust deletion).
        Because the trust passes the authoritative ``actor_id``, deletion must
        proceed regardless. This simulates the miss by removing the index entry.
        """
        from actingweb import attribute
        from actingweb.constants import CLIENT_INDEX_BUCKET, OAUTH2_SYSTEM_ACTOR
        from actingweb.oauth2_server.client_registry import get_mcp_client_registry

        config = aw_app.get_config()
        actor = ActorInterface.create(creator="user-idx@example.com", config=config)

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]
            client_data = client_manager.create_client(
                client_name="Index Client", trust_type="mcp_client"
            )
            client_id = client_data["client_id"]
            assert len(client_manager.list_clients()) == 1

            # Simulate the shared global index entry being unreadable.
            global_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=CLIENT_INDEX_BUCKET,
                config=config,
            )
            global_bucket.delete_attr(name=client_id)

            # Delete via the registry path (as trust deletion does) with the
            # authoritative actor_id. Must still remove the client.
            registry = get_mcp_client_registry(config)
            assert (
                registry.delete_client(client_id, actor_id=actor.id) is True  # type: ignore[arg-type]
            )
            assert len(client_manager.list_clients()) == 0
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
                client_name="Test Client", trust_type="mcp_client"
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
                client_name="ChatGPT", trust_type="mcp_client"
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
                    "excluded_patterns": ["memory_personal", "memory_travel"],
                },
                created_by="test",
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
        assert actor.id is not None, "Actor creation failed - id is None"

        try:
            client_manager = OAuth2ClientManager(actor.id, config)  # type: ignore[arg-type]

            # Connect ChatGPT - restricted access
            chatgpt = client_manager.create_client(
                client_name="ChatGPT", trust_type="mcp_client"
            )

            # Connect Claude - full access
            claude = client_manager.create_client(
                client_name="Claude", trust_type="mcp_client"
            )

            # Connect Cursor - work-only access
            cursor = client_manager.create_client(
                client_name="Cursor", trust_type="mcp_client"
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
                    "excluded_patterns": [
                        "memory_travel",
                        "memory_food",
                        "memory_work",
                    ],
                },
                created_by="test",
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
                    "excluded_patterns": [],
                },
                created_by="test",
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
                    "excluded_patterns": [
                        "memory_personal",
                        "memory_travel",
                        "memory_food",
                    ],
                },
                created_by="test",
            )
            permission_store.store_permissions(cursor_perms)

            # Verify each has different permissions
            chatgpt_stored = permission_store.get_permissions(
                actor.id, chatgpt_trust.peerid
            )  # type: ignore[arg-type]
            claude_stored = permission_store.get_permissions(
                actor.id, claude_trust.peerid
            )  # type: ignore[arg-type]
            cursor_stored = permission_store.get_permissions(
                actor.id, cursor_trust.peerid
            )  # type: ignore[arg-type]

            assert len(chatgpt_stored.properties["excluded_patterns"]) == 3  # type: ignore[arg-type]
            assert len(claude_stored.properties["excluded_patterns"]) == 0  # type: ignore[arg-type]
            assert len(cursor_stored.properties["excluded_patterns"]) == 3  # type: ignore
        finally:
            actor.delete()


class TestClientConnectionDeletion:
    """Deleting a connection to a client ends that actor's connection only
    (verification audit 2026-11-04, D1, D6, D7)."""

    @staticmethod
    def _rows_for(actor: ActorInterface, client_id: str) -> list:
        return [
            t
            for t in actor.trust.relationships
            if getattr(t, "oauth_client_id", None) == client_id
            or t.peerid.endswith(f":{client_id}")
        ]

    def test_deleting_a_connection_keeps_another_actors_client(self, aw_app):
        """Actor Y authorized a client registered under actor X, then deleted
        its row. X's client (row and global index row) survives; Y's token,
        rows and stored provider tokens are gone."""
        from actingweb import actor as actor_module
        from actingweb.constants import OAUTH_TOKENS_PREFIX
        from actingweb.oauth2_server.client_registry import MCPClientRegistry
        from actingweb.oauth2_server.token_manager import get_actingweb_token_manager

        config = aw_app.get_config()
        owner = ActorInterface.create(creator="owner@example.com", config=config)
        other = ActorInterface.create(creator="other@example.com", config=config)
        try:
            client_id = OAuth2ClientManager(owner.id, config).create_client(  # type: ignore[arg-type]
                client_name="Shared Client", trust_type="mcp_client"
            )["client_id"]
            assert other.trust.create_or_update_oauth_trust(
                email="other@example.com",
                trust_type="mcp_client",
                oauth_tokens={"access_token": "g-at", "refresh_token": "g-rt"},
                established_via="oauth2_client",
                client_id=client_id,
            )
            (row,) = self._rows_for(other, client_id)
            token_manager = get_actingweb_token_manager(config)
            token = token_manager.create_access_token(
                actor_id=other.id,  # type: ignore[arg-type]
                client_id=client_id,
                scope="mcp",
                trust_type="mcp_client",
                grant_type="client_credentials",
            )
            assert token is not None
            other_core = actor_module.Actor(other.id, config=config)
            assert other_core.store is not None
            assert other_core.store[f"{OAUTH_TOKENS_PREFIX}{row.peerid}"]

            assert other.trust.delete_relationship(row.peerid)

            registry = MCPClientRegistry(config)
            loaded = registry._load_client(client_id)
            assert loaded is not None and loaded["actor_id"] == owner.id
            assert len(OAuth2ClientManager(owner.id, config).list_clients()) == 1  # type: ignore[arg-type]
            assert self._rows_for(owner, client_id), "the owner's row must stay"
            assert token_manager.validate_access_token(token["access_token"]) is None
            assert self._rows_for(other, client_id) == []
            fresh = actor_module.Actor(other.id, config=config)
            assert fresh.store is not None
            assert fresh.store[f"{OAUTH_TOKENS_PREFIX}{row.peerid}"] is None
        finally:
            other.delete()
            owner.delete()

    def test_a_fault_before_the_row_delete_keeps_its_permissions(self, aw_app):
        """Custom permissions go after the trust row: a fault between the
        cleanup steps leaves the row with the permissions that narrowed it,
        never a live row on its trust type's defaults."""
        from unittest import mock

        from actingweb import actor as actor_module
        from actingweb.db.exceptions import DbError

        config = aw_app.get_config()
        actor = ActorInterface.create(creator="perm@example.com", config=config)
        try:
            client_id = OAuth2ClientManager(actor.id, config).create_client(  # type: ignore[arg-type]
                client_name="Narrowed", trust_type="mcp_client"
            )["client_id"]
            (row,) = self._rows_for(actor, client_id)
            assert TrustPermissionStore(config).store_permissions(
                TrustPermissions(
                    actor_id=actor.id,  # type: ignore[arg-type]
                    peer_id=row.peerid,
                    trust_type="mcp_client",
                    properties={"patterns": ["memory_*"], "operations": ["read"]},
                    created_by="test",
                )
            )
            core = actor_module.Actor(actor.id, config=config)
            with mock.patch(
                "actingweb.peer_profile.get_peer_profile_store",
                side_effect=DbError("peer profile delete"),
            ):
                with pytest.raises(DbError):
                    core.delete_reciprocal_trust(peerid=row.peerid, delete_peer=True)
            assert self._rows_for(actor, client_id), "the row must survive the fault"
            kept = TrustPermissionStore(config).get_permissions(actor.id, row.peerid)  # type: ignore[arg-type]
            assert kept is not None and kept.properties["patterns"] == ["memory_*"]  # type: ignore[index]
        finally:
            actor.delete()

    def test_bulk_deletion_passes_a_row_an_earlier_rows_cleanup_removed(self, aw_app):
        """An owner holds its registration row and the row of authorizing
        its own client. Deleting the first sweeps the second, which the bulk
        loop then reaches in its stale list: already gone is not a failure
        (fifth verification, Issue 1)."""
        from actingweb import actor as actor_module

        config = aw_app.get_config()
        actor = ActorInterface.create(creator="bulk@example.com", config=config)
        try:
            client_id = OAuth2ClientManager(actor.id, config).create_client(  # type: ignore[arg-type]
                client_name="Own Client", trust_type="mcp_client"
            )["client_id"]
            assert actor.trust.create_or_update_oauth_trust(
                email="bulk@example.com",
                trust_type="mcp_client",
                oauth_tokens={"access_token": "g-at"},
                established_via="oauth2_client",
                client_id=client_id,
            )
            assert len(self._rows_for(actor, client_id)) == 2

            core = actor_module.Actor(actor.id, config=config)
            assert core.delete_reciprocal_trust(delete_peer=True) is True
            fresh = ActorInterface(actor_module.Actor(actor.id, config=config))
            assert self._rows_for(fresh, client_id) == []
        finally:
            actor.delete()


# Fault targets for TestTrustDeletionConverges, one per row of the table in
# thoughts/reference/trust-row-deletion-invariants.md that can fault:
# target -> ({scenario: depth}, the step's table row). Depth 1 faults the row
# the route deletes; depth 2 a sibling row its sweep (step 8) deletes. The
# owner's own row disables the client (3a), so its revoke (3b) is a sibling's.
_FAULT_TARGETS = {
    "revoke": ({"connection": 1, "owner": 2}, "3b"),
    "disable": ({"owner": 1, "owner-single": 1}, "3a"),
    "disable_tokens": ({"owner": 1, "owner-single": 1}, "3a"),
    "client_row": ({"owner": 1, "owner-single": 1}, "3a"),
    "provider_tokens": ({"owner": 1, "connection": 1, "owner-single": 1}, "4"),
    "row": ({"owner": 1, "connection": 1, "owner-single": 1}, "6"),
    "permissions": ({"owner": 1, "connection": 1, "owner-single": 1}, "7"),
    "sibling_row": ({"owner": 2, "connection": 2}, "8"),
    "sibling_permissions": ({"owner": 2, "connection": 2}, "8"),
}
_CASES = [
    pytest.param(scenario, target, route, id=f"{scenario}-{target}-{route}")
    for target, (depths, _step) in _FAULT_TARGETS.items()
    for scenario in depths
    for route in ("one-row", "every-row")
]
# Steps that run before the row delete: a fault there leaves the faulted row.
_BEFORE_ROW = ("3a", "3b", "4", "6")


class TestTrustDeletionConverges:
    """The two rules of thoughts/reference/trust-row-deletion-invariants.md,
    for every step that can fault: the fault raises (never a success) and
    leaves the faulted row when it precedes the row delete, and retrying the
    route until it succeeds leaves nothing that authorises the connection
    (the client too, for its owner)."""

    @staticmethod
    def _rows_for(actor: ActorInterface, client_id: str) -> list:
        return TestClientConnectionDeletion._rows_for(actor, client_id)

    @staticmethod
    def _fresh(config, holder: ActorInterface) -> ActorInterface:
        from actingweb import actor as actor_module

        return ActorInterface(actor_module.Actor(holder.id, config=config))

    def _setup(self, config, scenario: str) -> dict:
        """An actor with the client's rows (three, or the owner's registration
        row alone), custom permissions on each, provider tokens on the
        authorization rows, a live access token and a live refresh token."""
        from actingweb import actor as actor_module
        from actingweb.constants import OAUTH_TOKENS_PREFIX
        from actingweb.oauth2_server.token_manager import get_actingweb_token_manager

        holder = ActorInterface.create(creator=f"{scenario}@example.com", config=config)
        owner = (
            holder
            if scenario.startswith("owner")
            else ActorInterface.create(creator="owner@example.com", config=config)
        )
        client_id = OAuth2ClientManager(owner.id, config).create_client(  # type: ignore[arg-type]
            client_name="Converge", trust_type="mcp_client"
        )["client_id"]
        sources = {
            "owner": ["oauth2_client", "oauth2"],
            "owner-single": [],
            "connection": ["oauth2_client", "oauth2", "oauth2_interactive"],
        }[scenario]
        for source in sources:
            assert holder.trust.create_or_update_oauth_trust(
                email=f"{scenario}@example.com",
                trust_type="mcp_client",
                oauth_tokens={"access_token": "g-at", "refresh_token": "g-rt"},
                established_via=source,
                client_id=client_id,
            )
        peer_ids = [t.peerid for t in self._rows_for(holder, client_id)]
        assert len(peer_ids) == (1 if scenario == "owner-single" else 3)
        for peer_id in peer_ids:
            assert TrustPermissionStore(config).store_permissions(
                TrustPermissions(
                    actor_id=holder.id,  # type: ignore[arg-type]
                    peer_id=peer_id,
                    trust_type="mcp_client",
                    properties={"patterns": ["memory_*"], "operations": ["read"]},
                    created_by="test",
                )
            )
        tokens = get_actingweb_token_manager(config)
        access = tokens.create_access_token(
            actor_id=holder.id,  # type: ignore[arg-type]
            client_id=client_id,
            scope="mcp",
            trust_type="mcp_client",
            grant_type="client_credentials",
        )
        assert access is not None
        code = tokens.create_authorization_code(
            holder.id,  # type: ignore[arg-type]
            client_id,
            {"access_token": "g"},
        )
        pair = tokens.exchange_authorization_code(code, client_id)
        assert pair is not None and pair.get("refresh_token")

        # What the deletion must end: all of it exists before.
        assert tokens.validate_access_token(access["access_token"]) is not None
        assert tokens.validate_access_token(pair["access_token"]) is not None
        core = actor_module.Actor(holder.id, config=config)
        assert core.store is not None
        with_provider_tokens = [
            p for p in peer_ids if core.store[f"{OAUTH_TOKENS_PREFIX}{p}"] is not None
        ]
        # The authorization rows, and the owner's registration row (the
        # code exchange stores its provider tokens there).
        owner_rows = 1 if scenario.startswith("owner") else 0
        assert len(with_provider_tokens) == len(sources) + owner_rows
        for peer_id in peer_ids:
            assert TrustPermissionStore(config).get_permissions(holder.id, peer_id)  # type: ignore[arg-type]
        return {
            "holder": holder,
            "owner": owner,
            "client_id": client_id,
            "peer_ids": peer_ids,
            "access_tokens": [access["access_token"], pair["access_token"]],
            "refresh_token": pair["refresh_token"],
        }

    @staticmethod
    def _patch(config, target: str, depth: int):
        """Patches that track which trust row ``Trust.delete`` is deleting
        (a stack: the sweep nests), and fault ``target`` on its first call
        at ``depth``. The state names the faulted row's peer id."""
        from contextlib import ExitStack
        from unittest import mock

        from actingweb import attribute, single_use
        from actingweb import trust as trust_module
        from actingweb.constants import OAUTH_TOKENS_PREFIX
        from actingweb.db.exceptions import DbError
        from actingweb.oauth2_server.client_registry import MCPClientRegistry
        from actingweb.oauth2_server.token_manager import (
            ActingWebTokenManager,
            TokenStoreUnavailable,
        )

        stack: list[str] = []
        state: dict = {"fired": False, "victim": None}
        original_delete = trust_module.Trust.delete

        def tracked(self, *args, **kwargs):
            stack.append(
                getattr(self, "peerid", None) or str((self.trust or {}).get("peerid"))
            )
            try:
                return original_delete(self, *args, **kwargs)
            finally:
                stack.pop()

        db_trust = config.DbTrust.DbTrust
        cls, name, when, error = {
            "revoke": (MCPClientRegistry, "revoke_connection_tokens", None, DbError),
            "disable": (MCPClientRegistry, "disable_client", None, DbError),
            "disable_tokens": (
                ActingWebTokenManager,
                "revoke_client_tokens",
                None,
                TokenStoreUnavailable,
            ),
            "provider_tokens": (
                attribute.InternalStore,
                "set_confirmed",
                lambda _s, k, *_a, **_k: k.startswith(OAUTH_TOKENS_PREFIX),
                DbError,
            ),
            # The index row went, the client row did not: the retry must
            # find the client by its row and disable it again.
            "client_row": (
                single_use,
                "delete_confirmed",
                lambda _c, _a, bucket, *_r, **_k: bucket == "mcp_clients",
                None,  # unconfirmed: what a backend fault looks like here
            ),
            "row": (db_trust, "delete", None, DbError),
            "permissions": (TrustPermissionStore, "delete_permissions", None, DbError),
            "sibling_row": (db_trust, "delete", None, DbError),
            "sibling_permissions": (
                TrustPermissionStore,
                "delete_permissions",
                None,
                DbError,
            ),
        }[target]
        original = getattr(cls, name)

        def faulty(*args, **kwargs):
            if (
                not state["fired"]
                and len(stack) == depth
                and (when is None or when(*args, **kwargs))
            ):
                state["fired"] = True
                state["victim"] = stack[-1]
                if error is None:
                    return False
                raise error("injected fault")
            return original(*args, **kwargs)

        patches = ExitStack()
        patches.enter_context(mock.patch.object(trust_module.Trust, "delete", tracked))
        patches.enter_context(mock.patch.object(cls, name, faulty))
        return patches, state

    @classmethod
    def _run(cls, config, holder: ActorInterface, client_id: str, route: str) -> None:
        from actingweb import actor as actor_module

        if route == "every-row":
            actor_module.Actor(holder.id, config=config).delete_reciprocal_trust(
                delete_peer=True
            )
            return
        fresh = cls._fresh(config, holder)
        for row in cls._rows_for(fresh, client_id):
            fresh.trust.delete_relationship(row.peerid)

    @pytest.mark.parametrize(("scenario", "target", "route"), _CASES)
    def test_a_fault_at_any_step_raises_and_a_retry_finishes(
        self, aw_app, scenario: str, target: str, route: str
    ):
        from actingweb import actor as actor_module
        from actingweb.constants import OAUTH_TOKENS_PREFIX
        from actingweb.db.exceptions import DbError
        from actingweb.oauth2_server.client_registry import MCPClientRegistry
        from actingweb.oauth2_server.token_manager import get_actingweb_token_manager
        from actingweb.trust_permissions import get_trust_permission_store

        depths, step = _FAULT_TARGETS[target]
        config = aw_app.get_config()
        s = self._setup(config, scenario)
        holder, client_id = s["holder"], s["client_id"]
        try:
            patches, state = self._patch(config, target, depths[scenario])
            # Rule 1: the fault raises; it never ends in success.
            with patches, pytest.raises(DbError):
                self._run(config, holder, client_id, route)
            assert state["fired"], f"{target} never ran on the {scenario} path"
            left_rows = [
                t.peerid for t in self._rows_for(self._fresh(config, holder), client_id)
            ]
            # Rule 2's handle: a fault before the row delete leaves the row.
            # Only checked for the route's own row: the sweep tries every
            # sibling before it raises, and a later sibling's own sweep can
            # delete a sibling that faulted.
            if step in _BEFORE_ROW and depths[scenario] == 1:
                assert state["victim"] in left_rows, "the faulted row must stay"
            if step == "3a":
                # The client row, which the retry reads (the index row may
                # already be gone).
                assert MCPClientRegistry(config).client_owned_by(
                    holder.id,  # type: ignore[arg-type]
                    client_id,
                ), "a faulted disable must leave the client row for the retry"

            # Rule 2: retrying the route finishes the job.
            for _ in range(4):
                if not self._rows_for(self._fresh(config, holder), client_id):
                    break
                self._run(config, holder, client_id, route)
            assert self._rows_for(self._fresh(config, holder), client_id) == []

            tokens = get_actingweb_token_manager(config)
            for access_token in s["access_tokens"]:
                assert tokens.validate_access_token(access_token) is None
            assert tokens.refresh_access_token(s["refresh_token"], client_id) is None
            core = actor_module.Actor(holder.id, config=config)
            assert core.store is not None
            permissions = get_trust_permission_store(config)
            for peer_id in s["peer_ids"]:
                assert core.store[f"{OAUTH_TOKENS_PREFIX}{peer_id}"] is None
                left = permissions.get_permissions(holder.id, peer_id)  # type: ignore[arg-type]
                if step in ("7", "8") and "permissions" in target:
                    if peer_id == state["victim"]:
                        # The table's accepted residue (step 7): the row is
                        # gone, and the next row for this peer id clears it.
                        continue
                assert left is None, f"permissions of {peer_id} survived"

            client = MCPClientRegistry(config)._load_client(client_id)
            if scenario.startswith("owner"):
                assert client is None, "the owner's client must be gone"
                assert not MCPClientRegistry(config).client_owned_by(
                    holder.id,  # type: ignore[arg-type]
                    client_id,
                ), "the owner's client row must be gone"
            else:
                assert client is not None, "another actor's client must stay"
        finally:
            holder.delete()
            if s["owner"] is not holder:
                s["owner"].delete()


class TestPeerRowPermissionResidue:
    """Trust.delete deletes a row's custom permissions after the row, so a
    fault there leaves them with the row gone (the table's step 7). A peer's
    peer id is stable: the next row for it must not inherit them (sixth
    verification, Issue 2)."""

    PEER = "a1b2c3d4e5f60718293a4b5c6d7e8f90"

    def _create_row(self, config, actor_id: str) -> bool:
        from actingweb import trust as trust_module

        return trust_module.Trust(
            actor_id=actor_id, peerid=self.PEER, config=config
        ).create(
            baseuri=f"https://peer.example.test/{self.PEER}",
            peer_type="urn:actingweb:example.test:peer",
            relationship="friend",
            approved=True,
            verified=True,
            established_via="trust",
        )

    def _grant(self, config, actor_id: str) -> None:
        assert TrustPermissionStore(config).store_permissions(
            TrustPermissions(
                actor_id=actor_id,
                peer_id=self.PEER,
                trust_type="friend",
                properties={"patterns": ["*"], "operations": ["read", "write"]},
                created_by="test",
            )
        )

    def test_a_recreated_peer_row_does_not_inherit_left_permissions(self, aw_app):
        from unittest import mock

        from actingweb import actor as actor_module
        from actingweb.db.exceptions import DbError
        from actingweb.trust_permissions import get_trust_permission_store

        config = aw_app.get_config()
        actor = ActorInterface.create(creator="residue@example.com", config=config)
        try:
            assert self._create_row(config, actor.id)  # type: ignore[arg-type]
            self._grant(config, actor.id)  # type: ignore[arg-type]
            with (
                mock.patch.object(
                    TrustPermissionStore,
                    "delete_permissions",
                    side_effect=DbError("injected fault"),
                ),
                pytest.raises(DbError),
            ):
                actor_module.Actor(actor.id, config=config).delete_reciprocal_trust(
                    peerid=self.PEER, delete_peer=False
                )
            store = get_trust_permission_store(config)
            assert store.get_permissions(actor.id, self.PEER) is not None  # type: ignore[arg-type]

            # The peer asks again and the owner approves: a fresh row.
            assert self._create_row(config, actor.id)  # type: ignore[arg-type]
            assert store.get_permissions(actor.id, self.PEER) is None  # type: ignore[arg-type]
        finally:
            actor.delete()

    def test_recreating_a_live_row_keeps_its_permissions(self, aw_app):
        """Create is an upsert: a re-sent request over a live row must not
        reset the custom permissions its owner set."""
        from actingweb.trust_permissions import get_trust_permission_store

        config = aw_app.get_config()
        actor = ActorInterface.create(creator="upsert@example.com", config=config)
        try:
            assert self._create_row(config, actor.id)  # type: ignore[arg-type]
            self._grant(config, actor.id)  # type: ignore[arg-type]
            assert self._create_row(config, actor.id)  # type: ignore[arg-type]
            store = get_trust_permission_store(config)
            assert store.get_permissions(actor.id, self.PEER) is not None  # type: ignore[arg-type]
        finally:
            actor.delete()
