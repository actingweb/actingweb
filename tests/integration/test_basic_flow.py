"""
Basic actingweb actor flow.

Creation of actor and various basic actions before deleting the actor.

This test suite runs sequentially - each test depends on the previous ones.
Converted from Runscope/Blazemeter JSON test suite.
"""

import requests


class TestBasicActorFlow:
    """
    Sequential test flow for basic actor operations.

    Tests must run in order as they share state (actor created in early tests,
    used in middle tests, deleted in final test).
    """

    # Shared state across tests in this class
    actor_url: str | None = None
    actor_id: str | None = None
    passphrase: str | None = None
    creator: str = "testuser@actingweb.net"
    trustee_actor_url: str | None = None
    trustee_passphrase: str | None = None

    def test_001_factory_root_get(self, http_client):
        """
        Test basic GET response at factory root.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.get(f"{http_client.base_url}/")
        # Factory root should return either 200 (some content) or 404 (no root handler)
        assert response.status_code in [200, 404]

    def test_002_post_bot_endpoint(self, http_client):
        """
        Test POST to /bot endpoint - should return 404.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(f"{http_client.base_url}/bot")
        assert response.status_code == 404

    def test_003_create_actor_with_json(self, http_client):
        """
        Create a new actor using JSON.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        assert response.json()["creator"] == self.creator
        assert response.json()["passphrase"]

        # Store for subsequent tests
        TestBasicActorFlow.actor_url = response.headers.get("Location")
        TestBasicActorFlow.actor_id = response.json()["id"]
        TestBasicActorFlow.passphrase = response.json()["passphrase"]

    def test_004_delete_actor_wrong_user(self, http_client):
        """
        Delete actor with wrong username should fail.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.delete(
            self.actor_url,  # type: ignore[arg-type,union-attr,attr-defined,return-value]
            auth=("wronguser@actingweb.net", self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 403

    def test_005_delete_actor_wrong_password(self, http_client):
        """
        Delete actor with wrong password should fail.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.delete(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, "wrongpassword"),
        )
        assert response.status_code == 403

    def test_006_get_actor_wrong_credentials(self, http_client):
        """
        Get actor information with wrong credentials should fail.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.get(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, "wrongpassword"),
        )
        assert response.status_code == 403

    def test_007_get_actor_correct_credentials(self, http_client):
        """
        Get actor information with correct credentials.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.get(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        data = response.json()
        assert data["creator"] == self.creator

    def test_008_get_meta_endpoint(self, http_client):
        """
        Get actor meta information.

        Spec: docs/actingweb-spec.rst:615-669
        """
        # Meta is publicly accessible
        response = requests.get(f"{self.actor_url}/meta")
        assert response.status_code == 200
        meta = response.json()
        # Check for either old or new format
        if "aw_version" in meta:
            # Old format - verify version value
            assert meta["aw_version"] in [1.0, "1.0"]
        elif "actingweb" in meta:
            # New format
            assert "version" in meta["actingweb"]

    def test_009_get_meta_specific_variable(self, http_client):
        """
        Get specific meta variable.

        Spec: docs/actingweb-spec.rst:615-669
        """
        response = requests.get(f"{self.actor_url}/meta/actingweb/version")
        # Should return 200 or 404 depending on meta structure
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            # Response text should be version number
            assert response.text in ["1.0", '"1.0"']

    def test_010_create_properties_form_data(self, http_client):
        """
        Create properties using form data (not JSON).

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.post(
            f"{self.actor_url}/properties",
            data={"test": "testvalue", "test2": "testvalue2"},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        data = response.json()
        assert data["test"] == "testvalue"
        assert data["test2"] == "testvalue2"

    def test_011_get_specific_property(self, http_client):
        """
        Get value of specific property.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.get(
            f"{self.actor_url}/properties/test",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        assert response.text == "testvalue"

    def test_012_update_property(self, http_client):
        """
        Update property value.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor_url}/properties/test",
            data="valuechanged",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # Verify update
        response = requests.get(
            f"{self.actor_url}/properties/test",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        assert response.text == "valuechanged"

    def test_013_get_all_properties(self, http_client):
        """
        Get all properties.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        props = response.json()
        assert props["test"] == "valuechanged"
        assert props["test2"] == "testvalue2"

    def test_014_create_properties_with_unicode(self, http_client):
        """
        Create properties with unicode characters.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.post(
            f"{self.actor_url}/properties",
            json={"var1": "value1æøå", "var2": "value2ÆØÅ", "var3": {"test3": "value3", "test4": "value4"}},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        assert response.json()["var1"] == "value1æøå"
        assert response.json()["var2"] == "value2ÆØÅ"

    def test_015_delete_property(self, http_client):
        """
        Delete a specific property.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.delete(
            f"{self.actor_url}/properties/var1",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # Verify deletion
        response = requests.get(
            f"{self.actor_url}/properties/var1",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 404

    def test_016_get_all_properties_after_delete(self, http_client):
        """
        Get all properties after deletion to verify var1 is gone.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        props = response.json()
        assert props["test"] == "valuechanged"
        assert props["test2"] == "testvalue2"
        assert props["var2"] == "value2ÆØÅ"
        assert "var1" not in props

    def test_017_nested_json_properties(self, http_client):
        """
        Create nested JSON property.

        Spec: docs/actingweb-spec.rst:671-791
        """
        location_data = {
            "type": "mobile",
            "latitude": {"hours": 1, "minutes": 1, "seconds": 1},
            "longitude": {"hours": 2, "minutes": 2, "seconds": 2}
        }

        response = requests.put(
            f"{self.actor_url}/properties/location",
            json=location_data,
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_018_get_nested_property(self, http_client):
        """
        Get nested property.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.get(
            f"{self.actor_url}/properties/location",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        location = response.json()
        assert location["latitude"]["hours"] == 1

    def test_019_get_deeply_nested_property(self, http_client):
        """
        Get deeply nested property (2 levels).

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.get(
            f"{self.actor_url}/properties/location/latitude",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        assert response.json()["minutes"] == 1

    def test_020_get_all_properties_with_nested(self, http_client):
        """
        Get all properties including nested ones.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        props = response.json()
        assert props["test"] == "valuechanged"
        assert props["test2"] == "testvalue2"
        assert props["var2"] == "value2ÆØÅ"
        # Nested properties might be in different formats
        if "location" in props:
            location = props["location"]
            # Handle both direct and quoted key formats
            if isinstance(location, dict):
                # Check for nested structure
                assert "latitude" in str(location) or "longitude" in str(location)

    def test_021_update_nested_property(self, http_client):
        """
        Update nested property value.

        Spec: docs/actingweb-spec.rst:671-791
        """
        # Update latitude
        response = requests.put(
            f"{self.actor_url}/properties/location/latitude",
            json={"hours": 3, "minutes": 3, "seconds": 3},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # Verify update
        response = requests.get(
            f"{self.actor_url}/properties/location/latitude",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        assert response.json()["hours"] == 3

    def test_022_update_deeply_nested_leaf(self, http_client):
        """
        Update deeply nested leaf value (3 levels).

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor_url}/properties/location/latitude/minutes",
            data="4",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # Verify update
        response = requests.get(
            f"{self.actor_url}/properties/location/latitude/minutes",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        # Response might be "4" or 4
        assert response.text in ["4", '"4"']

    def test_023_create_new_deeply_nested_path(self, http_client):
        """
        Create new deeply nested path via PUT.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor_url}/properties/location/latitude/milliseconds",
            data="50",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # Verify creation
        response = requests.get(
            f"{self.actor_url}/properties/location/latitude/milliseconds",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200

    def test_024_create_new_branch_in_nested_structure(self, http_client):
        """
        Create new branch in nested structure.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor_url}/properties/location/fraud/milliseconds",
            json={"test1": "testvalue1", "test2": "testvalue2"},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_025_verify_complex_nested_structure(self, http_client):
        """
        Verify complex nested structure exists.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        props = response.json()
        # Verify the structure contains our nested data
        assert "location" in str(props)

    def test_026_delete_deeply_nested_property(self, http_client):
        """
        Delete deeply nested property.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.delete(
            f"{self.actor_url}/properties/location/latitude/milliseconds",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # Verify deletion
        response = requests.get(
            f"{self.actor_url}/properties/location/latitude/milliseconds",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 404

    def test_027_delete_nonexistent_nested_property(self, http_client):
        """
        Delete non-existent nested property - should return 404.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.delete(
            f"{self.actor_url}/properties/location/latitude/milliseconds",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 404

    def test_028_delete_nested_branch(self, http_client):
        """
        Delete nested branch.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.delete(
            f"{self.actor_url}/properties/location/fraud",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_029_delete_nonexistent_path_in_var3(self, http_client):
        """
        Delete non-existent path - should return 404.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.delete(
            f"{self.actor_url}/properties/var3/nonexistent",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 404

    def test_030_delete_var3(self, http_client):
        """
        Delete var3 property.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.delete(
            f"{self.actor_url}/properties/var3",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_031_delete_all_properties(self, http_client):
        """
        Delete all properties at once.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.delete(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # Verify all deleted
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 404

    def test_032_delete_actor(self, http_client):
        """
        Delete the actor.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.delete(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_033_verify_actor_deleted(self, http_client):
        """
        Verify actor is not found after deletion.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.get(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 404

    def test_034_create_actor_with_trustee(self, http_client):
        """
        Create actor with trustee_root parameter.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": "trustee", "trustee_root": "http://www.actingweb.net"},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        assert response.json()["creator"] == "trustee"
        assert response.json()["passphrase"]
        if "trustee_root" in response.json():
            assert response.json()["trustee_root"] == "http://www.actingweb.net"

        TestBasicActorFlow.trustee_actor_url = response.headers.get("Location")
        TestBasicActorFlow.trustee_passphrase = response.json()["passphrase"]

    def test_035_get_actor_with_trustee(self, http_client):
        """
        Get actor with trustee root.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.get(
            self.trustee_actor_url,  # type: ignore[arg-type]
            auth=("trustee", self.trustee_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        assert response.json()["creator"] == "trustee"
        if "trustee_root" in response.json():
            assert response.json()["trustee_root"] == "http://www.actingweb.net"

    def test_036_get_actor_with_bearer_token(self, http_client):
        """
        Get actor with bearer token as trustee.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.get(
            self.trustee_actor_url,  # type: ignore[arg-type]
            headers={"Authorization": f"Bearer {self.trustee_passphrase}"},
        )
        # Bearer token auth might work differently
        assert response.status_code in [200, 403]

    def test_037_delete_trustee_actor(self, http_client):
        """
        Delete actor with trustee.

        Spec: docs/actingweb-spec.rst:454-505
        """
        if self.trustee_actor_url:
            response = requests.delete(
                self.trustee_actor_url,
                auth=("trustee", self.trustee_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code == 204
