"""Tests for base_integration module."""

from typing import Any
from unittest.mock import Mock

from actingweb.interface.integrations.base_integration import BaseActingWebIntegration


class TestBaseActingWebIntegrationInit:
    """Test initialization."""

    def test_init_with_actingweb_app(self):
        """Test BaseActingWebIntegration initialization with ActingWebApp."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}

        integration = BaseActingWebIntegration(mock_aw_app)

        assert integration.aw_app == mock_aw_app


class TestGetHandlerClass:
    """Test handler selection logic."""

    def _create_integration(self) -> tuple[BaseActingWebIntegration, Mock, Mock]:
        """Helper to create integration with mocks."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_webobj = Mock()
        mock_webobj.request.get.return_value = None  # No _method override
        mock_config = Mock()

        integration = BaseActingWebIntegration(mock_aw_app)
        return integration, mock_webobj, mock_config

    def test_get_handler_class_root(self):
        """Test root endpoint returns RootHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class("root", webobj, config)

        assert handler is not None
        assert "RootHandler" in type(handler).__name__

    def test_get_handler_class_meta(self):
        """Test meta endpoint returns MetaHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class("meta", webobj, config)

        assert handler is not None
        assert "MetaHandler" in type(handler).__name__

    def test_get_handler_class_properties(self):
        """Test properties endpoint returns PropertiesHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class("properties", webobj, config)

        assert handler is not None
        assert "PropertiesHandler" in type(handler).__name__

    def test_get_handler_class_properties_metadata(self):
        """Test properties metadata endpoint returns PropertyMetadataHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "properties", webobj, config, metadata=True
        )

        assert handler is not None
        assert "PropertyMetadataHandler" in type(handler).__name__

    def test_get_handler_class_properties_items(self):
        """Test properties list items endpoint returns PropertyListItemsHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "properties", webobj, config, items=True
        )

        assert handler is not None
        assert "PropertyListItemsHandler" in type(handler).__name__

    def test_get_handler_class_callbacks(self):
        """Test callbacks endpoint returns CallbacksHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class("callbacks", webobj, config)

        assert handler is not None
        assert "CallbacksHandler" in type(handler).__name__

    def test_get_handler_class_unknown(self):
        """Test unknown endpoint returns None."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class("unknown_endpoint", webobj, config)

        assert handler is None


class TestTrustHandlerSelection:
    """Test trust handler selection."""

    def _create_integration(self) -> tuple[BaseActingWebIntegration, Mock, Mock]:
        """Helper to create integration with mocks."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_webobj = Mock()
        mock_webobj.request.get.return_value = None  # No _method override
        mock_config = Mock()

        integration = BaseActingWebIntegration(mock_aw_app)
        return integration, mock_webobj, mock_config

    def test_trust_root_handler(self):
        """Test trust root endpoint returns TrustHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class("trust", webobj, config)

        assert handler is not None
        assert "TrustHandler" in type(handler).__name__

    def test_trust_relationship_handler(self):
        """Test trust relationship endpoint returns TrustRelationshipHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "trust", webobj, config, relationship="friend"
        )

        assert handler is not None
        assert "TrustRelationshipHandler" in type(handler).__name__

    def test_trust_peer_handler(self):
        """Test trust peer endpoint returns TrustPeerHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "trust", webobj, config, relationship="friend", peerid="peer123"
        )

        assert handler is not None
        assert "TrustPeerHandler" in type(handler).__name__

    def test_trust_permissions_handler(self):
        """Test trust permissions endpoint returns TrustPermissionHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "trust",
            webobj,
            config,
            relationship="friend",
            peerid="peer123",
            permissions=True,
        )

        assert handler is not None
        assert "TrustPermissionHandler" in type(handler).__name__

    def test_trust_shared_properties_handler(self):
        """Test trust shared_properties endpoint returns TrustSharedPropertiesHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "trust",
            webobj,
            config,
            relationship="friend",
            peerid="peer123",
            shared_properties=True,
        )

        assert handler is not None
        assert "TrustSharedPropertiesHandler" in type(handler).__name__

    def test_trust_method_override_handling(self):
        """Test _method=DELETE on single path returns TrustPeerHandler."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_webobj = Mock()
        mock_webobj.request.get.return_value = "DELETE"  # _method override
        mock_config = Mock()

        integration = BaseActingWebIntegration(mock_aw_app)

        handler = integration.get_handler_class(
            "trust", mock_webobj, mock_config, relationship="peer123"
        )

        # With _method=DELETE, single path should be TrustPeerHandler
        assert handler is not None
        assert "TrustPeerHandler" in type(handler).__name__


class TestSubscriptionHandlerSelection:
    """Test subscription handler selection."""

    def _create_integration(self) -> tuple[BaseActingWebIntegration, Mock, Mock]:
        """Helper to create integration with mocks."""
        mock_aw_app = Mock()
        mock_aw_app.hooks = {}
        mock_webobj = Mock()
        mock_webobj.request.get.return_value = None
        mock_config = Mock()

        integration = BaseActingWebIntegration(mock_aw_app)
        return integration, mock_webobj, mock_config

    def test_subscription_root_handler(self):
        """Test subscription root endpoint returns SubscriptionRootHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class("subscriptions", webobj, config)

        assert handler is not None
        assert "SubscriptionRootHandler" in type(handler).__name__

    def test_subscription_relationship_handler(self):
        """Test subscription relationship endpoint returns SubscriptionRelationshipHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "subscriptions", webobj, config, peerid="peer123"
        )

        assert handler is not None
        assert "SubscriptionRelationshipHandler" in type(handler).__name__

    def test_subscription_handler(self):
        """Test subscription with subid returns SubscriptionHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "subscriptions", webobj, config, peerid="peer123", subid="sub456"
        )

        assert handler is not None
        assert handler.__class__.__name__ == "SubscriptionHandler"

    def test_subscription_diff_handler(self):
        """Test subscription diff endpoint returns SubscriptionDiffHandler."""
        integration, webobj, config = self._create_integration()

        handler = integration.get_handler_class(
            "subscriptions", webobj, config, peerid="peer123", subid="sub456", seqnr=5
        )

        assert handler is not None
        assert "SubscriptionDiffHandler" in type(handler).__name__


class TestStaticMethods:
    """Test static utility methods."""

    def test_get_oauth_discovery_metadata(self):
        """Test get_oauth_discovery_metadata returns proper structure."""
        mock_config = Mock()
        mock_config.proto = "https://"
        mock_config.fqdn = "test.example.com"

        result = BaseActingWebIntegration.get_oauth_discovery_metadata(mock_config)

        assert result["issuer"] == "https://test.example.com"
        assert (
            result["authorization_endpoint"]
            == "https://test.example.com/oauth/authorize"
        )
        assert result["token_endpoint"] == "https://test.example.com/oauth/token"
        assert "code" in result["response_types_supported"]
        assert "authorization_code" in result["grant_types_supported"]
        assert "refresh_token" in result["grant_types_supported"]
        assert "S256" in result["code_challenge_methods_supported"]

    def test_normalize_http_method_uppercase(self):
        """Test normalize_http_method converts to uppercase."""
        assert BaseActingWebIntegration.normalize_http_method("get") == "GET"
        assert BaseActingWebIntegration.normalize_http_method("post") == "POST"
        assert BaseActingWebIntegration.normalize_http_method("Put") == "PUT"
        assert BaseActingWebIntegration.normalize_http_method("DELETE") == "DELETE"

    def test_normalize_http_method_empty(self):
        """Test normalize_http_method handles empty string."""
        assert BaseActingWebIntegration.normalize_http_method("") == "GET"

    def test_build_error_response(self):
        """Test build_error_response creates error structure."""
        result = BaseActingWebIntegration.build_error_response(404, "Not found")

        assert result["error"]["code"] == 404
        assert result["error"]["message"] == "Not found"

    def test_build_success_response_dict(self):
        """Test build_success_response returns dict as-is."""
        input_data: dict[str, Any] = {"key": "value", "nested": {"a": 1}}
        result = BaseActingWebIntegration.build_success_response(input_data)

        assert result == input_data

    def test_build_success_response_non_dict(self):
        """Test build_success_response wraps non-dict data."""
        result = BaseActingWebIntegration.build_success_response(["item1", "item2"])

        assert "data" in result
        assert result["data"] == ["item1", "item2"]
        assert result["status"] == "success"

    def test_extract_path_params(self):
        """Test extract_path_params returns empty dict (placeholder)."""
        result = BaseActingWebIntegration.extract_path_params(
            "/test/path", "/test/{id}"
        )

        assert result == {}
