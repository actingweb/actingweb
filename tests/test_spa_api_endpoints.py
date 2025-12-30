"""
Tests for SPA-oriented API endpoints added for React frontend support.

Tests cover:
1. OAuth2CallbackHandler SPA mode state decoding
2. Handler class existence and methods
3. Config trust types support
"""

import json
import unittest

from actingweb.config import Config


class TestOAuth2CallbackSPAMode(unittest.TestCase):
    """Test OAuth2CallbackHandler SPA mode support."""

    def test_decode_state_with_spa_mode(self):
        """Test state decoding extracts spa_mode flag."""
        from actingweb.handlers.oauth2_callback import _decode_state_with_extras

        # Create state with spa_mode - this is the raw JSON state format
        state_data = {
            "actor_id": "test_actor",
            "spa_mode": True,
            "redirect_uri": "/dashboard",
        }
        state_json = json.dumps(state_data)

        result = _decode_state_with_extras(state_json)

        self.assertEqual(result.get("actor_id"), "test_actor")
        self.assertTrue(result.get("spa_mode"))
        self.assertEqual(result.get("redirect_uri"), "/dashboard")

    def test_decode_state_without_spa_mode(self):
        """Test state decoding works without spa_mode (backwards compatible)."""
        from actingweb.handlers.oauth2_callback import _decode_state_with_extras

        # Simple state without spa_mode
        state_data = {"actor_id": "test_actor"}
        state_json = json.dumps(state_data)

        result = _decode_state_with_extras(state_json)

        self.assertEqual(result.get("actor_id"), "test_actor")
        self.assertFalse(result.get("spa_mode", False))

    def test_decode_non_json_state(self):
        """Test decoding non-JSON state returns empty dict."""
        from actingweb.handlers.oauth2_callback import _decode_state_with_extras

        # Non-JSON state (legacy format)
        result = _decode_state_with_extras("plain_actor_id")

        self.assertEqual(result, {})

    def test_decode_empty_state(self):
        """Test decoding empty state returns empty dict."""
        from actingweb.handlers.oauth2_callback import _decode_state_with_extras

        result = _decode_state_with_extras("")
        self.assertEqual(result, {})

        result = _decode_state_with_extras(None)  # type: ignore
        self.assertEqual(result, {})

    def test_decode_state_with_extra_fields(self):
        """Test state decoding preserves extra fields."""
        from actingweb.handlers.oauth2_callback import _decode_state_with_extras

        state_data = {
            "actor_id": "test_actor",
            "spa_mode": True,
            "client_type": "chatgpt",
            "trust_type": "mcp_client",
        }
        state_json = json.dumps(state_data)

        result = _decode_state_with_extras(state_json)

        self.assertEqual(result.get("client_type"), "chatgpt")
        self.assertEqual(result.get("trust_type"), "mcp_client")


class TestPropertyMetadataHandlerImport(unittest.TestCase):
    """Test that PropertyMetadataHandler is properly defined and importable."""

    def test_property_metadata_handler_exists(self):
        """Verify PropertyMetadataHandler class exists and is importable."""
        from actingweb.handlers.properties import PropertyMetadataHandler

        # Verify it's a class
        self.assertTrue(callable(PropertyMetadataHandler))

        # Verify it has expected methods
        self.assertTrue(hasattr(PropertyMetadataHandler, "get"))
        self.assertTrue(hasattr(PropertyMetadataHandler, "put"))

    def test_properties_handler_listall_accepts_metadata_param(self):
        """Verify PropertiesHandler.listall has metadata parameter handling."""
        import inspect

        from actingweb.handlers.properties import PropertiesHandler

        # Get the listall method source to verify it handles metadata param
        source = inspect.getsource(PropertiesHandler.listall)

        # Verify the method checks for metadata parameter
        self.assertIn("metadata", source.lower())

    def test_property_metadata_handler_has_permission_check(self):
        """Verify PropertyMetadataHandler has permission checking."""
        from actingweb.handlers.properties import PropertyMetadataHandler

        # Verify it has permission check method
        self.assertTrue(hasattr(PropertyMetadataHandler, "_check_property_permission"))


class TestTrustEndpointOAuth2Data(unittest.TestCase):
    """Test that trust endpoint returns OAuth2 client data."""

    def test_trust_db_model_has_oauth2_fields(self):
        """Verify Trust DB model has OAuth2 client fields."""
        from actingweb.db.dynamodb.trust import Trust

        # Verify OAuth2 client metadata fields exist
        self.assertTrue(hasattr(Trust, "client_name"))
        self.assertTrue(hasattr(Trust, "client_version"))
        self.assertTrue(hasattr(Trust, "client_platform"))
        self.assertTrue(hasattr(Trust, "oauth_client_id"))
        self.assertTrue(hasattr(Trust, "established_via"))
        self.assertTrue(hasattr(Trust, "peer_identifier"))

    def test_oauth2_client_manager_has_list_clients(self):
        """Verify OAuth2ClientManager has list_clients method."""
        from actingweb.interface.oauth_client_manager import OAuth2ClientManager

        # Verify it has list_clients method
        self.assertTrue(hasattr(OAuth2ClientManager, "list_clients"))


class TestEmailVerificationHandlerJSON(unittest.TestCase):
    """Test EmailVerificationHandler JSON API methods exist."""

    def test_email_verification_handler_has_json_methods(self):
        """Verify EmailVerificationHandler has JSON API methods."""
        from actingweb.handlers.email_verification import EmailVerificationHandler

        # Verify it has the JSON helper methods
        self.assertTrue(hasattr(EmailVerificationHandler, "_wants_json"))
        self.assertTrue(hasattr(EmailVerificationHandler, "_json_response"))

    def test_email_verification_handler_has_error_response(self):
        """Verify EmailVerificationHandler has error_response method."""
        from actingweb.handlers.email_verification import EmailVerificationHandler

        # Verify it has error_response method
        self.assertTrue(hasattr(EmailVerificationHandler, "error_response"))


class TestMetaHandlerTrustTypes(unittest.TestCase):
    """Test MetaHandler includes trusttypes support."""

    def test_meta_handler_handles_trusttypes_path(self):
        """Verify MetaHandler.get can handle trusttypes path."""
        import inspect

        from actingweb.handlers.meta import MetaHandler

        # Get the get method source
        source = inspect.getsource(MetaHandler.get)

        # Verify it handles trusttypes
        self.assertIn("trusttypes", source)

    def test_meta_handler_returns_default_trust_type(self):
        """Verify MetaHandler source includes default_trust_type handling."""
        import inspect

        from actingweb.handlers.meta import MetaHandler

        source = inspect.getsource(MetaHandler.get)

        # Verify it includes default_trust_type in response
        self.assertIn("default_trust_type", source)


class TestConfigTrustTypes(unittest.TestCase):
    """Test Config object can store trust types configuration."""

    def test_config_accepts_trust_types(self):
        """Verify Config can be configured with trust types."""
        config = Config(database="dynamodb", devtest=True)

        # Set trust types (dynamic attributes)
        config.trust_types = {  # type: ignore[attr-defined]
            "mcp_client": {"name": "mcp_client", "relationship": "friend"}
        }
        config.default_trust_type = "mcp_client"  # type: ignore[attr-defined]

        # Verify they're stored
        self.assertEqual(config.default_trust_type, "mcp_client")  # type: ignore[attr-defined]
        self.assertIn("mcp_client", config.trust_types)  # type: ignore[attr-defined]

    def test_config_has_trust_type_registry_attribute(self):
        """Verify Config can have trust_type_registry attribute."""
        config = Config(database="dynamodb", devtest=True)

        # Should be able to set trust_type_registry (dynamic attribute)
        config.trust_type_registry = None  # type: ignore[attr-defined]
        self.assertIsNone(config.trust_type_registry)  # type: ignore[attr-defined]


class TestTrustTypeDataclass(unittest.TestCase):
    """Test TrustType dataclass."""

    def test_trust_type_to_dict(self):
        """Test TrustType converts to dictionary."""
        from actingweb.trust_type_registry import TrustType

        trust_type = TrustType(
            name="test_client",
            display_name="Test Client",
            description="A test client",
            base_permissions={"read": True, "write": False},
        )

        result = trust_type.to_dict()

        self.assertEqual(result["name"], "test_client")
        self.assertEqual(result["display_name"], "Test Client")
        self.assertEqual(result["base_permissions"]["read"], True)

    def test_trust_type_from_dict(self):
        """Test TrustType creates from dictionary."""
        from actingweb.trust_type_registry import TrustType

        data = {
            "name": "test_client",
            "display_name": "Test Client",
            "description": "A test client",
            "base_permissions": {"read": True},
        }

        trust_type = TrustType.from_dict(data)

        self.assertEqual(trust_type.name, "test_client")
        self.assertEqual(trust_type.display_name, "Test Client")

    def test_trust_type_validate(self):
        """Test TrustType validation."""
        from actingweb.trust_type_registry import TrustType

        valid = TrustType(
            name="test", display_name="Test", description="Desc", base_permissions={}
        )
        self.assertTrue(valid.validate())

        invalid = TrustType(
            name="",  # Empty name
            display_name="Test",
            description="Desc",
            base_permissions={},
        )
        self.assertFalse(invalid.validate())


class TestListPropertyMetadata(unittest.TestCase):
    """Test ListProperty metadata methods exist."""

    def test_list_property_has_metadata_methods(self):
        """Verify ListProperty has metadata methods."""
        from actingweb.property_list import ListProperty

        # Verify metadata methods exist
        self.assertTrue(hasattr(ListProperty, "set_description"))
        self.assertTrue(hasattr(ListProperty, "get_description"))
        self.assertTrue(hasattr(ListProperty, "set_explanation"))
        self.assertTrue(hasattr(ListProperty, "get_explanation"))


class TestHandlerRouteMetadata(unittest.TestCase):
    """Test that handler routes have correct metadata flags."""

    def test_base_integration_has_metadata_flag_handling(self):
        """Verify base integration handles metadata flag in get_handler_class."""
        import inspect

        from actingweb.interface.integrations import base_integration

        source = inspect.getsource(
            base_integration.BaseActingWebIntegration.get_handler_class
        )

        # Verify metadata flag handling for properties
        self.assertIn("metadata", source)

    def test_fastapi_integration_inherits_from_base(self):
        """Verify FastAPI integration inherits from base integration."""
        from actingweb.interface.integrations import (
            base_integration,
            fastapi_integration,
        )

        self.assertTrue(
            issubclass(
                fastapi_integration.FastAPIIntegration,
                base_integration.BaseActingWebIntegration,
            )
        )

    def test_flask_integration_inherits_from_base(self):
        """Verify Flask integration inherits from base integration."""
        from actingweb.interface.integrations import (
            base_integration,
            flask_integration,
        )

        self.assertTrue(
            issubclass(
                flask_integration.FlaskIntegration,
                base_integration.BaseActingWebIntegration,
            )
        )


if __name__ == "__main__":
    unittest.main()
