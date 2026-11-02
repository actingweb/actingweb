"""Unit tests for CallbackProcessor functionality.

Tests are grouped with @pytest.mark.xdist_group to ensure they run on the same
worker during parallel execution, since they all patch actingweb.attribute.Attributes.
"""

import asyncio
import copy
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
from actingweb.db.exceptions import DbError

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
def mock_subscription() -> Generator[tuple[MagicMock, dict[str, int]], None, None]:
    """Create mock for Subscription class with sequence number storage.

    Yields:
        Tuple of (mock class, sequence storage dict keyed by "peer_id:sub_id")
    """
    with patch("actingweb.subscription.Subscription") as mock:
        sequence_storage: dict[str, int] = {}

        def subscription_init(
            actor_id: str | None = None,  # noqa: ARG001
            peerid: str | None = None,
            subid: str | None = None,
            callback: bool = False,  # noqa: ARG001, FBT001, FBT002
            config: Any = None,  # noqa: ARG001, ANN401
        ) -> MagicMock:
            key = f"{peerid}:{subid}"
            mock_instance = MagicMock()
            mock_instance.handle = MagicMock()

            # get() returns subscription data with sequence
            def get_subscription() -> dict[str, Any]:
                return {"sequence": sequence_storage.get(key, 0)}

            mock_instance.get.side_effect = get_subscription

            # handle.modify(seqnr=N) updates the sequence
            def modify_sequence(seqnr: int | None = None) -> bool:
                if seqnr is not None:
                    sequence_storage[key] = seqnr
                return True

            mock_instance.handle.modify.side_effect = modify_sequence

            return mock_instance

        mock.side_effect = subscription_init

        yield mock, sequence_storage


@pytest.fixture
def mock_attributes() -> Generator[tuple[MagicMock, dict[str, Any]], None, None]:
    """Create mock for Attributes class with simulated storage.

    Yields:
        Tuple of (mock class, storage dict)
    """
    with patch("actingweb.attribute.Attributes") as mock:
        storage: dict[str, Any] = {}

        def get_attr_side_effect(
            name: str | None = None, **kw: Any
        ) -> dict[str, Any] | None:
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

        def get_bucket_side_effect(**kw: Any) -> dict[str, Any]:
            return storage.copy()

        mock_instance = MagicMock()
        mock_instance.get_attr.side_effect = get_attr_side_effect
        mock_instance.set_attr.side_effect = set_attr_side_effect
        mock_instance.delete_attr.side_effect = delete_attr_side_effect
        mock_instance.get_bucket.side_effect = get_bucket_side_effect
        _back_cas(mock_instance, storage)
        mock.return_value = mock_instance

        yield mock, storage


def _back_cas(mock_instance: MagicMock, storage: dict[str, Any]) -> None:
    """Back the compare-and-swap calls with ``storage``, as the backends do."""

    def conditional_update(
        name: str | None = None,
        old_data: Any = None,
        new_data: Any = None,
        **_k: Any,
    ) -> bool:
        row = storage.get(name or "")
        if row is None or row.get("data") != old_data:
            return False
        storage[name or ""] = {"data": copy.deepcopy(new_data), "timestamp": None}
        return True

    def create_if_absent(name: str | None = None, data: Any = None, **_k: Any) -> bool:
        row = storage.get(name or "")
        if row is not None:
            return row.get("data") == data
        storage[name or ""] = {"data": copy.deepcopy(data), "timestamp": None}
        return True

    def get_attr_strict(name: str | None = None, **_k: Any) -> dict[str, Any] | None:
        return storage.get(name or "")

    mock_instance.conditional_update_attr.side_effect = conditional_update
    mock_instance.create_attr_if_absent.side_effect = create_if_absent
    mock_instance.dbprop.get_attr_strict.side_effect = get_attr_strict


# =============================================================================
# Test Classes
# =============================================================================


class TestCallbackProcessorSequencing:
    """Test callback sequencing logic."""

    def test_process_first_callback_in_sequence(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test processing first callback (sequence 1)."""
        processor = CallbackProcessor(mock_actor)

        result = asyncio.run(
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test processing callbacks in correct sequence order."""
        processor = CallbackProcessor(mock_actor)

        # Process sequence 1
        result1 = asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )
        assert result1 == ProcessResult.PROCESSED

        # Process sequence 2
        result2 = asyncio.run(
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test duplicate callback detection."""
        processor = CallbackProcessor(mock_actor)

        # Process sequence 1
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Try to process sequence 1 again
        result = asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "duplicate"},
            )
        )

        assert result == ProcessResult.DUPLICATE

    def test_detect_old_sequence_as_duplicate(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that sequences lower than last_seq are duplicates."""
        processor = CallbackProcessor(mock_actor)

        # Process sequences 1, 2, 3
        for seq in [1, 2, 3]:
            asyncio.run(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )

        # Try sequence 2 again
        result = asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=2,
                data={"value": "old"},
            )
        )

        assert result == ProcessResult.DUPLICATE

    def test_gap_adds_to_pending(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that gaps add callbacks to pending queue."""
        processor = CallbackProcessor(mock_actor)

        # Process sequence 1
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Skip to sequence 3 (gap at 2)
        result = asyncio.run(
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that filling a gap processes pending callbacks."""
        processor = CallbackProcessor(mock_actor)
        processed_callbacks: list[int] = []

        async def track_handler(cb: ProcessedCallback) -> None:
            processed_callbacks.append(cb.sequence)

        # Process sequence 1
        await_result = asyncio.run
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test back-pressure when pending queue is full."""
        processor = CallbackProcessor(mock_actor, max_pending=3)

        # Process sequence 1
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Add sequences 3, 4, 5 to pending (gap at 2)
        for seq in [3, 4, 5]:
            result = asyncio.run(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )
            assert result == ProcessResult.PENDING

        # Try to add sequence 6 - should be rejected
        result = asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=6,
                data={"value": "seq6"},
            )
        )

        assert result == ProcessResult.REJECTED

    def test_pending_callbacks_sorted(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that pending callbacks are sorted by sequence."""
        processor = CallbackProcessor(mock_actor)

        # Process sequence 1
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Add out-of-order sequences to pending
        for seq in [5, 3, 4]:
            asyncio.run(
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that gap timeout triggers resync."""
        processor = CallbackProcessor(mock_actor, gap_timeout_seconds=0.1)

        # Process sequence 1
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "first"},
            )
        )

        # Add sequence 3 to pending (gap at 2)
        asyncio.run(
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
        result = asyncio.run(
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that resync callback resets state."""
        processor = CallbackProcessor(mock_actor)

        # Build up some state
        for seq in [1, 2, 3]:
            asyncio.run(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )

        # Add pending callbacks
        for seq in [5, 6]:
            asyncio.run(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=seq,
                    data={"value": f"seq{seq}"},
                )
            )

        # Process resync callback
        result = asyncio.run(
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that resync invokes handler with correct type."""
        processor = CallbackProcessor(mock_actor)
        received_callback: ProcessedCallback | None = None

        async def handler(cb: ProcessedCallback) -> None:
            nonlocal received_callback
            received_callback = cb

        asyncio.run(
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

    def test_version_conflict_retries(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],
    ) -> None:
        """A compare-and-swap lost to another writer (that changed the row but
        claimed nothing) is retried against the row as it is now."""
        _mock, storage = mock_attributes
        instance = _mock.return_value
        real = instance.conditional_update_attr.side_effect
        real_create = instance.create_attr_if_absent.side_effect
        lost = [0]

        def interfering_create(
            name: str | None = None, data: Any = None, **k: Any
        ) -> bool:
            if lost[0] < 2 and "state:" in str(name):
                lost[0] += 1
                # Another writer got there first with an unrelated change.
                storage[name or ""] = {
                    "data": {"version": 7 + lost[0], "resync_pending": False},
                    "timestamp": None,
                }
                return False
            return real_create(name=name, data=data, **k)

        def interfering_update(name: str | None = None, **k: Any) -> bool:
            if lost[0] < 2 and "state:" in str(name):
                lost[0] += 1
                row = storage[name or ""]["data"]
                storage[name or ""] = {
                    "data": {**row, "version": row["version"] + 1},
                    "timestamp": None,
                }
                return False
            return real(name=name, **k)

        instance.create_attr_if_absent.side_effect = interfering_create
        instance.conditional_update_attr.side_effect = interfering_update
        processor = CallbackProcessor(
            mock_actor, max_retries=3, retry_backoff_base=0.01
        )
        handled: list[int] = []

        async def handler(cb: ProcessedCallback) -> None:
            handled.append(cb.sequence)

        result = asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "test"},
                handler=handler,
            )
        )

        assert result == ProcessResult.PROCESSED
        assert lost[0] == 2
        assert handled == [1]


class TestCallbackProcessorClaim:
    """Two deliveries of one in-order callback run the handler once (3.16,
    owner-decided plan D13): the winner claims the batch in the state row."""

    def test_a_concurrent_delivery_of_a_claimed_sequence_is_a_duplicate(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        processor = CallbackProcessor(mock_actor, max_retries=3, retry_backoff_base=0)
        runs: list[int] = []
        inner: dict[str, Any] = {}

        async def handler(cb: ProcessedCallback) -> None:
            runs.append(cb.sequence)
            if len(runs) == 1:
                # While the winner's handler runs (the sequence not yet
                # recorded), the same callback is delivered again.
                inner["result"] = await processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=1,
                    data={"value": "x"},
                    handler=handler,
                )

        result = asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "x"},
                handler=handler,
            )
        )
        assert result == ProcessResult.PROCESSED
        assert inner["result"] == ProcessResult.DUPLICATE
        assert runs == [1]

    def test_two_identical_first_writes_have_one_winner(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        processor = CallbackProcessor(mock_actor)
        state = {"version": 1, "resync_pending": False, "claimed_seq": 1}
        first = processor._cas_state("peer1", "sub1", None, dict(state))  # pyright: ignore[reportPrivateUsage]
        second = processor._cas_state("peer1", "sub1", None, dict(state))  # pyright: ignore[reportPrivateUsage]
        assert first is not None
        assert second is None

    def test_a_retried_write_that_landed_counts_as_won(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],
    ) -> None:
        _mock, storage = mock_attributes
        instance = _mock.return_value
        real = instance.conditional_update_attr.side_effect

        def landed_but_answered_false(**k: Any) -> bool:
            real(**k)
            return False

        processor = CallbackProcessor(mock_actor)
        row = processor._cas_state(  # pyright: ignore[reportPrivateUsage]
            "peer1", "sub1", None, {"version": 1, "resync_pending": False}
        )
        assert row is not None
        instance.conditional_update_attr.side_effect = landed_but_answered_false
        won = processor._cas_state("peer1", "sub1", row, {"version": 2})  # pyright: ignore[reportPrivateUsage]
        assert won is not None
        assert storage["state:peer1:sub1"]["data"] == won

    def test_a_false_with_an_unchanged_row_is_a_fault(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],
    ) -> None:
        _mock, _storage = mock_attributes
        instance = _mock.return_value
        processor = CallbackProcessor(mock_actor)
        row = processor._cas_state(  # pyright: ignore[reportPrivateUsage]
            "peer1", "sub1", None, {"version": 1, "resync_pending": False}
        )
        assert row is not None
        instance.conditional_update_attr.side_effect = lambda **k: False
        with pytest.raises(DbError):
            processor._cas_state("peer1", "sub1", row, {"version": 2})  # pyright: ignore[reportPrivateUsage]

    def test_a_faulting_reread_raises(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],
    ) -> None:
        _mock, _storage = mock_attributes
        instance = _mock.return_value
        processor = CallbackProcessor(mock_actor)
        row = processor._cas_state(  # pyright: ignore[reportPrivateUsage]
            "peer1", "sub1", None, {"version": 1, "resync_pending": False}
        )
        assert row is not None
        instance.conditional_update_attr.side_effect = lambda **k: False
        instance.dbprop.get_attr_strict.side_effect = DbError("throttled")
        with pytest.raises(DbError):
            processor._cas_state("peer1", "sub1", row, {"version": 2})  # pyright: ignore[reportPrivateUsage]

    def test_a_db_error_in_the_handler_releases_the_claim(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        processor = CallbackProcessor(mock_actor, retry_backoff_base=0)
        attempts: list[int] = []

        async def handler(cb: ProcessedCallback) -> None:
            attempts.append(cb.sequence)
            if len(attempts) == 1:
                raise DbError("auto-storage write")

        with pytest.raises(DbError):
            asyncio.run(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=1,
                    data={},
                    handler=handler,
                )
            )
        # The redelivery the 503 asks for runs the handler again.
        result = asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={},
                handler=handler,
            )
        )
        assert result == ProcessResult.PROCESSED
        assert attempts == [1, 1]

    def test_a_resync_reset_grows_the_version_so_a_stale_cas_loses(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        processor = CallbackProcessor(mock_actor)
        row = processor._cas_state(  # pyright: ignore[reportPrivateUsage]
            "peer1", "sub1", None, {"version": 1, "resync_pending": True}
        )
        assert row is not None
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=5,
                data={},
                callback_type="resync",
            )
        )
        after = processor._read_state_row("peer1", "sub1")  # pyright: ignore[reportPrivateUsage]
        assert after is not None and after["version"] > row["version"]
        assert processor._cas_state("peer1", "sub1", row, {"version": 2}) is None  # pyright: ignore[reportPrivateUsage]

    def test_the_sync_twin_runs_the_handler_once(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        processor = CallbackProcessor(mock_actor, retry_backoff_base=0)
        runs: list[int] = []
        inner: dict[str, Any] = {}

        def handler(cb: ProcessedCallback) -> None:
            runs.append(cb.sequence)
            if len(runs) == 1:
                inner["result"] = processor.process_callback_sync(
                    peer_id="peer1",
                    subscription_id="sub1",
                    sequence=1,
                    data={},
                    handler=handler,
                )

        assert (
            processor.process_callback_sync(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={},
                handler=handler,
            )
            == ProcessResult.PROCESSED
        )
        assert inner["result"] == ProcessResult.DUPLICATE
        assert runs == [1]


class TestCallbackProcessorCleanup:
    """Test state cleanup functionality."""

    def test_clear_state_removes_subscription_data(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test clearing state for a subscription."""
        processor = CallbackProcessor(mock_actor)

        # Create some state
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "test"},
            )
        )

        # Add pending
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=3,
                data={"value": "pending"},
            )
        )

        # Clear state
        processor.clear_state("peer1", "sub1")

        # Callback state attributes should be cleared (pending queue empty)
        # Note: Subscription sequence is NOT reset because the subscription still exists
        # In practice, clear_state() is called right before subscription deletion
        state_info = processor.get_state_info("peer1", "sub1")
        assert state_info["pending_count"] == 0  # Pending queue cleared
        assert state_info["last_seq"] == 1  # Subscription sequence unchanged

    def test_clear_all_state_for_peer(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test clearing all state for a peer."""
        processor = CallbackProcessor(mock_actor)

        # Create state for multiple subscriptions
        for sub_id in ["sub1", "sub2", "sub3"]:
            asyncio.run(
                processor.process_callback(
                    peer_id="peer1",
                    subscription_id=sub_id,
                    sequence=1,
                    data={"value": "test"},
                )
            )

        # Create state for another peer
        asyncio.run(
            processor.process_callback(
                peer_id="peer2",
                subscription_id="sub1",
                sequence=1,
                data={"value": "test"},
            )
        )

        # Clear all state for peer1
        processor.clear_all_state_for_peer("peer1")

        # peer1 callback state attributes should be cleared
        # Note: Subscription sequences are NOT reset because subscriptions still exist in tests
        # In practice, clear_all_state_for_peer() is called after subscriptions are deleted
        for sub_id in ["sub1", "sub2", "sub3"]:
            state_info = processor.get_state_info("peer1", sub_id)
            assert state_info["pending_count"] == 0  # Pending queue cleared
            assert state_info["last_seq"] == 1  # Subscription sequence unchanged

        # peer2 state should remain untouched
        state_info = processor.get_state_info("peer2", "sub1")
        assert state_info["last_seq"] == 1
        assert state_info["pending_count"] == 0


class TestCallbackProcessorSyncVersion:
    """Test synchronous version of callback processing."""

    def test_sync_process_callback(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
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
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
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
        assert CallbackType.PERMISSION.value == "permission"


class TestPermissionCallbackProcessing:
    """Test permission callback handling."""

    def test_permission_callback_bypasses_sequencing(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that permission callbacks bypass sequence tracking."""
        processor = CallbackProcessor(mock_actor)

        # Process a permission callback with arbitrary sequence
        result = asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="",  # Permission callbacks don't use subscription_id
                sequence=0,  # Permission callbacks don't use sequence
                data={
                    "properties": {"patterns": ["memory_*"], "operations": ["read"]},
                    "methods": {"allowed": ["sync_*"], "denied": []},
                },
                callback_type="permission",
            )
        )

        assert result == ProcessResult.PROCESSED

    def test_permission_callback_invokes_handler(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that permission callbacks invoke handler with correct type."""
        processor = CallbackProcessor(mock_actor)
        received_callback: ProcessedCallback | None = None

        async def handler(cb: ProcessedCallback) -> None:
            nonlocal received_callback
            received_callback = cb

        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="",
                sequence=0,
                data={
                    "properties": {"patterns": ["*"], "operations": ["read", "write"]},
                },
                callback_type="permission",
                handler=handler,
            )
        )

        assert received_callback is not None
        assert received_callback.callback_type == CallbackType.PERMISSION
        assert received_callback.peer_id == "peer1"
        assert "properties" in received_callback.data

    def test_permission_callback_does_not_affect_subscription_state(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test that permission callbacks don't affect subscription state."""
        processor = CallbackProcessor(mock_actor)

        # Set up subscription state
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="sub1",
                sequence=1,
                data={"value": "test"},
            )
        )

        state_before = processor.get_state_info("peer1", "sub1")
        assert state_before["last_seq"] == 1

        # Process a permission callback
        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="",
                sequence=0,
                data={"properties": {"patterns": ["*"]}},
                callback_type="permission",
            )
        )

        # Subscription state should be unchanged
        state_after = processor.get_state_info("peer1", "sub1")
        assert state_after["last_seq"] == 1

    def test_permission_callback_sync_version(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test synchronous permission callback processing."""
        processor = CallbackProcessor(mock_actor)
        received_callback: ProcessedCallback | None = None

        def handler(cb: ProcessedCallback) -> None:
            nonlocal received_callback
            received_callback = cb

        result = processor.process_callback_sync(
            peer_id="peer1",
            subscription_id="",
            sequence=0,
            data={"tools": {"allowed": ["search"], "denied": []}},
            callback_type="permission",
            handler=handler,
        )

        assert result == ProcessResult.PROCESSED
        assert received_callback is not None
        assert received_callback.callback_type == CallbackType.PERMISSION

    def test_permission_callback_with_full_permission_structure(
        self,
        mock_actor: MagicMock,
        mock_subscription: tuple[MagicMock, dict[str, int]],  # noqa: ARG002
        mock_attributes: tuple[MagicMock, dict[str, Any]],  # noqa: ARG002
    ) -> None:
        """Test permission callback with complete permission structure."""
        processor = CallbackProcessor(mock_actor)
        received_callback: ProcessedCallback | None = None

        async def handler(cb: ProcessedCallback) -> None:
            nonlocal received_callback
            received_callback = cb

        permission_data = {
            "properties": {
                "patterns": ["memory_*", "profile/*"],
                "operations": ["read", "subscribe"],
                "excluded_patterns": ["memory_private_*"],
            },
            "methods": {"allowed": ["sync_*"], "denied": []},
            "actions": {"allowed": ["*"], "denied": ["delete_*"]},
            "tools": {"allowed": ["search", "fetch"], "denied": []},
            "resources": {"allowed": ["data://*"], "denied": []},
            "prompts": {"allowed": ["*"]},
        }

        asyncio.run(
            processor.process_callback(
                peer_id="peer1",
                subscription_id="",
                sequence=0,
                data=permission_data,
                callback_type="permission",
                handler=handler,
            )
        )

        assert received_callback is not None
        assert received_callback.data == permission_data
        assert received_callback.data["properties"]["patterns"] == [
            "memory_*",
            "profile/*",
        ]
        assert received_callback.data["tools"]["allowed"] == ["search", "fetch"]


class TestProcessResultEnum:
    """Test ProcessResult enum."""

    def test_process_result_values(self) -> None:
        """Test ProcessResult enum values."""
        assert ProcessResult.PROCESSED.value == "processed"
        assert ProcessResult.DUPLICATE.value == "duplicate"
        assert ProcessResult.PENDING.value == "pending"
        assert ProcessResult.RESYNC_TRIGGERED.value == "resync_triggered"
        assert ProcessResult.REJECTED.value == "rejected"
