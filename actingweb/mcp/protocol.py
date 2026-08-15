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


def unsupported_version_message(requested: str | None) -> str:
    """The error ``message`` for a rejected ``MCP-Protocol-Version`` header.

    Names the versions this server speaks, **in the message string only**.

    The spec makes this argument for the mirror-image case — a server SHOULD
    name its versions because, for a client that cannot fall forward, *"this
    message may be the only diagnostic they can surface to users."* The same
    holds here: a client that cannot fall back gets a human-readable error
    naming what would have worked, instead of a bare rejection.

    **The versions belong in the message and nowhere else.** Moving them into a
    structured ``data.supported`` array is the one change that must not happen —
    see the comment on the rejection in ``MCPHandler._resolve_request_protocol_version``.
    """
    supported = ", ".join(SUPPORTED_PROTOCOL_VERSIONS)
    return (
        f"Unsupported MCP-Protocol-Version: {requested}. "
        f"This server supports: {supported}"
    )


def supports_structured_content(version: str | None) -> bool:
    """True if the negotiated protocol version supports ``structuredContent``."""
    return is_supported_protocol_version(version) and (
        version is not None and version >= STRUCTURED_CONTENT_MIN_VERSION
    )
