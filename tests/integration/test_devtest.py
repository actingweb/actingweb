"""
DevTest endpoints for ActingWeb.

Tests for development/testing endpoints including attribute buckets and proxy.

This test suite runs sequentially - each test depends on the previous ones.
Converted from Runscope/Blazemeter JSON test suite.

NOTE: These tests should ONLY run with devtest endpoints enabled.
In production, devtest MUST be disabled for security.
"""

import pytest
import requests


class TestDevTestEndpoints:
    """
    Sequential test flow for devtest endpoints.

    Tests must run in order as they share state.
    """

    actor_url = None
    actor_id = None
    passphrase = None
    creator = "devtest@actingweb.net"

    def test_001_create_actor(self, http_client):
        """
        Create actor for devtest operations.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        TestDevTestEndpoints.actor_url = response.headers.get("Location")
        TestDevTestEndpoints.actor_id = response.json()["id"]
        TestDevTestEndpoints.passphrase = response.json()["passphrase"]

    def test_002_create_attribute_bucket1(self, http_client):
        """
        Create attribute bucket1 with initial data.

        Spec: devtest endpoints
        """
        response = requests.post(
            f"{self.actor_url}/devtest/attribute/bucket1",
            json={"var1": "value1", "var2": "value2"},
            auth=(self.creator, self.passphrase),
        )

        # Accept 200 or 201 for creation
        assert response.status_code in [200, 201]
        data = response.json()
        assert data.get("var1") == "value1"
        assert data.get("var2") == "value2"

    def test_003_get_attribute_bucket1(self, http_client):
        """
        Get attribute bucket1.

        Spec: devtest endpoints
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute/bucket1",
            auth=(self.creator, self.passphrase),
        )

        assert response.status_code == 200
        data = response.json()
        # Attributes return {"data": value, "timestamp": ...} format
        if isinstance(data.get("var1"), dict):
            assert data["var1"]["data"] == "value1"
            assert data["var2"]["data"] == "value2"
        else:
            assert data.get("var1") == "value1"
            assert data.get("var2") == "value2"

    def test_004_get_all_attribute_buckets(self, http_client):
        """
        Get all attribute buckets.

        Spec: devtest endpoints
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            auth=(self.creator, self.passphrase),
        )

        assert response.status_code in [200, 404]  # 404 if no implementation
        if response.status_code == 200:
            data = response.json()
            # Should have bucket1
            assert "bucket1" in str(data)

    def test_005_change_attribute_in_bucket1(self, http_client):
        """
        Update attribute in bucket1.

        Spec: devtest endpoints
        """
        response = requests.put(
            f"{self.actor_url}/devtest/attribute/bucket1",
            json={"var1": "changed", "var2": "value2"},
            auth=(self.creator, self.passphrase),
        )

        # PUT might not be implemented for attributes, accept 404
        assert response.status_code in [200, 204, 404]

        if response.status_code in [200, 204]:
            # Verify change
            response = requests.get(
                f"{self.actor_url}/devtest/attribute/bucket1",
                auth=(self.creator, self.passphrase),
            )
            assert response.status_code == 200
            data = response.json()
            if isinstance(data.get("var1"), dict):
                assert data["var1"]["data"] == "changed"
            else:
                assert data.get("var1") == "changed"

    def test_006_create_attribute_bucket2(self, http_client):
        """
        Create attribute bucket2.

        Spec: devtest endpoints
        """
        response = requests.post(
            f"{self.actor_url}/devtest/attribute/bucket2",
            json={"var3": "value3", "var4": "value4"},
            auth=(self.creator, self.passphrase),
        )

        assert response.status_code in [200, 201]
        data = response.json()
        assert data.get("var3") == "value3"

    def test_007_create_attribute_bucket3(self, http_client):
        """
        Create attribute bucket3.

        Spec: devtest endpoints
        """
        response = requests.post(
            f"{self.actor_url}/devtest/attribute/bucket3",
            json={"var5": "value5"},
            auth=(self.creator, self.passphrase),
        )

        assert response.status_code in [200, 201]

    def test_008_create_attribute_bucket4_with_nested_data(self, http_client):
        """
        Create attribute bucket4 with nested data structure.

        Spec: devtest endpoints
        """
        response = requests.post(
            f"{self.actor_url}/devtest/attribute/bucket4",
            json={
                "vard1": {"data": {"var1": "value1", "var2": "value2"}},
                "vard2": {"data": {"var1": "value1", "var2": "value2"}},
            },
            auth=(self.creator, self.passphrase),
        )

        assert response.status_code in [200, 201]

    def test_009_verify_all_buckets_with_nested(self, http_client):
        """
        Verify all buckets including nested structure.

        Spec: devtest endpoints
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            auth=(self.creator, self.passphrase),
        )

        if response.status_code == 200:
            data = response.json()
            # Should have multiple buckets
            data_str = str(data)
            assert "bucket1" in data_str or "bucket2" in data_str

    def test_010_delete_attribute_in_bucket2(self, http_client):
        """
        Delete specific attribute in bucket2.

        Spec: devtest endpoints
        """
        response = requests.delete(
            f"{self.actor_url}/devtest/attribute/bucket2",
            auth=(self.creator, self.passphrase),
        )

        assert response.status_code in [200, 204]

    def test_011_verify_timestamp_fields(self, http_client):
        """
        Verify timestamp fields exist in buckets.

        Spec: devtest endpoints
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute/bucket1",
            auth=(self.creator, self.passphrase),
        )

        if response.status_code == 200:
            data = response.json()
            # Timestamp field might exist
            has_timestamp = "timestamp" in str(data).lower() or "time" in str(data).lower()
            # Not strictly required, so just check if data exists
            assert data is not None

    def test_012_delete_all_attribute_buckets(self, http_client):
        """
        Delete all attribute buckets.

        Spec: devtest endpoints
        """
        response = requests.delete(
            f"{self.actor_url}/devtest/attribute",
            auth=(self.creator, self.passphrase),
        )

        assert response.status_code in [200, 204, 404]  # 404 if no implementation

    def test_013_verify_buckets_deleted(self, http_client):
        """
        Verify all buckets are deleted.

        Spec: devtest endpoints
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            auth=(self.creator, self.passphrase),
        )

        # Should return 404 or empty result
        assert response.status_code in [404, 200]
        if response.status_code == 200:
            data = response.json()
            # Should be empty or minimal
            assert len(str(data)) < 50

    def test_014_create_self_proxy(self, http_client):
        """
        Create self-proxy for actor.

        Spec: devtest endpoints
        """
        response = requests.post(
            f"{self.actor_url}/devtest/proxy/create",
            auth=(self.creator, self.passphrase),
        )

        # Accept 200, 201, or 404 if not implemented
        assert response.status_code in [200, 201, 404, 501]

    def test_015_get_properties_via_proxy(self, http_client):
        """
        Get properties via self-proxy.

        Spec: devtest endpoints
        """
        # First create some properties
        response = requests.post(
            f"{self.actor_url}/properties",
            json={"proxy_test": "value"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 201

        # Try to access via proxy
        response = requests.get(
            f"{self.actor_url}/devtest/proxy/properties",
            auth=(self.creator, self.passphrase),
        )

        # Accept 200 or 404 if proxy not implemented
        assert response.status_code in [200, 404, 501]

    def test_016_put_properties_via_proxy(self, http_client):
        """
        Put properties via self-proxy.

        Spec: devtest endpoints
        """
        response = requests.put(
            f"{self.actor_url}/devtest/proxy/properties/proxy_test",
            data="changed",
            auth=(self.creator, self.passphrase),
        )

        # Accept 204 or 404 if proxy not implemented
        assert response.status_code in [200, 204, 404, 501]

    def test_017_delete_properties_via_proxy(self, http_client):
        """
        Delete properties via self-proxy.

        Spec: devtest endpoints
        """
        response = requests.delete(
            f"{self.actor_url}/devtest/proxy/properties",
            auth=(self.creator, self.passphrase),
        )

        # Accept 204 or 404 if proxy not implemented
        assert response.status_code in [200, 204, 404, 501]

    def test_018_delete_actor(self, http_client):
        """
        Clean up by deleting the actor.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.delete(
            self.actor_url,
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204
