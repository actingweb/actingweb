"""
Test property lookup table functionality.

Tests cover:
- DbPropertyLookup basic operations (get, create, delete)
- Property reverse lookup with lookup table
- Configuration-based indexing
- Dual-mode operation (lookup table vs legacy GSI/index)
- Error handling and best-effort consistency
- Cleanup on actor deletion

NOTE: These tests require the database backend to be available:
- DynamoDB: Requires DynamoDB local running on localhost:8001
- PostgreSQL: Requires PostgreSQL running with configured connection details
"""

import importlib
import uuid

import pytest

from actingweb.config import Config


def get_db_module(backend: str, module: str):
    """Import database module for the specified backend."""
    return importlib.import_module(f"actingweb.db.{backend}.{module}")


@pytest.fixture
def test_actor_id():
    """Generate a unique actor ID for each test."""
    return str(uuid.uuid4())


@pytest.fixture
def config_with_lookup_table(monkeypatch):
    """Configure environment to use lookup table."""
    monkeypatch.setenv("USE_PROPERTY_LOOKUP_TABLE", "true")
    monkeypatch.setenv("INDEXED_PROPERTIES", "oauthId,email,externalUserId")
    # Clear config singleton to force reload
    if hasattr(Config, "_instance"):
        delattr(Config, "_instance")
    yield
    # Cleanup
    if hasattr(Config, "_instance"):
        delattr(Config, "_instance")


@pytest.fixture
def config_with_legacy_index(monkeypatch):
    """Configure environment to use legacy GSI/index."""
    monkeypatch.setenv("USE_PROPERTY_LOOKUP_TABLE", "false")
    # Clear config singleton to force reload
    if hasattr(Config, "_instance"):
        delattr(Config, "_instance")
    yield
    # Cleanup
    if hasattr(Config, "_instance"):
        delattr(Config, "_instance")


@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
class TestPropertyLookupBasicOperations:
    """Test basic DbPropertyLookup operations."""

    def test_create_and_get_lookup(self, backend: str, test_actor_id: str):
        """Test creating and retrieving a lookup entry."""
        lookup_mod = get_db_module(backend, "property_lookup")

        # Create lookup entry
        lookup1 = lookup_mod.DbPropertyLookup()
        result = lookup1.create(
            property_name="oauthId", value="github:12345", actor_id=test_actor_id
        )
        assert result is True, "Create should succeed"

        # Retrieve lookup entry
        lookup2 = lookup_mod.DbPropertyLookup()
        actor_id = lookup2.get(property_name="oauthId", value="github:12345")
        assert actor_id == test_actor_id, f"Expected {test_actor_id}, got {actor_id}"

        # Cleanup
        lookup2.delete()

    def test_get_nonexistent_lookup(self, backend: str):
        """Test retrieving a non-existent lookup entry."""
        lookup_mod = get_db_module(backend, "property_lookup")

        lookup = lookup_mod.DbPropertyLookup()
        actor_id = lookup.get(property_name="nonexistent", value="nonexistent_value")
        assert actor_id is None, "Non-existent lookup should return None"

    def test_delete_lookup(self, backend: str, test_actor_id: str):
        """Test deleting a lookup entry."""
        lookup_mod = get_db_module(backend, "property_lookup")

        # Create lookup entry
        lookup1 = lookup_mod.DbPropertyLookup()
        lookup1.create(
            property_name="email", value="test@example.com", actor_id=test_actor_id
        )

        # Delete lookup entry
        lookup2 = lookup_mod.DbPropertyLookup()
        lookup2.get(property_name="email", value="test@example.com")
        result = lookup2.delete()
        assert result is True, "Delete should succeed"

        # Verify deletion
        lookup3 = lookup_mod.DbPropertyLookup()
        actor_id = lookup3.get(property_name="email", value="test@example.com")
        assert actor_id is None, "Deleted lookup should not be found"

    def test_create_duplicate_lookup(self, backend: str, test_actor_id: str):
        """Test creating a duplicate lookup entry (should handle gracefully)."""
        lookup_mod = get_db_module(backend, "property_lookup")

        # Create first entry
        lookup1 = lookup_mod.DbPropertyLookup()
        result1 = lookup1.create(
            property_name="oauthId", value="duplicate_value", actor_id=test_actor_id
        )
        assert result1 is True

        # Try to create duplicate (should fail or be ignored)
        other_actor_id = str(uuid.uuid4())
        lookup2 = lookup_mod.DbPropertyLookup()
        _result2 = lookup2.create(
            property_name="oauthId", value="duplicate_value", actor_id=other_actor_id
        )
        # Should fail (DynamoDB) or be ignored (PostgreSQL ON CONFLICT DO NOTHING)
        # Both backends should not overwrite the original entry

        # Verify original entry is still there
        lookup3 = lookup_mod.DbPropertyLookup()
        found_actor_id = lookup3.get(property_name="oauthId", value="duplicate_value")
        assert found_actor_id == test_actor_id, "Original entry should be preserved"

        # Cleanup
        lookup3.delete()


@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
class TestPropertyReverseLookuWithLookupTable:
    """Test property reverse lookup using lookup table."""

    def test_reverse_lookup_with_lookup_table_enabled(
        self, backend: str, test_actor_id: str, config_with_lookup_table
    ):
        """Test reverse lookup when lookup table is enabled."""
        property_mod = get_db_module(backend, "property")

        # Set an indexed property
        prop = property_mod.DbProperty()
        prop.set(actor_id=test_actor_id, name="oauthId", value="github:67890")

        # Reverse lookup should use lookup table
        prop2 = property_mod.DbProperty()
        found_actor_id = prop2.get_actor_id_from_property(
            name="oauthId", value="github:67890"
        )
        assert found_actor_id == test_actor_id, (
            f"Expected {test_actor_id}, got {found_actor_id}"
        )

        # Cleanup
        prop2.delete()

    def test_reverse_lookup_with_legacy_index_enabled(
        self, backend: str, test_actor_id: str, config_with_legacy_index
    ):
        """Test reverse lookup when legacy index is enabled."""
        property_mod = get_db_module(backend, "property")

        # Set a property
        prop = property_mod.DbProperty()
        prop.set(actor_id=test_actor_id, name="oauthId", value="github:11111")

        # Reverse lookup should use legacy index/GSI
        prop2 = property_mod.DbProperty()
        found_actor_id = prop2.get_actor_id_from_property(
            name="oauthId", value="github:11111"
        )
        assert found_actor_id == test_actor_id, (
            f"Expected {test_actor_id}, got {found_actor_id}"
        )

        # Cleanup
        prop2.delete()

    def test_indexed_property_creates_lookup_entry(
        self, backend: str, test_actor_id: str, config_with_lookup_table
    ):
        """Test that setting an indexed property creates a lookup entry."""
        property_mod = get_db_module(backend, "property")
        lookup_mod = get_db_module(backend, "property_lookup")

        # Set an indexed property
        prop = property_mod.DbProperty()
        prop.set(actor_id=test_actor_id, name="email", value="user@example.com")

        # Verify lookup entry was created
        lookup = lookup_mod.DbPropertyLookup()
        found_actor_id = lookup.get(property_name="email", value="user@example.com")
        assert found_actor_id == test_actor_id, "Lookup entry should be created"

        # Cleanup
        prop.delete()
        # Verify lookup entry was also deleted
        lookup2 = lookup_mod.DbPropertyLookup()
        found_actor_id2 = lookup2.get(property_name="email", value="user@example.com")
        assert found_actor_id2 is None, "Lookup entry should be deleted with property"

    def test_non_indexed_property_no_lookup_entry(
        self, backend: str, test_actor_id: str, config_with_lookup_table
    ):
        """Test that setting a non-indexed property does not create a lookup entry."""
        property_mod = get_db_module(backend, "property")
        lookup_mod = get_db_module(backend, "property_lookup")

        # Set a non-indexed property
        prop = property_mod.DbProperty()
        prop.set(actor_id=test_actor_id, name="notIndexed", value="some_value")

        # Verify no lookup entry was created
        lookup = lookup_mod.DbPropertyLookup()
        found_actor_id = lookup.get(property_name="notIndexed", value="some_value")
        assert found_actor_id is None, (
            "No lookup entry should be created for non-indexed property"
        )

        # Cleanup
        prop.delete()

    def test_update_indexed_property_updates_lookup(
        self, backend: str, test_actor_id: str, config_with_lookup_table
    ):
        """Test that updating an indexed property updates the lookup entry."""
        property_mod = get_db_module(backend, "property")
        lookup_mod = get_db_module(backend, "property_lookup")

        # Set initial value
        prop = property_mod.DbProperty()
        prop.set(actor_id=test_actor_id, name="email", value="old@example.com")

        # Verify initial lookup
        lookup1 = lookup_mod.DbPropertyLookup()
        found1 = lookup1.get(property_name="email", value="old@example.com")
        assert found1 == test_actor_id

        # Update to new value
        prop.set(actor_id=test_actor_id, name="email", value="new@example.com")

        # Verify old lookup is gone
        lookup2 = lookup_mod.DbPropertyLookup()
        found2 = lookup2.get(property_name="email", value="old@example.com")
        assert found2 is None, "Old lookup entry should be deleted"

        # Verify new lookup exists
        lookup3 = lookup_mod.DbPropertyLookup()
        found3 = lookup3.get(property_name="email", value="new@example.com")
        assert found3 == test_actor_id, "New lookup entry should be created"

        # Cleanup
        prop.delete()

    def test_delete_indexed_property_deletes_lookup(
        self, backend: str, test_actor_id: str, config_with_lookup_table
    ):
        """Test that deleting an indexed property deletes the lookup entry."""
        property_mod = get_db_module(backend, "property")
        lookup_mod = get_db_module(backend, "property_lookup")

        # Set property
        prop = property_mod.DbProperty()
        prop.set(actor_id=test_actor_id, name="externalUserId", value="ext123")

        # Verify lookup exists
        lookup1 = lookup_mod.DbPropertyLookup()
        found1 = lookup1.get(property_name="externalUserId", value="ext123")
        assert found1 == test_actor_id

        # Delete property
        prop.delete()

        # Verify lookup is gone
        lookup2 = lookup_mod.DbPropertyLookup()
        found2 = lookup2.get(property_name="externalUserId", value="ext123")
        assert found2 is None, "Lookup entry should be deleted"


@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
class TestPropertyListCleanup:
    """Test bulk property cleanup with lookup entries."""

    def test_delete_all_properties_deletes_lookup_entries(
        self, backend: str, test_actor_id: str, config_with_lookup_table
    ):
        """Test that deleting all properties also deletes all lookup entries."""
        property_mod = get_db_module(backend, "property")
        lookup_mod = get_db_module(backend, "property_lookup")

        # Set multiple indexed properties
        prop1 = property_mod.DbProperty()
        prop1.set(actor_id=test_actor_id, name="oauthId", value="github:99999")

        prop2 = property_mod.DbProperty()
        prop2.set(actor_id=test_actor_id, name="email", value="bulk@example.com")

        prop3 = property_mod.DbProperty()
        prop3.set(actor_id=test_actor_id, name="externalUserId", value="ext999")

        # Verify lookup entries exist
        lookup1 = lookup_mod.DbPropertyLookup()
        assert (
            lookup1.get(property_name="oauthId", value="github:99999") == test_actor_id
        )
        lookup2 = lookup_mod.DbPropertyLookup()
        assert (
            lookup2.get(property_name="email", value="bulk@example.com")
            == test_actor_id
        )
        lookup3 = lookup_mod.DbPropertyLookup()
        assert (
            lookup3.get(property_name="externalUserId", value="ext999") == test_actor_id
        )

        # Delete all properties
        prop_list = property_mod.DbPropertyList()
        prop_list.fetch(actor_id=test_actor_id)
        prop_list.delete()

        # Verify all lookup entries are gone
        lookup4 = lookup_mod.DbPropertyLookup()
        assert lookup4.get(property_name="oauthId", value="github:99999") is None
        lookup5 = lookup_mod.DbPropertyLookup()
        assert lookup5.get(property_name="email", value="bulk@example.com") is None
        lookup6 = lookup_mod.DbPropertyLookup()
        assert lookup6.get(property_name="externalUserId", value="ext999") is None


@pytest.mark.parametrize("backend", ["dynamodb", "postgresql"])
class TestLargeValueSupport:
    """Test that lookup table supports large property values."""

    def test_large_property_value_with_lookup_table(
        self, backend: str, test_actor_id: str, config_with_lookup_table
    ):
        """Test that large property values work with lookup table (no size limit)."""
        property_mod = get_db_module(backend, "property")

        # Create a large value (>2048 bytes, which would fail with GSI)
        large_value = "x" * 5000

        # Set property with large value
        prop = property_mod.DbProperty()
        result = prop.set(actor_id=test_actor_id, name="oauthId", value=large_value)
        assert result is True, "Should be able to set large value"

        # Verify reverse lookup works
        prop2 = property_mod.DbProperty()
        found_actor_id = prop2.get_actor_id_from_property(
            name="oauthId", value=large_value
        )
        assert found_actor_id == test_actor_id, "Should find actor by large value"

        # Cleanup
        prop2.delete()


class TestConfigurationIntegration:
    """Test configuration-based property indexing."""

    def test_config_from_environment_variables(self, monkeypatch):
        """Test that configuration reads from environment variables."""
        monkeypatch.setenv("USE_PROPERTY_LOOKUP_TABLE", "true")
        monkeypatch.setenv("INDEXED_PROPERTIES", "custom1,custom2,custom3")

        # Clear config singleton
        if hasattr(Config, "_instance"):
            delattr(Config, "_instance")

        config = Config()
        assert config.use_lookup_table is True
        assert "custom1" in config.indexed_properties
        assert "custom2" in config.indexed_properties
        assert "custom3" in config.indexed_properties

    def test_config_defaults(self):
        """Test that configuration has sensible defaults."""
        # Clear config singleton
        if hasattr(Config, "_instance"):
            delattr(Config, "_instance")

        config = Config()
        # Default should be False for backward compatibility
        assert config.use_lookup_table is False
        # Default indexed properties
        assert "oauthId" in config.indexed_properties
        assert "email" in config.indexed_properties
        assert "externalUserId" in config.indexed_properties
