"""Unit tests for log_filter module."""

import logging

import pytest

from actingweb import request_context
from actingweb.log_filter import (
    RequestContextFilter,
    StructuredContextFilter,
    add_context_filter_to_handler,
    add_context_filter_to_logger,
)


class TestRequestContextFilter:
    """Tests for RequestContextFilter."""

    def test_filter_adds_context_attribute(self) -> None:
        """Test that filter adds context attribute to log record."""
        # Set up context
        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000",
            actor_id="actor123",
            peer_id="peer456",
        )

        # Create a log record
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Apply filter
        filter_obj = RequestContextFilter()
        result = filter_obj.filter(record)

        # Filter should return True (don't filter out)
        assert result is True

        # Record should have context attribute
        assert hasattr(record, "context")
        assert record.context == "[55440000:actor123:peer456]"  # type: ignore[attr-defined]

        request_context.clear_request_context()

    def test_filter_with_no_context(self) -> None:
        """Test that filter works when no context is set."""
        request_context.clear_request_context()

        # Create a log record
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Apply filter
        filter_obj = RequestContextFilter()
        result = filter_obj.filter(record)

        assert result is True
        assert record.context == "[-:-:-]"  # type: ignore[attr-defined]

    def test_filter_in_actual_logging(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test filter integration with actual logging."""
        # Set up logger with filter
        logger = logging.getLogger("test_actual")
        logger.setLevel(logging.INFO)

        # Clear any existing handlers
        logger.handlers.clear()

        # Add handler with filter and formatter
        handler = logging.StreamHandler()
        handler.addFilter(RequestContextFilter())
        formatter = logging.Formatter("%(context)s %(name)s: %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # Set context and log
        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000", actor_id="actor123"
        )

        with caplog.at_level(logging.INFO, logger="test_actual"):
            logger.info("Test message")

        # Check that context appears in log record (caplog uses its own handler)
        assert len(caplog.records) == 1
        assert hasattr(caplog.records[0], "context")
        # The context attribute should have the correct value
        assert caplog.records[0].context == "[55440000:actor123:-]"  # type: ignore[attr-defined]

        # Clean up
        logger.removeHandler(handler)
        request_context.clear_request_context()


class TestStructuredContextFilter:
    """Tests for StructuredContextFilter."""

    def test_filter_adds_separate_fields(self) -> None:
        """Test that filter adds separate context fields to log record."""
        # Set up context
        test_id = "550e8400-e29b-41d4-a716-446655440000"
        request_context.set_request_context(
            request_id=test_id, actor_id="actor123", peer_id="peer456"
        )

        # Create a log record
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Apply filter
        filter_obj = StructuredContextFilter()
        result = filter_obj.filter(record)

        # Filter should return True (don't filter out)
        assert result is True

        # Record should have separate context fields
        assert hasattr(record, "request_id")
        assert hasattr(record, "actor_id")
        assert hasattr(record, "peer_id")

        assert record.request_id == test_id  # type: ignore[attr-defined]
        assert record.actor_id == "actor123"  # type: ignore[attr-defined]
        assert record.peer_id == "peer456"  # type: ignore[attr-defined]

        request_context.clear_request_context()

    def test_filter_with_no_context(self) -> None:
        """Test that filter works when no context is set."""
        request_context.clear_request_context()

        # Create a log record
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Apply filter
        filter_obj = StructuredContextFilter()
        result = filter_obj.filter(record)

        assert result is True
        assert record.request_id is None  # type: ignore[attr-defined]
        assert record.actor_id is None  # type: ignore[attr-defined]
        assert record.peer_id is None  # type: ignore[attr-defined]


class TestAddContextFilterToHandler:
    """Tests for add_context_filter_to_handler() function."""

    def test_add_text_filter(self) -> None:
        """Test adding text filter to handler."""
        handler = logging.StreamHandler()

        add_context_filter_to_handler(handler, structured=False)

        # Should have RequestContextFilter
        assert len(handler.filters) == 1
        assert isinstance(handler.filters[0], RequestContextFilter)

    def test_add_structured_filter(self) -> None:
        """Test adding structured filter to handler."""
        handler = logging.StreamHandler()

        add_context_filter_to_handler(handler, structured=True)

        # Should have StructuredContextFilter
        assert len(handler.filters) == 1
        assert isinstance(handler.filters[0], StructuredContextFilter)


class TestAddContextFilterToLogger:
    """Tests for add_context_filter_to_logger() function."""

    def test_add_filter_by_name(self) -> None:
        """Test adding filter to logger by name."""
        # Set up logger with handler
        logger = logging.getLogger("test_by_name")
        handler = logging.StreamHandler()
        logger.addHandler(handler)

        # Add filter
        add_context_filter_to_logger("test_by_name", structured=False)

        # Handler should have filter
        assert len(handler.filters) == 1
        assert isinstance(handler.filters[0], RequestContextFilter)

        # Clean up
        logger.removeHandler(handler)

    def test_add_filter_by_object(self) -> None:
        """Test adding filter to logger by object."""
        # Set up logger with handler
        logger = logging.getLogger("test_by_object")
        handler = logging.StreamHandler()
        logger.addHandler(handler)

        # Add filter
        add_context_filter_to_logger(logger, structured=False)

        # Handler should have filter
        assert len(handler.filters) == 1
        assert isinstance(handler.filters[0], RequestContextFilter)

        # Clean up
        logger.removeHandler(handler)

    def test_add_filter_to_multiple_handlers(self) -> None:
        """Test adding filter to logger with multiple handlers."""
        # Set up logger with multiple handlers
        logger = logging.getLogger("test_multiple")
        handler1 = logging.StreamHandler()
        handler2 = logging.StreamHandler()
        logger.addHandler(handler1)
        logger.addHandler(handler2)

        # Add filter
        add_context_filter_to_logger(logger, structured=False)

        # Both handlers should have filter
        assert len(handler1.filters) == 1
        assert len(handler2.filters) == 1
        assert isinstance(handler1.filters[0], RequestContextFilter)
        assert isinstance(handler2.filters[0], RequestContextFilter)

        # Clean up
        logger.removeHandler(handler1)
        logger.removeHandler(handler2)


class TestFilterPerformance:
    """Performance tests for log filters."""

    def test_request_context_filter_performance(self) -> None:
        """Test that RequestContextFilter has minimal overhead."""
        import time

        # Set up context
        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000",
            actor_id="actor123",
            peer_id="peer456",
        )

        # Create filter and record
        filter_obj = RequestContextFilter()
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Time filter operations
        iterations = 10000
        start = time.perf_counter()

        for _ in range(iterations):
            filter_obj.filter(record)

        elapsed = time.perf_counter() - start
        per_call = (elapsed / iterations) * 1_000_000  # Convert to microseconds

        # Should be under 20 microseconds per call (relaxed for CI variability)
        assert per_call < 20.0, (
            f"RequestContextFilter.filter() took {per_call:.2f}µs per call (expected <20µs)"
        )

        request_context.clear_request_context()

    def test_structured_context_filter_performance(self) -> None:
        """Test that StructuredContextFilter has minimal overhead."""
        import time

        # Set up context
        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000",
            actor_id="actor123",
            peer_id="peer456",
        )

        # Create filter and record
        filter_obj = StructuredContextFilter()
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            name="test",
            level=logging.INFO,
            fn="test.py",
            lno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        # Time filter operations
        iterations = 10000
        start = time.perf_counter()

        for _ in range(iterations):
            filter_obj.filter(record)

        elapsed = time.perf_counter() - start
        per_call = (elapsed / iterations) * 1_000_000  # Convert to microseconds

        # Should be under 20 microseconds per call (relaxed for CI variability)
        assert per_call < 20.0, (
            f"StructuredContextFilter.filter() took {per_call:.2f}µs per call (expected <20µs)"
        )

        request_context.clear_request_context()


class TestFilterWithConcurrency:
    """Test filters with concurrent logging."""

    @pytest.mark.asyncio
    async def test_filter_with_async_logging(self) -> None:
        """Test that filter works correctly with async logging."""
        import asyncio

        async def log_with_context(actor_id: str, messages: list[str]) -> None:
            request_context.set_actor_id(actor_id)

            logger = logging.getLogger(f"test_async_{actor_id}")
            handler = logging.StreamHandler()
            handler.addFilter(RequestContextFilter())
            logger.addHandler(handler)

            for msg in messages:
                logger.info(msg)
                await asyncio.sleep(0.001)

            # Verify context is still correct
            assert request_context.get_actor_id() == actor_id

            logger.removeHandler(handler)
            request_context.clear_request_context()

        # Run multiple tasks concurrently
        await asyncio.gather(
            log_with_context("actor1", ["msg1", "msg2"]),
            log_with_context("actor2", ["msg3", "msg4"]),
            log_with_context("actor3", ["msg5", "msg6"]),
        )
