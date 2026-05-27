"""Tests for the configurable MCP server name and instructions.

These reach MCP clients via the live ``initialize`` response built by
``MCPHandler._handle_initialize`` — ``serverInfo.name`` from
``config.mcp_server_name`` and ``InitializeResult.instructions`` from
``config.mcp_instructions`` (set by ``ActingWebApp.with_mcp(...)``).
"""

from actingweb import aw_web_request, config
from actingweb.handlers.mcp import MCPHandler


def _make_config(
    *, server_name: str | None = None, instructions: str | None = None
) -> config.Config:
    cfg = config.Config()
    cfg.fqdn = "test.example.com"
    cfg.proto = "https://"
    cfg.aw_type = "urn:actingweb:test:mcp_name"
    cfg.devtest = True
    if server_name is not None:
        cfg.mcp_server_name = server_name
    cfg.mcp_instructions = instructions
    return cfg


def _initialize(cfg: config.Config) -> dict:
    webobj = aw_web_request.AWWebObj(
        url="https://test.example.com/mcp",
        params={},
        body="",
        headers={},
        cookies={},
    )
    handler = MCPHandler(webobj, cfg, hooks=None)
    return handler.post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "test-client", "version": "1.0"}},
        }
    )


class TestServerNameInInitialize:
    def test_default_server_name_is_actingweb(self) -> None:
        result = _initialize(_make_config())["result"]
        assert result["serverInfo"]["name"] == "actingweb"

    def test_custom_server_name_surfaced(self) -> None:
        result = _initialize(_make_config(server_name="emm"))["result"]
        assert result["serverInfo"]["name"] == "emm"


class TestInstructionsInInitialize:
    def test_no_instructions_omits_field(self) -> None:
        result = _initialize(_make_config())["result"]
        assert "instructions" not in result

    def test_instructions_surfaced(self) -> None:
        result = _initialize(
            _make_config(server_name="emm", instructions="Call how_to_use() first")
        )["result"]
        assert result["instructions"] == "Call how_to_use() first"
