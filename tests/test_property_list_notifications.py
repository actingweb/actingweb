"""
Unit tests for PropertyList notification (register_diffs) functionality.

Tests verify that NotifyingListProperty correctly triggers subscription
notifications with proper diff info including item data.
"""

import json
from unittest.mock import Mock

from actingweb.interface.property_store import NotifyingListProperty


class TestPropertyListNotifications:
    """Test NotifyingListProperty calls register_diffs on mutations with correct data."""

    def _create_notifying_list(self, list_values=None):
        """Helper to create a NotifyingListProperty with mocks."""
        mock_list_prop = Mock()
        mock_list_prop.__len__ = Mock(return_value=len(list_values or []))

        mock_actor = Mock()
        mock_actor.register_diffs = Mock()

        notifying_list = NotifyingListProperty(
            list_prop=mock_list_prop,
            list_name="test_list",
            actor=mock_actor,
        )
        return notifying_list, mock_actor, mock_list_prop

    def test_append_calls_register_diffs_with_item_data(self):
        """Test that append() calls register_diffs with item and index."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2])
        # After append, length should be 3
        mock_list_prop.__len__ = Mock(return_value=3)

        notifying_list.append({"key": "value"})

        mock_actor.register_diffs.assert_called_once()
        call_args = mock_actor.register_diffs.call_args
        assert call_args[1]["target"] == "properties"
        assert call_args[1]["subtarget"] == "list:test_list"

        blob = json.loads(call_args[1]["blob"])
        assert blob["operation"] == "append"
        assert blob["item"] == {"key": "value"}
        assert blob["index"] == 2  # length - 1
        assert blob["length"] == 3

    def test_insert_calls_register_diffs_with_item_and_index(self):
        """Test that insert() calls register_diffs with item and index."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2, 3])
        mock_list_prop.__len__ = Mock(return_value=4)

        notifying_list.insert(1, "inserted_value")

        mock_actor.register_diffs.assert_called_once()
        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["operation"] == "insert"
        assert blob["item"] == "inserted_value"
        assert blob["index"] == 1
        assert blob["length"] == 4

    def test_setitem_calls_register_diffs_with_item_and_index(self):
        """Test that __setitem__ calls register_diffs with updated item and index."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2, 3])
        mock_list_prop.__len__ = Mock(return_value=3)
        mock_list_prop.__setitem__ = Mock()

        notifying_list[1] = "updated_value"

        mock_actor.register_diffs.assert_called_once()
        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["operation"] == "update"
        assert blob["item"] == "updated_value"
        assert blob["index"] == 1
        assert blob["length"] == 3

    def test_delitem_calls_register_diffs_with_index(self):
        """Test that __delitem__ calls register_diffs with deleted index."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2, 3])
        mock_list_prop.__len__ = Mock(return_value=2)
        mock_list_prop.__delitem__ = Mock()

        del notifying_list[1]

        mock_actor.register_diffs.assert_called_once()
        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["operation"] == "delete"
        assert blob["index"] == 1
        assert "item" not in blob  # delete doesn't include item
        assert blob["length"] == 2

    def test_pop_calls_register_diffs_with_index(self):
        """Test that pop() calls register_diffs with popped index."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2, 3])
        mock_list_prop.__len__ = Mock(return_value=2)
        mock_list_prop.pop = Mock(return_value="popped_value")

        result = notifying_list.pop(1)

        assert result == "popped_value"
        mock_actor.register_diffs.assert_called_once()
        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["operation"] == "pop"
        assert blob["index"] == 1
        assert blob["length"] == 2

    def test_pop_default_index(self):
        """Test that pop() without index uses -1."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2, 3])
        mock_list_prop.__len__ = Mock(return_value=2)
        mock_list_prop.pop = Mock(return_value="last_value")

        notifying_list.pop()

        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["index"] == -1

    def test_extend_calls_register_diffs_with_items(self):
        """Test that extend() calls register_diffs with all items."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1])
        mock_list_prop.__len__ = Mock(return_value=4)
        mock_list_prop.extend = Mock()

        notifying_list.extend([2, 3, 4])

        mock_actor.register_diffs.assert_called_once()
        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["operation"] == "extend"
        assert blob["items"] == [2, 3, 4]
        assert "item" not in blob  # extend uses items, not item
        assert blob["length"] == 4

    def test_clear_calls_register_diffs(self):
        """Test that clear() calls register_diffs."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2, 3])
        mock_list_prop.__len__ = Mock(return_value=0)
        mock_list_prop.clear = Mock()

        notifying_list.clear()

        mock_actor.register_diffs.assert_called_once()
        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["operation"] == "clear"
        assert blob["length"] == 0
        assert "item" not in blob
        assert "index" not in blob

    def test_delete_calls_register_diffs_without_length_query(self):
        """Test that delete() calls register_diffs without querying length."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2, 3])
        mock_list_prop.delete = Mock()
        # __len__ should NOT be called for delete_all

        notifying_list.delete()

        mock_actor.register_diffs.assert_called_once()
        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["operation"] == "delete_all"
        assert blob["length"] == 0  # Fixed to 0 for delete_all

    def test_remove_calls_register_diffs(self):
        """Test that remove() calls register_diffs."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1, 2, 3])
        mock_list_prop.__len__ = Mock(return_value=2)
        mock_list_prop.remove = Mock()

        notifying_list.remove(2)

        mock_actor.register_diffs.assert_called_once()
        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["operation"] == "remove"
        assert blob["length"] == 2

    def test_no_diff_registered_without_actor(self):
        """Test that no diff is registered when actor is None."""
        mock_list_prop = Mock()
        mock_list_prop.__len__ = Mock(return_value=1)

        notifying_list = NotifyingListProperty(
            list_prop=mock_list_prop,
            list_name="test_list",
            actor=None,
        )

        notifying_list.append("item")

        # No exception should be raised, just silently skipped
        mock_list_prop.append.assert_called_once_with("item")

    def test_metadata_operations_register_diffs(self):
        """Test that set_description and set_explanation register diffs."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([])
        mock_list_prop.set_description = Mock()
        mock_list_prop.set_explanation = Mock()

        notifying_list.set_description("New description")
        notifying_list.set_explanation("New explanation")

        assert mock_actor.register_diffs.call_count == 2
        for call in mock_actor.register_diffs.call_args_list:
            blob = json.loads(call[1]["blob"])
            assert blob["operation"] == "metadata"

    def test_diff_contains_list_name(self):
        """Test that registered diffs contain the correct list name."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1])
        mock_list_prop.__len__ = Mock(return_value=2)

        notifying_list.append("item")

        blob = json.loads(mock_actor.register_diffs.call_args[1]["blob"])
        assert blob["list"] == "test_list"

    def test_subtarget_has_list_prefix(self):
        """Test that subtarget uses 'list:' prefix for property list notifications."""
        notifying_list, mock_actor, mock_list_prop = self._create_notifying_list([1])
        mock_list_prop.__len__ = Mock(return_value=2)

        notifying_list.append("item")

        call_args = mock_actor.register_diffs.call_args
        assert call_args[1]["subtarget"] == "list:test_list"
