"""
MCP decorators for exposing ActingWeb functionality through the Model Context Protocol.

These decorators are used to mark ActingWeb hooks as MCP-exposed functionality:
- @mcp_tool: Expose actions as MCP tools
- @mcp_resource: Expose resources as MCP resources
- @mcp_prompt: Expose methods as MCP prompts
"""

from typing import Optional, List, Dict, Any, Callable


def mcp_tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    input_schema: Optional[Dict[str, Any]] = None
) -> Callable[..., Any]:
    """
    Decorator to expose an ActingWeb action as an MCP tool.
    
    Args:
        name: Override name for the tool (defaults to action name)
        description: Human-readable description of what the tool does
        input_schema: JSON schema describing expected parameters
    
    Example:
        @action_hook("send_notification")
        @mcp_tool(description="Send a notification to the user")
        def handle_notification(actor, action_name, data):
            return {"status": "sent"}
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(func, '_mcp_type', "tool")
        setattr(func, '_mcp_metadata', {
            "name": name,
            "description": description,
            "input_schema": input_schema
        })
        return func
    return decorator


def mcp_resource(
    uri_template: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    mime_type: str = "application/json"
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
        setattr(func, '_mcp_type', "resource")
        setattr(func, '_mcp_metadata', {
            "uri_template": uri_template,
            "name": name,
            "description": description,
            "mime_type": mime_type
        })
        return func
    return decorator


def mcp_prompt(
    name: Optional[str] = None,
    description: Optional[str] = None,
    arguments: Optional[List[Dict[str, Any]]] = None
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
        setattr(func, '_mcp_type', "prompt")
        setattr(func, '_mcp_metadata', {
            "name": name,
            "description": description,
            "arguments": arguments or []
        })
        return func
    return decorator


def get_mcp_metadata(func: Callable[..., Any]) -> Optional[Dict[str, Any]]:
    """Get MCP metadata from a decorated function."""
    if hasattr(func, '_mcp_type') and hasattr(func, '_mcp_metadata'):
        return {
            "type": getattr(func, '_mcp_type'),
            **getattr(func, '_mcp_metadata')
        }
    return None


def is_mcp_exposed(func: Callable[..., Any]) -> bool:
    """Check if a function is exposed through MCP."""
    return hasattr(func, '_mcp_type')