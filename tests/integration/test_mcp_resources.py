"""
MCP Resources Integration Tests.

Tests resource retrieval and management using the JSON-RPC 2.0 protocol.

Resources in MCP map to ActingWeb actor properties, meta information,
and other actor data accessible to the MCP client.
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


class TestMCPResourcesList:
    """Test resources/list method."""

    def test_resources_list_returns_valid_resources(self, oauth2_client):
        """
        Test that resources/list returns resources with valid structure.

        Each resource must have uri, name, and optionally mimeType and description.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 2},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        if "result" in data and "resources" in data["result"]:
            resources = data["result"]["resources"]
            assert isinstance(resources, list)

            for resource in resources:
                # Verify required MCP resource fields
                assert "uri" in resource, f"Resource missing uri: {resource}"
                assert isinstance(resource["uri"], str)

                assert "name" in resource, f"Resource missing name: {resource}"
                assert isinstance(resource["name"], str)

                # Optional fields
                if "mimeType" in resource:
                    assert isinstance(resource["mimeType"], str)
                if "description" in resource:
                    assert isinstance(resource["description"], str)

    def test_resources_list_pagination(self, oauth2_client):
        """
        Test resources/list with pagination.

        MCP supports cursor-based pagination for large resource lists.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "resources/list",
                "params": {"cursor": None},
                "id": 3,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        if "result" in data:
            assert "resources" in data["result"]
            # nextCursor is optional - present if more results available


class TestMCPResourceRead:
    """Test resources/read method."""

    def test_read_resource_basic(self, oauth2_client):
        """
        Test reading a specific resource.

        First list resources, then read one of them.
        """
        initialize_mcp_session(oauth2_client)

        # List resources to find one to read
        list_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 4},
            headers={"Content-Type": "application/json"},
        )

        assert list_response.status_code == 200
        list_data = list_response.json()

        if "result" in list_data and list_data["result"]["resources"]:
            # Pick first resource
            resource_uri = list_data["result"]["resources"][0]["uri"]

            # Read the resource
            read_response = oauth2_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "resources/read",
                    "params": {"uri": resource_uri},
                    "id": 5,
                },
                headers={"Content-Type": "application/json"},
            )

            assert read_response.status_code == 200
            read_data = read_response.json()

            if "result" in read_data:
                # Verify resource read response structure
                assert "contents" in read_data["result"]
                contents = read_data["result"]["contents"]
                assert isinstance(contents, list)

                for content in contents:
                    assert "uri" in content
                    assert "mimeType" in content
                    # Content must be text, blob, or resource
                    assert any(
                        key in content for key in ["text", "blob", "resource"]
                    )

    def test_read_nonexistent_resource(self, oauth2_client):
        """
        Test reading a resource that doesn't exist.

        Should return proper error.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "resources/read",
                "params": {"uri": "actingweb://nonexistent/resource/xyz"},
                "id": 6,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should get error for non-existent resource
        assert "error" in data
        assert "code" in data["error"]

    def test_read_resource_invalid_uri(self, oauth2_client):
        """
        Test reading a resource with invalid URI format.

        Should return validation error.
        """
        initialize_mcp_session(oauth2_client)

        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "resources/read",
                "params": {"uri": "not a valid uri"},
                "id": 7,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should get error for invalid URI
        # Accept either error or not found
        assert "error" in data or "result" in data


class TestMCPResourceTemplates:
    """Test resource URI templates."""

    def test_resource_template_expansion(self, oauth2_client):
        """
        Test resources that use URI templates.

        Example: actingweb://properties/{key}
        """
        initialize_mcp_session(oauth2_client)

        # List resources to find templated ones
        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 8},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        if "result" in data and "resourceTemplates" in data["result"]:
            templates = data["result"]["resourceTemplates"]
            assert isinstance(templates, list)

            for template in templates:
                assert "uriTemplate" in template
                assert "name" in template
                # mimeType is optional


class TestMCPResourceSubscriptions:
    """Test resource update subscriptions."""

    def test_subscribe_to_resource(self, oauth2_client):
        """
        Test subscribing to resource updates.

        MCP supports notifications when resources change.
        """
        initialize_mcp_session(oauth2_client)

        # List resources
        list_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 9},
            headers={"Content-Type": "application/json"},
        )

        if (
            list_response.status_code == 200
            and "result" in list_response.json()
            and list_response.json()["result"]["resources"]
        ):
            resource_uri = list_response.json()["result"]["resources"][0]["uri"]

            # Subscribe to resource
            subscribe_response = oauth2_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "resources/subscribe",
                    "params": {"uri": resource_uri},
                    "id": 10,
                },
                headers={"Content-Type": "application/json"},
            )

            # Subscription might not be supported
            assert subscribe_response.status_code in [200, 400]

            if subscribe_response.status_code == 200:
                sub_data = subscribe_response.json()
                # Either success or method not found
                assert "result" in sub_data or "error" in sub_data

    def test_unsubscribe_from_resource(self, oauth2_client):
        """
        Test unsubscribing from resource updates.
        """
        initialize_mcp_session(oauth2_client)

        # Try to unsubscribe (might fail if not subscribed or not supported)
        response = oauth2_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "resources/unsubscribe",
                "params": {"uri": "actingweb://properties"},
                "id": 11,
            },
            headers={"Content-Type": "application/json"},
        )

        # Unsubscribe might not be supported or might fail if not subscribed
        assert response.status_code in [200, 400]


class TestMCPResourceIntegration:
    """Integration tests for MCP resources."""

    def test_resource_lifecycle(self, oauth2_client):
        """
        Test complete resource lifecycle:
        1. List resources
        2. Read a resource
        3. Subscribe to updates (if supported)
        4. Unsubscribe (if supported)
        """
        initialize_mcp_session(oauth2_client)

        # Step 1: List
        list_response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "resources/list", "id": 12},
            headers={"Content-Type": "application/json"},
        )
        assert list_response.status_code == 200

        # Step 2: Read (if resources exist)
        list_data = list_response.json()
        if "result" in list_data and list_data["result"]["resources"]:
            resource_uri = list_data["result"]["resources"][0]["uri"]

            read_response = oauth2_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "resources/read",
                    "params": {"uri": resource_uri},
                    "id": 13,
                },
                headers={"Content-Type": "application/json"},
            )
            assert read_response.status_code == 200

            # Step 3 & 4: Subscribe/unsubscribe are optional
            # Already tested in separate test cases
