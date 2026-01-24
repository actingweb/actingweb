"""Tests for property_list module."""

from unittest.mock import Mock

from actingweb.property_list import ListProperty


class TestListPropertyMetadataAccess:
    """Test public metadata access methods."""

    def test_get_metadata_returns_all_fields(self):
        """Test get_metadata() returns all metadata fields."""
        mock_config = Mock()
        mock_db = Mock()
        mock_config.DbProperty.DbProperty.return_value = mock_db
        mock_db.get.return_value = None  # No existing metadata

        prop_list = ListProperty(
            actor_id="test_actor", name="test_list", config=mock_config
        )

        metadata = prop_list.get_metadata()

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
        mock_config = Mock()
        mock_db = Mock()
        mock_config.DbProperty.DbProperty.return_value = mock_db
        mock_db.get.return_value = None

        prop_list = ListProperty(
            actor_id="test_actor", name="test_list", config=mock_config
        )

        metadata1 = prop_list.get_metadata()
        metadata1["length"] = 999  # Modify the copy

        metadata2 = prop_list.get_metadata()
        assert metadata2["length"] == 0  # Original unchanged

    def test_get_metadata_excludes_description_and_explanation(self):
        """Test get_metadata() excludes description/explanation (have dedicated methods)."""
        mock_config = Mock()
        mock_db = Mock()
        mock_config.DbProperty.DbProperty.return_value = mock_db
        mock_db.get.return_value = None

        prop_list = ListProperty(
            actor_id="test_actor", name="test_list", config=mock_config
        )

        metadata = prop_list.get_metadata()

        # These should not be in get_metadata() output
        assert "description" not in metadata
        assert "explanation" not in metadata
