"""MCP protocol version constants and negotiation helpers.

Single source of truth for the protocol versions the ActingWeb MCP handlers
speak. Values come from the installed MCP SDK so they track the SDK's
``SUPPORTED_PROTOCOL_VERSIONS`` (currently up through ``2025-11-25``); a
conservative fallback applies if the SDK is unavailable.

The hand-rolled handlers in ``actingweb/handlers/mcp.py`` and
``async_mcp.py`` use :func:`negotiate_protocol_version` during ``initialize``
and :func:`supports_structured_content` when formatting ``tools/call``
results.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS as _SDK_SUPPORTED
    from mcp.types import LATEST_PROTOCOL_VERSION as _SDK_LATEST

    SUPPORTED_PROTOCOL_VERSIONS: list[str] = list(_SDK_SUPPORTED)
    LATEST_PROTOCOL_VERSION: str = _SDK_LATEST
except ImportError:
    # MCP SDK not installed; the /mcp endpoint won't serve real traffic, but
    # keep importable constants for discovery/metadata code paths.
    SUPPORTED_PROTOCOL_VERSIONS = ["2024-11-05"]  # pyright: ignore[reportConstantRedefinition]
    LATEST_PROTOCOL_VERSION = "2024-11-05"  # pyright: ignore[reportConstantRedefinition]

# Per the MCP HTTP transport spec, a server that receives no
# ``MCP-Protocol-Version`` header (and has no other way to identify the
# version) SHOULD assume this version.
DEFAULT_NEGOTIATED_VERSION = "2025-03-26"

# ``structuredContent`` / ``outputSchema`` on tool results were introduced in
# this revision. Protocol revisions are ISO date strings, which sort
# chronologically, so a lexicographic ``>=`` against a known-supported version
# is a valid "this revision or newer" test.
STRUCTURED_CONTENT_MIN_VERSION = "2025-06-18"


def negotiate_protocol_version(requested: str | None) -> str:
    """Return the protocol version to announce in an ``initialize`` response.

    Per the MCP lifecycle spec: if the client's requested version is
    supported, the server MUST respond with that same version; otherwise it
    responds with another version it supports (its latest).
    """
    if requested and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


def is_supported_protocol_version(version: str | None) -> bool:
    """True if ``version`` is one the handler supports."""
    return bool(version) and version in SUPPORTED_PROTOCOL_VERSIONS


def supports_structured_content(version: str | None) -> bool:
    """True if the negotiated protocol version supports ``structuredContent``."""
    return is_supported_protocol_version(version) and (
        version is not None and version >= STRUCTURED_CONTENT_MIN_VERSION
    )
