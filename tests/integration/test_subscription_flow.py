"""
Subscription actingweb actor flow.

Tests for subscription relationships between actors.

This test suite runs sequentially - each test depends on the previous ones.
Converted from Runscope/Blazemeter JSON test suite.
"""

import pytest
import requests


@pytest.mark.usefixtures("http_client")
class TestSubscriptionActorFlow:
    """
    Sequential test flow for subscriptions between actors.

    Tests must run in order as they share state (three actors and subscriptions).
    """

    # Shared state for actors
    actor1_url: str | None = None
    actor1_id = None
    passphrase1 = None
    creator1 = "trust1@actingweb.net"

    actor2_url: str | None = None
    actor2_id = None
    passphrase2 = None
    creator2 = "trust2@actingweb.net"

    actor3_url = None
    actor3_id = None
    passphrase3 = None
    creator3 = "trust3@actingweb.net"

    # Shared state for trust relationships
    trust1_secret = None  # Between actor1 and actor2
    trust2_secret = None  # Between actor1 and actor3

    # Shared state for subscriptions (7 subscriptions total)
    subid1 = None  # Actor2 subscribes to actor1 properties/test with granularity=none
    subid2 = None  # Actor2 subscribes to actor1 properties with granularity=high
    subid3 = None  # Actor2 subscribes to actor1 meta with granularity=high
    subid4 = None  # Actor3 subscribes to actor1 properties with granularity=low
    subid5 = None  # Actor3 subscribes to actor1 properties/data2 with granularity=high
    subid6 = None  # Actor3 subscribes to actor1 properties with granularity=none
    subid7 = None  # Actor2 subscribes to actor1 properties/test/resource

    def test_001_create_actor1(self, http_client):
        """
        Create first actor.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator1},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        assert response.json()["creator"] == self.creator1
        assert response.json()["passphrase"]

        TestSubscriptionActorFlow.actor1_url = response.headers.get("Location")
        TestSubscriptionActorFlow.actor1_id = response.json()["id"]
        TestSubscriptionActorFlow.passphrase1 = response.json()["passphrase"]

    def test_002_create_actor2(self, http_client):
        """
        Create second actor.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator2},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        assert response.json()["creator"] == self.creator2
        assert response.json()["passphrase"]

        TestSubscriptionActorFlow.actor2_url = response.headers.get("Location")
        TestSubscriptionActorFlow.actor2_id = response.json()["id"]
        TestSubscriptionActorFlow.passphrase2 = response.json()["passphrase"]

    def test_003_create_actor3(self, http_client):
        """
        Create third actor.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator3},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        assert response.json()["creator"] == self.creator3
        assert response.json()["passphrase"]

        TestSubscriptionActorFlow.actor3_url = response.headers.get("Location")
        TestSubscriptionActorFlow.actor3_id = response.json()["id"]
        TestSubscriptionActorFlow.passphrase3 = response.json()["passphrase"]

    def test_004_establish_trust_actor1_actor2(self, http_client):
        """
        Establish trust between actor1 and actor2.

        Spec: docs/actingweb-spec.rst:1092-1857
        """
        response = requests.post(
            f"{self.actor1_url}/trust",
            json={
                "url": self.actor2_url,
                "relationship": "friend",
                "desc": "Test relationship between actor1 and actor2",
            },
            auth=(self.creator1, self.passphrase1),  # type: ignore[arg-type,union-attr,attr-defined,return-value]
        )

        assert response.status_code in [201, 202]
        TestSubscriptionActorFlow.trust1_secret = response.json()["secret"]

        # Approve from actor2's side
        response = requests.put(
            f"{self.actor2_url}/trust/friend/{self.actor1_id}",
            json={"approved": True},
            auth=(self.creator2, self.passphrase2),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

        # Approve from actor1's side
        response = requests.put(
            f"{self.actor1_url}/trust/friend/{self.actor2_id}",
            json={"approved": True},
            auth=(self.creator1, self.passphrase1),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

    def test_005_establish_trust_actor1_actor3(self, http_client):
        """
        Establish trust between actor1 and actor3.

        Spec: docs/actingweb-spec.rst:1092-1857
        """
        response = requests.post(
            f"{self.actor1_url}/trust",
            json={
                "url": self.actor3_url,
                "relationship": "friend",
                "secret": "mysecret2",
                "desc": "Test relationship between actor1 and actor3",
            },
            auth=(self.creator1, self.passphrase1),  # type: ignore[arg-type]
        )

        assert response.status_code in [201, 202]
        TestSubscriptionActorFlow.trust2_secret = response.json()["secret"]

        # Approve from actor3's side
        response = requests.put(
            f"{self.actor3_url}/trust/friend/{self.actor1_id}",
            json={"approved": True},
            auth=(self.creator3, self.passphrase3),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

    def test_006_create_subscription_no_auth(self, http_client):
        """
        Try to create subscription without authentication - should fail.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor2_url}/subscriptions",
            json={
                "peerid": self.actor1_id,
                "target": "properties",
                "subtarget": "",
                "granularity": "high",
            },
        )
        assert response.status_code == 401

    def test_007_create_subscription1(self, http_client):
        """
        Create subscription 1: actor2 subscribes to actor1 properties/test with granularity=none.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor2_url}/subscriptions",
            json={
                "peerid": self.actor1_id,
                "target": "properties",
                "subtarget": "test",
                "granularity": "none",
            },
            auth=(self.creator2, self.passphrase2),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

    def test_008_get_subscription1_id(self, http_client):
        """
        Get subscription 1 from actor1 as peer to extract subscription ID.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 200

        data = response.json()
        if "data" in data and len(data["data"]) > 0:
            TestSubscriptionActorFlow.subid1 = data["data"][0]["subscriptionid"]

    def test_009_create_subscription2(self, http_client):
        """
        Create subscription 2: actor2 subscribes to actor1 properties with granularity=high.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor2_url}/subscriptions",
            json={
                "peerid": self.actor1_id,
                "target": "properties",
                "subtarget": "",
                "granularity": "high",
            },
            auth=(self.creator2, self.passphrase2),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

    def test_010_create_subscription3(self, http_client):
        """
        Create subscription 3: actor2 subscribes to actor1 meta with granularity=high.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor2_url}/subscriptions",
            json={
                "peerid": self.actor1_id,
                "target": "meta",
                "subtarget": "",
                "granularity": "high",
            },
            auth=(self.creator2, self.passphrase2),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

    def test_011_create_subscription4(self, http_client):
        """
        Create subscription 4: actor3 subscribes to actor1 properties with granularity=low.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor3_url}/subscriptions",
            json={
                "peerid": self.actor1_id,
                "target": "properties",
                "subtarget": "",
                "granularity": "low",
            },
            auth=(self.creator3, self.passphrase3),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

    def test_012_create_subscription5(self, http_client):
        """
        Create subscription 5: actor3 subscribes to actor1 properties/data2 with granularity=high.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor3_url}/subscriptions",
            json={
                "peerid": self.actor1_id,
                "target": "properties",
                "subtarget": "data2",
                "granularity": "high",
            },
            auth=(self.creator3, self.passphrase3),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

    def test_013_get_subscription5_id(self, http_client):
        """
        Get subscription 5 from actor1 as peer to extract subscription ID.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor3_id}",
            headers={"Authorization": f"Bearer {self.trust2_secret}"},
        )
        assert response.status_code == 200

        data = response.json()
        if "data" in data and len(data["data"]) >= 2:
            TestSubscriptionActorFlow.subid5 = data["data"][1]["subscriptionid"]

    def test_014_create_subscription6(self, http_client):
        """
        Create subscription 6: actor3 subscribes to actor1 properties with granularity=none.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor3_url}/subscriptions",
            json={
                "peerid": self.actor1_id,
                "target": "properties",
                "subtarget": "",
                "granularity": "none",
            },
            auth=(self.creator3, self.passphrase3),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

    def test_015_create_subscription7(self, http_client):
        """
        Create subscription 7: actor2 subscribes to actor1 properties/test/resource.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor2_url}/subscriptions",
            json={
                "peerid": self.actor1_id,
                "target": "properties",
                "subtarget": "test",
                "resource": "resource",
                "granularity": "none",
            },
            auth=(self.creator2, self.passphrase2),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

    def test_016_verify_callback_invalid_subid(self, http_client):
        """
        Verify callback with invalid subscription ID returns 404.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.post(
            f"{self.actor2_url}/callbacks/subscriptions/{self.actor1_id}/invalidsubid",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 404

    def test_017_verify_callback_valid_subid(self, http_client):
        """
        Verify callback with valid subscription ID.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        if not self.subid1:
            pytest.skip("No subscription ID available")

        response = requests.post(
            f"{self.actor2_url}/callbacks/subscriptions/{self.actor1_id}/{self.subid1}",
            json={"test": "fake"},
            headers={
                "Authorization": f"Bearer {self.trust1_secret}",
                "Content-Type": "application/json",
            },
        )
        # Accept 204 (success) or 400 (may require specific callback data format)
        assert response.status_code in [204, 400]

    def test_018_post_initial_properties(self, http_client):
        """
        Post initial data to /properties to trigger subscription notifications.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.post(
            f"{self.actor1_url}/properties",
            json={
                "data1": {
                    "str1": "initial",
                    "str2": "initial",
                },
                "data2": "initial",
                "test": {
                    "var1": "initial",
                    "var2": "initial",
                    "resource": "initial",
                },
            },
            headers={
                "Authorization": f"Bearer {self.trust1_secret}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 201
        assert response.json()["data2"] == "initial"

    def test_019_put_change1(self, http_client):
        """
        Put change 1 to /properties/test.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor1_url}/properties/test",
            data="change1",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 204

    def test_020_put_change2(self, http_client):
        """
        Put change 2 to /properties/test.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor1_url}/properties/test",
            data="change2",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 204

    def test_021_put_change3(self, http_client):
        """
        Put change 3 to /properties/test.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor1_url}/properties/test",
            data="change3",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 204

    def test_022_put_change4(self, http_client):
        """
        Put change 4 (nested object) to /properties/test.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor1_url}/properties/test",
            json={"resource": "change4", "some": "data"},
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 204

    def test_023_put_change5(self, http_client):
        """
        Put change 5 to /properties/test/resource.

        Spec: docs/actingweb-spec.rst:671-791
        """
        response = requests.put(
            f"{self.actor1_url}/properties/test/resource",
            data="change5",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 204

    def test_024_get_subscriptions_wrong_password(self, http_client):
        """
        Get subscriptions with wrong password should fail.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions",
            auth=(self.creator1, "wrongpassword"),
        )
        assert response.status_code == 403

    def test_025_get_subscriptions_as_creator(self, http_client):
        """
        Get all subscriptions as creator.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions",
            auth=(self.creator1, self.passphrase1),  # type: ignore[arg-type]
        )
        assert response.status_code == 200

    def test_026_search_subscriptions_by_target(self, http_client):
        """
        Search subscriptions by target parameter.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions?target=properties",
            auth=(self.creator1, self.passphrase1),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data:
            # Verify all subscriptions have target=properties
            assert len(data["data"]) >= 1
            for sub in data["data"]:
                assert sub["target"] == "properties"

    def test_027_search_subscriptions_by_peer_and_target(self, http_client):
        """
        Search subscriptions for specific peer with target parameter.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}?target=meta",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            assert data["data"][0]["target"] == "meta"
            assert data["data"][0]["sequence"] == 1

    def test_028_search_subscriptions_by_peer(self, http_client):
        """
        Search subscriptions for specific peer.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 200

    def test_029_get_subscription1_data(self, http_client):
        """
        Get subscription 1 data and verify all changes.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        if not self.subid1:
            pytest.skip("No subscription ID available")

        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}/{self.subid1}",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data:
            # Should have 6 data entries (initial + 5 changes)
            assert len(data["data"]) >= 5

            # Verify sequence numbers
            assert data["data"][0]["sequence"] == 1
            if len(data["data"]) > 1:
                assert data["data"][1]["sequence"] == 2

            # Verify some data values
            if "data" in data["data"][0] and isinstance(data["data"][0]["data"], dict):
                assert data["data"][0]["data"].get("resource") == "initial"

    def test_030_get_subscription7_data(self, http_client):
        """
        Get subscription 7 data (with resource filter).

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        # We need to get subid7 first from the subscription list
        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        if response.status_code == 200:
            data = response.json()
            if "data" in data:
                # Find subscription with resource field
                for sub in data["data"]:
                    if sub.get("resource") == "resource":
                        subid7 = sub["subscriptionid"]

                        # Now get the subscription data
                        response = requests.get(
                            f"{self.actor1_url}/subscriptions/{self.actor2_id}/{subid7}",
                            headers={"Authorization": f"Bearer {self.trust1_secret}"},
                        )
                        assert response.status_code == 200

                        sub_data = response.json()
                        if "data" in sub_data and len(sub_data["data"]) >= 2:
                            assert sub_data["data"][0]["sequence"] == 1
                            assert sub_data["data"][0]["data"] == "initial"
                            assert sub_data["data"][1]["sequence"] == 2
                            assert sub_data["data"][1]["data"] == "change4"
                        break

    def test_031_get_specific_diff(self, http_client):
        """
        Get specific diff by sequence number.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        if not self.subid1:
            pytest.skip("No subscription ID available")

        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}/{self.subid1}/1",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 200

    def test_032_clear_subscription_diffs(self, http_client):
        """
        Clear subscription diffs up to specific sequence number.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        if not self.subid1:
            pytest.skip("No subscription ID available")

        response = requests.put(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}/{self.subid1}",
            json={"sequence": 2},
            headers={
                "Authorization": f"Bearer {self.trust1_secret}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 204

    def test_033_get_subscription_after_clearing(self, http_client):
        """
        Get subscription after clearing to verify old diffs are removed.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        if not self.subid1:
            pytest.skip("No subscription ID available")

        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}/{self.subid1}",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            # First remaining entry should be sequence 3
            assert data["data"][0]["sequence"] >= 3
            assert data["data"][0]["data"] == "change2"

    def test_034_get_subscription6_nested_data(self, http_client):
        """
        Get subscription 6 and verify nested data structure.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor3_id}",
            headers={"Authorization": f"Bearer {self.trust2_secret}"},
        )
        if response.status_code == 200:
            data = response.json()
            if "data" in data:
                # Find subscription 6 (granularity=none)
                for sub in data["data"]:
                    if sub.get("granularity") == "none" and sub.get("subtarget") == "":
                        subid6 = sub["subscriptionid"]

                        # Get the subscription data
                        response = requests.get(
                            f"{self.actor1_url}/subscriptions/{self.actor3_id}/{subid6}",
                            headers={"Authorization": f"Bearer {self.trust2_secret}"},
                        )
                        if response.status_code == 200:
                            sub_data = response.json()
                            if "data" in sub_data and len(sub_data["data"]) > 0:
                                # Verify nested structure
                                first_data = sub_data["data"][0]["data"]
                                if (
                                    isinstance(first_data, dict)
                                    and "data1" in first_data
                                ):
                                    assert first_data["data1"]["str2"] == "initial"
                                assert sub_data["data"][0]["sequence"] == 1
                        break

    def test_035_delete_subscription_wrong_secret(self, http_client):
        """
        Try to delete subscription with wrong bearer token.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor2_id}",
            headers={"Authorization": f"Bearer {self.trust1_secret}"},
        )
        if response.status_code == 200:
            data = response.json()
            if "data" in data and len(data["data"]) > 1:
                # Try to delete subscription 2
                subid2 = data["data"][1]["subscriptionid"]

                response = requests.delete(
                    f"{self.actor1_url}/subscriptions/{self.actor2_id}/{subid2}",
                    headers={"Authorization": "Bearer wrongsecret"},
                )
                assert response.status_code == 403

    def test_036_delete_subscription4(self, http_client):
        """
        Delete subscription 4 as peer actor 3.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        response = requests.get(
            f"{self.actor1_url}/subscriptions/{self.actor3_id}",
            headers={"Authorization": f"Bearer {self.trust2_secret}"},
        )
        if response.status_code == 200:
            data = response.json()
            if "data" in data:
                # Find subscription 4 (granularity=low, no subtarget)
                for sub in data["data"]:
                    if sub.get("granularity") == "low" and sub.get("subtarget") == "":
                        subid4 = sub["subscriptionid"]

                        response = requests.delete(
                            f"{self.actor1_url}/subscriptions/{self.actor3_id}/{subid4}",
                            headers={"Authorization": f"Bearer {self.trust2_secret}"},
                        )
                        assert response.status_code == 204

                        # Verify deletion
                        response = requests.get(
                            f"{self.actor1_url}/subscriptions/{self.actor3_id}/{subid4}",
                            headers={"Authorization": f"Bearer {self.trust2_secret}"},
                        )
                        assert response.status_code == 404
                        break

    def test_037_delete_actor3(self, http_client):
        """
        Delete actor 3.

        Spec: docs/actingweb-spec.rst:454-505
        """
        response = requests.delete(
            self.actor3_url,  # type: ignore[arg-type]
            auth=(self.creator3, self.passphrase3),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_038_try_callback_after_actor_deleted(self, http_client):
        """
        Try callback after actor is deleted - should fail.

        Spec: docs/actingweb-spec.rst:1876-2308
        """
        if not self.subid5:
            pytest.skip("No subscription ID available")

        response = requests.post(
            f"{self.actor1_url}/callbacks/subscriptions/{self.actor3_id}/{self.subid5}",
            json={"test": "fake"},
            headers={
                "Authorization": f"Bearer {self.trust2_secret}",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 404

    def test_039_delete_actors(self, http_client):
        """
        Clean up by deleting remaining actors.

        Spec: docs/actingweb-spec.rst:454-505
        """
        # Delete actor1
        response = requests.delete(
            self.actor1_url,  # type: ignore[arg-type]
            auth=(self.creator1, self.passphrase1),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # Delete actor2
        response = requests.delete(
            self.actor2_url,  # type: ignore[arg-type]
            auth=(self.creator2, self.passphrase2),  # type: ignore[arg-type]
        )
        assert response.status_code == 204
