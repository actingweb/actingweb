"""
MCP (Model Context Protocol) integration for ActingWeb.

This module provides integration between ActingWeb and the Model Context Protocol,
allowing ActingWeb actors to expose their functionality to AI language models
and MCP-compatible clients.

ActingWeb implements the MCP protocol by hand in ``actingweb/handlers/mcp.py``
(and ``async_mcp.py``); it does not depend on the official ``mcp`` SDK. This
module provides only the infrastructure (decorators). Business logic for
specific MCP tools and prompts should be implemented in individual applications.
"""

from .decorators import mcp_prompt, mcp_resource, mcp_tool

__all__ = [
    "mcp_tool",
    "mcp_resource",
    "mcp_prompt",
]
