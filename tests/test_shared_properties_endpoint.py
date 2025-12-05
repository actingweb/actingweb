"""Tests for /trust/{rel}/{peer}/shared_properties endpoint."""

import json
from unittest.mock import Mock, patch

from actingweb.handlers.trust import TrustSharedPropertiesHandler
from actingweb.permission_evaluator import PermissionResult


class TestSharedPropertiesEndpoint:
    """Test suite for TrustSharedPropertiesHandler."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_config = Mock()
        self.mock_config.database = Mock()
        self.mock_config.root = "http://localhost"
        self.mock_response = Mock()
        self.mock_response.write = Mock()
        self.mock_response.set_status = Mock()
        self.mock_response.headers = {}

    def test_returns_permitted_properties(self):
        """Endpoint returns only properties peer has subscribe permission on."""
        # Create handler
        webobj = Mock()
        webobj.request = Mock()
        handler = TrustSharedPropertiesHandler(webobj, self.mock_config)
        handler.response = self.mock_response

        # Mock authentication
        mock_auth_result = Mock()
        mock_auth_result.success = True
        mock_actor = Mock()
        mock_actor.id = "actor-123"
        mock_auth_result.actor = mock_actor
        mock_auth_result.auth_obj = Mock()
        mock_auth_result.auth_obj.acl = {"peerid": "peer-123"}

        # Mock trust relationship
        mock_actor.get_trust_relationship = Mock(return_value={
            "peerid": "peer-123",
            "relationship": "friend"
        })

        # Mock properties
        mock_actor.get_properties = Mock(return_value={
            "data_public": {"info": "public"},
            "data_private": {"info": "private"},
            "config_settings": {"theme": "dark"},
        })

        with patch.object(handler, "authenticate_actor", return_value=mock_auth_result):
            with patch("actingweb.handlers.trust.get_permission_evaluator") as mock_get_eval:
                mock_evaluator = Mock()
                mock_get_eval.return_value = mock_evaluator

                # data_public allowed, others denied
                def permission_side_effect(actor_id, peer_id, prop_path, operation):
                    if prop_path == "data_public":
                        return PermissionResult.ALLOWED
                    return PermissionResult.DENIED

                mock_evaluator.evaluate_property_access.side_effect = permission_side_effect

                # Call the handler
                handler.get("actor-123", "friend", "peer-123")

                # Verify response
                assert self.mock_response.set_status.called
                assert self.mock_response.set_status.call_args[0][0] == 200
                assert self.mock_response.write.called

                # Parse response data
                response_json = self.mock_response.write.call_args[0][0]
                response_data = json.loads(response_json)

                # Verify structure
                assert response_data["actor_id"] == "actor-123"
                assert response_data["peer_id"] == "peer-123"
                assert response_data["relationship"] == "friend"

                # Verify only data_public is shared
                shared_names = [p["name"] for p in response_data["shared_properties"]]
                assert "data_public" in shared_names
                assert "data_private" not in shared_names
                assert "config_settings" not in shared_names

                # Verify excluded list
                assert "data_private" in response_data["excluded_properties"]
                assert "config_settings" in response_data["excluded_properties"]

    def test_requires_matching_peer_authentication(self):
        """Endpoint rejects requests where authenticated peer != path peer."""
        webobj = Mock()
        webobj.request = Mock()
        handler = TrustSharedPropertiesHandler(webobj, self.mock_config)
        handler.response = self.mock_response

        # Mock authentication with wrong peer
        mock_auth_result = Mock()
        mock_auth_result.success = True
        mock_actor = Mock()
        mock_auth_result.actor = mock_actor
        mock_auth_result.auth_obj = Mock()
        mock_auth_result.auth_obj.acl = {"peerid": "different-peer"}  # Wrong peer

        with patch.object(handler, "authenticate_actor", return_value=mock_auth_result):
            handler.get("actor-123", "friend", "peer-123")

            # Should return 403
            assert self.mock_response.set_status.called
            assert self.mock_response.set_status.call_args[0][0] == 403

    def test_requires_active_trust_relationship(self):
        """Endpoint returns 404 if trust relationship doesn't exist."""
        webobj = Mock()
        webobj.request = Mock()
        handler = TrustSharedPropertiesHandler(webobj, self.mock_config)
        handler.response = self.mock_response

        # Mock authentication
        mock_auth_result = Mock()
        mock_auth_result.success = True
        mock_actor = Mock()
        mock_auth_result.actor = mock_actor
        mock_auth_result.auth_obj = Mock()
        mock_auth_result.auth_obj.acl = {"peerid": "peer-123"}

        # No trust relationship
        mock_actor.get_trust_relationship = Mock(return_value=None)

        with patch.object(handler, "authenticate_actor", return_value=mock_auth_result):
            handler.get("actor-123", "friend", "peer-123")

            # Should return 404
            assert self.mock_response.set_status.called
            assert self.mock_response.set_status.call_args[0][0] == 404

    def test_requires_permission_system_available(self):
        """Endpoint returns 503 if permission system not available."""
        webobj = Mock()
        webobj.request = Mock()
        handler = TrustSharedPropertiesHandler(webobj, self.mock_config)
        handler.response = self.mock_response

        # Mock authentication
        mock_auth_result = Mock()
        mock_auth_result.success = True
        mock_actor = Mock()
        mock_auth_result.actor = mock_actor
        mock_auth_result.auth_obj = Mock()
        mock_auth_result.auth_obj.acl = {"peerid": "peer-123"}

        # Mock trust relationship
        mock_actor.get_trust_relationship = Mock(return_value={"peerid": "peer-123"})

        with patch.object(handler, "authenticate_actor", return_value=mock_auth_result):
            with patch("actingweb.handlers.trust.get_permission_evaluator") as mock_get_eval:
                mock_get_eval.return_value = None  # No evaluator

                handler.get("actor-123", "friend", "peer-123")

                # Should return 503
                assert self.mock_response.set_status.called
                assert self.mock_response.set_status.call_args[0][0] == 503

    def test_separates_shared_and_excluded_properties(self):
        """Response correctly categorizes properties by permission."""
        webobj = Mock()
        webobj.request = Mock()
        handler = TrustSharedPropertiesHandler(webobj, self.mock_config)
        handler.response = self.mock_response

        # Mock authentication
        mock_auth_result = Mock()
        mock_auth_result.success = True
        mock_actor = Mock()
        mock_actor.id = "actor-123"
        mock_auth_result.actor = mock_actor
        mock_auth_result.auth_obj = Mock()
        mock_auth_result.auth_obj.acl = {"peerid": "peer-123"}

        # Mock trust relationship
        mock_actor.get_trust_relationship = Mock(return_value={"peerid": "peer-123"})

        # Mock multiple properties
        mock_actor.get_properties = Mock(return_value={
            "allowed_prop1": {},
            "allowed_prop2": {},
            "denied_prop1": {},
            "denied_prop2": {},
        })

        with patch.object(handler, "authenticate_actor", return_value=mock_auth_result):
            with patch("actingweb.handlers.trust.get_permission_evaluator") as mock_get_eval:
                mock_evaluator = Mock()
                mock_get_eval.return_value = mock_evaluator

                # Allow props with "allowed", deny others
                def permission_side_effect(actor_id, peer_id, prop_path, operation):
                    if "allowed" in prop_path:
                        return PermissionResult.ALLOWED
                    return PermissionResult.DENIED

                mock_evaluator.evaluate_property_access.side_effect = permission_side_effect

                handler.get("actor-123", "friend", "peer-123")

                # Parse response
                response_json = self.mock_response.write.call_args[0][0]
                response_data = json.loads(response_json)

                # Verify categorization
                shared_names = [p["name"] for p in response_data["shared_properties"]]
                assert "allowed_prop1" in shared_names
                assert "allowed_prop2" in shared_names
                assert len(shared_names) == 2

                excluded_names = response_data["excluded_properties"]
                assert "denied_prop1" in excluded_names
                assert "denied_prop2" in excluded_names
                assert len(excluded_names) == 2
