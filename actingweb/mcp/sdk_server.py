"""
MCP server implementation using the official MCP Python SDK.

This module replaces the FastMCP implementation with the official SDK,
providing better compliance with the MCP specification and more robust
protocol handling.
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional, Union

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Server
    from mcp.types import Tool, Resource, Prompt, TextContent, GetPromptResult, PromptMessage, TextResourceContents
    from pydantic import AnyUrl
    MCP_AVAILABLE = True
else:
    try:
        from mcp.server import Server
        from mcp.types import Tool, Resource, Prompt, TextContent, GetPromptResult, PromptMessage, TextResourceContents
        from pydantic import AnyUrl
        MCP_AVAILABLE = True
    except ImportError:
        # Official MCP SDK not available
        MCP_AVAILABLE = False
        from typing import Any
        Server = Any
        Tool = Any
        Resource = Any
        Prompt = Any
        TextContent = Any
        GetPromptResult = Any
        PromptMessage = Any
        TextResourceContents = Any
        AnyUrl = Any

from ..interface.hooks import HookRegistry
from ..interface.actor_interface import ActorInterface
from .decorators import get_mcp_metadata, is_mcp_exposed

logger = logging.getLogger(__name__)


class ActingWebMCPServer:
    """
    MCP Server using the official SDK for ActingWeb actors.

    This class bridges ActingWeb's hook system to the MCP protocol,
    exposing actor functionality as MCP tools, resources, and prompts.
    """

    def __init__(self, actor_id: str, hooks: HookRegistry, actor: ActorInterface):
        if not MCP_AVAILABLE:
            raise ImportError("Official MCP SDK not available. Install with: pip install mcp")

        self.actor_id = actor_id
        self.hooks = hooks
        self.actor = actor
        self.server = Server(f"actingweb-{actor_id}")

        # Set up MCP handlers
        self._setup_handlers()

        logger.info(f"Created ActingWeb MCP server for actor {actor_id}")

    def _setup_handlers(self) -> None:
        """Set up MCP protocol handlers."""

        # Tools handler - expose action hooks as MCP tools
        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            """List available tools from ActingWeb action hooks."""
            tools = []

            if self.hooks:
                for action_name, hook_list in self.hooks._action_hooks.items():
                    for hook in hook_list:
                        if is_mcp_exposed(hook):
                            metadata = get_mcp_metadata(hook)
                            if metadata and metadata.get("type") == "tool":
                                tool = Tool(
                                    name=metadata.get("name", action_name),
                                    description=metadata.get("description", f"Execute {action_name} action"),
                                    inputSchema=metadata.get(
                                        "input_schema", {"type": "object", "properties": {}, "required": []}
                                    ),
                                )
                                tools.append(tool)

            logger.debug(f"Listed {len(tools)} tools for actor {self.actor_id}")
            return tools

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Execute a tool (ActingWeb action hook)."""
            if not self.hooks:
                raise ValueError("No hooks registry available")

            # Find the corresponding action hook
            for action_name, hook_list in self.hooks._action_hooks.items():
                for hook in hook_list:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "tool":
                            tool_name = metadata.get("name", action_name)
                            if tool_name == name:
                                try:
                                    # Execute the action hook
                                    result = hook(self.actor, action_name, arguments)

                                    # Handle async results
                                    if asyncio.iscoroutine(result):
                                        result = await result

                                    # Format result as text content
                                    if isinstance(result, dict):
                                        import json

                                        result_text = json.dumps(result, indent=2)
                                    else:
                                        result_text = str(result)

                                    logger.debug(f"Tool {name} executed successfully for actor {self.actor_id}")
                                    return [TextContent(type="text", text=result_text)]

                                except Exception as e:
                                    logger.error(f"Error executing tool {name}: {e}")
                                    return [TextContent(type="text", text=f"Error: {str(e)}")]

            raise ValueError(f"Tool not found: {name}")

        # Resources handler - expose resources from hooks or static resources
        @self.server.list_resources()
        async def handle_list_resources() -> List[Resource]:
            """List available resources."""
            resources = []

            # Static resources that are useful for MCP clients
            static_resources = [
                Resource(
                    uri="actingweb://notes/all",  # type: ignore[arg-type]
                    name="All Notes",
                    description="Access all stored notes for the current user",
                    mimeType="application/json",
                ),
                Resource(
                    uri="actingweb://reminders/pending",  # type: ignore[arg-type]
                    name="Pending Reminders",
                    description="List of all pending/incomplete reminders",
                    mimeType="application/json",
                ),
                Resource(
                    uri="actingweb://usage/stats",  # type: ignore[arg-type]
                    name="Usage Statistics",
                    description="Statistics about MCP tool usage and activity",
                    mimeType="application/json",
                ),
                Resource(
                    uri="actingweb://properties/all",  # type: ignore[arg-type]
                    name="Actor Properties",
                    description="All properties for this actor",
                    mimeType="application/json",
                ),
            ]

            resources.extend(static_resources)

            # TODO: Add dynamic resources from resource hooks when implemented

            logger.debug(f"Listed {len(resources)} resources for actor {self.actor_id}")
            return resources

        @self.server.read_resource()
        async def handle_read_resource(uri: AnyUrl) -> str:
            """Read a resource by URI."""
            try:
                uri_str = str(uri)
                if uri_str == "actingweb://notes/all":
                    notes = self.actor.properties.get("notes", [])
                    import json

                    return json.dumps({"total_notes": len(notes), "notes": notes}, indent=2)

                elif uri_str == "actingweb://reminders/pending":
                    reminders = self.actor.properties.get("reminders", [])
                    pending_reminders = [r for r in reminders if not r.get("completed", False)]
                    import json

                    return json.dumps(
                        {"total_pending": len(pending_reminders), "reminders": pending_reminders}, indent=2
                    )

                elif uri_str == "actingweb://usage/stats":
                    notes = self.actor.properties.get("notes", [])
                    reminders = self.actor.properties.get("reminders", [])
                    mcp_usage = self.actor.properties.get("mcp_usage_count", 0)

                    # Calculate tag usage
                    tag_counts: Dict[str, int] = {}
                    for note in notes:
                        for tag in note.get("tags", []):
                            tag_counts[tag] = tag_counts.get(tag, 0) + 1

                    import json

                    return json.dumps(
                        {
                            "mcp_usage_count": mcp_usage,
                            "total_notes": len(notes),
                            "total_reminders": len(reminders),
                            "pending_reminders": len([r for r in reminders if not r.get("completed", False)]),
                            "most_used_tags": dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]),
                            "created_at": self.actor.properties.get("created_at", "unknown"),
                        },
                        indent=2,
                    )

                elif uri_str == "actingweb://properties/all":
                    # Get all non-sensitive properties
                    props = {}
                    if hasattr(self.actor, "properties") and self.actor.properties:
                        # Get property names and values, excluding sensitive ones
                        sensitive_props = {"oauth_token", "oauth_refresh_token", "auth_token", "password", "secret"}
                        for prop_name in dir(self.actor.properties):
                            if not prop_name.startswith("_") and prop_name not in sensitive_props:
                                try:
                                    value = getattr(self.actor.properties, prop_name)
                                    if not callable(value):
                                        props[prop_name] = value
                                except Exception:
                                    pass  # Skip properties that can't be accessed

                    import json

                    return json.dumps({"actor_id": self.actor_id, "properties": props}, indent=2)

                else:
                    raise ValueError(f"Resource not found: {uri_str}")

            except Exception as e:
                logger.error(f"Error reading resource {uri}: {e}")
                raise ValueError(f"Error reading resource {uri}: {str(e)}")

        # Prompts handler - expose method hooks as MCP prompts
        @self.server.list_prompts()
        async def handle_list_prompts() -> List[Prompt]:
            """List available prompts from ActingWeb method hooks."""
            prompts = []

            if self.hooks:
                for method_name, hook_list in self.hooks._method_hooks.items():
                    for hook in hook_list:
                        if is_mcp_exposed(hook):
                            metadata = get_mcp_metadata(hook)
                            if metadata and metadata.get("type") == "prompt":
                                prompt = Prompt(
                                    name=metadata.get("name", method_name),
                                    description=metadata.get("description", f"Generate prompt for {method_name}"),
                                    arguments=metadata.get("arguments", []),
                                )
                                prompts.append(prompt)

            logger.debug(f"Listed {len(prompts)} prompts for actor {self.actor_id}")
            return prompts

        @self.server.get_prompt()
        async def handle_get_prompt(name: str, arguments: Dict[str, str] | None) -> GetPromptResult:
            """Get a prompt by name (execute method hook)."""
            if not self.hooks:
                raise ValueError("No hooks registry available")

            # Find the corresponding method hook
            for method_name, hook_list in self.hooks._method_hooks.items():
                for hook in hook_list:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "prompt":
                            prompt_name = metadata.get("name", method_name)
                            if prompt_name == name:
                                try:
                                    # Execute the method hook
                                    result = hook(self.actor, method_name, arguments)

                                    # Handle async results
                                    if asyncio.iscoroutine(result):
                                        result = await result

                                    # Convert result to string for prompt
                                    if isinstance(result, dict):
                                        if "prompt" in result:
                                            prompt_text = str(result["prompt"])
                                        else:
                                            import json

                                            prompt_text = json.dumps(result, indent=2)
                                    else:
                                        prompt_text = str(result)

                                    logger.debug(f"Prompt {name} generated successfully for actor {self.actor_id}")
                                    # Return as GetPromptResult - typically contains the prompt text
                                    return GetPromptResult(description=f"Generated prompt for {name}", messages=[PromptMessage(role="user", content=TextContent(type="text", text=prompt_text))])

                                except Exception as e:
                                    logger.error(f"Error generating prompt {name}: {e}")
                                    raise ValueError(f"Error generating prompt {name}: {str(e)}")

            raise ValueError(f"Prompt not found: {name}")


class MCPServerManager:
    """
    Manages MCP servers for ActingWeb actors using the official SDK.

    This class handles the creation and caching of MCP servers per actor,
    ensuring efficient resource usage and proper isolation between actors.
    """

    def __init__(self) -> None:
        self._servers: Dict[str, ActingWebMCPServer] = {}

    def get_server(self, actor_id: str, hook_registry: HookRegistry, actor: ActorInterface) -> ActingWebMCPServer:
        """
        Get or create an MCP server for the given actor.

        Args:
            actor_id: Unique identifier for the actor
            hook_registry: The hook registry containing registered hooks
            actor: The actor instance

        Returns:
            ActingWebMCPServer instance for the actor
        """
        if actor_id not in self._servers:
            self._servers[actor_id] = ActingWebMCPServer(actor_id, hook_registry, actor)
            logger.info(f"Created MCP server for actor {actor_id}")

        return self._servers[actor_id]

    def remove_server(self, actor_id: str) -> None:
        """Remove and cleanup MCP server for an actor."""
        if actor_id in self._servers:
            del self._servers[actor_id]
            logger.info(f"Removed MCP server for actor {actor_id}")

    def has_server(self, actor_id: str) -> bool:
        """Check if a server exists for the given actor."""
        return actor_id in self._servers


# Global server manager instance
_server_manager: Optional[MCPServerManager] = None


def get_server_manager() -> MCPServerManager:
    """Get or create the global MCP server manager instance."""
    global _server_manager
    if _server_manager is None:
        _server_manager = MCPServerManager()
    return _server_manager
