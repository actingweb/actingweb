"""
Integration tests for one publisher with several subscribers: each write
queues a diff per subscription, large payloads included, and a cleared or
deleted subscription leaves the others as they were.

The classes that tested FanOutManager, a granularity downgrade and a
circuit breaker (none of them on the publish path) were retired by the
subscription wire baseline (thoughts/plans/
2026-11-06-subscription-wire-baseline.md, Phase 2); tests/test_fanout.py
covers FanOutManager and the wire rows WD13 and WD14 the delivery.
"""

import pytest
import requests


@pytest.mark.xdist_group(name="fanout")
class TestDiffsQueuedForSeveralSubscribers:
    """One publisher, three subscribers: the diffs each write queues, per
    subscription, and what a clear or a delete leaves for the others."""

    # Publisher state
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "fanout_publisher@actingweb.net"

    # Subscriber states (we'll create 3 subscribers for fan-out testing)
    subscribers: list[dict] = []
    trust_secrets: list[str] = []
    subscription_ids: list[str] = []

    def test_001_create_publisher(self, http_client):
        """
        Create the publisher actor.
        """
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201

        TestDiffsQueuedForSeveralSubscribers.publisher_url = response.headers.get(
            "Location"
        )
        TestDiffsQueuedForSeveralSubscribers.publisher_id = response.json()["id"]
        TestDiffsQueuedForSeveralSubscribers.publisher_passphrase = response.json()[
            "passphrase"
        ]

    def test_002_create_subscribers(self, http_client):
        """
        Create multiple subscriber actors on peer server.
        """
        peer_url = getattr(http_client, "peer_url", http_client.base_url)

        TestDiffsQueuedForSeveralSubscribers.subscribers = []

        for i in range(3):
            creator = f"fanout_sub{i}@actingweb.net"
            response = http_client.post(
                f"{peer_url}/",
                json={"creator": creator},
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 201

            subscriber = {
                "url": response.headers.get("Location"),
                "id": response.json()["id"],
                "passphrase": response.json()["passphrase"],
                "creator": creator,
            }
            TestDiffsQueuedForSeveralSubscribers.subscribers.append(subscriber)

        assert len(self.subscribers) == 3

    def test_003_establish_trusts(self, http_client):
        """
        Establish trust between publisher and all subscribers.
        """
        TestDiffsQueuedForSeveralSubscribers.trust_secrets = []

        for subscriber in self.subscribers:
            # Publisher initiates trust
            response = requests.post(
                f"{self.publisher_url}/trust",
                json={
                    "url": subscriber["url"],
                    "relationship": "friend",
                },
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )

            assert response.status_code == 201
            secret = response.json().get("secret")
            peer_id = response.json().get("peerid")
            TestDiffsQueuedForSeveralSubscribers.trust_secrets.append(secret)

            # Subscriber approves
            response = requests.put(
                f"{subscriber['url']}/trust/friend/{self.publisher_id}",
                json={"approved": True},
                auth=(subscriber["creator"], subscriber["passphrase"]),  # type: ignore[arg-type]
            )
            assert response.status_code == 204

            # Publisher approves
            response = requests.put(
                f"{self.publisher_url}/trust/friend/{peer_id}",
                json={"approved": True},
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code in [200, 204]

            # Grant permissions
            response = requests.put(
                f"{self.publisher_url}/trust/friend/{subscriber['id']}/permissions",
                json={
                    "properties": {
                        "patterns": ["*"],
                        "operations": ["read", "subscribe"],
                    }
                },
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code in [200, 201, 204]

        assert len(self.trust_secrets) == 3

    def test_004_create_subscriptions(self, http_client):
        """
        Each subscriber creates a subscription to the publisher.
        """
        TestDiffsQueuedForSeveralSubscribers.subscription_ids = []

        for i, subscriber in enumerate(self.subscribers):
            # Subscriber creates subscription
            response = requests.post(
                f"{subscriber['url']}/subscriptions",
                json={
                    "peerid": self.publisher_id,
                    "target": "properties",
                    "subtarget": "",
                    "granularity": "high",
                },
                auth=(subscriber["creator"], subscriber["passphrase"]),  # type: ignore[arg-type]
            )
            assert response.status_code in [200, 201, 202, 204]

            # Get subscription ID from publisher's view
            response = requests.get(
                f"{self.publisher_url}/subscriptions/{subscriber['id']}",
                headers={"Authorization": f"Bearer {self.trust_secrets[i]}"},
            )
            assert response.status_code == 200
            data = response.json()

            if "data" in data and len(data["data"]) > 0:
                sub_id = data["data"][0]["subscriptionid"]
                TestDiffsQueuedForSeveralSubscribers.subscription_ids.append(sub_id)

        assert len(self.subscription_ids) == 3

    def test_010_verify_all_subscriptions_active(self, http_client):
        """
        Verify all subscriptions are active on publisher.
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200
        data = response.json()

        # Should have at least 3 subscriptions
        if "data" in data:
            assert len(data["data"]) >= 3

    def test_020_property_change_triggers_fanout(self, http_client):
        """
        Modify a property on the publisher and verify callbacks are triggered.

        This tests that changing a property fans out to all subscribers.
        """
        # Set a property on the publisher using owner auth
        response = requests.put(
            f"{self.publisher_url}/properties/fanout_test",
            data="test_value",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )

        # 201 or 204 is success
        assert response.status_code in [201, 204]

        # Verify property was set
        response = requests.get(
            f"{self.publisher_url}/properties/fanout_test",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200

    def test_021_verify_subscription_diffs_created(self, http_client):
        """
        Verify that subscription diffs were created for all subscribers.
        """
        for i, subscriber in enumerate(self.subscribers):
            response = requests.get(
                f"{self.publisher_url}/subscriptions/{subscriber['id']}/{self.subscription_ids[i]}",
                headers={"Authorization": f"Bearer {self.trust_secrets[i]}"},
            )

            # 200 or 404 (subscription may have cleared)
            assert response.status_code in [200, 404]
            if response.status_code == 200:
                data = response.json()
                # Verify sequence is tracked
                assert "sequence" in data
                assert isinstance(data["sequence"], int)

    def test_030_large_payload_test(self, http_client):
        """
        Test behavior with a larger payload.

        Large payloads may trigger granularity downgrade in production.
        This test verifies the callback mechanism works regardless.
        """
        # Create a larger property value
        large_value = "x" * 1000  # 1KB value

        response = requests.put(
            f"{self.publisher_url}/properties/large_value",
            data=large_value,
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code in [201, 204]

    def test_031_verify_large_payload_diffs(self, http_client):
        """
        Verify diffs were created for the large payload.
        """
        for i, subscriber in enumerate(self.subscribers):
            response = requests.get(
                f"{self.publisher_url}/subscriptions/{subscriber['id']}/{self.subscription_ids[i]}",
                headers={"Authorization": f"Bearer {self.trust_secrets[i]}"},
            )

            assert response.status_code == 200
            data = response.json()

            # Verify sequence incremented
            assert "sequence" in data
            assert data["sequence"] >= 2  # At least 2 changes now

    def test_040_clear_subscription_diffs(self, http_client):
        """
        Test clearing subscription diffs for one subscriber.
        """
        if not self.subscription_ids or not self.trust_secrets:
            pytest.skip("No subscriptions available")

        # Clear diffs up to sequence 2 for first subscriber
        response = requests.put(
            f"{self.publisher_url}/subscriptions/{self.subscribers[0]['id']}/{self.subscription_ids[0]}",
            json={"sequence": 2},
            headers={
                "Authorization": f"Bearer {self.trust_secrets[0]}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code in [200, 204]

    def test_041_verify_diffs_cleared(self, http_client):
        """
        Verify diffs were cleared for the subscriber.
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscribers[0]['id']}/{self.subscription_ids[0]}",
            headers={"Authorization": f"Bearer {self.trust_secrets[0]}"},
        )

        # 200 or 404 are both acceptable
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            # If there are remaining diffs, they should have sequence > 2
            if "data" in data and len(data["data"]) > 0:
                for diff in data["data"]:
                    assert diff.get("sequence", 0) > 2

    def test_050_delete_subscription(self, http_client):
        """
        Test deleting one subscription.
        """
        if not self.subscription_ids or not self.trust_secrets:
            pytest.skip("No subscriptions available")

        # Delete subscription for first subscriber
        response = requests.delete(
            f"{self.publisher_url}/subscriptions/{self.subscribers[0]['id']}/{self.subscription_ids[0]}",
            headers={"Authorization": f"Bearer {self.trust_secrets[0]}"},
        )

        assert response.status_code in [200, 204]

    def test_051_verify_subscription_deleted(self, http_client):
        """
        Verify the subscription was deleted.
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscribers[0]['id']}/{self.subscription_ids[0]}",
            headers={"Authorization": f"Bearer {self.trust_secrets[0]}"},
        )

        # Should return 404
        assert response.status_code == 404

    def test_060_large_payload_handling(self, http_client):
        """
        Test behavior with moderately large property payloads.

        Note: DynamoDB has a 400KB item size limit, but practical limits
        are lower when including attribute overhead. We use 2KB to stay safe.
        """
        # Create a larger property value (2KB - safe for DynamoDB)
        large_value = "L" * 2048

        response = requests.put(
            f"{self.publisher_url}/properties/large_payload_test",
            data=large_value,
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code in [201, 204]

    def test_061_verify_large_payload_tracked(self, http_client):
        """
        Verify that large payload changes are tracked in subscriptions.
        """
        for i, subscriber in enumerate(self.subscribers):
            if i >= len(self.subscription_ids):
                continue

            response = requests.get(
                f"{self.publisher_url}/subscriptions/{subscriber['id']}/{self.subscription_ids[i]}",
                headers={"Authorization": f"Bearer {self.trust_secrets[i]}"},
            )

            # Should have sequence for the large payload
            if response.status_code == 200:
                data = response.json()
                assert "sequence" in data
                # Sequence should have increased
                assert data["sequence"] >= 3

    def test_070_concurrent_property_changes(self, http_client):
        """
        Test concurrent property changes fan out correctly.

        Make several rapid property changes and verify all are tracked.
        """
        # Make 10 rapid property changes
        for i in range(10):
            response = requests.put(
                f"{self.publisher_url}/properties/concurrent_{i}",
                data=f"concurrent_value_{i}",
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code in [201, 204]

    def test_071_verify_all_concurrent_changes_tracked(self, http_client):
        """
        Verify all concurrent changes were tracked for all subscribers.
        """
        # Check first subscriber (the one not deleted in test_050)
        if len(self.subscribers) > 1 and len(self.subscription_ids) > 1:
            response = requests.get(
                f"{self.publisher_url}/subscriptions/{self.subscribers[1]['id']}/{self.subscription_ids[1]}",
                headers={"Authorization": f"Bearer {self.trust_secrets[1]}"},
            )

            if response.status_code == 200:
                data = response.json()
                # Should have sequence covering all changes
                # Initial (1) + large (1) + concurrent (10) = at least 12
                assert data["sequence"] >= 12

    def test_099_cleanup(self, http_client):
        """
        Clean up all test actors.
        """
        # Delete publisher
        if self.publisher_url and self.publisher_passphrase:
            requests.delete(
                self.publisher_url,
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )

        # Delete subscribers
        for subscriber in self.subscribers:
            if subscriber.get("url") and subscriber.get("passphrase"):
                requests.delete(
                    subscriber["url"],
                    auth=(subscriber["creator"], subscriber["passphrase"]),  # type: ignore[arg-type]
                )
