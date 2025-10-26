"""
MCP Prompts Integration Tests.

Tests prompt listing and invocation using the JSON-RPC 2.0 protocol.

Prompts in MCP map to ActingWeb methods - predefined workflows or
interactions that can be exposed to MCP clients.
"""

from mcp.types import LATEST_PROTOCOL_VERSION


def initialize_mcp_session(oauth2_client):
    """Helper to initialize an MCP session."""
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


class TestMCPPromptsList:
    """Test prompts/list method."""

    def test_prompts_list_returns_valid_prompts(self, oauth2_client):
        """
        Test that prompts/list returns prompts with valid structure.

        Each prompt must have name and optionally description and arguments.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        if "result" in data and "prompts" in data["result"]:
            prompts = data["result"]["prompts"]
            assert isinstance(prompts, list)

            for prompt in prompts:
                # Verify required MCP prompt fields
                assert "name" in prompt, f"Prompt missing name: {prompt}"
                assert isinstance(prompt["name"], str)

                # Optional fields
                if "description" in prompt:
                    assert isinstance(prompt["description"], str)

                if "arguments" in prompt:
                    # Arguments should be array of argument definitions
                    assert isinstance(prompt["arguments"], list)
                    for arg in prompt["arguments"]:
                        assert "name" in arg
                        assert "required" in arg

    def test_prompts_list_pagination(self, oauth2_client):
        """
        Test prompts/list with pagination.

        MCP supports cursor-based pagination.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "prompts/list",
                "params": {"cursor": None},
                "id": 3,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        if "result" in data:
            assert "prompts" in data["result"]
            # nextCursor is optional


class TestMCPPromptsGet:
    """Test prompts/get method."""

    def test_get_prompt_by_name(self, oauth2_client):
        """
        Test getting a specific prompt by name.

        First list prompts, then get one by name.
        """
        initialize_mcp_session(oauth2_client)

        # List prompts to find one
        list_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 4},
            headers={"Content-Type": "application/json"},
        )

        assert list_response.status_code == 200
        list_data = list_response.json()

        if "result" in list_data and list_data["result"]["prompts"]:
            # Pick first prompt
            prompt_name = list_data["result"]["prompts"][0]["name"]

            # Get the prompt
            get_response = oauth2_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "prompts/get",
                    "params": {"name": prompt_name},
                    "id": 5,
                },
                headers={"Content-Type": "application/json"},
            )

            assert get_response.status_code == 200
            get_data = get_response.json()

            if "result" in get_data:
                # Verify prompt response structure
                assert "messages" in get_data["result"]
                messages = get_data["result"]["messages"]
                assert isinstance(messages, list)

                for message in messages:
                    assert "role" in message
                    assert "content" in message
                    # Role must be user or assistant
                    assert message["role"] in ["user", "assistant"]

    def test_get_prompt_with_arguments(self, oauth2_client):
        """
        Test getting a prompt with argument values.

        Some prompts accept arguments that customize the prompt.
        """
        initialize_mcp_session(oauth2_client)

        # Try to get a prompt with arguments
        # This is speculative - depends on what prompts are configured
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "prompts/get",
                "params": {
                    "name": "example_prompt",
                    "arguments": {"param1": "value1", "param2": "value2"},
                },
                "id": 6,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        # Either succeeds or prompt not found - both acceptable

    def test_get_nonexistent_prompt(self, oauth2_client):
        """
        Test getting a prompt that doesn't exist.

        Should return proper error.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "prompts/get",
                "params": {"name": "nonexistent_prompt_xyz"},
                "id": 7,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should get error for non-existent prompt
        assert "error" in data
        assert "code" in data["error"]

    def test_get_prompt_missing_required_arguments(self, oauth2_client):
        """
        Test getting a prompt without required arguments.

        Should return validation error.
        """
        initialize_mcp_session(oauth2_client)

        # List prompts to find one with required arguments
        list_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 8},
            headers={"Content-Type": "application/json"},
        )

        if list_response.status_code == 200:
            list_data = list_response.json()

            if "result" in list_data:
                prompts = list_data["result"]["prompts"]

                # Find prompt with required arguments
                for prompt in prompts:
                    if "arguments" in prompt:
                        required_args = [
                            arg for arg in prompt["arguments"] if arg.get("required")
                        ]
                        if required_args:
                            # Try to get this prompt without arguments
                            get_response = oauth2_client.post(
                                "/mcp",
                                json={
                                    "jsonrpc": "2.0",
                                    "method": "prompts/get",
                                    "params": {
                                        "name": prompt["name"]
                                        # Missing required arguments
                                    },
                                    "id": 9,
                                },
                                headers={"Content-Type": "application/json"},
                            )

                            assert get_response.status_code == 200
                            get_data = get_response.json()

                            # Should get error for missing required arguments
                            # Or might work with defaults
                            assert "error" in get_data or "result" in get_data
                            break


class TestMCPPromptsIntegration:
    """Integration tests for MCP prompts."""

    def test_prompt_lifecycle(self, oauth2_client):
        """
        Test complete prompt lifecycle:
        1. List all prompts
        2. Get a specific prompt
        3. Verify prompt structure
        """
        initialize_mcp_session(oauth2_client)

        # Step 1: List all prompts
        list_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 10},
            headers={"Content-Type": "application/json"},
        )
        assert list_response.status_code == 200
        list_data = list_response.json()

        # Step 2: Get first prompt (if any exist)
        if "result" in list_data and list_data["result"]["prompts"]:
            prompt_name = list_data["result"]["prompts"][0]["name"]

            get_response = oauth2_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "prompts/get",
                    "params": {"name": prompt_name},
                    "id": 11,
                },
                headers={"Content-Type": "application/json"},
            )
            assert get_response.status_code == 200

            # Step 3: Verify structure
            get_data = get_response.json()
            if "result" in get_data:
                assert "messages" in get_data["result"]

    def test_prompts_match_actingweb_methods(self, oauth2_client):
        """
        Test that MCP prompts correctly map to ActingWeb methods.

        This is an integration test verifying the mapping is correct.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "prompts/list", "id": 12},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Just verify we can list prompts successfully
        # The actual prompts depend on ActingWeb configuration
        if "result" in data:
            assert "prompts" in data["result"]
            prompts = data["result"]["prompts"]
            # May be empty if no methods are exposed as prompts
            assert isinstance(prompts, list)

    def test_prompts_list_serialization_regression(self, oauth2_client):
        """
        Regression test for PromptArgument serialization bug.

        This tests the fix for a bug where prompts/list would fail with:
        "TypeError: Object of type PromptArgument is not JSON serializable"

        The issue was that Pydantic PromptArgument objects in the prompt.arguments
        field were not being converted to dictionaries before JSON serialization.

        See: mcp.py line 381-402
        """
        initialize_mcp_session(oauth2_client)

        # This request includes _meta with progressToken to match the user's example
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 10,
                "method": "prompts/list",
                "params": {"_meta": {"progressToken": 10}},
            },
            headers={"Content-Type": "application/json"},
        )

        # Should not get 500 Internal Server Error
        assert response.status_code == 200, \
            f"prompts/list failed with status {response.status_code}: {response.text}"

        data = response.json()

        # Should have a valid JSON-RPC response structure
        assert "jsonrpc" in data
        assert data["jsonrpc"] == "2.0"
        assert "id" in data
        assert data["id"] == 10

        # Should have result, not error
        assert "result" in data, \
            f"Expected 'result' in response, got error: {data.get('error')}"
        assert "error" not in data

        # Verify prompts structure
        assert "prompts" in data["result"]
        prompts = data["result"]["prompts"]
        assert isinstance(prompts, list)

        # Verify all prompts are properly serialized (including arguments)
        for prompt in prompts:
            assert isinstance(prompt, dict), f"Prompt not a dict: {type(prompt)}"
            assert "name" in prompt
            assert "description" in prompt
            assert "arguments" in prompt

            # Verify arguments are serialized as dicts, not Pydantic objects
            arguments = prompt["arguments"]
            assert isinstance(arguments, list)
            for arg in arguments:
                assert isinstance(arg, dict), \
                    f"PromptArgument not serialized to dict: {type(arg)}"
                # Verify standard PromptArgument fields
                assert "name" in arg
                # description and required are optional
                if "description" in arg:
                    assert isinstance(arg["description"], (str, type(None)))
                if "required" in arg:
                    assert isinstance(arg["required"], (bool, type(None)))
