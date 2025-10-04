"""
Runtime Context Advanced Tests.

Tests runtime context for client detection and customization:
- MCP context setting and retrieval
- OAuth2 context setting and retrieval
- Web context setting and retrieval
- Client info extraction from context
- Context persistence during request processing

Medium priority - used for response customization in actingweb_mcp.

References:
- actingweb/runtime_context.py:1-334 - RuntimeContext
- actingweb_mcp uses runtime context for client detection and customization
"""

import pytest
from actingweb.interface.app import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.runtime_context import RuntimeContext, get_client_info_from_context
from actingweb.actor import Actor as CoreActor


@pytest.fixture
def aw_app():
    """Create ActingWeb app for testing runtime context."""
    return ActingWebApp(
        aw_type="urn:actingweb:test:runtime_context",
        database="dynamodb",
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def test_actor_with_config(aw_app):
    """Create test actor with config and automatic cleanup."""
    config = aw_app.get_config()
    actor = ActorInterface.create(creator="test@example.com", config=config)
    yield (actor, config)
    actor.delete()


class TestRuntimeContextMCP:
    """Test runtime context for MCP clients."""

    def test_set_and_get_mcp_context(self, test_actor_with_config):
        """
        Test setting and retrieving MCP context.

        actingweb_mcp uses runtime context to detect client type.

        Spec: actingweb/runtime_context.py:95-134
        """
        test_actor, config = test_actor_with_config
        # Get core actor for runtime context
        core_actor = CoreActor(test_actor.id, config=config)

        # Set MCP context (as MCP handler does)
        runtime_context = RuntimeContext(core_actor)
        runtime_context.set_mcp_context(
            client_id="mcp_chatgpt_123",
            trust_relationship=None,  # Would be trust object in real usage
            peer_id="oauth2_client:chatgpt@openai.com:mcp_chatgpt_123",
            token_data={"scope": "mcp"}
        )

        # Get MCP context
        mcp_context = runtime_context.get_mcp_context()
        assert mcp_context is not None
        assert mcp_context.client_id == "mcp_chatgpt_123"
        assert mcp_context.peer_id == "oauth2_client:chatgpt@openai.com:mcp_chatgpt_123"

    def test_mcp_context_request_type(self, test_actor_with_config):
        """
        Test that MCP context sets request type to 'mcp'.

        Spec: actingweb/runtime_context.py:141-147
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        runtime_context.set_mcp_context(
            client_id="mcp_test_123",
            trust_relationship=None,
            peer_id="test_peer"
        )

        request_type = runtime_context.get_request_type()
        assert request_type == "mcp"

    def test_get_client_info_from_mcp_context(self, test_actor_with_config):
        """
        Test extracting client info from MCP context.

        actingweb_mcp uses this for client-specific formatting.

        Spec: actingweb/runtime_context.py:238-276
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        # Create mock trust relationship with client info
        class MockTrust:
            def __init__(self):
                self.client_name = "ChatGPT"
                self.client_version = "4.0"

        mock_trust = MockTrust()

        runtime_context.set_mcp_context(
            client_id="mcp_chatgpt_123",
            trust_relationship=mock_trust,
            peer_id="test_peer"
        )

        # Get client info
        client_info = get_client_info_from_context(core_actor)
        assert client_info is not None
        assert client_info["type"] == "mcp"
        assert client_info["name"] == "ChatGPT"


class TestRuntimeContextOAuth2:
    """Test runtime context for OAuth2 clients."""

    def test_set_and_get_oauth2_context(self, test_actor_with_config):
        """
        Test setting and retrieving OAuth2 context.

        Spec: actingweb/runtime_context.py:136-180
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        runtime_context.set_oauth2_context(
            client_id="oauth_client_123",
            user_email="user@example.com",
            scopes=["read", "write"]
        )

        oauth2_context = runtime_context.get_oauth2_context()
        assert oauth2_context is not None
        assert oauth2_context.client_id == "oauth_client_123"
        assert oauth2_context.user_email == "user@example.com"
        assert "read" in oauth2_context.scopes

    def test_oauth2_context_request_type(self, test_actor_with_config):
        """
        Test that OAuth2 context sets request type to 'oauth2'.

        Spec: actingweb/runtime_context.py:141-147
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        runtime_context.set_oauth2_context(
            client_id="oauth_test",
            user_email="test@example.com",
            scopes=["read"]
        )

        request_type = runtime_context.get_request_type()
        assert request_type == "oauth2"


class TestRuntimeContextWeb:
    """Test runtime context for web browser clients."""

    def test_set_and_get_web_context(self, test_actor_with_config):
        """
        Test setting and retrieving web context.

        Spec: actingweb/runtime_context.py:182-224
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        runtime_context.set_web_context(
            session_id="sess_abc123",
            user_agent="Mozilla/5.0",
            ip_address="192.168.1.1",
            authenticated_user="user@example.com"
        )

        web_context = runtime_context.get_web_context()
        assert web_context is not None
        assert web_context.session_id == "sess_abc123"
        assert web_context.user_agent == "Mozilla/5.0"

    def test_web_context_request_type(self, test_actor_with_config):
        """
        Test that web context sets request type to 'web'.

        Spec: actingweb/runtime_context.py:141-147
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        runtime_context.set_web_context(
            session_id="test_session",
            user_agent="Chrome"
        )

        request_type = runtime_context.get_request_type()
        assert request_type == "web"


class TestRuntimeContextCleanup:
    """Test runtime context cleanup operations."""

    def test_clear_context(self, test_actor_with_config):
        """
        Test clearing runtime context.

        Spec: actingweb/runtime_context.py:226-236
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        # Set MCP context
        runtime_context.set_mcp_context(
            client_id="mcp_test",
            trust_relationship=None,
            peer_id="test_peer"
        )

        # Verify it's set
        assert runtime_context.get_request_type() == "mcp"

        # Clear context
        runtime_context.clear_context()

        # Verify it's cleared
        assert runtime_context.get_request_type() is None

    def test_context_isolation_between_actors(self, aw_app):
        """
        Test that runtime context is isolated between different actors.

        Important for multi-tenant security.

        Spec: actingweb/runtime_context.py - Per-actor isolation
        """
        config = aw_app.get_config()
        actor1 = ActorInterface.create(creator="user1@example.com", config=config)
        actor2 = ActorInterface.create(creator="user2@example.com", config=config)

        try:
            core_actor1 = CoreActor(actor1.id, config=config)
            core_actor2 = CoreActor(actor2.id, config=config)

            # Set MCP context for actor1
            runtime_context1 = RuntimeContext(core_actor1)
            runtime_context1.set_mcp_context(
                client_id="mcp_actor1",
                trust_relationship=None,
                peer_id="actor1_peer"
            )

            # Set OAuth2 context for actor2
            runtime_context2 = RuntimeContext(core_actor2)
            runtime_context2.set_oauth2_context(
                client_id="oauth_actor2",
                user_email="actor2@example.com",
                scopes=["read"]
            )

            # Verify isolation
            assert runtime_context1.get_request_type() == "mcp"
            assert runtime_context2.get_request_type() == "oauth2"

            mcp_ctx = runtime_context1.get_mcp_context()
            oauth_ctx = runtime_context2.get_oauth2_context()

            assert mcp_ctx.client_id == "mcp_actor1"
            assert oauth_ctx.client_id == "oauth_actor2"
        finally:
            actor1.delete()
            actor2.delete()


class TestRuntimeContextClientDetection:
    """Test client detection using runtime context."""

    def test_detect_chatgpt_from_context(self, test_actor_with_config):
        """
        Test detecting ChatGPT client from runtime context.

        actingweb_mcp uses client detection for customization.

        Spec: actingweb/runtime_context.py:238-276
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        class MockTrust:
            client_name = "ChatGPT"
            client_version = "GPT-4"

        runtime_context.set_mcp_context(
            client_id="mcp_chatgpt",
            trust_relationship=MockTrust(),
            peer_id="test_peer"
        )

        client_info = get_client_info_from_context(core_actor)
        assert client_info is not None
        assert "chatgpt" in client_info["name"].lower()

    def test_detect_claude_from_context(self, test_actor_with_config):
        """
        Test detecting Claude client from runtime context.

        Spec: actingweb/runtime_context.py:238-276
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        class MockTrust:
            client_name = "Claude"
            client_version = "3.5"

        runtime_context.set_mcp_context(
            client_id="mcp_claude",
            trust_relationship=MockTrust(),
            peer_id="test_peer"
        )

        client_info = get_client_info_from_context(core_actor)
        assert client_info is not None
        assert "claude" in client_info["name"].lower()

    def test_no_client_info_without_context(self, test_actor_with_config):
        """
        Test that client info returns None when no context is set.

        Spec: actingweb/runtime_context.py:238-276
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)

        # No context set
        client_info = get_client_info_from_context(core_actor)
        assert client_info is None


class TestRuntimeContextCustomContext:
    """Test custom context extensions."""

    def test_set_custom_context(self, test_actor_with_config):
        """
        Test setting custom context for extensibility.

        Spec: actingweb/runtime_context.py:278-334
        """
        test_actor, config = test_actor_with_config
        core_actor = CoreActor(test_actor.id, config=config)
        runtime_context = RuntimeContext(core_actor)

        # Set custom context
        custom_data = {
            "service_id": "custom_service_123",
            "api_version": "v2",
            "features": ["advanced_search"]
        }
        runtime_context.set_custom_context("my_service", custom_data)

        # Retrieve custom context
        retrieved = runtime_context.get_custom_context("my_service")
        assert retrieved is not None
        assert retrieved["service_id"] == "custom_service_123"
        assert "advanced_search" in retrieved["features"]
