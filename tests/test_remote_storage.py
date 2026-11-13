"""Unit tests for RemotePeerStore functionality.

Tests are grouped with @pytest.mark.xdist_group to ensure they run on the same
worker during parallel execution, since they patch actingweb.attribute.Attributes.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.remote_storage import (
    DEFAULT_PEER_ID_PATTERN,
    PERMISSIVE_PEER_ID_PATTERN,
    RemotePeerStore,
    get_remote_bucket,
)

# Mark all tests in this module to run on the same xdist worker as callback_processor
# This prevents patch conflicts when tests run in parallel
pytestmark = pytest.mark.xdist_group(name="attribute_patching")


class TestGetRemoteBucket:
    """Test get_remote_bucket function."""

    def test_valid_hex_32_peer_id(self):
        """Test valid 32-char hex peer ID."""
        peer_id = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        bucket = get_remote_bucket(peer_id)
        assert bucket == f"remote:{peer_id}"

    def test_valid_uuid_format_peer_id(self):
        """Test valid UUID format peer ID."""
        peer_id = "a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6"
        bucket = get_remote_bucket(peer_id)
        assert bucket == f"remote:{peer_id}"

    def test_trailing_newline_rejected_by_both_patterns(self):
        """A trailing newline must not pass either pattern (3.14.4).

        ``$`` matched before a trailing newline, which is how a
        ``remote:<id>\\n`` bucket name came to exist.
        """
        hex_id = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        uuid_id = "a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6"
        for bad in (hex_id + "\n", uuid_id + "\n", hex_id + "\nx"):
            assert DEFAULT_PEER_ID_PATTERN.fullmatch(bad) is None
            assert PERMISSIVE_PEER_ID_PATTERN.fullmatch(bad) is None
            with pytest.raises(ValueError, match="Invalid peer_id format"):
                get_remote_bucket(bad)
            with pytest.raises(ValueError, match="Invalid peer_id format"):
                get_remote_bucket(bad, pattern=DEFAULT_PEER_ID_PATTERN)

    def test_invalid_peer_id_raises(self):
        """Test invalid peer ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid peer_id format"):
            get_remote_bucket("invalid")

    def test_validation_disabled(self):
        """Test validation can be disabled."""
        peer_id = "anything-goes-here"
        bucket = get_remote_bucket(peer_id, validate=False)
        assert bucket == f"remote:{peer_id}"

    def test_custom_pattern(self):
        """Test custom validation pattern."""
        import re

        custom_pattern = re.compile(r"^test-\d+$")
        bucket = get_remote_bucket("test-123", pattern=custom_pattern)
        assert bucket == "remote:test-123"


class TestPeerIdPatterns:
    """Test peer ID validation patterns."""

    def test_default_pattern_matches_hex32(self):
        """Test default pattern matches 32-char hex."""
        assert DEFAULT_PEER_ID_PATTERN.match("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert not DEFAULT_PEER_ID_PATTERN.match("invalid")
        assert not DEFAULT_PEER_ID_PATTERN.match("a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6")

    def test_permissive_pattern_matches_both(self):
        """Test permissive pattern matches both formats."""
        assert PERMISSIVE_PEER_ID_PATTERN.match("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert PERMISSIVE_PEER_ID_PATTERN.match("a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6")
        assert not PERMISSIVE_PEER_ID_PATTERN.match("invalid")


class TestRemotePeerStoreScalar:
    """Test RemotePeerStore scalar operations."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    @pytest.fixture
    def mock_attributes(self):
        """Create mock for Attributes class."""
        with patch("actingweb.attribute.Attributes") as mock:
            storage: dict[str, dict] = {}

            def get_attr_side_effect(name: str | None = None, **kw: Any) -> dict | None:
                if name is None:
                    return None
                return storage.get(name)

            def set_attr_side_effect(
                name: str | None = None, data: dict | None = None, **_kwargs: object
            ) -> bool:
                if name is None:
                    return False
                storage[name] = {"data": data, "timestamp": None}
                return True

            def delete_attr_side_effect(name=None):
                if name in storage:
                    del storage[name]
                return True

            def get_bucket_side_effect(**kw: Any):
                return storage

            def delete_bucket_side_effect():
                storage.clear()
                return True

            mock_instance = MagicMock()
            mock_instance.get_attr.side_effect = get_attr_side_effect
            mock_instance.set_attr.side_effect = set_attr_side_effect
            mock_instance.delete_attr.side_effect = delete_attr_side_effect
            mock_instance.get_bucket.side_effect = get_bucket_side_effect
            mock_instance.delete_bucket.side_effect = delete_bucket_side_effect
            mock.return_value = mock_instance

            yield mock, storage

    def test_get_value(self, mock_actor, mock_attributes):
        """Test getting a scalar value."""
        _, storage = mock_attributes
        storage["test_key"] = {"data": {"value": "test"}, "timestamp": None}

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        value = store.get_value("test_key")

        assert value == {"value": "test"}

    def test_get_value_not_found(self, mock_actor, mock_attributes):
        """Test getting non-existent value returns None."""
        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        value = store.get_value("nonexistent")

        assert value is None

    def test_set_value(self, mock_actor, mock_attributes):
        """Test setting a scalar value."""
        _, storage = mock_attributes
        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")

        store.set_value("test_key", {"value": "test"})

        assert storage["test_key"]["data"] == {"value": "test"}

    def test_delete_value(self, mock_actor, mock_attributes):
        """Test deleting a scalar value."""
        _, storage = mock_attributes
        storage["test_key"] = {"data": {"value": "test"}, "timestamp": None}

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        store.delete_value("test_key")

        assert "test_key" not in storage


def create_mock_list_attr(list_data, list_metadata):
    """Factory function to create MockListAttr classes."""

    class MockListAttr:
        def __init__(self, name):
            self.name = name
            if name not in list_data:
                list_data[name] = []

        def __iter__(self):
            return iter(list_data.get(self.name, []))

        def __len__(self):
            return len(list_data.get(self.name, []))

        def __getitem__(self, idx):
            return list_data[self.name][idx]

        def __setitem__(self, idx, value):
            list_data[self.name][idx] = value

        def __delitem__(self, idx):
            del list_data[self.name][idx]

        def append(self, item):
            list_data[self.name].append(item)

        def insert(self, idx, item):
            list_data[self.name].insert(idx, item)

        def extend(self, items):
            list_data[self.name].extend(items)

        def pop(self, idx=-1):
            return list_data[self.name].pop(idx)

        def clear(self):
            list_data[self.name] = []

        def delete(self):
            if self.name in list_data:
                del list_data[self.name]
            if self.name in list_metadata:
                del list_metadata[self.name]

        def set_metadata(self, metadata):
            list_metadata[self.name] = metadata

        def set_description(self, description):
            if self.name not in list_metadata:
                list_metadata[self.name] = {}
            list_metadata[self.name]["description"] = description

        def set_explanation(self, explanation):
            if self.name not in list_metadata:
                list_metadata[self.name] = {}
            list_metadata[self.name]["explanation"] = explanation

    return MockListAttr


def _replica() -> tuple[RemotePeerStore, Any]:
    """A RemotePeerStore over the in-memory attribute backend: the list core
    reaches the backend's list primitives directly (it never goes through
    ``Attributes``), so the assertions read the replica back through it."""
    from tests.mcp_token_double import make_config

    actor = MagicMock()
    actor.id = "actor123"
    actor.config, store = make_config()
    return RemotePeerStore(actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"), store


def _diff(name: str, operation: str, **fields: Any) -> dict[str, Any]:
    return {name: {"list": name, "operation": operation, **fields}}


class TestRemotePeerStoreList:
    """List operations on RemotePeerStore."""

    def test_get_list(self):
        remote, _ = _replica()
        remote.set_list("my_list", [{"id": 1}, {"id": 2}, {"id": 3}])
        assert remote.get_list("my_list") == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert remote.get_list("absent") == []

    def test_set_list(self):
        remote, _ = _replica()
        remote.set_list("my_list", [{"id": 1}])
        remote.set_list("my_list", [{"id": 1}, {"id": 2}])
        assert remote.get_list("my_list") == [{"id": 1}, {"id": 2}]

    def test_set_list_with_metadata(self):
        remote, _ = _replica()
        remote.set_list(
            "my_list",
            [{"id": 1}],
            metadata={"description": "Test list", "explanation": "For testing"},
        )
        lst = remote._get_list_store().get("my_list")
        assert lst.get_description() == "Test list"
        assert lst.get_explanation() == "For testing"

    def test_delete_list(self):
        remote, _ = _replica()
        remote.set_list("my_list", [{"id": 1}])
        remote.delete_list("my_list")
        assert remote.get_list("my_list") == []
        assert remote.list_all_lists() == []


class TestRemotePeerStoreCallbackData:
    """apply_callback_data at target level."""

    def test_apply_scalar_dict_value(self):
        remote, _ = _replica()
        results = remote.apply_callback_data({"status": {"online": True}})
        assert results["status"] == {"stored": True, "type": "scalar"}
        assert remote.get_value("status") == {"online": True}

    def test_apply_scalar_non_dict_value(self):
        remote, _ = _replica()
        results = remote.apply_callback_data({"count": 42})
        assert results["count"]["wrapped"] is True
        assert remote.get_value("count") == {"value": 42}

    def test_apply_list_append(self):
        remote, _ = _replica()
        remote.set_list("items", [{"id": 1}])
        results = remote.apply_callback_data(_diff("items", "append", item={"id": 2}))
        assert results["items"]["success"] is True
        assert remote.get_list("items") == [{"id": 1}, {"id": 2}]

    def test_apply_list_extend(self):
        remote, _ = _replica()
        results = remote.apply_callback_data(
            _diff("items", "extend", items=[{"id": 1}, {"id": 2}])
        )
        assert results["items"]["count"] == 2
        assert remote.get_list("items") == [{"id": 1}, {"id": 2}]

    def test_apply_list_insert(self):
        remote, _ = _replica()
        remote.set_list("items", ["a", "c"])
        remote.apply_callback_data(_diff("items", "insert", index=1, item="b"))
        assert remote.get_list("items") == ["a", "b", "c"]

    def test_apply_list_update(self):
        remote, _ = _replica()
        remote.set_list("items", ["a", "b"])
        remote.apply_callback_data(_diff("items", "update", index=1, item="B"))
        assert remote.get_list("items") == ["a", "B"]

    def test_apply_list_update_without_old_item_is_unchanged(self):
        """An index-addressed update writes at the index."""
        remote, _ = _replica()
        remote.set_list("items", ["a", "b", "c"])
        result = remote.apply_callback_data(_diff("items", "update", index=0, item="A"))
        assert result["items"]["index"] == 0
        assert remote.get_list("items") == ["A", "b", "c"]

    def test_apply_list_update_with_old_item_and_no_index_applies_by_value(self):
        remote, _ = _replica()
        remote.set_list("items", [{"id": 1}, {"id": 2}])
        remote.apply_callback_data(
            _diff("items", "update", old_item={"id": 2}, item={"id": 2, "x": 1})
        )
        assert remote.get_list("items") == [{"id": 1}, {"id": 2, "x": 1}]

    def test_apply_list_update_with_ambiguous_old_item_falls_back_to_index(self):
        remote, _ = _replica()
        remote.set_list("items", ["dup", "dup", "z"])
        remote.apply_callback_data(
            _diff("items", "update", old_item="dup", item="new", index=1)
        )
        assert remote.get_list("items") == ["dup", "new", "z"]

    def test_apply_list_update_with_ambiguous_old_item_and_no_index_is_out_of_step(
        self,
    ):
        """3.16 verification re-run 2: dropped silently before; the replica
        cannot tell which row, so it is rebuilt."""
        remote, _ = _replica()
        remote.set_list("items", ["dup", "dup"])
        result = remote.apply_callback_data(
            _diff("items", "update", old_item="dup", item="new")
        )
        assert result.out_of_step is not None
        assert remote.get_list("items") == ["dup", "dup"]

    def test_apply_list_update_with_ambiguous_old_item_and_no_index_logs_a_warning(
        self, caplog
    ):
        remote, _ = _replica()
        remote.set_list("items", ["dup", "dup"])
        with caplog.at_level("WARNING"):
            remote.apply_callback_data(
                _diff("items", "update", old_item="dup", item="n")
            )
        assert "out of step" in caplog.text

    def test_apply_list_update_with_null_old_item_applies_by_value(self):
        remote, _ = _replica()
        remote.set_list("items", ["a", None])
        remote.apply_callback_data(_diff("items", "update", old_item=None, item="b"))
        assert remote.get_list("items") == ["a", "b"]

    def test_apply_list_remove_of_a_none_item_applies(self):
        remote, _ = _replica()
        remote.set_list("items", ["a", None, "c"])
        remote.apply_callback_data(_diff("items", "remove", item=None))
        assert remote.get_list("items") == ["a", "c"]

    def test_apply_list_update_with_old_item_prefers_value_match_over_drifted_index(
        self,
    ):
        remote, _ = _replica()
        remote.set_list("items", ["x", "target", "y"])
        remote.apply_callback_data(
            _diff("items", "update", old_item="target", item="T", index=0)
        )
        assert remote.get_list("items") == ["x", "T", "y"]

    def test_apply_list_update_with_old_item_not_found_is_out_of_step(self):
        """3.16 verification re-run 2: it overwrote whatever sat at the index;
        the replica drifted, so it is rebuilt instead."""
        remote, _ = _replica()
        remote.set_list("items", ["a", "b"])
        result = remote.apply_callback_data(
            _diff("items", "update", old_item="gone", item="B", index=1)
        )
        assert result.out_of_step is not None
        assert remote.get_list("items") == ["a", "b"]

    def test_apply_list_delete(self):
        remote, _ = _replica()
        remote.set_list("items", ["a", "b", "c"])
        remote.apply_callback_data(_diff("items", "delete", index=1))
        assert remote.get_list("items") == ["a", "c"]

    def test_apply_list_pop(self):
        remote, _ = _replica()
        remote.set_list("items", ["a", "b", "c"])
        remote.apply_callback_data(_diff("items", "pop"))
        assert remote.get_list("items") == ["a", "b"]
        remote.apply_callback_data(_diff("items", "pop", index=-2))
        assert remote.get_list("items") == ["b"]

    def test_apply_list_clear(self):
        remote, _ = _replica()
        remote.set_list("items", ["a"])
        remote.apply_callback_data(_diff("items", "clear"))
        assert remote.get_list("items") == []

    def test_apply_list_remove(self):
        remote, _ = _replica()
        remote.set_list("items", ["a", "b", "a"])
        remote.apply_callback_data(_diff("items", "remove", item="a"))
        assert remote.get_list("items") == ["b", "a"]

    def test_apply_list_metadata_ignored(self):
        remote, _ = _replica()
        result = remote.apply_callback_data(_diff("items", "metadata", description="d"))
        assert result["items"] == {"operation": "metadata", "ignored": True}


class TestRemotePeerStoreResync:
    """apply_resync_data replaces only the properties it carries."""

    def test_resync_preserves_other_properties(self):
        remote, _ = _replica()
        remote.set_value("keep", {"v": 1})
        remote.apply_resync_data({"changed": {"v": 2}})
        assert remote.get_value("keep") == {"v": 1}
        assert remote.get_value("changed") == {"v": 2}

    def test_resync_handles_lists(self):
        remote, _ = _replica()
        results = remote.apply_resync_data({"list:items": [{"id": 1}, {"id": 2}]})
        assert results["items"]["items"] == 2
        assert remote.get_list("items") == [{"id": 1}, {"id": 2}]

    def test_resync_wraps_non_dict_values(self):
        remote, _ = _replica()
        remote.apply_resync_data({"count": 5})
        assert remote.get_value("count") == {"value": 5}

    def test_resync_preserves_other_lists(self):
        remote, _ = _replica()
        remote.set_list("other", ["x"])
        remote.apply_resync_data({"items": {"_list": True, "items": ["a"]}})
        assert remote.get_list("other") == ["x"]
        assert remote.get_list("items") == ["a"]

    def test_resync_replaces_same_list(self):
        remote, _ = _replica()
        remote.set_list("items", ["old1", "old2"])
        remote.apply_resync_data({"items": {"_list": True, "items": ["new"]}})
        assert remote.get_list("items") == ["new"]

    def test_resync_mixed_preserves_unrelated(self):
        remote, _ = _replica()
        remote.set_value("unrelated", {"v": 0})
        remote.set_list("unrelated_list", ["u"])
        remote.apply_resync_data(
            {"scalar": {"v": 1}, "items": {"_list": True, "items": [1, 2]}}
        )
        assert remote.get_value("unrelated") == {"v": 0}
        assert remote.get_list("unrelated_list") == ["u"]
        assert remote.get_value("scalar") == {"v": 1}
        assert remote.get_list("items") == [1, 2]


class TestRemotePeerStoreStats:
    """Test storage statistics."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    def test_get_storage_stats(self, mock_actor):
        """Test getting storage statistics."""
        with patch("actingweb.attribute.Attributes") as mock:
            mock_instance = MagicMock()
            mock_instance.get_bucket.return_value = {
                "scalar1": {"data": {}},
                "scalar2": {"data": {}},
                "list:items:meta": {"data": {}},
                "list:items:0": {"data": {}},
            }
            mock.return_value = mock_instance

            store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
            stats = store.get_storage_stats()

            assert stats["peer_id"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
            assert stats["bucket"] == "remote:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
            assert stats["list_count"] == 2  # list:items:meta and list:items:0
            assert stats["scalar_count"] == 2
            assert stats["total_attributes"] == 4


class TestRemotePeerStoreListAllScalars:
    """Test list_all_scalars method."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    def test_list_all_scalars_filters_list_keys(self, mock_actor):
        """Test that list: prefixed keys are excluded."""
        with patch("actingweb.attribute.Attributes") as mock:
            mock_instance = MagicMock()
            mock_instance.get_bucket.return_value = {
                "status": {"data": {"active": True}},
                "config": {"data": {"key": "val"}},
                "list:items:meta": {"data": {}},
                "list:items:0": {"data": {}},
                "list:items:1": {"data": {}},
            }
            mock.return_value = mock_instance

            store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
            scalars = store.list_all_scalars()

            assert sorted(scalars) == ["config", "status"]

    def test_list_all_scalars_empty_bucket(self, mock_actor):
        """Test with empty bucket returns empty list."""
        with patch("actingweb.attribute.Attributes") as mock:
            mock_instance = MagicMock()
            mock_instance.get_bucket.return_value = {}
            mock.return_value = mock_instance

            store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
            scalars = store.list_all_scalars()

            assert scalars == []

    def test_list_all_scalars_none_bucket(self, mock_actor):
        """Test with None bucket returns empty list."""
        with patch("actingweb.attribute.Attributes") as mock:
            mock_instance = MagicMock()
            mock_instance.get_bucket.return_value = None
            mock.return_value = mock_instance

            store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
            scalars = store.list_all_scalars()

            assert scalars == []

    def test_list_all_scalars_only_list_keys(self, mock_actor):
        """Test when all keys are list keys."""
        with patch("actingweb.attribute.Attributes") as mock:
            mock_instance = MagicMock()
            mock_instance.get_bucket.return_value = {
                "list:items:meta": {"data": {}},
                "list:items:0": {"data": {}},
            }
            mock.return_value = mock_instance

            store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
            scalars = store.list_all_scalars()

            assert scalars == []


class TestRemotePeerStoreGetAllProperties:
    """get_all_properties over the in-memory backend."""

    def test_get_all_properties_mixed(self):
        remote, _ = _replica()
        remote.set_value("status", {"active": True})
        remote.set_list("items", [{"id": 1}, {"id": 2}])
        props = remote.get_all_properties()
        assert props["items"]["type"] == "list"
        assert props["items"]["value"] == [{"id": 1}, {"id": 2}]
        assert props["items"]["item_count"] == 2
        assert props["status"]["type"] == "scalar"
        assert props["status"]["value"] == {"active": True}

    def test_get_all_properties_empty(self):
        remote, _ = _replica()
        assert remote.get_all_properties() == {}

    def test_get_all_properties_only_scalars(self):
        remote, _ = _replica()
        remote.set_value("key1", {"val": 1})
        remote.set_value("key2", {"val": 2})
        props = remote.get_all_properties()
        assert len(props) == 2
        assert {p["type"] for p in props.values()} == {"scalar"}

    def test_get_all_properties_only_lists(self):
        remote, _ = _replica()
        remote.set_list("list_a", [{"id": 1}])
        remote.set_list("list_b", [{"id": 2}, {"id": 3}])
        props = remote.get_all_properties()
        assert len(props) == 2
        assert props["list_a"]["item_count"] == 1
        assert props["list_b"]["item_count"] == 2

    def test_get_all_properties_skips_none_scalars(self):
        remote, store = _replica()
        store.bucket("actor123", remote.bucket)["empty_key"] = {"data": None}
        assert "empty_key" not in remote.get_all_properties()


class TestRemotePeerStoreCleanup:
    """Test cleanup operations."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    def test_delete_all(self, mock_actor):
        """Test deleting all peer data."""
        with patch("actingweb.attribute.Attributes") as mock:
            mock_instance = MagicMock()
            mock_instance.delete_bucket.return_value = True
            mock.return_value = mock_instance

            store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
            store.delete_all()

            mock_instance.delete_bucket.assert_called_once()


class TestRemotePeerStoreValidation:
    """Test peer ID validation."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    def test_invalid_peer_id_raises(self, mock_actor):
        """Test invalid peer ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid peer_id format"):
            RemotePeerStore(mock_actor, "invalid-peer-id")

    def test_validation_can_be_disabled(self, mock_actor):
        """Test validation can be disabled."""
        with patch("actingweb.attribute.Attributes"):
            store = RemotePeerStore(
                mock_actor, "any-format-accepted", validate_peer_id=False
            )
            assert store.bucket == "remote:any-format-accepted"

    def test_bucket_property(self, mock_actor):
        """Test bucket property returns correct value."""
        with patch("actingweb.attribute.Attributes"):
            store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
            assert store.bucket == "remote:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


class TestRemotePeerStorePermissionData:
    """Test apply_permission_data method."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    @pytest.fixture
    def mock_permission_store(self):
        """Create mock for PeerPermissionStore."""
        stored_permissions = []

        with patch(
            "actingweb.peer_permissions.get_peer_permission_store"
        ) as mock_get_store:
            mock_store = MagicMock()

            def store_permissions_side_effect(perms):
                stored_permissions.append(perms)
                return True

            mock_store.store_permissions.side_effect = store_permissions_side_effect
            mock_get_store.return_value = mock_store

            # Also mock Attributes to avoid errors
            with patch("actingweb.attribute.Attributes"):
                yield mock_store, stored_permissions

    def test_apply_permission_data_stores_permissions(
        self, mock_actor, mock_permission_store
    ):
        """Test applying permission data stores in PeerPermissionStore."""
        _, stored_permissions = mock_permission_store

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        permissions = {
            "properties": {
                "patterns": ["memory_*", "profile/*"],
                "operations": ["read", "subscribe"],
            },
            "methods": {"allowed": ["sync_*"], "denied": []},
        }

        result = store.apply_permission_data(permissions)

        assert result["operation"] == "permission_update"
        assert result["success"] is True
        assert len(stored_permissions) == 1

        stored = stored_permissions[0]
        assert stored.actor_id == "actor123"
        assert stored.peer_id == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        assert stored.properties == permissions["properties"]
        assert stored.methods == permissions["methods"]

    def test_apply_permission_data_with_all_fields(
        self, mock_actor, mock_permission_store
    ):
        """Test applying permission data with all permission fields."""
        _, stored_permissions = mock_permission_store

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        permissions = {
            "properties": {
                "patterns": ["*"],
                "operations": ["read", "write", "subscribe", "delete"],
                "excluded_patterns": ["private_*"],
            },
            "methods": {"allowed": ["*"], "denied": ["delete_*"]},
            "actions": {"allowed": ["*"], "denied": []},
            "tools": {"allowed": ["search", "fetch"], "denied": []},
            "resources": {"allowed": ["data://*"], "denied": []},
            "prompts": {"allowed": ["*"]},
        }

        result = store.apply_permission_data(permissions)

        assert result["success"] is True
        stored = stored_permissions[0]
        assert stored.properties == permissions["properties"]
        assert stored.methods == permissions["methods"]
        assert stored.actions == permissions["actions"]
        assert stored.tools == permissions["tools"]
        assert stored.resources == permissions["resources"]
        assert stored.prompts == permissions["prompts"]

    def test_apply_permission_data_with_partial_fields(
        self, mock_actor, mock_permission_store
    ):
        """Test applying permission data with only some fields."""
        _, stored_permissions = mock_permission_store

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        permissions = {
            "tools": {"allowed": ["search"], "denied": []},
        }

        result = store.apply_permission_data(permissions)

        assert result["success"] is True
        stored = stored_permissions[0]
        assert stored.tools == permissions["tools"]
        # Other fields should be None
        assert stored.properties is None
        assert stored.methods is None

    def test_apply_permission_data_includes_timestamp(
        self, mock_actor, mock_permission_store
    ):
        """Test that apply_permission_data includes fetched_at timestamp."""
        _, stored_permissions = mock_permission_store

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        permissions = {"properties": {"patterns": ["*"]}}

        store.apply_permission_data(permissions)

        stored = stored_permissions[0]
        assert stored.fetched_at is not None
        # Should be an ISO timestamp
        assert "T" in stored.fetched_at

    def test_apply_permission_data_with_no_actor_id(self, mock_permission_store):
        """Test apply_permission_data fails gracefully with no actor ID."""
        mock_store, _ = mock_permission_store

        actor = MagicMock()
        actor.id = None  # No actor ID
        actor.config = MagicMock()

        store = RemotePeerStore(
            actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", validate_peer_id=False
        )
        permissions = {"properties": {"patterns": ["*"]}}

        result = store.apply_permission_data(permissions)

        assert result["success"] is False
        assert "error" in result
        # Store should not be called
        mock_store.store_permissions.assert_not_called()

    def test_apply_permission_data_handles_store_error(self, mock_actor):
        """Test apply_permission_data handles store errors gracefully."""
        with patch(
            "actingweb.peer_permissions.get_peer_permission_store"
        ) as mock_get_store:
            mock_store = MagicMock()
            mock_store.store_permissions.side_effect = Exception("Database error")
            mock_get_store.return_value = mock_store

            with patch("actingweb.attribute.Attributes"):
                store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
                permissions = {"properties": {"patterns": ["*"]}}

                result = store.apply_permission_data(permissions)

                assert result["success"] is False
                assert "error" in result
                assert "Database error" in result["error"]


class TestApplyResyncData:
    """Test apply_resync_data with flag-based list format."""

    @pytest.fixture
    def mock_actor(self):
        """A mock ActorInterface over the in-memory attribute backend: the
        list core reaches the backend's list primitives directly (it never
        goes through ``Attributes``), so a mocked config cannot hold a
        list."""
        from tests.mcp_token_double import make_config

        actor = MagicMock()
        actor.id = "actor123"
        actor.config, _store = make_config()
        return actor

    def test_apply_resync_data_flag_based_list(self, mock_actor):
        """Test new flag-based list format {"_list": true, "items": [...]}."""
        with patch("actingweb.attribute.Attributes"):
            store = RemotePeerStore(
                mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", validate_peer_id=False
            )

            # Apply resync data with flag-based list
            data = {
                "scalar_prop": {"value": "test"},
                "memory_travel": {
                    "_list": True,
                    "items": [
                        {"id": "1", "location": "Paris"},
                        {"id": "2", "location": "Tokyo"},
                        {"id": "3", "location": "NYC"},
                    ],
                },
            }

            results = store.apply_resync_data(data)

            # Verify results
            assert results["scalar_prop"]["success"] is True
            assert results["memory_travel"]["success"] is True
            assert results["memory_travel"]["items"] == 3
            assert results["memory_travel"]["operation"] == "resync"
            assert [i["location"] for i in store.get_list("memory_travel")] == [
                "Paris",
                "Tokyo",
                "NYC",
            ]

    def test_apply_resync_data_legacy_list_prefix(self, mock_actor):
        """Test backward compatibility with legacy "list:" prefix format."""
        with patch("actingweb.attribute.Attributes"):
            store = RemotePeerStore(
                mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", validate_peer_id=False
            )

            # Apply resync data with legacy list: prefix
            data = {
                "scalar_prop": {"value": "test"},
                "list:memory_travel": [
                    {"id": "1", "location": "Paris"},
                    {"id": "2", "location": "Tokyo"},
                ],
            }

            results = store.apply_resync_data(data)

            # Verify results (note: key is "memory_travel" without "list:" prefix)
            assert results["scalar_prop"]["success"] is True
            assert results["memory_travel"]["success"] is True
            assert results["memory_travel"]["items"] == 2
            assert results["memory_travel"]["operation"] == "resync"

    def test_apply_resync_data_mixed_format(self, mock_actor):
        """Test both flag-based and legacy formats work together."""
        with patch("actingweb.attribute.Attributes"):
            store = RemotePeerStore(
                mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", validate_peer_id=False
            )

            # Apply resync data with mixed formats
            data = {
                "scalar1": {"value": "test1"},
                "new_list": {"_list": True, "items": [{"id": "1"}]},
                "scalar2": {"value": "test2"},
                "list:legacy_list": [{"id": "2"}, {"id": "3"}],
            }

            results = store.apply_resync_data(data)

            # Verify all formats processed correctly
            assert results["scalar1"]["success"] is True
            assert results["new_list"]["success"] is True
            assert results["new_list"]["items"] == 1
            assert results["scalar2"]["success"] is True
            assert results["legacy_list"]["success"] is True
            assert results["legacy_list"]["items"] == 2

    def test_apply_resync_data_empty_flag_based_list(self, mock_actor):
        """Test empty list in flag-based format."""
        with patch("actingweb.attribute.Attributes"):
            store = RemotePeerStore(
                mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", validate_peer_id=False
            )

            # Apply resync data with empty list
            data = {"empty_list": {"_list": True, "items": []}}

            results = store.apply_resync_data(data)

            # Verify empty list handled correctly
            assert results["empty_list"]["success"] is True
            assert results["empty_list"]["items"] == 0
            assert results["empty_list"]["operation"] == "resync"

    def test_apply_resync_data_flag_list_without_items(self, mock_actor):
        """Test flag-based list without items field (skipped to avoid data loss)."""
        with patch("actingweb.attribute.Attributes"):
            store = RemotePeerStore(
                mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", validate_peer_id=False
            )

            # Apply resync data with list flag but no items (transformation failure scenario)
            data = {"list_without_items": {"_list": True, "count": 5}}

            results = store.apply_resync_data(data)

            # Should skip to avoid treating metadata as empty list (data loss)
            assert results["list_without_items"]["success"] is False
            assert results["list_without_items"]["operation"] == "skip"
            assert results["list_without_items"]["reason"] == "metadata_without_items"
