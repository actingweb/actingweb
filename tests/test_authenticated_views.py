"""
Unit tests for authenticated views and permission enforcement.
"""

from unittest.mock import Mock, patch

import pytest

from actingweb.interface.authenticated_views import (
    AuthContext,
    AuthenticatedActorView,
    AuthenticatedPropertyStore,
    PermissionError,
)
from actingweb.permission_evaluator import PermissionResult


class TestAuthContext:
    """Test AuthContext class."""

    def test_peer_context(self):
        """Test peer authentication context."""
        ctx = AuthContext(
            peer_id="peer123", trust_relationship={"relationship": "friend"}
        )
        assert ctx.peer_id == "peer123"
        assert ctx.accessor_id == "peer123"
        assert ctx.is_peer is True
        assert ctx.is_client is False

    def test_client_context(self):
        """Test client authentication context."""
        ctx = AuthContext(
            client_id="client123", trust_relationship={"client_name": "MCP"}
        )
        assert ctx.client_id == "client123"
        assert ctx.accessor_id == "client123"
        assert ctx.is_peer is False
        assert ctx.is_client is True

    def test_accessor_id_prefers_peer(self):
        """Test that accessor_id returns peer_id when both are present."""
        ctx = AuthContext(peer_id="peer123", client_id="client123")
        assert ctx.accessor_id == "peer123"


class TestAuthenticatedActorView:
    """Test AuthenticatedActorView creation."""

    def test_as_peer_creates_authenticated_view(self):
        """Test actor.as_peer() creates an authenticated view."""
        mock_actor = Mock()
        mock_actor.id = "actor123"
        mock_actor.creator = "user@example.com"
        mock_actor.url = "https://example.com/actor123"
        mock_actor._core_actor = Mock()
        mock_actor._core_actor.config = None

        from actingweb.interface.actor_interface import ActorInterface

        # Mock the ActorInterface
        with patch.object(ActorInterface, "__init__", return_value=None):
            actor_interface = Mock(spec=ActorInterface)
            actor_interface.id = "actor123"
            actor_interface.creator = "user@example.com"
            actor_interface.url = "https://example.com/actor123"
            actor_interface._core_actor = mock_actor._core_actor
            actor_interface.properties = Mock()
            actor_interface.property_lists = Mock()
            actor_interface.subscriptions = Mock()
            actor_interface.trust = Mock()

            # Create authenticated view
            auth_view = AuthenticatedActorView(
                actor_interface,
                AuthContext(peer_id="peer123"),
                hooks=None,
            )

            assert auth_view.id == "actor123"
            assert auth_view.auth_context.peer_id == "peer123"
            assert auth_view.auth_context.is_peer is True

    def test_as_client_creates_authenticated_view(self):
        """Test actor.as_client() creates an authenticated view."""
        mock_actor = Mock()
        mock_actor.id = "actor123"
        mock_actor.creator = "user@example.com"
        mock_actor.url = "https://example.com/actor123"
        mock_actor._core_actor = Mock()
        mock_actor._core_actor.config = None

        from actingweb.interface.actor_interface import ActorInterface

        with patch.object(ActorInterface, "__init__", return_value=None):
            actor_interface = Mock(spec=ActorInterface)
            actor_interface.id = "actor123"
            actor_interface._core_actor = mock_actor._core_actor
            actor_interface.properties = Mock()
            actor_interface.property_lists = Mock()
            actor_interface.subscriptions = Mock()
            actor_interface.trust = Mock()

            auth_view = AuthenticatedActorView(
                actor_interface,
                AuthContext(client_id="mcp_client_123"),
                hooks=None,
            )

            assert auth_view.id == "actor123"
            assert auth_view.auth_context.client_id == "mcp_client_123"
            assert auth_view.auth_context.is_client is True

    def test_auth_context_accessor_id_returns_peer_or_client(self):
        """Test auth_context.accessor_id returns correct identifier."""
        mock_actor = Mock()
        mock_actor._core_actor = Mock()
        mock_actor._core_actor.config = None

        from actingweb.interface.actor_interface import ActorInterface

        with patch.object(ActorInterface, "__init__", return_value=None):
            actor_interface = Mock(spec=ActorInterface)
            actor_interface._core_actor = mock_actor._core_actor
            actor_interface.properties = Mock()

            # Peer access
            peer_view = AuthenticatedActorView(
                actor_interface,
                AuthContext(peer_id="peer123"),
                hooks=None,
            )
            assert peer_view.auth_context.accessor_id == "peer123"

            # Client access
            client_view = AuthenticatedActorView(
                actor_interface,
                AuthContext(client_id="client123"),
                hooks=None,
            )
            assert client_view.auth_context.accessor_id == "client123"

    def test_auth_context_is_peer_and_is_client_properties(self):
        """Test auth_context.is_peer and is_client properties."""
        mock_actor = Mock()
        mock_actor._core_actor = Mock()
        mock_actor._core_actor.config = None

        from actingweb.interface.actor_interface import ActorInterface

        with patch.object(ActorInterface, "__init__", return_value=None):
            actor_interface = Mock(spec=ActorInterface)
            actor_interface._core_actor = mock_actor._core_actor
            actor_interface.properties = Mock()

            peer_view = AuthenticatedActorView(
                actor_interface,
                AuthContext(peer_id="peer123"),
                hooks=None,
            )
            assert peer_view.auth_context.is_peer is True
            assert peer_view.auth_context.is_client is False

            client_view = AuthenticatedActorView(
                actor_interface,
                AuthContext(client_id="client123"),
                hooks=None,
            )
            assert client_view.auth_context.is_peer is False
            assert client_view.auth_context.is_client is True


class TestAuthenticatedPropertyStore:
    """Test AuthenticatedPropertyStore permission enforcement."""

    def test_authenticated_property_read_checks_permission(self):
        """Test that reading a property checks permission."""
        mock_store = Mock()
        mock_store.__getitem__ = Mock(return_value="value")

        auth_context = AuthContext(peer_id="peer123")
        mock_config = Mock()  # Provide a config so permission checking is enabled

        with patch(
            "actingweb.interface.authenticated_views.get_permission_evaluator"
        ) as mock_get_evaluator:
            mock_evaluator = Mock()
            mock_evaluator.evaluate_property_access = Mock(
                return_value=PermissionResult.ALLOWED
            )
            mock_get_evaluator.return_value = mock_evaluator

            auth_store = AuthenticatedPropertyStore(
                mock_store, auth_context, "actor123", mock_config
            )
            result = auth_store["test_key"]

            # Verify permission was checked
            mock_evaluator.evaluate_property_access.assert_called_once_with(
                "actor123", "peer123", "test_key", "read"
            )
            assert result == "value"

    def test_authenticated_property_write_checks_permission(self):
        """Test that writing a property checks permission."""
        mock_store = Mock()
        mock_store.__setitem__ = Mock()

        auth_context = AuthContext(peer_id="peer123")
        mock_config = Mock()

        with patch(
            "actingweb.interface.authenticated_views.get_permission_evaluator"
        ) as mock_get_evaluator:
            mock_evaluator = Mock()
            mock_evaluator.evaluate_property_access = Mock(
                return_value=PermissionResult.ALLOWED
            )
            mock_get_evaluator.return_value = mock_evaluator

            auth_store = AuthenticatedPropertyStore(
                mock_store, auth_context, "actor123", mock_config
            )
            auth_store["test_key"] = "new_value"

            # Verify permission was checked
            mock_evaluator.evaluate_property_access.assert_called_once_with(
                "actor123", "peer123", "test_key", "write"
            )
            mock_store.__setitem__.assert_called_once_with("test_key", "new_value")

    def test_authenticated_property_delete_checks_permission(self):
        """Test that deleting a property checks permission."""
        mock_store = Mock()
        mock_store.__delitem__ = Mock()

        auth_context = AuthContext(peer_id="peer123")
        mock_config = Mock()

        with patch(
            "actingweb.interface.authenticated_views.get_permission_evaluator"
        ) as mock_get_evaluator:
            mock_evaluator = Mock()
            mock_evaluator.evaluate_property_access = Mock(
                return_value=PermissionResult.ALLOWED
            )
            mock_get_evaluator.return_value = mock_evaluator

            auth_store = AuthenticatedPropertyStore(
                mock_store, auth_context, "actor123", mock_config
            )
            del auth_store["test_key"]

            # Verify permission was checked
            mock_evaluator.evaluate_property_access.assert_called_once_with(
                "actor123", "peer123", "test_key", "delete"
            )
            mock_store.__delitem__.assert_called_once_with("test_key")

    def test_permission_error_raised_when_denied(self):
        """Test that PermissionError is raised when access is denied."""
        mock_store = Mock()

        auth_context = AuthContext(peer_id="peer123")
        mock_config = Mock()

        with patch(
            "actingweb.interface.authenticated_views.get_permission_evaluator"
        ) as mock_get_evaluator:
            mock_evaluator = Mock()
            mock_evaluator.evaluate_property_access = Mock(
                return_value=PermissionResult.DENIED
            )
            mock_get_evaluator.return_value = mock_evaluator

            auth_store = AuthenticatedPropertyStore(
                mock_store, auth_context, "actor123", mock_config
            )

            with pytest.raises(PermissionError):
                _ = auth_store["test_key"]

    def test_owner_mode_has_no_permission_checks(self):
        """Test that owner mode (no accessor_id) allows all access."""
        mock_store = Mock()
        mock_store.__getitem__ = Mock(return_value="value")
        mock_store.__setitem__ = Mock()

        # No accessor_id = owner mode
        auth_context = AuthContext()

        with patch(
            "actingweb.interface.authenticated_views.get_permission_evaluator"
        ) as mock_get_evaluator:
            mock_evaluator = Mock()
            mock_get_evaluator.return_value = mock_evaluator

            auth_store = AuthenticatedPropertyStore(
                mock_store, auth_context, "actor123", None
            )

            # Read and write should work without permission checks
            _ = auth_store["test_key"]  # Just verify no error
            auth_store["test_key"] = "new_value"

            # Evaluator should not be called
            mock_evaluator.evaluate_property_access.assert_not_called()

    def test_authenticated_view_filters_iterable_properties(self):
        """Test that __iter__ filters properties to accessible ones."""
        mock_store = Mock()
        mock_store.__iter__ = Mock(
            return_value=iter(["public_key", "private_key", "config"])
        )

        auth_context = AuthContext(peer_id="peer123")
        mock_config = Mock()

        with patch(
            "actingweb.interface.authenticated_views.get_permission_evaluator"
        ) as mock_get_evaluator:
            mock_evaluator = Mock()

            # Allow public_key and config, deny private_key
            def evaluate_side_effect(actor_id, accessor_id, key, operation):
                if key == "private_key":
                    return PermissionResult.DENIED
                return PermissionResult.ALLOWED

            mock_evaluator.evaluate_property_access = Mock(
                side_effect=evaluate_side_effect
            )
            mock_get_evaluator.return_value = mock_evaluator

            auth_store = AuthenticatedPropertyStore(
                mock_store, auth_context, "actor123", mock_config
            )

            accessible_keys = list(auth_store)

            # Should only include accessible keys
            assert "public_key" in accessible_keys
            assert "config" in accessible_keys
            assert "private_key" not in accessible_keys
