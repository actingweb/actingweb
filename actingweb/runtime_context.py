"""
Runtime Context System for ActingWeb.

This module provides a generic system for attaching runtime context to actor objects
during request processing. This solves the architectural constraint where hook functions
have fixed signatures but need access to request-specific context.

Architecture Problem:
- ActingWeb hook functions have fixed signatures: hook(actor, action_name, data)
- Multiple clients can access the same actor (MCP clients, web users, API clients)
- Each request needs context about the current client/request for proper handling
- Can't modify hook signatures without breaking framework compatibility

Solution:
- Attach runtime context to actor objects during request processing
- Provide type-safe access methods with clear documentation
- Support multiple context types (MCP, OAuth2, web sessions, etc.)
- Clean up context after request completion

Usage Example::

    # During request authentication:
    runtime_context = RuntimeContext(actor)
    runtime_context.set_mcp_context(
        client_id="mcp_abc123",
        trust_relationship=trust_obj,
        peer_id="oauth2_client:user@example.com:mcp_abc123"
    )

    # In hook functions:
    def handle_search(actor, action_name, data):
        runtime_context = RuntimeContext(actor)
        mcp_context = runtime_context.get_mcp_context()
        if mcp_context:
            client_name = mcp_context.trust_relationship.client_name
            # Customize behavior based on client type
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Runtime context attribute name on actor objects
_RUNTIME_CONTEXT_ATTR = "_actingweb_runtime_context"


@dataclass
class MCPContext:
    """
    Runtime context for MCP (Model Context Protocol) requests.

    Contains information about the current MCP client making the request,
    allowing tools to customize behavior based on client capabilities.
    """

    client_id: str  # OAuth2 client ID (e.g., "mcp_abc123")
    trust_relationship: Any  # Trust database record with client metadata
    peer_id: str  # Normalized peer identifier for permission checking
    token_data: dict[str, Any] | None = None  # OAuth2 token metadata


@dataclass
class OAuth2Context:
    """
    Runtime context for OAuth2 authenticated requests.

    Contains information about the current OAuth2 session for web or API access.
    """

    client_id: str  # OAuth2 client ID
    user_email: str  # Authenticated user email
    scopes: list[str]  # Granted OAuth2 scopes
    token_data: dict[str, Any] | None = None  # Token metadata


@dataclass
class WebContext:
    """
    Runtime context for web browser requests.

    Contains session and authentication information for web UI access.
    """

    session_id: str | None = None  # Session identifier
    user_agent: str | None = None  # Browser user agent
    ip_address: str | None = None  # Client IP address
    authenticated_user: str | None = None  # Authenticated user identifier


class RuntimeContext:
    """
    Generic runtime context manager for ActingWeb actors.

    Provides type-safe access to request-specific context that gets attached
    to actor objects during request processing. This solves the architectural
    constraint where hook functions can't receive additional parameters.

    The context is request-scoped and should be cleaned up after processing.
    """

    def __init__(self, actor: Any):
        """
        Initialize runtime context for an actor.

        Args:
            actor: ActorInterface or Actor object to attach context to
        """
        self.actor = actor

    def _get_context_data(self) -> dict[str, Any]:
        """Get the runtime context data dict, creating if needed."""
        if not hasattr(self.actor, _RUNTIME_CONTEXT_ATTR):
            setattr(self.actor, _RUNTIME_CONTEXT_ATTR, {})
        return getattr(self.actor, _RUNTIME_CONTEXT_ATTR)

    def set_mcp_context(
        self,
        client_id: str,
        trust_relationship: Any,
        peer_id: str,
        token_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Set MCP context for the current request.

        Args:
            client_id: OAuth2 client ID of the MCP client
            trust_relationship: Trust database record with client metadata
            peer_id: Normalized peer identifier for permission checking
            token_data: Optional OAuth2 token metadata
        """
        context_data = self._get_context_data()
        context_data["mcp"] = MCPContext(
            client_id=client_id,
            trust_relationship=trust_relationship,
            peer_id=peer_id,
            token_data=token_data,
        )
        # MCP context set successfully (no logging needed for routine operation)

    def get_mcp_context(self) -> MCPContext | None:
        """
        Get MCP context for the current request.

        Returns:
            MCPContext if this is an MCP request, None otherwise
        """
        context_data = self._get_context_data()
        return context_data.get("mcp")

    def set_oauth2_context(
        self,
        client_id: str,
        user_email: str,
        scopes: list[str],
        token_data: dict[str, Any] | None = None,
    ) -> None:
        """
        Set OAuth2 context for the current request.

        Args:
            client_id: OAuth2 client ID
            user_email: Authenticated user email
            scopes: Granted OAuth2 scopes
            token_data: Optional token metadata
        """
        context_data = self._get_context_data()
        context_data["oauth2"] = OAuth2Context(
            client_id=client_id,
            user_email=user_email,
            scopes=scopes,
            token_data=token_data,
        )
        logger.debug(
            f"Set OAuth2 context for client {client_id} on actor {self.actor.id}"
        )

    def get_oauth2_context(self) -> OAuth2Context | None:
        """
        Get OAuth2 context for the current request.

        Returns:
            OAuth2Context if this is an OAuth2 request, None otherwise
        """
        context_data = self._get_context_data()
        return context_data.get("oauth2")

    def set_web_context(
        self,
        session_id: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        authenticated_user: str | None = None,
    ) -> None:
        """
        Set web browser context for the current request.

        Args:
            session_id: Session identifier
            user_agent: Browser user agent
            ip_address: Client IP address
            authenticated_user: Authenticated user identifier
        """
        context_data = self._get_context_data()
        context_data["web"] = WebContext(
            session_id=session_id,
            user_agent=user_agent,
            ip_address=ip_address,
            authenticated_user=authenticated_user,
        )
        logger.debug(
            f"Set web context for session {session_id} on actor {self.actor.id}"
        )

    def get_web_context(self) -> WebContext | None:
        """
        Get web browser context for the current request.

        Returns:
            WebContext if this is a web request, None otherwise
        """
        context_data = self._get_context_data()
        return context_data.get("web")

    def get_request_type(self) -> str | None:
        """
        Determine the type of the current request.

        Returns:
            "mcp", "oauth2", "web", or None if no context is set
        """
        context_data = self._get_context_data()
        if "mcp" in context_data:
            return "mcp"
        elif "oauth2" in context_data:
            return "oauth2"
        elif "web" in context_data:
            return "web"
        return None

    def clear_context(self) -> None:
        """
        Clear all runtime context from the actor.

        This should be called after request processing is complete
        to avoid context leaking between requests.
        """
        if hasattr(self.actor, _RUNTIME_CONTEXT_ATTR):
            delattr(self.actor, _RUNTIME_CONTEXT_ATTR)
            logger.debug(f"Cleared runtime context from actor {self.actor.id}")

    def has_context(self) -> bool:
        """
        Check if any runtime context is set.

        Returns:
            True if any context is attached to the actor
        """
        return hasattr(self.actor, _RUNTIME_CONTEXT_ATTR)

    def set_custom_context(self, key: str, value: Any) -> None:
        """
        Set custom context data.

        Args:
            key: Context key (avoid 'mcp', 'oauth2', 'web' which are reserved)
            value: Context value
        """
        if key in ("mcp", "oauth2", "web"):
            raise ValueError(
                f"Context key '{key}' is reserved, use specific setter methods"
            )

        context_data = self._get_context_data()
        context_data[key] = value
        logger.debug(f"Set custom context '{key}' on actor {self.actor.id}")

    def get_custom_context(self, key: str) -> Any:
        """
        Get custom context data.

        Args:
            key: Context key

        Returns:
            Context value or None if not found
        """
        context_data = self._get_context_data()
        return context_data.get(key)


def get_client_info_from_context(actor: Any) -> dict[str, str] | None:
    """
    Helper function to extract client information from runtime context.

    This provides a unified way to get client details regardless of context type.

    Args:
        actor: Actor object with potential runtime context

    Returns:
        Dict with 'name', 'version', 'platform' keys, or None if no client info available
    """
    runtime_context = RuntimeContext(actor)

    # Try MCP context first
    mcp_context = runtime_context.get_mcp_context()
    if mcp_context and mcp_context.trust_relationship:
        trust = mcp_context.trust_relationship
        client_name = getattr(trust, "client_name", "")
        client_version = getattr(trust, "client_version", "")
        client_platform = getattr(trust, "client_platform", "")

        if client_name:  # Only return if we have actual client info
            return {
                "name": client_name,
                "version": client_version or "",
                "platform": client_platform or "",
                "type": "mcp",
            }

    # Try OAuth2 context
    oauth2_context = runtime_context.get_oauth2_context()
    if oauth2_context:
        return {
            "name": f"OAuth2 Client ({oauth2_context.client_id})",
            "version": "",
            "platform": "",
            "type": "oauth2",
        }

    # Try web context
    web_context = runtime_context.get_web_context()
    if web_context:
        return {
            "name": "Web Browser",
            "version": "",
            "platform": web_context.user_agent or "",
            "type": "web",
        }

    return None
