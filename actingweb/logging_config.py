"""Centralized logging configuration for ActingWeb.

This module provides utilities for configuring logging across the ActingWeb
framework with sensible defaults for different environments.
"""

import logging


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
