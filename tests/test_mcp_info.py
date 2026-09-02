"""``GET /mcp/info`` is derived, not literal (3.14.4).

Until 3.14.4 both integrations carried a byte-identical dict with
``tools_count: 4``, ``prompts_count: 3``, ``actor_lookup: "email_based"``
and the demo application's description, whatever the app actually
registered. The document is the ``resource_documentation`` target of the
OAuth discovery chain and is unauthenticated, so it is now built by one
function from config scalars and the in-memory hook registry only. The
routes themselves are exercised in tests/integration/test_mcp_info_route.py.
"""

from actingweb.handlers.mcp import build_mcp_info
from actingweb.interface.hooks import HookRegistry
from actingweb.mcp.decorators import mcp_prompt, mcp_tool
from tests.mcp_helpers import make_mcp_config

REMOVED_KEYS = ("tools_count", "prompts_count", "actor_lookup", "version")


class TestBuilder:
    def test_empty_registry_has_no_features(self) -> None:
        info = build_mcp_info(make_mcp_config(), HookRegistry())
        assert info["supported_features"] == []
        assert info["mcp_enabled"] is True
        assert info["server_name"] == "actingweb"
        for key in REMOVED_KEYS:
            assert key not in info

    def test_features_follow_the_registry(self) -> None:
        hooks = HookRegistry()

        @mcp_tool(description="a tool")
        def a_tool(actor, action_name, data):
            return {}

        @mcp_prompt(description="a prompt")
        def a_prompt(actor, method_name, data):
            return {}

        hooks.register_action_hook("a_tool", a_tool)
        assert build_mcp_info(make_mcp_config(), hooks)["supported_features"] == [
            "tools"
        ]
        hooks.register_method_hook("a_prompt", a_prompt)
        assert build_mcp_info(make_mcp_config(), hooks)["supported_features"] == [
            "tools",
            "prompts",
        ]

    def test_mcp_enabled_follows_config(self) -> None:
        cfg = make_mcp_config()
        cfg.mcp = False
        assert build_mcp_info(cfg, None)["mcp_enabled"] is False

    def test_server_name_and_description_follow_config(self) -> None:
        cfg = make_mcp_config(server_name="emm")
        cfg.desc = "ActingWeb app: urn:actingweb:test:mcp_info"
        info = build_mcp_info(cfg, None)
        assert info["server_name"] == "emm"
        assert info["description"] == "ActingWeb app: urn:actingweb:test:mcp_info"
        assert "Demo" not in info["description"]

    def test_authentication_block_unchanged(self) -> None:
        info = build_mcp_info(make_mcp_config(), None)
        auth = info["authentication"]
        assert auth["discovery_url"] == (
            "https://test.example.com/.well-known/oauth-authorization-server"
        )
        assert auth["resource_discovery_url"] == (
            "https://test.example.com/.well-known/oauth-protected-resource"
        )
        assert info["mcp_endpoint"] == "/mcp"
