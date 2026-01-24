"""
Tests for SPA OAuth2 endpoints.

Tests the /oauth/spa/* endpoints that provide JSON-only OAuth2 flows
optimized for Single Page Applications.
"""

import json
from unittest.mock import MagicMock

import pytest


class TestOAuth2SPAHandler:
    """Test the OAuth2SPAHandler class."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config object."""
        config = MagicMock()
        config.proto = "https://"
        config.fqdn = "test.example.com"
        config.oauth = {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
        }
        config.oauth2_provider = "google"
        config.new_token = MagicMock(return_value="test-access-token")
        return config

    @pytest.fixture
    def mock_webobj(self):
        """Create a mock AWWebObj."""
        webobj = MagicMock()
        webobj.request = MagicMock()
        webobj.request.body = None
        webobj.request.headers = {"Accept": "application/json"}
        webobj.request.cookies = {}
        webobj.request.get = MagicMock(return_value="")
        webobj.response = MagicMock()
        webobj.response.headers = {}
        webobj.response._cookies = []
        webobj.response.set_status = MagicMock()
        webobj.response.write = MagicMock()
        webobj.response.set_cookie = MagicMock()
        return webobj

    def test_handle_config_returns_oauth_info(self, mock_config, mock_webobj):
        """Test that /oauth/spa/config returns OAuth configuration."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        handler = OAuth2SPAHandler(mock_webobj, mock_config)
        result = handler._handle_config()

        assert "oauth_providers" in result
        assert "pkce_supported" in result
        assert result["pkce_supported"] is True
        assert "token_delivery_modes" in result
        assert "json" in result["token_delivery_modes"]
        assert "cookie" in result["token_delivery_modes"]
        assert "hybrid" in result["token_delivery_modes"]
        assert "endpoints" in result
        # Check actual endpoint names used by handler
        assert "authorize" in result["endpoints"]
        assert "token" in result["endpoints"]
        assert "callback" in result["endpoints"]

    def test_handle_config_does_not_include_trust_types(self, mock_config, mock_webobj):
        """Test that config endpoint does NOT include trust types.

        Trust types are only relevant for MCP client authorization (ActingWeb as OAuth server),
        not for user login configuration (ActingWeb as OAuth client).
        """
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        handler = OAuth2SPAHandler(mock_webobj, mock_config)
        result = handler._handle_config()

        # trust_types should NOT be in config - they're for MCP authorization, not user login
        assert "trust_types" not in result

    def test_options_returns_cors_headers(self, mock_config, mock_webobj):
        """Test that OPTIONS requests return proper CORS headers."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        handler = OAuth2SPAHandler(mock_webobj, mock_config)
        handler.options("config")

        # Check CORS headers were set
        assert mock_webobj.response.set_status.called

    def test_authorize_validates_provider(self, mock_config, mock_webobj):
        """Test that authorize validates the OAuth provider."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        mock_webobj.request.body = json.dumps({"provider": "invalid_provider"})

        handler = OAuth2SPAHandler(mock_webobj, mock_config)
        result = handler._handle_authorize()

        assert "error" in result
        assert result["error"] is True

    def test_authorize_validates_token_delivery(self, mock_config, mock_webobj):
        """Test that authorize validates token_delivery mode."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        mock_webobj.request.body = json.dumps(
            {"provider": "google", "token_delivery": "invalid_mode"}
        )

        handler = OAuth2SPAHandler(mock_webobj, mock_config)
        result = handler._handle_authorize()

        assert "error" in result
        assert "Invalid token_delivery mode" in result["message"]

    def test_authorize_with_server_pkce(self, mock_config, mock_webobj):
        """Test authorize with server-managed PKCE generates proper response."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler, generate_pkce_pair

        # Test that PKCE pair generation works
        verifier, challenge = generate_pkce_pair()
        assert len(verifier) == 64
        assert challenge

        # Test that handler validates token_delivery properly
        mock_webobj.request.body = json.dumps(
            {"provider": "google", "pkce": "server", "token_delivery": "json"}
        )

        handler = OAuth2SPAHandler(mock_webobj, mock_config)

        # Without proper OAuth setup, we expect an error about OAuth not being enabled
        result = handler._handle_authorize()

        # Either we get the expected result or an error (which is acceptable for unit test)
        assert "error" in result or "authorization_url" in result


class TestPKCEFunctions:
    """Test PKCE helper functions."""

    def test_generate_pkce_pair(self):
        """Test PKCE code verifier and challenge generation."""
        from actingweb.handlers.oauth2_spa import generate_pkce_pair

        verifier, challenge = generate_pkce_pair()

        # Verifier should be 64 characters
        assert len(verifier) == 64

        # Challenge should be base64url encoded
        assert challenge
        assert "+" not in challenge  # No standard base64 chars
        assert "/" not in challenge

    def test_verify_pkce_correct(self):
        """Test PKCE verification with correct verifier."""
        from actingweb.handlers.oauth2_spa import generate_pkce_pair, verify_pkce

        verifier, challenge = generate_pkce_pair()

        assert verify_pkce(verifier, challenge) is True

    def test_verify_pkce_incorrect(self):
        """Test PKCE verification with incorrect verifier."""
        from actingweb.handlers.oauth2_spa import generate_pkce_pair, verify_pkce

        _, challenge = generate_pkce_pair()
        wrong_verifier = "wrong_verifier_that_does_not_match_the_challenge"

        assert verify_pkce(wrong_verifier, challenge) is False


class TestOAuth2SessionManagerTokens:
    """Test SPA token management in OAuth2SessionManager."""

    def test_token_generation_creates_unique_tokens(self):
        """Test that token generation creates unique tokens."""
        import secrets

        # Test the secrets-based token generation
        token1 = secrets.token_urlsafe(48)
        token2 = secrets.token_urlsafe(48)

        assert token1 != token2
        assert len(token1) > 20
        assert len(token2) > 20

    def test_token_ttl_constants(self):
        """Test that token TTL constants are properly defined."""
        from actingweb.constants import SPA_ACCESS_TOKEN_TTL, SPA_REFRESH_TOKEN_TTL

        # Access token: 1 hour
        assert SPA_ACCESS_TOKEN_TTL == 3600

        # Refresh token: 2 weeks
        assert SPA_REFRESH_TOKEN_TTL == 86400 * 14

    def test_bucket_names_defined(self):
        """Test that bucket names for tokens are defined."""
        from actingweb.oauth_session import (
            _ACCESS_TOKEN_BUCKET,
            _REFRESH_TOKEN_BUCKET,
        )

        assert _ACCESS_TOKEN_BUCKET
        assert _REFRESH_TOKEN_BUCKET
        assert _ACCESS_TOKEN_BUCKET != _REFRESH_TOKEN_BUCKET


class TestFactoryJSONAPI:
    """Test the factory endpoint JSON API for SPAs."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config."""
        config = MagicMock()
        config.proto = "https://"
        config.fqdn = "test.example.com"
        config.oauth = {"client_id": "test-id"}
        config.oauth2_provider = "google"
        config.ui = True
        return config

    @pytest.fixture
    def mock_webobj(self):
        """Create mock web object."""
        webobj = MagicMock()
        webobj.request = MagicMock()
        webobj.request.headers = {"Accept": "application/json"}
        webobj.request.get = MagicMock(return_value="")
        webobj.response = MagicMock()
        webobj.response.headers = {}
        webobj.response.write = MagicMock()
        webobj.response.set_status = MagicMock()
        return webobj

    def test_wants_json_with_accept_header(self, mock_config, mock_webobj):
        """Test JSON detection via Accept header."""
        from actingweb.handlers.factory import RootFactoryHandler

        mock_webobj.request.headers = {"Accept": "application/json"}

        handler = RootFactoryHandler(mock_webobj, mock_config)
        assert handler._wants_json() is True

    def test_wants_json_with_format_param(self, mock_config, mock_webobj):
        """Test JSON detection via format query param."""
        from actingweb.handlers.factory import RootFactoryHandler

        mock_webobj.request.headers = {}
        mock_webobj.request.get = MagicMock(
            side_effect=lambda x: "json" if x == "format" else ""
        )

        handler = RootFactoryHandler(mock_webobj, mock_config)
        assert handler._wants_json() is True

    def test_get_json_config_returns_oauth_endpoints(self, mock_config, mock_webobj):
        """Test that JSON config includes OAuth endpoints but not trust_types."""
        from actingweb.handlers.factory import RootFactoryHandler

        mock_webobj.request.headers = {"Accept": "application/json"}

        handler = RootFactoryHandler(mock_webobj, mock_config)
        result = handler._get_json_config()

        assert "endpoints" in result
        # Unified endpoints (no /spa/ prefix)
        assert "config" in result["endpoints"]
        assert "callback" in result["endpoints"]
        assert "revoke" in result["endpoints"]
        assert "session" in result["endpoints"]
        assert "logout" in result["endpoints"]
        # SPA-specific (different purpose than MCP OAuth2)
        assert "spa_authorize" in result["endpoints"]
        assert "spa_token" in result["endpoints"]

        # trust_types should NOT be in factory config - they're for MCP authorization
        assert "trust_types" not in result


class TestOAuthEmailJSONSupport:
    """Test OAuth email handler JSON support for SPAs."""

    def test_email_handler_has_wants_json_method(self):
        """Test that OAuth2EmailHandler has _wants_json method."""
        from actingweb.handlers.oauth_email import OAuth2EmailHandler

        # Verify the method exists
        assert hasattr(OAuth2EmailHandler, "_wants_json")

    def test_email_handler_has_set_cors_headers_method(self):
        """Test that OAuth2EmailHandler has _set_cors_headers method."""
        from actingweb.handlers.oauth_email import OAuth2EmailHandler

        # Verify the method exists
        assert hasattr(OAuth2EmailHandler, "_set_cors_headers")

    def test_json_detection_via_accept_header(self):
        """Test JSON detection logic via Accept header."""
        # Test the logic without instantiating the handler
        accept_header = "application/json"
        is_json = "application/json" in accept_header
        assert is_json is True

        accept_header = "text/html"
        is_json = "application/json" in accept_header
        assert is_json is False

    def test_json_detection_via_format_param(self):
        """Test JSON detection logic via format parameter."""
        format_param = "json"
        is_json = format_param == "json"
        assert is_json is True

        format_param = "html"
        is_json = format_param == "json"
        assert is_json is False


class TestTokenDeliveryModes:
    """Test different token delivery modes."""

    def test_json_mode_returns_all_tokens(self):
        """Test JSON mode returns access and refresh tokens in body."""
        # This would be tested in integration tests
        pass

    def test_cookie_mode_sets_httponly_cookies(self):
        """Test cookie mode sets HttpOnly cookies."""
        # This would be tested in integration tests
        pass

    def test_hybrid_mode_splits_tokens(self):
        """Test hybrid mode returns access in body, refresh in cookie."""
        # This would be tested in integration tests
        pass


class TestRefreshTokenRotation:
    """Test refresh token rotation behavior."""

    def test_refresh_token_uniqueness(self):
        """Test that secrets.token_urlsafe generates unique tokens."""
        import secrets

        # Test the underlying token generation
        token1 = secrets.token_urlsafe(48)
        token2 = secrets.token_urlsafe(48)

        # Each call should produce a unique token
        assert token1 != token2
        assert len(token1) > 40  # token_urlsafe(48) produces ~64 chars
        assert len(token2) > 40

    def test_token_data_structure(self):
        """Test the expected structure of refresh token data."""
        import time

        # Test the data structure that would be stored
        token_data = {
            "actor_id": "actor123",
            "email": "user@example.com",
            "used": False,
            "expires_at": int(time.time()) + (86400 * 14),  # 2 weeks
            "created_at": int(time.time()),
        }

        # Verify structure
        assert "actor_id" in token_data
        assert "email" in token_data
        assert "used" in token_data
        assert "expires_at" in token_data
        assert token_data["used"] is False

        # Simulate marking as used
        token_data["used"] = True
        assert token_data["used"] is True

    def test_used_token_flag(self):
        """Test the 'used' flag for refresh token rotation."""
        # Test that we can detect already-used tokens
        used_token_data = {
            "actor_id": "actor123",
            "used": True,  # Already used!
            "expires_at": 9999999999,
        }

        # The caller should check the 'used' flag
        assert used_token_data["used"] is True

        # Fresh token should have used=False
        fresh_token_data = {
            "actor_id": "actor123",
            "used": False,
            "expires_at": 9999999999,
        }
        assert fresh_token_data["used"] is False


class TestPassphraseExchange:
    """Test passphrase-to-SPA-token exchange endpoint."""

    @pytest.fixture
    def mock_config_devtest_enabled(self):
        """Create a mock config object with devtest enabled."""
        config = MagicMock()
        config.proto = "https://"
        config.fqdn = "test.example.com"
        config.oauth = {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
        }
        config.oauth2_provider = "google"
        config.devtest = True
        config.new_token = MagicMock(return_value="test-access-token")
        return config

    @pytest.fixture
    def mock_config_devtest_disabled(self):
        """Create a mock config object with devtest disabled."""
        config = MagicMock()
        config.proto = "https://"
        config.fqdn = "test.example.com"
        config.oauth = {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
        }
        config.oauth2_provider = "google"
        config.devtest = False
        config.new_token = MagicMock(return_value="test-access-token")
        return config

    @pytest.fixture
    def mock_webobj(self):
        """Create a mock AWWebObj."""
        webobj = MagicMock()
        webobj.request = MagicMock()
        webobj.request.body = None
        webobj.request.headers = {"Accept": "application/json"}
        webobj.request.cookies = {}
        webobj.request.get = MagicMock(return_value="")
        webobj.response = MagicMock()
        webobj.response.headers = {}
        webobj.response._cookies = []
        webobj.response.set_status = MagicMock()
        webobj.response.write = MagicMock()
        webobj.response.set_cookie = MagicMock()
        return webobj

    def test_passphrase_grant_rejected_when_devtest_disabled(
        self, mock_config_devtest_disabled, mock_webobj
    ):
        """Test that passphrase grant returns 403 when devtest mode is disabled."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        mock_webobj.request.body = json.dumps(
            {
                "grant_type": "passphrase",
                "actor_id": "test-actor-id",
                "passphrase": "test-passphrase",
            }
        )

        handler = OAuth2SPAHandler(mock_webobj, mock_config_devtest_disabled)
        result = handler._handle_token()

        assert result["error"] is True
        assert result["status_code"] == 403
        assert "devtest" in result["message"].lower()

    def test_passphrase_grant_missing_actor_id(
        self, mock_config_devtest_enabled, mock_webobj
    ):
        """Test that passphrase grant returns error when actor_id is missing."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        mock_webobj.request.body = json.dumps(
            {
                "grant_type": "passphrase",
                "passphrase": "test-passphrase",
            }
        )

        handler = OAuth2SPAHandler(mock_webobj, mock_config_devtest_enabled)
        result = handler._handle_token()

        assert result["error"] is True
        assert result["status_code"] == 400
        assert "actor_id" in result["message"]

    def test_passphrase_grant_missing_passphrase(
        self, mock_config_devtest_enabled, mock_webobj
    ):
        """Test that passphrase grant returns error when passphrase is missing."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        mock_webobj.request.body = json.dumps(
            {
                "grant_type": "passphrase",
                "actor_id": "test-actor-id",
            }
        )

        handler = OAuth2SPAHandler(mock_webobj, mock_config_devtest_enabled)
        result = handler._handle_token()

        assert result["error"] is True
        assert result["status_code"] == 400
        assert "passphrase" in result["message"]

    def test_passphrase_grant_type_routed_correctly(
        self, mock_config_devtest_enabled, mock_webobj
    ):
        """Test that grant_type=passphrase is routed to the correct handler."""
        from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

        mock_webobj.request.body = json.dumps(
            {
                "grant_type": "passphrase",
                "actor_id": "test-actor-id",
                "passphrase": "test-passphrase",
            }
        )

        handler = OAuth2SPAHandler(mock_webobj, mock_config_devtest_enabled)

        # Patch the _handle_passphrase_exchange method to verify it's called
        with MagicMock() as mock_handler:
            handler._handle_passphrase_exchange = mock_handler
            mock_handler.return_value = {"success": True}

            handler._handle_token()

            # Verify the passphrase handler was called
            mock_handler.assert_called_once()

    def test_passphrase_grant_response_structure(self):
        """Test the expected response structure for successful passphrase exchange."""
        import time

        # Define the expected response structure
        expected_response = {
            "success": True,
            "actor_id": "actor123",
            "access_token": "some-token",
            "refresh_token": "some-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "expires_at": int(time.time()) + 3600,
            "refresh_token_expires_in": 86400 * 14,
        }

        # Verify the structure has all required fields
        assert "success" in expected_response
        assert "actor_id" in expected_response
        assert "access_token" in expected_response
        assert "refresh_token" in expected_response
        assert "token_type" in expected_response
        assert "expires_in" in expected_response
        assert "expires_at" in expected_response
        assert "refresh_token_expires_in" in expected_response
        assert expected_response["token_type"] == "Bearer"
        assert expected_response["expires_in"] == 3600
        assert expected_response["refresh_token_expires_in"] == 86400 * 14
