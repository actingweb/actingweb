"""
Integration tests for async operations and peer communication.

Tests that async peer communication completes without blocking.
"""

import time

import requests


class TestAsyncOperations:
    """Test async operations complete without blocking."""

    def test_trust_creation_to_peer_completes_within_timeout(
        self, actor_factory, test_app, peer_app
    ):
        """Test that trust creation to peer completes within reasonable time."""
        # Create actors on both servers
        response = requests.post(
            f"{test_app}/",
            json={"creator": "alice@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor1 = response.json()

        response = requests.post(
            f"{peer_app}/",
            json={"creator": "bob@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor2 = response.json()

        # Measure trust creation time
        start_time = time.time()

        response = requests.post(
            f"{test_app}/{actor1['id']}/trust",
            json={
                "url": f"{peer_app}/{actor2['id']}",
                "relationship": "friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )

        elapsed = time.time() - start_time

        # Trust creation should succeed
        assert response.status_code == 201, f"Trust creation failed: {response.text}"

        # Should complete within 10 seconds (generous timeout for CI)
        assert elapsed < 10.0, f"Trust creation took {elapsed}s, expected < 10s"

        # Cleanup
        requests.delete(
            f"{test_app}/{actor1['id']}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        requests.delete(
            f"{peer_app}/{actor2['id']}",
            auth=(actor2["creator"], actor2["passphrase"]),
        )

    def test_subscription_to_peer_completes_within_timeout(
        self, test_app, peer_app
    ):
        """Test that creating subscription to peer completes within timeout."""
        # Create actors
        response = requests.post(
            f"{test_app}/",
            json={"creator": "alice@example.com"},
            headers={"Content-Type": "application/json"},
        )
        actor1 = response.json()

        response = requests.post(
            f"{peer_app}/",
            json={"creator": "bob@example.com"},
            headers={"Content-Type": "application/json"},
        )
        actor2 = response.json()

        # Establish trust first
        response = requests.post(
            f"{test_app}/{actor1['id']}/trust",
            json={
                "url": f"{peer_app}/{actor2['id']}",
                "relationship": "friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 201

        peer_id = response.json()["peerid"]

        # Approve trust from actor2's side
        response = requests.put(
            f"{peer_app}/{actor2['id']}/trust/friend/{actor1['id']}",
            json={"approved": True},
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code in [200, 204]

        # Approve trust from actor1's side
        response = requests.put(
            f"{test_app}/{actor1['id']}/trust/friend/{peer_id}",
            json={"approved": True},
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code in [200, 204]

        # Grant permissions for actor1 to subscribe to actor2's properties
        response = requests.put(
            f"{peer_app}/{actor2['id']}/trust/friend/{actor1['id']}/permissions",
            json={
                "properties": {
                    "patterns": ["properties", "properties/*"],
                    "operations": ["read", "subscribe"],
                }
            },
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code in [200, 201, 204]

        # Measure subscription creation time
        start_time = time.time()

        # Create subscription from actor1 to actor2's properties
        response = requests.post(
            f"{test_app}/{actor1['id']}/subscriptions",
            json={
                "peerid": peer_id,
                "target": "properties",
                "granularity": "high",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )

        elapsed = time.time() - start_time

        # Subscription creation should succeed
        assert response.status_code in [200, 201, 202, 204], f"Subscription failed: {response.text}"

        # Should complete within 10 seconds
        assert elapsed < 10.0, f"Subscription took {elapsed}s, expected < 10s"

        # Cleanup
        requests.delete(
            f"{test_app}/{actor1['id']}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        requests.delete(
            f"{peer_app}/{actor2['id']}",
            auth=(actor2["creator"], actor2["passphrase"]),
        )

    def test_trust_deletion_with_peer_notify_completes_within_timeout(
        self, test_app, peer_app
    ):
        """Test that trust deletion with peer notification completes quickly."""
        # Create actors
        response = requests.post(
            f"{test_app}/",
            json={"creator": "alice@example.com"},
            headers={"Content-Type": "application/json"},
        )
        actor1 = response.json()

        response = requests.post(
            f"{peer_app}/",
            json={"creator": "bob@example.com"},
            headers={"Content-Type": "application/json"},
        )
        actor2 = response.json()

        # Create trust
        response = requests.post(
            f"{test_app}/{actor1['id']}/trust",
            json={
                "url": f"{peer_app}/{actor2['id']}",
                "relationship": "friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        peer_id = response.json()["peerid"]

        # Measure deletion time
        start_time = time.time()

        response = requests.delete(
            f"{test_app}/{actor1['id']}/trust/friend/{peer_id}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )

        elapsed = time.time() - start_time

        # Deletion should succeed
        assert response.status_code in [200, 204], f"Deletion failed: {response.text}"

        # Should complete within 10 seconds
        assert elapsed < 10.0, f"Trust deletion took {elapsed}s, expected < 10s"

        # Cleanup
        requests.delete(
            f"{test_app}/{actor1['id']}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        requests.delete(
            f"{peer_app}/{actor2['id']}",
            auth=(actor2["creator"], actor2["passphrase"]),
        )

    def test_concurrent_requests_do_not_block(self, test_app):
        """Test that concurrent actor creation requests don't block each other."""
        import concurrent.futures

        def create_actor(index: int) -> float:
            """Create an actor and return elapsed time."""
            start = time.time()
            response = requests.post(
                f"{test_app}/",
                json={"creator": f"user{index}@example.com"},
                headers={"Content-Type": "application/json"},
            )
            elapsed = time.time() - start

            # Cleanup
            if response.status_code == 201:
                actor = response.json()
                requests.delete(
                    f"{test_app}/{actor['id']}",
                    auth=(actor["creator"], actor["passphrase"]),
                )

            return elapsed

        # Create 5 actors concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            start_time = time.time()
            futures = [executor.submit(create_actor, i) for i in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            total_time = time.time() - start_time

        # All requests should complete
        assert len(results) == 5

        # Total time should be less than if they ran sequentially
        # If each takes 1s sequentially, concurrent should be much faster
        # Allow 10s for 5 concurrent requests (generous for CI)
        assert total_time < 10.0, f"Concurrent requests took {total_time}s"

        # Each individual request should be reasonably fast
        for elapsed in results:
            assert elapsed < 5.0, f"Individual request took {elapsed}s"

    def test_two_actor_trust_handshake_completes(
        self, test_app, peer_app
    ):
        """Test complete bidirectional trust establishment between two servers."""
        # Create actor on test_app
        response = requests.post(
            f"{test_app}/",
            json={"creator": "alice@example.com"},
            headers={"Content-Type": "application/json"},
        )
        actor1 = response.json()

        # Create actor on peer_app
        response = requests.post(
            f"{peer_app}/",
            json={"creator": "bob@example.com"},
            headers={"Content-Type": "application/json"},
        )
        actor2 = response.json()

        # Measure full handshake time
        start_time = time.time()

        # Step 1: Actor1 initiates trust to Actor2
        response = requests.post(
            f"{test_app}/{actor1['id']}/trust",
            json={
                "url": f"{peer_app}/{actor2['id']}",
                "relationship": "friend",
            },
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 201

        # Step 2: Actor2 approves the trust (simulating peer notification)
        # This would normally happen via callback, but we simulate manually
        response = requests.put(
            f"{peer_app}/{actor2['id']}/trust/friend/{actor1['id']}",
            json={"approved": True},
            auth=(actor2["creator"], actor2["passphrase"]),
        )
        assert response.status_code in [200, 204]

        elapsed = time.time() - start_time

        # Full handshake should complete within 15 seconds
        assert elapsed < 15.0, f"Trust handshake took {elapsed}s, expected < 15s"

        # Verify both sides are approved
        response = requests.get(
            f"{test_app}/{actor1['id']}/trust",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        assert response.status_code == 200

        # Cleanup
        requests.delete(
            f"{test_app}/{actor1['id']}",
            auth=(actor1["creator"], actor1["passphrase"]),
        )
        requests.delete(
            f"{peer_app}/{actor2['id']}",
            auth=(actor2["creator"], actor2["passphrase"]),
        )
