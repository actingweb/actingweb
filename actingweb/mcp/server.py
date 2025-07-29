"""
MCP server factory and management for ActingWeb.

This module provides functionality to create and manage MCP servers for
ActingWeb actors, bridging ActingWeb hooks to MCP functionality.
"""

from typing import Dict, Any, Callable
import logging
import asyncio

try:
    from mcp.server import FastMCP  # type: ignore
except ImportError:
    # MCP SDK not available - this will be caught at runtime
    FastMCP = None  # type: ignore

from ..interface.hooks import HookRegistry
from ..interface.actor_interface import ActorInterface
from .decorators import get_mcp_metadata, is_mcp_exposed


logger = logging.getLogger(__name__)


class MCPServerManager:
    """
    Manages MCP servers for ActingWeb actors.

    This class handles the creation and caching of MCP servers per actor,
    ensuring efficient resource usage and proper isolation between actors.
    """

    def __init__(self) -> None:
        self._servers: Dict[str, Any] = {}

    def get_server(self, actor_id: str, hook_registry: HookRegistry, actor: ActorInterface) -> Any:
        """
        Get or create an MCP server for the given actor.

        Args:
            actor_id: Unique identifier for the actor
            hook_registry: The hook registry containing registered hooks
            actor: The actor instance

        Returns:
            FastMCP server instance for the actor
        """
        if actor_id not in self._servers:
            self._servers[actor_id] = create_mcp_server(actor_id, hook_registry, actor)
            logger.info(f"Created MCP server for actor {actor_id}")

        return self._servers[actor_id]

    def remove_server(self, actor_id: str) -> None:
        """Remove and cleanup MCP server for an actor."""
        if actor_id in self._servers:
            del self._servers[actor_id]
            logger.info(f"Removed MCP server for actor {actor_id}")


def create_mcp_server(actor_id: str, hook_registry: HookRegistry, actor: ActorInterface) -> Any:
    """
    Create a FastMCP server for an ActingWeb actor.

    Args:
        actor_id: Unique identifier for the actor
        hook_registry: The hook registry containing registered hooks
        actor: The actor instance

    Returns:
        Configured FastMCP server instance
    """
    if FastMCP is None:
        raise ImportError("MCP SDK not available. Install with: pip install actingweb[mcp]")

    mcp = FastMCP(f"ActingWeb-{actor_id}")

    # Register tools from action hooks
    _register_action_hooks_as_tools(mcp, hook_registry, actor)

    # Register resources from resource hooks
    _register_resource_hooks_as_resources(mcp, hook_registry, actor)

    # Register prompts from method hooks
    _register_method_hooks_as_prompts(mcp, hook_registry, actor)

    logger.info(f"MCP server created for actor {actor_id}")
    return mcp


def _register_action_hooks_as_tools(mcp: Any, hook_registry: HookRegistry, actor: ActorInterface) -> None:
    """Register MCP-exposed action hooks as FastMCP tools."""
    for action_name, hooks in hook_registry._action_hooks.items():
        for hook in hooks:
            if is_mcp_exposed(hook):
                metadata = get_mcp_metadata(hook)
                if metadata and metadata["type"] == "tool":
                    _register_tool(mcp, action_name, hook, metadata, actor)


def _register_resource_hooks_as_resources(mcp: Any, hook_registry: HookRegistry, actor: ActorInterface) -> None:
    """Register MCP-exposed resource hooks as FastMCP resources."""
    # Note: FastMCP resources work differently - they're typically registered with URI patterns
    # For now, we'll implement a simpler approach and enhance in Phase 2
    pass


def _register_method_hooks_as_prompts(mcp: Any, hook_registry: HookRegistry, actor: ActorInterface) -> None:
    """Register MCP-exposed method hooks as FastMCP prompts."""
    for method_name, hooks in hook_registry._method_hooks.items():
        for hook in hooks:
            if is_mcp_exposed(hook):
                metadata = get_mcp_metadata(hook)
                if metadata and metadata["type"] == "prompt":
                    _register_prompt(mcp, method_name, hook, metadata, actor)


def _register_tool(
    mcp: Any, action_name: str, hook: Callable[..., Any], metadata: Dict[str, Any], actor: ActorInterface
) -> None:
    """Register a single action hook as an MCP tool."""
    tool_name = metadata.get("name") or action_name
    description = metadata.get("description") or f"Execute {action_name} action"

    @mcp.tool(name=tool_name, description=description)
    async def tool_wrapper(**kwargs: Any) -> Dict[str, Any]:
        """Wrapper function that bridges MCP tool calls to ActingWeb action hooks."""
        try:
            # Execute the ActingWeb action hook
            result = hook(actor, action_name, kwargs)

            # Handle both sync and async results
            if asyncio.iscoroutine(result):
                result = await result

            # Ensure we return a dict
            if not isinstance(result, dict):
                result = {"result": result}

            return result
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return {"error": str(e)}


def _register_prompt(
    mcp: Any, method_name: str, hook: Callable[..., Any], metadata: Dict[str, Any], actor: ActorInterface
) -> None:
    """Register a single method hook as an MCP prompt."""
    prompt_name = metadata.get("name") or method_name
    description = metadata.get("description") or f"Generate prompt for {method_name}"

    # For Phase 1, we'll implement a basic prompt registration
    # This will be enhanced in Phase 2 with proper argument handling
    @mcp.prompt(name=prompt_name, description=description)
    async def prompt_wrapper(**kwargs: Any) -> str:
        """Wrapper function that bridges MCP prompt calls to ActingWeb method hooks."""
        try:
            # Execute the ActingWeb method hook
            result = hook(actor, method_name, kwargs)

            # Handle both sync and async results
            if asyncio.iscoroutine(result):
                result = await result

            # Convert result to string for prompt
            if isinstance(result, dict):
                # If result has a 'prompt' key, use that
                if "prompt" in result:
                    return str(result["prompt"])
                # Otherwise, convert the whole dict
                return str(result)

            return str(result)
        except Exception as e:
            logger.error(f"Error generating prompt {prompt_name}: {e}")
            return f"Error: {str(e)}"


# Global server manager instance
_server_manager = MCPServerManager()


def get_server_manager() -> MCPServerManager:
    """Get the global MCP server manager instance."""
    return _server_manager
