"""Tests for attribute_list module."""

from unittest.mock import Mock

import pytest

from actingweb.attribute_list import ListAttribute, ListAttributeIterator


class TestListAttributeInitialization:
    """Test ListAttribute class initialization."""

    def test_init_with_all_params(self):
        """Test initialization with actor_id, bucket, name, config."""
        mock_config = object()
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=mock_config,
        )

        assert attr_list.actor_id == "test_actor"
        assert attr_list.bucket == "test_bucket"
        assert attr_list.name == "test_list"
        assert attr_list.config == mock_config
        assert attr_list._meta_cache is None

    def test_init_without_config(self):
        """Test initialization without config (no database)."""
        attr_list = ListAttribute(
            actor_id="test_actor", bucket="test_bucket", name="test_list", config=None
        )

        assert attr_list.actor_id == "test_actor"
        assert attr_list.bucket == "test_bucket"
        assert attr_list.name == "test_list"
        assert attr_list.config is None

    def test_get_meta_attribute_name(self):
        """Test _get_meta_attribute_name() returns 'list:{name}:meta'."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="my_list",
            config=None,
        )

        assert attr_list._get_meta_attribute_name() == "list:my_list:meta"

    def test_get_item_attribute_name(self):
        """Test _get_item_attribute_name(index) returns 'list:{name}:{index}'."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="my_list",
            config=None,
        )

        assert attr_list._get_item_attribute_name(0) == "list:my_list:0"
        assert attr_list._get_item_attribute_name(5) == "list:my_list:5"
        assert attr_list._get_item_attribute_name(42) == "list:my_list:42"


class TestListAttributeMetadata:
    """Test ListAttribute metadata operations."""

    def test_create_default_metadata(self):
        """Test _create_default_metadata() returns proper structure."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        meta = attr_list._create_default_metadata()

        required_fields = [
            "length",
            "created_at",
            "updated_at",
            "item_type",
            "chunk_size",
            "version",
            "description",
            "explanation",
        ]
        for field in required_fields:
            assert field in meta

        assert meta["length"] == 0
        assert meta["item_type"] == "json"
        assert meta["chunk_size"] == 1
        assert meta["version"] == "1.0"
        assert meta["description"] == ""
        assert meta["explanation"] == ""

    def test_invalidate_cache(self):
        """Test _invalidate_cache() clears the metadata cache."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        attr_list._meta_cache = {"test": "data"}
        attr_list._invalidate_cache()

        assert attr_list._meta_cache is None


class TestListAttributeIterator:
    """Test ListAttributeIterator class."""

    def test_iterator_initialization(self):
        """Test ListAttributeIterator initializes correctly."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        iterator = ListAttributeIterator(attr_list)

        assert iterator.list_prop == attr_list
        assert iterator.current_index == 0

    def test_iterator_iter_returns_self(self):
        """Test __iter__ returns the iterator itself."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        iterator = ListAttributeIterator(attr_list)

        assert iterator.__iter__() is iterator


class TestListAttributeErrorHandling:
    """Test ListAttribute error handling for operations without database."""

    def test_len_without_config_returns_zero(self):
        """Test __len__ returns 0 when no config provided."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        # Without a database, metadata returns default which has length 0
        assert len(attr_list) == 0

    def test_append_without_config_raises_error(self):
        """Test append() raises RuntimeError without config."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        with pytest.raises(RuntimeError) as exc_info:
            attr_list.append({"test": "data"})

        assert "config is None" in str(exc_info.value)

    def test_getitem_without_config_raises_error(self):
        """Test __getitem__ raises RuntimeError without config."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        # Since len() returns 0, accessing any index should raise IndexError first
        with pytest.raises(IndexError):
            _ = attr_list[0]

    def test_clear_without_config_raises_error(self):
        """Test clear() raises RuntimeError without config."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        with pytest.raises(RuntimeError) as exc_info:
            attr_list.clear()

        assert "config is None" in str(exc_info.value)

    def test_get_item_attribute_name_with_negative_index_raises_error(self):
        """Test _get_item_attribute_name raises ValueError for negative index."""
        mock_config = Mock()
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=mock_config,
        )

        with pytest.raises(ValueError) as exc_info:
            attr_list._get_item_attribute_name(-1)

        assert "non-negative" in str(exc_info.value)


class TestListAttributeMetadataAccess:
    """Test public metadata access methods."""

    def test_get_metadata_returns_all_fields(self):
        """Test get_metadata() returns all metadata fields."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,  # No config means it uses defaults
        )

        metadata = attr_list.get_metadata()

        # Check all required fields are present
        assert "created_at" in metadata
        assert "updated_at" in metadata
        assert "version" in metadata
        assert "item_type" in metadata
        assert "chunk_size" in metadata
        assert "length" in metadata

        # Check types and default values
        assert isinstance(metadata["created_at"], str)
        assert isinstance(metadata["updated_at"], str)
        assert metadata["version"] == "1.0"
        assert metadata["item_type"] == "json"
        assert metadata["chunk_size"] == 1
        assert metadata["length"] == 0

    def test_get_metadata_returns_copy(self):
        """Test get_metadata() returns a copy that doesn't affect stored metadata."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        metadata1 = attr_list.get_metadata()
        metadata1["length"] = 999  # Modify the copy

        metadata2 = attr_list.get_metadata()
        assert metadata2["length"] == 0  # Original unchanged

    def test_get_metadata_excludes_description_and_explanation(self):
        """Test get_metadata() excludes description/explanation (have dedicated methods)."""
        attr_list = ListAttribute(
            actor_id="test_actor",
            bucket="test_bucket",
            name="test_list",
            config=None,
        )

        metadata = attr_list.get_metadata()

        # These should not be in get_metadata() output
        assert "description" not in metadata
        assert "explanation" not in metadata
