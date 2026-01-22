"""
Integration tests for peer profile caching.

Tests PeerProfileStore operations with DynamoDB/PostgreSQL and
the integration with trust lifecycle hooks.
"""

import os

import pytest
import requests


@pytest.fixture
def test_config(docker_services, setup_database, worker_info):  # noqa: ARG001
    """
    Provide a Config object for tests that need direct access.

    This fixture creates a Config object matching the test environment,
    including proper schema isolation for PostgreSQL parallel tests.
    """
    from actingweb.config import Config

    # Create config based on DATABASE_BACKEND
    database_backend = os.environ.get("DATABASE_BACKEND", "dynamodb")

    # Set up environment for PostgreSQL schema isolation
    if database_backend == "postgresql":
        os.environ["PG_DB_HOST"] = os.environ.get("PG_DB_HOST", "localhost")
        os.environ["PG_DB_PORT"] = os.environ.get("PG_DB_PORT", "5433")
        os.environ["PG_DB_NAME"] = os.environ.get("PG_DB_NAME", "actingweb_test")
        os.environ["PG_DB_USER"] = os.environ.get("PG_DB_USER", "actingweb")
        os.environ["PG_DB_PASSWORD"] = os.environ.get("PG_DB_PASSWORD", "testpassword")
        os.environ["PG_DB_PREFIX"] = worker_info["db_prefix"]
        os.environ["PG_DB_SCHEMA"] = "public"

    config = Config(database=database_backend)

    return config


@pytest.mark.xdist_group(name="peer_profile_flow")
class TestPeerProfileStore:
    """
    Test PeerProfileStore storage operations.

    These tests verify that peer profiles can be stored and retrieved
    from the database.
    """

    actor_url: str | None = None
    actor_id: str | None = None
    passphrase: str | None = None
    creator: str = "profile_test@example.com"

    def test_001_create_actor(self, http_client):
        """Create an actor for peer profile tests."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        TestPeerProfileStore.actor_url = response.headers.get("Location")
        TestPeerProfileStore.actor_id = response.json()["id"]
        TestPeerProfileStore.passphrase = response.json()["passphrase"]

    def test_002_store_and_retrieve_profile(self, test_config):
        """Test storing and retrieving a peer profile."""
        from actingweb.peer_profile import (
            PeerProfile,
            get_peer_profile_store,
        )

        assert self.actor_id is not None
        actor_id = self.actor_id

        # Create a test profile
        profile = PeerProfile(
            actor_id=actor_id,
            peer_id="test_peer_001",
            displayname="Test Peer",
            email="peer@example.com",
            description="A test peer for integration testing",
            extra_attributes={"custom_field": "custom_value"},
            fetched_at="2025-01-22T10:00:00",
        )

        # Store the profile
        store = get_peer_profile_store(test_config)
        result = store.store_profile(profile)
        assert result is True

        # Retrieve the profile
        retrieved = store.get_profile(actor_id, "test_peer_001")
        assert retrieved is not None
        assert retrieved.actor_id == actor_id
        assert retrieved.peer_id == "test_peer_001"
        assert retrieved.displayname == "Test Peer"
        assert retrieved.email == "peer@example.com"
        assert retrieved.description == "A test peer for integration testing"
        assert retrieved.extra_attributes["custom_field"] == "custom_value"
        assert retrieved.fetched_at == "2025-01-22T10:00:00"

    def test_003_update_existing_profile(self, test_config):
        """Test updating an existing peer profile."""
        from actingweb.peer_profile import (
            PeerProfile,
            get_peer_profile_store,
        )

        assert self.actor_id is not None
        actor_id = self.actor_id

        # Create updated profile with same keys
        updated_profile = PeerProfile(
            actor_id=actor_id,
            peer_id="test_peer_001",
            displayname="Updated Peer Name",
            email="updated@example.com",
            description="Updated description",
            fetched_at="2025-01-22T12:00:00",
        )

        # Store the updated profile
        store = get_peer_profile_store(test_config)
        result = store.store_profile(updated_profile)
        assert result is True

        # Verify update
        retrieved = store.get_profile(actor_id, "test_peer_001")
        assert retrieved is not None
        assert retrieved.displayname == "Updated Peer Name"
        assert retrieved.email == "updated@example.com"
        assert retrieved.description == "Updated description"
        assert retrieved.fetched_at == "2025-01-22T12:00:00"

    def test_004_list_actor_profiles(self, test_config):
        """Test listing all profiles for an actor."""
        from actingweb.peer_profile import (
            PeerProfile,
            get_peer_profile_store,
        )

        assert self.actor_id is not None
        actor_id = self.actor_id

        store = get_peer_profile_store(test_config)

        # Store additional profiles
        for i in range(2, 4):
            profile = PeerProfile(
                actor_id=actor_id,
                peer_id=f"test_peer_00{i}",
                displayname=f"Test Peer {i}",
            )
            store.store_profile(profile)

        # List all profiles
        profiles = store.list_actor_profiles(actor_id)
        assert len(profiles) >= 3  # At least the 3 we created

        peer_ids = [p.peer_id for p in profiles]
        assert "test_peer_001" in peer_ids
        assert "test_peer_002" in peer_ids
        assert "test_peer_003" in peer_ids

    def test_005_delete_profile(self, test_config):
        """Test deleting a peer profile."""
        from actingweb.peer_profile import get_peer_profile_store

        assert self.actor_id is not None
        actor_id = self.actor_id

        store = get_peer_profile_store(test_config)

        # Verify profile exists
        profile = store.get_profile(actor_id, "test_peer_002")
        assert profile is not None

        # Delete the profile
        result = store.delete_profile(actor_id, "test_peer_002")
        assert result is True

        # Verify deletion
        profile = store.get_profile(actor_id, "test_peer_002")
        assert profile is None

    def test_006_get_nonexistent_profile_returns_none(self, test_config):
        """Test that getting a nonexistent profile returns None."""
        from actingweb.peer_profile import get_peer_profile_store

        assert self.actor_id is not None
        actor_id = self.actor_id

        store = get_peer_profile_store(test_config)
        profile = store.get_profile(actor_id, "nonexistent_peer")
        assert profile is None

    def test_007_store_profile_with_fetch_error(self, test_config):
        """Test storing a profile with a fetch error."""
        from actingweb.peer_profile import (
            PeerProfile,
            get_peer_profile_store,
        )

        assert self.actor_id is not None
        actor_id = self.actor_id

        profile = PeerProfile(
            actor_id=actor_id,
            peer_id="error_peer",
            fetch_error="Connection refused",
            fetched_at="2025-01-22T10:00:00",
        )

        store = get_peer_profile_store(test_config)
        result = store.store_profile(profile)
        assert result is True

        # Verify fetch_error is preserved
        retrieved = store.get_profile(actor_id, "error_peer")
        assert retrieved is not None
        assert retrieved.fetch_error == "Connection refused"
        assert retrieved.displayname is None

    def test_008_cleanup_profiles(self, test_config):
        """Clean up test profiles."""
        from actingweb.peer_profile import get_peer_profile_store

        assert self.actor_id is not None
        actor_id = self.actor_id

        store = get_peer_profile_store(test_config)

        # Clean up all test profiles
        for peer_id in ["test_peer_001", "test_peer_003", "error_peer"]:
            store.delete_profile(actor_id, peer_id)

    def test_099_cleanup_actor(self, http_client):
        """Clean up the test actor."""
        if self.actor_url and self.passphrase:
            requests.delete(
                self.actor_url,
                auth=(self.creator, self.passphrase),
            )


@pytest.mark.xdist_group(name="peer_profile_trust_flow")
class TestPeerProfileTrustIntegration:
    """
    Test peer profile integration with trust relationships.

    These tests verify that peer profiles can be manually managed
    via the TrustManager interface.
    """

    actor1_url: str | None = None
    actor1_id: str | None = None
    actor1_passphrase: str | None = None
    actor1_creator: str = "profile_trust1@example.com"

    actor2_url: str | None = None
    actor2_id: str | None = None
    actor2_passphrase: str | None = None
    actor2_creator: str = "profile_trust2@example.com"

    def test_001_create_actor1(self, http_client):
        """Create the first test actor."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.actor1_creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        TestPeerProfileTrustIntegration.actor1_url = response.headers.get("Location")
        TestPeerProfileTrustIntegration.actor1_id = response.json()["id"]
        TestPeerProfileTrustIntegration.actor1_passphrase = response.json()["passphrase"]

    def test_002_create_actor2(self, http_client):
        """Create the second test actor."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.actor2_creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        TestPeerProfileTrustIntegration.actor2_url = response.headers.get("Location")
        TestPeerProfileTrustIntegration.actor2_id = response.json()["id"]
        TestPeerProfileTrustIntegration.actor2_passphrase = response.json()["passphrase"]

    def test_003_set_actor2_properties(self, http_client):
        """Set properties on actor2 that can be cached in peer profile."""
        assert self.actor2_url is not None
        assert self.actor2_passphrase is not None

        response = requests.post(
            f"{self.actor2_url}/properties",
            json={
                "displayname": "Actor Two",
                "email": "actor2@example.com",
                "description": "The second test actor",
            },
            auth=(self.actor2_creator, self.actor2_passphrase),
        )
        assert response.status_code == 201

    def test_004_trust_manager_get_peer_profile_without_caching(self, test_config):
        """Test that get_peer_profile returns None when caching is disabled."""
        from actingweb.actor import Actor
        from actingweb.interface.actor_interface import ActorInterface

        assert self.actor1_id is not None
        assert self.actor2_id is not None

        # Create ActorInterface for actor1 (caching not enabled in config)
        core_actor = Actor(actor_id=self.actor1_id, config=test_config)
        actor_interface = ActorInterface(core_actor)

        # get_peer_profile should return None since caching is disabled
        profile = actor_interface.trust.get_peer_profile(self.actor2_id)
        assert profile is None

    def test_005_test_refresh_peer_profile_without_caching(self, test_config):
        """Test that refresh_peer_profile returns None when caching is disabled."""
        from actingweb.actor import Actor
        from actingweb.interface.actor_interface import ActorInterface

        assert self.actor1_id is not None
        assert self.actor2_id is not None

        core_actor = Actor(actor_id=self.actor1_id, config=test_config)
        actor_interface = ActorInterface(core_actor)

        # refresh_peer_profile should return None since caching is disabled
        profile = actor_interface.trust.refresh_peer_profile(self.actor2_id)
        assert profile is None

    def test_006_manual_profile_storage_with_enabled_config(self, test_config):
        """Test manual profile storage works when caching is enabled via config."""
        from actingweb.peer_profile import (
            PeerProfile,
            get_peer_profile_store,
        )

        # Ensure actor IDs are set (from previous tests)
        assert self.actor1_id is not None
        assert self.actor2_id is not None
        actor1_id: str = self.actor1_id
        actor2_id: str = self.actor2_id

        # Manually enable peer profile caching on config
        test_config.peer_profile_attributes = ["displayname", "email", "description"]

        try:
            # Store a profile manually
            profile = PeerProfile(
                actor_id=actor1_id,
                peer_id=actor2_id,
                displayname="Actor Two",
                email="actor2@example.com",
                description="Manually stored profile",
            )

            store = get_peer_profile_store(test_config)
            result = store.store_profile(profile)
            assert result is True

            # Now get_peer_profile via TrustManager should work
            from actingweb.actor import Actor
            from actingweb.interface.actor_interface import ActorInterface

            core_actor = Actor(actor_id=actor1_id, config=test_config)
            actor_interface = ActorInterface(core_actor)

            retrieved = actor_interface.trust.get_peer_profile(actor2_id)
            assert retrieved is not None
            assert retrieved.displayname == "Actor Two"
            assert retrieved.email == "actor2@example.com"

            # Cleanup
            store.delete_profile(actor1_id, actor2_id)

        finally:
            # Reset config
            test_config.peer_profile_attributes = None

    def test_099_cleanup_actors(self, http_client):
        """Clean up test actors."""
        if self.actor1_url and self.actor1_passphrase:
            requests.delete(
                self.actor1_url,
                auth=(self.actor1_creator, self.actor1_passphrase),
            )
        if self.actor2_url and self.actor2_passphrase:
            requests.delete(
                self.actor2_url,
                auth=(self.actor2_creator, self.actor2_passphrase),
            )


class TestPeerProfileCacheOperations:
    """Test PeerProfileStore cache operations."""

    def test_cache_hit_avoids_database_read(self, test_config):
        """Test that cached profiles are returned without database read."""
        from actingweb.peer_profile import (
            PeerProfile,
            get_peer_profile_store,
        )

        actor_id = "cache_test_actor"
        peer_id = "cache_test_peer"

        store = get_peer_profile_store(test_config)

        # Store a profile (also caches it)
        profile = PeerProfile(
            actor_id=actor_id,
            peer_id=peer_id,
            displayname="Cached Profile",
        )
        store.store_profile(profile)

        # First retrieval populates cache
        retrieved1 = store.get_profile(actor_id, peer_id)
        assert retrieved1 is not None

        # Second retrieval should hit cache
        # (We can't easily verify this without mocking, but we can verify it works)
        retrieved2 = store.get_profile(actor_id, peer_id)
        assert retrieved2 is not None
        assert retrieved2.displayname == "Cached Profile"

        # Clear cache and verify still works (reads from DB)
        store.clear_cache()
        retrieved3 = store.get_profile(actor_id, peer_id)
        assert retrieved3 is not None
        assert retrieved3.displayname == "Cached Profile"

        # Cleanup
        store.delete_profile(actor_id, peer_id)

    def test_delete_clears_cache(self, test_config):
        """Test that deleting a profile clears it from cache."""
        from actingweb.peer_profile import (
            PeerProfile,
            get_peer_profile_store,
        )

        actor_id = "delete_cache_actor"
        peer_id = "delete_cache_peer"

        store = get_peer_profile_store(test_config)

        # Store a profile
        profile = PeerProfile(
            actor_id=actor_id,
            peer_id=peer_id,
            displayname="To Be Deleted",
        )
        store.store_profile(profile)

        # Verify it's in cache
        retrieved = store.get_profile(actor_id, peer_id)
        assert retrieved is not None

        # Delete should clear from cache
        store.delete_profile(actor_id, peer_id)

        # Verify it's gone
        retrieved = store.get_profile(actor_id, peer_id)
        assert retrieved is None
