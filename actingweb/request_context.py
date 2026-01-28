"""Request context management for logging correlation.

This module provides thread-safe and async-safe storage for request-scoped
context information (request ID, actor ID, peer ID) using Python's contextvars.

The context is automatically isolated per request and propagates correctly
through async/await boundaries, making it suitable for both Flask (WSGI) and
FastAPI (ASGI) applications.
"""

import uuid
from contextvars import ContextVar
from typing import Any

# Context variables for request-scoped data
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_actor_id: ContextVar[str | None] = ContextVar("actor_id", default=None)
_peer_id: ContextVar[str | None] = ContextVar("peer_id", default=None)


def generate_request_id() -> str:
    """
    Generate a new UUID4 request ID.

    Returns:
        A string UUID in the format: "550e8400-e29b-41d4-a716-446655440000"

    Example:
        >>> request_id = generate_request_id()
        >>> len(request_id)
        36
    """
    return str(uuid.uuid4())


def set_request_id(request_id: str | None) -> None:
    """
    Set the request ID for the current context.

    Args:
        request_id: The request ID to set, or None to clear

    Example:
        >>> set_request_id("550e8400-e29b-41d4-a716-446655440000")
        >>> get_request_id()
        '550e8400-e29b-41d4-a716-446655440000'
    """
    _request_id.set(request_id)


def get_request_id() -> str | None:
    """
    Get the request ID for the current context.

    Returns:
        The request ID if set, otherwise None

    Example:
        >>> get_request_id()  # Returns None if not set
        >>> set_request_id("550e8400-e29b-41d4-a716-446655440000")
        >>> get_request_id()
        '550e8400-e29b-41d4-a716-446655440000'
    """
    return _request_id.get()


def get_short_request_id() -> str:
    """
    Get a shortened version of the request ID (last 8 characters).

    This is useful for compact log formats where the full UUID is too verbose.
    8 characters provides sufficient uniqueness for correlation within a
    reasonable time window.

    Returns:
        Last 8 characters of the request ID, or "-" if no request ID is set

    Example:
        >>> set_request_id("550e8400-e29b-41d4-a716-446655440000")
        >>> get_short_request_id()
        '40000'
        >>> set_request_id(None)
        >>> get_short_request_id()
        '-'
    """
    request_id = _request_id.get()
    if request_id:
        # Remove hyphens and take last 8 chars for compact representation
        return request_id.replace("-", "")[-8:]
    return "-"


def set_actor_id(actor_id: str | None) -> None:
    """
    Set the actor ID for the current context.

    Args:
        actor_id: The actor ID to set, or None to clear

    Example:
        >>> set_actor_id("actor123")
        >>> get_actor_id()
        'actor123'
    """
    _actor_id.set(actor_id)


def get_actor_id() -> str | None:
    """
    Get the actor ID for the current context.

    Returns:
        The actor ID if set, otherwise None

    Example:
        >>> get_actor_id()  # Returns None if not set
        >>> set_actor_id("actor123")
        >>> get_actor_id()
        'actor123'
    """
    return _actor_id.get()


def set_peer_id(peer_id: str | None) -> None:
    """
    Set the peer ID for the current context.

    The peer ID identifies the remote actor or client making the request,
    and is typically set after authentication completes.

    Args:
        peer_id: The peer ID to set, or None to clear

    Example:
        >>> set_peer_id("peer456")
        >>> get_peer_id()
        'peer456'
    """
    _peer_id.set(peer_id)


def get_peer_id() -> str | None:
    """
    Get the peer ID for the current context.

    Returns:
        The peer ID if set, otherwise None

    Example:
        >>> get_peer_id()  # Returns None if not set
        >>> set_peer_id("peer456")
        >>> get_peer_id()
        'peer456'
    """
    return _peer_id.get()


def get_short_peer_id() -> str:
    """
    Get a shortened version of the peer ID (last segment after final colon).

    Peer IDs often follow the pattern "urn:actingweb:example.com:actor123",
    so this extracts just the last segment for compact logging.

    Returns:
        Last segment of peer ID after final colon, or "-" if no peer ID is set

    Example:
        >>> set_peer_id("urn:actingweb:example.com:actor123")
        >>> get_short_peer_id()
        'actor123'
        >>> set_peer_id("simple_peer")
        >>> get_short_peer_id()
        'simple_peer'
        >>> set_peer_id(None)
        >>> get_short_peer_id()
        '-'
    """
    peer_id = _peer_id.get()
    if peer_id:
        # Extract last segment after final colon, or use full ID if no colons
        return peer_id.split(":")[-1]
    return "-"


def set_request_context(
    request_id: str | None = None,
    actor_id: str | None = None,
    peer_id: str | None = None,
    *,
    generate_id: bool = True,
) -> str:
    """
    Set all request context values at once.

    This is the primary entry point for framework integrations (Flask, FastAPI)
    to establish request context at the start of request handling.

    Args:
        request_id: The request ID, or None to generate a new one
        actor_id: The actor ID from the request path
        peer_id: The peer ID (typically set later after authentication)
        generate_id: If True and request_id is None, generate a new UUID

    Returns:
        The request ID that was set (either provided or generated)

    Example:
        >>> # Framework integration: set context at request start
        >>> req_id = set_request_context(
        ...     request_id=request.headers.get("X-Request-ID"),
        ...     actor_id=request.path_params.get("actor_id"),
        ...     generate_id=True,
        ... )
        >>> print(f"Handling request {req_id}")
    """
    if request_id is None and generate_id:
        request_id = generate_request_id()

    _request_id.set(request_id)
    _actor_id.set(actor_id)
    _peer_id.set(peer_id)

    return request_id or ""


def clear_request_context() -> None:
    """
    Clear all request context values.

    This should be called at the end of request handling to prevent context
    leakage between requests. Framework integrations should call this in
    finally blocks or response handlers.

    Example:
        >>> set_request_context(actor_id="actor123")
        >>> get_actor_id()
        'actor123'
        >>> clear_request_context()
        >>> get_actor_id()  # Returns None
    """
    _request_id.set(None)
    _actor_id.set(None)
    _peer_id.set(None)


def get_context_dict() -> dict[str, Any]:
    """
    Get all context values as a dictionary.

    This is useful for structured logging (JSON) where context should be
    included as separate fields rather than in a formatted string.

    Returns:
        Dictionary with keys: request_id, actor_id, peer_id
        Values are None if not set in current context

    Example:
        >>> set_request_context(
        ...     request_id="550e8400-e29b-41d4-a716-446655440000",
        ...     actor_id="actor123",
        ... )
        >>> get_context_dict()
        {'request_id': '550e8400-e29b-41d4-a716-446655440000', 'actor_id': 'actor123', 'peer_id': None}
    """
    return {
        "request_id": _request_id.get(),
        "actor_id": _actor_id.get(),
        "peer_id": _peer_id.get(),
    }


def format_context_compact() -> str:
    """
    Format context as a compact string for text-based logging.

    Format: [short_request_id:actor_id:short_peer_id]
    Missing values are represented as "-"

    Returns:
        Formatted context string like "[a1b2c3d4:actor123:peer456]"

    Example:
        >>> set_request_context(
        ...     request_id="550e8400-e29b-41d4-a716-446655440000",
        ...     actor_id="actor123",
        ... )
        >>> set_peer_id("urn:actingweb:example.com:peer456")
        >>> format_context_compact()
        '[55440000:actor123:peer456]'
        >>> clear_request_context()
        >>> format_context_compact()
        '[-:-:-]'
    """
    short_req = get_short_request_id()
    actor = get_actor_id() or "-"
    short_peer = get_short_peer_id()

    return f"[{short_req}:{actor}:{short_peer}]"
