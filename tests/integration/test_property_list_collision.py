"""Integration tests for property/list name collision detection."""

import pytest

from actingweb.interface import ActorInterface


@pytest.fixture
def test_actor(test_app):
    """Create a test actor with automatic cleanup."""
    from actingweb.config import Config

    config = Config(
        aw_type="urn:actingweb:example.com:testapp",
        actor_id=None,
        database="dynamodb",
    )
    actor = ActorInterface.create(
        creator="collision@example.com",
        config=config,
    )
    yield actor
    # Cleanup
    try:
        actor.delete()
    except Exception:
        pass  # Best effort cleanup


class TestPropertyListCollisionDetection:
    """Test that lists take precedence over properties when names collide."""

    def test_list_creation_raises_error_when_property_exists(self, test_actor):
        """When a list is created and a property exists, ValueError is raised."""
        actor = test_actor

        # Create a regular property first
        actor.properties["collision_test"] = "original_property_value"
        assert actor.properties["collision_test"] == "original_property_value"

        # Try to create a list with the same name - should raise ValueError
        test_list = actor.property_lists.collision_test

        with pytest.raises(ValueError) as exc_info:
            # This will trigger metadata load which checks for collision
            test_list.append({"item": "first"})

        # Verify error message
        assert "Cannot create list 'collision_test'" in str(exc_info.value)
        assert "property with this name already exists" in str(exc_info.value)

    def test_property_set_raises_error_when_list_exists(self, test_actor):
        """When setting a property and a list exists, ValueError is raised."""
        actor = test_actor

        # Create a list first
        test_list = actor.property_lists.list_first
        test_list.append({"item": "list_data"})
        assert len(test_list) == 1

        # Try to create a property with the same name - should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            actor.properties["list_first"] = "property_value"

        # Verify error message
        assert "Cannot create property 'list_first'" in str(exc_info.value)
        assert "list with this name already exists" in str(exc_info.value)

        # Verify list still exists and works
        assert len(test_list) == 1
        assert test_list[0] == {"item": "list_data"}

    def test_multiple_collisions_raise_errors(self, test_actor):
        """Test multiple property/list collision scenarios raise appropriate errors."""
        actor = test_actor

        # Create properties first
        actor.properties["name1"] = "value1"
        actor.properties["name2"] = "value2"
        actor.properties["name3"] = "value3"

        # Try to create lists with same names as properties - should raise errors
        list1 = actor.property_lists.name1
        with pytest.raises(ValueError) as exc_info:
            list1.append("item1")
        assert "Cannot create list 'name1'" in str(exc_info.value)

        list2 = actor.property_lists.name2
        with pytest.raises(ValueError) as exc_info:
            list2.append("item2")
        assert "Cannot create list 'name2'" in str(exc_info.value)

        # name3 property should still exist
        assert actor.properties["name3"] == "value3"

        # Now create list3 successfully (different name)
        list3 = actor.property_lists.list3
        list3.append("item3")
        assert len(list3) == 1

        # Try to set a property with same name as list3 - should raise error
        with pytest.raises(ValueError) as exc_info:
            actor.properties["list3"] = "new_value"
        assert "Cannot create property 'list3'" in str(exc_info.value)

        # List should still work
        assert len(list3) == 1
        assert list3[0] == "item3"

    def test_property_and_list_can_coexist_with_different_names(self, test_actor):
        """Test that properties and lists with different names can coexist."""
        actor = test_actor

        # Create a property
        actor.properties["my_property"] = "property_value"

        # Create a list with a different name
        my_list = actor.property_lists.my_list
        my_list.append("list_item")

        # Both should work fine
        assert actor.properties["my_property"] == "property_value"
        assert len(my_list) == 1
        assert my_list[0] == "list_item"

        # Verify they don't interfere with each other
        actor.properties["my_property"] = "updated_value"
        my_list.append("another_item")

        assert actor.properties["my_property"] == "updated_value"
        assert len(my_list) == 2
