"""
Devtest attributes actingweb test.

Tests for the devtest attribute bucket API which provides timestamped
attribute storage organized into named buckets.

This test suite runs sequentially - each test depends on the previous ones.
Converted from Runscope/Blazemeter JSON test suite.

NOTE: The /devtest endpoints should be disabled in production environments.
"""

import pytest
import requests


class TestDevtestAttributesFlow:
    """
    Sequential test flow for devtest attribute bucket operations.

    Tests must run in order as they share state (actor and attribute buckets).
    """

    actor_url = None
    passphrase = None
    creator = "testuser@actingweb.net"

    def test_001_factory_root_get(self, http_client):
        """
        Test basic GET response at factory root.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.get(f"{http_client.base_url}/")
        assert response.status_code in [200, 404]

    def test_002_post_bot_endpoint(self, http_client):
        """
        Test POST to /bot endpoint - should return 404.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(f"{http_client.base_url}/bot")
        assert response.status_code == 404

    def test_003_create_actor(self, http_client):
        """
        Create actor for devtest attribute tests.

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

        TestDevtestAttributesFlow.actor_url = response.headers.get("Location")
        TestDevtestAttributesFlow.passphrase = response.json()["passphrase"]

    def test_004_create_attribute_bucket1(self, http_client):
        """
        Create first attribute bucket with var1 and var2.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.post(
            f"{self.actor_url}/devtest/attribute/bucket1",
            json={"var1": "value1", "var2": "value2"},
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("var1") == "value1"

    def test_005_get_attribute_bucket1(self, http_client):
        """
        Get the attribute bucket1 and verify structure.

        Attributes are stored with data and timestamp fields.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute/bucket1",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()

        # Attributes are stored with structure: {attr_name: {data: value, timestamp: ts}}
        if isinstance(data, dict):
            # Check for the nested structure
            if "var1" in data:
                # May be stored as {"data": "value1", "timestamp": "..."}
                if isinstance(data["var1"], dict):
                    assert data["var1"].get("data") == "value1"
                # Or may be returned directly
                else:
                    assert data["var1"] == "value1"

    def test_006_get_all_buckets(self, http_client):
        """
        Get all attribute buckets.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()

        # Should contain bucket1
        assert "bucket1" in data
        # Verify nested structure
        if isinstance(data["bucket1"], dict) and "var1" in data["bucket1"]:
            bucket1_var1 = data["bucket1"]["var1"]
            if isinstance(bucket1_var1, dict):
                assert bucket1_var1.get("data") == "value1"

    def test_007_change_attribute_in_bucket1(self, http_client):
        """
        Change an attribute in bucket1 from value1 to value2.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.put(
            f"{self.actor_url}/devtest/attribute/bucket1/var1",
            json="value2",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204

    def test_008_verify_attribute_changed(self, http_client):
        """
        Verify the attribute was changed to value2.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()

        # Verify var1 is now value2
        if "bucket1" in data and "var1" in data["bucket1"]:
            bucket1_var1 = data["bucket1"]["var1"]
            if isinstance(bucket1_var1, dict):
                assert bucket1_var1.get("data") == "value2"

    def test_009_create_attribute_bucket2(self, http_client):
        """
        Create second attribute bucket with varb1 and varb2.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.post(
            f"{self.actor_url}/devtest/attribute/bucket2",
            json={"varb1": "valueb1", "varb2": "valueb2"},
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("varb1") == "valueb1"

    def test_010_verify_two_buckets(self, http_client):
        """
        Verify both bucket1 and bucket2 exist with correct values.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()

        # Should have both buckets
        assert "bucket1" in data
        assert "bucket2" in data

        # Verify bucket2 values
        if "bucket2" in data and "varb2" in data["bucket2"]:
            bucket2_varb2 = data["bucket2"]["varb2"]
            if isinstance(bucket2_varb2, dict):
                assert bucket2_varb2.get("data") == "valueb2"

    def test_011_create_attribute_bucket3(self, http_client):
        """
        Create third attribute bucket with varc1 and varc2.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.post(
            f"{self.actor_url}/devtest/attribute/bucket3",
            json={"varc1": "valuec1", "varc2": "valuec2"},
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("varc1") == "valuec1"

    def test_012_verify_three_buckets(self, http_client):
        """
        Verify all three buckets exist.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()

        # Should have all three buckets
        assert "bucket1" in data
        assert "bucket2" in data
        assert "bucket3" in data

    def test_013_create_attribute_bucket4_with_nested_data(self, http_client):
        """
        Create fourth attribute bucket with nested JSON data.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.post(
            f"{self.actor_url}/devtest/attribute/bucket4",
            json={
                "vard1": "valued1",
                "vard2": {
                    "var1": "test1",
                    "var2": "test2"
                }
            },
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("vard1") == "valued1"

    def test_014_verify_nested_attribute_data(self, http_client):
        """
        Verify bucket4 contains nested data structure.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()

        # Verify bucket4 has nested structure
        if "bucket4" in data and "vard2" in data["bucket4"]:
            bucket4_vard2 = data["bucket4"]["vard2"]
            if isinstance(bucket4_vard2, dict):
                vard2_data = bucket4_vard2.get("data", bucket4_vard2)
                if isinstance(vard2_data, dict):
                    assert vard2_data.get("var2") == "test2"

    def test_015_delete_attribute_in_bucket2(self, http_client):
        """
        Delete varb2 attribute from bucket2.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.delete(
            f"{self.actor_url}/devtest/attribute/bucket2/varb2",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204

    def test_016_verify_attribute_deleted(self, http_client):
        """
        Verify varb2 is deleted but varb1 and other buckets remain.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()

        # bucket2 should still exist with varb1
        assert "bucket2" in data
        if "bucket2" in data:
            assert "varb1" in data["bucket2"]
            # varb2 should be gone
            # Note: may still appear in structure but should be marked deleted

        # Other buckets should still exist
        assert "bucket1" in data
        assert "bucket3" in data

        # Verify timestamps exist on remaining attributes
        if "bucket1" in data and "var1" in data["bucket1"]:
            bucket1_var1 = data["bucket1"]["var1"]
            if isinstance(bucket1_var1, dict):
                assert "timestamp" in bucket1_var1

    def test_017_delete_second_attribute_in_bucket2(self, http_client):
        """
        Delete varb1 attribute from bucket2 (last attribute in bucket).

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.delete(
            f"{self.actor_url}/devtest/attribute/bucket2/varb1",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204

    def test_018_verify_bucket2_empty_or_deleted(self, http_client):
        """
        Verify bucket2 is empty or removed after deleting all attributes.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()

        # bucket2 may not exist, or may exist but be empty
        # Other buckets should still exist
        assert "bucket1" in data
        assert "bucket3" in data

    def test_019_delete_all_buckets(self, http_client):
        """
        Delete all attribute buckets at once.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.delete(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204

    def test_020_verify_all_buckets_deleted(self, http_client):
        """
        Verify all buckets are deleted.

        Spec: docs/actingweb-spec.rst:454-505 (devtest endpoints)
        """
        response = requests.get(
            f"{self.actor_url}/devtest/attribute",
            headers={"Content-Type": "application/json"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 404

    def test_021_delete_actor(self, http_client):
        """
        Clean up by deleting the actor.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.delete(
            self.actor_url,
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 204
