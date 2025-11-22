"""
MCP (Model Context Protocol) integration for ActingWeb.

This module provides integration between ActingWeb and the Model Context Protocol,
allowing ActingWeb actors to expose their functionality to AI language models
and MCP-compatible clients.

This module provides only the infrastructure (decorators, handlers, server management).
Business logic for specific MCP tools and prompts should be implemented in individual
applications.
"""

from .decorators import mcp_prompt, mcp_resource, mcp_tool
from .sdk_server import MCPServerManager, get_server_manager

__all__ = [
    "mcp_tool",
    "mcp_resource",
    "mcp_prompt",
    "MCPServerManager",
    "get_server_manager",
]
