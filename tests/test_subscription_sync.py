"""
Unit tests for SubscriptionManager sync methods.

Tests the pull-based synchronization API:
- sync_subscription()
- sync_peer()
- sync_subscription_async()
- sync_peer_async()
- SubscriptionSyncResult
- PeerSyncResult
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.interface.subscription_manager import (
    PeerSyncResult,
    SubscriptionManager,
    SubscriptionSyncResult,
)
from actingweb.subscription_config import SubscriptionProcessingConfig


class FakeConfig:
    """Minimal Config mock for testing."""

    def __init__(self) -> None:
        self.root = "https://example.com/"


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

    def get_subscriptions(
        self,
        peerid: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
    ) -> list[dict[str, Any]]:
        """Mock get_subscriptions - returns list of dicts."""
        result = []
        for key, sub in self._subscriptions.items():
            if peerid is not None and key[0] != peerid:
                continue
            if target is not None and sub.get("target") != target:
                continue
            result.append(sub)
        return result


class TestSubscriptionSyncResult:
    """Tests for SubscriptionSyncResult dataclass."""

    def test_success_result(self):
        """Test creating a success result."""
        result = SubscriptionSyncResult(
            subscription_id="sub_1",
            success=True,
            diffs_fetched=5,
            diffs_processed=5,
            final_sequence=10,
        )

        assert result.subscription_id == "sub_1"
        assert result.success is True
        assert result.diffs_fetched == 5
        assert result.diffs_processed == 5
        assert result.final_sequence == 10
        assert result.error is None
        assert result.error_code is None

    def test_error_result(self):
        """Test creating an error result."""
        result = SubscriptionSyncResult(
            subscription_id="sub_1",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Subscription not found",
            error_code=404,
        )

        assert result.success is False
        assert result.error == "Subscription not found"
        assert result.error_code == 404


class TestPeerSyncResult:
    """Tests for PeerSyncResult dataclass."""

    def test_success_result(self):
        """Test creating a success result."""
        sub_results = [
            SubscriptionSyncResult(
                subscription_id="sub_1",
                success=True,
                diffs_fetched=3,
                diffs_processed=3,
                final_sequence=5,
            ),
            SubscriptionSyncResult(
                subscription_id="sub_2",
                success=True,
                diffs_fetched=2,
                diffs_processed=2,
                final_sequence=8,
            ),
        ]

        result = PeerSyncResult(
            peer_id="peer_1",
            success=True,
            subscriptions_synced=2,
            total_diffs_processed=5,
            subscription_results=sub_results,
        )

        assert result.peer_id == "peer_1"
        assert result.success is True
        assert result.subscriptions_synced == 2
        assert result.total_diffs_processed == 5
        assert len(result.subscription_results) == 2
        assert result.error is None

    def test_partial_failure_result(self):
        """Test result when some subscriptions failed."""
        sub_results = [
            SubscriptionSyncResult(
                subscription_id="sub_1",
                success=True,
                diffs_fetched=3,
                diffs_processed=3,
                final_sequence=5,
            ),
            SubscriptionSyncResult(
                subscription_id="sub_2",
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Peer unreachable",
                error_code=502,
            ),
        ]

        result = PeerSyncResult(
            peer_id="peer_1",
            success=False,
            subscriptions_synced=1,
            total_diffs_processed=3,
            subscription_results=sub_results,
        )

        assert result.success is False
        assert result.subscriptions_synced == 1


class TestSyncSubscription:
    """Tests for SubscriptionManager.sync_subscription()."""

    def test_subscription_not_found(self):
        """Test sync when subscription doesn't exist."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.sync_subscription(
            peer_id="peer_1", subscription_id="sub_nonexistent"
        )

        assert result.success is False
        assert result.error == "Subscription not found"
        assert result.error_code == 404

    def test_no_trust_relationship(self):
        """Test sync when no trust relationship exists."""
        actor = FakeCoreActor()
        # Add a callback subscription
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Mock _get_peer_proxy to return proxy with no trust
        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = None
            mock_get_proxy.return_value = mock_proxy

            result = manager.sync_subscription(
                peer_id="peer_1", subscription_id="sub_1"
            )

        assert result.success is False
        assert result.error == "No trust relationship with peer"
        assert result.error_code == 404

    def test_peer_communication_error(self):
        """Test sync when peer communication fails."""
        actor = FakeCoreActor()
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}
            mock_proxy.get_resource.return_value = None
            mock_proxy.last_response_code = 502
            mock_get_proxy.return_value = mock_proxy

            result = manager.sync_subscription(
                peer_id="peer_1", subscription_id="sub_1"
            )

        assert result.success is False
        assert result.error_code == 502

    def test_peer_error_response(self):
        """Test sync when peer returns an error."""
        actor = FakeCoreActor()
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}
            mock_proxy.get_resource.return_value = {
                "error": {"code": 403, "message": "Forbidden"}
            }
            mock_get_proxy.return_value = mock_proxy

            result = manager.sync_subscription(
                peer_id="peer_1", subscription_id="sub_1"
            )

        assert result.success is False
        assert result.error == "Forbidden"
        assert result.error_code == 403

    def test_no_pending_diffs(self):
        """Test sync when there are no pending diffs (without auto_storage baseline fetch)."""
        actor = FakeCoreActor()
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        # Use auto_storage=False to test the simple no-diff path
        # (auto_storage=True would trigger baseline fetching)
        config = SubscriptionProcessingConfig(
            enabled=True, auto_sequence=False, auto_storage=False
        )

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}
            mock_proxy.get_resource.return_value = {"sequence": 5, "data": []}
            mock_get_proxy.return_value = mock_proxy

            result = manager.sync_subscription(
                peer_id="peer_1", subscription_id="sub_1", config=config
            )

        assert result.success is True
        assert result.diffs_fetched == 0
        assert result.diffs_processed == 0
        assert result.final_sequence == 5

    def test_success_with_diffs_no_sequence_tracking(self):
        """Test successful sync with diffs but no sequence tracking."""
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

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}
            mock_proxy.get_resource.return_value = {
                "sequence": 10,
                "data": [
                    {"sequence": 8, "timestamp": "2024-01-01T00:00:00Z", "data": {}},
                    {"sequence": 9, "timestamp": "2024-01-01T00:00:01Z", "data": {}},
                    {"sequence": 10, "timestamp": "2024-01-01T00:00:02Z", "data": {}},
                ],
            }
            mock_proxy.change_resource.return_value = {}
            mock_get_proxy.return_value = mock_proxy

            result = manager.sync_subscription(
                peer_id="peer_1", subscription_id="sub_1", config=config
            )

        assert result.success is True
        assert result.diffs_fetched == 3
        assert result.diffs_processed == 3
        assert result.final_sequence == 10

        # Verify clear was called
        mock_proxy.change_resource.assert_called_once()
        call_args = mock_proxy.change_resource.call_args
        assert call_args.kwargs["params"]["sequence"] == 10

    def test_clear_diffs_failure_still_succeeds(self):
        """Test that sync succeeds even if clearing diffs fails."""
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

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}
            mock_proxy.get_resource.return_value = {
                "sequence": 5,
                "data": [
                    {"sequence": 5, "timestamp": "2024-01-01T00:00:00Z", "data": {}},
                ],
            }
            # Clear fails
            mock_proxy.change_resource.return_value = {"error": {"code": 500}}
            mock_get_proxy.return_value = mock_proxy

            result = manager.sync_subscription(
                peer_id="peer_1", subscription_id="sub_1", config=config
            )

        # Sync should still succeed
        assert result.success is True
        assert result.diffs_fetched == 1
        assert result.diffs_processed == 1


class TestSyncPeer:
    """Tests for SubscriptionManager.sync_peer()."""

    def test_no_outbound_subscriptions(self):
        """Test sync_peer when there are no outbound subscriptions."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = manager.sync_peer(peer_id="peer_1")

        assert result.success is True
        assert result.subscriptions_synced == 0
        assert result.total_diffs_processed == 0
        assert len(result.subscription_results) == 0

    def test_sync_multiple_subscriptions(self):
        """Test syncing multiple subscriptions to a peer."""
        actor = FakeCoreActor()
        # Add multiple outbound subscriptions
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        actor._subscriptions[("peer_1", "sub_2", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_2",
            "target": "events",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        config = SubscriptionProcessingConfig(
            enabled=True, auto_sequence=False, auto_storage=False
        )

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}
            # Return different diffs for different subscriptions
            mock_proxy.get_resource.side_effect = [
                {
                    "sequence": 5,
                    "data": [
                        {"sequence": 5, "data": {}},
                    ],
                },
                {
                    "sequence": 3,
                    "data": [
                        {"sequence": 2, "data": {}},
                        {"sequence": 3, "data": {}},
                    ],
                },
            ]
            mock_proxy.change_resource.return_value = {}
            mock_get_proxy.return_value = mock_proxy

            result = manager.sync_peer(peer_id="peer_1", config=config)

        assert result.success is True
        assert result.subscriptions_synced == 2
        assert result.total_diffs_processed == 3  # 1 + 2
        assert len(result.subscription_results) == 2

    def test_partial_failure(self):
        """Test sync_peer when some subscriptions fail."""
        actor = FakeCoreActor()
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        actor._subscriptions[("peer_1", "sub_2", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_2",
            "target": "events",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        config = SubscriptionProcessingConfig(
            enabled=True, auto_sequence=False, auto_storage=False
        )

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}
            # First succeeds, second fails
            mock_proxy.get_resource.side_effect = [
                {"sequence": 5, "data": [{"sequence": 5, "data": {}}]},
                {"error": {"code": 500, "message": "Internal error"}},
            ]
            mock_proxy.change_resource.return_value = {}
            mock_get_proxy.return_value = mock_proxy

            result = manager.sync_peer(peer_id="peer_1", config=config)

        assert result.success is False  # Overall failure due to one subscription failing
        assert result.subscriptions_synced == 1  # One succeeded
        assert result.total_diffs_processed == 1

        # Check individual results
        success_results = [r for r in result.subscription_results if r.success]
        failed_results = [r for r in result.subscription_results if not r.success]
        assert len(success_results) == 1
        assert len(failed_results) == 1
        assert failed_results[0].error_code == 500


class TestSyncSubscriptionAsync:
    """Tests for SubscriptionManager.sync_subscription_async()."""

    @pytest.mark.asyncio
    async def test_subscription_not_found(self):
        """Test async sync when subscription doesn't exist."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = await manager.sync_subscription_async(
            peer_id="peer_1", subscription_id="sub_nonexistent"
        )

        assert result.success is False
        assert result.error == "Subscription not found"
        assert result.error_code == 404

    @pytest.mark.asyncio
    async def test_no_trust_relationship(self):
        """Test async sync when no trust relationship exists."""
        actor = FakeCoreActor()
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = None
            mock_get_proxy.return_value = mock_proxy

            result = await manager.sync_subscription_async(
                peer_id="peer_1", subscription_id="sub_1"
            )

        assert result.success is False
        assert result.error == "No trust relationship with peer"
        assert result.error_code == 404

    @pytest.mark.asyncio
    async def test_success_with_diffs(self):
        """Test successful async sync with diffs."""
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

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}

            # Mock async methods
            async def mock_get_resource_async(path):
                return {
                    "sequence": 5,
                    "data": [
                        {"sequence": 5, "timestamp": "2024-01-01T00:00:00Z", "data": {}},
                    ],
                }

            async def mock_change_resource_async(path, params):
                return {}

            mock_proxy.get_resource_async = mock_get_resource_async
            mock_proxy.change_resource_async = mock_change_resource_async
            mock_get_proxy.return_value = mock_proxy

            result = await manager.sync_subscription_async(
                peer_id="peer_1", subscription_id="sub_1", config=config
            )

        assert result.success is True
        assert result.diffs_fetched == 1
        assert result.diffs_processed == 1
        assert result.final_sequence == 5


class TestSyncPeerAsync:
    """Tests for SubscriptionManager.sync_peer_async()."""

    @pytest.mark.asyncio
    async def test_no_outbound_subscriptions(self):
        """Test async sync_peer when there are no outbound subscriptions."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        result = await manager.sync_peer_async(peer_id="peer_1")

        assert result.success is True
        assert result.subscriptions_synced == 0
        assert result.total_diffs_processed == 0

    @pytest.mark.asyncio
    async def test_sync_multiple_subscriptions_concurrent(self):
        """Test async syncing multiple subscriptions concurrently."""
        actor = FakeCoreActor()
        actor._subscriptions[("peer_1", "sub_1", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_1",
            "target": "properties",
            "callback": True,
        }
        actor._subscriptions[("peer_1", "sub_2", True)] = {
            "peerid": "peer_1",
            "subscriptionid": "sub_2",
            "target": "events",
            "callback": True,
        }
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        config = SubscriptionProcessingConfig(
            enabled=True, auto_sequence=False, auto_storage=False
        )

        call_count = 0

        with patch.object(manager, "_get_peer_proxy") as mock_get_proxy:
            mock_proxy = MagicMock()
            mock_proxy.trust = {"baseuri": "https://peer.example.com/", "secret": "s"}

            async def mock_get_resource_async(path):
                nonlocal call_count
                call_count += 1
                # Return different diffs based on path
                if "sub_1" in path:
                    return {"sequence": 5, "data": [{"sequence": 5, "data": {}}]}
                return {
                    "sequence": 3,
                    "data": [
                        {"sequence": 2, "data": {}},
                        {"sequence": 3, "data": {}},
                    ],
                }

            async def mock_change_resource_async(path, params):
                return {}

            mock_proxy.get_resource_async = mock_get_resource_async
            mock_proxy.change_resource_async = mock_change_resource_async
            mock_get_proxy.return_value = mock_proxy

            result = await manager.sync_peer_async(peer_id="peer_1", config=config)

        assert result.success is True
        assert result.subscriptions_synced == 2
        assert result.total_diffs_processed == 3
        assert call_count == 2  # Both subscriptions were called


class TestGetPeerProxy:
    """Tests for SubscriptionManager._get_peer_proxy()."""

    def test_creates_proxy_with_correct_params(self):
        """Test that _get_peer_proxy creates AwProxy with correct parameters."""
        actor = FakeCoreActor()
        manager = SubscriptionManager(actor)  # type: ignore[arg-type]

        with patch("actingweb.aw_proxy.AwProxy") as MockAwProxy:
            mock_proxy = MagicMock()
            MockAwProxy.return_value = mock_proxy

            result = manager._get_peer_proxy("peer_123")

            MockAwProxy.assert_called_once()
            call_kwargs = MockAwProxy.call_args.kwargs
            assert call_kwargs["peer_target"]["id"] == "actor_1"
            assert call_kwargs["peer_target"]["peerid"] == "peer_123"
            assert call_kwargs["config"] == actor.config
            assert result == mock_proxy
