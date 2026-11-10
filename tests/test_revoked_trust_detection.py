"""Test revoked trust detection and cleanup during sync."""

import asyncio
import threading
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from actingweb.interface.hooks import HookRegistry
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

    # The delete runs in a worker thread, as the real one does, and calls
    # the callback with the row it re-read (3.16).
    order: list[str] = []
    row = {"peerid": "peer456", "relationship": "friend"}

    def delete_in_thread(**kw: Any) -> bool:
        kw["before_local_delete"](dict(row))
        order.append("delete")
        return True

    async def delete_async(**kw: Any) -> bool:
        return await asyncio.to_thread(delete_in_thread, **kw)

    mock_actor.delete_reciprocal_trust_async = AsyncMock(side_effect=delete_async)

    registry = HookRegistry()
    seen: dict[str, Any] = {}
    main_loop = asyncio.get_running_loop()

    async def async_hook(actor: Any, **kw: Any) -> None:
        seen["async_loop"] = asyncio.get_running_loop()
        seen["kw"] = kw
        order.append("async_hook")

    def sync_hook(actor: Any, **kw: Any) -> None:
        seen["sync_thread"] = threading.current_thread()
        order.append("sync_hook")

    registry.register_lifecycle_hook("trust_deleted", async_hook)
    registry.register_lifecycle_hook("trust_deleted", sync_hook)
    mock_actor.config._hooks = registry

    # Create manager
    manager = SubscriptionManager(mock_actor)

    # Mock _get_peer_proxy to return a proxy that simulates peer not existing
    mock_proxy = MagicMock()
    mock_proxy.trust = {"relationship": "friend"}
    mock_proxy.last_response_code = 404
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
                peerid="peer456", delete_peer=False, before_local_delete=ANY
            )
            # Verification re-run 1 (Issue B): the hooks fire from the
            # delete's re-read (a row already gone fires nothing), before it
            # deletes; a coroutine hook on the caller's loop, a sync hook off
            # it.
            assert order == ["async_hook", "sync_hook", "delete"]
            assert seen["async_loop"] is main_loop
            assert seen["sync_thread"] is not threading.main_thread()
            assert seen["kw"]["trust_data"]["peerid"] == "peer456"
            assert seen["kw"]["initiated_by_peer"] is True
            # Audit A9: our own trust row at the peer, not trust/<our id>.
            mock_proxy.get_resource_async.assert_called_once_with(
                path="trust/friend/actor123"
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
    mock_proxy.trust = {"relationship": "friend"}
    mock_proxy.last_response_code = 404
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
                peerid="peer456", delete_peer=False, before_local_delete=ANY
            )
            # The hook fires through the delete's callback (3.16), with the
            # row the delete read and initiated_by_peer.
            hooks = mock_actor.config._hooks  # what the manager's ActorInterface holds
            callback = mock_actor.delete_reciprocal_trust.call_args.kwargs[
                "before_local_delete"
            ]
            callback({"peerid": "peer456", "relationship": "friend"})
            event, *_ = hooks.execute_lifecycle_hooks.call_args.args
            assert event == "trust_deleted"
            kwargs = hooks.execute_lifecycle_hooks.call_args.kwargs
            assert kwargs["trust_data"]["peerid"] == "peer456"
            assert kwargs["initiated_by_peer"] is True

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


def _all_404_manager(code: int) -> tuple[SubscriptionManager, MagicMock, MagicMock]:
    mock_actor = MagicMock()
    mock_actor.id = "actor123"
    mock_actor.config = MagicMock()
    mock_actor.config.peer_profile_attributes = None
    mock_actor.config.peer_capabilities_caching = False
    mock_actor.config.peer_permissions_caching = False
    mock_actor.delete_reciprocal_trust = MagicMock(return_value=True)
    manager = SubscriptionManager(mock_actor)
    proxy = MagicMock()
    proxy.trust = {"relationship": "friend"}
    proxy.last_response_code = code
    proxy.get_resource = MagicMock(return_value={"id": "x"})
    manager._get_peer_proxy = MagicMock(return_value=proxy)  # type: ignore[method-assign]
    sub = MagicMock()
    sub.is_outbound = True
    sub.subscription_id = "sub1"
    manager.get_subscriptions_to_peer = MagicMock(return_value=[sub])  # type: ignore[method-assign]
    manager.sync_subscription = MagicMock(  # type: ignore[method-assign]
        return_value=SubscriptionSyncResult(
            subscription_id="sub1",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )
    )
    return manager, mock_actor, proxy


@pytest.mark.parametrize("code", [500, 502, 408])
def test_an_unreachable_peer_keeps_the_trust(code: int) -> None:
    """Audit A9: only a refusal (401, 403, 404) of our own trust row at the
    peer reads as revoked; no answer or a server error keeps the trust."""
    manager, actor, proxy = _all_404_manager(code)
    manager.sync_peer("peer456")
    actor.delete_reciprocal_trust.assert_not_called()
    proxy.get_resource.assert_called_once_with(path="trust/friend/actor123")


def test_a_json_refusal_is_not_read_as_a_live_trust() -> None:
    """A 404 with a JSON body reached the old check without an ``error`` key
    and read as "trust exists"; the status decides now."""
    manager, actor, _ = _all_404_manager(404)
    manager.sync_peer("peer456")
    actor.delete_reciprocal_trust.assert_called_once()
