"""
.with_mcp(enable=False) must actually disable /mcp.

The Flask and FastAPI integrations register the /mcp route unconditionally
(so config.mcp can be toggled without touching route setup), which means
MCPHandler.get()/.post() and AsyncMCPHandler.post_async() are the only
place that can gate on it. They didn't, until now: an app that called
.with_mcp(enable=False) (or never called .with_mcp() and built a bare
Config directly) still ran a fully live MCP server. Found while building
examples/demo/, which explicitly disables MCP.
"""

from actingweb.handlers.async_mcp import AsyncMCPHandler
from tests.mcp_helpers import make_mcp_config, make_mcp_handler, make_mcp_webobj


def test_get_404s_when_mcp_disabled():
    cfg = make_mcp_config()
    cfg.mcp = False
    handler = make_mcp_handler(cfg=cfg)

    result = handler.get()

    assert handler.response.status_code == 404
    assert result.get("status_code") == 404


def test_post_404s_when_mcp_disabled():
    cfg = make_mcp_config()
    cfg.mcp = False
    handler = make_mcp_handler(cfg=cfg)

    result = handler.post({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    assert handler.response.status_code == 404
    assert result.get("status_code") == 404


async def test_post_async_404s_when_mcp_disabled():
    cfg = make_mcp_config()
    cfg.mcp = False
    handler = AsyncMCPHandler(make_mcp_webobj(), cfg)

    result = await handler.post_async(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    )

    assert handler.response.status_code == 404
    assert result.get("status_code") == 404


def test_get_serves_normally_when_mcp_enabled():
    """Sanity check the gate isn't inverted or unconditional."""
    handler = make_mcp_handler()  # make_mcp_config() defaults mcp=True

    result = handler.get()

    assert handler.response.status_code != 404
    assert result.get("server_name") == "actingweb-mcp"
