"""Test revoked trust detection and cleanup during sync."""

import asyncio
import threading
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from actingweb.actor import TrustReplaced
from actingweb.interface.hooks import HookRegistry
from actingweb.interface.subscription_manager import (
    SubscriptionManager,
    SubscriptionSyncResult,
)


def _all_404(n: int) -> list[SubscriptionSyncResult]:
    return [
        SubscriptionSyncResult(
            subscription_id=f"sub{i}",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Not found",
            error_code=404,
        )
        for i in range(n)
    ]


async def _revoke(
    registry: HookRegistry, order: list[str], *, re_paired: bool = False
) -> tuple[Any, MagicMock, Any]:
    """``sync_peer_async`` against a peer that answers 404 everywhere; the
    core delete calls its callback with the row it re-read, as the real one
    does (3.16)."""
    mock_actor = MagicMock()
    mock_actor.id = "actor123"
    mock_actor.config = MagicMock()
    mock_actor.config.peer_profile_attributes = None
    mock_actor.config.peer_capabilities_caching = False
    mock_actor.config.peer_permissions_caching = False
    mock_actor.config._hooks = registry
    row = {"peerid": "peer456", "relationship": "friend", "secret": "s1"}

    def delete(**kw: Any) -> bool:
        if re_paired:
            raise TrustReplaced("peer456")
        kw["before_local_delete"](dict(row))
        order.append("delete")
        return True

    mock_actor.delete_reciprocal_trust = MagicMock(side_effect=delete)
    manager = SubscriptionManager(mock_actor)
    mock_proxy = MagicMock()
    mock_proxy.trust = dict(row)
    mock_proxy.last_response_code = 404
    mock_proxy.get_resource_async = AsyncMock(
        return_value={"error": {"code": 404, "message": "Not found"}}
    )
    manager._get_peer_proxy = MagicMock(return_value=mock_proxy)
    subs = [MagicMock(is_outbound=True, subscription_id=f"sub{i}") for i in range(2)]
    with (
        patch.object(manager, "get_subscriptions_to_peer", return_value=subs),
        patch.object(manager, "sync_subscription_async", side_effect=_all_404(2)),
    ):
        result = await manager.sync_peer_async("peer456")
    return result, mock_actor, mock_proxy


@pytest.mark.asyncio
async def test_sync_peer_detects_and_cleans_up_revoked_trust() -> None:
    """Test that sync_peer_async detects revoked trust (all 404s) and cleans up."""
    order: list[str] = []
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
    result, mock_actor, mock_proxy = await _revoke(registry, order)

    # Re-run 2 (Issue 7): only the row the probe used is deleted, so a
    # re-pair meanwhile keeps its row.
    mock_actor.delete_reciprocal_trust.assert_called_once_with(
        peerid="peer456",
        delete_peer=False,
        expected_secret="s1",
        before_local_delete=ANY,
    )
    # Verification re-run 1 (Issue B): the hooks fire from the delete's
    # re-read (a row already gone fires nothing), before it deletes; a
    # coroutine hook on the caller's loop, a sync hook off it.
    assert order == ["async_hook", "sync_hook", "delete"]
    assert seen["async_loop"] is main_loop
    assert seen["sync_thread"] is not threading.main_thread()
    assert seen["kw"]["trust_data"]["peerid"] == "peer456"
    assert seen["kw"]["initiated_by_peer"] is True
    # Audit A9: our own trust row at the peer, not trust/<our id>.
    mock_proxy.get_resource_async.assert_called_once_with(path="trust/friend/actor123")
    assert not result.success
    assert result.subscriptions_synced == 0
    assert result.error == "Trust relationship has been revoked by peer"


@pytest.mark.asyncio
async def test_a_hook_needing_the_default_pool_does_not_deadlock() -> None:
    """Re-run 2 (Issue 3): the delete held a default-pool thread while the
    coroutine hook it waited on needed one (``*_async`` calls use
    ``to_thread``); with the pool full, both waited for ever. The delete
    runs on its own executor."""
    from concurrent.futures import ThreadPoolExecutor

    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    order: list[str] = []
    registry = HookRegistry()

    async def hook_using_the_pool(actor: Any, **kw: Any) -> None:
        await asyncio.to_thread(order.append, "hook")

    registry.register_lifecycle_hook("trust_deleted", hook_using_the_pool)
    result, _, _ = await asyncio.wait_for(_revoke(registry, order), timeout=10)
    assert order == ["hook", "delete"]
    assert result.error == "Trust relationship has been revoked by peer"


@pytest.mark.asyncio
async def test_a_trust_re_paired_since_the_probe_is_kept() -> None:
    """Re-run 2 (Issue 7): the delete refuses a row whose secret is not the
    probe's; the sync reports no revocation and fires no hook."""
    order: list[str] = []
    registry = HookRegistry()
    registry.register_lifecycle_hook(
        "trust_deleted", lambda actor, **kw: order.append("hook")
    )
    result, _, _ = await _revoke(registry, order, re_paired=True)
    assert order == []
    assert result.error != "Trust relationship has been revoked by peer"


def test_a_coroutine_hook_that_never_finishes_is_given_up() -> None:
    """Re-run 2 (Issue 3): the worker thread waited with no bound; a loop
    that stopped, or a hook that hangs, is given up after the timeout and
    the next hook still runs."""
    registry = HookRegistry()
    registry.LOOP_HOOK_TIMEOUT_SECONDS = 0.2
    ran: list[str] = []
    loop = asyncio.new_event_loop()  # never run: the coroutine never starts

    async def never(actor: Any, **kw: Any) -> None:
        ran.append("never")

    def after(actor: Any, **kw: Any) -> None:
        ran.append("after")

    registry.register_lifecycle_hook("trust_deleted", never)
    registry.register_lifecycle_hook("trust_deleted", after)
    try:
        registry.execute_lifecycle_hooks_for_loop("trust_deleted", loop, None)
    finally:
        loop.close()
    assert ran == ["after"]


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
    mock_proxy.trust = {"relationship": "friend", "secret": "s1"}
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
                peerid="peer456",
                delete_peer=False,
                expected_secret="s1",
                before_local_delete=ANY,
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
