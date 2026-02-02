"""Tests for permission query endpoint."""

import json
from unittest.mock import MagicMock, patch

import pytest

from actingweb.handlers.permissions import PermissionsHandler
from actingweb.trust_permissions import TrustPermissions


class TestPermissionsHandler:
    """Test permission query handler."""

    @pytest.fixture
    def mock_webobj(self):
        """Create mock web object."""
        webobj = MagicMock()
        webobj.request = MagicMock()
        webobj.request.get = MagicMock(return_value=None)
        webobj.response = MagicMock()
        return webobj

    @pytest.fixture
    def mock_config(self):
        """Create mock config."""
        config = MagicMock()
        return config

    @pytest.fixture
    def handler(self, mock_webobj, mock_config):
        """Create handler instance."""
        handler = PermissionsHandler(mock_webobj, mock_config)
        handler.response = MagicMock()
        return handler

    def test_get_permissions_custom_override(self, handler):
        """Test querying custom permission overrides."""
        # Mock authentication
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.actor = MagicMock()
        auth_result.authorize = MagicMock(return_value=True)

        # Mock actor interface with trust relationship
        mock_actor_interface = MagicMock()
        trust_rel = MagicMock()
        trust_rel.relationship = "subscriber"
        mock_actor_interface.trust.get_relationship = MagicMock(return_value=trust_rel)

        handler.authenticate_actor = MagicMock(return_value=auth_result)
        handler._get_actor_interface = MagicMock(return_value=mock_actor_interface)

        # Mock custom permissions
        custom_perms = TrustPermissions(
            actor_id="actor123",
            peer_id="peer456",
            trust_type="subscriber",
            properties={"patterns": ["memory_travel"], "operations": ["read"]},
        )

        # Create a proper mock that returns None for non-existent attributes
        mock_store = MagicMock()
        mock_store_instance = MagicMock()
        mock_store_instance.get_permissions.return_value = custom_perms
        # Mock _get_effective_permissions to return the expected merged result
        mock_store_instance._get_effective_permissions.return_value = {
            "properties": {"patterns": ["memory_travel"], "operations": ["read"]},
            "methods": None,
            "actions": None,
            "tools": None,
            "resources": None,
            "prompts": None,
        }
        mock_store.return_value = mock_store_instance

        with patch(
            "actingweb.handlers.permissions.get_trust_permission_store", mock_store
        ):
            handler.get("actor123", "peer456")

            # Verify response
            handler.response.set_status.assert_called_with(200, "OK")
            written_data = handler.response.write.call_args[0][0]
            response = json.loads(written_data)

            assert response["actor_id"] == "actor123"
            assert response["peer_id"] == "peer456"
            assert response["source"] == "custom_override"
            assert "memory_travel" in response["permissions"]["properties"]["patterns"]

    def test_get_permissions_trust_type_default(self, handler):
        """Test querying trust type default permissions."""
        # Mock authentication
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.actor = MagicMock()
        auth_result.authorize = MagicMock(return_value=True)

        # Mock actor interface with trust relationship
        mock_actor_interface = MagicMock()
        trust_rel = MagicMock()
        trust_rel.relationship = "subscriber"
        mock_actor_interface.trust.get_relationship = MagicMock(return_value=trust_rel)

        handler.authenticate_actor = MagicMock(return_value=auth_result)
        handler._get_actor_interface = MagicMock(return_value=mock_actor_interface)

        # Mock no custom permissions
        mock_store = MagicMock()
        mock_store_instance = MagicMock()
        mock_store_instance.get_permissions.return_value = None
        mock_store.return_value = mock_store_instance

        # Mock trust type registry
        mock_registry = MagicMock()
        registry_instance = MagicMock()
        trust_type = MagicMock()
        trust_type.base_permissions = {
            "properties": {
                "patterns": ["displayname", "email"],
                "operations": ["read"],
            },
            "methods": {},
            "actions": {},
            "tools": {},
            "resources": {},
            "prompts": {},
        }
        registry_instance.get_type.return_value = trust_type
        mock_registry.return_value = registry_instance

        with patch(
            "actingweb.handlers.permissions.get_trust_permission_store", mock_store
        ):
            with patch("actingweb.handlers.permissions.get_registry", mock_registry):
                handler.get("actor123", "peer456")

                # Verify response
                handler.response.set_status.assert_called_with(200, "OK")
                written_data = handler.response.write.call_args[0][0]
                response = json.loads(written_data)

                assert response["source"] == "trust_type_default"
                assert response["trust_type"] == "subscriber"
                assert (
                    "displayname" in response["permissions"]["properties"]["patterns"]
                )

    def test_get_permissions_no_trust_relationship(self, handler):
        """Test querying permissions with no trust relationship."""
        # Mock authentication
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.actor = MagicMock()

        # Mock no trust relationship
        auth_result.actor.trust.get_relationship = MagicMock(return_value=None)

        handler.authenticate_actor = MagicMock(return_value=auth_result)

        handler.get("actor123", "peer456")

        # Verify 404 response
        handler.response.set_status.assert_called_with(
            404, "Trust relationship not found"
        )

    def test_get_permissions_auth_failed(self, handler):
        """Test querying permissions with authentication failure."""
        # Mock failed authentication
        auth_result = MagicMock()
        auth_result.success = False

        handler.authenticate_actor = MagicMock(return_value=auth_result)

        handler.get("actor123", "peer456")

        # Handler should return early, no status set
        handler.response.set_status.assert_not_called()

    def test_get_permissions_authorization_failed(self, handler):
        """Test querying permissions with authorization failure."""
        # Mock authentication success but authorization failure
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.actor = MagicMock()

        # Mock auth_obj.check_authorisation to return False
        mock_auth_obj = MagicMock()
        mock_auth_obj.check_authorisation = MagicMock(return_value=False)
        auth_result.auth_obj = mock_auth_obj

        # Mock actor interface with trust relationship
        mock_actor_interface = MagicMock()
        trust_rel = MagicMock()
        trust_rel.relationship = "subscriber"
        mock_actor_interface.trust.get_relationship = MagicMock(return_value=trust_rel)

        handler.authenticate_actor = MagicMock(return_value=auth_result)
        handler._get_actor_interface = MagicMock(return_value=mock_actor_interface)

        handler.get("actor123", "peer456")

        # Verify authorization was checked with correct parameters
        mock_auth_obj.check_authorisation.assert_called_once_with(
            path="permissions",
            subpath="<id>",
            method="GET",
            peerid="peer456",
        )

        # Verify 403 response was set
        handler.response.set_status.assert_called_with(403, "Forbidden")

    def test_get_permissions_trust_type_not_found(self, handler):
        """Test querying permissions when trust type is not found in registry."""
        # Mock authentication
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.actor = MagicMock()
        auth_result.authorize = MagicMock(return_value=True)

        # Mock actor interface with trust relationship
        mock_actor_interface = MagicMock()
        trust_rel = MagicMock()
        trust_rel.relationship = "unknown_type"
        mock_actor_interface.trust.get_relationship = MagicMock(return_value=trust_rel)

        handler.authenticate_actor = MagicMock(return_value=auth_result)
        handler._get_actor_interface = MagicMock(return_value=mock_actor_interface)

        # Mock no custom permissions
        mock_store = MagicMock()
        mock_store_instance = MagicMock()
        mock_store_instance.get_permissions.return_value = None
        mock_store.return_value = mock_store_instance

        # Mock trust type not found in registry
        mock_registry = MagicMock()
        registry_instance = MagicMock()
        registry_instance.get_type.return_value = None
        mock_registry.return_value = registry_instance

        with patch(
            "actingweb.handlers.permissions.get_trust_permission_store", mock_store
        ):
            with patch("actingweb.handlers.permissions.get_registry", mock_registry):
                handler.get("actor123", "peer456")

                # Verify 500 response
                handler.response.set_status.assert_called_with(
                    500, "Trust type 'unknown_type' not configured"
                )

    def test_get_permissions_exception_handling(self, handler):
        """Test exception handling in permission query."""
        # Mock authentication
        auth_result = MagicMock()
        auth_result.success = True
        auth_result.actor = MagicMock()
        auth_result.authorize = MagicMock(return_value=True)

        # Mock actor interface with trust relationship
        mock_actor_interface = MagicMock()
        trust_rel = MagicMock()
        trust_rel.relationship = "subscriber"
        mock_actor_interface.trust.get_relationship = MagicMock(return_value=trust_rel)

        handler.authenticate_actor = MagicMock(return_value=auth_result)
        handler._get_actor_interface = MagicMock(return_value=mock_actor_interface)

        # Mock exception in get_permissions
        mock_store = MagicMock()
        mock_store.side_effect = Exception("Database error")

        with patch(
            "actingweb.handlers.permissions.get_trust_permission_store", mock_store
        ):
            handler.get("actor123", "peer456")

            # Verify 500 response
            handler.response.set_status.assert_called_with(500, "Internal server error")
