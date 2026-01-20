"""Unit tests for RemotePeerStore functionality."""

from unittest.mock import MagicMock, patch

import pytest

from actingweb.remote_storage import (
    DEFAULT_PEER_ID_PATTERN,
    PERMISSIVE_PEER_ID_PATTERN,
    RemotePeerStore,
    get_remote_bucket,
)


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
        assert PERMISSIVE_PEER_ID_PATTERN.match(
            "a1b2c3d4-e5f6-a7b8-c9d0-e1f2a3b4c5d6"
        )
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

            def get_attr_side_effect(name=None):
                return storage.get(name)

            def set_attr_side_effect(name=None, data=None, **_kwargs):
                storage[name] = {"data": data, "timestamp": None}
                return True

            def delete_attr_side_effect(name=None):
                if name in storage:
                    del storage[name]
                return True

            def get_bucket_side_effect():
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

    return MockListAttr


class MockListStore:
    """Mock AttributeListStore that uses MockListAttr."""

    def __init__(self, list_data, list_metadata):
        self._list_data = list_data
        self._list_metadata = list_metadata
        self._MockListAttr = create_mock_list_attr(list_data, list_metadata)
        self._cache: dict = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._cache:
            self._cache[name] = self._MockListAttr(name)
        return self._cache[name]

    def list_all(self):
        return list(self._list_data.keys())


class TestRemotePeerStoreList:
    """Test RemotePeerStore list operations."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    @pytest.fixture
    def mock_list_store(self):
        """Create mock for AttributeListStore class."""
        list_data: dict[str, list] = {}
        list_metadata: dict[str, dict] = {}

        with patch(
            "actingweb.attribute_list_store.AttributeListStore"
        ) as list_mock:
            list_mock.return_value = MockListStore(list_data, list_metadata)

            # Also mock Attributes for delete_bucket
            with patch("actingweb.attribute.Attributes") as attr_mock:
                attr_instance = MagicMock()
                attr_instance.delete_bucket.return_value = True
                attr_instance.get_bucket.return_value = {}
                attr_mock.return_value = attr_instance

                yield list_mock, list_data, list_metadata

    def test_get_list(self, mock_actor, mock_list_store):
        """Test getting a list."""
        _, list_data, _ = mock_list_store
        list_data["items"] = [{"id": 1}, {"id": 2}]

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        items = store.get_list("items")

        assert items == [{"id": 1}, {"id": 2}]

    def test_set_list(self, mock_actor, mock_list_store):
        """Test setting a list."""
        _, list_data, _ = mock_list_store

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        store.set_list("items", [{"id": 1}, {"id": 2}])

        assert list_data["items"] == [{"id": 1}, {"id": 2}]

    def test_set_list_with_metadata(self, mock_actor, mock_list_store):
        """Test setting a list with metadata."""
        _, list_data, list_metadata = mock_list_store

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        store.set_list("items", [{"id": 1}], metadata={"count": 1})

        assert list_data["items"] == [{"id": 1}]
        assert list_metadata["items"] == {"count": 1}

    def test_delete_list(self, mock_actor, mock_list_store):
        """Test deleting a list."""
        _, list_data, _ = mock_list_store
        list_data["items"] = [{"id": 1}]

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        store.delete_list("items")

        assert "items" not in list_data


class TestRemotePeerStoreCallbackData:
    """Test apply_callback_data method."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    @pytest.fixture
    def mock_storage(self):
        """Create mocks for both Attributes and AttributeListStore."""
        scalar_storage: dict[str, dict] = {}
        list_data: dict[str, list] = {}
        list_metadata: dict[str, dict] = {}

        with patch("actingweb.attribute.Attributes") as attr_mock:
            attr_instance = MagicMock()

            def get_attr_side_effect(name=None):
                return scalar_storage.get(name)

            def set_attr_side_effect(name=None, data=None, **_kwargs):
                scalar_storage[name] = {"data": data, "timestamp": None}
                return True

            def delete_bucket_side_effect():
                scalar_storage.clear()
                list_data.clear()
                return True

            attr_instance.get_attr.side_effect = get_attr_side_effect
            attr_instance.set_attr.side_effect = set_attr_side_effect
            attr_instance.delete_bucket.side_effect = delete_bucket_side_effect
            attr_instance.get_bucket.return_value = scalar_storage
            attr_mock.return_value = attr_instance

            with patch(
                "actingweb.attribute_list_store.AttributeListStore"
            ) as list_mock:
                list_mock.return_value = MockListStore(list_data, list_metadata)

                yield scalar_storage, list_data

    def test_apply_scalar_dict_value(self, mock_actor, mock_storage):
        """Test applying scalar dict value."""
        scalar_storage, _ = mock_storage

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data({"status": {"online": True}})

        assert results["status"]["stored"] is True
        assert results["status"]["type"] == "scalar"
        assert scalar_storage["status"]["data"] == {"online": True}

    def test_apply_scalar_non_dict_value(self, mock_actor, mock_storage):
        """Test applying scalar non-dict value gets wrapped."""
        scalar_storage, _ = mock_storage

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data({"count": 42})

        assert results["count"]["stored"] is True
        assert results["count"]["wrapped"] is True
        assert scalar_storage["count"]["data"] == {"value": 42}

    def test_apply_list_append(self, mock_actor, mock_storage):
        """Test applying list append operation."""
        _, list_data = mock_storage

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data(
            {"list:items": {"operation": "append", "item": {"id": 1}}}
        )

        assert results["items"]["operation"] == "append"
        assert results["items"]["success"] is True
        assert list_data["items"] == [{"id": 1}]

    def test_apply_list_extend(self, mock_actor, mock_storage):
        """Test applying list extend operation."""
        _, list_data = mock_storage

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data(
            {"list:items": {"operation": "extend", "items": [{"id": 1}, {"id": 2}]}}
        )

        assert results["items"]["operation"] == "extend"
        assert results["items"]["count"] == 2
        assert list_data["items"] == [{"id": 1}, {"id": 2}]

    def test_apply_list_insert(self, mock_actor, mock_storage):
        """Test applying list insert operation."""
        _, list_data = mock_storage
        list_data["items"] = [{"id": 1}, {"id": 3}]

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data(
            {"list:items": {"operation": "insert", "index": 1, "item": {"id": 2}}}
        )

        assert results["items"]["operation"] == "insert"
        assert results["items"]["index"] == 1
        assert list_data["items"] == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_apply_list_update(self, mock_actor, mock_storage):
        """Test applying list update operation."""
        _, list_data = mock_storage
        list_data["items"] = [{"id": 1}, {"id": 2}]

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data(
            {"list:items": {"operation": "update", "index": 1, "item": {"id": 99}}}
        )

        assert results["items"]["operation"] == "update"
        assert results["items"]["index"] == 1
        assert list_data["items"][1] == {"id": 99}

    def test_apply_list_delete(self, mock_actor, mock_storage):
        """Test applying list delete operation."""
        _, list_data = mock_storage
        list_data["items"] = [{"id": 1}, {"id": 2}, {"id": 3}]

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data(
            {"list:items": {"operation": "delete", "index": 1}}
        )

        assert results["items"]["operation"] == "delete"
        assert results["items"]["index"] == 1
        assert list_data["items"] == [{"id": 1}, {"id": 3}]

    def test_apply_list_pop(self, mock_actor, mock_storage):
        """Test applying list pop operation."""
        _, list_data = mock_storage
        list_data["items"] = [{"id": 1}, {"id": 2}]

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data({"list:items": {"operation": "pop"}})

        assert results["items"]["operation"] == "pop"
        assert results["items"]["success"] is True
        assert list_data["items"] == [{"id": 1}]

    def test_apply_list_clear(self, mock_actor, mock_storage):
        """Test applying list clear operation."""
        _, list_data = mock_storage
        list_data["items"] = [{"id": 1}, {"id": 2}]

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data({"list:items": {"operation": "clear"}})

        assert results["items"]["operation"] == "clear"
        assert results["items"]["success"] is True
        assert list_data["items"] == []

    def test_apply_list_remove(self, mock_actor, mock_storage):
        """Test applying list remove operation."""
        _, list_data = mock_storage
        list_data["items"] = [{"id": 1}, {"id": 2}]

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data(
            {"list:items": {"operation": "remove", "item": {"id": 1}}}
        )

        assert results["items"]["operation"] == "remove"
        assert results["items"]["success"] is True
        assert list_data["items"] == [{"id": 2}]

    def test_apply_list_metadata_ignored(self, mock_actor, mock_storage):
        """Test metadata-only operation is ignored."""
        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_callback_data({"list:items": {"operation": "metadata"}})

        assert results["items"]["operation"] == "metadata"
        assert results["items"]["ignored"] is True


class TestRemotePeerStoreResync:
    """Test apply_resync_data method."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock ActorInterface."""
        actor = MagicMock()
        actor.id = "actor123"
        actor.config = MagicMock()
        return actor

    @pytest.fixture
    def mock_storage(self):
        """Create mocks for both Attributes and AttributeListStore."""
        scalar_storage: dict[str, dict] = {}
        list_data: dict[str, list] = {}
        list_metadata: dict[str, dict] = {}

        with patch("actingweb.attribute.Attributes") as attr_mock:
            attr_instance = MagicMock()

            def set_attr_side_effect(name=None, data=None, **_kwargs):
                scalar_storage[name] = {"data": data, "timestamp": None}
                return True

            def delete_bucket_side_effect():
                scalar_storage.clear()
                list_data.clear()
                return True

            attr_instance.set_attr.side_effect = set_attr_side_effect
            attr_instance.delete_bucket.side_effect = delete_bucket_side_effect
            attr_mock.return_value = attr_instance

            with patch(
                "actingweb.attribute_list_store.AttributeListStore"
            ) as list_mock:
                list_mock.return_value = MockListStore(list_data, list_metadata)

                yield scalar_storage, list_data

    def test_resync_replaces_all_data(self, mock_actor, mock_storage):
        """Test resync replaces all data."""
        scalar_storage, _ = mock_storage
        scalar_storage["old_key"] = {"data": {"old": True}, "timestamp": None}

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_resync_data({"new_key": {"new": True}})

        assert "old_key" not in scalar_storage
        assert scalar_storage["new_key"]["data"] == {"new": True}
        assert results["new_key"]["operation"] == "resync"
        assert results["new_key"]["success"] is True

    def test_resync_handles_lists(self, mock_actor, mock_storage):
        """Test resync handles list data."""
        _, list_data = mock_storage

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_resync_data({"list:items": [{"id": 1}, {"id": 2}]})

        assert results["items"]["operation"] == "resync"
        assert results["items"]["items"] == 2
        assert list_data["items"] == [{"id": 1}, {"id": 2}]

    def test_resync_wraps_non_dict_values(self, mock_actor, mock_storage):
        """Test resync wraps non-dict values."""
        scalar_storage, _ = mock_storage

        store = RemotePeerStore(mock_actor, "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        results = store.apply_resync_data({"count": 42})

        assert scalar_storage["count"]["data"] == {"value": 42}
        assert results["count"]["operation"] == "resync"
        assert results["count"]["success"] is True


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
