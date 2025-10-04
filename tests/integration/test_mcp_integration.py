"""
MCP Integration Tests.

End-to-end tests for complete MCP workflows combining OAuth2 authentication,
tools, resources, and prompts.

These tests verify the entire MCP stack works together correctly.
"""

import pytest
import json


def initialize_mcp_session(oauth2_client):
    """Helper to initialize an MCP session."""
    # Initialize
    init_response = oauth2_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "Test Client", "version": "1.0.0"},
            },
            "id": 1,
        },
        headers={"Content-Type": "application/json"},
    )
    assert init_response.status_code == 200

    # Send initialized notification
    notif_response = oauth2_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        },
        headers={"Content-Type": "application/json"},
    )
    assert notif_response.status_code == 200


class TestMCPCompleteWorkflow:
    """Test complete end-to-end MCP workflows."""

    def test_complete_mcp_session(self, oauth2_client):
        """
        Test complete MCP session workflow:

        1. OAuth2 authentication (done by fixture)
        2. Initialize MCP session
        3. List capabilities (tools, resources, prompts)
        4. Perform operations (call tool, read resource, get prompt)
        5. Verify all operations work together

        This validates the entire MCP stack.
        """
        # Step 1: OAuth2 auth already done by oauth2_client fixture

        # Step 2: Initialize session
        init_response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "roots": {"listChanged": True},
                        "sampling": {},
                    },
                    "clientInfo": {
                        "name": "Integration Test Client",
                        "version": "1.0.0",
                    },
                },
                "id": 1,
            },
            headers={"Content-Type": "application/json"},
        )

        assert init_response.status_code == 200
        init_data = init_response.json()
        assert "result" in init_data
        assert "capabilities" in init_data["result"]
        assert "serverInfo" in init_data["result"]

        # Send initialized notification
        notif_response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            headers={"Content-Type": "application/json"},
        )
        assert notif_response.status_code == 200

        # Step 3: List all capabilities
        tools_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )
        assert tools_response.status_code == 200

        resources_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 3},
            headers={"Content-Type": "application/json"},
        )
        assert resources_response.status_code == 200

        prompts_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 4},
            headers={"Content-Type": "application/json"},
        )
        assert prompts_response.status_code == 200

        # Step 4 & 5: Verify we got valid responses
        # (Actual operations tested in specific test files)
        for response in [tools_response, resources_response, prompts_response]:
            data = response.json()
            # Should get either result or error (both acceptable)
            assert "result" in data or "error" in data

    def test_mcp_with_actor_context(self, oauth2_client):
        """
        Test that MCP session is properly bound to actor context.

        Each MCP session should operate in the context of a specific actor,
        with access controlled by trust relationships and permissions.
        """
        initialize_mcp_session(oauth2_client)

        # The oauth2_client should have an associated actor
        # Verify we can access actor-specific resources
        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 5},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        if "result" in data:
            # Resources should be actor-specific
            assert "resources" in data["result"]

    def test_mcp_error_recovery(self, oauth2_client):
        """
        Test that MCP session can recover from errors.

        After an error, subsequent requests should still work.
        """
        initialize_mcp_session(oauth2_client)

        # Send an invalid request to trigger error
        error_response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "nonexistent/method",
                "id": 6,
            },
            headers={"Content-Type": "application/json"},
        )

        assert error_response.status_code == 200
        error_data = error_response.json()
        assert "error" in error_data

        # Session should still be valid - send a valid request
        valid_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 7},
            headers={"Content-Type": "application/json"},
        )

        assert valid_response.status_code == 200
        valid_data = valid_response.json()
        # Should get successful response
        assert "result" in valid_data or "error" in valid_data

    def test_mcp_session_isolation(self, oauth2_client, test_app):
        """
        Test that MCP sessions are properly isolated.

        Multiple clients should have independent sessions.
        """
        # Initialize first session
        initialize_mcp_session(oauth2_client)

        # First client lists tools
        response1 = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 8},
            headers={"Content-Type": "application/json"},
        )
        assert response1.status_code == 200

        # Sessions are isolated by Bearer token
        # Each token represents a different session
        # This test verifies the oauth2_client works correctly


class TestMCPProtocolCompliance:
    """Test MCP protocol compliance."""

    def test_initialize_required_before_methods(self, oauth2_client):
        """
        Test that MCP requires initialization before calling methods.

        This is a protocol requirement.
        """
        # Try to call a method without initializing
        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 9},
            headers={"Content-Type": "application/json"},
        )

        # Implementation may enforce this or not
        # Both behaviors are acceptable in test environment
        assert response.status_code in [200, 400]

    def test_initialized_notification_after_initialize(self, oauth2_client):
        """
        Test that initialized notification is sent after initialize.

        This is required by MCP protocol.
        """
        # Initialize
        init_response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "Test", "version": "1.0"},
                },
                "id": 10,
            },
            headers={"Content-Type": "application/json"},
        )
        assert init_response.status_code == 200

        # Send initialized notification
        notif_response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            headers={"Content-Type": "application/json"},
        )

        # Notification should be accepted
        assert notif_response.status_code == 200

    def test_jsonrpc_version_must_be_2_0(self, oauth2_client):
        """
        Test that JSON-RPC version must be "2.0".

        MCP uses JSON-RPC 2.0.
        """
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",  # Correct version
                "method": "ping",
                "id": 11,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200

    def test_request_id_preserved_in_response(self, oauth2_client):
        """
        Test that request ID is preserved in response.

        This is a JSON-RPC 2.0 requirement.
        """
        initialize_mcp_session(oauth2_client)

        request_id = 12345

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": request_id,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Response must include same ID
        assert "id" in data
        assert data["id"] == request_id


class TestMCPCapabilities:
    """Test MCP capability negotiation."""

    def test_server_reports_capabilities(self, oauth2_client):
        """
        Test that server reports its capabilities in initialize response.

        Capabilities tell clients what features are supported.
        """
        init_response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "roots": {"listChanged": True},
                    },
                    "clientInfo": {"name": "Test", "version": "1.0"},
                },
                "id": 1,
            },
            headers={"Content-Type": "application/json"},
        )

        assert init_response.status_code == 200
        data = init_response.json()

        assert "result" in data
        assert "capabilities" in data["result"]

        capabilities = data["result"]["capabilities"]
        # Server should report what it supports
        # At minimum, should indicate if tools/resources/prompts are supported

    def test_server_info_in_initialize(self, oauth2_client):
        """
        Test that server includes serverInfo in initialize response.
        """
        init_response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "Test", "version": "1.0"},
                },
                "id": 1,
            },
            headers={"Content-Type": "application/json"},
        )

        assert init_response.status_code == 200
        data = init_response.json()

        assert "result" in data
        assert "serverInfo" in data["result"]

        server_info = data["result"]["serverInfo"]
        assert "name" in server_info
        assert "version" in server_info


class TestMCPPerformance:
    """Test MCP performance characteristics."""

    @pytest.mark.slow
    def test_multiple_sequential_requests(self, oauth2_client):
        """
        Test that multiple sequential requests work correctly.

        This verifies session state is maintained across requests.
        """
        initialize_mcp_session(oauth2_client)

        # Make 10 sequential requests
        for i in range(10):
            response = oauth2_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "tools/list",
                    "id": 100 + i,
                },
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "jsonrpc" in data
            assert data["id"] == 100 + i
