"""Tests for Flask integration module."""

from unittest.mock import Mock, patch

from actingweb.interface.integrations.flask_integration import FlaskIntegration


class TestFlaskIntegrationInit:
    """Test Flask integration initialization."""

    def test_init_with_flask_app(self):
        """Test FlaskIntegration initialization with Flask app."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_flask_app = Mock()

        with patch.object(FlaskIntegration, "setup_routes"):
            integration = FlaskIntegration(mock_aw_app, mock_flask_app)

        assert integration.aw_app == mock_aw_app
        assert integration.flask_app == mock_flask_app

    def test_inherits_base_integration(self):
        """Test FlaskIntegration inherits from BaseActingWebIntegration."""
        from actingweb.interface.integrations.base_integration import (
            BaseActingWebIntegration,
        )

        assert issubclass(FlaskIntegration, BaseActingWebIntegration)


class TestFlaskIntegrationMethods:
    """Test Flask integration methods."""

    def test_setup_routes_method_exists(self):
        """Test that FlaskIntegration has setup_routes method."""
        assert hasattr(FlaskIntegration, "setup_routes")
        assert callable(FlaskIntegration.setup_routes)

    def test_get_handler_class_inherited(self):
        """Test FlaskIntegration inherits get_handler_class from base."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_flask_app = Mock()

        with patch.object(FlaskIntegration, "setup_routes"):
            integration = FlaskIntegration(mock_aw_app, mock_flask_app)

        assert hasattr(integration, "get_handler_class")
        assert callable(integration.get_handler_class)

    def test_get_oauth_discovery_metadata_inherited(self):
        """Test FlaskIntegration inherits get_oauth_discovery_metadata from base."""
        mock_config = Mock()
        mock_config.proto = "https://"
        mock_config.fqdn = "test.example.com"

        result = FlaskIntegration.get_oauth_discovery_metadata(mock_config)

        assert result["issuer"] == "https://test.example.com"
        assert "authorization_endpoint" in result
        assert "token_endpoint" in result


class TestFlaskIntegrationAttributes:
    """Test Flask integration attributes."""

    def test_has_aw_app_attribute(self):
        """Test FlaskIntegration has aw_app attribute after init."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_flask_app = Mock()

        with patch.object(FlaskIntegration, "setup_routes"):
            integration = FlaskIntegration(mock_aw_app, mock_flask_app)

        assert hasattr(integration, "aw_app")
        assert integration.aw_app == mock_aw_app

    def test_has_flask_app_attribute(self):
        """Test FlaskIntegration has flask_app attribute after init."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_flask_app = Mock()

        with patch.object(FlaskIntegration, "setup_routes"):
            integration = FlaskIntegration(mock_aw_app, mock_flask_app)

        assert hasattr(integration, "flask_app")
        assert integration.flask_app == mock_flask_app


class TestFlaskOAuthAuthentication:
    """Test Flask OAuth authentication and token validation."""

    def _create_integration(self):
        """Create a FlaskIntegration instance for testing."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_config = Mock()
        mock_config.oauth = True
        mock_aw_app.get_config.return_value = mock_config
        mock_flask_app = Mock()

        with patch.object(FlaskIntegration, "setup_routes"):
            return FlaskIntegration(mock_aw_app, mock_flask_app)

    def test_valid_actingweb_session_token_returns_none(self):
        """Test that valid ActingWeb session token allows access."""
        integration = self._create_integration()

        mock_request = Mock()
        mock_request.authorization = None
        mock_request.headers = {}
        mock_request.cookies = {"oauth_token": "valid_session_token"}
        mock_request.url = "http://test.example.com/actor123/www"

        mock_session_manager = Mock()
        mock_session_manager.validate_access_token.return_value = {
            "actor_id": "actor123",
            "email": "user@example.com",
        }

        with patch(
            "actingweb.interface.integrations.flask_integration.request", mock_request
        ):
            with patch(
                "actingweb.oauth_session.get_oauth2_session_manager",
                return_value=mock_session_manager,
            ):
                result = integration._check_authentication_and_redirect()

        assert result is None  # None means authentication succeeded
        mock_session_manager.validate_access_token.assert_called_once_with(
            "valid_session_token"
        )

    def test_invalid_session_valid_oauth_provider_token_returns_none(self):
        """Test OAuth provider token fallback when session token is invalid."""
        integration = self._create_integration()

        mock_request = Mock()
        mock_request.authorization = None
        mock_request.headers = {}
        mock_request.cookies = {"oauth_token": "oauth_provider_token"}
        mock_request.url = "http://test.example.com/actor123/www"

        # Session manager returns None (invalid session token)
        mock_session_manager = Mock()
        mock_session_manager.validate_access_token.return_value = None

        # OAuth authenticator validates the provider token
        mock_authenticator = Mock()
        mock_authenticator.is_enabled.return_value = True
        mock_authenticator.validate_token_and_get_user_info.return_value = {
            "email": "user@example.com"
        }
        mock_authenticator.get_email_from_user_info.return_value = "user@example.com"

        with patch(
            "actingweb.interface.integrations.flask_integration.request", mock_request
        ):
            with patch(
                "actingweb.oauth_session.get_oauth2_session_manager",
                return_value=mock_session_manager,
            ):
                with patch(
                    "actingweb.oauth2.create_oauth2_authenticator",
                    return_value=mock_authenticator,
                ):
                    result = integration._check_authentication_and_redirect()

        assert result is None  # None means authentication succeeded via fallback
        mock_authenticator.validate_token_and_get_user_info.assert_called_once_with(
            "oauth_provider_token"
        )

    def test_invalid_tokens_redirects_to_oauth(self):
        """Test that invalid tokens redirect to OAuth."""
        integration = self._create_integration()

        mock_request = Mock()
        mock_request.authorization = None
        mock_request.headers = {}
        mock_request.cookies = {"oauth_token": "invalid_token"}
        mock_request.url = "http://test.example.com/actor123/www"

        # Session manager returns None
        mock_session_manager = Mock()
        mock_session_manager.validate_access_token.return_value = None

        # OAuth authenticator also fails
        mock_authenticator = Mock()
        mock_authenticator.is_enabled.return_value = True
        mock_authenticator.validate_token_and_get_user_info.return_value = None

        mock_redirect_response = Mock()

        with patch(
            "actingweb.interface.integrations.flask_integration.request", mock_request
        ):
            with patch(
                "actingweb.oauth_session.get_oauth2_session_manager",
                return_value=mock_session_manager,
            ):
                with patch(
                    "actingweb.oauth2.create_oauth2_authenticator",
                    return_value=mock_authenticator,
                ):
                    with patch.object(
                        integration,
                        "_create_oauth_redirect_response",
                        return_value=mock_redirect_response,
                    ) as mock_redirect:
                        result = integration._check_authentication_and_redirect()

        assert result == mock_redirect_response
        mock_redirect.assert_called_once_with(
            redirect_after_auth="http://test.example.com/actor123/www",
            clear_cookie=True,
        )

    def test_no_oauth_cookie_redirects_to_oauth(self):
        """Test that missing oauth_token cookie redirects to OAuth."""
        integration = self._create_integration()

        mock_request = Mock()
        mock_request.authorization = None
        mock_request.headers = {}
        mock_request.cookies = {}  # No oauth_token cookie
        mock_request.url = "http://test.example.com/actor123/www"

        mock_redirect_response = Mock()

        with patch(
            "actingweb.interface.integrations.flask_integration.request", mock_request
        ):
            with patch.object(
                integration,
                "_create_oauth_redirect_response",
                return_value=mock_redirect_response,
            ) as mock_redirect:
                result = integration._check_authentication_and_redirect()

        assert result == mock_redirect_response
        mock_redirect.assert_called_once_with(
            redirect_after_auth="http://test.example.com/actor123/www",
            clear_cookie=False,  # No cookie to clear
        )

    def test_basic_auth_header_returns_none(self):
        """Test that Basic auth header bypasses OAuth check."""
        integration = self._create_integration()

        mock_request = Mock()
        mock_request.authorization = Mock()  # Has authorization
        mock_request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        mock_request.cookies = {}

        with patch(
            "actingweb.interface.integrations.flask_integration.request", mock_request
        ):
            result = integration._check_authentication_and_redirect()

        assert result is None  # Basic auth bypasses OAuth

    def test_bearer_token_returns_none(self):
        """Test that Bearer token bypasses OAuth redirect."""
        integration = self._create_integration()

        mock_request = Mock()
        mock_request.authorization = None
        mock_request.headers = {"Authorization": "Bearer some_token"}
        mock_request.cookies = {}

        with patch(
            "actingweb.interface.integrations.flask_integration.request", mock_request
        ):
            result = integration._check_authentication_and_redirect()

        assert result is None  # Bearer token bypasses OAuth redirect

    def test_session_token_validation_exception_falls_back_to_oauth_provider(self):
        """Test that session validation exception falls back to OAuth provider."""
        integration = self._create_integration()

        mock_request = Mock()
        mock_request.authorization = None
        mock_request.headers = {}
        mock_request.cookies = {"oauth_token": "some_token"}
        mock_request.url = "http://test.example.com/actor123/www"

        # Session manager raises exception
        mock_session_manager = Mock()
        mock_session_manager.validate_access_token.side_effect = Exception(
            "Session error"
        )

        # OAuth authenticator validates successfully
        mock_authenticator = Mock()
        mock_authenticator.is_enabled.return_value = True
        mock_authenticator.validate_token_and_get_user_info.return_value = {
            "email": "user@example.com"
        }
        mock_authenticator.get_email_from_user_info.return_value = "user@example.com"

        with patch(
            "actingweb.interface.integrations.flask_integration.request", mock_request
        ):
            with patch(
                "actingweb.oauth_session.get_oauth2_session_manager",
                return_value=mock_session_manager,
            ):
                with patch(
                    "actingweb.oauth2.create_oauth2_authenticator",
                    return_value=mock_authenticator,
                ):
                    result = integration._check_authentication_and_redirect()

        assert result is None  # Fallback succeeded

    def test_oauth_provider_validation_exception_redirects_to_oauth(self):
        """Test that OAuth provider validation exception redirects to OAuth."""
        integration = self._create_integration()

        mock_request = Mock()
        mock_request.authorization = None
        mock_request.headers = {}
        mock_request.cookies = {"oauth_token": "some_token"}
        mock_request.url = "http://test.example.com/actor123/www"

        # Session manager returns None
        mock_session_manager = Mock()
        mock_session_manager.validate_access_token.return_value = None

        # OAuth authenticator raises exception
        mock_authenticator = Mock()
        mock_authenticator.is_enabled.return_value = True
        mock_authenticator.validate_token_and_get_user_info.side_effect = Exception(
            "OAuth provider error"
        )

        mock_redirect_response = Mock()

        with patch(
            "actingweb.interface.integrations.flask_integration.request", mock_request
        ):
            with patch(
                "actingweb.oauth_session.get_oauth2_session_manager",
                return_value=mock_session_manager,
            ):
                with patch(
                    "actingweb.oauth2.create_oauth2_authenticator",
                    return_value=mock_authenticator,
                ):
                    with patch.object(
                        integration,
                        "_create_oauth_redirect_response",
                        return_value=mock_redirect_response,
                    ):
                        result = integration._check_authentication_and_redirect()

        assert result == mock_redirect_response
