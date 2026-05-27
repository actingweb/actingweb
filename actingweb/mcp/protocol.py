"""MCP protocol version constants and negotiation helpers.

Single source of truth for the protocol versions the ActingWeb MCP handlers
speak. ActingWeb implements the MCP protocol by hand (see
``actingweb/handlers/mcp.py`` / ``async_mcp.py``) and does not depend on the
official ``mcp`` SDK, so these constants are maintained here directly.

``SUPPORTED_PROTOCOL_VERSIONS`` reflects the revisions this handler can
*negotiate* (tools/resources/prompts semantics + structuredContent). It is not
a claim of full transport compliance: the modern Streamable HTTP transport and
the newer OAuth model are tracked separately in the Phase 3 roadmap (see
``thoughts/plans/2026-05-26-mcp-version-negotiation-structuredcontent.md``).
"Supported" here means "negotiable", not "fully implemented end to end".

When the MCP spec publishes a new revision, append it here (the revisions are
ISO dates and the list is kept in chronological order) and bump
``LATEST_PROTOCOL_VERSION``.

The handlers use :func:`negotiate_protocol_version` during ``initialize`` and
:func:`supports_structured_content` when formatting ``tools/call`` results.
"""

import logging

logger = logging.getLogger(__name__)

# Chronological list of MCP protocol revisions this handler can negotiate.
SUPPORTED_PROTOCOL_VERSIONS: list[str] = [
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
]
LATEST_PROTOCOL_VERSION: str = SUPPORTED_PROTOCOL_VERSIONS[-1]

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
