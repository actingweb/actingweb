"""
MCP decorators for exposing ActingWeb functionality through the Model Context Protocol.

These decorators are used to mark ActingWeb hooks as MCP-exposed functionality:
- @mcp_tool: Expose actions as MCP tools
- @mcp_resource: Expose resources as MCP resources
- @mcp_prompt: Expose methods as MCP prompts
"""

from collections.abc import Callable
from typing import Any


def mcp_tool(
    name: str | None = None,
    description: str | None = None,
    input_schema: dict[str, Any] | None = None,
    allowed_clients: list[str] | None = None,
    client_descriptions: dict[str, str] | None = None,
    title: str | None = None,
    output_schema: dict[str, Any] | None = None,
    annotations: dict[str, Any] | None = None,
) -> Callable[..., Any]:
    """
    Decorator to expose an ActingWeb action as an MCP tool.

    Args:
        name: Override name for the tool (defaults to action name)
        description: Human-readable description of what the tool does
        input_schema: JSON schema describing expected parameters
        allowed_clients: List of client types that can access this tool.
                        If None, tool is available to all clients.
                        Example: ["chatgpt", "claude", "cursor"]
        client_descriptions: Client-specific descriptions for safety/clarity.
                           Example: {"chatgpt": "Search your personal notes", "claude": "Search and store information"}
        title: Human-readable title for the tool (optional)
        output_schema: JSON schema describing the tool's output (optional)
        annotations: Safety and behavior annotations for the tool.
                    IMPORTANT: ChatGPT uses these for safety evaluation.
                    Example: {
                        "destructiveHint": True,  # Tool can cause destructive changes
                        "readOnlyHint": False,    # Tool modifies data
                        "idempotentHint": False,  # Repeated calls have different effects
                        "openWorldHint": False    # Tool doesn't interact with outside world
                    }

    Example:
        @action_hook("delete_note")
        @mcp_tool(
            description="Delete a note permanently",
            annotations={"destructiveHint": True, "readOnlyHint": False}
        )
        def handle_delete(actor, action_name, data):
            return {"status": "deleted"}

        @action_hook("search")
        @mcp_tool(
            description="Search your notes",
            annotations={"readOnlyHint": True, "destructiveHint": False}
        )
        def handle_search(actor, action_name, data):
            return {"results": [...]}
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, "_mcp_type", "tool")  # noqa: B010
        setattr(func, "_mcp_metadata", {  # noqa: B010
            "name": name,
            "description": description,
            "input_schema": input_schema,
            "allowed_clients": allowed_clients,
            "client_descriptions": client_descriptions or {},
            "title": title,
            "output_schema": output_schema,
            "annotations": annotations,
        })
        return func

    return decorator


def mcp_resource(
    uri_template: str | None = None,
    name: str | None = None,
    description: str | None = None,
    mime_type: str = "application/json",
) -> Callable[..., Any]:
    """
    Decorator to expose an ActingWeb resource as an MCP resource.

    Args:
        uri_template: URI template for the resource (e.g., "config://{path}")
        name: Override name for the resource
        description: Human-readable description of the resource
        mime_type: MIME type of the resource content

    Example:
        @resource_hook("config")
        @mcp_resource(uri_template="config://{path}")
        def get_config(actor, path):
            return {"setting": "value"}
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, "_mcp_type", "resource")  # noqa: B010
        setattr(func, "_mcp_metadata", {  # noqa: B010
            "uri_template": uri_template,
            "name": name,
            "description": description,
            "mime_type": mime_type,
        })
        return func

    return decorator


def mcp_prompt(
    name: str | None = None,
    description: str | None = None,
    arguments: list[dict[str, Any]] | None = None,
) -> Callable[..., Any]:
    """
    Decorator to expose an ActingWeb method as an MCP prompt.

    Args:
        name: Override name for the prompt
        description: Human-readable description of the prompt
        arguments: List of argument definitions for the prompt

    Example:
        @method_hook("generate_report")
        @mcp_prompt(
            description="Generate a report",
            arguments=[
                {"name": "report_type", "description": "Type of report", "required": True},
                {"name": "date_range", "description": "Date range for report", "required": False}
            ]
        )
        def generate_report_prompt(actor, method_name, data):
            return f"Generate a {data.get('report_type')} report"
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, "_mcp_type", "prompt")  # noqa: B010
        setattr(func, "_mcp_metadata", {  # noqa: B010
            "name": name,
            "description": description,
            "arguments": arguments or [],
        })
        return func

    return decorator


def get_mcp_metadata(func: Callable[..., Any]) -> dict[str, Any] | None:
    """Get MCP metadata from a decorated function."""
    if hasattr(func, "_mcp_type") and hasattr(func, "_mcp_metadata"):
        mcp_type = getattr(func, "_mcp_type")  # noqa: B009
        mcp_metadata = getattr(func, "_mcp_metadata")  # noqa: B009
        return {"type": mcp_type, **mcp_metadata}
    return None


def is_mcp_exposed(func: Callable[..., Any]) -> bool:
    """Check if a function is exposed through MCP."""
    return hasattr(func, "_mcp_type")
