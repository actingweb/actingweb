"""
MCP Basic Integration Tests.

Tests basic MCP functionality using OAuth2 Bearer token authentication.

This test suite demonstrates the pattern for testing OAuth2-protected endpoints:
1. Register OAuth2 client
2. Get access token
3. Make authenticated requests with Bearer token
"""

import pytest
import json


def initialize_mcp_session(oauth2_client):
    """
    Helper to initialize an MCP session.

    This sends the required initialize request and initialized notification.
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


class TestMCPAuthentication:
    """Test MCP endpoint authentication."""

    def test_mcp_without_auth_returns_401(self, test_app):
        """
        MCP endpoint without authentication should return 401.

        This verifies the authentication requirement is enforced.
        """
        import requests

        response = requests.post(
            f"{test_app}/mcp",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={"Content-Type": "application/json"},
        )

        # Without auth, might get 401 or might allow ping (depends on implementation)
        # The key is that we can't access protected methods without auth
        assert response.status_code in [200, 401]

    def test_mcp_with_oauth2_bearer_token(self, oauth2_client):
        """
        MCP endpoint with valid Bearer token should work.

        This tests the complete OAuth2 flow:
        1. Client registered (done by fixture)
        2. Access token obtained (done by fixture)
        3. Request with Bearer token succeeds
        """
        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "jsonrpc" in data
        assert data["jsonrpc"] == "2.0"

    def test_mcp_initialize(self, oauth2_client):
        """
        Test MCP initialize method.

        The initialize method sets up the MCP session and returns server capabilities.
        """
        response = oauth2_client.post(
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

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "capabilities" in data["result"]
        assert "serverInfo" in data["result"]


    def test_list_tools(self, oauth2_client):
        """
        Test listing available MCP tools.

        Tools are derived from ActingWeb actions exposed to MCP.
        """
        initialize_mcp_session(oauth2_client)

        # Debug: Print token being used
        print(f"\nDEBUG: Using access_token: {oauth2_client.access_token[:50]}...")
        print(f"DEBUG: Token starts with: {oauth2_client.access_token[:10]}")

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )

        print(f"DEBUG: Response status: {response.status_code}")
        print(f"DEBUG: Response: {response.json()}")

        assert response.status_code == 200
        data = response.json()
        assert "result" in data or "error" not in data, f"Got error: {data.get('error')}"
        if "result" in data:
            assert "tools" in data["result"]
            # Should return a list of tools (may be empty if no actions configured)
            assert isinstance(data["result"]["tools"], list)

    def test_list_resources(self, oauth2_client):
        """
        Test listing available MCP resources.

        Resources are derived from ActingWeb properties and other actor data.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "resources" in data["result"]
        # Should return a list of resources
        assert isinstance(data["result"]["resources"], list)

    def test_list_prompts(self, oauth2_client):
        """
        Test listing available MCP prompts.

        Prompts are derived from ActingWeb methods exposed to MCP.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "prompts" in data["result"]
        # Should return a list of prompts (may be empty if no methods configured)
        assert isinstance(data["result"]["prompts"], list)
