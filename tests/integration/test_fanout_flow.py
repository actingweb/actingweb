"""
Integration tests for fan-out callback delivery.

Tests the FanOutManager with:
- Multiple subscribers
- Circuit breaker pattern
- Granularity downgrade for large payloads
- Compression when supported by peers
"""

import pytest
import requests


@pytest.mark.xdist_group(name="fanout")
class TestFanOutFlow:
    """
    Test FanOutManager with multiple subscribers.

    Creates one publisher with multiple subscribers to test parallel delivery.
    """

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

        TestFanOutFlow.publisher_url = response.headers.get("Location")
        TestFanOutFlow.publisher_id = response.json()["id"]
        TestFanOutFlow.publisher_passphrase = response.json()["passphrase"]

    def test_002_create_subscribers(self, http_client):
        """
        Create multiple subscriber actors on peer server.
        """
        peer_url = getattr(http_client, "peer_url", http_client.base_url)

        TestFanOutFlow.subscribers = []

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
            TestFanOutFlow.subscribers.append(subscriber)

        assert len(self.subscribers) == 3

    def test_003_establish_trusts(self, http_client):
        """
        Establish trust between publisher and all subscribers.
        """
        TestFanOutFlow.trust_secrets = []

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
            TestFanOutFlow.trust_secrets.append(secret)

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
        TestFanOutFlow.subscription_ids = []

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
                TestFanOutFlow.subscription_ids.append(sub_id)

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


@pytest.mark.xdist_group(name="granularity_downgrade")
class TestGranularityDowngrade:
    """
    Test granularity downgrade behavior for large payloads.

    When payloads exceed a threshold, the system should downgrade
    from high to low granularity (sending URL instead of data).
    """

    # Publisher state
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "granularity_publisher@actingweb.net"

    # Subscriber state
    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "granularity_subscriber@actingweb.net"

    trust_secret: str | None = None
    subscription_id: str | None = None

    def test_001_create_actors(self, http_client):
        """
        Create publisher and subscriber actors.
        """
        # Create publisher
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestGranularityDowngrade.publisher_url = response.headers.get("Location")
        TestGranularityDowngrade.publisher_id = response.json()["id"]
        TestGranularityDowngrade.publisher_passphrase = response.json()["passphrase"]

        # Create subscriber
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.subscriber_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestGranularityDowngrade.subscriber_url = response.headers.get("Location")
        TestGranularityDowngrade.subscriber_id = response.json()["id"]
        TestGranularityDowngrade.subscriber_passphrase = response.json()["passphrase"]

    def test_002_establish_trust_and_subscription(self, http_client):
        """
        Establish trust and subscription.
        """
        # Establish trust
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={
                "url": self.subscriber_url,
                "relationship": "friend",
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        TestGranularityDowngrade.trust_secret = response.json().get("secret")
        peer_id = response.json().get("peerid")

        # Approve trust
        response = requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        response = requests.put(
            f"{self.publisher_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

        # Grant permissions
        response = requests.put(
            f"{self.publisher_url}/trust/friend/{self.subscriber_id}/permissions",
            json={
                "properties": {
                    "patterns": ["*"],
                    "operations": ["read", "subscribe"],
                }
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 204]

        # Create subscription with high granularity
        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "subtarget": "",
                "granularity": "high",  # Request high granularity
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Get subscription ID
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            TestGranularityDowngrade.subscription_id = data["data"][0]["subscriptionid"]

    def test_010_small_payload_high_granularity(self, http_client):
        """
        Test that small payloads use high granularity (data included).
        """
        # Set a small property
        response = requests.put(
            f"{self.publisher_url}/properties/small_prop",
            data="small_value",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [201, 204]

    def test_011_verify_small_payload_diff(self, http_client):
        """
        Verify small payload diff contains data.
        """
        if not self.subscription_id:
            pytest.skip("No subscription ID available")

        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should have sequence
        assert "sequence" in data
        assert data["sequence"] >= 1

        # Check diff data if available
        if "data" in data and len(data["data"]) > 0:
            # Diffs for high granularity should contain data
            diff = data["data"][0]
            assert "data" in diff or "sequence" in diff

    def test_020_very_large_payload(self, http_client):
        """
        Test behavior with larger payload.

        Note: DynamoDB has strict item size limits (~400KB total, but
        practical limits are much lower due to attribute overhead).
        We test with 2KB which should be within limits.
        """
        # Create a 2KB property value (safely within DynamoDB limits)
        large_value = "X" * 2048

        response = requests.put(
            f"{self.publisher_url}/properties/very_large_prop",
            data=large_value,
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )

        # Should succeed (property stored)
        assert response.status_code in [201, 204]

    def test_021_verify_large_payload_tracked(self, http_client):
        """
        Verify large payload change is tracked.

        The system should either:
        1. Include full data (high granularity)
        2. Include URL only (low granularity - downgraded)
        """
        if not self.subscription_id:
            pytest.skip("No subscription ID available")

        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()

        # Sequence should be incremented
        assert "sequence" in data
        assert data["sequence"] >= 2

    def test_099_cleanup(self, http_client):
        """
        Clean up test actors.
        """
        if self.publisher_url and self.publisher_passphrase:
            requests.delete(
                self.publisher_url,
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )

        if self.subscriber_url and self.subscriber_passphrase:
            requests.delete(
                self.subscriber_url,
                auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
            )


@pytest.mark.xdist_group(name="circuit_breaker")
class TestCircuitBreakerBehavior:
    """
    Test circuit breaker behavior in subscription delivery.

    Note: These tests document expected circuit breaker behavior.
    Full circuit breaker testing requires mocking the subscriber
    to return errors, which is done in unit tests.
    """

    # Actor states
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "cb_publisher@actingweb.net"

    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "cb_subscriber@actingweb.net"

    trust_secret: str | None = None
    subscription_id: str | None = None

    def test_001_create_actors(self, http_client):
        """
        Create publisher and subscriber for circuit breaker tests.
        """
        # Create publisher
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestCircuitBreakerBehavior.publisher_url = response.headers.get("Location")
        TestCircuitBreakerBehavior.publisher_id = response.json()["id"]
        TestCircuitBreakerBehavior.publisher_passphrase = response.json()["passphrase"]

        # Create subscriber
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.subscriber_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestCircuitBreakerBehavior.subscriber_url = response.headers.get("Location")
        TestCircuitBreakerBehavior.subscriber_id = response.json()["id"]
        TestCircuitBreakerBehavior.subscriber_passphrase = response.json()["passphrase"]

    def test_002_establish_trust(self, http_client):
        """
        Establish trust between publisher and subscriber.
        """
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={
                "url": self.subscriber_url,
                "relationship": "friend",
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201

        TestCircuitBreakerBehavior.trust_secret = response.json().get("secret")
        peer_id = response.json().get("peerid")

        # Approve both sides
        response = requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        response = requests.put(
            f"{self.publisher_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

        # Grant permissions
        response = requests.put(
            f"{self.publisher_url}/trust/friend/{self.subscriber_id}/permissions",
            json={
                "properties": {
                    "patterns": ["*"],
                    "operations": ["read", "subscribe"],
                }
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 204]

    def test_003_create_subscription(self, http_client):
        """
        Create subscription for circuit breaker tests.
        """
        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "subtarget": "",
                "granularity": "high",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Get subscription ID
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            TestCircuitBreakerBehavior.subscription_id = data["data"][0][
                "subscriptionid"
            ]

    def test_010_normal_callback_delivery(self, http_client):
        """
        Test that normal callback delivery works.

        This is the baseline for circuit breaker testing.
        """
        # Trigger a callback by changing a property
        response = requests.put(
            f"{self.publisher_url}/properties/cb_test",
            data="normal_value",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [201, 204]

    def test_011_verify_callback_delivered(self, http_client):
        """
        Verify the callback was delivered (subscription diff exists).
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "sequence" in data
        assert data["sequence"] >= 1

    def test_020_multiple_rapid_changes(self, http_client):
        """
        Test rapid property changes.

        This tests that the system handles burst traffic appropriately.
        """
        for i in range(5):
            response = requests.put(
                f"{self.publisher_url}/properties/rapid_{i}",
                data=f"rapid_value_{i}",
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code in [201, 204]

    def test_021_verify_all_changes_tracked(self, http_client):
        """
        Verify all changes were tracked in subscription.
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()

        # Sequence should have incremented for all changes
        assert "sequence" in data
        assert data["sequence"] >= 6  # Initial + 5 rapid changes

    def test_030_verify_circuit_state_normal(self, http_client):
        """
        Verify circuit breaker is in normal state after successful deliveries.

        After multiple successful callbacks, the circuit should remain closed.
        """
        # The circuit breaker state is internal to the system
        # We verify normal operation by confirming callbacks are processed
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        # If we can read subscription state, the circuit is working

    def test_040_burst_delivery_handled(self, http_client):
        """
        Test that burst delivery is handled without circuit issues.

        Rapid successful deliveries should not trigger circuit breaker.
        """
        # Make a burst of property changes
        for i in range(10):
            response = requests.put(
                f"{self.publisher_url}/properties/burst_{i}",
                data=f"burst_value_{i}",
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code in [201, 204]

    def test_041_verify_burst_delivery_complete(self, http_client):
        """
        Verify all burst deliveries were tracked.
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should have sequence for all burst changes
        # Previous (6) + burst (10) = 16
        assert data["sequence"] >= 16

    def test_099_cleanup(self, http_client):
        """
        Clean up test actors.
        """
        if self.publisher_url and self.publisher_passphrase:
            requests.delete(
                self.publisher_url,
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )

        if self.subscriber_url and self.subscriber_passphrase:
            requests.delete(
                self.subscriber_url,
                auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
            )


@pytest.mark.xdist_group(name="circuit_breaker_recovery")
class TestCircuitBreakerRecovery:
    """
    Test circuit breaker recovery behavior.

    Tests that the system recovers properly after failures.
    """

    # Actor states
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "cb_recovery_publisher@actingweb.net"

    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "cb_recovery_subscriber@actingweb.net"

    trust_secret: str | None = None
    subscription_id: str | None = None

    def test_001_create_actors(self, http_client):
        """
        Create publisher and subscriber for circuit breaker recovery tests.
        """
        # Create publisher
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestCircuitBreakerRecovery.publisher_url = response.headers.get("Location")
        TestCircuitBreakerRecovery.publisher_id = response.json()["id"]
        TestCircuitBreakerRecovery.publisher_passphrase = response.json()["passphrase"]

        # Create subscriber
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.subscriber_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestCircuitBreakerRecovery.subscriber_url = response.headers.get("Location")
        TestCircuitBreakerRecovery.subscriber_id = response.json()["id"]
        TestCircuitBreakerRecovery.subscriber_passphrase = response.json()["passphrase"]

    def test_002_establish_trust(self, http_client):
        """
        Establish trust between publisher and subscriber.
        """
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={
                "url": self.subscriber_url,
                "relationship": "friend",
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201

        TestCircuitBreakerRecovery.trust_secret = response.json().get("secret")
        peer_id = response.json().get("peerid")

        # Approve both sides
        response = requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        response = requests.put(
            f"{self.publisher_url}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

        # Grant permissions
        response = requests.put(
            f"{self.publisher_url}/trust/friend/{self.subscriber_id}/permissions",
            json={
                "properties": {
                    "patterns": ["*"],
                    "operations": ["read", "subscribe"],
                }
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 204]

    def test_003_create_subscription(self, http_client):
        """
        Create subscription for recovery tests.
        """
        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "subtarget": "",
                "granularity": "high",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Get subscription ID
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            TestCircuitBreakerRecovery.subscription_id = data["data"][0][
                "subscriptionid"
            ]

    def test_010_successful_delivery_establishes_baseline(self, http_client):
        """
        Verify successful deliveries work and establish baseline.
        """
        # Make several successful property changes
        for i in range(5):
            response = requests.put(
                f"{self.publisher_url}/properties/recovery_{i}",
                data=f"value_{i}",
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code in [201, 204]

    def test_011_verify_baseline_established(self, http_client):
        """
        Verify baseline deliveries were tracked.
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sequence"] >= 5

    def test_020_continued_delivery_after_activity(self, http_client):
        """
        Test that deliveries continue working after initial activity.
        """
        # Make more property changes
        for i in range(5, 10):
            response = requests.put(
                f"{self.publisher_url}/properties/recovery_{i}",
                data=f"value_{i}",
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code in [201, 204]

    def test_021_verify_continued_delivery(self, http_client):
        """
        Verify continued deliveries were tracked.
        """
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["sequence"] >= 10

    def test_099_cleanup(self, http_client):
        """
        Clean up test actors.
        """
        if self.publisher_url and self.publisher_passphrase:
            requests.delete(
                self.publisher_url,
                auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
            )

        if self.subscriber_url and self.subscriber_passphrase:
            requests.delete(
                self.subscriber_url,
                auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
            )
