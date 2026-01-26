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


class TestPropertyListCollisionDetection:
    """Test property/list name collision detection and resolution."""

    def test_list_creation_raises_error_when_property_exists(self):
        """When a list is created and a property exists, raise ValueError."""
        mock_config = Mock()
        mock_db = Mock()
        mock_config.DbProperty.DbProperty.return_value = mock_db

        # Simulate: no list metadata exists, but property exists
        mock_db.get.side_effect = [
            None,  # First call: no list metadata
            "existing_property_value",  # Second call: property exists
        ]

        prop_list = ListProperty(
            actor_id="test_actor", name="collision_name", config=mock_config
        )

        # Access metadata to trigger collision check - should raise ValueError
        import pytest

        with pytest.raises(ValueError) as exc_info:
            _ = prop_list._load_metadata()

        assert "Cannot create list 'collision_name'" in str(exc_info.value)
        assert "property with this name already exists" in str(exc_info.value)

    def test_list_creation_proceeds_when_no_property_exists(self):
        """When a list is created and no property exists, creation proceeds normally."""
        mock_config = Mock()
        mock_db = Mock()
        mock_config.DbProperty.DbProperty.return_value = mock_db

        # Simulate: no list metadata, no property exists
        mock_db.get.return_value = None

        prop_list = ListProperty(
            actor_id="test_actor", name="new_list", config=mock_config
        )

        # Access metadata to trigger check - should succeed
        metadata = prop_list._load_metadata()

        # Verify metadata was created with defaults
        assert metadata["length"] == 0
        assert "created_at" in metadata

    def test_property_set_raises_error_when_list_exists(self):
        """When setting a property and a list exists, raise ValueError."""
        from actingweb.property import PropertyStore

        mock_config = Mock()
        mock_db = Mock()
        mock_config.DbProperty.DbProperty.return_value = mock_db

        # Create a PropertyStore
        store = PropertyStore(actor_id="test_actor", config=mock_config)

        # Mock PropertyListStore.exists() to return True (list exists)
        from unittest.mock import patch

        import pytest

        with patch(
            "actingweb.property.PropertyListStore.exists", return_value=True
        ) as mock_exists:
            # Try to set a property with same name as existing list - should raise
            with pytest.raises(ValueError) as exc_info:
                store.collision_name = "some_value"

            # Verify exists() was called to check for list
            mock_exists.assert_called_once_with("collision_name")

            # Verify error message
            assert "Cannot create property 'collision_name'" in str(exc_info.value)
            assert "list with this name already exists" in str(exc_info.value)

    def test_property_set_proceeds_when_no_list_exists(self):
        """When setting a property and no list exists, property is set normally."""
        from actingweb.property import PropertyStore

        mock_config = Mock()
        mock_db = Mock()
        mock_config.DbProperty.DbProperty.return_value = mock_db

        store = PropertyStore(actor_id="test_actor", config=mock_config)

        # Mock PropertyListStore.exists() to return False (no list exists)
        from unittest.mock import patch

        with patch(
            "actingweb.property.PropertyListStore.exists", return_value=False
        ) as mock_exists:
            # Set a property - should succeed
            store.normal_property = "some_value"

            # Verify exists() was called to check for list
            mock_exists.assert_called_once_with("normal_property")

            # Verify property WAS set in database
            mock_db.set.assert_called_once()
            call_args = mock_db.set.call_args[1]
            assert call_args["name"] == "normal_property"
            assert call_args["value"] == "some_value"
