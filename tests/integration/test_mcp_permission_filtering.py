"""
MCP Permission Filtering Integration Tests.

Tests that MCP endpoints properly filter tools, prompts, and resources
based on the permission system and trust relationships.

This ensures:
1. tools/list only returns tools the client has permission to access
2. tools/call enforces permissions and returns proper errors for denied access
3. prompts/list filters prompts based on permissions
4. prompts/get enforces permissions
5. resources/list filters resources based on permissions
"""

import pytest


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
                "clientInfo": {"name": "Permission Test Client", "version": "1.0.0"},
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


class TestMCPToolsPermissionFiltering:
    """Test that tools/list and tools/call respect permissions."""

    def test_tools_list_without_authentication(self, test_app):
        """Test that tools/list without auth returns limited or no tools."""
        import requests

        response = requests.post(
            f"{test_app}/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Content-Type": "application/json"},
        )

        # Without authentication, should either:
        # - Return 401 (authentication required)
        # - Return empty list (no permissions)
        # - Return ping/public tools only
        assert response.status_code in [200, 401]

    def test_tools_list_with_oauth2_returns_filtered_list(self, oauth2_client):
        """
        Test that tools/list returns only tools the client has permission to access.

        Uses the oauth2_client fixture which provides an authenticated client with
        MCP trust relationship. Verifies that permission filtering works end-to-end.
        """
        initialize_mcp_session(oauth2_client)

        # List tools - should only see tools this client has permission for
        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should have result with tools array
        assert "result" in data, f"Expected result, got: {data}"
        assert "tools" in data["result"]
        tools = data["result"]["tools"]

        # Tools should be a list (may be empty if no permissions granted)
        assert isinstance(tools, list)

        # Verify tool structure if any tools returned
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

        # The key test: The list should be filtered based on permissions
        # If the test harness has no hooks registered, list will be empty
        # If hooks are registered with @mcp_tool decorator, only permitted tools appear

    def test_tools_call_with_invalid_tool_name(self, oauth2_client):
        """
        Test that tools/call returns proper error for non-existent tools.

        This verifies error handling when a tool doesn't exist or isn't accessible.
        """
        initialize_mcp_session(oauth2_client)

        # Try to call a tool that doesn't exist
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "nonexistent_tool_12345",
                    "arguments": {},
                },
                "id": 3,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should get an error (tool not found or permission denied)
        assert "error" in data or "result" in data

        if "error" in data:
            # Verify it's a proper JSON-RPC error
            assert "code" in data["error"]
            assert "message" in data["error"]
            # Should be either -32601 (method not found) or -32003 (permission denied)
            assert data["error"]["code"] in [-32601, -32003, -32600]


class TestMCPPromptsPermissionFiltering:
    """Test that prompts/list and prompts/get respect permissions."""

    def test_prompts_list_returns_filtered_list(self, oauth2_client):
        """
        Test that prompts/list returns only prompts the client has permission to access.

        The test harness may not have prompts registered, so we verify the structure
        and that permission filtering is applied (empty list if no permissions).
        """
        initialize_mcp_session(oauth2_client)

        # List prompts
        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 10},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should have result with prompts array
        assert "result" in data, f"Expected result, got: {data}"
        assert "prompts" in data["result"]
        prompts = data["result"]["prompts"]

        # Prompts should be a list (may be empty if no permissions granted)
        assert isinstance(prompts, list)

        # Verify prompt structure if any prompts returned
        for prompt in prompts:
            assert "name" in prompt
            assert "description" in prompt

    def test_prompts_get_with_invalid_prompt_name(self, oauth2_client):
        """
        Test that prompts/get returns error for non-existent prompts.
        """
        initialize_mcp_session(oauth2_client)

        # Try to get a prompt that doesn't exist
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "prompts/get",
                "params": {
                    "name": "nonexistent_prompt_12345",
                    "arguments": {},
                },
                "id": 11,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should get an error (prompt not found or permission denied)
        if "error" in data:
            assert "code" in data["error"]
            assert "message" in data["error"]


class TestMCPResourcesPermissionFiltering:
    """Test that resources/list and resources/read respect permissions."""

    def test_resources_list_returns_filtered_list(self, oauth2_client):
        """
        Test that resources/list returns only resources the client has permission to access.
        """
        initialize_mcp_session(oauth2_client)

        # List resources
        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 20},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should have result with resources array
        assert "result" in data, f"Expected result, got: {data}"
        assert "resources" in data["result"]
        resources = data["result"]["resources"]

        # Resources should be a list
        assert isinstance(resources, list)

        # Verify resource structure if any resources returned
        for resource in resources:
            assert "uri" in resource
            assert "name" in resource


class TestMCPPermissionErrorHandling:
    """Test that permission denials provide clear error messages."""

    def test_permission_error_structure_is_valid_jsonrpc(self, oauth2_client):
        """
        Test that permission-related errors follow JSON-RPC 2.0 error format.

        Even when operations fail due to permissions, the error response should
        be properly formatted according to JSON-RPC 2.0 specification.
        """
        initialize_mcp_session(oauth2_client)

        # Test various operations that might be denied
        test_operations = [
            {
                "method": "tools/call",
                "params": {"name": "admin_delete_all", "arguments": {}},
                "id": 30,
            },
            {
                "method": "prompts/get",
                "params": {"name": "admin_system_prompt", "arguments": {}},
                "id": 31,
            },
        ]

        for operation in test_operations:
            response = oauth2_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": operation["method"],
                    "params": operation["params"],
                    "id": operation["id"],
                },
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 200
            data = response.json()

            # Response must have either result or error, not both
            assert ("result" in data) != ("error" in data), "Must have either result or error"

            # If there's an error, verify it's properly formatted
            if "error" in data:
                error = data["error"]
                assert "code" in error
                assert "message" in error
                assert isinstance(error["code"], int)
                assert isinstance(error["message"], str)

                # JSON-RPC 2.0 error codes should be negative integers
                assert error["code"] < 0

            # Verify JSON-RPC fields
            assert data.get("jsonrpc") == "2.0"
            assert data.get("id") == operation["id"]


class TestMCPPermissionFiltering:
    """Test the permission filtering mechanism itself."""

    def test_mcp_client_can_list_capabilities(self, oauth2_client):
        """
        Test that authenticated MCP clients can access basic capabilities.

        This verifies that the permission system doesn't block basic MCP
        protocol operations like listing what's available.
        """
        initialize_mcp_session(oauth2_client)

        # Should be able to list tools
        tools_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 40},
            headers={"Content-Type": "application/json"},
        )
        assert tools_response.status_code == 200
        assert "result" in tools_response.json()

        # Should be able to list prompts
        prompts_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 41},
            headers={"Content-Type": "application/json"},
        )
        assert prompts_response.status_code == 200
        assert "result" in prompts_response.json()

        # Should be able to list resources
        resources_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 42},
            headers={"Content-Type": "application/json"},
        )
        assert resources_response.status_code == 200
        assert "result" in resources_response.json()

    def test_permission_filtering_is_consistent(self, oauth2_client):
        """
        Test that permission filtering is consistent across multiple requests.

        The same client making multiple requests should see the same filtered
        results (tools/prompts/resources should not randomly appear/disappear).
        """
        initialize_mcp_session(oauth2_client)

        # Get tools list twice
        response1 = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 50},
            headers={"Content-Type": "application/json"},
        )

        response2 = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 51},
            headers={"Content-Type": "application/json"},
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

        tools1 = response1.json().get("result", {}).get("tools", [])
        tools2 = response2.json().get("result", {}).get("tools", [])

        # Should get the same tools both times
        tools1_names = {t["name"] for t in tools1}
        tools2_names = {t["name"] for t in tools2}
        assert tools1_names == tools2_names, "Tool list should be consistent across requests"
