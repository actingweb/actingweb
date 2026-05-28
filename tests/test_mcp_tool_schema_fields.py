"""Tests for ``title`` and ``outputSchema`` serialisation on tools/list.

``@mcp_tool`` accepts ``title`` and ``output_schema``; both must round-trip
through the ``/mcp`` ``tools/list`` builder. Hosts that key on the MCP
2025-11-25 ``Tool.title`` (e.g. Claude Code's tool-permission dialog) need
``title``, and clients supporting structured output need ``outputSchema``
to validate against.
"""

import unittest
from unittest.mock import Mock, patch

from actingweb.handlers.mcp import MCPHandler
from actingweb.interface.hooks import HookRegistry
from actingweb.mcp.decorators import mcp_tool


class FakeActor:
    def __init__(self, actor_id: str = "actor1", peer_id: str = "") -> None:
        self.id = actor_id
        self._mcp_trust_context = {"peer_id": peer_id} if peer_id else {}


def _list_tools(handler: MCPHandler, actor: FakeActor) -> list:
    with patch.object(
        MCPHandler, "authenticate_and_get_actor_cached", return_value=actor
    ), patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc:
        mock_mcp_context = Mock()
        mock_mcp_context.peer_id = None
        mock_rc.return_value.get_mcp_context.return_value = mock_mcp_context
        resp = handler.post(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/list",
                "params": {},
            }
        )
    return resp.get("result", {}).get("tools", [])


class TestToolSchemaFieldSerialisation(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = FakeActor()
        self.handler = MCPHandler()

    def test_title_and_output_schema_are_serialised(self) -> None:
        hooks = HookRegistry()
        output_schema = {
            "type": "object",
            "properties": {"result": {"type": "string"}},
        }

        @mcp_tool(
            description="x",
            title="Friendly Title",
            output_schema=output_schema,
        )
        def hook(actor, action_name, data):
            return {}

        hooks.register_action_hook("t", hook)
        self.handler.hooks = hooks

        tools = _list_tools(self.handler, self.actor)
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool.get("title"), "Friendly Title")
        self.assertEqual(tool.get("outputSchema"), output_schema)

    def test_omitted_when_unset(self) -> None:
        hooks = HookRegistry()

        @mcp_tool(description="x")
        def hook(actor, action_name, data):
            return {}

        hooks.register_action_hook("t", hook)
        self.handler.hooks = hooks

        tools = _list_tools(self.handler, self.actor)
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertNotIn("title", tool)
        self.assertNotIn("outputSchema", tool)

    def test_only_title_set(self) -> None:
        hooks = HookRegistry()

        @mcp_tool(description="x", title="T")
        def hook(actor, action_name, data):
            return {}

        hooks.register_action_hook("t", hook)
        self.handler.hooks = hooks

        tool = _list_tools(self.handler, self.actor)[0]
        self.assertEqual(tool.get("title"), "T")
        self.assertNotIn("outputSchema", tool)

    def test_only_output_schema_set(self) -> None:
        hooks = HookRegistry()
        schema = {"type": "object"}

        @mcp_tool(description="x", output_schema=schema)
        def hook(actor, action_name, data):
            return {}

        hooks.register_action_hook("t", hook)
        self.handler.hooks = hooks

        tool = _list_tools(self.handler, self.actor)[0]
        self.assertNotIn("title", tool)
        self.assertEqual(tool.get("outputSchema"), schema)


if __name__ == "__main__":
    unittest.main()
