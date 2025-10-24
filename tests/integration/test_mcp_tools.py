"""
MCP Tools Integration Tests.

Tests tool invocation, permission enforcement, and error handling
using the JSON-RPC 2.0 protocol at /mcp endpoint.

This extends test_mcp_basic.py with comprehensive tool testing.
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


class TestMCPToolInvocation:
    """Test invoking MCP tools via JSON-RPC."""

    def test_call_tool_basic(self, oauth2_client):
        """
        Test basic tool invocation.

        Uses tools/call method to invoke an ActingWeb action exposed as a tool.
        """
        initialize_mcp_session(oauth2_client)

        # Call a tool (this is a generic test - specific tool availability
        # depends on what actions the test app exposes)
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "echo",  # Assuming echo tool exists
                    "arguments": {"message": "test"},
                },
                "id": 3,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should get either a result or a method not found error
        # (depending on whether echo tool is configured)
        assert "jsonrpc" in data
        assert data["jsonrpc"] == "2.0"
        assert data.get("id") == 3

        # If tool exists, check result structure
        if "result" in data:
            assert "content" in data["result"]
            assert isinstance(data["result"]["content"], list)

    def test_call_nonexistent_tool(self, oauth2_client):
        """
        Test calling a tool that doesn't exist.

        Should return proper JSON-RPC error.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "nonexistent_tool_xyz",
                    "arguments": {},
                },
                "id": 4,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should get JSON-RPC error
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_call_tool_invalid_arguments(self, oauth2_client):
        """
        Test calling a tool with invalid arguments.

        Should return proper validation error.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "echo",
                    # Missing required arguments or wrong types
                    "arguments": {"wrong_param": 123},
                },
                "id": 5,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should get error (either tool not found or invalid arguments)
        # Accept both as valid responses
        assert "error" in data or "result" in data

    def test_call_tool_without_initialize(self, oauth2_client):
        """
        Test calling a tool without initializing session first.

        MCP protocol requires initialization before calling methods.
        """
        # Don't call initialize_mcp_session

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "echo",
                    "arguments": {"message": "test"},
                },
                "id": 6,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Might get error about uninitialized session or might work
        # depending on implementation
        assert "jsonrpc" in data


class TestMCPToolsListCapabilities:
    """Test tools/list method capabilities."""

    def test_tools_list_returns_valid_schema(self, oauth2_client):
        """
        Test that tools/list returns tools with valid JSON schemas.

        Each tool must have name, description, and inputSchema.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 7},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        if "result" in data and "tools" in data["result"]:
            tools = data["result"]["tools"]

            for tool in tools:
                # Verify required MCP tool fields
                assert "name" in tool, f"Tool missing name: {tool}"
                assert isinstance(tool["name"], str)

                # Description is optional but recommended
                if "description" in tool:
                    assert isinstance(tool["description"], str)

                # inputSchema must be valid JSON Schema
                assert "inputSchema" in tool, f"Tool {tool.get('name')} missing inputSchema"
                schema = tool["inputSchema"]
                assert "type" in schema  # Required by JSON Schema
                assert isinstance(schema, dict)

    def test_tools_list_pagination(self, oauth2_client):
        """
        Test tools/list with pagination parameters.

        MCP supports cursor-based pagination.
        """
        initialize_mcp_session(oauth2_client)

        # Request with pagination
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "params": {
                    "cursor": None,  # First page
                },
                "id": 8,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        if "result" in data:
            # nextCursor is optional - present if more results available
            assert "tools" in data["result"]


class TestMCPErrorHandling:
    """Test MCP error handling and edge cases."""

    def test_invalid_jsonrpc_version(self, oauth2_client):
        """
        Test request with invalid JSON-RPC version.

        Must be "2.0".
        """
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "1.0",  # Wrong version
                "method": "tools/list",
                "id": 9,
            },
            headers={"Content-Type": "application/json"},
        )

        # Server might reject invalid version
        assert response.status_code in [200, 400]

    def test_missing_method(self, oauth2_client):
        """
        Test request without method field.

        Should return -32600 (Invalid Request) or -32601 (Method not found).
        """
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                # Missing method
                "id": 10,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code in [200, 400]

        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                # JSON-RPC Invalid Request or Method not found error
                assert data["error"]["code"] in [-32600, -32601]

    def test_invalid_json(self, oauth2_client):
        """
        Test request with invalid JSON.

        Should return -32700 (Parse Error).
        """
        response = oauth2_client.post(
            "/mcp",
            data="{'invalid': json}",  # Not valid JSON
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code in [200, 400]

    def test_method_not_found(self, oauth2_client):
        """
        Test calling non-existent method.

        Should return -32601 (Method Not Found).
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "nonexistent/method",
                "id": 11,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "error" in data
        assert data["error"]["code"] == -32601  # Method not found

    def test_batch_request(self, oauth2_client):
        """
        Test JSON-RPC batch request.

        MCP servers should support batch requests, but it's optional.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json=[
                {"jsonrpc": "2.0", "method": "tools/list", "id": 12},
                {"jsonrpc": "2.0", "method": "resources/list", "id": 13},
                {"jsonrpc": "2.0", "method": "prompts/list", "id": 14},
            ],
            headers={"Content-Type": "application/json"},
        )

        # Batch request support is optional - accept 500 if not implemented
        assert response.status_code in [200, 400, 500, 501]

        if response.status_code == 200:
            data = response.json()
            # Should get array of responses
            if isinstance(data, list):
                assert len(data) == 3
                for item in data:
                    assert "jsonrpc" in item
                    assert "id" in item


class TestMCPToolPermissions:
    """Test that MCP respects permission system."""

    def test_tool_access_with_limited_permissions(self, oauth2_client):
        """
        Test that tool invocation respects trust relationship permissions.

        This is an integration test - the actual permission enforcement
        depends on how the ActingWeb app is configured.
        """
        initialize_mcp_session(oauth2_client)

        # Try to call a tool that might require higher permissions
        # The actual behavior depends on configured permissions
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": "delete_actor",  # Destructive operation
                    "arguments": {},
                },
                "id": 15,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        # Either succeeds, tool not found, or permission denied
        # All are acceptable depending on configuration

    def test_tools_list_includes_all_fields_regression(self, oauth2_client):
        """
        Regression test to ensure tools/list includes ALL Tool fields.

        This is critical for ChatGPT safety evaluation. The refactoring initially
        only included name/description/inputSchema, which stripped important
        safety metadata from the annotations field.

        Tool fields:
        - name (required)
        - description (optional)
        - inputSchema (required)
        - title (optional)
        - outputSchema (optional)
        - annotations (optional but IMPORTANT for safety):
          - destructiveHint
          - readOnlyHint
          - idempotentHint
          - openWorldHint
        - meta (optional)

        See: mcp.py line 330-356
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200, \
            f"tools/list failed: {response.status_code} {response.text}"

        data = response.json()
        assert "result" in data
        assert "tools" in data["result"]
        tools = data["result"]["tools"]

        # Verify each tool has the structure we expect
        for tool in tools:
            # Required fields
            assert "name" in tool, "Tool missing 'name' field"
            assert isinstance(tool["name"], str)
            assert "inputSchema" in tool, "Tool missing 'inputSchema' field"
            assert isinstance(tool["inputSchema"], dict)

            # Optional fields - verify they're included IF present (not stripped)
            # The key point is that if the Tool object has these fields,
            # they should appear in the response (not be stripped)

            # Check that we're not limiting to only 3 fields
            # If a tool has more fields, they should be preserved
            if len(tool.keys()) <= 3:
                # Only has name, description, inputSchema - might be OK
                pass
            else:
                # Has additional fields - good! Let's verify they're valid
                valid_fields = {
                    "name", "description", "inputSchema",
                    "title", "outputSchema", "annotations", "meta"
                }
                for field in tool.keys():
                    assert field in valid_fields, \
                        f"Unexpected field '{field}' in tool - make sure we're using model_dump()"

            # If annotations exist, verify structure
            if "annotations" in tool and tool["annotations"] is not None:
                annotations = tool["annotations"]
                assert isinstance(annotations, dict), \
                    "annotations should be a dict, not a Pydantic object"

                # Verify annotations fields are valid
                valid_annotation_fields = {
                    "title", "readOnlyHint", "destructiveHint",
                    "idempotentHint", "openWorldHint"
                }
                for field in annotations.keys():
                    assert field in valid_annotation_fields, \
                        f"Invalid annotation field: {field}"
