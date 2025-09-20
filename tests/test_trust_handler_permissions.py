"""
Tests for trust handler permission management functionality.

This test suite verifies that the trust handler properly supports
per-relationship permission management as specified in the ActingWeb spec.
"""

import json
import unittest
from unittest.mock import Mock, patch, MagicMock

from actingweb.handlers.trust import TrustPeerHandler, TrustPermissionHandler
from actingweb.trust_permissions import TrustPermissions


class TestTrustHandlerPermissions(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures."""
        self.config = Mock()
        self.request = Mock()
        self.response = Mock()
        self.response.headers = {}

        # Mock request body
        self.request.body = json.dumps({
            "properties": {"allowed": ["public/*"], "denied": ["private/*"]},
            "methods": {"allowed": ["get_profile"]},
            "notes": "Test permission override"
        }).encode('utf-8')

        # Mock auth response
        self.auth_response = Mock()
        self.auth_response.response = {"code": 200}
        self.auth_response.check_authorisation = Mock(return_value=True)
        self.auth_response.trust = None  # Add trust attribute

        # Mock actor
        self.actor = Mock()
        self.actor.get_trust_relationships = Mock(return_value=[{
            "peerid": "test-peer",
            "relationship": "friend",
            "approved": True,
            "verified": True
        }])
        self.actor.modify_trust_and_notify = Mock(return_value=True)

        # Mock permission store
        self.permission_store = Mock()
        self.permission_store.get_permissions = Mock()
        self.permission_store.store_permissions = Mock(return_value=True)
        self.permission_store.update_permissions = Mock(return_value=True)
        self.permission_store.delete_permissions = Mock(return_value=True)

    def _mock_authentication(self, handler):
        """Helper method to mock authentication for handlers."""
        auth_result = Mock()
        auth_result.success = True
        auth_result.actor = self.actor
        auth_result.auth_obj = self.auth_response

        # Mock both possible authentication methods
        handler.authenticate_actor = Mock(return_value=auth_result)
        handler.require_authenticated_actor = Mock(return_value=self.actor)
        return auth_result

    @patch('actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE', True)
    @patch('actingweb.handlers.trust.get_trust_permission_store')
    @patch('actingweb.handlers.trust.trust.Trust')
    def test_get_trust_with_permissions_query(self, mock_trust, mock_get_store):
        """Test GET /trust/{relationship}/{peerid}?permissions=true"""
        mock_get_store.return_value = self.permission_store

        # Create test permissions
        test_permissions = TrustPermissions(
            actor_id="test-actor",
            peer_id="test-peer",
            trust_type="friend",
            properties={"allowed": ["public/*"]},
            methods={"allowed": ["get_profile"]},
            notes="Test permissions"
        )
        self.permission_store.get_permissions.return_value = test_permissions

        handler = TrustPeerHandler()
        handler.config = self.config
        handler.request = Mock()
        handler.request.get = Mock(side_effect=lambda key: "true" if key == "permissions" else None)
        handler.response = self.response

        # Mock authentication
        self._mock_authentication(handler)

        handler.get("test-actor", "friend", "test-peer")

        # Verify response includes permission data
        self.response.write.assert_called_once()
        response_data = json.loads(self.response.write.call_args[0][0])
        self.assertIn("permissions", response_data)
        self.assertEqual(response_data["permissions"]["properties"], {"allowed": ["public/*"]})
        self.assertEqual(response_data["permissions"]["methods"], {"allowed": ["get_profile"]})
        self.assertEqual(response_data["permissions"]["notes"], "Test permissions")

    @patch('actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE', True)
    @patch('actingweb.handlers.trust.get_trust_permission_store')
    @patch('actingweb.handlers.trust.create_permission_override')
    def test_put_trust_with_permissions(self, mock_create_override, mock_get_store):
        """Test PUT /trust/{relationship}/{peerid} with permission updates"""
        mock_get_store.return_value = self.permission_store

        # No existing permissions
        self.permission_store.get_permissions.return_value = None

        # Mock permission creation
        mock_permissions = Mock()
        mock_create_override.return_value = mock_permissions

        handler = TrustPeerHandler()
        handler.config = self.config
        handler.request = self.request
        handler.response = self.response

        # Mock authentication
        self._mock_authentication(handler)

        # Mock request body with permissions
        handler.request.body = json.dumps({
            "approved": True,
            "desc": "Test relationship",
            "permissions": {
                "properties": {"allowed": ["public/*"], "denied": ["private/*"]},
                "methods": {"allowed": ["get_profile"]}
            }
        }).encode('utf-8')

        handler.put("test-actor", "friend", "test-peer")

        # Verify trust update and permission creation
        self.actor.modify_trust_and_notify.assert_called_once()
        mock_create_override.assert_called_once_with(
            actor_id="test-actor",
            peer_id="test-peer",
            trust_type="friend",
            permission_updates={
                "properties": {"allowed": ["public/*"], "denied": ["private/*"]},
                "methods": {"allowed": ["get_profile"]}
            }
        )
        self.permission_store.store_permissions.assert_called_once_with(mock_permissions)

    @patch('actingweb.handlers.trust.PERMISSION_SYSTEM_AVAILABLE', True)
    @patch('actingweb.handlers.trust.get_trust_permission_store')
    def test_get_trust_permissions_handler(self, mock_get_store):
        """Test GET /trust/{relationship}/{peerid}/permissions"""
        mock_get_store.return_value = self.permission_store

        # Mock existing permissions
        test_permissions = TrustPermissions(
            actor_id="test-actor",
            peer_id="test-peer",
            trust_type="friend",
            properties={"allowed": ["public/*"]},
            methods={"allowed": ["get_profile"]},
            notes="Test permissions"
        )
        self.permission_store.get_permissions.return_value = test_permissions

        handler = TrustPermissionHandler()
        handler.config = self.config
        handler.request = Mock()
        handler.response = self.response

        # Mock authentication
        self._mock_authentication(handler)

        handler.get("test-actor", "friend", "test-peer")

        # Verify response
        self.response.write.assert_called_once()
        response_data = json.loads(self.response.write.call_args[0][0])

        self.assertEqual(response_data["actor_id"], "test-actor")
        self.assertEqual(response_data["peer_id"], "test-peer")
        self.assertEqual(response_data["trust_type"], "friend")
        self.assertEqual(response_data["properties"], {"allowed": ["public/*"]})
        self.assertEqual(response_data["methods"], {"allowed": ["get_profile"]})
        self.assertEqual(response_data["notes"], "Test permissions")


if __name__ == '__main__':
    unittest.main()