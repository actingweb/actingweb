"""
MCP (Model Context Protocol) integration for ActingWeb.

This module provides integration between ActingWeb and the Model Context Protocol,
allowing ActingWeb actors to expose their functionality to AI language models
and MCP-compatible clients.
"""

from .decorators import mcp_tool, mcp_resource, mcp_prompt
from .server import create_mcp_server, MCPServerManager

__all__ = [
    "mcp_tool",
    "mcp_resource", 
    "mcp_prompt",
    "create_mcp_server",
    "MCPServerManager"
]