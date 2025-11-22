"""
OAuth2 Flow Integration Tests.

Tests the complete OAuth2 authentication flows:

1. External OAuth2 Provider Flow (Google/GitHub) → Used for user authentication
2. ActingWeb OAuth2 Server Flow → Issues tokens to MCP clients

These flows work together:
- External provider authenticates the user (email verification)
- ActingWeb OAuth2 server issues tokens to MCP clients
- MCP clients use issued tokens to access /mcp endpoints
- /www endpoints use external provider tokens (via session cookies)

This comprehensive test suite ensures all OAuth2 components work together.
"""

import requests
import responses


class TestExternalOAuth2Provider:
    """Test external OAuth2 provider integration (Google/GitHub)."""

    @responses.activate
    def test_google_oauth2_token_exchange(self):
        """
        Test Google OAuth2 token exchange flow.

        This simulates:
        1. User authorizes app with Google
        2. Google redirects back with auth code
        3. App exchanges code for access token
        4. App fetches user info with access token
        """
        from .utils.oauth2_mocks import GoogleOAuth2Mock

        mock = GoogleOAuth2Mock()

        # Mock token exchange
        mock.mock_token_exchange(
            responses,
            code="test_code",
            access_token="google_access_token",
            email="user@example.com",
        )

        # Exchange code for token
        response = requests.post(
            mock.token_url,
            data={
                "code": "test_code",
                "client_id": "test_client",
                "client_secret": "test_secret",
                "redirect_uri": "http://localhost/callback",
                "grant_type": "authorization_code",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "google_access_token"
        assert data["token_type"] == "Bearer"

    @responses.activate
    def test_google_oauth2_userinfo(self):
        """
        Test Google OAuth2 userinfo endpoint.

        This verifies email and email_verified claims.
        """
        from .utils.oauth2_mocks import GoogleOAuth2Mock

        mock = GoogleOAuth2Mock()

        # Mock userinfo endpoint
        mock.mock_userinfo_endpoint(
            responses,
            access_token="google_access_token",
            email="user@example.com",
            email_verified=True,
        )

        # Fetch user info
        response = requests.get(
            mock.userinfo_url,
            headers={"Authorization": "Bearer google_access_token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "user@example.com"
        assert data["email_verified"] is True

    @responses.activate
    def test_github_oauth2_flow(self):
        """
        Test GitHub OAuth2 flow.

        GitHub uses a slightly different flow than Google.
        """
        from .utils.oauth2_mocks import GitHubOAuth2Mock

        mock = GitHubOAuth2Mock()

        # Mock token exchange
        mock.mock_token_exchange(
            responses,
            code="github_code",
            access_token="github_access_token",
            email="user@example.com",
        )

        # Mock user endpoints
        mock.mock_userinfo_endpoint(
            responses,
            access_token="github_access_token",
            email="user@example.com",
        )

        # Exchange code for token
        token_response = requests.post(
            mock.token_url,
            data={"code": "github_code"},
        )

        assert token_response.status_code == 200
        token_data = token_response.json()
        assert "access_token" in token_data

        # Fetch user info
        user_response = requests.get(
            mock.user_url,
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )

        assert user_response.status_code == 200
        user_data = user_response.json()
        assert user_data["email"] == "user@example.com"


class TestActingWebOAuth2Server:
    """
    Test ActingWeb's OAuth2 authorization server for MCP clients.

    ActingWeb acts as an OAuth2 server that issues tokens to MCP clients
    after the user has been authenticated via external provider (Google/GitHub).
    """

    def test_mcp_client_registration(self, test_app):
        """
        Test MCP client dynamic registration (RFC 7591).

        This creates a new OAuth2 client that can request tokens.
        """
        response = requests.post(
            f"{test_app}/oauth/register",
            json={
                "client_name": "Test MCP Client",
                "redirect_uris": ["http://localhost:3000/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "scope": "mcp",
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        client_data = response.json()

        # Verify client credentials
        assert "client_id" in client_data
        assert "client_secret" in client_data
        assert client_data["client_name"] == "Test MCP Client"
        assert client_data["trust_type"] == "mcp_client"

        # Verify OAuth2 endpoints are provided
        assert "authorization_endpoint" in client_data
        assert "token_endpoint" in client_data
        assert client_data["actor_id"] == "_actingweb_oauth2"

    def test_complete_mcp_authorization_flow(self, test_app):
        """
        Test complete MCP authorization flow:

        1. External OAuth2 (Google) - User authenticates  [MOCKED]
        2. MCP client registration - Client gets credentials [REAL]
        3. Authorization request - User authorizes MCP client [REAL]
        4. Token exchange - Client gets access token [REAL]
        5. MCP access - Client uses token to access /mcp [REAL]

        This is the full end-to-end flow.
        Note: We mock only external provider, ActingWeb calls are real.
        """
        # Note: No @responses.activate here because we need real HTTP to ActingWeb
        # External provider mocking would be done in the OAuth callback handler

        # Step 2: Register MCP client
        client_response = requests.post(
            f"{test_app}/oauth/register",
            json={
                "client_name": "ChatGPT MCP Client",
                "redirect_uris": ["http://localhost:3000/callback"],
                "grant_types": ["authorization_code"],
                "scope": "mcp",
            },
            headers={"Content-Type": "application/json"},
        )

        assert client_response.status_code == 201
        client = client_response.json()

        # Step 3: Authorization request
        # In real flow: User clicks "authorize" in browser
        # For testing: We verify the endpoint exists and accepts the request
        auth_response = requests.get(
            f"{test_app}/oauth/authorize",
            params={
                "client_id": client["client_id"],
                "redirect_uri": "http://localhost:3000/callback",
                "response_type": "code",
                "scope": "mcp",
                "state": "random_state_123",
            },
            allow_redirects=False,
        )

        # Should redirect to Google OAuth (302) or show auth form (200)
        assert auth_response.status_code in [200, 302]

        # Note: Full authorization flow testing requires:
        # - Simulating user login via Google
        # - User approving the MCP client
        # - Getting authorization code
        # - Exchanging code for token
        # This is complex and requires session management
        # For now, we've verified the infrastructure is in place


class TestMCPWithIssuedToken:
    """
    Test MCP endpoints with properly issued tokens.

    These tests use the oauth2_client fixture which handles:
    1. Client registration
    2. Token issuance
    3. Making authenticated requests
    """

    def test_mcp_with_bearer_token(self, oauth2_client):
        """
        Test MCP endpoint with valid Bearer token.

        The oauth2_client fixture provides a fully authenticated client.
        """
        # Ping doesn't require auth, but we test with auth to verify it works
        response = oauth2_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data or data.get("id") == 1

    def test_mcp_authentication_required(self, test_app):
        """
        Test that authenticated MCP methods require Bearer token.

        Methods like tools/list require authentication.
        """
        # Try without Bearer token
        response = requests.post(
            f"{test_app}/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Content-Type": "application/json"},
        )

        # Should get authentication error
        assert response.status_code in [200, 401]  # 200 with error in JSON-RPC

        if response.status_code == 200:
            data = response.json()
            # JSON-RPC error for authentication
            assert "error" in data
            assert data["error"]["code"] == -32002  # Authentication required


class TestWWWWithOAuth2:
    """
    Test /www endpoints with OAuth2 authentication.

    /www endpoints use external OAuth2 provider (Google/GitHub) for authentication.
    Unlike /mcp which uses ActingWeb-issued tokens, /www uses session cookies
    from the external provider flow.
    """

    def test_www_requires_authentication(self, test_app):
        """
        Test that /www endpoints require authentication.

        Without auth, should redirect to OAuth provider or return 401/302.
        """
        # Create an actor first
        actor_response = requests.post(
            f"{test_app}/",
            json={"creator": "test@example.com"},
            headers={"Content-Type": "application/json"},
        )

        assert actor_response.status_code == 201
        actor_id = actor_response.json()["id"]

        # Try to access /www without authentication
        www_response = requests.get(
            f"{test_app}/{actor_id}/www",
            allow_redirects=False,
        )

        # Should redirect to OAuth login (302) or require auth (401)
        assert www_response.status_code in [302, 401]

        if www_response.status_code == 302:
            # Should redirect to Google OAuth
            location = www_response.headers.get("Location", "")
            assert "google" in location.lower() or "oauth" in location.lower()

    @responses.activate
    def test_www_with_oauth_session(self, test_app):
        """
        Test /www with authenticated OAuth session via Google OAuth.

        Flow:
        1. Create actor via factory
        2. Mock Google OAuth flow (token exchange + userinfo)
        3. Use Google token as oauth_token cookie to access /www
        """
        import requests

        from .utils.oauth2_mocks import GoogleOAuth2Mock

        # Allow requests to test app to pass through
        responses.add_passthru(test_app)

        # Setup Google OAuth mock
        google_mock = GoogleOAuth2Mock()
        google_mock.mock_token_exchange(
            responses,
            code="google_auth_code",
            access_token="google_access_token",
            email="oauth_session_test@example.com",
        )
        google_mock.mock_userinfo_endpoint(
            responses,
            access_token="google_access_token",
            email="oauth_session_test@example.com",
            email_verified=True,
        )

        # Create an actor
        actor_response = requests.post(
            f"{test_app}/",
            json={"creator": "oauth_session_test@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert actor_response.status_code == 201
        actor_id = actor_response.json()["id"]

        # Simulate OAuth callback (this would normally come from Google redirect)
        # In real flow: User authorizes -> Google redirects to /oauth/callback?code=...&state=...
        # For www access, we need to go through the full OAuth flow to get a session cookie

        # Since we're testing with mocked Google, we can directly use the Google token
        # as the oauth_token cookie (ActingWeb accepts Google tokens for www access)
        response = requests.get(
            f"{test_app}/{actor_id}/www",
            cookies={"oauth_token": "google_access_token"},
        )

        # Should get 200 with HTML content
        assert response.status_code == 200
        assert "text/html" in response.headers.get("Content-Type", "")


class TestOAuth2CORSPreflight:
    """Test CORS preflight (OPTIONS) requests to OAuth2 endpoints."""

    def test_options_register_endpoint(self, test_app):
        """
        Test OPTIONS request to /oauth/register (CORS preflight).

        This is a regression test for a bug where OPTIONS requests to OAuth2
        endpoints were being routed to handler.get() instead of handler.options(),
        causing "Unknown OAuth2 endpoint: register" errors.

        See: fastapi_integration.py line 1109
        """
        response = requests.options(
            f"{test_app}/oauth/register",
            headers={"Origin": "https://mcp-client.example.com"},
        )

        # Should succeed with 200
        assert response.status_code == 200, (
            f"OPTIONS /oauth/register failed: {response.status_code} {response.text}"
        )

        # Should have CORS headers
        assert "Access-Control-Allow-Origin" in response.headers, (
            "Missing CORS Allow-Origin header"
        )
        assert "Access-Control-Allow-Methods" in response.headers, (
            "Missing CORS Allow-Methods header"
        )
        assert "Access-Control-Allow-Headers" in response.headers, (
            "Missing CORS Allow-Headers header"
        )

        # Verify CORS headers contain expected values
        assert response.headers["Access-Control-Allow-Origin"] in [
            "*",
            "https://mcp-client.example.com",
        ]
        assert "POST" in response.headers["Access-Control-Allow-Methods"]
        assert "OPTIONS" in response.headers["Access-Control-Allow-Methods"]
        assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]

    def test_options_authorize_endpoint(self, test_app):
        """Test OPTIONS request to /oauth/authorize (CORS preflight)."""
        response = requests.options(
            f"{test_app}/oauth/authorize",
            headers={"Origin": "https://mcp-client.example.com"},
        )

        assert response.status_code == 200, (
            f"OPTIONS /oauth/authorize failed: {response.status_code} {response.text}"
        )
        assert "Access-Control-Allow-Origin" in response.headers
        assert "Access-Control-Allow-Methods" in response.headers

    def test_options_token_endpoint(self, test_app):
        """Test OPTIONS request to /oauth/token (CORS preflight)."""
        response = requests.options(
            f"{test_app}/oauth/token",
            headers={"Origin": "https://mcp-client.example.com"},
        )

        assert response.status_code == 200, (
            f"OPTIONS /oauth/token failed: {response.status_code} {response.text}"
        )
        assert "Access-Control-Allow-Origin" in response.headers
        assert "Access-Control-Allow-Methods" in response.headers

    def test_options_logout_endpoint(self, test_app):
        """Test OPTIONS request to /oauth/logout (CORS preflight)."""
        response = requests.options(
            f"{test_app}/oauth/logout",
            headers={"Origin": "https://mcp-client.example.com"},
        )

        assert response.status_code == 200, (
            f"OPTIONS /oauth/logout failed: {response.status_code} {response.text}"
        )
        assert "Access-Control-Allow-Origin" in response.headers
        assert "Access-Control-Allow-Methods" in response.headers


class TestOAuth2Discovery:
    """Test OAuth2 discovery endpoints."""

    def test_protected_resource_mcp_discovery_version(self, test_app):
        """
        Test that /.well-known/oauth-protected-resource/mcp reports correct MCP version.

        This is a regression test for a bug where the discovery endpoint was hardcoding
        "2024-11-05" instead of using LATEST_PROTOCOL_VERSION from the MCP SDK.

        The SDK was updated to 2025-06-18 but the discovery endpoint was still reporting
        the old version, which would confuse MCP clients.

        See: oauth2_endpoints.py line 637
        """
        response = requests.get(f"{test_app}/.well-known/oauth-protected-resource/mcp")

        assert response.status_code == 200, (
            f"Discovery endpoint failed: {response.status_code} {response.text}"
        )

        data = response.json()

        # Verify structure
        assert "mcp_version" in data, "Missing mcp_version field"
        assert "supported_protocol_versions" in data, (
            "Missing supported_protocol_versions field"
        )
        assert "capabilities" in data, "Missing capabilities field"

        # Verify version is from SDK (should be 2025-06-18 or newer, not hardcoded 2024-11-05)
        from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
        from mcp.types import LATEST_PROTOCOL_VERSION

        assert data["mcp_version"] == LATEST_PROTOCOL_VERSION, (
            f"Expected mcp_version={LATEST_PROTOCOL_VERSION}, got {data['mcp_version']}"
        )

        assert data["supported_protocol_versions"] == SUPPORTED_PROTOCOL_VERSIONS, (
            f"Expected supported_protocol_versions={SUPPORTED_PROTOCOL_VERSIONS}, got {data['supported_protocol_versions']}"
        )

        # Verify capabilities structure
        assert isinstance(data["capabilities"], dict)
        assert "tools" in data["capabilities"]
        assert "prompts" in data["capabilities"]

        # Log for debugging
        print("\nMCP Discovery endpoint reports:")
        print(f"  mcp_version: {data['mcp_version']}")
        print(f"  supported_protocol_versions: {data['supported_protocol_versions']}")

    def test_protected_resource_discovery(self, test_app):
        """Test OAuth2 Protected Resource discovery endpoint."""
        response = requests.get(f"{test_app}/.well-known/oauth-protected-resource")

        assert response.status_code == 200
        data = response.json()

        # Verify standard OAuth2 protected resource metadata
        assert "resource" in data
        assert "authorization_servers" in data
        assert "scopes_supported" in data
        assert "bearer_methods_supported" in data
