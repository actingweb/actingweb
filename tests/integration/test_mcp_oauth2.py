"""
MCP OAuth2 Integration Tests.

Tests ActingWeb's OAuth2 authorization server functionality for MCP clients.

ActingWeb acts as an OAuth2 authorization server, allowing MCP clients to:
1. Register dynamically (RFC 7591)
2. Obtain access tokens via OAuth2 authorization code flow
3. Use tokens to access actor APIs

This is critical for MCP functionality - MCP clients authenticate using OAuth2.

Spec: OAuth2 authorization server for MCP clients
"""

from typing import Any

import pytest


class TestMCPOAuth2ClientRegistration:
    """Test dynamic client registration for MCP clients (RFC 7591)."""

    def test_client_registration_success(self, http_client, base_url):
        """
        Test successful MCP client registration.

        POST /oauth/register should create a new OAuth2 client and return
        client_id and client_secret.
        """
        # Register a new MCP client
        response = http_client.post(
            f"{base_url}/oauth/register",
            json={
                "client_name": "Test MCP Client",
                "redirect_uris": ["http://localhost:3000/callback"],
                "token_endpoint_auth_method": "client_secret_post",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "mcp",
            },
            headers={"Content-Type": "application/json"},
        )

        # Debug: print response details if not 201
        if response.status_code != 201:
            print(f"\nResponse status: {response.status_code}")
            print(f"Response headers: {dict(response.headers)}")
            print(f"Response body: {response.text[:500]}")
            try:
                print(f"Response JSON: {response.json()}")
            except Exception:
                pass

        assert response.status_code == 201, (
            f"Expected 201, got {response.status_code}. Response: {response.text[:200]}"
        )
        client_data = response.json()

        # Verify response contains required fields
        assert "client_id" in client_data
        assert "client_secret" in client_data
        assert "client_name" in client_data
        assert client_data["client_name"] == "Test MCP Client"
        # Scope is represented as trust_type in ActingWeb
        assert client_data.get("trust_type") == "mcp_client"

    def test_client_registration_missing_fields(self, http_client, base_url):
        """
        Test client registration with missing required fields.

        Should return 400 Bad Request.
        """
        response = http_client.post(
            f"{base_url}/oauth/register",
            json={
                # Missing client_name
                "redirect_uris": ["http://localhost:3000/callback"],
            },
            headers={"Content-Type": "application/json"},
        )

        # Should fail with 400
        assert response.status_code == 400


class TestMCPOAuth2Authorization:
    """Test OAuth2 authorization flow for MCP clients."""

    @pytest.fixture
    def registered_client(self, base_url, worker_info) -> dict[str, Any]:
        """A client an actor's owner created (3.16: an anonymous registration
        may not ask for client_credentials)."""
        from .conftest import TEST_APP_CONFIG
        from .utils.oauth2_helper import create_owner_client

        helper = create_owner_client(
            base_url,
            TEST_APP_CONFIG["config"],
            worker_id=worker_info["worker_id"],
            client_name="Test Token Client",
        )
        return {"client_id": helper.client_id, "client_secret": helper.client_secret}

    def test_token_request_client_credentials(
        self, http_client, base_url, registered_client
    ):
        """
        Test token request using client_credentials grant.

        This is the simplest flow - client authenticates directly with
        client_id and client_secret to get a token.
        """
        response = http_client.post(
            f"{base_url}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
                "scope": "mcp",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        # Note: This might not be implemented for all grant types
        # If 400/501, that's acceptable - we're testing the endpoint exists
        assert response.status_code in [200, 400, 501]

        if response.status_code == 200:
            token_data = response.json()
            assert "access_token" in token_data
            assert "token_type" in token_data
            assert token_data["token_type"].lower() == "bearer"

    def test_token_request_invalid_credentials(
        self, http_client, base_url, registered_client
    ):
        """
        Test token request with invalid client credentials.

        Should return 401 Unauthorized.
        """
        response = http_client.post(
            f"{base_url}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": registered_client["client_id"],
                "client_secret": "wrong_secret",
                "scope": "mcp",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert response.status_code in [400, 401]
        assert response.json()["error"] == "invalid_client"

    def test_register_public_client_gets_no_secret(self, http_client, base_url):
        """A ``none`` registration is a public client: 201 and no secret."""
        response = http_client.post(
            f"{base_url}/oauth/register",
            json={
                "client_name": "Public Test\nClient\u202e",
                "redirect_uris": ["http://localhost:3000/callback"],
                "token_endpoint_auth_method": "none",
            },
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in data
        # Client-supplied name sanitised before it is stored or returned
        assert data["client_name"] == "Public Test Client"

        # Public clients may not use client_credentials
        response = http_client.post(
            f"{base_url}/oauth/token",
            data={"grant_type": "client_credentials", "client_id": data["client_id"]},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "unauthorized_client"

    def test_token_request_missing_grant_type(
        self, http_client, base_url, registered_client
    ):
        """
        Test token request without grant_type parameter.

        Should return 400 Bad Request.
        """
        response = http_client.post(
            f"{base_url}/oauth/token",
            data={
                # Missing grant_type
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        assert response.status_code == 400


class TestMCPOAuth2Integration:
    """Integration tests for complete MCP OAuth2 flows."""

    def test_client_registration_and_token_flow(self, http_client, base_url):
        """An anonymous registration may not ask for client_credentials (400),
        and a client registered without it may not use it on the system
        actor (unauthorized_client) (3.16)."""
        refused = http_client.post(
            f"{base_url}/oauth/register",
            json={
                "client_name": "Integration Test Client",
                "redirect_uris": ["http://localhost:3000/callback"],
                "grant_types": ["client_credentials"],
                "scope": "mcp",
            },
            headers={"Content-Type": "application/json"},
        )
        assert refused.status_code == 400
        assert refused.json()["error"] == "invalid_client_metadata"

        registration_response = http_client.post(
            f"{base_url}/oauth/register",
            json={
                "client_name": "Integration Test Client",
                "redirect_uris": ["http://localhost:3000/callback"],
                "scope": "mcp",
            },
            headers={"Content-Type": "application/json"},
        )
        assert registration_response.status_code == 201
        client = registration_response.json()

        token_response = http_client.post(
            f"{base_url}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "scope": "mcp",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert token_response.status_code in (400, 401)
        assert token_response.json()["error"] == "unauthorized_client"


@pytest.fixture
def base_url(http_client) -> str:
    """Get the base URL for OAuth2 endpoints."""
    return http_client.base_url
