"""
OAuth2 mock helpers for testing.

Provides mock responses for:
- Google OAuth2 provider
- GitHub OAuth2 provider
- MCP token issuance endpoint
"""

import responses


class OAuth2MockProvider:
    """Base class for OAuth2 provider mocks."""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        self.auth_codes: dict[str, dict] = {}
        self.access_tokens: dict[str, dict] = {}

    def mock_authorization_redirect(
        self, responses_mock, state: str, code: str = "test_auth_code"
    ):
        """
        Mock the authorization redirect.

        In real flow:
        1. App redirects user to provider auth URL
        2. Provider redirects back with code

        In test:
        We simulate step 2 by having the test directly call the callback with code.
        """
        self.auth_codes[code] = {
            "state": state,
            "email": "test@example.com",
            "used": False,
        }

    def mock_token_exchange(
        self,
        responses_mock,
        code: str = "test_auth_code",
        access_token: str = "test_access_token",
        refresh_token: str | None = "test_refresh_token",
        email: str = "test@example.com",
    ):
        """Mock the token exchange endpoint."""
        raise NotImplementedError("Subclasses must implement")

    def mock_userinfo_endpoint(
        self,
        responses_mock,
        access_token: str = "test_access_token",
        email: str = "test@example.com",
        email_verified: bool = True,
    ):
        """Mock the userinfo endpoint."""
        raise NotImplementedError("Subclasses must implement")


class GoogleOAuth2Mock(OAuth2MockProvider):
    """Mock Google OAuth2 provider."""

    def __init__(self):
        super().__init__("google")
        self.token_url = "https://oauth2.googleapis.com/token"
        self.userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"

    def mock_token_exchange(
        self,
        responses_mock,
        code: str = "test_auth_code",
        access_token: str = "test_access_token",
        refresh_token: str | None = "test_refresh_token",
        email: str = "test@example.com",
    ):
        """Mock Google token exchange."""
        responses_mock.add(
            responses.POST,
            self.token_url,
            json={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "openid email profile",
                "id_token": "test_id_token",  # Would be a real JWT in production
            },
            status=200,
        )

        self.access_tokens[access_token] = {
            "email": email,
            "code": code,
        }

    def mock_userinfo_endpoint(
        self,
        responses_mock,
        access_token: str = "test_access_token",
        email: str = "test@example.com",
        email_verified: bool = True,
    ):
        """Mock Google userinfo endpoint."""
        responses_mock.add(
            responses.GET,
            self.userinfo_url,
            json={
                "email": email,
                "email_verified": email_verified,
                "name": "Test User",
                "picture": "https://example.com/photo.jpg",
            },
            status=200,
        )


class GitHubOAuth2Mock(OAuth2MockProvider):
    """Mock GitHub OAuth2 provider."""

    def __init__(self):
        super().__init__("github")
        self.token_url = "https://github.com/login/oauth/access_token"
        self.user_url = "https://api.github.com/user"
        self.emails_url = "https://api.github.com/user/emails"

    def mock_token_exchange(
        self,
        responses_mock,
        code: str = "test_auth_code",
        access_token: str = "test_access_token",
        refresh_token: str | None = None,
        email: str = "test@example.com",
    ):
        """Mock GitHub token exchange."""
        responses_mock.add(
            responses.POST,
            self.token_url,
            json={
                "access_token": access_token,
                "token_type": "bearer",
                "scope": "user:email",
            },
            status=200,
        )

        self.access_tokens[access_token] = {
            "email": email,
            "code": code,
        }

    def mock_userinfo_endpoint(
        self,
        responses_mock,
        access_token: str = "test_access_token",
        email: str = "test@example.com",
        email_verified: bool = True,
    ):
        """Mock GitHub user endpoints."""
        # User info endpoint
        responses_mock.add(
            responses.GET,
            self.user_url,
            json={
                "login": "testuser",
                "name": "Test User",
                "email": email,
            },
            status=200,
        )

        # User emails endpoint (GitHub specific)
        responses_mock.add(
            responses.GET,
            self.emails_url,
            json=[{"email": email, "verified": email_verified, "primary": True}],
            status=200,
        )
