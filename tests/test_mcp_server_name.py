"""Tests for the configurable MCP server name and instructions.

These reach MCP clients via the live ``initialize`` response built by
``MCPHandler._handle_initialize`` — ``serverInfo.name`` from
``config.mcp_server_name`` and ``InitializeResult.instructions`` from
``config.mcp_instructions`` (set by ``ActingWebApp.with_mcp(...)``).
"""

from actingweb import config
from tests.mcp_helpers import make_mcp_config, make_mcp_handler


def _initialize(cfg: config.Config) -> dict:
    handler = make_mcp_handler(cfg=cfg)
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
        result = _initialize(make_mcp_config())["result"]
        assert result["serverInfo"]["name"] == "actingweb"

    def test_custom_server_name_surfaced(self) -> None:
        result = _initialize(make_mcp_config(server_name="emm"))["result"]
        assert result["serverInfo"]["name"] == "emm"


class TestInstructionsInInitialize:
    def test_no_instructions_omits_field(self) -> None:
        result = _initialize(make_mcp_config())["result"]
        assert "instructions" not in result

    def test_instructions_surfaced(self) -> None:
        result = _initialize(
            make_mcp_config(server_name="emm", instructions="Call how_to_use() first")
        )["result"]
        assert result["instructions"] == "Call how_to_use() first"


class TestWithMcpBuilderPropagation:
    """with_mcp() settings must reach Config even though __init__ builds the
    Config eagerly (via the permission-system warmup) before the fluent
    builder methods run. Regression test for the builder->config sync gap.
    """

    def _app(self, **mcp_kwargs):
        from actingweb.interface import ActingWebApp

        return ActingWebApp(
            aw_type="urn:actingweb:test:mcpbuild",
            database="dynamodb",
            fqdn="localhost:5000",
        ).with_mcp(**mcp_kwargs)

    def test_server_name_reaches_config(self) -> None:
        cfg = self._app(enable=True, server_name="doctest").get_config()
        assert cfg.mcp_server_name == "doctest"

    def test_instructions_reach_config(self) -> None:
        cfg = self._app(
            enable=True, instructions="Call how_to_use() first"
        ).get_config()
        assert cfg.mcp_instructions == "Call how_to_use() first"

    def test_enable_false_reaches_config(self) -> None:
        cfg = self._app(enable=False).get_config()
        assert cfg.mcp is False

    def test_custom_server_name_surfaced_in_initialize_via_builder(self) -> None:
        cfg = self._app(enable=True, server_name="doctest").get_config()
        result = _initialize(cfg)["result"]
        assert result["serverInfo"]["name"] == "doctest"
