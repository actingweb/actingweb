"""Test revoked trust detection and cleanup during sync."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from actingweb.interface.subscription_manager import (
    SubscriptionManager,
    SubscriptionSyncResult,
)


@pytest.mark.asyncio
async def test_sync_peer_detects_and_cleans_up_revoked_trust():
    """Test that sync_peer_async detects revoked trust (all 404s) and cleans up."""
    # Setup mock core actor
    mock_actor = MagicMock()
    mock_actor.id = "actor123"
    mock_actor.config = MagicMock()
    mock_actor.config.peer_profile_attributes = None
    mock_actor.config.peer_capabilities_caching = False
    mock_actor.config.peer_permissions_caching = False

    # Mock successful trust deletion
    mock_actor.delete_reciprocal_trust_async = AsyncMock(return_value=True)

    # Create manager
    manager = SubscriptionManager(mock_actor)

    # Mock _get_peer_proxy to return a proxy that simulates peer not existing
    mock_proxy = MagicMock()
    mock_proxy.get_resource_async = AsyncMock(
        return_value={"error": {"code": 404, "message": "Not found"}}
    )
    manager._get_peer_proxy = MagicMock(return_value=mock_proxy)

    # Mock subscriptions to peer
    mock_sub1 = MagicMock()
    mock_sub1.is_outbound = True
    mock_sub1.subscription_id = "sub1"

    mock_sub2 = MagicMock()
    mock_sub2.is_outbound = True
    mock_sub2.subscription_id = "sub2"

    with patch.object(
        manager,
        "get_subscriptions_to_peer",
        return_value=[mock_sub1, mock_sub2],
    ):
        # Mock sync_subscription_async to return 404 errors for all subscriptions
        mock_result1 = SubscriptionSyncResult(
            subscription_id="sub1",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )
        mock_result2 = SubscriptionSyncResult(
            subscription_id="sub2",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )

        with patch.object(
            manager,
            "sync_subscription_async",
            side_effect=[mock_result1, mock_result2],
        ):
            # Execute sync
            result = await manager.sync_peer_async("peer456")

            # Verify trust deletion was called
            mock_actor.delete_reciprocal_trust_async.assert_called_once_with(
                peerid="peer456", delete_peer=False
            )

            # Verify result
            assert not result.success
            assert result.subscriptions_synced == 0
            assert result.error == "Trust relationship has been revoked by peer"


@pytest.mark.asyncio
async def test_sync_peer_ignores_mixed_errors():
    """Test that sync_peer_async doesn't cleanup on mixed error codes."""
    # Setup mock core actor
    mock_actor = MagicMock()
    mock_actor.id = "actor123"
    mock_actor.config = MagicMock()
    mock_actor.config.peer_profile_attributes = None
    mock_actor.config.peer_capabilities_caching = False
    mock_actor.config.peer_permissions_caching = False

    mock_actor.delete_reciprocal_trust_async = AsyncMock(return_value=True)

    # Create manager
    manager = SubscriptionManager(mock_actor)

    # Mock subscriptions to peer
    mock_sub1 = MagicMock()
    mock_sub1.is_outbound = True
    mock_sub1.subscription_id = "sub1"

    mock_sub2 = MagicMock()
    mock_sub2.is_outbound = True
    mock_sub2.subscription_id = "sub2"

    with patch.object(
        manager,
        "get_subscriptions_to_peer",
        return_value=[mock_sub1, mock_sub2],
    ):
        # Mock sync_subscription_async to return mixed errors (404 and 500)
        mock_result1 = SubscriptionSyncResult(
            subscription_id="sub1",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )
        mock_result2 = SubscriptionSyncResult(
            subscription_id="sub2",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Server error",
            error_code=500,
        )

        with patch.object(
            manager,
            "sync_subscription_async",
            side_effect=[mock_result1, mock_result2],
        ):
            # Execute sync
            result = await manager.sync_peer_async("peer456")

            # Verify trust deletion was NOT called (mixed error codes)
            mock_actor.delete_reciprocal_trust_async.assert_not_called()

            # Verify result
            assert not result.success
            assert result.error is None  # No revocation detected


def test_sync_peer_sync_detects_and_cleans_up_revoked_trust():
    """Test that sync_peer (sync) detects revoked trust (all 404s) and cleans up."""
    # Setup mock core actor
    mock_actor = MagicMock()
    mock_actor.id = "actor123"
    mock_actor.config = MagicMock()
    mock_actor.config.peer_profile_attributes = None
    mock_actor.config.peer_capabilities_caching = False
    mock_actor.config.peer_permissions_caching = False

    # Mock successful trust deletion
    mock_actor.delete_reciprocal_trust = MagicMock(return_value=True)

    # Create manager
    manager = SubscriptionManager(mock_actor)

    # Mock _get_peer_proxy to return a proxy that simulates peer not existing
    mock_proxy = MagicMock()
    mock_proxy.get_resource = MagicMock(
        return_value={"error": {"code": 404, "message": "Not found"}}
    )
    manager._get_peer_proxy = MagicMock(return_value=mock_proxy)

    # Mock subscriptions to peer
    mock_sub1 = MagicMock()
    mock_sub1.is_outbound = True
    mock_sub1.subscription_id = "sub1"

    mock_sub2 = MagicMock()
    mock_sub2.is_outbound = True
    mock_sub2.subscription_id = "sub2"

    with patch.object(
        manager,
        "get_subscriptions_to_peer",
        return_value=[mock_sub1, mock_sub2],
    ):
        # Mock sync_subscription to return 404 errors for all subscriptions
        mock_result1 = SubscriptionSyncResult(
            subscription_id="sub1",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )
        mock_result2 = SubscriptionSyncResult(
            subscription_id="sub2",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )

        with patch.object(
            manager,
            "sync_subscription",
            side_effect=[mock_result1, mock_result2],
        ):
            # Execute sync
            result = manager.sync_peer("peer456")

            # Verify trust deletion was called
            mock_actor.delete_reciprocal_trust.assert_called_once_with(
                peerid="peer456", delete_peer=False
            )

            # Verify result
            assert not result.success
            assert result.subscriptions_synced == 0
            assert result.error == "Trust relationship has been revoked by peer"


def test_sync_peer_sync_ignores_mixed_errors():
    """Test that sync_peer (sync) doesn't cleanup on mixed error codes."""
    # Setup mock core actor
    mock_actor = MagicMock()
    mock_actor.id = "actor123"
    mock_actor.config = MagicMock()
    mock_actor.config.peer_profile_attributes = None
    mock_actor.config.peer_capabilities_caching = False
    mock_actor.config.peer_permissions_caching = False

    mock_actor.delete_reciprocal_trust = MagicMock(return_value=True)

    # Create manager
    manager = SubscriptionManager(mock_actor)

    # Mock subscriptions to peer
    mock_sub1 = MagicMock()
    mock_sub1.is_outbound = True
    mock_sub1.subscription_id = "sub1"

    mock_sub2 = MagicMock()
    mock_sub2.is_outbound = True
    mock_sub2.subscription_id = "sub2"

    with patch.object(
        manager,
        "get_subscriptions_to_peer",
        return_value=[mock_sub1, mock_sub2],
    ):
        # Mock sync_subscription to return mixed errors (404 and 500)
        mock_result1 = SubscriptionSyncResult(
            subscription_id="sub1",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )
        mock_result2 = SubscriptionSyncResult(
            subscription_id="sub2",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Server error",
            error_code=500,
        )

        with patch.object(
            manager,
            "sync_subscription",
            side_effect=[mock_result1, mock_result2],
        ):
            # Execute sync
            result = manager.sync_peer("peer456")

            # Verify trust deletion was NOT called (mixed error codes)
            mock_actor.delete_reciprocal_trust.assert_not_called()

            # Verify result
            assert not result.success
            assert result.error is None  # No revocation detected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
