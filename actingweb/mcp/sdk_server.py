"""
MCP server implementation using the official MCP Python SDK.

This module replaces the FastMCP implementation with the official SDK,
providing better compliance with the MCP specification and more robust
protocol handling.
"""

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server import Server
    from mcp.types import (
        GetPromptResult,
        Prompt,
        PromptMessage,
        Resource,
        TextContent,
        Tool,
    )
    from pydantic import AnyUrl

    MCP_AVAILABLE = True
else:
    try:
        from mcp.server import Server
        from mcp.types import (
            GetPromptResult,
            Prompt,
            PromptMessage,
            Resource,
            TextContent,
            Tool,
        )
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
        AnyUrl = Any

from ..interface.actor_interface import ActorInterface
from ..interface.hooks import HookRegistry
from ..permission_evaluator import (
    PermissionResult,
    PermissionType,
    get_permission_evaluator,
)
from .decorators import get_mcp_metadata, is_mcp_exposed

logger = logging.getLogger(__name__)


def _get_config_from_actor(actor: Any) -> Any:
    """Helper function to extract config from actor."""
    # Try different ways to get config depending on actor implementation
    if hasattr(actor, "_config"):
        return actor._config
    elif hasattr(actor, "config"):
        return actor.config
    elif hasattr(actor, "core_actor") and hasattr(actor.core_actor, "config"):
        return actor.core_actor.config
    return None


class ActingWebMCPServer:
    """
    MCP Server using the official SDK for ActingWeb actors.

    This class bridges ActingWeb's hook system to the MCP protocol,
    exposing actor functionality as MCP tools, resources, and prompts.
    """

    def __init__(self, actor_id: str, hooks: HookRegistry, actor: ActorInterface):
        if not MCP_AVAILABLE:
            raise ImportError(
                "Official MCP SDK not available. Install with: pip install mcp"
            )

        self.actor_id = actor_id
        self.hooks = hooks
        self.actor = actor
        self.server = Server(f"actingweb-{actor_id}")

        # Set up MCP handlers
        self._setup_handlers()

        logger.debug(f"Created ActingWeb MCP server for actor {actor_id}")

    def _setup_handlers(self) -> None:
        """Set up MCP protocol handlers."""

        # Tools handler - expose action hooks as MCP tools
        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:  # pyright: ignore[reportUnusedFunction]
            """List available tools from ActingWeb action hooks with permission filtering."""
            tools = []

            if self.hooks:
                # Get trust context and peer_id first
                trust_context = getattr(self.actor, "_mcp_trust_context", None)
                peer_id = trust_context.get("peer_id") if trust_context else None

                # Get permission evaluator and trust context
                config = _get_config_from_actor(self.actor)
                # Get permission evaluator (must be initialized at startup)
                evaluator = None
                if peer_id and config:
                    try:
                        evaluator = get_permission_evaluator(config)
                    except RuntimeError:
                        logger.debug(
                            "Permission evaluator not initialized - skipping permission checks"
                        )
                        evaluator = None
                    except Exception as e:
                        logger.warning(f"Error accessing permission evaluator: {e}")
                        evaluator = None

                for action_name, hook_list in self.hooks._action_hooks.items():
                    for hook in hook_list:
                        if is_mcp_exposed(hook):
                            metadata = get_mcp_metadata(hook)
                            if metadata and metadata.get("type") == "tool":
                                tool_name = metadata.get("name", action_name)

                                # Check permission for this tool
                                if peer_id and evaluator:
                                    permission_result = evaluator.evaluate_permission(
                                        self.actor_id,
                                        peer_id,
                                        PermissionType.TOOLS,
                                        tool_name,
                                    )
                                    if permission_result != PermissionResult.ALLOWED:
                                        logger.debug(
                                            f"Tool '{tool_name}' filtered out - access denied for peer {peer_id}"
                                        )
                                        continue

                                # Build tool with optional fields
                                tool_kwargs = {
                                    "name": tool_name,
                                    "description": metadata.get(
                                        "description", f"Execute {action_name} action"
                                    ),
                                    "inputSchema": metadata.get(
                                        "input_schema",
                                        {
                                            "type": "object",
                                            "properties": {},
                                            "required": [],
                                        },
                                    ),
                                }

                                # Add optional title
                                if metadata.get("title"):
                                    tool_kwargs["title"] = metadata["title"]

                                # Add optional output schema
                                if metadata.get("output_schema"):
                                    tool_kwargs["outputSchema"] = metadata[
                                        "output_schema"
                                    ]

                                # Add optional annotations for safety metadata
                                if metadata.get("annotations"):
                                    from mcp.types import ToolAnnotations

                                    annotations_dict = metadata["annotations"]
                                    tool_kwargs["annotations"] = ToolAnnotations(
                                        **annotations_dict
                                    )

                                tool = Tool(**tool_kwargs)
                                tools.append(tool)

            logger.debug(
                f"Listed {len(tools)} tools for actor {self.actor_id} (after permission filtering)"
            )
            return tools

        @self.server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict[str, Any]
        ) -> list[TextContent]:  # pyright: ignore[reportUnusedFunction]
            """Execute a tool (ActingWeb action hook) with permission checking."""
            if not self.hooks:
                raise ValueError("No hooks registry available")

            # Check permission before execution
            config = _get_config_from_actor(self.actor)
            evaluator = get_permission_evaluator(config) if config else None
            trust_context = getattr(self.actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None

            if peer_id and evaluator:
                permission_result = evaluator.evaluate_permission(
                    self.actor_id, peer_id, PermissionType.TOOLS, name
                )
                if permission_result != PermissionResult.ALLOWED:
                    logger.warning(
                        f"Tool execution denied for '{name}' - peer {peer_id} lacks permission"
                    )
                    raise ValueError(
                        f"Access denied: You don't have permission to use tool '{name}'"
                    )

            # Find the corresponding action hook
            for action_name, hook_list in self.hooks._action_hooks.items():
                for hook in hook_list:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "tool":
                            tool_name = metadata.get("name", action_name)
                            if tool_name == name:
                                try:
                                    # Execute the action hook with permission verified
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

                                    logger.debug(
                                        f"Tool {name} executed successfully for actor {self.actor_id}"
                                    )
                                    return [TextContent(type="text", text=result_text)]

                                except Exception as e:
                                    logger.error(f"Error executing tool {name}: {e}")
                                    return [
                                        TextContent(
                                            type="text", text=f"Error: {str(e)}"
                                        )
                                    ]

            raise ValueError(f"Tool not found: {name}")

        # Resources handler - expose resources from hooks or static resources
        @self.server.list_resources()
        async def handle_list_resources() -> list[Resource]:  # pyright: ignore[reportUnusedFunction]
            """List available resources with permission filtering."""
            resources = []

            # Get permission evaluator and trust context
            config = _get_config_from_actor(self.actor)
            evaluator = get_permission_evaluator(config) if config else None
            trust_context = getattr(self.actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None

            # Dynamic resources from method hooks decorated with @mcp_resource
            if self.hooks and hasattr(self.hooks, "_method_hooks"):
                for method_name, hook_list in self.hooks._method_hooks.items():
                    for hook in hook_list:
                        if is_mcp_exposed(hook):
                            metadata = get_mcp_metadata(hook)
                            if metadata and metadata.get("type") == "resource":
                                uri_template = (
                                    metadata.get("uri_template")
                                    or f"actingweb://{method_name}"
                                )

                                # Check permission for this resource
                                if peer_id and evaluator:
                                    permission_result = evaluator.evaluate_permission(
                                        self.actor_id,
                                        peer_id,
                                        PermissionType.RESOURCES,
                                        uri_template,
                                    )
                                    if permission_result != PermissionResult.ALLOWED:
                                        logger.debug(
                                            f"Resource '{uri_template}' filtered out - access denied for peer {peer_id}"
                                        )
                                        continue

                                # Create a resource entry using the template
                                try:
                                    res = Resource(
                                        uri=uri_template,  # type: ignore[arg-type]
                                        name=metadata.get("name", method_name),
                                        description=metadata.get(
                                            "description",
                                            f"Resource provided by {method_name}",
                                        ),
                                        mimeType=metadata.get(
                                            "mime_type", "application/json"
                                        ),
                                    )
                                    resources.append(res)
                                except Exception as e:
                                    logger.debug(
                                        f"Skipping resource for method {method_name} due to error building descriptor: {e}"
                                    )

            logger.debug(
                f"Listed {len(resources)} resources for actor {self.actor_id} (after permission filtering)"
            )
            return resources

        @self.server.read_resource()
        async def handle_read_resource(uri: AnyUrl) -> str:  # pyright: ignore[reportUnusedFunction]
            """Read a resource by URI with permission checking."""
            uri_str = str(uri)

            # Check permission before accessing resource
            config = _get_config_from_actor(self.actor)
            evaluator = get_permission_evaluator(config) if config else None
            trust_context = getattr(self.actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None

            if peer_id and evaluator:
                permission_result = evaluator.evaluate_permission(
                    self.actor_id, peer_id, PermissionType.RESOURCES, uri_str
                )
                if permission_result != PermissionResult.ALLOWED:
                    logger.warning(
                        f"Resource access denied for '{uri_str}' - peer {peer_id} lacks permission"
                    )
                    raise ValueError(
                        f"Access denied: You don't have permission to access resource '{uri_str}'"
                    )

            try:
                if uri_str == "actingweb://properties/all":
                    # Get all non-sensitive properties
                    props = {}
                    if hasattr(self.actor, "properties") and self.actor.properties:
                        # Get property names and values, excluding sensitive ones
                        sensitive_props = {
                            "oauth_token",
                            "oauth_refresh_token",
                            "auth_token",
                            "password",
                            "secret",
                        }
                        for prop_name in dir(self.actor.properties):
                            if (
                                not prop_name.startswith("_")
                                and prop_name not in sensitive_props
                            ):
                                try:
                                    value = getattr(self.actor.properties, prop_name)
                                    if not callable(value):
                                        props[prop_name] = value
                                except Exception:
                                    pass  # Skip properties that can't be accessed

                    import json

                    return json.dumps(
                        {"actor_id": self.actor_id, "properties": props}, indent=2
                    )

                else:
                    # Try dynamic resource hooks from @mcp_resource-decorated method hooks
                    if self.hooks and hasattr(self.hooks, "_method_hooks"):
                        for method_name, hook_list in self.hooks._method_hooks.items():
                            for hook in hook_list:
                                if is_mcp_exposed(hook):
                                    metadata = get_mcp_metadata(hook)
                                    if metadata and metadata.get("type") == "resource":
                                        template = (
                                            metadata.get("uri_template")
                                            or f"actingweb://{method_name}"
                                        )

                                        # Convert template to regex and attempt a match
                                        variables: dict[str, str] | None = None
                                        try:
                                            variables = _match_uri_template(
                                                template, uri_str
                                            )
                                        except Exception:
                                            variables = None

                                        if variables is not None:
                                            # Execute the method hook with extracted variables
                                            try:
                                                result = hook(
                                                    self.actor, method_name, variables
                                                )
                                                if asyncio.iscoroutine(result):
                                                    result = await result

                                                if isinstance(result, dict):
                                                    import json

                                                    return json.dumps(result, indent=2)
                                                else:
                                                    return str(result)
                                            except Exception as e:
                                                logger.error(
                                                    f"Error reading dynamic resource via {method_name} for URI {uri_str}: {e}"
                                                )
                                                raise ValueError(
                                                    f"Error reading dynamic resource for {uri_str}: {str(e)}"
                                                ) from e

                    # If no dynamic handler matched, not found
                    raise ValueError(f"Resource not found: {uri_str}")

            except Exception as e:
                logger.error(f"Error reading resource {uri}: {e}")
                raise ValueError(f"Error reading resource {uri}: {str(e)}") from e

        # Prompts handler - expose method hooks as MCP prompts
        @self.server.list_prompts()
        async def handle_list_prompts() -> list[Prompt]:  # pyright: ignore[reportUnusedFunction]
            """List available prompts from ActingWeb method hooks with permission filtering."""
            prompts = []

            if self.hooks:
                # Get trust context and peer_id first
                trust_context = getattr(self.actor, "_mcp_trust_context", None)
                peer_id = trust_context.get("peer_id") if trust_context else None

                # Get permission evaluator and trust context
                config = _get_config_from_actor(self.actor)
                # Get permission evaluator (must be initialized at startup)
                evaluator = None
                if peer_id and config:
                    try:
                        evaluator = get_permission_evaluator(config)
                    except RuntimeError:
                        logger.debug(
                            "Permission evaluator not initialized - skipping permission checks"
                        )
                        evaluator = None
                    except Exception as e:
                        logger.warning(f"Error accessing permission evaluator: {e}")
                        evaluator = None

                for method_name, hook_list in self.hooks._method_hooks.items():
                    for hook in hook_list:
                        if is_mcp_exposed(hook):
                            metadata = get_mcp_metadata(hook)
                            if metadata and metadata.get("type") == "prompt":
                                prompt_name = metadata.get("name", method_name)

                                # Check permission for this prompt
                                if peer_id and evaluator:
                                    permission_result = evaluator.evaluate_permission(
                                        self.actor_id,
                                        peer_id,
                                        PermissionType.PROMPTS,
                                        prompt_name,
                                    )
                                    if permission_result != PermissionResult.ALLOWED:
                                        logger.debug(
                                            f"Prompt '{prompt_name}' filtered out - access denied for peer {peer_id}"
                                        )
                                        continue

                                prompt = Prompt(
                                    name=prompt_name,
                                    description=metadata.get(
                                        "description",
                                        f"Generate prompt for {method_name}",
                                    ),
                                    arguments=metadata.get("arguments", []),
                                )
                                prompts.append(prompt)

            logger.debug(
                f"Listed {len(prompts)} prompts for actor {self.actor_id} (after permission filtering)"
            )
            return prompts

        @self.server.get_prompt()
        async def handle_get_prompt(
            name: str, arguments: dict[str, str] | None
        ) -> GetPromptResult:  # pyright: ignore[reportUnusedFunction]
            """Get a prompt by name (execute method hook) with permission checking."""
            if not self.hooks:
                raise ValueError("No hooks registry available")

            # Check permission before execution
            config = _get_config_from_actor(self.actor)
            evaluator = get_permission_evaluator(config) if config else None
            trust_context = getattr(self.actor, "_mcp_trust_context", None)
            peer_id = trust_context.get("peer_id") if trust_context else None

            if peer_id and evaluator:
                permission_result = evaluator.evaluate_permission(
                    self.actor_id, peer_id, PermissionType.PROMPTS, name
                )
                if permission_result != PermissionResult.ALLOWED:
                    logger.warning(
                        f"Prompt access denied for '{name}' - peer {peer_id} lacks permission"
                    )
                    raise ValueError(
                        f"Access denied: You don't have permission to access prompt '{name}'"
                    )

            # Find the corresponding method hook
            for method_name, hook_list in self.hooks._method_hooks.items():
                for hook in hook_list:
                    if is_mcp_exposed(hook):
                        metadata = get_mcp_metadata(hook)
                        if metadata and metadata.get("type") == "prompt":
                            prompt_name = metadata.get("name", method_name)
                            if prompt_name == name:
                                try:
                                    # Execute the method hook with permission verified
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

                                    logger.debug(
                                        f"Prompt {name} generated successfully for actor {self.actor_id}"
                                    )
                                    # Return as GetPromptResult - typically contains the prompt text
                                    return GetPromptResult(
                                        description=f"Generated prompt for {name}",
                                        messages=[
                                            PromptMessage(
                                                role="user",
                                                content=TextContent(
                                                    type="text", text=prompt_text
                                                ),
                                            )
                                        ],
                                    )

                                except Exception as e:
                                    logger.error(f"Error generating prompt {name}: {e}")
                                    raise ValueError(
                                        f"Error generating prompt {name}: {str(e)}"
                                    ) from e

            raise ValueError(f"Prompt not found: {name}")


class MCPServerManager:
    """
    Manages MCP servers for ActingWeb actors using the official SDK.

    This class handles the creation and caching of MCP servers per actor,
    ensuring efficient resource usage and proper isolation between actors.
    """

    def __init__(self) -> None:
        self._servers: dict[str, ActingWebMCPServer] = {}

    def get_server(
        self, actor_id: str, hook_registry: HookRegistry, actor: ActorInterface
    ) -> ActingWebMCPServer:
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
            logger.debug(f"Created MCP server for actor {actor_id}")

        return self._servers[actor_id]

    def remove_server(self, actor_id: str) -> None:
        """Remove and cleanup MCP server for an actor."""
        if actor_id in self._servers:
            del self._servers[actor_id]
            logger.debug(f"Removed MCP server for actor {actor_id}")

    def has_server(self, actor_id: str) -> bool:
        """Check if a server exists for the given actor."""
        return actor_id in self._servers


# Global server manager instance
_server_manager: MCPServerManager | None = None


def get_server_manager() -> MCPServerManager:
    """Get or create the global MCP server manager instance."""
    global _server_manager
    if _server_manager is None:
        _server_manager = MCPServerManager()
    return _server_manager


def _match_uri_template(template: str, uri: str) -> dict[str, str] | None:
    """
    Match a URI against a simple template with {variables}.

    Returns a dict of variables if match, otherwise None.
    """
    # Build a regex from the template, replacing {var} with named groups
    pattern_parts: list[str] = []
    last_index = 0
    for m in re.finditer(r"{(\w+)}", template):
        start, end = m.span()
        var_name = m.group(1)
        # Escape static part
        pattern_parts.append(re.escape(template[last_index:start]))
        # Insert a conservative matcher for the variable (no slashes)
        pattern_parts.append(f"(?P<{var_name}>[^/]+)")
        last_index = end
    # Remainder of template
    pattern_parts.append(re.escape(template[last_index:]))
    pattern = "^" + "".join(pattern_parts) + "$"

    match = re.match(pattern, uri)
    if not match:
        return None
    return {k: v for k, v in match.groupdict().items() if v is not None}
