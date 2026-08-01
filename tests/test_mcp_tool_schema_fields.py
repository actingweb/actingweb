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
from actingweb.permission_evaluator import PermissionResult

# A resolved (truthy) peer id. Since Phase 3, tools/list fails closed to an
# empty list when no trust relationship resolved, so this test -- about
# schema-field serialisation, not permissions -- needs a real peer id and an
# allow-everything evaluator to reach any tools at all.
_PEER_ID = "oauth2_client:client-1:client-1"


class FakeActor:
    def __init__(self, actor_id: str = "actor1") -> None:
        self.id = actor_id
        # Peer id, when needed, is supplied via a mocked RuntimeContext in
        # each test — the real auth path sets it there, not on the actor.


def _list_tools(handler: MCPHandler, actor: FakeActor) -> list:
    evaluator = Mock()
    evaluator.evaluate_permission = Mock(return_value=PermissionResult.ALLOWED)
    with (
        patch.object(
            MCPHandler, "authenticate_and_get_actor_cached", return_value=actor
        ),
        patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
        patch(
            "actingweb.permission_evaluator.get_permission_evaluator",
            return_value=evaluator,
        ),
    ):
        mock_mcp_context = Mock()
        mock_mcp_context.peer_id = _PEER_ID
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
