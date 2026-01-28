"""Centralized logging configuration for ActingWeb.

This module provides utilities for configuring logging across the ActingWeb
framework with sensible defaults for different environments.
"""

import logging
from typing import Literal


def configure_actingweb_logging(
    level: int = logging.INFO,
    *,
    db_level: int | None = None,
    handlers_level: int | None = None,
    interface_level: int | None = None,
    oauth_level: int | None = None,
    mcp_level: int | None = None,
) -> None:
    """
    Configure ActingWeb logging with sensible defaults.

    This function sets up hierarchical logging for different ActingWeb subsystems,
    allowing fine-grained control over verbosity in different parts of the framework.

    Args:
        level: Default level for all actingweb loggers (default: INFO)
        db_level: Override for database operations (default: WARNING to reduce noise)
        handlers_level: Override for HTTP handlers (default: uses main level)
        interface_level: Override for interface layer (default: uses main level)
        oauth_level: Override for OAuth2 components (default: uses main level)
        mcp_level: Override for MCP protocol (default: uses main level)

    Example:
        Development setup (verbose):
            >>> import logging
            >>> from actingweb.logging_config import configure_actingweb_logging
            >>> configure_actingweb_logging(logging.DEBUG)

        Production setup (quiet DB, normal handlers):
            >>> configure_actingweb_logging(
            ...     level=logging.WARNING,
            ...     handlers_level=logging.INFO,
            ...     db_level=logging.ERROR,
            ... )

        Testing setup (only errors):
            >>> configure_actingweb_logging(logging.ERROR)
    """
    # Set root actingweb logger
    actingweb_logger = logging.getLogger("actingweb")
    actingweb_logger.setLevel(level)

    # Configure subsystems with specific levels or defaults
    if db_level is not None:
        logging.getLogger("actingweb.db.dynamodb").setLevel(db_level)
    else:
        # DB operations are typically noisy in debug mode, default to WARNING
        # unless the main level is ERROR (then keep it at ERROR)
        logging.getLogger("actingweb.db.dynamodb").setLevel(
            max(level, logging.WARNING) if level < logging.ERROR else level
        )

    if handlers_level is not None:
        logging.getLogger("actingweb.handlers").setLevel(handlers_level)

    if interface_level is not None:
        logging.getLogger("actingweb.interface").setLevel(interface_level)

    if oauth_level is not None:
        logging.getLogger("actingweb.oauth2_server").setLevel(oauth_level)

    if mcp_level is not None:
        logging.getLogger("actingweb.mcp").setLevel(mcp_level)

    # Silence noisy third-party libraries
    _configure_third_party_loggers()


def _configure_third_party_loggers() -> None:
    """Configure third-party library loggers to reduce noise.

    Sets common third-party libraries to WARNING level to prevent
    excessive debug output from cluttering logs.
    """
    noisy_libraries = [
        "pynamodb",
        "botocore",
        "boto3",
        "urllib3",
        "urllib3.connectionpool",
        "requests",
        "httpx",
    ]

    for library in noisy_libraries:
        logging.getLogger(library).setLevel(logging.WARNING)


def get_performance_critical_loggers() -> list[str]:
    """
    Return list of loggers that should be WARNING+ in production.

    These loggers are in hot paths and excessive logging impacts performance.
    Use this to configure production environments where performance is critical.

    Returns:
        List of logger names that are performance-sensitive

    Example:
        >>> for logger_name in get_performance_critical_loggers():
        ...     logging.getLogger(logger_name).setLevel(logging.WARNING)
    """
    return [
        "actingweb.db.dynamodb",  # Database operations - every request
        "actingweb.auth",  # Authentication - every request
        "actingweb.handlers.properties",  # Frequent property access
        "actingweb.aw_proxy",  # Peer communication - can be chatty
        "actingweb.permission_evaluator",  # Called frequently for access control
    ]


def configure_production_logging(
    *,
    http_traffic: bool = True,
    lifecycle_events: bool = True,
) -> None:
    """
    Configure logging for production environments with performance focus.

    This is an opinionated production configuration that balances
    observability with performance.

    Args:
        http_traffic: If True, log HTTP request handling at INFO level
        lifecycle_events: If True, log actor lifecycle events at INFO level

    Example:
        >>> configure_production_logging()
        >>> # HTTP traffic and lifecycle events logged, everything else quiet
    """
    # Base level: only warnings and errors
    configure_actingweb_logging(
        level=logging.WARNING,
        handlers_level=logging.INFO if http_traffic else logging.WARNING,
        interface_level=logging.INFO if lifecycle_events else logging.WARNING,
        db_level=logging.ERROR,  # DB errors only
        oauth_level=logging.WARNING,
        mcp_level=logging.WARNING,
    )


def configure_development_logging(*, verbose: bool = False) -> None:
    """
    Configure logging for development environments.

    Args:
        verbose: If True, enable DEBUG logging everywhere (default: False)

    Example:
        >>> configure_development_logging()  # INFO level
        >>> configure_development_logging(verbose=True)  # DEBUG level
    """
    level = logging.DEBUG if verbose else logging.INFO

    configure_actingweb_logging(
        level=level,
        # Even in dev, DB can be noisy at DEBUG
        db_level=logging.INFO if verbose else logging.WARNING,
    )


def configure_testing_logging(*, debug: bool = False) -> None:
    """
    Configure logging for test environments.

    By default, only shows errors during tests to keep output clean.
    Can be overridden with debug=True for troubleshooting.

    Args:
        debug: If True, show all DEBUG logs (default: False)

    Example:
        >>> import os
        >>> # Enable debug logging with environment variable
        >>> debug_tests = os.getenv("ACTINGWEB_DEBUG") == "1"
        >>> configure_testing_logging(debug=debug_tests)
    """
    if debug:
        configure_development_logging(verbose=True)
    else:
        # Quiet by default - only errors
        configure_actingweb_logging(logging.ERROR)


def get_context_format(
    *,
    include_timestamp: bool = True,
    include_context: bool = True,
    include_logger: bool = True,
    include_level: bool = True,
) -> str:
    """
    Generate a log format string with optional request context.

    This function creates format strings suitable for use with logging.Formatter.
    When include_context is True, the format includes a %(context)s placeholder
    that will be populated by RequestContextFilter.

    Args:
        include_timestamp: Include timestamp in format (default: True)
        include_context: Include request context placeholder (default: True)
        include_logger: Include logger name (default: True)
        include_level: Include log level (default: True)

    Returns:
        A format string suitable for logging.Formatter

    Example:
        >>> get_context_format()
        '%(asctime)s %(context)s %(name)s:%(levelname)s: %(message)s'
        >>> get_context_format(include_timestamp=False, include_context=False)
        '%(name)s:%(levelname)s: %(message)s'
    """
    parts = []

    if include_timestamp:
        parts.append("%(asctime)s")

    if include_context:
        parts.append("%(context)s")

    logger_level = []
    if include_logger:
        logger_level.append("%(name)s")
    if include_level:
        logger_level.append("%(levelname)s")

    if logger_level:
        parts.append(":".join(logger_level))

    parts.append("%(message)s")

    return " ".join(parts)


def enable_request_context_filter(
    *,
    logger: str | logging.Logger = "actingweb",
    structured: bool = False,
    handler_type: Literal["all", "stream", "file"] = "all",
) -> None:
    """
    Enable request context injection for ActingWeb loggers.

    This function adds RequestContextFilter to existing logging handlers,
    enabling automatic injection of request context (request ID, actor ID,
    peer ID) into log records.

    After enabling the filter, you should update log formats to include
    the %(context)s placeholder:

        formatter = logging.Formatter(get_context_format())
        handler.setFormatter(formatter)

    Args:
        logger: Logger name or Logger object to add filters to (default: "actingweb")
        structured: If True, use StructuredContextFilter for JSON logging;
                   if False, use RequestContextFilter for text logging
        handler_type: Which handlers to add filter to:
                     - "all": Add to all handlers
                     - "stream": Add only to StreamHandler instances
                     - "file": Add only to FileHandler instances

    Example:
        Text logging with context:
            >>> import logging
            >>> from actingweb.logging_config import (
            ...     configure_actingweb_logging,
            ...     enable_request_context_filter,
            ...     get_context_format,
            ... )
            >>> configure_actingweb_logging(logging.INFO)
            >>> enable_request_context_filter()
            >>> # Update format to include context
            >>> for handler in logging.getLogger("actingweb").handlers:
            ...     formatter = logging.Formatter(get_context_format())
            ...     handler.setFormatter(formatter)

        JSON logging with structured context:
            >>> enable_request_context_filter(structured=True)
            >>> # Use custom JSON formatter that accesses record.request_id, etc.
    """
    from actingweb.log_filter import (
        RequestContextFilter,
        StructuredContextFilter,
    )

    if isinstance(logger, str):
        logger = logging.getLogger(logger)

    filter_class = StructuredContextFilter if structured else RequestContextFilter

    for handler in logger.handlers:
        # Filter by handler type if requested
        # Note: Use type() for exact match since FileHandler inherits from StreamHandler
        if handler_type == "stream" and type(handler) is not logging.StreamHandler:
            continue
        if handler_type == "file" and not isinstance(handler, logging.FileHandler):
            continue

        handler.addFilter(filter_class())


def configure_actingweb_logging_with_context(
    level: int = logging.INFO,
    *,
    db_level: int | None = None,
    handlers_level: int | None = None,
    interface_level: int | None = None,
    oauth_level: int | None = None,
    mcp_level: int | None = None,
    enable_context: bool = True,
    structured: bool = False,
) -> None:
    """
    Configure ActingWeb logging with request context support.

    This is a convenience function that combines configure_actingweb_logging()
    with enable_request_context_filter() and format configuration.

    Args:
        level: Default level for all actingweb loggers (default: INFO)
        db_level: Override for database operations (default: WARNING)
        handlers_level: Override for HTTP handlers (default: uses main level)
        interface_level: Override for interface layer (default: uses main level)
        oauth_level: Override for OAuth2 components (default: uses main level)
        mcp_level: Override for MCP protocol (default: uses main level)
        enable_context: If True, enable request context injection (default: True)
        structured: If True, use structured context for JSON logging (default: False)

    Example:
        Development with context:
            >>> import logging
            >>> configure_actingweb_logging_with_context(logging.DEBUG)

        Production with context:
            >>> configure_actingweb_logging_with_context(
            ...     level=logging.WARNING,
            ...     handlers_level=logging.INFO,
            ...     db_level=logging.ERROR,
            ... )

        Disable context:
            >>> configure_actingweb_logging_with_context(
            ...     level=logging.INFO,
            ...     enable_context=False,
            ... )
    """
    # First configure basic logging
    configure_actingweb_logging(
        level=level,
        db_level=db_level,
        handlers_level=handlers_level,
        interface_level=interface_level,
        oauth_level=oauth_level,
        mcp_level=mcp_level,
    )

    # Set up root handler if none exists
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            get_context_format()
            if enable_context
            else get_context_format(include_context=False)
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Enable context if requested
    if enable_context:
        # Add filter to root logger (covers all actingweb loggers)
        enable_request_context_filter(
            logger=root_logger, structured=structured, handler_type="all"
        )

        # Update formatters to include context
        for handler in root_logger.handlers:
            if not structured:
                # For text logging, update format to include %(context)s
                current_format = handler.formatter._fmt if handler.formatter else None  # type: ignore[attr-defined]
                if current_format and "%(context)s" not in current_format:
                    # Use default context format
                    handler.setFormatter(logging.Formatter(get_context_format()))
