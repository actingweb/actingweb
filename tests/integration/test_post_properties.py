"""
Comprehensive tests for POST /properties endpoint.

Verifies POST /properties works correctly for:
- Simple properties (single and batch)
- List properties (creation and bulk updates)
- Mixed operations (simple + list properties)
"""

import pytest
import requests


@pytest.mark.xdist_group(name="post_properties_flow")
class TestPostPropertiesFlow:
    """
    Test POST /properties for both simple properties and list properties.

    Tests must run in order as they share state.
    """

    actor_url: str | None = None
    passphrase: str | None = None
    creator: str = "posttest@actingweb.net"

    def test_001_create_actor(self, http_client):
        """Create actor for POST properties tests."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        TestPostPropertiesFlow.actor_url = response.headers.get("Location")
        TestPostPropertiesFlow.passphrase = response.json()["passphrase"]

    def test_002_post_single_simple_property(self, http_client):
        """Test POST /properties with a single simple property."""
        response = requests.post(
            f"{self.actor_url}/properties",
            json={"name": "John Doe"},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        data = response.json()
        assert "name" in data
        assert data["name"] == "John Doe"

        # Verify via GET - check if property exists by listing all first
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        all_props = response.json()
        assert "name" in all_props, f"Property 'name' not found in {all_props.keys()}"
        assert all_props["name"] == "John Doe"

    def test_003_post_multiple_simple_properties(self, http_client):
        """Test POST /properties with multiple simple properties at once."""
        response = requests.post(
            f"{self.actor_url}/properties",
            json={"email": "john@example.com", "age": 30, "city": "San Francisco"},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        data = response.json()
        assert "email" in data
        assert "age" in data
        assert "city" in data

        # Verify all properties exist
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        properties = response.json()
        assert properties["email"] == "john@example.com"
        assert properties["age"] == 30
        assert properties["city"] == "San Francisco"
        assert properties["name"] == "John Doe"  # From previous test

    def test_004_post_create_empty_list_property(self, http_client):
        """Test POST /properties to create an empty list property."""
        response = requests.post(
            f"{self.actor_url}/properties",
            json={"todos": {"_type": "list"}},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        data = response.json()
        assert "todos" in data

        # Verify list property exists and is empty
        response = requests.get(
            f"{self.actor_url}/properties/todos",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        items = response.json()
        assert isinstance(items, list)
        assert len(items) == 0

    def test_005_post_create_list_property_with_metadata(self, http_client):
        """Test POST /properties to create a list property with description/explanation."""
        response = requests.post(
            f"{self.actor_url}/properties",
            json={
                "notes": {
                    "_type": "list",
                    "description": "Quick notes",
                    "explanation": "A list of quick notes and reminders",
                }
            },
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201

        # Verify metadata
        response = requests.get(
            f"{self.actor_url}/properties/notes/metadata",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        metadata = response.json()
        assert metadata["description"] == "Quick notes"
        assert metadata["explanation"] == "A list of quick notes and reminders"
        assert metadata["_list"] is True
        assert metadata["count"] == 0

    def test_006_post_bulk_update_list_items(self, http_client):
        """Test POST /properties to bulk update list items."""
        # First add some items to the todos list
        response = requests.post(
            f"{self.actor_url}/properties",
            json={
                "todos": {
                    "items": [
                        {"index": 0, "task": "Buy milk", "done": False},
                        {"index": 1, "task": "Walk dog", "done": False},
                        {"index": 2, "task": "Read book", "done": True},
                    ]
                }
            },
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201

        # Verify items were added
        response = requests.get(
            f"{self.actor_url}/properties/todos",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 3
        assert items[0]["task"] == "Buy milk"
        assert items[1]["task"] == "Walk dog"
        assert items[2]["task"] == "Read book"

    def test_007_post_bulk_update_and_delete_items(self, http_client):
        """Test POST /properties to update existing items and delete items."""
        # Update item at index 1 and delete item at index 2
        response = requests.post(
            f"{self.actor_url}/properties",
            json={
                "todos": {
                    "items": [
                        {"index": 1, "task": "Walk dog", "done": True},  # Update
                        {"index": 2},  # Delete (only index, no data)
                    ]
                }
            },
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201

        # Verify changes
        response = requests.get(
            f"{self.actor_url}/properties/todos",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 2  # One item deleted
        assert items[0]["task"] == "Buy milk"
        assert items[1]["task"] == "Walk dog"
        assert items[1]["done"] is True  # Updated

    def test_008_post_mixed_properties_and_lists(self, http_client):
        """Test POST /properties with both simple properties and list creation."""
        response = requests.post(
            f"{self.actor_url}/properties",
            json={
                "status": "active",
                "last_update": "2026-01-27",
                "tags": {"_type": "list", "description": "User tags"},
            },
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201

        # Verify all properties via list endpoint
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        all_props = response.json()
        assert "status" in all_props
        assert all_props["status"] == "active"
        assert "last_update" in all_props
        assert all_props["last_update"] == "2026-01-27"

        # Verify list property
        response = requests.get(
            f"{self.actor_url}/properties/tags",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        items = response.json()
        assert isinstance(items, list)
        assert len(items) == 0

    def test_009_post_complex_property_values(self, http_client):
        """Test POST /properties with nested objects and arrays."""
        response = requests.post(
            f"{self.actor_url}/properties",
            json={
                "config": {
                    "theme": "dark",
                    "notifications": {"email": True, "sms": False},
                },
                "preferences": ["privacy", "security", "performance"],
            },
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201

        # Verify nested object
        response = requests.get(
            f"{self.actor_url}/properties/config",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        config = response.json()
        assert config["theme"] == "dark"
        assert config["notifications"]["email"] is True

        # Verify array
        response = requests.get(
            f"{self.actor_url}/properties/preferences",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        prefs = response.json()
        assert isinstance(prefs, list)
        assert len(prefs) == 3

    def test_010_verify_all_properties_via_list(self, http_client):
        """Verify all properties created via POST are accessible."""
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        properties = response.json()

        # Simple properties from various tests
        assert "name" in properties
        assert "email" in properties
        assert "age" in properties
        assert "city" in properties
        assert "status" in properties
        assert "last_update" in properties
        assert "config" in properties
        assert "preferences" in properties

        # List properties should show up with _list marker
        assert "todos" in properties
        assert "notes" in properties
        assert "tags" in properties

    def test_011_delete_actor(self, http_client):
        """Clean up by deleting the actor."""
        response = requests.delete(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204
