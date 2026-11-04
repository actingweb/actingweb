"""Argument checks shared by the database backends (internal)."""

from typing import Any


def check_subscription_callback(callback: Any, *, modifying: bool) -> None:
    """Refuse a non-bool subscription ``callback`` before any I/O.

    It is a boolean column on both backends: PynamoDB stored any truthy
    value (a URL) as ``True`` and PostgreSQL failed the cast as a store
    fault. A mistyped call is a programming error, so it raises
    ``TypeError``, never ``DbError``; the message names the type, never the
    value (on the path that hit it the value was a URL).
    """
    if modifying and callback is None:
        return
    if isinstance(callback, bool):
        return
    raise TypeError(
        f"subscription callback must be a bool{' or None' if modifying else ''}, "
        f"not {type(callback).__name__}; it is a boolean column on both "
        "backends: pass callback=True for a subscription that delivers callbacks"
    )
