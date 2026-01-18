"""Tests for attribute_list_store module."""

from unittest.mock import Mock

import pytest

from actingweb.attribute_list_store import AttributeListStore


class TestAttributeListStoreInitialization:
    """Test AttributeListStore class initialization."""

    def test_init_with_all_params(self):
        """Test initialization with actor_id, bucket, config."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        assert store._actor_id == "test_actor"
        assert store._bucket == "test_bucket"
        assert store._config == mock_config
        assert store._list_cache == {}

    def test_init_without_actor_id(self):
        """Test initialization without actor_id."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id=None, bucket="test_bucket", config=mock_config
        )

        assert store._actor_id is None
        assert store._bucket == "test_bucket"

    def test_init_without_bucket(self):
        """Test initialization without bucket."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket=None, config=mock_config
        )

        assert store._actor_id == "test_actor"
        assert store._bucket is None


class TestAttributeListStoreExists:
    """Test AttributeListStore exists method."""

    def test_exists_returns_false_for_nonexistent(self):
        """Test exists() returns False for non-existent list."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_db_attr.get_attr.return_value = None
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        assert store.exists("nonexistent_list") is False

    def test_exists_returns_true_for_existing(self):
        """Test exists() returns True for list with metadata."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        # Return metadata for existing list
        mock_db_attr.get_attr.return_value = {
            "data": {"length": 0, "created_at": "2025-01-01"}
        }
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        assert store.exists("existing_list") is True

    def test_exists_without_config(self):
        """Test exists() returns False without config."""
        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=None
        )

        assert store.exists("any_list") is False

    def test_exists_without_actor_id(self):
        """Test exists() returns False without actor_id."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id=None, bucket="test_bucket", config=mock_config
        )

        assert store.exists("any_list") is False

    def test_exists_without_bucket(self):
        """Test exists() returns False without bucket."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket=None, config=mock_config
        )

        assert store.exists("any_list") is False


class TestAttributeListStoreListAll:
    """Test AttributeListStore list_all method."""

    def test_list_all_empty(self):
        """Test list_all() returns empty list when no lists exist."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {}
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        result = store.list_all()

        assert result == []

    def test_list_all_returns_all_lists(self):
        """Test list_all() returns all list names."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {
            "list:memories:meta": {"data": {}},
            "list:notes:meta": {"data": {}},
            "list:tasks:meta": {"data": {}},
        }
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        result = store.list_all()

        assert set(result) == {"memories", "notes", "tasks"}

    def test_list_all_filters_non_list_attributes(self):
        """Test list_all() ignores attributes without :meta suffix."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {
            "list:memories:meta": {"data": {}},
            "list:memories:0": {"data": "item"},
            "list:notes:1": {"data": "item"},
            "regular_attribute": {"data": "value"},
            "another:attribute": {"data": "value"},
        }
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        result = store.list_all()

        # Should only return "memories" since it's the only one with :meta suffix
        assert result == ["memories"]

    def test_list_all_without_config(self):
        """Test list_all() returns empty list without config."""
        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=None
        )

        result = store.list_all()

        assert result == []

    def test_list_all_without_actor_id(self):
        """Test list_all() returns empty list without actor_id."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id=None, bucket="test_bucket", config=mock_config
        )

        result = store.list_all()

        assert result == []

    def test_list_all_without_bucket(self):
        """Test list_all() returns empty list without bucket."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket=None, config=mock_config
        )

        result = store.list_all()

        assert result == []

    def test_list_all_handles_complex_names(self):
        """Test list_all() handles list names with colons."""
        mock_config = Mock()
        mock_db_attr = Mock()
        mock_db_attr.get_bucket.return_value = {
            "list:my:complex:name:meta": {"data": {}},
            "list:simple:meta": {"data": {}},
        }
        mock_config.DbAttribute.DbAttribute.return_value = mock_db_attr

        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        result = store.list_all()

        assert set(result) == {"my:complex:name", "simple"}


class TestAttributeListStoreGetAttr:
    """Test AttributeListStore __getattr__ method."""

    def test_getattr_returns_attribute_list_property(self):
        """Test __getattr__ returns ListAttribute instance."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        prop = store.my_list

        from actingweb.attribute_list import ListAttribute

        assert isinstance(prop, ListAttribute)
        assert prop.actor_id == "test_actor"
        assert prop.bucket == "test_bucket"
        assert prop.name == "my_list"

    def test_getattr_caches_instance(self):
        """Test __getattr__ returns same instance on repeated calls."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        prop1 = store.my_list
        prop2 = store.my_list

        assert prop1 is prop2  # Same object reference

    def test_getattr_rejects_private_names(self):
        """Test __getattr__ raises AttributeError for _private names."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        with pytest.raises(AttributeError) as exc_info:
            _ = store._private_attr

        assert "has no attribute" in str(exc_info.value)

    def test_getattr_requires_actor_id(self):
        """Test __getattr__ raises if actor_id is None."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id=None, bucket="test_bucket", config=mock_config
        )

        with pytest.raises(RuntimeError) as exc_info:
            _ = store.my_list

        assert "actor_id" in str(exc_info.value)

    def test_getattr_requires_bucket(self):
        """Test __getattr__ raises if bucket is None."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket=None, config=mock_config
        )

        with pytest.raises(RuntimeError) as exc_info:
            _ = store.my_list

        assert "bucket" in str(exc_info.value)

    def test_getattr_different_names(self):
        """Test __getattr__ creates different instances for different names."""
        mock_config = Mock()
        store = AttributeListStore(
            actor_id="test_actor", bucket="test_bucket", config=mock_config
        )

        prop1 = store.list1
        prop2 = store.list2

        assert prop1.name == "list1"
        assert prop2.name == "list2"
        assert prop1 is not prop2
