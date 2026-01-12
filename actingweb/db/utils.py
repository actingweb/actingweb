"""Database utility functions shared across backends."""

from datetime import UTC, datetime


def ensure_timezone_aware_iso(dt: datetime) -> str:
    """
    Convert datetime to ISO string, ensuring UTC timezone if none exists.

    Args:
        dt: datetime object to convert

    Returns:
        ISO 8601 formatted string with timezone information

    Example:
        >>> from datetime import datetime
        >>> dt = datetime(2024, 1, 15, 10, 30)
        >>> ensure_timezone_aware_iso(dt)
        '2024-01-15T10:30:00+00:00'
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()
