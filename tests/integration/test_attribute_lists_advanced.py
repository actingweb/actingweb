"""
Attribute Lists Advanced Tests.

Tests attribute list operations for internal storage:
- Dynamic attribute list creation with arbitrary names
- Metadata storage and retrieval patterns
- list_all() discovery functionality
- exists() checks
- Complete list deletion
- Item deletion by index
- Bucket isolation

These tests verify ListAttribute provides the same functionality as
ListProperty but using internal attributes storage instead of properties.

References:
- actingweb/attribute_list.py - ListAttribute implementation
- actingweb/attribute_list_store.py - AttributeListStore implementation
- actingweb/property_list.py - ListProperty (pattern to mirror)
"""

import os

import pytest

from actingweb.attribute_list_store import AttributeListStore
from actingweb.interface.actor_interface import ActorInterface
from actingweb.interface.app import ActingWebApp

# Get database backend from environment (set by conftest.py)
DATABASE_BACKEND = os.environ.get("DATABASE_BACKEND", "dynamodb")


@pytest.fixture
def aw_app(docker_services, setup_database, worker_info):  # noqa: ARG001
    """Create ActingWeb app for testing."""
    # Set up environment for PostgreSQL schema isolation
    if DATABASE_BACKEND == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    return ActingWebApp(
        aw_type="urn:actingweb:test:attribute_lists",
        database=DATABASE_BACKEND,
        fqdn="test.example.com",
        proto="http://",
    )


@pytest.fixture
def test_actor(aw_app):
    """Create a test actor with automatic cleanup."""
    config = aw_app.get_config()
    actor = ActorInterface.create(
        creator="test@example.com",
        config=config,
    )
    yield actor
    # Cleanup
    try:
        actor.delete()
    except Exception:
        pass


class TestListAttributeDynamicCreation:
    """Test dynamic creation and access of attribute lists."""

    def test_create_multiple_attribute_lists_dynamically(self, test_actor):
        """
        Test that attribute lists can be created dynamically with any name.

        Similar to property lists, but stored in internal attributes.
        """
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        # Create multiple attribute lists dynamically
        memory_types = [
            "memory_personal",
            "memory_travel",
            "memory_food",
            "memory_health",
            "memory_work",
        ]

        for memory_type in memory_types:
            attr_list = getattr(store, memory_type)
            attr_list.append(
                {
                    "id": 1,
                    "content": f"Test data for {memory_type}",
                    "created_at": "2025-10-03T10:00:00",
                }
            )

        # Verify all exist
        all_lists = store.list_all()
        for memory_type in memory_types:
            assert memory_type in all_lists, (
                f"Expected {memory_type} in list_all() output"
            )

        # Verify content retrieval
        personal_list = store.memory_personal
        items = personal_list.to_list()
        assert len(items) == 1
        assert items[0]["content"] == "Test data for memory_personal"

    def test_attribute_list_names_with_special_characters(self, test_actor):
        """
        Test attribute lists with various naming patterns.
        """
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        test_names = [
            "memory_test_123",
            "memory_user_defined_type",
            "notes_2025",
            "list_with_numbers_456",
        ]

        for name in test_names:
            attr_list = getattr(store, name)
            attr_list.append({"data": f"test_{name}"})

        all_lists = store.list_all()
        for name in test_names:
            assert name in all_lists


class TestListAttributeMetadataStorage:
    """Test metadata storage pattern for attribute lists."""

    def test_description_and_explanation_persist(self, test_actor):
        """Test get/set description and explanation."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.memory_travel

        # Set metadata
        attr_list.set_description("Travel memories and plans")
        attr_list.set_explanation("Stores travel-related information")

        # Add some items
        attr_list.append({"id": 1, "content": "Paris trip 2025"})

        # Verify metadata persists
        assert attr_list.get_description() == "Travel memories and plans"
        assert attr_list.get_explanation() == "Stores travel-related information"

    def test_metadata_accessible_with_many_items(self, test_actor):
        """Test metadata retrieval with 100+ items."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.memory_notes

        # Set metadata
        attr_list.set_description("Quick notes")
        attr_list.set_explanation("Short notes and reminders")

        # Add 100 data items
        for i in range(100):
            attr_list.append({"id": i + 1, "content": f"Note {i + 1}"})

        # Metadata should still be accessible
        assert attr_list.get_description() == "Quick notes"
        assert attr_list.get_explanation() == "Short notes and reminders"
        assert len(attr_list) == 100


class TestListAttributeDiscovery:
    """Test list_all() and exists() methods for attribute list discovery."""

    def test_list_all_returns_all_lists(self, test_actor):
        """Test list_all() discovers all attribute lists in bucket."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        # Create several attribute lists
        memory_types = ["memory_personal", "memory_travel", "memory_food"]
        for memory_type in memory_types:
            attr_list = getattr(store, memory_type)
            attr_list.append({"content": "test"})

        # list_all() should return all of them
        all_lists = store.list_all()
        assert len(all_lists) >= 3
        for memory_type in memory_types:
            assert memory_type in all_lists

    def test_exists_check(self, test_actor):
        """Test exists() accurately reports list existence."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        # Non-existent list
        assert not store.exists("memory_nonexistent")

        # Create list by accessing and appending
        attr_list = store.memory_test
        attr_list.append({"data": "test"})

        # Should now exist
        assert store.exists("memory_test")

        # Still shouldn't exist for different name
        assert not store.exists("memory_other")

    def test_exists_false_for_accessed_but_empty(self, test_actor):
        """Test exists() returns False for lists never populated."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        # Access list but don't append anything
        _ = store.memory_empty  # noqa: F841

        # Should not exist because no items were appended (no metadata created)
        assert not store.exists("memory_empty")


class TestListAttributeDeletion:
    """Test attribute list deletion operations."""

    def test_complete_list_deletion(self, test_actor):
        """Test that attribute lists can be completely deleted."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        # Create and populate attribute list
        attr_list = store.memory_temp
        attr_list.append({"id": 1, "content": "temp data 1"})
        attr_list.append({"id": 2, "content": "temp data 2"})
        attr_list.append({"id": 3, "content": "temp data 3"})

        # Verify it exists
        assert store.exists("memory_temp")
        all_lists_before = store.list_all()
        assert "memory_temp" in all_lists_before

        # Delete the entire list
        attr_list.delete()

        # Verify deletion
        assert not store.exists("memory_temp")
        all_lists_after = store.list_all()
        assert "memory_temp" not in all_lists_after

    def test_delete_item_by_index(self, test_actor):
        """Test deleting items from attribute list by index."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.memory_notes

        # Add multiple items
        for i in range(5):
            attr_list.append({"id": i + 1, "content": f"Note {i + 1}"})

        # Verify initial state
        items = attr_list.to_list()
        assert len(items) == 5
        assert items[2]["content"] == "Note 3"

        # Delete item at index 2 (third item)
        del attr_list[2]

        # Verify deletion and shift
        items_after = attr_list.to_list()
        assert len(items_after) == 4
        # Item at index 2 should now be the old item 4 (shifted down)
        assert items_after[2]["content"] == "Note 4"
        # Item 3 should no longer exist
        contents = [item["content"] for item in items_after]
        assert "Note 3" not in contents


class TestListAttributeLargeData:
    """Test attribute lists with large amounts of data."""

    def test_list_with_100_items(self, test_actor):
        """Test list operations with 100 items."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.large_list

        # Add 100 items
        for i in range(100):
            attr_list.append({"id": i + 1, "content": f"Item {i + 1}"})

        # Verify length
        assert len(attr_list) == 100

        # Verify retrieval works
        items = attr_list.to_list()
        assert len(items) == 100
        assert items[0]["content"] == "Item 1"
        assert items[99]["content"] == "Item 100"

    def test_multiple_large_lists(self, test_actor):
        """Test multiple lists each with many items."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        # Create 3 lists with 50 items each
        for list_num in range(3):
            list_name = f"list_{list_num}"
            attr_list = getattr(store, list_name)
            for i in range(50):
                attr_list.append({"list": list_num, "item": i + 1})

        # Verify all exist
        all_lists = store.list_all()
        assert "list_0" in all_lists
        assert "list_1" in all_lists
        assert "list_2" in all_lists

        # Verify lengths
        assert len(store.list_0) == 50
        assert len(store.list_1) == 50
        assert len(store.list_2) == 50

    def test_large_item_content(self, test_actor):
        """Test items with large JSON content."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.large_items

        # Create item with large content
        large_content = "x" * 10000  # 10KB string
        attr_list.append(
            {
                "id": 1,
                "content": large_content,
                "metadata": {"description": "Large item"},
            }
        )

        # Verify retrieval
        items = attr_list.to_list()
        assert len(items) == 1
        assert len(items[0]["content"]) == 10000


class TestListAttributeBucketIsolation:
    """Test that lists in different buckets are isolated."""

    def test_lists_in_different_buckets_isolated(self, test_actor):
        """Test lists in different buckets don't interfere."""
        config = test_actor.config

        # Create stores for different buckets
        store1 = AttributeListStore(
            actor_id=test_actor.id, bucket="bucket1", config=config
        )
        store2 = AttributeListStore(
            actor_id=test_actor.id, bucket="bucket2", config=config
        )

        # Add items to same list name in different buckets
        store1.my_list.append({"bucket": 1, "data": "bucket1 data"})
        store2.my_list.append({"bucket": 2, "data": "bucket2 data"})

        # Verify isolation
        items1 = store1.my_list.to_list()
        items2 = store2.my_list.to_list()

        assert len(items1) == 1
        assert len(items2) == 1
        assert items1[0]["bucket"] == 1
        assert items2[0]["bucket"] == 2

    def test_same_list_name_in_different_buckets(self, test_actor):
        """Test same list name can exist independently in different buckets."""
        config = test_actor.config

        # Create stores for different buckets
        store_cache = AttributeListStore(
            actor_id=test_actor.id, bucket="cache", config=config
        )
        store_state = AttributeListStore(
            actor_id=test_actor.id, bucket="state", config=config
        )

        # Create "history" list in both buckets
        store_cache.history.append({"type": "cache", "item": 1})
        store_cache.history.append({"type": "cache", "item": 2})

        store_state.history.append({"type": "state", "item": 1})
        store_state.history.append({"type": "state", "item": 2})
        store_state.history.append({"type": "state", "item": 3})

        # Verify different lengths
        assert len(store_cache.history) == 2
        assert len(store_state.history) == 3

        # Verify list_all() shows the list in each bucket
        assert "history" in store_cache.list_all()
        assert "history" in store_state.list_all()


class TestListAttributeOperations:
    """Test various list operations."""

    def test_pop_operation(self, test_actor):
        """Test pop() removes and returns items."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.test_list
        attr_list.append({"id": 1})
        attr_list.append({"id": 2})
        attr_list.append({"id": 3})

        # Pop last item
        item = attr_list.pop()
        assert item["id"] == 3
        assert len(attr_list) == 2

        # Pop specific index
        item = attr_list.pop(0)
        assert item["id"] == 1
        assert len(attr_list) == 1

    def test_insert_operation(self, test_actor):
        """Test insert() adds items at specific positions."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.test_list
        attr_list.append({"id": 1})
        attr_list.append({"id": 3})

        # Insert at index 1
        attr_list.insert(1, {"id": 2})

        items = attr_list.to_list()
        assert len(items) == 3
        assert items[0]["id"] == 1
        assert items[1]["id"] == 2
        assert items[2]["id"] == 3

    def test_clear_operation(self, test_actor):
        """Test clear() removes all items but preserves metadata."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.test_list
        attr_list.set_description("Test list")
        attr_list.append({"id": 1})
        attr_list.append({"id": 2})

        # Clear the list
        attr_list.clear()

        # List should be empty
        assert len(attr_list) == 0
        items = attr_list.to_list()
        assert items == []

        # But metadata still exists (list exists)
        assert store.exists("test_list")

    def test_slice_operation(self, test_actor):
        """Test slice() returns range of items."""
        config = test_actor.config
        store = AttributeListStore(
            actor_id=test_actor.id, bucket="test_bucket", config=config
        )

        attr_list = store.test_list
        for i in range(10):
            attr_list.append({"id": i})

        # Get slice
        items = attr_list.slice(2, 5)
        assert len(items) == 3
        assert items[0]["id"] == 2
        assert items[1]["id"] == 3
        assert items[2]["id"] == 4
