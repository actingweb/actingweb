"""MCP resource URI matching is whole-string (3.14.4).

``match_uri_template`` anchored with ``$`` (tolerates a trailing newline)
and the handler's legacy ``uri_pattern`` metadata was applied with
``re.match`` (a prefix match). Both now require the whole URI.
"""

import unittest
from unittest.mock import Mock, patch

from actingweb.handlers.mcp import MCPHandler
from actingweb.interface.hooks import HookRegistry
from actingweb.mcp.decorators import mcp_resource
from actingweb.mcp.uri import match_uri_template


class TestMatchUriTemplate(unittest.TestCase):
    def test_exact_match(self) -> None:
        self.assertEqual(match_uri_template("notes://{id}", "notes://7"), {"id": "7"})

    def test_trailing_newline_rejected(self) -> None:
        self.assertIsNone(match_uri_template("config://app", "config://app\n"))
        self.assertIsNone(match_uri_template("notes://{id}/x", "notes://7/x\n"))

    def test_variable_segment_accepts_newline_by_design(self) -> None:
        # The variable class is "anything but a slash"; keeping a newline
        # out of a resource URI is the permission evaluator's job (it
        # denies every identifier carrying a control character), not the
        # template matcher's.
        self.assertEqual(
            match_uri_template("notes://{id}", "notes://7\n"), {"id": "7\n"}
        )


class FakeAuthedActor:
    def __init__(self) -> None:
        self.id = "actor-1"


class TestLegacyUriPatternDispatch(unittest.TestCase):
    """``uri_pattern`` metadata must match the whole URI, not a prefix."""

    def _handler(self) -> MCPHandler:
        hooks = HookRegistry()

        @mcp_resource(uri_template="exact://only", mime_type="text/plain")
        def a_resource(actor, method_name, params):
            return {"hit": True}

        # uri_pattern is legacy, hand-authored metadata; the decorator has
        # no parameter for it.
        a_resource._mcp_metadata["uri_pattern"] = r"legacy://v"  # type: ignore[attr-defined]
        hooks.register_method_hook("a_resource", a_resource)
        handler = MCPHandler()
        handler.hooks = hooks
        return handler

    def _read(self, uri: str) -> dict:
        handler = self._handler()
        with (
            patch.object(
                MCPHandler,
                "authenticate_and_get_actor_cached",
                return_value=FakeAuthedActor(),
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
            patch("actingweb.permission_evaluator.get_permission_evaluator") as ev,
        ):
            ctx = Mock()
            ctx.peer_id = "oauth2_client:c:c"
            mock_rc.return_value.get_mcp_context.return_value = ctx
            from actingweb.permission_evaluator import PermissionResult

            ev.return_value.evaluate_permission.return_value = PermissionResult.ALLOWED
            return handler.post(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "resources/read",
                    "params": {"uri": uri},
                }
            )

    def test_full_pattern_match_dispatches(self) -> None:
        self.assertIn("result", self._read("legacy://v"))

    def test_prefix_only_match_no_longer_dispatches(self) -> None:
        resp = self._read("legacy://v/../../security/key")
        self.assertIn("error", resp)
        self.assertNotIn("result", resp)
