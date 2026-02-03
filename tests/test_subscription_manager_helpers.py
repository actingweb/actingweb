"""Unit tests for SubscriptionManager helper methods.

Tests the private helper methods:
- _is_capability_cache_stale()
- _extract_profile_from_remote_store()
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.interface.subscription_manager import SubscriptionManager


class FakeConfig:
    """Minimal Config mock for testing."""

    def __init__(self) -> None:
        self.root = "https://example.com/"
        self.peer_capabilities_max_age_seconds = 3600  # 1 hour default


class FakeCoreActor:
    """Minimal core Actor mock for testing."""

    def __init__(self) -> None:
        self.id = "actor_1"
        self.config = FakeConfig()


# Patch paths - RemotePeerStore is imported inside the method from ..remote_storage
REMOTE_PEER_STORE_PATCH = "actingweb.remote_storage.RemotePeerStore"


class TestCapabilityCacheStaleness:
    """Test _is_capability_cache_stale() method."""

    def test_no_cache_entry_returns_stale(self):
        """Missing cache entry should trigger fetch."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock store that returns None (no cached capabilities)
        mock_store = MagicMock()
        mock_store.get_capabilities = MagicMock(return_value=None)

        result = manager._is_capability_cache_stale(
            store=mock_store,
            actor_id="actor_1",
            peer_id="peer_1",
            actor_config=actor.config,
        )

        assert result is True  # Should fetch

    def test_cache_without_fetched_at_returns_stale(self):
        """Cache entry without fetched_at timestamp should trigger fetch."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock cached capabilities without fetched_at
        mock_cached = MagicMock()
        mock_cached.fetched_at = None

        mock_store = MagicMock()
        mock_store.get_capabilities = MagicMock(return_value=mock_cached)

        result = manager._is_capability_cache_stale(
            store=mock_store,
            actor_id="actor_1",
            peer_id="peer_1",
            actor_config=actor.config,
        )

        assert result is True  # Should fetch

    def test_fresh_cache_returns_not_stale(self):
        """Recent cache entry should not trigger fetch."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock cached capabilities fetched 5 minutes ago
        five_minutes_ago = datetime.now(UTC) - timedelta(minutes=5)
        mock_cached = MagicMock()
        mock_cached.fetched_at = five_minutes_ago.isoformat()

        mock_store = MagicMock()
        mock_store.get_capabilities = MagicMock(return_value=mock_cached)

        # Config with 1 hour max age
        actor.config.peer_capabilities_max_age_seconds = 3600

        result = manager._is_capability_cache_stale(
            store=mock_store,
            actor_id="actor_1",
            peer_id="peer_1",
            actor_config=actor.config,
        )

        assert result is False  # Should NOT fetch (cache is fresh)

    def test_stale_cache_returns_stale(self):
        """Old cache entry should trigger fetch."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock cached capabilities fetched 2 hours ago
        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        mock_cached = MagicMock()
        mock_cached.fetched_at = two_hours_ago.isoformat()

        mock_store = MagicMock()
        mock_store.get_capabilities = MagicMock(return_value=mock_cached)

        # Config with 1 hour max age
        actor.config.peer_capabilities_max_age_seconds = 3600

        result = manager._is_capability_cache_stale(
            store=mock_store,
            actor_id="actor_1",
            peer_id="peer_1",
            actor_config=actor.config,
        )

        assert result is True  # Should fetch (cache is stale)

    def test_zero_max_age_always_returns_stale(self):
        """Zero max age means staleness check disabled - always fetch."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock recent cache
        one_minute_ago = datetime.now(UTC) - timedelta(minutes=1)
        mock_cached = MagicMock()
        mock_cached.fetched_at = one_minute_ago.isoformat()

        mock_store = MagicMock()
        mock_store.get_capabilities = MagicMock(return_value=mock_cached)

        # Config with 0 max age (disabled)
        actor.config.peer_capabilities_max_age_seconds = 0

        result = manager._is_capability_cache_stale(
            store=mock_store,
            actor_id="actor_1",
            peer_id="peer_1",
            actor_config=actor.config,
        )

        assert result is True  # Should always fetch

    def test_negative_max_age_always_returns_stale(self):
        """Negative max age means staleness check disabled - always fetch."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock recent cache
        one_minute_ago = datetime.now(UTC) - timedelta(minutes=1)
        mock_cached = MagicMock()
        mock_cached.fetched_at = one_minute_ago.isoformat()

        mock_store = MagicMock()
        mock_store.get_capabilities = MagicMock(return_value=mock_cached)

        # Config with negative max age
        actor.config.peer_capabilities_max_age_seconds = -1

        result = manager._is_capability_cache_stale(
            store=mock_store,
            actor_id="actor_1",
            peer_id="peer_1",
            actor_config=actor.config,
        )

        assert result is True  # Should always fetch

    def test_exception_returns_stale(self):
        """Exception during staleness check should return stale (fetch to be safe)."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock store that raises exception
        mock_store = MagicMock()
        mock_store.get_capabilities = MagicMock(side_effect=Exception("Database error"))

        result = manager._is_capability_cache_stale(
            store=mock_store,
            actor_id="actor_1",
            peer_id="peer_1",
            actor_config=actor.config,
        )

        assert result is True  # Should fetch on error

    def test_missing_config_attribute_uses_default(self):
        """Missing peer_capabilities_max_age_seconds should use default."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock cached capabilities fetched 30 minutes ago
        thirty_minutes_ago = datetime.now(UTC) - timedelta(minutes=30)
        mock_cached = MagicMock()
        mock_cached.fetched_at = thirty_minutes_ago.isoformat()

        mock_store = MagicMock()
        mock_store.get_capabilities = MagicMock(return_value=mock_cached)

        # Config without max_age attribute
        mock_config = MagicMock()
        del mock_config.peer_capabilities_max_age_seconds  # Remove attribute

        result = manager._is_capability_cache_stale(
            store=mock_store,
            actor_id="actor_1",
            peer_id="peer_1",
            actor_config=mock_config,
        )

        # Default is 3600 seconds, 30 minutes is fresh
        assert result is False


class TestProfileExtraction:
    """Test _extract_profile_from_remote_store() method."""

    def test_extract_displayname_email_description(self):
        """Test extracting standard profile attributes."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Config with standard profile attributes
        actor.config.peer_profile_attributes = ["displayname", "email", "description"]  # type: ignore[attr-defined]

        # Mock RemotePeerStore.get_value to return property values
        with patch(REMOTE_PEER_STORE_PATCH) as MockStore:
            mock_store_instance = MagicMock()
            MockStore.return_value = mock_store_instance

            def mock_get_value(attr: str) -> dict[str, Any] | None:
                values = {
                    "displayname": {"value": "John Doe"},
                    "email": {"value": "john@example.com"},
                    "description": {"value": "Test user"},
                }
                return values.get(attr)

            mock_store_instance.get_value = mock_get_value

            profile, extracted = manager._extract_profile_from_remote_store(
                peer_id="peer_1",
                actor_id="actor_1",
                actor_config=actor.config,
            )

            assert extracted is True
            assert profile.displayname == "John Doe"
            assert profile.email == "john@example.com"
            assert profile.description == "Test user"

    def test_extract_extra_attributes(self):
        """Test that non-standard attributes go to extra_attributes."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Config with custom attribute
        actor.config.peer_profile_attributes = ["displayname", "custom_field", "role"]  # type: ignore[attr-defined]

        with patch(REMOTE_PEER_STORE_PATCH) as MockStore:
            mock_store_instance = MagicMock()
            MockStore.return_value = mock_store_instance

            def mock_get_value(attr: str) -> dict[str, Any] | None:
                values = {
                    "displayname": {"value": "Jane"},
                    "custom_field": {"value": "custom_value"},
                    "role": {"value": "admin"},
                }
                return values.get(attr)

            mock_store_instance.get_value = mock_get_value

            profile, extracted = manager._extract_profile_from_remote_store(
                peer_id="peer_1",
                actor_id="actor_1",
                actor_config=actor.config,
            )

            assert extracted is True
            assert profile.displayname == "Jane"
            assert profile.extra_attributes["custom_field"] == "custom_value"
            assert profile.extra_attributes["role"] == "admin"

    def test_extract_missing_attributes_not_extracted(self):
        """Test that missing attributes don't prevent extraction."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        actor.config.peer_profile_attributes = ["displayname", "email"]  # type: ignore[attr-defined]

        with patch(REMOTE_PEER_STORE_PATCH) as MockStore:
            mock_store_instance = MagicMock()
            MockStore.return_value = mock_store_instance

            # Only displayname exists, email is missing
            def mock_get_value(attr: str) -> dict[str, Any] | None:
                if attr == "displayname":
                    return {"value": "Bob"}
                return None

            mock_store_instance.get_value = mock_get_value

            profile, extracted = manager._extract_profile_from_remote_store(
                peer_id="peer_1",
                actor_id="actor_1",
                actor_config=actor.config,
            )

            assert extracted is True  # At least one attribute extracted
            assert profile.displayname == "Bob"
            assert profile.email is None

    def test_extraction_all_missing_returns_false(self):
        """Test extraction returns False if all attributes are missing."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        actor.config.peer_profile_attributes = ["displayname", "email"]  # type: ignore[attr-defined]

        with patch(REMOTE_PEER_STORE_PATCH) as MockStore:
            mock_store_instance = MagicMock()
            MockStore.return_value = mock_store_instance

            # All attributes missing
            mock_store_instance.get_value = MagicMock(return_value=None)

            profile, extracted = manager._extract_profile_from_remote_store(
                peer_id="peer_1",
                actor_id="actor_1",
                actor_config=actor.config,
            )

            assert extracted is False
            assert profile.displayname is None
            assert profile.email is None

    def test_extraction_exception_returns_false(self):
        """Test exception during extraction returns (profile, False)."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        actor.config.peer_profile_attributes = ["displayname"]  # type: ignore[attr-defined]

        with patch(REMOTE_PEER_STORE_PATCH) as MockStore:
            mock_store_instance = MagicMock()
            MockStore.return_value = mock_store_instance

            # Simulate exception during get_value
            mock_store_instance.get_value = MagicMock(
                side_effect=Exception("Storage error")
            )

            _, extracted = manager._extract_profile_from_remote_store(
                peer_id="peer_1",
                actor_id="actor_1",
                actor_config=actor.config,
            )

            assert extracted is False

    def test_extract_raw_value_not_wrapped(self):
        """Test extracting value that's not wrapped in {value: ...}."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        actor.config.peer_profile_attributes = ["displayname"]  # type: ignore[attr-defined]

        with patch(REMOTE_PEER_STORE_PATCH) as MockStore:
            mock_store_instance = MagicMock()
            MockStore.return_value = mock_store_instance

            # Return raw value without wrapper
            mock_store_instance.get_value = MagicMock(return_value="RawName")

            profile, extracted = manager._extract_profile_from_remote_store(
                peer_id="peer_1",
                actor_id="actor_1",
                actor_config=actor.config,
            )

            assert extracted is True
            assert profile.displayname == "RawName"

    def test_extract_preserves_complex_types_in_extra(self):
        """Test that complex types in extra_attributes are preserved."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        actor.config.peer_profile_attributes = ["tags", "settings"]  # type: ignore[attr-defined]

        with patch(REMOTE_PEER_STORE_PATCH) as MockStore:
            mock_store_instance = MagicMock()
            MockStore.return_value = mock_store_instance

            def mock_get_value(attr: str) -> dict[str, Any] | None:
                values = {
                    "tags": {"value": ["python", "asyncio"]},
                    "settings": {"value": {"theme": "dark", "notifications": True}},
                }
                return values.get(attr)

            mock_store_instance.get_value = mock_get_value

            profile, extracted = manager._extract_profile_from_remote_store(
                peer_id="peer_1",
                actor_id="actor_1",
                actor_config=actor.config,
            )

            assert extracted is True
            # Complex types should be preserved
            assert profile.extra_attributes["tags"] == ["python", "asyncio"]
            assert profile.extra_attributes["settings"] == {
                "theme": "dark",
                "notifications": True,
            }

    def test_extract_none_value_converts_to_none(self):
        """Test that explicit None values are handled correctly."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        actor.config.peer_profile_attributes = ["displayname"]  # type: ignore[attr-defined]

        with patch(REMOTE_PEER_STORE_PATCH) as MockStore:
            mock_store_instance = MagicMock()
            MockStore.return_value = mock_store_instance

            # Return wrapped None value
            mock_store_instance.get_value = MagicMock(return_value={"value": None})

            profile, extracted = manager._extract_profile_from_remote_store(
                peer_id="peer_1",
                actor_id="actor_1",
                actor_config=actor.config,
            )

            # A wrapped value (even if None) counts as found
            assert extracted is True
            assert profile.displayname is None


class TestSyncPeerTrustVerification:
    """Test sync_peer trust verification logic for the all-404 case."""

    def test_sync_peer_all_404_with_valid_trust(self):
        """Test that sync_peer cleans dead subs but preserves trust when trust exists."""
        from unittest.mock import MagicMock

        from actingweb.interface.subscription_manager import (
            SubscriptionManager,
            SubscriptionSyncResult,
        )

        actor = FakeCoreActor()
        actor.config.peer_profile_attributes = None  # type: ignore[attr-defined]
        actor.config.peer_capabilities_caching = False  # type: ignore[attr-defined]

        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock subscriptions
        mock_sub = MagicMock()
        mock_sub.is_outbound = True
        mock_sub.is_callback = True
        mock_sub.subscription_id = "sub_1"

        manager.get_subscriptions_to_peer = MagicMock(return_value=[mock_sub])  # type: ignore[method-assign]
        manager.get_callback_subscription = MagicMock(return_value=mock_sub)  # type: ignore[method-assign]

        # Mock sync_subscription to return 404
        mock_sync_result = SubscriptionSyncResult(
            subscription_id="sub_1",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )
        manager.sync_subscription = MagicMock(return_value=mock_sync_result)  # type: ignore[method-assign]

        # Mock proxy that shows trust still exists
        mock_proxy = MagicMock()
        mock_proxy.get_resource = MagicMock(
            return_value={"relationship": "friend", "verified": True}
        )
        manager._get_peer_proxy = MagicMock(return_value=mock_proxy)  # type: ignore[method-assign]

        # Mock subscription deletion
        mock_sub_obj = MagicMock()
        actor.get_subscription_obj = MagicMock(return_value=mock_sub_obj)  # type: ignore[attr-defined]

        result = manager.sync_peer("peer_1")

        # Trust should NOT be deleted
        assert result.success is False
        # Trust deletion should not have been called (trust still exists)
        # Instead, dead subscriptions should be cleaned up
        mock_sub_obj.delete.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
