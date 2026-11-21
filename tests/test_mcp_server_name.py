"""Tests for the configurable MCP server name and instructions.

These reach MCP clients via the live ``initialize`` response built by
``MCPHandler._handle_initialize`` — ``serverInfo.name`` from
``config.mcp_server_name`` and ``InitializeResult.instructions`` from
``config.mcp_instructions`` (set by ``ActingWebApp.with_mcp(...)``).
"""

from typing import Any

import pytest

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


class TestGetMcpAgreesWithInitialize:
    """``GET /mcp`` derives server_name and capabilities the same way
    ``initialize`` does (3.14.4); before, it announced ``actingweb-mcp`` and
    three literal ``True`` capabilities regardless of configuration."""

    def _get(self, cfg, hooks=None):
        handler = make_mcp_handler(cfg=cfg, hooks=hooks)
        handler.authenticate_and_get_actor_cached = lambda: object()
        return handler.get()

    def test_server_name_matches(self) -> None:
        cfg = make_mcp_config(server_name="emm")
        assert self._get(cfg)["server_name"] == "emm"
        assert self._get(make_mcp_config())["server_name"] == "actingweb"

    def test_capabilities_follow_the_registry(self) -> None:
        from actingweb.interface.hooks import HookRegistry
        from actingweb.mcp.decorators import mcp_tool

        hooks = HookRegistry()
        body = self._get(make_mcp_config(), hooks)
        assert body["capabilities"] == {
            "tools": False,
            "resources": False,
            "prompts": False,
        }

        @mcp_tool(description="a tool")
        def a_tool(actor, action_name, data):
            return {}

        hooks.register_action_hook("a_tool", a_tool)
        body = self._get(make_mcp_config(), hooks)
        assert body["capabilities"]["tools"] is True
        assert body["capabilities"]["prompts"] is False


def _all_three_hooks():
    from actingweb.interface.hooks import HookRegistry
    from actingweb.mcp.decorators import mcp_prompt, mcp_resource, mcp_tool

    hooks = HookRegistry()

    @mcp_tool(description="a tool")
    def a_tool(actor, action_name, data):
        return {}

    @mcp_resource(uri_template="notes://{id}", description="a resource")
    def a_resource(actor, method_name, data):
        return {}

    @mcp_prompt(description="a prompt")
    def a_prompt(actor, method_name, data):
        return {}

    hooks.register_action_hook("a_tool", a_tool)
    hooks.register_method_hook("a_resource", a_resource)
    hooks.register_method_hook("a_prompt", a_prompt)
    return hooks


def test_initialize_advertises_no_list_change_notifications() -> None:
    # 4.0: the server never sends notifications/*/list_changed.
    handler = make_mcp_handler(cfg=make_mcp_config(), hooks=_all_three_hooks())
    result = handler.post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "test-client", "version": "1.0"}},
        }
    )["result"]
    capabilities = result["capabilities"]
    for kind in ("tools", "resources", "prompts"):
        assert capabilities[kind]["listChanged"] is False, kind


class TestServerVersionInInitialize:
    """``with_mcp(server_version=...)`` (4.0.0rc2,
    plans/2026-11-21-trust-request-answer-secret.md phase 3)."""

    def _app(self) -> Any:
        from actingweb.interface import ActingWebApp

        return ActingWebApp(
            aw_type="urn:actingweb:test:mcpversion",
            database="dynamodb",
            fqdn="localhost:5000",
        )

    def test_the_app_announces_its_version(self) -> None:
        """AC-16: through the builder, so the runtime re-apply is covered."""
        cfg = self._app().with_mcp(enable=True, server_version="2.3.1").get_config()
        assert _initialize(cfg)["result"]["serverInfo"]["version"] == "2.3.1"

    def test_a_later_call_keeps_the_version(self) -> None:
        app = self._app().with_mcp(enable=True, server_version="2.3.1")
        cfg = app.with_mcp(enable=True, server_name="other").get_config()
        assert _initialize(cfg)["result"]["serverInfo"]["version"] == "2.3.1"

    def test_the_default_is_the_library_version(self) -> None:
        """AC-17 (regression): unset, the library's version, also when the
        application sets its own with with_app_version()."""
        from actingweb import __version__

        plain = self._app().with_mcp(enable=True).get_config()
        assert _initialize(plain)["result"]["serverInfo"]["version"] == __version__
        app = self._app().with_app_version("9.9").with_mcp(enable=True)
        versioned = app.get_config()
        assert versioned.version == "9.9"
        assert _initialize(versioned)["result"]["serverInfo"]["version"] == __version__

    @pytest.mark.parametrize("value", ["", "   ", 5, None])
    def test_an_invalid_server_version_is_refused(self, value: Any) -> None:
        """AC-33: as with_app_version() refuses the same value."""
        with pytest.raises(ValueError):
            self._app().with_app_version(value)
        with pytest.raises(ValueError):
            self._app().with_mcp(enable=True, server_version=value)
