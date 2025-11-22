"""
Test transparent hook permission checking.

This tests that the hook registry properly checks permissions before executing
hooks, providing transparent access control without requiring developers to
add explicit permission checks in their hook functions.
"""

import tempfile
import unittest
from unittest.mock import Mock, patch

from actingweb.config import Config
from actingweb.interface.hooks import HookRegistry
from actingweb.permission_evaluator import PermissionResult


class TestTransparentHookPermissions(unittest.TestCase):
    """Test transparent permission checking in hook execution."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.config = Config(database="dynamodb", devtest=True)

        self.hook_registry = HookRegistry()
        self.actor_id = "test_actor_123"
        self.peer_id = "test_peer_456"

    def tearDown(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_actor(self, actor_id: str):
        """Create a mock actor for testing."""
        actor = Mock()
        actor.id = actor_id
        actor.actor_id = actor_id
        return actor

    def _create_auth_context(self, peer_id: str):
        """Create auth context for testing."""
        return {"peer_id": peer_id, "config": self.config, "operation": "read"}

    @patch("actingweb.interface.hooks.get_permission_evaluator")
    def test_property_hook_permission_allowed(self, mock_get_evaluator):
        """Test property hook execution when permission is allowed."""
        # Setup mock permission evaluator
        mock_evaluator = Mock()
        mock_evaluator.evaluate_property_access = Mock(
            return_value=PermissionResult.ALLOWED
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Register a test hook
        test_hook = Mock(return_value="transformed_value")
        test_hook._operations = ["get"]  # Set operations attribute for Mock
        self.hook_registry.register_property_hook("test_prop", test_hook)

        # Execute hook with permission
        actor = self._create_mock_actor(self.actor_id)
        auth_context = self._create_auth_context(self.peer_id)

        result = self.hook_registry.execute_property_hooks(
            "test_prop", "get", actor, "original_value", [], auth_context
        )

        # Verify hook was executed
        self.assertEqual(result, "transformed_value")
        test_hook.assert_called_once_with(actor, "get", "original_value", [])
        mock_evaluator.evaluate_property_access.assert_called_once_with(
            self.actor_id, self.peer_id, "test_prop", "read"
        )

    @patch("actingweb.interface.hooks.get_permission_evaluator")
    def test_property_hook_permission_denied(self, mock_get_evaluator):
        """Test property hook execution when permission is denied."""
        # Setup mock permission evaluator to deny access
        mock_evaluator = Mock()
        mock_evaluator.evaluate_property_access = Mock(
            return_value=PermissionResult.DENIED
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Register a test hook
        test_hook = Mock(return_value="transformed_value")
        test_hook._operations = ["get"]  # Set operations attribute for Mock
        self.hook_registry.register_property_hook("secret_prop", test_hook)

        # Execute hook with denied permission
        actor = self._create_mock_actor(self.actor_id)
        auth_context = self._create_auth_context(self.peer_id)

        result = self.hook_registry.execute_property_hooks(
            "secret_prop", "get", actor, "secret_value", [], auth_context
        )

        # Verify hook was NOT executed and original value returned
        self.assertEqual(result, "secret_value")  # Original value returned
        test_hook.assert_not_called()  # Hook should not have been called
        mock_evaluator.evaluate_property_access.assert_called_once()

    @patch("actingweb.interface.hooks.get_permission_evaluator")
    def test_method_hook_permission_allowed(self, mock_get_evaluator):
        """Test method hook execution when permission is allowed."""
        # Setup mock permission evaluator
        mock_evaluator = Mock()
        mock_evaluator.evaluate_method_access = Mock(
            return_value=PermissionResult.ALLOWED
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Register a test hook
        test_hook = Mock(return_value={"result": "success"})
        self.hook_registry.register_method_hook("get_profile", test_hook)

        # Execute hook with permission
        actor = self._create_mock_actor(self.actor_id)
        auth_context = self._create_auth_context(self.peer_id)

        result = self.hook_registry.execute_method_hooks(
            "get_profile", actor, {"param": "value"}, auth_context
        )

        # Verify hook was executed
        self.assertEqual(result, {"result": "success"})
        test_hook.assert_called_once_with(actor, "get_profile", {"param": "value"})
        mock_evaluator.evaluate_method_access.assert_called_once_with(
            self.actor_id, self.peer_id, "get_profile"
        )

    @patch("actingweb.interface.hooks.get_permission_evaluator")
    def test_action_hook_permission_denied(self, mock_get_evaluator):
        """Test action hook execution when permission is denied."""
        # Setup mock permission evaluator to deny access
        mock_evaluator = Mock()
        mock_evaluator.evaluate_action_access = Mock(
            return_value=PermissionResult.DENIED
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Register a test hook
        test_hook = Mock(return_value={"result": "executed"})
        self.hook_registry.register_action_hook("admin_delete", test_hook)

        # Execute hook with denied permission
        actor = self._create_mock_actor(self.actor_id)
        auth_context = self._create_auth_context(self.peer_id)

        result = self.hook_registry.execute_action_hooks(
            "admin_delete", actor, {"target": "item"}, auth_context
        )

        # Verify hook was NOT executed
        self.assertIsNone(result)  # None returned for denied access
        test_hook.assert_not_called()  # Hook should not have been called
        mock_evaluator.evaluate_action_access.assert_called_once()

    def test_hook_execution_without_auth_context(self):
        """Test hook execution without auth context (basic/oauth auth)."""
        # Register a test hook
        test_hook = Mock(return_value="result")
        test_hook._operations = ["get"]  # Set operations attribute for Mock
        self.hook_registry.register_property_hook("public_prop", test_hook)

        # Execute hook without auth context (no peer relationship)
        actor = self._create_mock_actor(self.actor_id)

        result = self.hook_registry.execute_property_hooks(
            "public_prop", "get", actor, "value", []
        )  # No auth_context parameter

        # Verify hook was executed (no permission checking for basic/oauth auth)
        self.assertEqual(result, "result")
        test_hook.assert_called_once()

    def test_hook_execution_no_peer_id(self):
        """Test hook execution when auth context has no peer ID."""
        # Register a test hook
        test_hook = Mock(return_value="result")
        self.hook_registry.register_method_hook("public_method", test_hook)

        # Execute hook with auth context but no peer ID
        actor = self._create_mock_actor(self.actor_id)
        auth_context = {"peer_id": "", "config": self.config}  # Empty peer_id

        result = self.hook_registry.execute_method_hooks(
            "public_method", actor, {}, auth_context
        )

        # Verify hook was executed (no peer relationship = basic/oauth auth)
        self.assertEqual(result, "result")
        test_hook.assert_called_once()

    @patch("actingweb.interface.hooks.get_permission_evaluator")
    def test_hook_permission_error_fallback(self, mock_get_evaluator):
        """Test hook execution falls back to allow on permission evaluator errors."""
        # Setup mock permission evaluator to raise exception
        mock_evaluator = Mock()
        mock_evaluator.evaluate_property_access = Mock(
            side_effect=Exception("Permission error")
        )
        mock_get_evaluator.return_value = mock_evaluator

        # Register a test hook
        test_hook = Mock(return_value="result")
        test_hook._operations = ["get"]  # Set operations attribute for Mock
        self.hook_registry.register_property_hook("test_prop", test_hook)

        # Execute hook with permission evaluator error
        actor = self._create_mock_actor(self.actor_id)
        auth_context = self._create_auth_context(self.peer_id)

        result = self.hook_registry.execute_property_hooks(
            "test_prop", "get", actor, "value", [], auth_context
        )

        # Verify hook was executed (fallback on errors)
        self.assertEqual(result, "result")
        test_hook.assert_called_once()


if __name__ == "__main__":
    unittest.main()
