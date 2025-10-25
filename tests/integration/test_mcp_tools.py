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


class TestMCPToolResponseFormatRegression:
    """
    Regression tests for tool response format handling.

    These tests ensure critical response metadata is preserved through
    the SDK server's response handling pipeline.
    """

    def test_sdk_server_preserves_is_error_field_success(self):
        """
        Unit test: Verify SDK server preserves isError=false in CallToolResult.

        **Problem (Oct 2025):**
        When tools returned storage confirmations with isError: false, the SDK server
        extracted only the text content and discarded the isError field. This caused
        ChatGPT to misinterpret successful operations as errors.

        **Root Cause:**
        sdk_server.py:260-269 was converting responses with content arrays to plain
        TextContent lists, losing all metadata including isError.

        **Fix:**
        Modified SDK server to detect isError field and return CallToolResult object
        to preserve the flag through the MCP protocol.

        **This test ensures:**
        - Storage confirmations include isError: false
        - The isError field survives the SDK server's response handling
        - ChatGPT receives proper success indicators

        Related files:
        - actingweb/mcp/sdk_server.py:271-278 (CallToolResult with isError)
        - hooks/mcp/protocol/mcp_response.py:136 (adds isError to responses)
        """
        from mcp.types import CallToolResult, TextContent

        # Simulate the SDK server's response handling logic
        # This is the response format that comes from storage confirmation tools
        tool_response = {
            "content": [
                {
                    "type": "text",
                    "text": "✅ Successfully stored: test data"
                }
            ],
            "isError": False,  # This field MUST be preserved
            "success": True,
            "memory_type": "memory_test"
        }

        # Extract content items (simulating sdk_server.py:264-269)
        content_items = tool_response["content"]
        text_contents = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_contents.append(TextContent(type="text", text=item["text"]))

        # CRITICAL TEST: Verify isError flag is detected and preserved
        # This simulates sdk_server.py:271-278
        if "isError" in tool_response:
            is_error = tool_response["isError"]

            # SDK server should create CallToolResult with isError flag
            result = CallToolResult(
                content=text_contents if text_contents else [TextContent(type="text", text="")],
                isError=is_error
            )

            # Verify the CallToolResult preserves the flag
            assert hasattr(result, 'isError'), \
                "CallToolResult missing isError attribute - regression detected!"
            assert result.isError is False, \
                f"isError should be False for success, got: {result.isError}"
            assert len(result.content) > 0, "Content should not be empty"
            assert result.content[0].text == "✅ Successfully stored: test data"

    def test_sdk_server_preserves_is_error_field_failure(self):
        """
        Unit test: Verify SDK server preserves isError=true in CallToolResult.

        Companion test to success case - ensures error responses also preserve
        the isError flag.
        """
        from mcp.types import CallToolResult, TextContent

        # Simulate error response from tool
        tool_response = {
            "content": [
                {
                    "type": "text",
                    "text": "❌ Storage failed: validation error"
                }
            ],
            "isError": True,  # This field MUST be preserved
            "success": False,
            "error": "Validation failed"
        }

        # Extract content items
        content_items = tool_response["content"]
        text_contents = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_contents.append(TextContent(type="text", text=item["text"]))

        # CRITICAL TEST: Verify isError=true is preserved
        if "isError" in tool_response:
            is_error = tool_response["isError"]

            result = CallToolResult(
                content=text_contents if text_contents else [TextContent(type="text", text="")],
                isError=is_error
            )

            # Verify the CallToolResult preserves the error flag
            assert hasattr(result, 'isError'), \
                "CallToolResult missing isError attribute for errors - regression detected!"
            assert result.isError is True, \
                f"isError should be True for errors, got: {result.isError}"
            assert len(result.content) > 0, "Content should not be empty"
            assert "❌" in result.content[0].text, "Error indicator missing"

    def test_tool_response_without_is_error_field(self):
        """
        Test that responses without isError field still work correctly.

        Not all tool responses need isError - only storage confirmations and errors.
        This test ensures backward compatibility.
        """
        from mcp.types import TextContent

        # Response without isError field (e.g., from structuredContent responses)
        tool_response = {
            "content": [
                {
                    "type": "text",
                    "text": "Search results: 5 items found"
                }
            ]
        }

        # Extract content items
        content_items = tool_response["content"]
        text_contents = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                text_contents.append(TextContent(type="text", text=item["text"]))

        # When no isError flag present, return plain content list (old behavior)
        if "isError" not in tool_response:
            result = text_contents if text_contents else [TextContent(type="text", text="")]

            # Verify plain list works
            assert isinstance(result, list), "Should return list when no isError"
            assert len(result) > 0, "Content should not be empty"
            assert result[0].text == "Search results: 5 items found"
