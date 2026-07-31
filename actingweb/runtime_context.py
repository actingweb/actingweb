"""
Runtime Context System for ActingWeb.

This module provides a generic system for making request-specific context
available to hook functions during request processing. This solves the
architectural constraint where hook functions have fixed signatures but need
access to request-specific context.

Architecture Problem:

- ActingWeb hook functions have fixed signatures: hook(actor, action_name, data)
- Multiple clients can access the same actor (MCP clients, web users, API clients)
- Each request needs context about the current client/request for proper handling
- Can't modify hook signatures without breaking framework compatibility
- The actor object handed to hooks is frequently the *same* cached object
  reused across many requests (MCP's per-actor cache is the primary example),
  so context cannot live as mutable state on the actor without leaking
  between requests and, under concurrency, between callers.

Solution:

- Store context in a module-level ``contextvars.ContextVar``, keyed by actor
  id, rather than as an attribute on the actor object.
- ``ContextVar`` is task-local under asyncio and thread-local under a plain
  WSGI worker thread, so context set for one request is invisible to a
  concurrently running request even when both share the same actor object.
- Provide type-safe access methods with clear documentation
- Support multiple context types (MCP, OAuth2, web sessions, etc.)
- Framework integrations (Flask, FastAPI) clear the ContextVar at the end of
  each request, via the module-level ``clear_all_context()``, so nothing
  survives onto a reused worker thread. ``clear_all_context()`` is
  framework/test plumbing -- application hooks should use
  ``RuntimeContext(actor).clear_context()`` if they need to clear a specific
  actor's context mid-request.

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

Concurrency notes:

- A request dispatched onto a fresh ``asyncio`` task automatically inherits
  the context that was active when the task was created (a snapshot, not a
  live link — the child cannot mutate the parent's view and vice versa).
- A request dispatched onto a *new thread* (e.g. ``ThreadPoolExecutor``)
  does **not** automatically inherit the caller's context; the submitting
  code must capture ``contextvars.copy_context()`` and run the callable via
  ``ctx.run(...)`` for context to cross the hop. See
  ``actingweb/interface/hooks.py`` for the one place ActingWeb does this.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Maps actor id -> that actor's context dict (e.g. {"mcp": MCPContext(...)}).
# The value is treated as immutable once set: every write builds a *new*
# outer dict and a *new* per-actor dict rather than mutating in place, because
# a context snapshot captured by `copy_context()` (e.g. across an asyncio task
# boundary or an executor hop) shares the same dict objects as its parent —
# in-place mutation would be visible on both sides of that boundary.
# Default is `None`, not `{}`: a mutable default object would be the single
# shared sentinel returned by every context that never called `.set()`, so
# `_all_contexts()` normalizes it to a fresh empty dict on every read instead.
_runtime_context_var: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "actingweb_runtime_context", default=None
)


def _all_contexts() -> dict[str, dict[str, Any]]:
    """Current thread's/task's view of the per-actor context map."""
    return _runtime_context_var.get() or {}


def _actor_key(actor: Any) -> str:
    """Stable per-actor key for the context map.

    Keyed by ``actor.id`` so that ``RuntimeContext(a)`` and
    ``RuntimeContext(b)`` observe the same context whenever ``a.id == b.id``
    -- including when one is an ``ActorInterface`` and the other is the
    ``CoreActor`` it wraps, which previously (attribute-based storage) stored
    on whichever object was actually passed and therefore missed reads
    through the other wrapper.

    Every production call site constructs ``RuntimeContext`` on an actor
    already resolved by id (post-authentication, from the actor cache or a
    direct ``CoreActor(actor_id, ...)`` lookup), so ``actor.id`` is never
    falsy there. The ``_no_id_`` fallback below exists only so lightweight
    test doubles with no ``id`` attribute at all (see
    ``tests/test_runtime_context_unit.py``'s ``_Bag``) still get an object
    identity to key on rather than colliding on a shared key. It is a
    correctness convenience for tests, not a defended production path: if a
    real actor with a falsy id ever reached here, this key would be prone to
    reuse across objects (CPython can reallocate a garbage-collected
    object's address), so this branch must not be relied on for isolation
    guarantees in production code.
    """
    actor_id = getattr(actor, "id", None)
    if actor_id:
        return str(actor_id)
    return f"_no_id_{id(actor)}"


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
    # Per-MCP-connection identifier, distinct from ``peer_id`` (which is
    # shared across concurrent sessions on the same OAuth2 credential).
    # Prefer the ``Mcp-Session-Id`` header (MCP HTTP streamable spec);
    # fall back to ``client_ip + user_agent`` hash when the header is
    # absent. ``None`` when neither is available.
    transport_session_id: str | None = None
    # Live ``clientInfo`` from the active session's ``initialize`` call,
    # when available. Distinct from ``trust_relationship.client_name``
    # (which is a per-credential cache overwritten by whichever session
    # last registered). Use this for self-attribution in tool responses
    # so two concurrent sessions on one credential don't see each other's
    # cached identity.
    client_info: dict[str, Any] | None = None


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

    Provides type-safe access to request-specific context, stored in a
    ``ContextVar`` keyed by actor id rather than as state on the actor
    object. This solves the architectural constraint where hook functions
    can't receive additional parameters, without letting context leak across
    requests that happen to share a cached actor object.

    The context is request-scoped (task-local under asyncio, thread-local
    under a plain worker thread) and is cleared by the framework integration
    at the end of each request.
    """

    def __init__(self, actor: Any):
        """
        Initialize runtime context for an actor.

        Args:
            actor: ActorInterface or Actor object whose context to read/write.
                Only ``actor.id`` (and, for unsaved actors, object identity)
                is used to key the underlying storage -- no state is written
                onto the actor object itself.
        """
        self.actor = actor

    def _get_context_data(self) -> dict[str, Any]:
        """Get this actor's runtime context data dict (read-only view)."""
        return _all_contexts().get(_actor_key(self.actor), {})

    def _set_context_data(self, context_data: dict[str, Any]) -> None:
        """Replace this actor's runtime context data dict.

        Builds a new outer mapping rather than mutating the existing one in
        place, so a context snapshot held elsewhere (a parent asyncio task,
        the caller of an executor hop) is unaffected by this write.
        """
        new_all_contexts = dict(_all_contexts())
        new_all_contexts[_actor_key(self.actor)] = context_data
        _runtime_context_var.set(new_all_contexts)

    def set_mcp_context(
        self,
        client_id: str,
        trust_relationship: Any,
        peer_id: str,
        token_data: dict[str, Any] | None = None,
        transport_session_id: str | None = None,
        client_info: dict[str, Any] | None = None,
    ) -> None:
        """
        Set MCP context for the current request.

        Args:
            client_id: OAuth2 client ID of the MCP client
            trust_relationship: Trust database record with client metadata
            peer_id: Normalized peer identifier for permission checking
            token_data: Optional OAuth2 token metadata
            transport_session_id: Optional per-MCP-connection identifier
                that distinguishes concurrent sessions sharing one
                OAuth2 credential (see ``MCPContext.transport_session_id``).
            client_info: Optional live ``clientInfo`` dict from the
                active session's ``initialize`` call (see
                ``MCPContext.client_info``).
        """
        context_data = dict(self._get_context_data())
        context_data["mcp"] = MCPContext(
            client_id=client_id,
            trust_relationship=trust_relationship,
            peer_id=peer_id,
            token_data=token_data,
            transport_session_id=transport_session_id,
            client_info=client_info,
        )
        self._set_context_data(context_data)
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
        context_data = dict(self._get_context_data())
        context_data["oauth2"] = OAuth2Context(
            client_id=client_id,
            user_email=user_email,
            scopes=scopes,
            token_data=token_data,
        )
        self._set_context_data(context_data)
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
        context_data = dict(self._get_context_data())
        context_data["web"] = WebContext(
            session_id=session_id,
            user_agent=user_agent,
            ip_address=ip_address,
            authenticated_user=authenticated_user,
        )
        self._set_context_data(context_data)
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
        Clear all runtime context for this actor.

        This should be called after request processing is complete
        to avoid context leaking between requests.
        """
        actor_key = _actor_key(self.actor)
        all_contexts = _all_contexts()
        if actor_key in all_contexts:
            new_all_contexts = dict(all_contexts)
            del new_all_contexts[actor_key]
            _runtime_context_var.set(new_all_contexts)
            logger.debug(f"Cleared runtime context from actor {self.actor.id}")

    def has_context(self) -> bool:
        """
        Check if any runtime context is set.

        Returns:
            True if any context is set for this actor
        """
        return _actor_key(self.actor) in _all_contexts()

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

        context_data = dict(self._get_context_data())
        context_data[key] = value
        self._set_context_data(context_data)
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


def clear_all_context() -> None:
    """Clear runtime context for every actor tracked in the calling
    thread's/task's own context.

    Framework integrations call this once at the end of a request/response
    cycle (Flask ``teardown_request``, FastAPI middleware ``finally``) as a
    blanket reset, since a request handler does not always know in advance
    which actor id(s) it touched. Test fixtures use it to reset state
    between tests that share a thread or event loop.

    This resets only the calling thread's/task's own view of
    ``_runtime_context_var`` -- it has no effect on a concurrently running
    request's context, which lives in its own copied ``Context``.
    """
    _runtime_context_var.set({})


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

    # Try MCP context first. Prefer the live ``client_info`` captured
    # at the current session's ``initialize`` over the trust
    # relationship's cached ``client_name``: the trust rel is per-OAuth2-
    # credential and gets overwritten whenever a new session registers,
    # so two concurrent sessions sharing one credential would otherwise
    # see each other's identity.
    mcp_context = runtime_context.get_mcp_context()
    if mcp_context:
        live = (
            mcp_context.client_info
            if isinstance(mcp_context.client_info, dict)
            else None
        )
        if live and live.get("name"):
            # MCP ``clientInfo`` carries only name/version per spec;
            # ``platform`` is an ActingWeb enrichment on the trust rel,
            # so this key is normally "" on the live-info path.
            return {
                "name": str(live.get("name") or ""),
                "version": str(live.get("version") or ""),
                "platform": str(live.get("platform") or ""),
                "type": "mcp",
            }
        if mcp_context.trust_relationship:
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
