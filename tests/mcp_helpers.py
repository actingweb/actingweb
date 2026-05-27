"""Shared helpers for MCP handler unit tests.

Centralizes the small bits of setup (config + framework-agnostic request
object + handler construction) that several MCP test modules need, so they
don't each re-declare them.
"""

from actingweb import aw_web_request, config
from actingweb.handlers.mcp import MCPHandler


def make_mcp_config(
    *, server_name: str | None = None, instructions: str | None = None
) -> config.Config:
    """Build a minimal Config suitable for MCP handler tests."""
    cfg = config.Config()
    cfg.fqdn = "test.example.com"
    cfg.proto = "https://"
    cfg.aw_type = "urn:actingweb:test:mcp"
    cfg.devtest = True
    if server_name is not None:
        cfg.mcp_server_name = server_name
    cfg.mcp_instructions = instructions
    return cfg


def make_mcp_webobj(headers: dict[str, str] | None = None) -> aw_web_request.AWWebObj:
    """Build an AWWebObj pointed at /mcp with optional request headers."""
    return aw_web_request.AWWebObj(
        url="https://test.example.com/mcp",
        params={},
        body="",
        headers=headers or {},
        cookies={},
    )


def make_mcp_handler(
    headers: dict[str, str] | None = None,
    *,
    cfg: config.Config | None = None,
    hooks=None,
) -> MCPHandler:
    """Build a sync MCPHandler with an optional header set, config, and hooks."""
    return MCPHandler(make_mcp_webobj(headers), cfg or make_mcp_config(), hooks=hooks)
