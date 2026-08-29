"""
Property Lists Advanced Tests.

Tests property list operations critical for actingweb_mcp memory storage:
- Dynamic property list creation with arbitrary names
- Metadata storage and retrieval patterns
- list_all() discovery functionality
- exists() checks
- Complete list deletion
- Item deletion by index

These tests protect actingweb_mcp from regressions when improving ActingWeb.

References:
- actingweb/property_list.py:39-430 - ListProperty implementation
- actingweb/property.py:5-56 - PropertyListStore implementation
- actingweb_mcp uses these patterns extensively for memory storage
"""

import os

import pytest

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
        aw_type="urn:actingweb:test:property_lists",
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


class TestPropertyListDynamicCreation:
    """Test dynamic creation and access of property lists."""

    def test_create_multiple_property_lists_dynamically(self, test_actor):
        """
        Test that property lists can be created dynamically with any name.

        actingweb_mcp creates memory_personal, memory_travel, memory_food, etc.
        on-demand without pre-registration.

        Spec: actingweb/property_list.py:46-56 - __getattr__ pattern
        """
        # Create multiple property lists dynamically (actingweb_mcp pattern)
        memory_types = [
            "memory_personal",
            "memory_travel",
            "memory_food",
            "memory_health",
            "memory_work",
        ]

        for memory_type in memory_types:
            prop_list = getattr(test_actor.property_lists, memory_type)
            prop_list.append(
                {
                    "id": 1,
                    "content": f"Test data for {memory_type}",
                    "created_at": "2025-10-03T10:00:00",
                }
            )

        # Verify all exist
        all_lists = test_actor.property_lists.list_all()
        for memory_type in memory_types:
            assert memory_type in all_lists, (
                f"Expected {memory_type} in list_all() output"
            )

        # Verify content retrieval
        personal_list = test_actor.property_lists.memory_personal
        items = personal_list.to_list()
        assert len(items) == 1
        assert items[0]["content"] == "Test data for memory_personal"

    def test_property_list_names_with_underscores_and_numbers(self, test_actor):
        """
        Test property lists with various naming patterns.

        actingweb_mcp allows user-created memory types with custom names.

        Spec: actingweb/property_list.py:48 - All names are valid except _*
        """
        test_names = [
            "memory_test_123",
            "memory_user_defined_type",
            "notes_2025",
            "list_with_numbers_456",
        ]

        for name in test_names:
            prop_list = getattr(test_actor.property_lists, name)
            prop_list.append({"data": f"test_{name}"})

        all_lists = test_actor.property_lists.list_all()
        for name in test_names:
            assert name in all_lists


class TestPropertyListMetadataStorage:
    """Test metadata storage pattern used by actingweb_mcp."""

    def test_metadata_as_first_item_persists(self, test_actor):
        """
        Test that metadata stored as first item persists correctly.

        actingweb_mcp stores metadata in the first item to track display_name,
        description, emoji, keywords, etc.

        Spec: actingweb_mcp uses metadata in first item pattern
        """
        prop_list = test_actor.property_lists.memory_travel

        # Store metadata as first item (actingweb_mcp pattern)
        metadata = {
            "type_name": "memory_travel",
            "display_name": "Travel Memories",
            "description": "Travel plans and memories",
            "emoji": "✈️",
            "keywords": ["flight", "hotel", "vacation", "trip"],
            "created_at": "2025-10-03T10:00:00",
            "created_by": "mcp_auto",
        }
        prop_list.insert(0, metadata)

        # Add actual data items
        prop_list.append(
            {"id": 1, "content": "Paris trip 2025", "created_at": "2025-10-03T11:00:00"}
        )
        prop_list.append(
            {
                "id": 2,
                "content": "Tokyo flight booked",
                "created_at": "2025-10-03T12:00:00",
            }
        )
        prop_list.append(
            {
                "id": 3,
                "content": "Hotel reservation confirmed",
                "created_at": "2025-10-03T13:00:00",
            }
        )

        # Retrieve and verify order is preserved
        items = prop_list.to_list()
        assert len(items) == 4

        # First item should be metadata
        assert items[0]["type_name"] == "memory_travel"
        assert items[0]["display_name"] == "Travel Memories"
        assert items[0]["emoji"] == "✈️"

        # Subsequent items should be data
        assert items[1]["content"] == "Paris trip 2025"
        assert items[2]["content"] == "Tokyo flight booked"
        assert items[3]["content"] == "Hotel reservation confirmed"

    def test_metadata_retrieval_after_many_items(self, test_actor):
        """
        Test that metadata remains accessible even with many items.

        actingweb_mcp reads metadata on every dashboard load.

        Spec: actingweb_mcp reads metadata from first item
        """
        prop_list = test_actor.property_lists.memory_notes

        # Store metadata
        metadata = {
            "type_name": "memory_notes",
            "display_name": "Quick Notes",
            "description": "Short notes and reminders",
            "created_at": "2025-10-03T10:00:00",
        }
        prop_list.insert(0, metadata)

        # Add 50 data items
        for i in range(50):
            prop_list.append({"id": i + 1, "content": f"Note {i + 1}"})

        # Metadata should still be first item
        items = prop_list.to_list()
        assert len(items) == 51
        assert items[0]["type_name"] == "memory_notes"
        assert items[0]["display_name"] == "Quick Notes"


class TestPropertyListInsertIntoNonEmptyList:
    """Regression coverage for ListProperty.insert() on a non-empty list.

    Every prior insert() test called it on an empty list (insert(0, ...) as
    the very first operation), so the shift loop ran zero iterations and
    never exercised the bug where DynamoDB's insert() reused a single
    stale DbProperty handle across the whole shift, overwriting every
    shifted row with the last value read instead of its own (see
    thoughts/research/2026-08-07-property-list-index-integrity.md). These
    assert full list content, including the last element, after inserting
    into a list with existing items.
    """

    def test_insert_at_end_minus_one_into_non_empty_list(self, test_actor):
        prop_list = test_actor.property_lists.insert_regression_a
        prop_list.append("a")
        prop_list.append("b")
        prop_list.append("c")

        prop_list.insert(1, "X")

        items = prop_list.to_list()
        assert items == ["a", "X", "b", "c"]

    def test_insert_at_zero_into_non_empty_list(self, test_actor):
        prop_list = test_actor.property_lists.insert_regression_b
        prop_list.append("a")
        prop_list.append("b")
        prop_list.append("c")

        prop_list.insert(0, "X")

        items = prop_list.to_list()
        assert items == ["X", "a", "b", "c"]


class TestPropertyListDiscovery:
    """Test list_all() and exists() methods for property list discovery."""

    def test_list_all_returns_all_property_lists(self, test_actor):
        """
        Test list_all() discovers all property lists for an actor.

        actingweb_mcp uses list_all() to display all memory types in dashboard.

        Spec: actingweb/property.py:28-44 - list_all() implementation
        """
        # Create several property lists
        memory_types = ["memory_personal", "memory_travel", "memory_food"]
        for memory_type in memory_types:
            prop_list = getattr(test_actor.property_lists, memory_type)
            prop_list.append({"content": "test"})

        # list_all() should return all of them
        all_lists = test_actor.property_lists.list_all()
        assert len(all_lists) >= 3
        for memory_type in memory_types:
            assert memory_type in all_lists

    def test_list_all_excludes_regular_properties(self, test_actor):
        """
        Test that list_all() only returns property lists, not regular properties.

        Spec: actingweb/property.py:36-38 - Filters for list:*-meta pattern
        """
        # Create property list
        prop_list = test_actor.property_lists.memory_test
        prop_list.append({"content": "test"})

        # list_all() should only return property lists
        all_lists = test_actor.property_lists.list_all()
        assert "memory_test" in all_lists

    def test_exists_check_for_property_lists(self, test_actor):
        """
        Test exists() method accurately reports property list existence.

        actingweb_mcp uses exists() to check if memory types exist before accessing.

        Spec: actingweb/property.py:17-26 - exists() implementation
        """
        # Non-existent list
        assert not test_actor.property_lists.exists("memory_nonexistent")

        # Create list by accessing and appending
        prop_list = test_actor.property_lists.memory_test
        prop_list.append({"data": "test"})

        # Should now exist
        assert test_actor.property_lists.exists("memory_test")

        # Still shouldn't exist for different name
        assert not test_actor.property_lists.exists("memory_other")

    def test_exists_returns_false_for_empty_list(self, test_actor):
        """
        Test that exists() returns False for lists that were accessed but never populated.

        Spec: actingweb/property.py:22 - Checks for metadata property
        """
        # Access list but don't append anything
        _ = test_actor.property_lists.memory_empty  # noqa: F841

        # Should not exist because no items were appended (no metadata created)
        assert not test_actor.property_lists.exists("memory_empty")


class TestPropertyListDeletion:
    """Test property list deletion operations."""

    def test_complete_list_deletion(self, test_actor):
        """
        Test that property lists can be completely deleted.

        actingweb_mcp allows users to delete entire memory types.

        Spec: actingweb/property_list.py:302-319 - delete() implementation
        """
        # Create and populate property list
        prop_list = test_actor.property_lists.memory_temp
        prop_list.append({"id": 1, "content": "temp data 1"})
        prop_list.append({"id": 2, "content": "temp data 2"})
        prop_list.append({"id": 3, "content": "temp data 3"})

        # Verify it exists
        assert test_actor.property_lists.exists("memory_temp")
        all_lists_before = test_actor.property_lists.list_all()
        assert "memory_temp" in all_lists_before

        # Delete the entire list
        prop_list.delete()

        # Verify deletion
        assert not test_actor.property_lists.exists("memory_temp")
        all_lists_after = test_actor.property_lists.list_all()
        assert "memory_temp" not in all_lists_after

    def test_delete_removes_all_items_and_metadata(self, test_actor):
        """
        Test that delete() removes all items and metadata.

        Spec: actingweb/property_list.py:310-316 - Deletes items and metadata
        """
        # Create list with many items
        prop_list = test_actor.property_lists.memory_test_delete
        for i in range(20):
            prop_list.append({"id": i + 1, "content": f"Item {i + 1}"})

        # Verify items exist
        items_before = prop_list.to_list()
        assert len(items_before) == 20

        # Delete
        prop_list.delete()

        # Recreate same list (should be empty, not contain old data)
        new_prop_list = test_actor.property_lists.memory_test_delete
        items_after = new_prop_list.to_list()
        assert len(items_after) == 0


class TestPropertyListItemDeletion:
    """Test item deletion by index."""

    def test_delete_item_by_index(self, test_actor):
        """
        Test deleting items from property list by index.

        actingweb_mcp allows users to delete individual memory items.

        Spec: actingweb/property_list.py:212-251 - __delitem__ implementation
        """
        prop_list = test_actor.property_lists.memory_notes

        # Add multiple items
        for i in range(5):
            prop_list.append({"id": i + 1, "content": f"Note {i + 1}"})

        # Verify initial state
        items = prop_list.to_list()
        assert len(items) == 5
        assert items[2]["content"] == "Note 3"

        # Delete item at index 2 (third item)
        del prop_list[2]

        # Verify deletion and shift
        items_after = prop_list.to_list()
        assert len(items_after) == 4
        # Item at index 2 should now be the old item 4 (shifted down)
        assert items_after[2]["content"] == "Note 4"
        # Item 3 should no longer exist
        contents = [item["content"] for item in items_after]
        assert "Note 3" not in contents

    def test_delete_first_item(self, test_actor):
        """
        Test deleting first item from property list.

        Note: actingweb_mcp stores metadata as first item, so this tests
        accidental deletion of metadata.

        Spec: actingweb/property_list.py:212-251 - __delitem__ with index 0
        """
        prop_list = test_actor.property_lists.memory_test

        # Add items
        prop_list.append({"id": 1, "content": "First"})
        prop_list.append({"id": 2, "content": "Second"})
        prop_list.append({"id": 3, "content": "Third"})

        # Delete first item
        del prop_list[0]

        # Verify
        items = prop_list.to_list()
        assert len(items) == 2
        assert items[0]["content"] == "Second"
        assert items[1]["content"] == "Third"

    def test_delete_last_item(self, test_actor):
        """
        Test deleting last item from property list.

        Spec: actingweb/property_list.py:212-251 - __delitem__ with last index
        """
        prop_list = test_actor.property_lists.memory_test

        # Add items
        prop_list.append({"id": 1, "content": "First"})
        prop_list.append({"id": 2, "content": "Second"})
        prop_list.append({"id": 3, "content": "Third"})

        # Delete last item (index 2 or -1)
        del prop_list[2]

        # Verify
        items = prop_list.to_list()
        assert len(items) == 2
        assert items[0]["content"] == "First"
        assert items[1]["content"] == "Second"

    def test_delete_with_negative_index(self, test_actor):
        """
        Test deleting item with negative index (Python list convention).

        Spec: actingweb/property_list.py:215-216 - Negative index support
        """
        prop_list = test_actor.property_lists.memory_test

        # Add items
        for i in range(5):
            prop_list.append({"id": i + 1, "content": f"Item {i + 1}"})

        # Delete second-to-last item (index -2)
        del prop_list[-2]

        # Verify
        items = prop_list.to_list()
        assert len(items) == 4
        # Item 4 should be gone
        contents = [item["content"] for item in items]
        assert "Item 4" not in contents
        assert "Item 5" in contents


class TestPropertyListLargeData:
    """Test property lists with large amounts of data."""

    def test_property_list_with_100_items(self, test_actor):
        """
        Test property list with 100 items (realistic for actingweb_mcp).

        actingweb_mcp users may accumulate dozens or hundreds of memories.

        Spec: actingweb/property_list.py - No size limit on lists
        """
        prop_list = test_actor.property_lists.memory_large

        # Add 100 items
        for i in range(100):
            prop_list.append(
                {
                    "id": i + 1,
                    "content": f"Memory item {i + 1}",
                    "created_at": f"2025-10-03T{i % 24:02d}:00:00",
                }
            )

        # Verify all items are stored
        items = prop_list.to_list()
        assert len(items) == 100

        # Verify order is preserved
        assert items[0]["content"] == "Memory item 1"
        assert items[50]["content"] == "Memory item 51"
        assert items[99]["content"] == "Memory item 100"

    def test_multiple_large_property_lists(self, test_actor):
        """
        Test multiple property lists each with many items.

        actingweb_mcp has 6+ predefined memory types, each potentially large.

        Spec: No limit on number of property lists per actor
        """
        memory_types = [
            "memory_personal",
            "memory_travel",
            "memory_food",
            "memory_work",
            "memory_health",
        ]

        # Create 5 lists with 20 items each
        for memory_type in memory_types:
            prop_list = getattr(test_actor.property_lists, memory_type)
            for i in range(20):
                prop_list.append(
                    {"id": i + 1, "content": f"{memory_type} item {i + 1}"}
                )

        # Verify all lists exist
        all_lists = test_actor.property_lists.list_all()
        for memory_type in memory_types:
            assert memory_type in all_lists

        # Verify item counts
        for memory_type in memory_types:
            prop_list = getattr(test_actor.property_lists, memory_type)
            items = prop_list.to_list()
            assert len(items) == 20


class TestListPrefixWithRows:
    """``list_prefix_with_rows()`` end to end against real storage on both
    backends -- the motivating case is exactly this file's subject: an
    ``actingweb_mcp``-style actor whose ``memory_*`` lists are created at
    runtime, where reading one namespace used to mean dumping the whole
    partition.
    """

    def test_reads_one_namespace_and_primes_every_list_from_the_rows(self, test_actor):
        from actingweb.property_list import ListProperty

        for name, items in (
            ("memory_personal", ["a", "b"]),
            ("memory_travel", ["c"]),
            ("notes", ["not-a-memory"]),
        ):
            prop_list = getattr(test_actor.property_lists, name)
            for item in items:
                prop_list.append(item)

        names, rows = test_actor.property_lists.list_prefix_with_rows("memory_")

        assert sorted(names) == ["memory_personal", "memory_travel"]
        assert not any(row.startswith("list:notes") for row in rows)
        # The point of returning rows: every named list reads out of them
        # without a second query per list.
        primed = {
            name: ListProperty(
                test_actor.id, name, test_actor.config
            ).to_list_from_rows(rows)
            for name in names
        }
        assert primed == {
            "memory_personal": ["a", "b"],
            "memory_travel": ["c"],
        }

    def test_a_prefix_matches_the_list_named_exactly_that_and_its_siblings(
        self, test_actor
    ):
        for name in ("memory", "memory_a", "memory-old"):
            getattr(test_actor.property_lists, name).append("x")

        broad, _ = test_actor.property_lists.list_prefix_with_rows("memory")
        narrow, _ = test_actor.property_lists.list_prefix_with_rows("memory_")

        assert sorted(broad) == ["memory", "memory-old", "memory_a"]
        assert narrow == ["memory_a"]

    def test_a_non_ascii_list_name_round_trips(self, test_actor):
        """DynamoDB's ``begins_with`` and PostgreSQL's ``starts_with()`` are
        both byte comparisons; a synthesised ``~`` upper bound would drop
        these, since ``é`` encodes above ``~``."""
        from actingweb.property_list import ListProperty

        test_actor.property_lists.mémoire_a.append("é-item")
        test_actor.property_lists.mémoire_b.append("autre")
        test_actor.property_lists.memoire_c.append("ascii")

        names, rows = test_actor.property_lists.list_prefix_with_rows("mémoire_")

        assert sorted(names) == ["mémoire_a", "mémoire_b"]
        assert ListProperty(
            test_actor.id, "mémoire_a", test_actor.config
        ).to_list_from_rows(rows) == ["é-item"]

    def test_an_underscore_is_literal_not_a_wildcard(self, test_actor):
        """Fails loudly if the PostgreSQL side is ever rewritten as
        ``LIKE prefix || '%'``."""
        test_actor.property_lists.memory_a.append("x")
        test_actor.property_lists.memoryXa.append("y")

        names, _ = test_actor.property_lists.list_prefix_with_rows("memory_")

        assert names == ["memory_a"]

    def test_nothing_matching_is_an_ordinary_empty_answer(self, test_actor):
        test_actor.property_lists.notes.append("x")

        assert test_actor.property_lists.list_prefix_with_rows("memory_") == ([], {})

    def test_an_empty_prefix_raises(self, test_actor):
        with pytest.raises(ValueError):
            test_actor.property_lists.list_prefix_with_rows("")

    def test_list_all_with_rows_still_sees_everything(self, test_actor):
        """The whole-partition method is unchanged -- the scoped one is an
        addition, not a replacement."""
        test_actor.property_lists.memory_a.append("x")
        test_actor.property_lists.notes.append("y")

        all_names, all_rows = test_actor.property_lists.list_all_with_rows()

        assert sorted(all_names) == ["memory_a", "notes"]
        assert any(row.startswith("list:notes") for row in all_rows)


class TestAuthenticatedBulkListReads:
    """``AuthenticatedPropertyListStore``'s three bulk readers over the REAL
    store, not a fake. The unit suite
    (``tests/test_authenticated_bulk_list_reads.py``) pins the filtering
    logic; this pins that the real ``PropertyListStore`` actually satisfies
    the interface those readers call, on both backends.
    """

    def _authed(self, test_actor, evaluator=None, accessor_id="peer123"):
        from unittest.mock import Mock

        from actingweb.interface.authenticated_views import (
            AuthContext,
            AuthenticatedPropertyListStore,
        )

        return AuthenticatedPropertyListStore(
            test_actor.property_lists,
            AuthContext(peer_id=accessor_id),
            test_actor.id,
            test_actor.config if evaluator is None else Mock(),
        )

    def test_all_three_readers_work_against_real_storage(self, test_actor):
        from unittest.mock import Mock, patch

        from actingweb.permission_evaluator import PermissionResult

        test_actor.property_lists.memory_a.append("x")
        test_actor.property_lists.memory_b.append("y")
        test_actor.property_lists.secret.append("z")

        with patch(
            "actingweb.interface.authenticated_views.get_permission_evaluator"
        ) as mock_get:
            evaluator = Mock()
            evaluator.evaluate_bulk_property_access = Mock(
                side_effect=lambda a, p, paths, op: {
                    path: (
                        PermissionResult.DENIED
                        if path == "secret"
                        else PermissionResult.ALLOWED
                    )
                    for path in paths
                }
            )
            mock_get.return_value = evaluator
            authed = self._authed(test_actor, evaluator=evaluator)

            assert sorted(authed.list_all()) == ["memory_a", "memory_b"]

            names, rows = authed.list_all_with_rows()
            assert sorted(names) == ["memory_a", "memory_b"]
            assert not any("secret" in row for row in rows)

            names, rows = authed.list_prefix_with_rows("memory_")
            assert sorted(names) == ["memory_a", "memory_b"]
            assert not any("secret" in row for row in rows)

    def test_the_permitted_rows_still_read_as_real_contents(self, test_actor):
        from unittest.mock import Mock, patch

        from actingweb.permission_evaluator import PermissionResult
        from actingweb.property_list import ListProperty

        test_actor.property_lists.foo.append("a")
        test_actor.property_lists.foo.append("b")
        for item in ("p", "q"):
            getattr(test_actor.property_lists, "foo-old").append(item)

        with patch(
            "actingweb.interface.authenticated_views.get_permission_evaluator"
        ) as mock_get:
            evaluator = Mock()
            evaluator.evaluate_bulk_property_access = Mock(
                side_effect=lambda a, p, paths, op: {
                    path: (
                        PermissionResult.DENIED
                        if path == "foo"
                        else PermissionResult.ALLOWED
                    )
                    for path in paths
                }
            )
            mock_get.return_value = evaluator
            names, rows = self._authed(
                test_actor, evaluator=evaluator
            ).list_all_with_rows()

        assert names == ["foo-old"]
        # The case a bare startswith() prune breaks: foo-old keeps its ITEM
        # rows, so it reads as its contents rather than as [].
        assert ListProperty(
            test_actor.id, "foo-old", test_actor.config
        ).to_list_from_rows(rows) == ["p", "q"]

    def test_a_method_name_is_not_reachable_as_a_list_name(self, test_actor):
        import pytest as _pytest

        authed = self._authed(test_actor)
        with _pytest.raises(AttributeError):
            authed.__getattr__("list_all_with_rows")
