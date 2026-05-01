"""Tests for the visibility_predicate parameter on @mcp_tool.

The predicate gates whether a tool appears in tools/list for a given actor.
Tools without a predicate are always visible (regression). Predicate
exceptions are treated as "not visible" (fail-closed).
"""

import unittest
from unittest.mock import Mock, patch

from actingweb.handlers.mcp import MCPHandler
from actingweb.interface.hooks import HookRegistry
from actingweb.mcp.decorators import get_mcp_metadata, mcp_tool


class FakeActor:
    def __init__(self, actor_id: str = "actor1", peer_id: str = "") -> None:
        self.id = actor_id
        self._mcp_trust_context = {"peer_id": peer_id} if peer_id else {}


class TestVisibilityPredicateMetadata(unittest.TestCase):
    def test_default_predicate_is_none(self) -> None:
        @mcp_tool(description="x")
        def f(actor, action_name, data):
            return {}

        metadata = get_mcp_metadata(f)
        assert metadata is not None
        self.assertIsNone(metadata.get("visibility_predicate"))

    def test_predicate_stored_on_metadata(self) -> None:
        sentinel = lambda actor: True  # noqa: E731

        @mcp_tool(description="x", visibility_predicate=sentinel)
        def f(actor, action_name, data):
            return {}

        metadata = get_mcp_metadata(f)
        assert metadata is not None
        self.assertIs(metadata.get("visibility_predicate"), sentinel)


def _make_hooks_with_predicates(predicates: dict) -> HookRegistry:
    """Build hooks where each tool name maps to its visibility predicate."""
    hooks = HookRegistry()

    for tool_name, predicate in predicates.items():

        def make_hook(name=tool_name):
            @mcp_tool(description=f"tool {name}", visibility_predicate=predicate)
            def hook(actor, action_name, data):
                return {"name": name}

            return hook

        hooks.register_action_hook(tool_name, make_hook())

    return hooks


class TestVisibilityPredicateFiltering(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = FakeActor()
        self.handler = MCPHandler()

    def _list_tool_names(self) -> set[str]:
        with patch.object(
            MCPHandler, "authenticate_and_get_actor_cached", return_value=self.actor
        ), patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc:
            mock_mcp_context = Mock()
            mock_mcp_context.peer_id = None
            mock_rc.return_value.get_mcp_context.return_value = mock_mcp_context
            resp = self.handler.post(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "tools/list",
                    "params": {},
                }
            )
        return {t.get("name") for t in resp.get("result", {}).get("tools", [])}

    def test_predicate_false_omits_tool(self) -> None:
        self.handler.hooks = _make_hooks_with_predicates(
            {
                "visible_tool": lambda actor: True,
                "hidden_tool": lambda actor: False,
            }
        )
        names = self._list_tool_names()
        self.assertIn("visible_tool", names)
        self.assertNotIn("hidden_tool", names)

    def test_no_predicate_is_visible(self) -> None:
        hooks = HookRegistry()

        @mcp_tool(description="legacy")
        def legacy(actor, action_name, data):
            return {}

        hooks.register_action_hook("legacy_tool", legacy)
        self.handler.hooks = hooks
        names = self._list_tool_names()
        self.assertIn("legacy_tool", names)

    def test_predicate_exception_fails_closed(self) -> None:
        def boom(actor):
            raise RuntimeError("kaboom")

        self.handler.hooks = _make_hooks_with_predicates({"crash_tool": boom})
        names = self._list_tool_names()
        self.assertNotIn("crash_tool", names)

    def test_predicate_receives_actor(self) -> None:
        seen: list = []

        def capture(actor):
            seen.append(actor)
            return True

        self.handler.hooks = _make_hooks_with_predicates({"observe_tool": capture})
        self._list_tool_names()
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0], self.actor)


if __name__ == "__main__":
    unittest.main()
