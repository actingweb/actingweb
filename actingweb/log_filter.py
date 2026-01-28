"""Logging filters for request context injection.

This module provides logging.Filter classes that automatically inject request
context (request ID, actor ID, peer ID) into log records, enabling correlation
and filtering without modifying existing log statements.
"""

import logging

from actingweb import request_context


class RequestContextFilter(logging.Filter):
    """
    Logging filter that injects request context into log records.

    This filter adds a 'context' attribute to each LogRecord containing
    formatted context information. The context includes:
    - Request ID (short form, last 8 chars)
    - Actor ID (full)
    - Peer ID (short form, last segment after colon)

    The context is formatted as: [req_id:actor_id:peer_id]
    Missing values are represented as "-"

    Usage:
        >>> import logging
        >>> from actingweb.log_filter import RequestContextFilter
        >>> from actingweb.request_context import set_request_context
        >>>
        >>> # Set up logger with filter
        >>> logger = logging.getLogger("myapp")
        >>> handler = logging.StreamHandler()
        >>> handler.addFilter(RequestContextFilter())
        >>> formatter = logging.Formatter(
        ...     "%(asctime)s %(context)s %(name)s:%(levelname)s: %(message)s"
        ... )
        >>> handler.setFormatter(formatter)
        >>> logger.addHandler(handler)
        >>>
        >>> # Context automatically appears in logs
        >>> set_request_context(actor_id="actor123")
        >>> logger.info("Processing request")
        # Output: 2024-01-15 10:23:45,123 [a1b2c3d4:actor123:-] myapp:INFO: Processing request

    Attributes:
        None - all state comes from contextvars in request_context module
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add context to the log record.

        This method is called by the logging framework for each log record.
        It adds a 'context' attribute containing the formatted context string.

        Args:
            record: The LogRecord to process

        Returns:
            Always True (record is never filtered out)
        """
        # Add formatted context to record
        record.context = request_context.format_context_compact()  # type: ignore[attr-defined]
        return True


class StructuredContextFilter(logging.Filter):
    """
    Logging filter that injects request context as separate fields.

    This filter is designed for structured logging (JSON) where context
    values should be separate fields rather than a formatted string.

    The filter adds these attributes to each LogRecord:
    - request_id: Full request ID (UUID)
    - actor_id: Actor ID
    - peer_id: Peer ID

    Values are None if not set in current context.

    Usage:
        >>> import logging
        >>> import json
        >>> from actingweb.log_filter import StructuredContextFilter
        >>> from actingweb.request_context import set_request_context
        >>>
        >>> # Set up logger with filter for JSON output
        >>> logger = logging.getLogger("myapp")
        >>> handler = logging.StreamHandler()
        >>> handler.addFilter(StructuredContextFilter())
        >>>
        >>> # Custom JSON formatter (simplified example)
        >>> class JsonFormatter(logging.Formatter):
        ...     def format(self, record):
        ...         return json.dumps({
        ...             "timestamp": record.created,
        ...             "level": record.levelname,
        ...             "logger": record.name,
        ...             "message": record.getMessage(),
        ...             "request_id": getattr(record, "request_id", None),
        ...             "actor_id": getattr(record, "actor_id", None),
        ...             "peer_id": getattr(record, "peer_id", None),
        ...         })
        >>>
        >>> handler.setFormatter(JsonFormatter())
        >>> logger.addHandler(handler)
        >>>
        >>> # Context automatically included in JSON
        >>> set_request_context(actor_id="actor123")
        >>> logger.info("Processing request")
        # Output: {"timestamp": 1234567890.123, "level": "INFO", ...}

    Attributes:
        None - all state comes from contextvars in request_context module
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add context fields to the log record.

        This method is called by the logging framework for each log record.
        It adds separate attributes for each context field.

        Args:
            record: The LogRecord to process

        Returns:
            Always True (record is never filtered out)
        """
        # Get context as dictionary
        context = request_context.get_context_dict()

        # Add each field as a separate attribute
        record.request_id = context["request_id"]  # type: ignore[attr-defined]
        record.actor_id = context["actor_id"]  # type: ignore[attr-defined]
        record.peer_id = context["peer_id"]  # type: ignore[attr-defined]

        return True


def add_context_filter_to_handler(
    handler: logging.Handler, *, structured: bool = False
) -> None:
    """
    Add a request context filter to a logging handler.

    This is a convenience function for adding the appropriate filter type
    to an existing handler.

    Args:
        handler: The logging handler to add the filter to
        structured: If True, use StructuredContextFilter for JSON logging;
                   if False, use RequestContextFilter for text logging

    Example:
        >>> import logging
        >>> handler = logging.StreamHandler()
        >>> add_context_filter_to_handler(handler)
        >>> # Handler now has RequestContextFilter attached
    """
    filter_class = StructuredContextFilter if structured else RequestContextFilter
    handler.addFilter(filter_class())


def add_context_filter_to_logger(
    logger: logging.Logger | str, *, structured: bool = False
) -> None:
    """
    Add a request context filter to all handlers of a logger.

    This is a convenience function for adding filters to an existing logger's
    handlers. It's useful for adding context to loggers that are already
    configured.

    Args:
        logger: The logger (or logger name) to add filters to
        structured: If True, use StructuredContextFilter for JSON logging;
                   if False, use RequestContextFilter for text logging

    Example:
        >>> import logging
        >>> logging.basicConfig()  # Set up basic logging
        >>> add_context_filter_to_logger("actingweb")
        >>> # All actingweb loggers now include request context
    """
    if isinstance(logger, str):
        logger = logging.getLogger(logger)

    filter_class = StructuredContextFilter if structured else RequestContextFilter
    for handler in logger.handlers:
        handler.addFilter(filter_class())
