"""Database utility functions shared across backends."""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


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


def sanitize_json_data(data: Any, *, log_source: str = "") -> Any:
    """
    Recursively sanitize data to ensure valid UTF-8 and JSON encoding.

    Removes Unicode surrogate characters (invalid UTF-16 pairs) and other
    problematic characters that break JSON encoding. This is critical for
    handling untrusted data from remote peers.

    Args:
        data: Data to sanitize (dict, list, str, or primitive)
        log_source: Optional source identifier for logging (e.g., "peer:abc123")

    Returns:
        Sanitized copy of data safe for JSON encoding

    Example:
        >>> # String with surrogate characters
        >>> bad_str = "test\\uD800data"
        >>> sanitize_json_data(bad_str)
        'test\ufffddata'  # Surrogate replaced with replacement character
    """

    if isinstance(data, str):
        try:
            # Attempt to encode/decode to detect surrogates
            data.encode("utf-8", errors="strict")
            return data
        except UnicodeEncodeError:
            # Replace surrogates and other invalid characters
            sanitized = data.encode("utf-8", errors="replace").decode(
                "utf-8", errors="replace"
            )
            if log_source:
                logger.warning(
                    f"Sanitized invalid Unicode in string from {log_source}: "
                    f"replaced {len(data) - len(sanitized.encode('utf-8'))} bytes"
                )
            return sanitized

    elif isinstance(data, dict):
        sanitized_dict = {}
        for key, value in data.items():
            # Sanitize both key and value
            sanitized_key = sanitize_json_data(key, log_source=log_source)
            sanitized_value = sanitize_json_data(value, log_source=log_source)
            sanitized_dict[sanitized_key] = sanitized_value
        return sanitized_dict

    elif isinstance(data, list):
        sanitized_list = [
            sanitize_json_data(item, log_source=log_source) for item in data
        ]
        return sanitized_list

    elif isinstance(data, tuple):
        # Preserve tuples (though rare in JSON)
        return tuple(sanitize_json_data(item, log_source=log_source) for item in data)

    else:
        # Primitives (int, float, bool, None) pass through unchanged
        return data
