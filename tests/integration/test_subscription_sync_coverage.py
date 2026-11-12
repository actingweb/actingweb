"""
Integration tests for subscription sync coverage gaps.

Tests end-to-end flows for:
- sync_peer trust revocation detection and cleanup
- sync_subscription baseline fetch scenarios
- Trust verification when all subscriptions return 404
"""

import pytest
import requests

pytestmark = pytest.mark.xdist_group(name="sync_coverage")


def _subscriptions_of(subscriber: dict | None, publisher: dict | None) -> list:
    """``subscriber``'s subscriptions at ``publisher``, from its own listing."""
    assert subscriber and publisher
    response = requests.get(
        f"{subscriber['url']}/subscriptions",
        params={"peerid": publisher["id"]},
        auth=(subscriber["creator"], subscriber["passphrase"]),
        timeout=5,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _subscription_id(subscriber: dict | None, publisher: dict | None) -> str:
    """The id of ``subscriber``'s one subscription at ``publisher``, from
    the subscriber's own listing."""
    assert subscriber and publisher
    response = requests.get(
        f"{subscriber['url']}/subscriptions",
        params={"peerid": publisher["id"]},
        auth=(subscriber["creator"], subscriber["passphrase"]),
        timeout=5,
    )
    assert response.status_code == 200, response.text
    rows = response.json()["data"]
    assert len(rows) == 1, rows
    return rows[0]["subscriptionid"]


def _sdk_actor(actor_id: str):
    """The actor through the library, under the test app's own config."""
    from actingweb.actor import Actor

    from .conftest import TEST_APP_CONFIG

    core = Actor(config=TEST_APP_CONFIG["config"])
    core.get(actor_id=actor_id)
    assert core.id == actor_id, f"actor {actor_id} not found"
    return core


class TestSyncPeerTrustRevocation:
    """Test sync_peer trust revocation detection end-to-end.

    When all subscription syncs return 404, sync_peer should:
    1. Verify if the trust relationship still exists on the peer
    2. If trust exists, clean up dead subscriptions but keep trust
    3. If trust doesn't exist, delete local trust and trigger hook
    """

    actor_a: dict | None = None
    actor_b: dict | None = None
    subscription_id: str | None = None

    def test_001_create_actors_and_establish_trust(
        self, class_actor_factory, trust_helper
    ) -> None:
        """Create two actors with trust relationship and subscription."""
        # Create actors
        TestSyncPeerTrustRevocation.actor_a = class_actor_factory.create(
            "trust_revoke_a@example.com"
        )
        TestSyncPeerTrustRevocation.actor_b = class_actor_factory.create(
            "trust_revoke_b@example.com"
        )

        # Establish trust from A to B
        trust_helper.establish(
            self.actor_a,
            self.actor_b,
            "friend",
            approve=True,  # type: ignore[arg-type]
        )

        # Grant permissions from B to A for properties
        response = requests.put(
            f"{self.actor_b['url']}/trust/friend/{self.actor_a['id']}/permissions",  # type: ignore[index]
            json={"properties": ["displayname", "status"]},
            auth=(self.actor_b["creator"], self.actor_b["passphrase"]),  # type: ignore[index]
            timeout=5,
        )
        assert response.status_code == 201

        # Set a property on B
        response = requests.put(
            f"{self.actor_b['url']}/properties/displayname",  # type: ignore[index]
            json={"value": "Actor B"},
            auth=(self.actor_b["creator"], self.actor_b["passphrase"]),  # type: ignore[index]
            timeout=5,
        )
        assert response.status_code == 204

        # Create subscription from A to B
        response = requests.post(
            f"{self.actor_a['url']}/subscriptions",  # type: ignore[index]
            json={
                "peerid": self.actor_b["id"],  # type: ignore[index]
                "target": "properties",
                "subtarget": "",
                "resource": "",
                "granularity": "high",
            },
            auth=(self.actor_a["creator"], self.actor_a["passphrase"]),  # type: ignore[index]
            timeout=5,
        )
        assert response.status_code == 204
        # 204 carries no body: the id is read from A's own listing.
        TestSyncPeerTrustRevocation.subscription_id = _subscription_id(
            self.actor_a, self.actor_b
        )

    def test_002_sync_with_valid_trust_succeeds(self) -> None:
        """Test sync_peer succeeds with valid trust."""
        assert self.actor_a and self.actor_b, "Previous test failed to create actors"

        from actingweb.interface.actor_interface import ActorInterface

        sdk_actor_a = _sdk_actor(self.actor_a["id"])

        actor_interface = ActorInterface(sdk_actor_a)
        result = actor_interface.subscriptions.sync_peer(self.actor_b["id"])

        assert result.success is True or (result.subscriptions_synced > 0), (
            f"Sync should succeed with valid trust: {result.error}"
        )

    def test_003_delete_subscription_on_peer(self) -> None:
        """B loses its subscription row for A without telling A.

        Deleted through the library at B, not over REST: B's REST delete
        also removes A's side, which would leave A nothing dead to clean.
        A keeps its callback subscription, now dead at B, with the trust
        intact on both sides."""
        assert (
            self.actor_a
            and self.actor_b
            and TestSyncPeerTrustRevocation.subscription_id
        ), "Previous test failed"

        sdk_actor_b = _sdk_actor(self.actor_b["id"])
        sub = sdk_actor_b.get_subscription_obj(
            peerid=self.actor_a["id"], subid=self.subscription_id, callback=False
        )
        assert sub and sub.get(), "B holds no subscription row for A"
        sub.delete()

        response = requests.get(
            f"{self.actor_b['url']}/subscriptions/{self.actor_a['id']}/{self.subscription_id}",
            auth=(self.actor_b["creator"], self.actor_b["passphrase"]),
            timeout=5,
        )
        assert response.status_code == 404, response.text
        assert [
            r["subscriptionid"] for r in _subscriptions_of(self.actor_a, self.actor_b)
        ] == [self.subscription_id]

    def test_004_sync_cleans_dead_subscription_preserves_trust(self) -> None:
        """sync_peer finds A's subscription gone at B (404), checks that B
        still holds the trust, deletes A's dead subscription and keeps the
        trust."""
        assert self.actor_a and self.actor_b, "Previous test failed"

        from actingweb.interface.actor_interface import ActorInterface

        sdk_actor_a = _sdk_actor(self.actor_a["id"])

        actor_interface = ActorInterface(sdk_actor_a)
        result = actor_interface.subscriptions.sync_peer(self.actor_b["id"])
        assert [
            (r.subscription_id, r.success, r.error_code)
            for r in result.subscription_results
        ] == [(self.subscription_id, False, 404)], result
        assert _subscriptions_of(self.actor_a, self.actor_b) == []

        # When subscription is gone but trust exists, the sync will fail
        # but trust should be preserved
        # Check that trust still exists
        response = requests.get(
            f"{self.actor_a['url']}/trust/friend/{self.actor_b['id']}",
            auth=(self.actor_a["creator"], self.actor_a["passphrase"]),
            timeout=5,
        )
        # Trust should still exist (200) because only the subscription was deleted
        assert response.status_code == 200, (
            f"Trust check returned unexpected status: {response.status_code}"
        )

    def test_005_cleanup(self) -> None:
        """Clean up test actors (handled by fixture cleanup)."""
        # Actors are cleaned up by class_actor_factory fixture
        pass


class TestSyncSubscriptionBaseline:
    """Test sync_subscription baseline fetch scenarios.

    When a subscription has no pending diffs, sync_subscription should
    fetch baseline data from the target resource.
    """

    actor_a: dict | None = None
    actor_b: dict | None = None
    subscription_id: str | None = None

    def test_001_setup_actors_and_subscription(
        self, class_actor_factory, trust_helper
    ) -> None:
        """Create actors, trust, and subscription."""
        # Create actors
        TestSyncSubscriptionBaseline.actor_a = class_actor_factory.create(
            "baseline_a@example.com"
        )
        TestSyncSubscriptionBaseline.actor_b = class_actor_factory.create(
            "baseline_b@example.com"
        )

        # Establish trust
        trust_helper.establish(
            self.actor_a,
            self.actor_b,
            "friend",
            approve=True,  # type: ignore[arg-type]
        )

        # Grant permissions
        response = requests.put(
            f"{self.actor_b['url']}/trust/friend/{self.actor_a['id']}/permissions",  # type: ignore[index]
            json={"properties": ["displayname", "status", "items"]},
            auth=(self.actor_b["creator"], self.actor_b["passphrase"]),  # type: ignore[index]
            timeout=5,
        )
        assert response.status_code == 201

        # Set properties on B
        response = requests.put(
            f"{self.actor_b['url']}/properties/displayname",  # type: ignore[index]
            json={"value": "Baseline Test User"},
            auth=(self.actor_b["creator"], self.actor_b["passphrase"]),  # type: ignore[index]
            timeout=5,
        )
        assert response.status_code == 204

        response = requests.put(
            f"{self.actor_b['url']}/properties/status",  # type: ignore[index]
            json={"value": "active"},
            auth=(self.actor_b["creator"], self.actor_b["passphrase"]),  # type: ignore[index]
            timeout=5,
        )
        assert response.status_code == 204

        # Create subscription from A to B
        response = requests.post(
            f"{self.actor_a['url']}/subscriptions",  # type: ignore[index]
            json={
                "peerid": self.actor_b["id"],  # type: ignore[index]
                "target": "properties",
                "subtarget": "",
                "resource": "",
                "granularity": "high",
            },
            auth=(self.actor_a["creator"], self.actor_a["passphrase"]),  # type: ignore[index]
            timeout=5,
        )
        assert response.status_code == 204
        # 204 carries no body: the id is read from A's own listing.
        TestSyncSubscriptionBaseline.subscription_id = _subscription_id(
            self.actor_a, self.actor_b
        )

    def test_002_sync_subscription_fetches_baseline(self) -> None:
        """Test that sync_subscription with no diffs fetches baseline data."""
        assert (
            self.actor_a
            and self.actor_b
            and TestSyncSubscriptionBaseline.subscription_id
        ), "Previous test failed"

        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.remote_storage import RemotePeerStore
        from actingweb.subscription_config import SubscriptionProcessingConfig

        sdk_actor_a = _sdk_actor(self.actor_a["id"])

        actor_interface = ActorInterface(sdk_actor_a)

        # Sync with auto_storage enabled
        sync_config = SubscriptionProcessingConfig(
            enabled=True, auto_storage=True, auto_sequence=True
        )

        result = actor_interface.subscriptions.sync_subscription(
            peer_id=self.actor_b["id"],
            subscription_id=self.subscription_id,  # type: ignore[arg-type]
            config=sync_config,
        )

        assert result.success, f"Sync failed: {result.error}"

        # Verify baseline data was stored
        remote_store = RemotePeerStore(
            actor=actor_interface, peer_id=self.actor_b["id"], validate_peer_id=False
        )

        displayname = remote_store.get_value("displayname")
        assert displayname is not None, "Baseline displayname should be stored"

        # Handle wrapped format
        if isinstance(displayname, dict) and "value" in displayname:
            assert displayname["value"] == "Baseline Test User"
        else:
            assert displayname == "Baseline Test User"

    def test_003_sync_with_list_property(self) -> None:
        """Test baseline fetch transforms list metadata to items."""
        assert (
            self.actor_a
            and self.actor_b
            and TestSyncSubscriptionBaseline.subscription_id
        ), "Previous test failed"

        # A list "items" at B with three items
        b_auth = (self.actor_b["creator"], self.actor_b["passphrase"])
        response = requests.post(
            f"{self.actor_b['url']}/properties",
            json={"items": {"_type": "list"}},
            auth=b_auth,
            timeout=5,
        )
        assert response.status_code == 201, response.text
        for i in range(3):
            response = requests.post(
                f"{self.actor_b['url']}/properties/items/items",
                json={"action": "add", "item_value": f"Item {i + 1}"},
                auth=b_auth,
                timeout=5,
            )
            assert response.status_code == 201, response.text

        from actingweb.interface.actor_interface import ActorInterface
        from actingweb.remote_storage import RemotePeerStore
        from actingweb.subscription_config import SubscriptionProcessingConfig

        sdk_actor_a = _sdk_actor(self.actor_a["id"])

        actor_interface = ActorInterface(sdk_actor_a)

        # Sync again to fetch list property
        sync_config = SubscriptionProcessingConfig(
            enabled=True, auto_storage=True, auto_sequence=True
        )

        (before,) = _subscriptions_of(self.actor_a, self.actor_b)
        result = actor_interface.subscriptions.sync_subscription(
            peer_id=self.actor_b["id"],
            subscription_id=self.subscription_id,  # type: ignore[arg-type]
            config=sync_config,
        )

        assert result.success, f"Sync failed: {result.error}"
        (after,) = _subscriptions_of(self.actor_a, self.actor_b)

        # Verify list items were stored
        remote_store = RemotePeerStore(
            actor=actor_interface, peer_id=self.actor_b["id"], validate_peer_id=False
        )

        # Today: B's REST item adds were queued as diffs, so the sync applies
        # them rather than the baseline, and a REST list diff is not applied
        # as a list operation (wire row WL1): A's replica list stays empty.
        # attribute-list-v2-port:4 owns the change.
        # The four queued diffs (the list created, three items added) are
        # what the sync applied, not a baseline: the counter says four, and
        # A's subscription moved four sequences on (the counter alone counts
        # a diff whatever its handler stored).
        assert result.diffs_processed == 4, result
        assert after["sequence"] == before["sequence"] + 4, (before, after)
        assert remote_store.get_list("items") == []

    def test_004_cleanup(self) -> None:
        """Clean up test actors (handled by fixture cleanup)."""
        pass


class TestSyncSubscriptionErrorHandling:
    """Test sync_subscription error handling scenarios."""

    actor_a: dict | None = None
    actor_b: dict | None = None

    def test_001_create_actors(self, class_actor_factory, trust_helper) -> None:
        """Create actors for error handling tests."""
        TestSyncSubscriptionErrorHandling.actor_a = class_actor_factory.create(
            "error_handling_a@example.com"
        )
        TestSyncSubscriptionErrorHandling.actor_b = class_actor_factory.create(
            "error_handling_b@example.com"
        )

        # Establish trust
        trust_helper.establish(
            self.actor_a,
            self.actor_b,
            "friend",
            approve=True,  # type: ignore[arg-type]
        )

    def test_002_sync_nonexistent_subscription_returns_404(self) -> None:
        """Test that syncing a non-existent subscription returns 404."""
        assert self.actor_a and self.actor_b, "Previous test failed"

        from actingweb.interface.actor_interface import ActorInterface

        sdk_actor_a = _sdk_actor(self.actor_a["id"])

        actor_interface = ActorInterface(sdk_actor_a)

        # Try to sync a subscription that doesn't exist
        result = actor_interface.subscriptions.sync_subscription(
            peer_id=self.actor_b["id"], subscription_id="nonexistent_sub_id_12345"
        )

        assert result.success is False
        assert result.error_code == 404
        assert "not found" in result.error.lower() if result.error else False

    def test_003_sync_with_no_trust_returns_error(self) -> None:
        """Test syncing with a peer we don't have trust with returns error."""
        assert self.actor_a, "Previous test failed"

        from actingweb.interface.actor_interface import ActorInterface

        sdk_actor_a = _sdk_actor(self.actor_a["id"])

        actor_interface = ActorInterface(sdk_actor_a)

        # Create a fake callback subscription to test the no-trust path
        # This subscription points to a peer we don't have trust with
        result = actor_interface.subscriptions.sync_subscription(
            peer_id="fake_peer_with_no_trust", subscription_id="fake_sub_id"
        )

        assert result.success is False
        # Could be 404 (subscription not found) since we don't have the callback subscription

    def test_004_cleanup(self) -> None:
        """Clean up test actors (handled by fixture cleanup)."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
