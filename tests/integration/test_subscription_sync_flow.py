"""
Integration tests for subscription sync methods.

Tests the pull-based synchronization API:
- SubscriptionSyncResult and PeerSyncResult dataclasses
- Export verification from actingweb.interface module

Note: The sync_subscription() and sync_peer() methods are thoroughly tested
in the unit tests (tests/test_subscription_sync.py). These integration tests
focus on verifying the public API exports work correctly.
"""

import pytest

from actingweb.interface import (
    PeerSyncResult,
    SubscriptionSyncResult,
)


@pytest.mark.xdist_group(name="subscription_sync_dataclasses")
class TestSyncResultDataclasses:
    """
    Integration tests verifying SubscriptionSyncResult and PeerSyncResult.

    These tests verify that the sync result types are properly exported
    from the actingweb.interface module and work as expected.
    """

    def test_subscription_sync_result_from_module(self):
        """Verify SubscriptionSyncResult is exported from interface module."""
        result = SubscriptionSyncResult(
            subscription_id="test_sub",
            success=True,
            diffs_fetched=5,
            diffs_processed=5,
            final_sequence=10,
        )

        assert result.subscription_id == "test_sub"
        assert result.success is True
        assert result.diffs_fetched == 5
        assert result.diffs_processed == 5
        assert result.final_sequence == 10
        assert result.error is None
        assert result.error_code is None

    def test_peer_sync_result_from_module(self):
        """Verify PeerSyncResult is exported from interface module."""
        sub_results = [
            SubscriptionSyncResult(
                subscription_id="sub1",
                success=True,
                diffs_fetched=3,
                diffs_processed=3,
                final_sequence=5,
            ),
            SubscriptionSyncResult(
                subscription_id="sub2",
                success=True,
                diffs_fetched=2,
                diffs_processed=2,
                final_sequence=8,
            ),
        ]

        result = PeerSyncResult(
            peer_id="peer123",
            success=True,
            subscriptions_synced=2,
            total_diffs_processed=5,
            subscription_results=sub_results,
        )

        assert result.peer_id == "peer123"
        assert result.success is True
        assert result.subscriptions_synced == 2
        assert result.total_diffs_processed == 5
        assert len(result.subscription_results) == 2
        assert result.error is None

    def test_subscription_sync_result_with_error(self):
        """Verify error handling in SubscriptionSyncResult."""
        result = SubscriptionSyncResult(
            subscription_id="test_sub",
            success=False,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=0,
            error="Peer unreachable",
            error_code=502,
        )

        assert result.success is False
        assert result.error == "Peer unreachable"
        assert result.error_code == 502

    def test_peer_sync_result_with_partial_failure(self):
        """Verify PeerSyncResult handles partial failures correctly."""
        sub_results = [
            SubscriptionSyncResult(
                subscription_id="sub1",
                success=True,
                diffs_fetched=3,
                diffs_processed=3,
                final_sequence=5,
            ),
            SubscriptionSyncResult(
                subscription_id="sub2",
                success=False,
                diffs_fetched=0,
                diffs_processed=0,
                final_sequence=0,
                error="Connection timeout",
                error_code=408,
            ),
        ]

        result = PeerSyncResult(
            peer_id="peer123",
            success=False,  # Overall failure due to one subscription failing
            subscriptions_synced=1,
            total_diffs_processed=3,
            subscription_results=sub_results,
        )

        assert result.success is False
        assert result.subscriptions_synced == 1
        assert result.total_diffs_processed == 3
        assert len(result.subscription_results) == 2

        # Verify individual results
        success_results = [r for r in result.subscription_results if r.success]
        failed_results = [r for r in result.subscription_results if not r.success]
        assert len(success_results) == 1
        assert len(failed_results) == 1
        assert failed_results[0].error_code == 408

    def test_subscription_sync_result_no_diffs(self):
        """Verify SubscriptionSyncResult handles empty sync correctly."""
        result = SubscriptionSyncResult(
            subscription_id="test_sub",
            success=True,
            diffs_fetched=0,
            diffs_processed=0,
            final_sequence=5,  # Current sequence even with no pending diffs
        )

        assert result.success is True
        assert result.diffs_fetched == 0
        assert result.diffs_processed == 0
        assert result.final_sequence == 5
        assert result.error is None

    def test_peer_sync_result_no_subscriptions(self):
        """Verify PeerSyncResult handles no subscriptions correctly."""
        result = PeerSyncResult(
            peer_id="peer123",
            success=True,
            subscriptions_synced=0,
            total_diffs_processed=0,
            subscription_results=[],
        )

        assert result.success is True
        assert result.subscriptions_synced == 0
        assert result.total_diffs_processed == 0
        assert len(result.subscription_results) == 0
