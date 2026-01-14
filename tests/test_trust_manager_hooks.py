"""
Unit tests for TrustManager lifecycle hook execution.
"""

from unittest.mock import Mock

from actingweb.interface.trust_manager import TrustManager


class TestTrustManagerHooks:
    """Test TrustManager lifecycle hook execution."""

    def test_approve_relationship_triggers_trust_approved_hook(self):
        """Test that approve_relationship triggers trust_approved hook when both approve."""
        mock_actor = Mock()
        mock_hooks = Mock()

        # Mock get_relationship to return a relationship
        relationship_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "approved": False,
            "peer_approved": True,
        }
        mock_actor.get_trust_relationship = Mock(return_value=relationship_data)

        # After approval, both should be approved
        approved_relationship = {
            "peerid": "peer123",
            "relationship": "friend",
            "approved": True,
            "peer_approved": True,
        }

        # Mock modify_trust_and_notify to succeed
        mock_actor.modify_trust_and_notify = Mock(return_value=True)

        manager = TrustManager(mock_actor, hooks=mock_hooks)

        # Mock get_relationship to return approved state after modification
        def get_relationship_side_effect(peerid):
            return approved_relationship

        mock_actor.get_trust_relationship = Mock(
            side_effect=get_relationship_side_effect
        )

        result = manager.approve_relationship("peer123")

        assert result is True
        # Verify lifecycle hook was called
        mock_hooks.execute_lifecycle_hooks.assert_called_once()
        call_args = mock_hooks.execute_lifecycle_hooks.call_args
        assert call_args[0][0] == "trust_approved"
        assert call_args[1]["peer_id"] == "peer123"
        assert call_args[1]["relationship"] == "friend"

    def test_approve_relationship_hook_only_fires_when_both_approved(self):
        """Test that hook only fires when both sides have approved."""
        mock_actor = Mock()
        mock_hooks = Mock()

        # Relationship where peer hasn't approved yet
        relationship_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "approved": False,
            "peer_approved": False,
        }
        mock_actor.get_trust_relationship = Mock(return_value=relationship_data)

        # After our approval, only we approved (peer still hasn't)
        partially_approved = {
            "peerid": "peer123",
            "relationship": "friend",
            "approved": True,
            "peer_approved": False,  # Peer hasn't approved
        }

        mock_actor.modify_trust_and_notify = Mock(return_value=True)

        manager = TrustManager(mock_actor, hooks=mock_hooks)

        # Mock to return partially approved state
        mock_actor.get_trust_relationship = Mock(return_value=partially_approved)

        result = manager.approve_relationship("peer123")

        assert result is True
        # Hook should NOT be called since peer hasn't approved
        mock_hooks.execute_lifecycle_hooks.assert_not_called()

    def test_delete_relationship_triggers_trust_deleted_hook(self):
        """Test that delete_relationship triggers trust_deleted hook."""
        mock_actor = Mock()
        mock_hooks = Mock()

        # Mock existing relationship
        relationship_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "approved": True,
            "peer_approved": True,
        }
        mock_actor.get_trust_relationship = Mock(return_value=relationship_data)
        mock_actor.delete_reciprocal_trust = Mock(return_value=True)

        manager = TrustManager(mock_actor, hooks=mock_hooks)
        result = manager.delete_relationship("peer123")

        assert result is True
        # Verify lifecycle hook was called
        mock_hooks.execute_lifecycle_hooks.assert_called_once()
        call_args = mock_hooks.execute_lifecycle_hooks.call_args
        assert call_args[0][0] == "trust_deleted"
        assert call_args[1]["peer_id"] == "peer123"
        assert call_args[1]["relationship"] == "friend"

    def test_delete_relationship_hook_fires_before_deletion(self):
        """Test that hook is called before the actual deletion."""
        mock_actor = Mock()
        mock_hooks = Mock()

        relationship_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "approved": True,
            "peer_approved": True,
        }
        mock_actor.get_trust_relationship = Mock(return_value=relationship_data)

        # Track call order
        call_order = []

        def hook_side_effect(*args, **kwargs):
            call_order.append("hook")

        def delete_side_effect(*args, **kwargs):
            call_order.append("delete")
            return True

        mock_hooks.execute_lifecycle_hooks = Mock(side_effect=hook_side_effect)
        mock_actor.delete_reciprocal_trust = Mock(side_effect=delete_side_effect)

        manager = TrustManager(mock_actor, hooks=mock_hooks)
        manager.delete_relationship("peer123")

        # Hook should be called before deletion
        assert call_order == ["hook", "delete"]

    def test_hooks_not_called_when_no_hook_registry(self):
        """Test that operations work without hook registry."""
        mock_actor = Mock()

        relationship_data = {
            "peerid": "peer123",
            "relationship": "friend",
            "approved": False,
            "peer_approved": True,
        }
        mock_actor.get_trust_relationship = Mock(return_value=relationship_data)
        mock_actor.modify_trust_and_notify = Mock(return_value=True)

        # Create manager WITHOUT hooks
        manager = TrustManager(mock_actor, hooks=None)

        # Should work without errors
        result = manager.approve_relationship("peer123")
        assert result is True

    def test_lifecycle_hook_receives_correct_parameters(self):
        """Test that lifecycle hooks receive all required parameters."""
        mock_actor = Mock()
        mock_hooks = Mock()

        relationship_data = {
            "peerid": "peer123",
            "relationship": "collaborator",
            "approved": True,
            "peer_approved": True,
        }
        mock_actor.get_trust_relationship = Mock(return_value=relationship_data)
        mock_actor.delete_reciprocal_trust = Mock(return_value=True)

        manager = TrustManager(mock_actor, hooks=mock_hooks)
        manager.delete_relationship("peer123")

        # Verify hook parameters
        mock_hooks.execute_lifecycle_hooks.assert_called_once()
        call_args = mock_hooks.execute_lifecycle_hooks.call_args

        # Positional args
        assert call_args[0][0] == "trust_deleted"

        # Keyword args
        assert "actor" in call_args[1]
        assert call_args[1]["peer_id"] == "peer123"
        assert call_args[1]["relationship"] == "collaborator"
