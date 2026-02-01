"""
Unit tests for subscription baseline fetch methods.

Tests the baseline fetch refactoring:
- _fetch_and_transform_baseline() / _fetch_and_transform_baseline_async()
- subscribe_to_peer() baseline fetch with auto_storage config
- sync_subscription() baseline fetch with auto_storage config
- Resync callback handling
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.interface.subscription_manager import SubscriptionManager
from actingweb.subscription_config import SubscriptionProcessingConfig


class FakeConfig:
    """Minimal Config mock for testing."""

    def __init__(self) -> None:
        self.root = "https://example.com/"
        self.peer_profile_attributes: list[str] | None = None
        self.peer_capabilities_caching: bool = False
        self.peer_permissions_caching: bool = False
        self._subscription_config: SubscriptionProcessingConfig | None = None


class FakeCoreActor:
    """Minimal core Actor mock for testing."""

    def __init__(self) -> None:
        self.id = "actor_1"
        self.config = FakeConfig()
        self._subscriptions: dict[tuple[str, str, bool], dict[str, Any]] = {}

    def get_subscription(
        self, peerid: str, subid: str, callback: bool = False
    ) -> dict[str, Any] | None:
        """Mock get_subscription - returns dict."""
        key = (peerid, subid, callback)
        return self._subscriptions.get(key)

    def create_remote_subscription(
        self,
        peerid: str,
        target: str,
        subtarget: str | None = None,
        resource: str | None = None,
        granularity: str = "high",
    ) -> str | None:
        """Mock create_remote_subscription."""
        return f"https://peer.example.com/{peerid}/subscriptions/actor_1/sub_new"


class TestFetchAndTransformBaseline:
    """Tests for _fetch_and_transform_baseline() method."""

    def test_fetch_and_transform_basic(self):
        """Test basic baseline fetch without property lists."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock proxy
        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        mock_proxy.get_resource.return_value = {
            "scalar_prop": {"value": "test"},
            "number_prop": {"value": 42},
        }

        with patch.object(manager, "_get_peer_proxy", return_value=mock_proxy):
            result = manager._fetch_and_transform_baseline(
                peer_id="peer_1", target="properties"
            )

        assert result is not None
        assert result["scalar_prop"] == {"value": "test"}
        assert result["number_prop"] == {"value": 42}
        # Verify it added ?metadata=true for properties
        mock_proxy.get_resource.assert_called_once_with(path="properties?metadata=true")

    def test_fetch_and_transform_with_subtarget(self):
        """Test baseline fetch with subtarget (no metadata param)."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        mock_proxy.get_resource.return_value = [
            {"id": "1", "location": "Paris"},
            {"id": "2", "location": "Tokyo"},
        ]

        with patch.object(manager, "_get_peer_proxy", return_value=mock_proxy):
            result = manager._fetch_and_transform_baseline(
                peer_id="peer_1", target="properties", subtarget="memory_travel"
            )

        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 2
        # Verify no ?metadata=true when subtarget specified
        mock_proxy.get_resource.assert_called_once_with(path="properties/memory_travel")

    def test_fetch_and_transform_with_property_lists(self):
        """Test baseline fetch transforms property list metadata."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock proxy for baseline fetch
        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}

        # First call: baseline fetch returns metadata
        # Subsequent calls: fetch individual lists
        def mock_get_resource(path: str):
            if path == "properties?metadata=true":
                return {
                    "scalar_prop": {"value": "test"},
                    "list_prop": {"_list": True, "count": 3},
                }
            elif path == "properties/list_prop":
                return [
                    {"id": "1"},
                    {"id": "2"},
                    {"id": "3"},
                ]
            return None

        mock_proxy.get_resource.side_effect = mock_get_resource

        with patch.object(manager, "_get_peer_proxy", return_value=mock_proxy):
            result = manager._fetch_and_transform_baseline(
                peer_id="peer_1", target="properties"
            )

        assert result is not None
        # Scalar unchanged
        assert result["scalar_prop"] == {"value": "test"}
        # List transformed
        assert result["list_prop"]["_list"] is True
        assert "items" in result["list_prop"]
        assert len(result["list_prop"]["items"]) == 3

    def test_fetch_and_transform_no_proxy(self):
        """Test baseline fetch when no proxy available."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        with patch.object(manager, "_get_peer_proxy", return_value=None):
            result = manager._fetch_and_transform_baseline(
                peer_id="peer_1", target="properties"
            )

        assert result is None

    def test_fetch_and_transform_error_response(self):
        """Test baseline fetch handles error responses."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        mock_proxy.get_resource.return_value = {"error": "Permission denied"}

        with patch.object(manager, "_get_peer_proxy", return_value=mock_proxy):
            result = manager._fetch_and_transform_baseline(
                peer_id="peer_1", target="properties"
            )

        assert result is None

    def test_fetch_and_transform_exception(self):
        """Test baseline fetch handles exceptions."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        mock_proxy.get_resource.side_effect = Exception("Network timeout")

        with patch.object(manager, "_get_peer_proxy", return_value=mock_proxy):
            result = manager._fetch_and_transform_baseline(
                peer_id="peer_1", target="properties"
            )

        assert result is None


class TestFetchAndTransformBaselineAsync:
    """Tests for _fetch_and_transform_baseline_async() method."""

    @pytest.mark.asyncio
    async def test_fetch_and_transform_async_basic(self):
        """Test async baseline fetch without property lists."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}

        # Make get_resource_async return a coroutine
        async def mock_get_resource_async(path: str):
            return {"scalar_prop": {"value": "test"}}

        mock_proxy.get_resource_async = mock_get_resource_async

        with patch.object(manager, "_get_peer_proxy", return_value=mock_proxy):
            result = await manager._fetch_and_transform_baseline_async(
                peer_id="peer_1", target="properties"
            )

        assert result is not None
        assert result["scalar_prop"] == {"value": "test"}


class TestSubscribeToPeerBaselineFetch:
    """Tests for subscribe_to_peer() baseline fetch behavior."""

    def test_subscribe_to_peer_with_auto_storage_true(self):
        """Test subscribe_to_peer stores baseline when auto_storage=True."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        mock_proxy.get_resource.return_value = {"prop": {"value": "test"}}

        # Mock RemotePeerStore
        with (
            patch.object(manager, "_get_peer_proxy", return_value=mock_proxy),
            patch("actingweb.remote_storage.RemotePeerStore") as mock_store_class,
            patch("actingweb.interface.actor_interface.ActorInterface"),
            patch.object(manager, "_refresh_peer_metadata"),
        ):
            mock_store = MagicMock()
            mock_store_class.return_value = mock_store

            # Default config has auto_storage=True
            result = manager.subscribe_to_peer(
                peer_id="peer_1", target="properties", granularity="high"
            )

            assert result is not None
            # Verify baseline was stored
            mock_store.apply_resync_data.assert_called_once()
            stored_data = mock_store.apply_resync_data.call_args[0][0]
            assert stored_data["prop"] == {"value": "test"}

    def test_subscribe_to_peer_with_auto_storage_false(self):
        """Test subscribe_to_peer skips storage when auto_storage=False."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        mock_proxy.get_resource.return_value = {"prop": {"value": "test"}}

        # Mock config to return auto_storage=False
        with (
            patch.object(manager, "_get_peer_proxy", return_value=mock_proxy),
            patch(
                "actingweb.subscription_config.SubscriptionProcessingConfig"
            ) as mock_config_class,
            patch("actingweb.remote_storage.RemotePeerStore") as mock_store_class,
            patch("actingweb.interface.actor_interface.ActorInterface"),
            patch.object(manager, "_refresh_peer_metadata"),
        ):
            mock_config = MagicMock()
            mock_config.auto_storage = False
            mock_config_class.return_value = mock_config

            mock_store = MagicMock()
            mock_store_class.return_value = mock_store

            result = manager.subscribe_to_peer(
                peer_id="peer_1", target="properties", granularity="high"
            )

            assert result is not None
            # Verify baseline was NOT stored
            mock_store.apply_resync_data.assert_not_called()

    def test_subscribe_to_peer_refreshes_metadata(self):
        """Test subscribe_to_peer refreshes peer metadata even with auto_storage=False."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        mock_proxy.get_resource.return_value = {"prop": {"value": "test"}}

        with (
            patch.object(manager, "_get_peer_proxy", return_value=mock_proxy),
            patch(
                "actingweb.subscription_config.SubscriptionProcessingConfig"
            ) as mock_config_class,
            patch.object(manager, "_refresh_peer_metadata") as mock_refresh,
        ):
            mock_config = MagicMock()
            mock_config.auto_storage = False
            mock_config_class.return_value = mock_config

            result = manager.subscribe_to_peer(
                peer_id="peer_1", target="properties", granularity="high"
            )

            assert result is not None
            # Verify metadata refresh was called regardless of storage
            mock_refresh.assert_called_once_with("peer_1")


class TestSyncSubscriptionBaselineFetch:
    """Tests for sync_subscription() baseline fetch behavior."""

    def test_sync_subscription_fetches_baseline_when_no_diffs(self):
        """Test sync_subscription fetches baseline when no diffs and auto_storage=True."""
        actor = FakeCoreActor()
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        config = SubscriptionProcessingConfig(
            enabled=True, auto_sequence=False, auto_storage=True
        )

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        # First call: fetch diffs (returns empty)
        # Second call: fetch baseline
        mock_proxy.get_resource.side_effect = [
            {"sequence": 5, "data": []},  # No diffs
            {"prop": {"value": "baseline"}},  # Baseline data
        ]

        with (
            patch.object(manager, "_get_peer_proxy", return_value=mock_proxy),
            patch("actingweb.remote_storage.RemotePeerStore") as mock_store_class,
            patch("actingweb.interface.actor_interface.ActorInterface"),
            patch("actingweb.subscription.Subscription"),
        ):
            mock_store = MagicMock()
            mock_store_class.return_value = mock_store

            result = manager.sync_subscription(
                peer_id="peer_1", subscription_id="sub_1", config=config
            )

            assert result.success is True
            assert result.diffs_fetched == 0
            assert result.diffs_processed == 1  # Baseline fetch counts as 1

            # Verify baseline was stored
            mock_store.apply_resync_data.assert_called_once()
            stored_data = mock_store.apply_resync_data.call_args[0][0]
            assert stored_data["prop"] == {"value": "baseline"}

    def test_sync_subscription_skips_baseline_when_auto_storage_false(self):
        """Test sync_subscription skips baseline fetch when auto_storage=False."""
        actor = FakeCoreActor()
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        config = SubscriptionProcessingConfig(
            enabled=True, auto_sequence=False, auto_storage=False
        )

        mock_proxy = MagicMock()
        mock_proxy.trust = {"verified": True}
        mock_proxy.get_resource.return_value = {"sequence": 5, "data": []}

        with (
            patch.object(manager, "_get_peer_proxy", return_value=mock_proxy),
            patch("actingweb.subscription.Subscription"),
        ):
            result = manager.sync_subscription(
                peer_id="peer_1", subscription_id="sub_1", config=config
            )

            assert result.success is True
            assert result.diffs_fetched == 0
            assert result.diffs_processed == 0

            # Verify only one call (for diffs, not baseline)
            assert mock_proxy.get_resource.call_count == 1


class TestRefreshPeerMetadata:
    """Tests for _refresh_peer_metadata() method."""

    def test_refresh_peer_metadata_when_profile_enabled(self):
        """Test metadata refresh calls profile fetch when configured."""
        actor = FakeCoreActor()
        actor.config.peer_profile_attributes = ["displayname", "email"]
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        with (
            patch("actingweb.peer_profile.fetch_peer_profile") as mock_fetch,
            patch("actingweb.peer_profile.get_peer_profile_store") as mock_get_store,
        ):
            mock_profile = MagicMock()
            mock_fetch.return_value = mock_profile
            mock_store = MagicMock()
            mock_get_store.return_value = mock_store

            manager._refresh_peer_metadata("peer_1")

            # Verify profile was fetched and stored
            mock_fetch.assert_called_once()
            mock_store.store_profile.assert_called_once_with(mock_profile)

    def test_refresh_peer_metadata_when_capabilities_enabled(self):
        """Test metadata refresh calls capabilities fetch when configured."""
        actor = FakeCoreActor()
        actor.config.peer_capabilities_caching = True
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        with (
            patch(
                "actingweb.peer_capabilities.fetch_peer_methods_and_actions"
            ) as mock_fetch,
            patch(
                "actingweb.peer_capabilities.get_cached_capabilities_store"
            ) as mock_get_store,
        ):
            mock_capabilities = MagicMock()
            mock_fetch.return_value = mock_capabilities
            mock_store = MagicMock()
            mock_get_store.return_value = mock_store

            manager._refresh_peer_metadata("peer_1")

            # Verify capabilities were fetched and stored
            mock_fetch.assert_called_once()
            mock_store.store_capabilities.assert_called_once_with(mock_capabilities)

    def test_refresh_peer_metadata_handles_errors_gracefully(self):
        """Test metadata refresh doesn't raise on errors."""
        actor = FakeCoreActor()
        actor.config.peer_profile_attributes = ["displayname"]
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        with patch(
            "actingweb.peer_profile.fetch_peer_profile",
            side_effect=Exception("Network error"),
        ):
            # Should not raise
            manager._refresh_peer_metadata("peer_1")
