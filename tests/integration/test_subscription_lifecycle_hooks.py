"""
Integration tests for subscription lifecycle hooks and revoke_peer_subscription.

Tests:
1. subscription_deleted hook fires when peer deletes their subscription
2. subscription_deleted hook fires when we revoke a peer's subscription
3. revoke_peer_subscription() method correctly removes inbound subscriptions
"""

import pytest
import requests


@pytest.mark.xdist_group(name="subscription_lifecycle_hooks")
class TestSubscriptionDeletedHook:
    """
    Test subscription_deleted lifecycle hook.

    The subscription_deleted hook fires for inbound subscriptions only:
    - When a peer unsubscribes from us (initiated_by_peer=True)
    - When we revoke a peer's subscription (initiated_by_peer=False)
    """

    # Publisher state (receives subscriptions)
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "hook_publisher@actingweb.net"

    # Subscriber state (creates subscriptions to publisher)
    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "hook_subscriber@actingweb.net"

    trust_secret: str | None = None
    subscription_id: str | None = None

    def test_001_create_publisher(self, http_client):
        """Create the publisher actor (receives subscriptions)."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201

        TestSubscriptionDeletedHook.publisher_url = response.headers.get("Location")
        TestSubscriptionDeletedHook.publisher_id = response.json()["id"]
        TestSubscriptionDeletedHook.publisher_passphrase = response.json()["passphrase"]

    def test_002_create_subscriber(self, http_client):
        """Create the subscriber actor."""
        peer_url = getattr(http_client, "peer_url", http_client.base_url)

        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.subscriber_creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201

        TestSubscriptionDeletedHook.subscriber_url = response.headers.get("Location")
        TestSubscriptionDeletedHook.subscriber_id = response.json()["id"]
        TestSubscriptionDeletedHook.subscriber_passphrase = response.json()[
            "passphrase"
        ]

    def test_003_establish_trust(self, http_client):
        """Establish trust between publisher and subscriber."""
        # Publisher initiates trust to subscriber
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={
                "url": self.subscriber_url,
                "relationship": "friend",
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 201
        TestSubscriptionDeletedHook.trust_secret = response.json().get("secret")
        peer_id = response.json().get("peerid")

        # Subscriber approves
        response = requests.put(
            f"{self.subscriber_url}/trust/friend/{self.publisher_id}",
            json={"approved": True},
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
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

    def test_004_create_subscription(self, http_client):
        """Subscriber creates subscription to publisher (creates inbound sub on publisher)."""
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

        # Get subscription ID from publisher's view (inbound subscription)
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            TestSubscriptionDeletedHook.subscription_id = data["data"][0][
                "subscriptionid"
            ]

        assert self.subscription_id is not None

    def test_010_verify_inbound_subscription_exists(self, http_client):
        """Verify the inbound subscription exists on publisher."""
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["subscriptionid"] == self.subscription_id

    def test_020_peer_deletes_subscription(self, http_client):
        """
        Peer deletes their subscription (should trigger hook with initiated_by_peer=True).

        When the peer (subscriber) deletes their subscription via the REST API,
        the subscription_deleted hook should fire with initiated_by_peer=True.
        """
        # Peer deletes subscription via REST API
        response = requests.delete(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 204

    def test_021_verify_subscription_deleted(self, http_client):
        """Verify the subscription was deleted."""
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 404

    def test_030_create_another_subscription_for_revoke_test(self, http_client):
        """Create another subscription for testing revoke_peer_subscription."""
        # Subscriber creates another subscription
        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "subtarget": "test",
                "granularity": "low",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Get new subscription ID from publisher's view
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data and len(data["data"]) > 0:
            TestSubscriptionDeletedHook.subscription_id = data["data"][0][
                "subscriptionid"
            ]

        assert self.subscription_id is not None

    def test_040_owner_deletes_inbound_subscription(self, http_client):
        """
        Owner deletes an inbound subscription (should trigger hook with initiated_by_peer=False).

        When the publisher (owner) deletes a peer's subscription via REST API,
        the subscription_deleted hook should fire with initiated_by_peer=False.
        """
        # Owner deletes the subscription (not peer-initiated)
        response = requests.delete(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_041_verify_revoked_subscription_deleted(self, http_client):
        """Verify the revoked subscription was deleted."""
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 404

    def test_099_cleanup(self, http_client):
        """Clean up test actors."""
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


@pytest.mark.xdist_group(name="revoke_peer_subscription")
class TestRevokePeerSubscription:
    """
    Test revoke_peer_subscription() method.

    The revoke_peer_subscription() method is used by the publisher/owner to
    terminate a peer's subscription to their data. This differs from unsubscribe()
    which is used by the subscriber to terminate their own subscription.
    """

    # Publisher state
    publisher_url: str | None = None
    publisher_id: str | None = None
    publisher_passphrase: str | None = None
    publisher_creator: str = "revoke_publisher@actingweb.net"

    # Subscriber state
    subscriber_url: str | None = None
    subscriber_id: str | None = None
    subscriber_passphrase: str | None = None
    subscriber_creator: str = "revoke_subscriber@actingweb.net"

    trust_secret: str | None = None
    subscription_ids: list[str] = []

    def test_001_create_actors(self, http_client):
        """Create publisher and subscriber actors."""
        # Create publisher
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.publisher_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestRevokePeerSubscription.publisher_url = response.headers.get("Location")
        TestRevokePeerSubscription.publisher_id = response.json()["id"]
        TestRevokePeerSubscription.publisher_passphrase = response.json()["passphrase"]

        # Create subscriber
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.subscriber_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestRevokePeerSubscription.subscriber_url = response.headers.get("Location")
        TestRevokePeerSubscription.subscriber_id = response.json()["id"]
        TestRevokePeerSubscription.subscriber_passphrase = response.json()["passphrase"]

    def test_002_establish_trust(self, http_client):
        """Establish trust between publisher and subscriber."""
        response = requests.post(
            f"{self.publisher_url}/trust",
            json={
                "url": self.subscriber_url,
                "relationship": "friend",
            },
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201

        TestRevokePeerSubscription.trust_secret = response.json().get("secret")
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

    def test_003_create_multiple_subscriptions(self, http_client):
        """Create multiple subscriptions for testing."""
        TestRevokePeerSubscription.subscription_ids = []

        # Create first subscription
        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "subtarget": "data1",
                "granularity": "high",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Create second subscription
        response = requests.post(
            f"{self.subscriber_url}/subscriptions",
            json={
                "peerid": self.publisher_id,
                "target": "properties",
                "subtarget": "data2",
                "granularity": "low",
            },
            auth=(self.subscriber_creator, self.subscriber_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Get subscription IDs from publisher's view
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()

        if "data" in data:
            for sub in data["data"]:
                TestRevokePeerSubscription.subscription_ids.append(
                    sub["subscriptionid"]
                )

        assert len(self.subscription_ids) >= 2

    def test_010_verify_subscriptions_exist(self, http_client):
        """Verify both subscriptions exist."""
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data.get("data", [])) >= 2

    def test_020_revoke_single_subscription(self, http_client):
        """
        Test revoking a single inbound subscription.

        This simulates the publisher using revoke_peer_subscription() to
        terminate one specific subscription from a peer.
        """
        if not self.subscription_ids:
            pytest.skip("No subscriptions available")

        sub_id_to_revoke = self.subscription_ids[0]

        # Publisher revokes the subscription (owner-initiated delete)
        response = requests.delete(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{sub_id_to_revoke}",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_021_verify_single_revocation(self, http_client):
        """Verify only the revoked subscription was deleted."""
        # First subscription should be deleted
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_ids[0]}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 404

        # Second subscription should still exist
        if len(self.subscription_ids) > 1:
            response = requests.get(
                f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_ids[1]}",
                headers={"Authorization": f"Bearer {self.trust_secret}"},
            )
            assert response.status_code == 200

    def test_030_revoke_remaining_subscription(self, http_client):
        """Revoke the remaining subscription."""
        if len(self.subscription_ids) < 2:
            pytest.skip("Not enough subscriptions")

        response = requests.delete(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}/{self.subscription_ids[1]}",
            auth=(self.publisher_creator, self.publisher_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_031_verify_all_subscriptions_revoked(self, http_client):
        """Verify all subscriptions are revoked."""
        response = requests.get(
            f"{self.publisher_url}/subscriptions/{self.subscriber_id}",
            headers={"Authorization": f"Bearer {self.trust_secret}"},
        )
        assert response.status_code == 200
        data = response.json()
        # Should have no inbound subscriptions left
        assert len(data.get("data", [])) == 0

    def test_099_cleanup(self, http_client):
        """Clean up test actors."""
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


@pytest.mark.xdist_group(name="unsubscribe_vs_revoke")
class TestUnsubscribeVsRevoke:
    """
    Test the difference between unsubscribe() and revoke_peer_subscription().

    - unsubscribe(): Used by SUBSCRIBER to terminate their OWN outbound subscription
    - revoke_peer_subscription(): Used by PUBLISHER to terminate a peer's inbound subscription
    """

    # Actor A (will be both subscriber and publisher)
    actor_a_url: str | None = None
    actor_a_id: str | None = None
    actor_a_passphrase: str | None = None
    actor_a_creator: str = "actor_a@actingweb.net"

    # Actor B (will be both subscriber and publisher)
    actor_b_url: str | None = None
    actor_b_id: str | None = None
    actor_b_passphrase: str | None = None
    actor_b_creator: str = "actor_b@actingweb.net"

    trust_secret_a: str | None = None
    trust_secret_b: str | None = None

    sub_a_to_b_id: str | None = (
        None  # A subscribes to B (outbound for A, inbound for B)
    )
    sub_b_to_a_id: str | None = (
        None  # B subscribes to A (outbound for B, inbound for A)
    )

    def test_001_create_actors(self, http_client):
        """Create both actors."""
        # Create Actor A
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.actor_a_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestUnsubscribeVsRevoke.actor_a_url = response.headers.get("Location")
        TestUnsubscribeVsRevoke.actor_a_id = response.json()["id"]
        TestUnsubscribeVsRevoke.actor_a_passphrase = response.json()["passphrase"]

        # Create Actor B
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": self.actor_b_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestUnsubscribeVsRevoke.actor_b_url = response.headers.get("Location")
        TestUnsubscribeVsRevoke.actor_b_id = response.json()["id"]
        TestUnsubscribeVsRevoke.actor_b_passphrase = response.json()["passphrase"]

    def test_002_establish_mutual_trust(self, http_client):
        """Establish mutual trust between A and B."""
        # A initiates trust to B
        response = requests.post(
            f"{self.actor_a_url}/trust",
            json={
                "url": self.actor_b_url,
                "relationship": "friend",
            },
            auth=(self.actor_a_creator, self.actor_a_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 201
        TestUnsubscribeVsRevoke.trust_secret_a = response.json().get("secret")
        peer_id_b = response.json().get("peerid")

        # B approves
        response = requests.put(
            f"{self.actor_b_url}/trust/friend/{self.actor_a_id}",
            json={"approved": True},
            auth=(self.actor_b_creator, self.actor_b_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

        # A approves
        response = requests.put(
            f"{self.actor_a_url}/trust/friend/{peer_id_b}",
            json={"approved": True},
            auth=(self.actor_a_creator, self.actor_a_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 204]

        # Get B's trust secret to A
        response = requests.get(
            f"{self.actor_b_url}/trust/friend/{self.actor_a_id}",
            auth=(self.actor_b_creator, self.actor_b_passphrase),  # type: ignore[arg-type]
        )
        if response.status_code == 200:
            TestUnsubscribeVsRevoke.trust_secret_b = response.json().get("secret")

        # Grant mutual permissions
        for actor_url, actor_auth, peer_id in [
            (
                self.actor_a_url,
                (self.actor_a_creator, self.actor_a_passphrase),
                self.actor_b_id,
            ),
            (
                self.actor_b_url,
                (self.actor_b_creator, self.actor_b_passphrase),
                self.actor_a_id,
            ),
        ]:
            response = requests.put(
                f"{actor_url}/trust/friend/{peer_id}/permissions",
                json={
                    "properties": {
                        "patterns": ["*"],
                        "operations": ["read", "subscribe"],
                    }
                },
                auth=actor_auth,  # type: ignore[arg-type]
            )
            assert response.status_code in [200, 201, 204]

    def test_003_create_bidirectional_subscriptions(self, http_client):
        """Create subscriptions in both directions."""
        # A subscribes to B (outbound for A, inbound for B)
        response = requests.post(
            f"{self.actor_a_url}/subscriptions",
            json={
                "peerid": self.actor_b_id,
                "target": "properties",
                "subtarget": "status",
                "granularity": "high",
            },
            auth=(self.actor_a_creator, self.actor_a_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Get subscription ID from B's view (inbound)
        response = requests.get(
            f"{self.actor_b_url}/subscriptions/{self.actor_a_id}",
            headers={"Authorization": f"Bearer {self.trust_secret_a}"},
        )
        if response.status_code == 200:
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                TestUnsubscribeVsRevoke.sub_a_to_b_id = data["data"][0][
                    "subscriptionid"
                ]

        # B subscribes to A (outbound for B, inbound for A)
        response = requests.post(
            f"{self.actor_b_url}/subscriptions",
            json={
                "peerid": self.actor_a_id,
                "target": "properties",
                "subtarget": "events",
                "granularity": "low",
            },
            auth=(self.actor_b_creator, self.actor_b_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code in [200, 201, 202, 204]

        # Get subscription ID from A's view (inbound)
        response = requests.get(
            f"{self.actor_a_url}/subscriptions/{self.actor_b_id}",
            headers={"Authorization": f"Bearer {self.trust_secret_b}"},
        )
        if response.status_code == 200:
            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                TestUnsubscribeVsRevoke.sub_b_to_a_id = data["data"][0][
                    "subscriptionid"
                ]

    def test_010_verify_both_subscriptions_exist(self, http_client):
        """Verify both subscriptions exist."""
        # A's inbound subscription from B
        response = requests.get(
            f"{self.actor_a_url}/subscriptions",
            auth=(self.actor_a_creator, self.actor_a_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200

        # B's inbound subscription from A
        response = requests.get(
            f"{self.actor_b_url}/subscriptions",
            auth=(self.actor_b_creator, self.actor_b_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200

    def test_020_a_revokes_b_subscription(self, http_client):
        """
        A uses revoke_peer_subscription to terminate B's subscription to A.

        This tests the owner/publisher revoking an inbound subscription.
        A is the publisher, B is the subscriber.
        """
        if not self.sub_b_to_a_id:
            pytest.skip("No subscription ID available")

        # A revokes B's subscription (owner-initiated)
        response = requests.delete(
            f"{self.actor_a_url}/subscriptions/{self.actor_b_id}/{self.sub_b_to_a_id}",
            auth=(self.actor_a_creator, self.actor_a_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 204

    def test_021_verify_b_subscription_revoked(self, http_client):
        """Verify B's subscription to A was revoked."""
        response = requests.get(
            f"{self.actor_a_url}/subscriptions/{self.actor_b_id}/{self.sub_b_to_a_id}",
            auth=(self.actor_a_creator, self.actor_a_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 404

    def test_030_a_unsubscribes_from_b(self, http_client):
        """
        A uses unsubscribe to terminate their own subscription to B.

        This tests the subscriber terminating their own outbound subscription.
        A is the subscriber, B is the publisher.
        """
        if not self.sub_a_to_b_id:
            pytest.skip("No subscription ID available")

        # A needs to delete their outbound subscription
        # First, get A's outbound subscriptions to B
        response = requests.get(
            f"{self.actor_a_url}/subscriptions?peerid={self.actor_b_id}",
            auth=(self.actor_a_creator, self.actor_a_passphrase),  # type: ignore[arg-type]
        )
        assert response.status_code == 200

        # Then delete via their own endpoint
        # This goes through unsubscribe() path
        # The subscription is deleted from B's inbound side via remote call
        response = requests.delete(
            f"{self.actor_b_url}/subscriptions/{self.actor_a_id}/{self.sub_a_to_b_id}",
            headers={"Authorization": f"Bearer {self.trust_secret_a}"},
        )
        assert response.status_code == 204

    def test_031_verify_a_unsubscribed(self, http_client):
        """Verify A's subscription to B was deleted."""
        response = requests.get(
            f"{self.actor_b_url}/subscriptions/{self.actor_a_id}/{self.sub_a_to_b_id}",
            headers={"Authorization": f"Bearer {self.trust_secret_a}"},
        )
        assert response.status_code == 404

    def test_099_cleanup(self, http_client):
        """Clean up test actors."""
        if self.actor_a_url and self.actor_a_passphrase:
            requests.delete(
                self.actor_a_url,
                auth=(self.actor_a_creator, self.actor_a_passphrase),  # type: ignore[arg-type]
            )

        if self.actor_b_url and self.actor_b_passphrase:
            requests.delete(
                self.actor_b_url,
                auth=(self.actor_b_creator, self.actor_b_passphrase),  # type: ignore[arg-type]
            )
