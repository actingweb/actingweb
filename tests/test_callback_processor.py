"""Unit tests for CallbackProcessor functionality.

Tests are grouped with @pytest.mark.xdist_group to ensure they run on the same
worker during parallel execution, since they all patch actingweb.attribute.Attributes.
"""

import asyncio
import time
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.callback_processor import (
    CallbackProcessor,
    CallbackType,
    ProcessedCallback,
    ProcessResult,
)

# Mark all tests in this module to run on the same xdist worker as test_remote_storage
# Both modules patch actingweb.attribute.Attributes, so they must run together
pytestmark = pytest.mark.xdist_group(name="attribute_patching")


# =============================================================================
# Shared Fixtures
# =============================================================================


@pytest.fixture
def mock_actor() -> MagicMock:
    """Create a mock ActorInterface."""
    actor = MagicMock()
    actor.id = "actor123"
    actor.config = MagicMock()
    return actor


@pytest.fixture
def mock_attributes() -> Generator[tuple[MagicMock, dict[str, Any]], None, None]:
    """Create mock for Attributes class with simulated storage.

    Yields:
        Tuple of (mock class, storage dict)
    """
    with patch("actingweb.attribute.Attributes") as mock:
        storage: dict[str, Any] = {}

        def get_attr_side_effect(name: str | None = None) -> dict[str, Any] | None:
            if name is None:
                return None
            return storage.get(name)

        def set_attr_side_effect(
            name: str | None = None, data: dict[str, Any] | None = None, **_kwargs: Any
        ) -> bool:
            if name is None:
                return False
            storage[name] = {"data": data, "timestamp": None}
            return True

        def delete_attr_side_effect(name: str | None = None) -> bool:
            if name is not None and name in storage:
                del storage[name]
            return True

        def get_bucket_side_effect() -> dict[str, Any]:
            return storage.copy()

        mock_instance = MagicMock()
        mock_instance.get_attr.side_effect = get_attr_side_effect
        mock_instance.set_attr.side_effect = set_attr_side_effect
        mock_instance.delete_attr.side_effect = delete_attr_side_effect
        mock_instance.get_bucket.side_effect = get_bucket_side_effect
        mock.return_value = mock_instance

        yield mock, storage


# =============================================================================
# Test Classes
# =============================================================================


class TestCallbackProcessorSequencing:
    """Test callback sequencing logic."""

    def test_process_first_callback_in_sequence(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test processing first callback (sequence 1)."""
        processor = CallbackProcessor(mock_actor)

        result = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "test"},
            )
        )

        assert result == ProcessResult.PROCESSED

        # Check state was updated
        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["last_seq"] == 1
        assert state_info["pending_count"] == 0

    def test_process_callback_in_order(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test processing callbacks in correct sequence order."""
        processor = CallbackProcessor(mock_actor)

        # Process sequence 1
        result1 = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )
        assert result1 == ProcessResult.PROCESSED

        # Process sequence 2
        result2 = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=2,
                data={"value": "second"},
            )
        )
        assert result2 == ProcessResult.PROCESSED

        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["last_seq"] == 2

    def test_detect_duplicate_callback(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test duplicate callback detection."""
        processor = CallbackProcessor(mock_actor)

        # Process sequence 1
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Try to process sequence 1 again
        result = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "duplicate"},
            )
        )

        assert result == ProcessResult.DUPLICATE

    def test_detect_old_sequence_as_duplicate(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test that sequences lower than last_seq are duplicates."""
        processor = CallbackProcessor(mock_actor)

        # Process sequences 1, 2, 3
        for seq in [1, 2, 3]:
            asyncio.get_event_loop().run_until_complete(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )

        # Try sequence 2 again
        result = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=2,
                data={"value": "old"},
            )
        )

        assert result == ProcessResult.DUPLICATE

    def test_gap_adds_to_pending(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test that gaps add callbacks to pending queue."""
        processor = CallbackProcessor(mock_actor)

        # Process sequence 1
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Skip to sequence 3 (gap at 2)
        result = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=3,
                data={"value": "third"},
            )
        )

        assert result == ProcessResult.PENDING

        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["last_seq"] == 1  # Still at 1
        assert state_info["pending_count"] == 1
        assert 3 in state_info["pending_sequences"]

    def test_fill_gap_processes_pending(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test that filling a gap processes pending callbacks."""
        processor = CallbackProcessor(mock_actor)
        processed_callbacks: list[int] = []

        async def track_handler(cb: ProcessedCallback) -> None:
            processed_callbacks.append(cb.sequence)

        # Process sequence 1
        await_result = asyncio.get_event_loop().run_until_complete
        await_result(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
                handler=track_handler,
            )
        )

        # Add sequence 3 to pending
        await_result(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=3,
                data={"value": "third"},
                handler=track_handler,
            )
        )

        # Fill gap with sequence 2
        processed_callbacks.clear()
        result = await_result(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=2,
                data={"value": "second"},
                handler=track_handler,
            )
        )

        assert result == ProcessResult.PROCESSED
        assert processed_callbacks == [2, 3]  # Both processed in order

        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["last_seq"] == 3
        assert state_info["pending_count"] == 0


class TestCallbackProcessorPendingQueue:
    """Test pending queue functionality."""

    def test_pending_queue_limit(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test back-pressure when pending queue is full."""
        processor = CallbackProcessor(mock_actor, max_pending=3)

        # Process sequence 1
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Add sequences 3, 4, 5 to pending (gap at 2)
        for seq in [3, 4, 5]:
            result = asyncio.get_event_loop().run_until_complete(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )
            assert result == ProcessResult.PENDING

        # Try to add sequence 6 - should be rejected
        result = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=6,
                data={"value": "seq6"},
            )
        )

        assert result == ProcessResult.REJECTED

    def test_pending_callbacks_sorted(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test that pending callbacks are sorted by sequence."""
        processor = CallbackProcessor(mock_actor)

        # Process sequence 1
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Add out-of-order sequences to pending
        for seq in [5, 3, 4]:
            asyncio.get_event_loop().run_until_complete(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )

        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["pending_sequences"] == [3, 4, 5]  # Sorted

    def test_gap_timeout_triggers_resync(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test that gap timeout triggers resync."""
        processor = CallbackProcessor(mock_actor, gap_timeout_seconds=0.1)

        # Process sequence 1
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Add sequence 3 to pending (gap at 2)
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=3,
                data={"value": "third"},
            )
        )

        # Wait for timeout
        time.sleep(0.15)

        # Try to add another callback - should trigger resync
        result = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=4,
                data={"value": "fourth"},
            )
        )

        assert result == ProcessResult.RESYNC_TRIGGERED

        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["resync_pending"] is True
        assert state_info["pending_count"] == 0  # Queue cleared


class TestCallbackProcessorResync:
    """Test resync callback handling."""

    def test_resync_resets_state(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test that resync callback resets state."""
        processor = CallbackProcessor(mock_actor)

        # Build up some state
        for seq in [1, 2, 3]:
            asyncio.get_event_loop().run_until_complete(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )

        # Add pending callbacks
        for seq in [5, 6]:
            asyncio.get_event_loop().run_until_complete(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )

        # Process resync callback
        result = asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=10,
                data={"url": "https://example.com/data"},
                callback_type="resync",
            )
        )

        assert result == ProcessResult.PROCESSED

        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["last_seq"] == 10  # Reset to resync sequence
        assert state_info["pending_count"] == 0  # Queue cleared
        assert state_info["resync_pending"] is False

    def test_resync_invokes_handler(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test that resync invokes handler with correct type."""
        processor = CallbackProcessor(mock_actor)
        received_callback: ProcessedCallback | None = None

        async def handler(cb: ProcessedCallback) -> None:
            nonlocal received_callback
            received_callback = cb

        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=5,
                data={"url": "https://example.com/resync"},
                callback_type="resync",
                handler=handler,
            )
        )

        assert received_callback is not None
        assert received_callback.callback_type == CallbackType.RESYNC
        assert received_callback.sequence == 5
        assert received_callback.data["url"] == "https://example.com/resync"


class TestCallbackProcessorOptimisticLocking:
    """Test optimistic locking behavior."""

    def test_version_conflict_retries(self, mock_actor: MagicMock) -> None:
        """Test that version conflicts trigger retries."""
        with patch("actingweb.attribute.Attributes") as mock:
            storage: dict[str, Any] = {}
            call_count = [0]

            def get_attr_side_effect(
                name: str | None = None,
            ) -> dict[str, Any] | None:
                if name is None:
                    return None
                return storage.get(name)

            def set_attr_side_effect(
                name: str | None = None,
                data: dict[str, Any] | None = None,
                **_kwargs: Any,
            ) -> bool:
                if name is None:
                    return False
                call_count[0] += 1
                # First two calls fail (version conflict), third succeeds
                if call_count[0] <= 2 and "state:" in str(name):
                    # Simulate external update by bumping version
                    current = storage.get(name, {"data": {"version": 0}})
                    if current:
                        current_data = current.get("data") or {}
                        version = data.get("version", 0) if data else 0
                        current_data["version"] = version
                        storage[name] = {"data": current_data, "timestamp": None}
                    return True
                storage[name] = {"data": data, "timestamp": None}
                return True

            def delete_attr_side_effect(name: str | None = None) -> bool:
                if name is not None and name in storage:
                    del storage[name]
                return True

            def get_bucket_side_effect() -> dict[str, Any]:
                return storage.copy()

            mock_instance = MagicMock()
            mock_instance.get_attr.side_effect = get_attr_side_effect
            mock_instance.set_attr.side_effect = set_attr_side_effect
            mock_instance.delete_attr.side_effect = delete_attr_side_effect
            mock_instance.get_bucket.side_effect = get_bucket_side_effect
            mock.return_value = mock_instance

            processor = CallbackProcessor(
                mock_actor, max_retries=3, retry_backoff_base=0.01
            )

            result = asyncio.get_event_loop().run_until_complete(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=1,
                    data={"value": "test"},
                )
            )

            assert result == ProcessResult.PROCESSED


class TestCallbackProcessorCleanup:
    """Test state cleanup functionality."""

    def test_clear_state_removes_subscription_data(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test clearing state for a subscription."""
        processor = CallbackProcessor(mock_actor)

        # Create some state
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "test"},
            )
        )

        # Add pending
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=3,
                data={"value": "pending"},
            )
        )

        # Clear state
        processor.clear_state("peer1", "sub1")

        # State should be reset
        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["last_seq"] == 0
        assert state_info["pending_count"] == 0

    def test_clear_all_state_for_peer(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test clearing all state for a peer."""
        processor = CallbackProcessor(mock_actor)

        # Create state for multiple subscriptions
        for sub_id in ["sub1", "sub2", "sub3"]:
            asyncio.get_event_loop().run_until_complete(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id=sub_id,
                    sequence=1,
                    data={"value": "test"},
                )
            )

        # Create state for another peer
        asyncio.get_event_loop().run_until_complete(
            processor.process_callback(
                peer_id="peer2",
                subscription_id="sub1",
                sequence=1,
                data={"value": "test"},
            )
        )

        # Clear all state for peer1
        processor.clear_all_state_for_peer("peer1")

        # peer1 state should be cleared
        for sub_id in ["sub1", "sub2", "sub3"]:
            state_info = processor.get_state_info("peer1", sub_id)
            assert state_info["last_seq"] == 0

        # peer2 state should remain
        state_info = processor.get_state_info("peer2", "sub1")
        assert state_info["last_seq"] == 1


class TestCallbackProcessorSyncVersion:
    """Test synchronous version of callback processing."""

    def test_sync_process_callback(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test synchronous callback processing."""
        processor = CallbackProcessor(mock_actor)

        result = processor.process_callback_sync(
            peer_id="peer1",
            subscription_id="sub1",
            sequence=1,
            data={"value": "test"},
        )

        assert result == ProcessResult.PROCESSED

        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["last_seq"] == 1

    def test_sync_handler_invoked(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test sync handler is invoked correctly."""
        processor = CallbackProcessor(mock_actor)
        received_callbacks: list[ProcessedCallback] = []

        def handler(cb: ProcessedCallback) -> None:
            received_callbacks.append(cb)

        processor.process_callback_sync(
            peer_id="peer1",
            subscription_id="sub1",
            sequence=1,
            data={"value": "test"},
            handler=handler,
        )

        assert len(received_callbacks) == 1
        assert received_callbacks[0].sequence == 1
        assert received_callbacks[0].callback_type == CallbackType.DIFF

    def test_sync_resync_processing(
        self, mock_actor: MagicMock, mock_attributes: tuple[MagicMock, dict[str, Any]]  # noqa: ARG002
    ) -> None:
        """Test synchronous resync processing."""
        processor = CallbackProcessor(mock_actor)
        received_callback: ProcessedCallback | None = None

        def handler(cb: ProcessedCallback) -> None:
            nonlocal received_callback
            received_callback = cb

        result = processor.process_callback_sync(
            peer_id="peer1",
            subscription_id="sub1",
            sequence=5,
            data={"url": "https://example.com/resync"},
            callback_type="resync",
            handler=handler,
        )

        assert result == ProcessResult.PROCESSED
        assert received_callback is not None
        assert received_callback.callback_type == CallbackType.RESYNC


class TestProcessedCallbackDataclass:
    """Test ProcessedCallback dataclass."""

    def test_processed_callback_creation(self) -> None:
        """Test creating ProcessedCallback."""
        cb = ProcessedCallback(
            peer_id="peer1",
            subscription_id="sub1",
            sequence=5,
            callback_type=CallbackType.DIFF,
            data={"key": "value"},
            timestamp="2024-01-01T00:00:00Z",
        )

        assert cb.peer_id == "peer1"
        assert cb.subscription_id == "sub1"
        assert cb.sequence == 5
        assert cb.callback_type == CallbackType.DIFF
        assert cb.data == {"key": "value"}
        assert cb.timestamp == "2024-01-01T00:00:00Z"


class TestCallbackTypeEnum:
    """Test CallbackType enum."""

    def test_callback_type_values(self) -> None:
        """Test CallbackType enum values."""
        assert CallbackType.DIFF.value == "diff"
        assert CallbackType.RESYNC.value == "resync"


class TestProcessResultEnum:
    """Test ProcessResult enum."""

    def test_process_result_values(self) -> None:
        """Test ProcessResult enum values."""
        assert ProcessResult.PROCESSED.value == "processed"
        assert ProcessResult.DUPLICATE.value == "duplicate"
        assert ProcessResult.PENDING.value == "pending"
        assert ProcessResult.RESYNC_TRIGGERED.value == "resync_triggered"
        assert ProcessResult.REJECTED.value == "rejected"
