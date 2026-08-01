"""Regression tests for sync `resources/read` authorization (research C8).

`mcp.py:_handle_resource_read` used to read a permission guard from a direct
actor attribute that no production code wrote (it was orphaned when the MCP
SDK was dropped). In a live request that guard was never entered, so
`resources/read` had no authorization check at all on the Flask path.
FastAPI's `AsyncMCPHandler._handle_resource_read_async` reads `RuntimeContext`
correctly and was never affected.

These tests exercise the real `_handle_resource_read` / `_handle_resource_read_async`
dispatch through `MCPHandler.post` / `AsyncMCPHandler.post_async`, with
`RuntimeContext` and the permission evaluator mocked -- matching the existing
`test_mcp_permissions.py` pattern -- so the assertion that could not previously
be written (the check never ran) can now be made.
"""

import asyncio
import unittest
from unittest.mock import Mock, patch

from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import MCPHandler
from actingweb.interface.hooks import HookRegistry
from actingweb.mcp.decorators import mcp_resource
from actingweb.permission_evaluator import PermissionResult, PermissionType


def make_hooks() -> HookRegistry:
    hooks = HookRegistry()

    @mcp_resource(uri_template="notes://{id}", mime_type="text/plain")
    def get_note(actor, method_name, params):
        return {"note": "hello"}

    hooks.register_method_hook("get_note", get_note)
    return hooks


class FakeActor:
    def __init__(self, actor_id: str = "actor1") -> None:
        self.id = actor_id


def _eval_perm_allow_notes(actor_id, peer_id, perm_type, target, operation="access"):
    """Allows only the "allowed" peer to read notes://1; denies everyone else."""
    if (
        perm_type == PermissionType.RESOURCES
        and target == "notes://1"
        and peer_id == "oauth2_client:allowed:allowed"
    ):
        return PermissionResult.ALLOWED
    return PermissionResult.DENIED


class TestSyncResourceReadPermissions(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = FakeActor()
        self.handler = MCPHandler()
        self.handler.hooks = make_hooks()

    def _read(self, uri: str, peer_id: str | None):
        with (
            patch.object(
                MCPHandler,
                "authenticate_and_get_actor_cached",
                return_value=self.actor,
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
            patch(
                "actingweb.permission_evaluator.get_permission_evaluator"
            ) as mock_get_eval,
        ):
            mock_mcp_context = Mock()
            mock_mcp_context.peer_id = peer_id
            mock_rc.return_value.get_mcp_context.return_value = mock_mcp_context

            mock_eval = Mock()
            mock_eval.evaluate_permission = Mock(side_effect=_eval_perm_allow_notes)
            mock_get_eval.return_value = mock_eval

            return self.handler.post(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "resources/read",
                    "params": {"uri": uri},
                }
            )

    def test_denies_when_peer_lacks_permission(self) -> None:
        resp = self._read("notes://1", peer_id="oauth2_client:blocked:blocked")
        self.assertIn("error", resp)
        self.assertEqual(resp["error"].get("code"), -32003)

    def test_allows_when_peer_has_permission(self) -> None:
        resp = self._read("notes://1", peer_id="oauth2_client:allowed:allowed")
        self.assertIn("result", resp)
        self.assertNotIn("error", resp)

    def test_no_trust_denies_without_crashing(self) -> None:
        """peer_id=None (no runtime context / no resolved trust) denies
        cleanly with -32003, rather than crashing or falling open (Phase 3
        fail-closed authorization -- see research finding on missing trust).
        """
        resp = self._read("notes://1", peer_id=None)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"].get("code"), -32003)
        self.assertIn("no trust relationship", resp["error"].get("message", ""))


class TestSyncAsyncResourceReadParity(unittest.TestCase):
    """Sync and async resources/read must reach the same decision."""

    def _sync_decision(self, peer_id: str | None) -> bool:
        handler = MCPHandler()
        handler.hooks = make_hooks()
        actor = FakeActor()
        with (
            patch.object(
                MCPHandler, "authenticate_and_get_actor_cached", return_value=actor
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
            patch(
                "actingweb.permission_evaluator.get_permission_evaluator"
            ) as mock_get_eval,
        ):
            mock_mcp_context = Mock()
            mock_mcp_context.peer_id = peer_id
            mock_rc.return_value.get_mcp_context.return_value = mock_mcp_context
            mock_eval = Mock()
            mock_eval.evaluate_permission = Mock(side_effect=_eval_perm_allow_notes)
            mock_get_eval.return_value = mock_eval

            resp = handler.post(
                {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "resources/read",
                    "params": {"uri": "notes://1"},
                }
            )
        return "error" not in resp

    def _async_decision(self, peer_id: str | None) -> bool:
        handler = AsyncMCPHandler()
        handler.hooks = make_hooks()
        actor = FakeActor()
        with (
            patch.object(
                AsyncMCPHandler,
                "authenticate_and_get_actor_cached",
                return_value=actor,
            ),
            # Async handlers resolve peer_id via the inherited
            # MCPHandler._require_mcp_peer_id(), which is defined in mcp.py
            # and uses that module's own RuntimeContext import -- patch it
            # there, not on async_mcp or the runtime_context source module.
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
            patch(
                "actingweb.permission_evaluator.get_permission_evaluator"
            ) as mock_get_eval,
        ):
            mock_mcp_context = Mock()
            mock_mcp_context.peer_id = peer_id
            mock_rc.return_value.get_mcp_context.return_value = mock_mcp_context
            mock_eval = Mock()
            mock_eval.evaluate_permission = Mock(side_effect=_eval_perm_allow_notes)
            mock_get_eval.return_value = mock_eval

            resp = asyncio.run(
                handler.post_async(
                    {
                        "jsonrpc": "2.0",
                        "id": "1",
                        "method": "resources/read",
                        "params": {"uri": "notes://1"},
                    }
                )
            )
        return "error" not in resp

    def test_allowed_peer_matches_across_handlers(self) -> None:
        peer_id = "oauth2_client:allowed:allowed"
        self.assertTrue(self._sync_decision(peer_id))
        self.assertTrue(self._async_decision(peer_id))

    def test_denied_peer_matches_across_handlers(self) -> None:
        peer_id = "oauth2_client:blocked:blocked"
        self.assertFalse(self._sync_decision(peer_id))
        self.assertFalse(self._async_decision(peer_id))


if __name__ == "__main__":
    unittest.main()
