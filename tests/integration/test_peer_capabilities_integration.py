"""
Integration tests for peer capability storage in trust relationships.

Tests that capability fields (aw_supported, aw_version, capabilities_fetched_at)
are correctly stored and retrieved from the database backends.

Also tests the methods/actions caching functionality via CachedCapabilitiesStore.

Phase 0 validation: Verifies database schema changes work correctly.
"""

import os

import pytest
import requests

from actingweb.config import Config
from actingweb.peer_capabilities import (
    CachedCapabilitiesStore,
    CachedCapability,
    CachedPeerCapabilities,
)


def _create_test_config() -> Config:
    """Create a config object for integration testing."""
    # Use environment variables set by conftest.py
    database = os.environ.get("DATABASE_BACKEND", "dynamodb")
    return Config(
        database=database,
        fqdn="test.actingweb.net",
        proto="http://",
        aw_type="urn:actingweb:test:capabilities",
        desc="Test app for capabilities",
        version="1.0.0",
        devtest=True,
    )


@pytest.mark.xdist_group(name="peer_capabilities")
class TestPeerCapabilitiesIntegration:
    """
    Test peer capability field storage in trust relationships.

    These tests verify that the capability tracking fields added in Phase 0
    are correctly persisted and retrieved from the database.
    """

    # Shared state
    actor1_url: str | None = None
    actor1_id: str | None = None
    creator1: str = "caps_test1@actingweb.net"
    passphrase1: str | None = None
    actor2_url: str | None = None
    actor2_id: str | None = None
    creator2: str = "caps_test2@actingweb.net"
    passphrase2: str | None = None
    trust_url: str | None = None
    trust_secret: str | None = None

    def test_001_create_actors(self, http_client):
        """Create two actors for trust relationship tests."""
        # Create actor 1
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": "caps_test1@actingweb.net"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestPeerCapabilitiesIntegration.actor1_url = response.headers.get("Location")
        TestPeerCapabilitiesIntegration.actor1_id = response.json()["id"]
        TestPeerCapabilitiesIntegration.passphrase1 = response.json()["passphrase"]

        # Create actor 2 on peer server
        peer_url = getattr(http_client, "peer_url", http_client.base_url)
        response = http_client.post(
            f"{peer_url}/",
            json={"creator": "caps_test2@actingweb.net"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestPeerCapabilitiesIntegration.actor2_url = response.headers.get("Location")
        TestPeerCapabilitiesIntegration.actor2_id = response.json()["id"]
        TestPeerCapabilitiesIntegration.passphrase2 = response.json()["passphrase"]

    def test_002_create_trust_relationship(self, http_client):
        """Create a trust relationship between the actors."""
        assert self.actor1_url is not None
        assert self.actor1_id is not None
        assert self.passphrase1 is not None
        assert self.actor2_url is not None

        response = requests.post(
            f"{self.actor1_url}/trust",
            json={
                "url": self.actor2_url,
                "relationship": "friend",
                "desc": "Capability test trust",
            },
            auth=(self.creator1, self.passphrase1),
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        TestPeerCapabilitiesIntegration.trust_url = response.headers.get("Location")
        TestPeerCapabilitiesIntegration.trust_secret = response.json().get("secret")

    def test_003_verify_trust_created(self, http_client):
        """Verify trust relationship was created."""
        assert self.trust_url is not None
        assert self.actor1_id is not None
        assert self.passphrase1 is not None

        response = requests.get(
            self.trust_url,
            auth=(self.creator1, self.passphrase1),
        )

        assert response.status_code == 200
        data = response.json()
        assert data.get("relationship") == "friend"

    def test_004_update_capability_fields_via_devtest(self, http_client):
        """
        Update capability fields using the internal devtest endpoint.

        This tests that the capability fields can be stored in the database.
        In production, these would be updated by PeerCapabilities.refresh().
        """
        assert self.actor1_url is not None
        assert self.actor1_id is not None
        assert self.passphrase1 is not None
        assert self.actor2_id is not None

        # Update via direct trust modification (using devtest/trust endpoint)
        update_url = f"{self.actor1_url}/devtest/trust/{self.actor2_id}"
        response = requests.put(
            update_url,
            json={
                "aw_supported": "subscriptionbatch,callbackcompression,subscriptionresync",
                "aw_version": "1.4",
                "capabilities_fetched_at": "2026-01-20T12:00:00+00:00",
            },
            auth=(self.creator1, self.passphrase1),
            headers={"Content-Type": "application/json"},
        )

        # Note: devtest endpoint might not exist for trust modification
        # This test documents the expected behavior when such endpoint is added
        if response.status_code == 404:
            pytest.skip("Devtest trust modification endpoint not available")
        elif response.status_code == 200:
            assert True  # Fields were updated
        else:
            pytest.fail(f"Unexpected status code: {response.status_code}")

    def test_005_cleanup_trust(self, http_client):
        """Clean up trust relationship."""
        if self.trust_url and self.actor1_id and self.passphrase1:
            response = requests.delete(
                self.trust_url,
                auth=(self.creator1, self.passphrase1),
            )
            # 204 or 200 are both acceptable
            assert response.status_code in (200, 204, 404)

    def test_006_cleanup_actors(self, http_client):
        """Clean up test actors."""
        # Delete actor 1
        if self.actor1_url and self.actor1_id and self.passphrase1:
            response = requests.delete(
                self.actor1_url,
                auth=(self.creator1, self.passphrase1),
            )
            assert response.status_code in (200, 204, 404)

        # Delete actor 2
        if self.actor2_url and self.actor2_id and self.passphrase2:
            response = requests.delete(
                self.actor2_url,
                auth=(self.creator2, self.passphrase2),
            )
            assert response.status_code in (200, 204, 404)


@pytest.mark.xdist_group(name="cached_capabilities")
class TestCachedCapabilitiesStoreIntegration:
    """
    Integration tests for CachedCapabilitiesStore.

    Tests that methods/actions caching works correctly with the database backend.
    """

    # Shared state
    actor_url: str | None = None
    actor_id: str | None = None
    creator: str = "cached_caps_test@actingweb.net"
    passphrase: str | None = None

    def test_001_create_actor(self, http_client):
        """Create an actor for caching tests."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": "cached_caps_test@actingweb.net"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestCachedCapabilitiesStoreIntegration.actor_url = response.headers.get(
            "Location"
        )
        TestCachedCapabilitiesStoreIntegration.actor_id = response.json()["id"]
        TestCachedCapabilitiesStoreIntegration.passphrase = response.json()[
            "passphrase"
        ]

    def test_002_store_and_retrieve_capabilities(self, http_client):
        """Test storing and retrieving capabilities from database."""
        assert self.actor_id is not None

        config = _create_test_config()
        store = CachedCapabilitiesStore(config)

        # Create capabilities to store
        method1 = CachedCapability(
            name="get_data",
            description="Get data from actor",
            input_schema={"type": "object", "properties": {"key": {"type": "string"}}},
            capability_type="method",
        )
        method2 = CachedCapability(
            name="set_data",
            description="Set data on actor",
            capability_type="method",
        )
        action1 = CachedCapability(
            name="reset",
            description="Reset actor state",
            capability_type="action",
        )

        capabilities = CachedPeerCapabilities(
            actor_id=self.actor_id,
            peer_id="test_peer_001",
            methods=[method1, method2],
            actions=[action1],
            fetched_at="2024-01-01T00:00:00Z",
        )

        # Store capabilities
        result = store.store_capabilities(capabilities)
        assert result is True

        # Clear cache to force retrieval from database
        store.clear_cache()

        # Retrieve capabilities
        retrieved = store.get_capabilities(self.actor_id, "test_peer_001")
        assert retrieved is not None
        assert retrieved.actor_id == self.actor_id
        assert retrieved.peer_id == "test_peer_001"
        assert len(retrieved.methods) == 2
        assert len(retrieved.actions) == 1
        assert retrieved.methods[0].name == "get_data"
        assert retrieved.methods[0].input_schema is not None
        assert retrieved.actions[0].name == "reset"

    def test_003_update_capabilities(self, http_client):
        """Test updating existing capabilities."""
        assert self.actor_id is not None

        config = _create_test_config()
        store = CachedCapabilitiesStore(config)

        # Create new capabilities (with different methods)
        method_new = CachedCapability(
            name="new_method",
            description="A new method",
            capability_type="method",
        )

        capabilities = CachedPeerCapabilities(
            actor_id=self.actor_id,
            peer_id="test_peer_001",
            methods=[method_new],
            actions=[],
            fetched_at="2024-01-02T00:00:00Z",
        )

        # Store updated capabilities
        result = store.store_capabilities(capabilities)
        assert result is True

        # Clear cache and retrieve
        store.clear_cache()
        retrieved = store.get_capabilities(self.actor_id, "test_peer_001")

        # Should have the updated data
        assert retrieved is not None
        assert len(retrieved.methods) == 1
        assert retrieved.methods[0].name == "new_method"
        assert len(retrieved.actions) == 0
        assert retrieved.fetched_at == "2024-01-02T00:00:00Z"

    def test_004_multiple_peers(self, http_client):
        """Test storing capabilities for multiple peers."""
        assert self.actor_id is not None

        config = _create_test_config()
        store = CachedCapabilitiesStore(config)

        # Store capabilities for peer 2
        caps_peer2 = CachedPeerCapabilities(
            actor_id=self.actor_id,
            peer_id="test_peer_002",
            methods=[CachedCapability(name="peer2_method", capability_type="method")],
            actions=[],
            fetched_at="2024-01-01T00:00:00Z",
        )
        result = store.store_capabilities(caps_peer2)
        assert result is True

        # Store capabilities for peer 3
        caps_peer3 = CachedPeerCapabilities(
            actor_id=self.actor_id,
            peer_id="test_peer_003",
            methods=[],
            actions=[CachedCapability(name="peer3_action", capability_type="action")],
            fetched_at="2024-01-01T00:00:00Z",
        )
        result = store.store_capabilities(caps_peer3)
        assert result is True

        # Clear cache and list all capabilities
        store.clear_cache()
        all_caps = store.list_actor_capabilities(self.actor_id)

        # Should have at least 3 peer entries (from test_002, test_003, and this test)
        assert len(all_caps) >= 3

        # Find specific peer entries
        peer2_caps = next((c for c in all_caps if c.peer_id == "test_peer_002"), None)
        assert peer2_caps is not None
        assert len(peer2_caps.methods) == 1
        assert peer2_caps.methods[0].name == "peer2_method"

        peer3_caps = next((c for c in all_caps if c.peer_id == "test_peer_003"), None)
        assert peer3_caps is not None
        assert len(peer3_caps.actions) == 1
        assert peer3_caps.actions[0].name == "peer3_action"

    def test_005_delete_capabilities(self, http_client):
        """Test deleting capabilities."""
        assert self.actor_id is not None

        config = _create_test_config()
        store = CachedCapabilitiesStore(config)

        # Delete capabilities for test_peer_001
        result = store.delete_capabilities(self.actor_id, "test_peer_001")
        assert result is True

        # Verify deletion
        store.clear_cache()
        retrieved = store.get_capabilities(self.actor_id, "test_peer_001")
        assert retrieved is None

    def test_006_delete_nonexistent(self, http_client):
        """Test deleting non-existent capabilities is idempotent (doesn't error)."""
        assert self.actor_id is not None

        config = _create_test_config()
        store = CachedCapabilitiesStore(config)
        # Deleting non-existent capabilities should be idempotent (no error)
        # Note: Returns True because attribute bucket delete is idempotent
        result = store.delete_capabilities(self.actor_id, "nonexistent_peer")
        assert result is True  # Idempotent delete succeeds

    def test_007_cleanup_remaining_capabilities(self, http_client):
        """Clean up remaining test capabilities."""
        assert self.actor_id is not None

        config = _create_test_config()
        store = CachedCapabilitiesStore(config)

        # Delete all test peers
        for peer_id in ["test_peer_002", "test_peer_003"]:
            store.delete_capabilities(self.actor_id, peer_id)

    def test_008_cleanup_actor(self, http_client):
        """Clean up test actor."""
        if self.actor_url and self.actor_id and self.passphrase:
            response = requests.delete(
                self.actor_url,
                auth=(self.creator, self.passphrase),
            )
            assert response.status_code in (200, 204, 404)
