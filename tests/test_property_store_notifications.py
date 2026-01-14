"""
Unit tests for PropertyStore notification (register_diffs) functionality.
"""

from unittest.mock import Mock, patch

from actingweb.interface.property_store import PropertyStore


class TestPropertyStoreNotifications:
    """Test PropertyStore calls register_diffs on mutations."""

    def test_setitem_calls_register_diffs(self):
        """Test that __setitem__ calls register_diffs."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=None, config=None
        )
        store["test_key"] = "test_value"

        # Verify register_diffs was called
        mock_actor.register_diffs.assert_called_once()
        call_args = mock_actor.register_diffs.call_args
        assert call_args[1]["target"] == "properties"
        assert call_args[1]["subtarget"] == "test_key"
        assert '"test_value"' in call_args[1]["blob"]  # JSON-encoded value

    def test_delitem_calls_register_diffs(self):
        """Test that __delitem__ calls register_diffs."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=None, config=None
        )
        del store["test_key"]

        # Verify register_diffs was called with JSON-encoded empty string (deletion)
        mock_actor.register_diffs.assert_called_once()
        call_args = mock_actor.register_diffs.call_args
        assert call_args[1]["target"] == "properties"
        assert call_args[1]["subtarget"] == "test_key"
        assert call_args[1]["blob"] == '""'  # JSON-encoded empty string

    def test_set_calls_register_diffs(self):
        """Test that set() method calls register_diffs."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=None, config=None
        )
        store.set("test_key", "test_value")

        # Verify register_diffs was called
        mock_actor.register_diffs.assert_called_once()

    def test_delete_calls_register_diffs(self):
        """Test that delete() method calls register_diffs."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_core_store.__getitem__ = Mock(return_value="existing_value")
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=None, config=None
        )

        # Mock __contains__ to return True
        with patch.object(store, "__contains__", return_value=True):
            result = store.delete("test_key")

        assert result is True
        # Verify register_diffs was called
        mock_actor.register_diffs.assert_called_once()

    def test_update_calls_register_diffs_for_each_key(self):
        """Test that update() calls register_diffs for each key."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=None, config=None
        )
        store.update({"key1": "value1", "key2": "value2"})

        # Verify register_diffs was called twice (once per key)
        assert mock_actor.register_diffs.call_count == 2

    def test_clear_calls_register_diffs(self):
        """Test that clear() calls register_diffs."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_core_store.get_all = Mock(
            return_value={"key1": "value1", "key2": "value2"}
        )
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=None, config=None
        )
        store.clear()

        # Should call register_diffs for each key + one for "clear all"
        assert mock_actor.register_diffs.call_count >= 2

    def test_set_without_notification_does_not_register_diff(self):
        """Test that set_without_notification doesn't call register_diffs."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=None, config=None
        )
        store.set_without_notification("test_key", "test_value")

        # Verify register_diffs was NOT called
        mock_actor.register_diffs.assert_not_called()

        # But value was stored
        mock_core_store.__setitem__.assert_called_once_with("test_key", "test_value")

    def test_hook_executed_before_store(self):
        """Test that property hooks are executed before storing."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()
        mock_hooks = Mock()

        # Mock hook execution to return transformed value
        mock_hooks.execute_property_hooks = Mock(return_value="transformed_value")

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=mock_hooks, config=None
        )
        store["test_key"] = "original_value"

        # Verify hook was called before storage
        mock_hooks.execute_property_hooks.assert_called_once()
        call_args = mock_hooks.execute_property_hooks.call_args
        assert call_args[0][0] == "test_key"  # key
        assert call_args[0][1] == "put"  # operation
        # The actor interface is created dynamically
        assert call_args[0][3] == "original_value"  # value
        assert call_args[0][4] == ["test_key"]  # path

        # Verify transformed value was stored
        mock_core_store.__setitem__.assert_called_once_with(
            "test_key", "transformed_value"
        )

    def test_hook_can_transform_value(self):
        """Test that hooks can transform values before storage."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()
        mock_hooks = Mock()

        # Hook transforms value to uppercase
        def transform_hook(key, operation, actor, value, path):
            return value.upper() if isinstance(value, str) else value

        mock_hooks.execute_property_hooks = Mock(side_effect=transform_hook)

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=mock_hooks, config=None
        )
        store["test_key"] = "lowercase"

        # Verify uppercase value was stored
        mock_core_store.__setitem__.assert_called_once_with("test_key", "LOWERCASE")

    def test_hook_can_reject_value_returning_none(self):
        """Test that hooks returning None still store original value (None rejection not implemented)."""
        mock_core_store = Mock()
        mock_core_store.__setitem__ = Mock()
        mock_actor = Mock()
        mock_actor.register_diffs = Mock()
        mock_hooks = Mock()

        # Hook returns None (should store original value per current implementation)
        mock_hooks.execute_property_hooks = Mock(return_value=None)

        store = PropertyStore(
            mock_core_store, actor=mock_actor, hooks=mock_hooks, config=None
        )
        store["test_key"] = "original_value"

        # Current implementation stores original value when hook returns None
        mock_core_store.__setitem__.assert_called_once_with(
            "test_key", "original_value"
        )
