"""Cache invalidation hooks for code that revokes MCP credentials.

The MCP handler keeps in-process caches of validated tokens, actor wrappers and
trust relationships, all on a five-minute TTL. Anything that revokes a
credential or narrows an authorization has to say so, or the change is honoured
from a warm process until that TTL expires — a *staleness* window, not an
authorization bypass, but a real one:
``thoughts/todo/mcp-cache-lifecycle-and-revocation.md`` §1.

**Why this module exists rather than importing the handler directly.** The
callers are core modules — token revocation, trust deletion, permission
changes — and MCP is an optional, higher layer. Importing
``actingweb.handlers.mcp`` from ``actingweb/trust.py`` at module scope inverts
that layering and risks an import cycle. These shims do the import lazily, per
call, and degrade to a no-op when the handler is unimportable (MCP not in use,
or a partially-installed environment). Revocation must never fail because a
cache could not be told about it.

**Single-process only.** Every cache here is a module global, so this clears
the process that served the revocation and nothing else. In a multi-worker or
multi-container deployment, other processes keep serving their own entries
until their TTL expires. Closing that needs a shared invalidation channel and
is deliberately out of scope — §2 of the same todo.
"""

import logging

logger = logging.getLogger(__name__)


def evict_caches_for_token(token: str) -> bool:
    """Drop MCP cache state keyed by ``token``. True if something was cached."""
    if not token:
        return False
    try:
        from ..handlers.mcp import MCPHandler
    except Exception:  # pragma: no cover - MCP unavailable; nothing to evict
        logger.debug("MCP handler unavailable; skipping token cache eviction")
        return False
    try:
        return bool(MCPHandler.clear_token_from_cache(token))
    except Exception:  # pragma: no cover - eviction must never fail revocation
        logger.warning("Failed to evict MCP token cache entry", exc_info=True)
        return False


def evict_caches_for_actor(actor_id: str) -> int:
    """Drop every MCP cache entry for ``actor_id``. Returns the count.

    Used where the change does not arrive holding a token — a revoke-all, a
    deleted trust relationship, a downgraded permission.
    """
    if not actor_id:
        return 0
    try:
        from ..handlers.mcp import evict_mcp_caches_for_actor
    except Exception:  # pragma: no cover - MCP unavailable; nothing to evict
        logger.debug("MCP handler unavailable; skipping actor cache eviction")
        return 0
    try:
        return evict_mcp_caches_for_actor(actor_id)
    except Exception:  # pragma: no cover - eviction must never fail revocation
        logger.warning("Failed to evict MCP caches for actor", exc_info=True)
        return 0
