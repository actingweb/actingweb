"""
Test permission system integration with ActingWeb handlers.

This tests that the unified access control system properly integrates with
the properties, methods, and actions handlers to provide granular permissions.
"""

import tempfile
import unittest
from unittest.mock import Mock, patch

from actingweb.config import Config
from actingweb.handlers.actions import ActionsHandler
from actingweb.handlers.methods import MethodsHandler
from actingweb.handlers.properties import PropertiesHandler
from actingweb.permission_evaluator import PermissionResult


class TestHandlerPermissionIntegration(unittest.TestCase):
    """Test permission system integration with handlers."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        # Use supported Config kwargs; devtest True enables test paths
        self.config = Config(database="dynamodb", devtest=True)

        # Mock actor ID and peer ID for testing
        self.actor_id = "test_actor_123"
        self.peer_id = "test_peer_456"

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_auth_with_peer(self, actor_id: str, peer_id: str):
        """Create mock auth object with peer relationship."""
        auth_obj = Mock()
        auth_obj.acl = Mock()
        auth_obj.acl.peerid = peer_id
        auth_obj.check_authorisation = Mock(return_value=True)  # Legacy fallback
        return auth_obj

    def _create_mock_auth_without_peer(self, actor_id: str):
        """Create mock auth object without peer relationship (basic/oauth auth)."""
        auth_obj = Mock()
        auth_obj.acl = Mock()
        auth_obj.acl.peerid = ""  # No peer relationship
        auth_obj.check_authorisation = Mock(return_value=True)  # Legacy auth
        return auth_obj

    @patch("actingweb.handlers.properties.get_permission_evaluator")
    def test_properties_handler_with_peer_permission(self, mock_get_evaluator):
        """Test properties handler uses permission evaluator for peer access."""
        # Setup mock permission evaluator
        mock_evaluator = Mock()
        mock_evaluator.evaluate_property_access = Mock(
            return_value=PermissionResult.ALLOWED
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Create handler and test permission check
        handler = PropertiesHandler(config=self.config)
        auth_obj = self._create_mock_auth_with_peer(self.actor_id, self.peer_id)

        # Test permission check
        result = handler._check_property_permission(
            self.actor_id, auth_obj, "public/profile", "read"
        )

        # Verify permission evaluator was called
        self.assertTrue(result)
        mock_evaluator.evaluate_property_access.assert_called_once_with(
            self.actor_id, self.peer_id, "public/profile", "read"
        )

    @patch("actingweb.handlers.properties.get_permission_evaluator")
    def test_properties_handler_permission_denied(self, mock_get_evaluator):
        """Test properties handler denies access when permission evaluator returns denied."""
        # Setup mock permission evaluator to deny access
        mock_evaluator = Mock()
        mock_evaluator.evaluate_property_access = Mock(
            return_value=PermissionResult.DENIED
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Create handler and test permission check
        handler = PropertiesHandler(config=self.config)
        auth_obj = self._create_mock_auth_with_peer(self.actor_id, self.peer_id)

        # Test permission check
        result = handler._check_property_permission(
            self.actor_id, auth_obj, "private/secrets", "read"
        )

        # Verify access was denied
        self.assertFalse(result)
        mock_evaluator.evaluate_property_access.assert_called_once()

    def test_properties_handler_fallback_to_legacy(self):
        """Test properties handler falls back to legacy auth when no peer relationship."""
        # Create handler without peer relationship
        handler = PropertiesHandler(config=self.config)
        auth_obj = self._create_mock_auth_without_peer(self.actor_id)

        # Test permission check
        result = handler._check_property_permission(
            self.actor_id, auth_obj, "email", "read"
        )

        # Verify legacy authorization was used
        self.assertTrue(result)
        auth_obj.check_authorisation.assert_called_once_with(
            path="properties", subpath="email", method="GET"
        )

    @patch("actingweb.handlers.methods.get_permission_evaluator")
    def test_methods_handler_with_peer_permission(self, mock_get_evaluator):
        """Test methods handler uses permission evaluator for peer access."""
        # Setup mock permission evaluator
        mock_evaluator = Mock()
        mock_evaluator.evaluate_method_access = Mock(
            return_value=PermissionResult.ALLOWED
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Create handler and test permission check
        handler = MethodsHandler(config=self.config)
        auth_obj = self._create_mock_auth_with_peer(self.actor_id, self.peer_id)

        # Test permission check
        result = handler._check_method_permission(
            self.actor_id, auth_obj, "get_profile"
        )

        # Verify permission evaluator was called
        self.assertTrue(result)
        mock_evaluator.evaluate_method_access.assert_called_once_with(
            self.actor_id, self.peer_id, "get_profile"
        )

    @patch("actingweb.handlers.actions.get_permission_evaluator")
    def test_actions_handler_with_peer_permission(self, mock_get_evaluator):
        """Test actions handler uses permission evaluator for peer access."""
        # Setup mock permission evaluator
        mock_evaluator = Mock()
        mock_evaluator.evaluate_action_access = Mock(
            return_value=PermissionResult.ALLOWED
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Create handler and test permission check
        handler = ActionsHandler(config=self.config)
        auth_obj = self._create_mock_auth_with_peer(self.actor_id, self.peer_id)

        # Test permission check
        result = handler._check_action_permission(
            self.actor_id, auth_obj, "send_message"
        )

        # Verify permission evaluator was called
        self.assertTrue(result)
        mock_evaluator.evaluate_action_access.assert_called_once_with(
            self.actor_id, self.peer_id, "send_message"
        )

    @patch("actingweb.handlers.properties.get_permission_evaluator")
    def test_permission_evaluator_error_fallback(self, mock_get_evaluator):
        """Test handlers fall back to legacy auth on permission evaluator errors."""
        # Setup mock permission evaluator to raise exception
        mock_evaluator = Mock()
        mock_evaluator.evaluate_property_access = Mock(
            side_effect=Exception("Database error")
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Create handler and test permission check
        handler = PropertiesHandler(config=self.config)
        auth_obj = self._create_mock_auth_with_peer(self.actor_id, self.peer_id)

        # Test permission check
        result = handler._check_property_permission(
            self.actor_id, auth_obj, "profile", "read"
        )

        # Verify fallback to legacy authorization
        self.assertTrue(result)  # Legacy auth should allow
        auth_obj.check_authorisation.assert_called_once()

    @patch("actingweb.handlers.properties.get_permission_evaluator")
    def test_not_found_permission_fallback(self, mock_get_evaluator):
        """Test handlers fall back to legacy auth when no permission rule found."""
        # Setup mock permission evaluator to return NOT_FOUND
        mock_evaluator = Mock()
        mock_evaluator.evaluate_property_access = Mock(
            return_value=PermissionResult.NOT_FOUND
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Create handler and test permission check
        handler = PropertiesHandler(config=self.config)
        auth_obj = self._create_mock_auth_with_peer(self.actor_id, self.peer_id)

        # Test permission check
        result = handler._check_property_permission(
            self.actor_id, auth_obj, "unconfigured", "read"
        )

        # Verify fallback to legacy authorization
        self.assertTrue(result)  # Legacy auth should allow
        auth_obj.check_authorisation.assert_called_once()


if __name__ == "__main__":
    unittest.main()
