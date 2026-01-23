"""
Integration tests for auto-delete on permission revocation.

Tests the complete flow of:
1. Storing peer data in RemotePeerStore
2. Receiving permission callback with revoked patterns
3. Verifying cached data is deleted when auto_delete_on_revocation=True
"""

import json
from unittest.mock import Mock, patch

import pytest


class TestPermissionRevocationIntegration:
    """Test auto-delete on permission revocation integration."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config with auto_delete_on_revocation enabled."""
        config = Mock()
        config.database = "dynamodb"
        config.peer_permissions_caching = True
        config.auto_delete_on_revocation = True
        config.root = "https://test.example.com/"
        return config

    @pytest.fixture
    def mock_config_disabled(self):
        """Create mock config with auto_delete_on_revocation disabled."""
        config = Mock()
        config.database = "dynamodb"
        config.peer_permissions_caching = True
        config.auto_delete_on_revocation = False
        config.root = "https://test.example.com/"
        return config

    @pytest.fixture
    def mock_actor_interface(self, mock_config):
        """Create mock ActorInterface."""
        actor = Mock()
        actor.id = "test_actor_123"
        actor.config = mock_config
        return actor

    def test_detect_revoked_patterns_identifies_removals(self):
        """Test that detect_revoked_property_patterns correctly identifies revoked patterns."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_revoked_property_patterns,
        )

        old_perms = PeerPermissions(
            actor_id="actor1",
            peer_id="peer1",
            properties={
                "patterns": ["memory_*", "profile_*", "settings_*"],
                "operations": ["read"],
            },
        )

        new_perms = PeerPermissions(
            actor_id="actor1",
            peer_id="peer1",
            properties={
                "patterns": ["memory_*"],  # profile_* and settings_* revoked
                "operations": ["read"],
            },
        )

        revoked = detect_revoked_property_patterns(old_perms, new_perms)

        assert set(revoked) == {"profile_*", "settings_*"}

    def test_detect_permission_changes_full_analysis(self):
        """Test that detect_permission_changes provides complete change info."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_permission_changes,
        )

        old_perms = PeerPermissions(
            actor_id="actor1",
            peer_id="peer1",
            properties={
                "patterns": ["memory_*", "settings_*"],
                "operations": ["read"],
            },
        )

        new_perms = PeerPermissions(
            actor_id="actor1",
            peer_id="peer1",
            properties={
                "patterns": ["memory_*", "profile_*"],  # settings revoked, profile added
                "operations": ["read"],
            },
        )

        changes = detect_permission_changes(old_perms, new_perms)

        assert changes["is_initial"] is False
        assert changes["has_revocations"] is True
        assert changes["revoked_patterns"] == ["settings_*"]
        assert changes["granted_patterns"] == ["profile_*"]

    def test_initial_permission_callback_no_revocations(self):
        """Test that initial callback (no old permissions) has no revocations."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_permission_changes,
        )

        new_perms = PeerPermissions(
            actor_id="actor1",
            peer_id="peer1",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
        )

        changes = detect_permission_changes(None, new_perms)

        assert changes["is_initial"] is True
        assert changes["has_revocations"] is False
        assert changes["revoked_patterns"] == []
        assert changes["granted_patterns"] == ["memory_*"]

    @patch("actingweb.remote_storage.RemotePeerStore")
    def test_callback_handler_deletes_data_on_revocation(
        self, mock_store_class, mock_config
    ):
        """Test that callback handler deletes data when permissions are revoked."""
        from actingweb.handlers.callbacks import CallbacksHandler

        # Setup mock RemotePeerStore
        mock_store = Mock()
        mock_store.list_all_lists.return_value = [
            "memory_travel",
            "memory_work",
            "profile_info",
            "settings_prefs",
        ]
        mock_store_class.return_value = mock_store

        # Setup mock actor interface
        mock_actor_interface = Mock()
        mock_actor_interface.id = "test_actor_123"

        # Create handler and call _delete_revoked_peer_data
        handler = CallbacksHandler(config=mock_config)
        handler._delete_revoked_peer_data(
            actor_interface=mock_actor_interface,
            peer_id="peer123",
            revoked_patterns=["profile_*", "settings_*"],
        )

        # Verify deletion was called for matching lists
        assert mock_store.delete_list.call_count == 2
        deleted_lists = [call[0][0] for call in mock_store.delete_list.call_args_list]
        assert "profile_info" in deleted_lists
        assert "settings_prefs" in deleted_lists

    @patch("actingweb.remote_storage.RemotePeerStore")
    def test_callback_handler_does_not_delete_non_matching(
        self, mock_store_class, mock_config
    ):
        """Test that non-matching lists are not deleted."""
        from actingweb.handlers.callbacks import CallbacksHandler

        # Setup mock RemotePeerStore
        mock_store = Mock()
        mock_store.list_all_lists.return_value = [
            "memory_travel",
            "memory_work",
            "other_data",
        ]
        mock_store_class.return_value = mock_store

        # Setup mock actor interface
        mock_actor_interface = Mock()
        mock_actor_interface.id = "test_actor_123"

        # Create handler and call with pattern that doesn't match any list
        handler = CallbacksHandler(config=mock_config)
        handler._delete_revoked_peer_data(
            actor_interface=mock_actor_interface,
            peer_id="peer123",
            revoked_patterns=["profile_*"],  # No profile_* lists exist
        )

        # Verify no deletion was called
        mock_store.delete_list.assert_not_called()

    @patch("actingweb.remote_storage.RemotePeerStore")
    def test_callback_handler_empty_patterns_no_deletion(
        self, mock_store_class, mock_config
    ):
        """Test that empty revoked patterns does not trigger deletion."""
        from actingweb.handlers.callbacks import CallbacksHandler

        mock_store = Mock()
        mock_store_class.return_value = mock_store

        mock_actor_interface = Mock()
        mock_actor_interface.id = "test_actor_123"

        handler = CallbacksHandler(config=mock_config)
        handler._delete_revoked_peer_data(
            actor_interface=mock_actor_interface,
            peer_id="peer123",
            revoked_patterns=[],
        )

        # Verify store was never instantiated (early return)
        mock_store_class.assert_not_called()


class TestPermissionCallbackHandler:
    """Test permission callback handler with full flow."""

    def test_permission_changes_structure(self):
        """Test that permission_changes dict has expected structure."""
        from actingweb.peer_permissions import (
            PeerPermissions,
            detect_permission_changes,
        )

        # Setup old permissions
        old_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*", "profile_*"],
                "operations": ["read"],
            },
            fetched_at="2026-01-22T10:00:00Z",
        )

        # Setup new permissions with profile_* revoked
        new_perms = PeerPermissions(
            actor_id="actor123",
            peer_id="peer456",
            properties={
                "patterns": ["memory_*"],
                "operations": ["read"],
            },
            fetched_at="2026-01-23T10:00:00Z",
        )

        # Detect changes - this is what the callback handler does
        changes = detect_permission_changes(old_perms, new_perms)

        # Verify structure matches what callback hooks expect
        assert "is_initial" in changes
        assert "has_revocations" in changes
        assert "revoked_patterns" in changes
        assert "granted_patterns" in changes

        # Verify values
        assert changes["is_initial"] is False
        assert changes["has_revocations"] is True
        assert changes["revoked_patterns"] == ["profile_*"]
        assert changes["granted_patterns"] == []


class TestActingWebAppConfiguration:
    """Test ActingWebApp configuration for auto_delete_on_revocation."""

    def test_with_peer_permissions_default_auto_delete_false(self):
        """Test that auto_delete_on_revocation defaults to False."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions(enable=True)

        assert app._peer_permissions_caching is True
        assert app._auto_delete_on_revocation is False

    def test_with_peer_permissions_auto_delete_enabled(self):
        """Test enabling auto_delete_on_revocation."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions(enable=True, auto_delete_on_revocation=True)

        assert app._peer_permissions_caching is True
        assert app._auto_delete_on_revocation is True

    def test_config_propagation(self):
        """Test that settings are propagated to Config object."""
        from actingweb.interface.app import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            fqdn="test.example.com",
        ).with_peer_permissions(enable=True, auto_delete_on_revocation=True)

        config = app.get_config()

        assert config.peer_permissions_caching is True
        assert config.auto_delete_on_revocation is True


class TestGlobPatternMatching:
    """Test that glob pattern matching works correctly for deletion."""

    def test_wildcard_matching(self):
        """Test that fnmatch works for wildcard patterns."""
        import fnmatch

        # Test cases for pattern matching
        assert fnmatch.fnmatch("memory_travel", "memory_*") is True
        assert fnmatch.fnmatch("memory_work", "memory_*") is True
        assert fnmatch.fnmatch("profile_info", "memory_*") is False
        assert fnmatch.fnmatch("profile_info", "profile_*") is True
        assert fnmatch.fnmatch("settings_prefs", "*_prefs") is True
        assert fnmatch.fnmatch("any_data", "*") is True

    def test_exact_matching(self):
        """Test exact pattern matching."""
        import fnmatch

        assert fnmatch.fnmatch("memory_travel", "memory_travel") is True
        assert fnmatch.fnmatch("memory_travel", "memory_work") is False

    def test_question_mark_matching(self):
        """Test single character wildcard matching."""
        import fnmatch

        assert fnmatch.fnmatch("item1", "item?") is True
        assert fnmatch.fnmatch("item12", "item?") is False
