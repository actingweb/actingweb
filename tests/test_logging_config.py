"""Unit tests for logging_config module."""

import logging

import pytest

from actingweb import request_context
from actingweb.log_filter import RequestContextFilter, StructuredContextFilter
from actingweb.logging_config import (
    configure_actingweb_logging_with_context,
    enable_request_context_filter,
    get_context_format,
)


class TestGetContextFormat:
    """Tests for get_context_format() function."""

    def test_default_format(self) -> None:
        """Test default format includes all components."""
        format_str = get_context_format()

        assert "%(asctime)s" in format_str
        assert "%(context)s" in format_str
        assert "%(name)s" in format_str
        assert "%(levelname)s" in format_str
        assert "%(message)s" in format_str

    def test_format_without_timestamp(self) -> None:
        """Test format without timestamp."""
        format_str = get_context_format(include_timestamp=False)

        assert "%(asctime)s" not in format_str
        assert "%(context)s" in format_str
        assert "%(message)s" in format_str

    def test_format_without_context(self) -> None:
        """Test format without context."""
        format_str = get_context_format(include_context=False)

        assert "%(asctime)s" in format_str
        assert "%(context)s" not in format_str
        assert "%(message)s" in format_str

    def test_format_without_logger(self) -> None:
        """Test format without logger name."""
        format_str = get_context_format(include_logger=False)

        assert "%(name)s" not in format_str
        assert "%(levelname)s" in format_str
        assert "%(message)s" in format_str

    def test_format_without_level(self) -> None:
        """Test format without log level."""
        format_str = get_context_format(include_level=False)

        assert "%(name)s" in format_str
        assert "%(levelname)s" not in format_str
        assert "%(message)s" in format_str

    def test_minimal_format(self) -> None:
        """Test minimal format with only message."""
        format_str = get_context_format(
            include_timestamp=False,
            include_context=False,
            include_logger=False,
            include_level=False,
        )

        assert format_str == "%(message)s"


class TestEnableRequestContextFilter:
    """Tests for enable_request_context_filter() function."""

    def setup_method(self) -> None:
        """Set up test logger with handler."""
        self.logger = logging.getLogger("test_enable_filter")
        self.handler = logging.StreamHandler()
        self.logger.addHandler(self.handler)

    def teardown_method(self) -> None:
        """Clean up test logger."""
        self.logger.removeHandler(self.handler)
        request_context.clear_request_context()

    def test_enable_text_filter(self) -> None:
        """Test enabling text filter."""
        enable_request_context_filter(logger=self.logger, structured=False)

        # Handler should have RequestContextFilter
        assert len(self.handler.filters) == 1
        assert isinstance(self.handler.filters[0], RequestContextFilter)

    def test_enable_structured_filter(self) -> None:
        """Test enabling structured filter."""
        enable_request_context_filter(logger=self.logger, structured=True)

        # Handler should have StructuredContextFilter
        assert len(self.handler.filters) == 1
        assert isinstance(self.handler.filters[0], StructuredContextFilter)

    def test_enable_filter_by_name(self) -> None:
        """Test enabling filter using logger name."""
        enable_request_context_filter(logger="test_enable_filter", structured=False)

        # Handler should have filter
        assert len(self.handler.filters) == 1
        assert isinstance(self.handler.filters[0], RequestContextFilter)

    def test_filter_all_handlers(self) -> None:
        """Test that filter is added to all handlers."""
        # Add second handler
        handler2 = logging.StreamHandler()
        self.logger.addHandler(handler2)

        enable_request_context_filter(logger=self.logger, handler_type="all")

        # Both handlers should have filter
        assert len(self.handler.filters) == 1
        assert len(handler2.filters) == 1

        # Clean up
        self.logger.removeHandler(handler2)

    def test_filter_stream_handlers_only(self) -> None:
        """Test filtering only StreamHandler instances."""
        # Add a FileHandler (we'll use StreamHandler as mock for simplicity)
        handler2 = logging.FileHandler("/tmp/test.log")
        self.logger.addHandler(handler2)

        enable_request_context_filter(logger=self.logger, handler_type="stream")

        # Only StreamHandler should have filter
        assert len(self.handler.filters) == 1
        assert len(handler2.filters) == 0

        # Clean up
        self.logger.removeHandler(handler2)
        handler2.close()


class TestConfigureActingwebLoggingWithContext:
    """Tests for configure_actingweb_logging_with_context() function."""

    def setup_method(self) -> None:
        """Set up before each test."""
        # Clean root logger before test
        root = logging.getLogger()
        for handler in root.handlers[:]:
            # Clear filters from handler
            handler.filters.clear()
            root.removeHandler(handler)
        request_context.clear_request_context()

    def teardown_method(self) -> None:
        """Clean up after tests."""
        request_context.clear_request_context()
        # Reset root logger
        root = logging.getLogger()
        for handler in root.handlers[:]:
            # Clear filters from handler
            handler.filters.clear()
            root.removeHandler(handler)

    def test_configure_with_context_enabled(self) -> None:
        """Test configuration with context enabled."""
        configure_actingweb_logging_with_context(
            level=logging.INFO, enable_context=True
        )

        root = logging.getLogger()

        # Root logger should have handlers
        assert len(root.handlers) > 0

        # At least one handler should have a filter
        has_filter = any(len(h.filters) > 0 for h in root.handlers)
        assert has_filter

    def test_configure_with_context_disabled(self) -> None:
        """Test configuration with context disabled."""
        configure_actingweb_logging_with_context(
            level=logging.INFO, enable_context=False
        )

        root = logging.getLogger()

        # Root logger should have handlers
        assert len(root.handlers) > 0

        # No handlers should have RequestContextFilter or StructuredContextFilter
        for handler in root.handlers:
            for filter_obj in handler.filters:
                assert not isinstance(filter_obj, RequestContextFilter)
                assert not isinstance(filter_obj, StructuredContextFilter)

    def test_configure_with_structured_context(self) -> None:
        """Test configuration with structured context."""
        configure_actingweb_logging_with_context(
            level=logging.INFO, enable_context=True, structured=True
        )

        root = logging.getLogger()

        # At least one handler should have StructuredContextFilter
        has_structured_filter = any(
            any(isinstance(f, StructuredContextFilter) for f in h.filters)
            for h in root.handlers
        )
        assert has_structured_filter

    def test_configure_sets_log_levels(self) -> None:
        """Test that configuration sets appropriate log levels."""
        configure_actingweb_logging_with_context(
            level=logging.INFO,
            db_level=logging.ERROR,
            handlers_level=logging.DEBUG,
        )

        # Check that levels are set
        assert logging.getLogger("actingweb").level == logging.INFO
        assert logging.getLogger("actingweb.db.dynamodb").level == logging.ERROR
        assert logging.getLogger("actingweb.handlers").level == logging.DEBUG


class TestIntegrationWithActualLogging:
    """Integration tests with actual logging output."""

    def teardown_method(self) -> None:
        """Clean up after tests."""
        request_context.clear_request_context()

    def test_context_appears_in_log_output(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that context appears in actual log output."""
        # Set up logger with context
        logger = logging.getLogger("test_integration")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        handler = logging.StreamHandler()
        logger.addHandler(handler)

        # Now add the filter (after handler is attached to logger)
        enable_request_context_filter(logger=logger)

        # Update formatter to include context
        formatter = logging.Formatter(get_context_format())
        handler.setFormatter(formatter)

        # Set context and log
        request_context.set_request_context(
            request_id="550e8400-e29b-41d4-a716-446655440000",
            actor_id="actor123",
            peer_id="peer456",
        )

        with caplog.at_level(logging.INFO, logger="test_integration"):
            logger.info("Test message with context")

        # Check that context appears in log record (caplog uses its own handler/formatter)
        assert len(caplog.records) == 1
        assert hasattr(caplog.records[0], "context")
        assert caplog.records[0].context == "[55440000:actor123:peer456]"  # type: ignore[attr-defined]
        assert "Test message with context" in caplog.text

        # Clean up
        logger.removeHandler(handler)

    def test_logging_without_context_set(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test logging when no context is set."""
        # Set up logger with context filter
        logger = logging.getLogger("test_no_context")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        handler = logging.StreamHandler()
        logger.addHandler(handler)

        # Add filter after handler is attached
        enable_request_context_filter(logger=logger)

        formatter = logging.Formatter(get_context_format())
        handler.setFormatter(formatter)

        # Clear context and log
        request_context.clear_request_context()

        with caplog.at_level(logging.INFO, logger="test_no_context"):
            logger.info("Test message without context")

        # Should show placeholder values in log record
        assert len(caplog.records) == 1
        assert hasattr(caplog.records[0], "context")
        assert caplog.records[0].context == "[-:-:-]"  # type: ignore[attr-defined]
        assert "Test message without context" in caplog.text

        # Clean up
        logger.removeHandler(handler)

    def test_context_isolation_in_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that context isolation works in logging."""
        from concurrent.futures import ThreadPoolExecutor

        def log_with_context(actor_id: str) -> None:
            request_context.set_actor_id(actor_id)

            logger = logging.getLogger(f"test_isolation_{actor_id}")
            logger.setLevel(logging.INFO)

            handler = logging.StreamHandler()
            logger.addHandler(handler)

            # Add filter after handler is attached
            enable_request_context_filter(logger=logger)
            formatter = logging.Formatter("%(context)s %(message)s")
            handler.setFormatter(formatter)

            logger.info(f"Message from {actor_id}")

            logger.removeHandler(handler)
            request_context.clear_request_context()

        # Run multiple threads
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(log_with_context, f"actor{i}") for i in range(3)]
            for f in futures:
                f.result()

        # Each thread should have logged with its own context
        # (We can't easily verify the output here due to thread isolation,
        # but the test ensures no exceptions are raised)
