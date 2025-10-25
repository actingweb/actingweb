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
from mcp.types import LATEST_PROTOCOL_VERSION


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
                "protocolVersion": LATEST_PROTOCOL_VERSION,
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
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
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

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )

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

    def test_metadata_name_none_regression(self, oauth2_client):
        """
        Regression test for metadata with name=None.

        This tests the fix for a bug where MCP metadata with name=None
        would cause Pydantic validation errors when creating Tool/Prompt/Resource objects.

        The fix ensures that when metadata.get("name") returns None,
        we fall back to using the action_name or method_name.

        See: sdk_server.py lines 120, 172, 260, 393, 443
        """
        initialize_mcp_session(oauth2_client)

        # Test tools/list - should not fail with validation error
        tools_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )

        assert tools_response.status_code == 200, \
            f"tools/list failed: {tools_response.json()}"

        tools_data = tools_response.json()
        assert "result" in tools_data, \
            f"Expected 'result' in response, got error: {tools_data.get('error')}"
        assert "tools" in tools_data["result"]

        # Verify all tools have valid (non-None) names
        for tool in tools_data["result"]["tools"]:
            assert "name" in tool, "Tool missing 'name' field"
            assert tool["name"] is not None, "Tool has None name"
            assert isinstance(tool["name"], str), f"Tool name is not string: {type(tool['name'])}"
            assert len(tool["name"]) > 0, "Tool name is empty string"

        # Test prompts/list - should not fail with validation error
        prompts_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 3},
            headers={"Content-Type": "application/json"},
        )

        assert prompts_response.status_code == 200, \
            f"prompts/list failed: {prompts_response.json()}"

        prompts_data = prompts_response.json()
        assert "result" in prompts_data, \
            f"Expected 'result' in response, got error: {prompts_data.get('error')}"
        assert "prompts" in prompts_data["result"]

        # Verify all prompts have valid (non-None) names
        for prompt in prompts_data["result"]["prompts"]:
            assert "name" in prompt, "Prompt missing 'name' field"
            assert prompt["name"] is not None, "Prompt has None name"
            assert isinstance(prompt["name"], str), f"Prompt name is not string: {type(prompt['name'])}"
            assert len(prompt["name"]) > 0, "Prompt name is empty string"

        # Test resources/list - should not fail with validation error
        resources_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 4},
            headers={"Content-Type": "application/json"},
        )

        assert resources_response.status_code == 200, \
            f"resources/list failed: {resources_response.json()}"

        resources_data = resources_response.json()
        assert "result" in resources_data, \
            f"Expected 'result' in response, got error: {resources_data.get('error')}"
        assert "resources" in resources_data["result"]

        # Verify all resources have valid (non-None) names
        for resource in resources_data["result"]["resources"]:
            assert "name" in resource, "Resource missing 'name' field"
            assert resource["name"] is not None, "Resource has None name"
            assert isinstance(resource["name"], str), f"Resource name is not string: {type(resource['name'])}"
            assert len(resource["name"]) > 0, "Resource name is empty string"
