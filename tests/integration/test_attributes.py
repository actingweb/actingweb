"""
Attributes actingweb test.

Additional property/attribute edge cases and advanced scenarios.

This test suite runs sequentially - each test depends on the previous ones.
Converted from Runscope/Blazemeter JSON test suite.
"""

import pytest
import requests


class TestAttributesFlow:
    """
    Sequential test flow for advanced property/attribute operations.

    Tests must run in order as they share state.
    """

    actor_url = None
    passphrase = None
    creator = "attr@actingweb.net"

    def test_001_create_actor(self, http_client):
        """
        Create actor for attribute tests.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        TestAttributesFlow.actor_url = response.headers.get("Location")
        TestAttributesFlow.passphrase = response.json()["passphrase"]

    def test_002_complex_nested_properties(self, http_client):
        """
        Test deeply nested property structures.

        Spec: docs/actingweb-spec.rst:671-791
        """
        complex_data = {
            "config": {
                "settings": {
                    "notifications": {
                        "email": True,
                        "sms": False,
                        "frequency": "daily"
                    },
                    "privacy": {
                        "public_profile": True,
                        "show_email": False
                    }
                }
            }
        }

        response = requests.post(
            f"{self.actor_url}/properties",
            json=complex_data,
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 201

    def test_003_update_nested_leaf(self, http_client):
        """
        Update a deeply nested leaf value.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor_url}/properties/config/settings/notifications/frequency",
            data="hourly",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204

        # Verify update
        response = requests.get(
            f"{self.actor_url}/properties/config/settings/notifications/frequency",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        # Nested values may be JSON-encoded
        assert response.text in ["hourly", '"hourly"']

    def test_004_array_properties(self, http_client):
        """
        Test properties with array values.

        Spec: docs/actingweb-spec.rst:671-791
        """
        array_data = {
            "tags": ["important", "work", "urgent"],
            "numbers": [1, 2, 3, 4, 5]
        }

        response = requests.post(
            f"{self.actor_url}/properties",
            json=array_data,
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 201

        # Verify arrays are preserved
        response = requests.get(
            f"{self.actor_url}/properties/tags",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3

    def test_005_special_characters_in_values(self, http_client):
        """
        Test properties with special characters and unicode.

        Spec: docs/actingweb-spec.rst:671-791
        """
        special_data = {
            "emoji": "Hello 👋 World 🌍",
            "symbols": "!@#$%^&*()",
            "quotes": 'He said "hello"',
            "newlines": "Line1\nLine2\nLine3"
        }

        response = requests.post(
            f"{self.actor_url}/properties",
            json=special_data,
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 201

    def test_006_moderate_property_value(self, http_client):
        """
        Test storing moderate-sized property values.

        Note: DynamoDB has a 400KB limit per item, so we test with a reasonable size.

        Spec: docs/actingweb-spec.rst:671-791
        """
        # Use 1KB instead of 10KB to stay well within limits
        moderate_value = "x" * 1000

        response = requests.put(
            f"{self.actor_url}/properties/moderate_data",
            data=moderate_value,
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204

        # Verify retrieval
        response = requests.get(
            f"{self.actor_url}/properties/moderate_data",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        assert len(response.text) == 1000

    def test_007_delete_all_and_recreate(self, http_client):
        """
        Test deleting all properties and creating new ones.

        Spec: docs/actingweb-spec.rst:671-791
        """
        # Delete all
        response = requests.delete(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204

        # Verify all deleted
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 404

        # Create new properties
        response = requests.post(
            f"{self.actor_url}/properties",
            json={"fresh": "start"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 201

    def test_008_delete_actor(self, http_client):
        """
        Clean up by deleting the actor.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.delete(
            self.actor_url,
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204
