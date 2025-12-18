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
        assert callable(getattr(FlaskIntegration, "setup_routes"))

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
