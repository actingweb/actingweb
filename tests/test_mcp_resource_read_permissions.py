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
from typing import Any
from unittest.mock import Mock, patch

from actingweb.config import Config
from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import MCPHandler
from actingweb.interface.hooks import HookRegistry
from actingweb.mcp.decorators import mcp_resource
from actingweb.permission_evaluator import PermissionResult, PermissionType


def make_hooks() -> HookRegistry:
    hooks = HookRegistry()

    @mcp_resource(uri_template="notes://{id}", mime_type="text/plain")
    def get_note(actor: Any, method_name: str, params: dict[str, Any]) -> Any:
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
        self.handler = MCPHandler(config=Config(mcp=True, unique_creator=False))
        self.handler.hooks = make_hooks()

    def _read(self, uri: str, peer_id: str | None) -> dict[str, Any]:
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
        handler = MCPHandler(config=Config(mcp=True, unique_creator=False))
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
        handler = AsyncMCPHandler(config=Config(mcp=True, unique_creator=False))
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


def _allow_all(*_a, **_k):
    return PermissionResult.ALLOWED


def _contents_hooks(seen: list[dict[str, Any]]) -> HookRegistry:
    """Resources whose results cover every formatting branch (3.16)."""
    hooks = HookRegistry()

    @mcp_resource(uri_template="typed://{id}", mime_type="application/x-test")
    def typed(actor: Any, method_name: str, params: dict[str, Any]) -> Any:
        seen.append(dict(params))
        return {"id": params.get("id"), "n": 1}

    @mcp_resource(uri_template="plain://{id}")
    def plain(actor: Any, method_name: str, params: dict[str, Any]) -> Any:
        return {"content": "ignored key", "x": [1, 2]}

    @mcp_resource(uri_template="text://doc", mime_type="text/markdown")
    def text(actor: Any, method_name: str, params: dict[str, Any]) -> Any:
        return "# heading"

    @mcp_resource(uri_template="raw://doc")
    def raw(actor: Any, method_name: str, params: dict[str, Any]) -> Any:
        return {"contents": [{"uri": "raw://doc", "text": "as is"}]}

    @mcp_resource(uri_template="legacy://unused")
    def legacy(actor: Any, method_name: str, params: dict[str, Any]) -> Any:
        return "legacy body"

    # uri_pattern is legacy, hand-authored metadata; the decorator has no
    # parameter for it.
    legacy._mcp_metadata["uri_pattern"] = r"legacy://v\w*"  # type: ignore[attr-defined]

    @mcp_resource(uri_template="shadow://{uri}/{id}")
    def shadow(actor: Any, method_name: str, params: dict[str, Any]) -> Any:
        seen.append(dict(params))
        return "shadow"

    for name, hook in (
        ("shadow", shadow),
        ("typed", typed),
        ("plain", plain),
        ("text", text),
        ("raw", raw),
        ("legacy", legacy),
    ):
        hooks.register_method_hook(name, hook)
    return hooks


class TestSyncAsyncResourceReadContents(unittest.TestCase):
    """Flask and FastAPI answer ``resources/read`` with the same body,
    ``mimeType`` and hook arguments, and match ``uri_pattern`` the same
    (3.16: the async path used ``str()``, a key the decorator never writes,
    and no pattern fallback)."""

    def _read(
        self,
        handler_cls: type[MCPHandler] | type[AsyncMCPHandler],
        uri: str,
        seen: list[dict[str, Any]],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        handler = handler_cls(config=Config(mcp=True, unique_creator=False))
        handler.hooks = _contents_hooks(seen)
        request = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "resources/read",
            "params": {"uri": uri, **(extra or {})},
        }
        with (
            patch.object(
                handler_cls,
                "authenticate_and_get_actor_cached",
                return_value=FakeActor(),
            ),
            patch("actingweb.handlers.mcp.RuntimeContext") as mock_rc,
            patch(
                "actingweb.permission_evaluator.get_permission_evaluator"
            ) as mock_get_eval,
        ):
            mock_rc.return_value.get_mcp_context.return_value = Mock(
                peer_id="oauth2_client:allowed:allowed"
            )
            mock_get_eval.return_value = Mock(
                evaluate_permission=Mock(side_effect=_allow_all)
            )
            if isinstance(handler, AsyncMCPHandler):
                return asyncio.run(handler.post_async(request))
            return handler.post(request)

    def _both(
        self, uri: str, extra: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        sync_seen: list[dict[str, Any]] = []
        async_seen: list[dict[str, Any]] = []
        sync = self._read(MCPHandler, uri, sync_seen, extra)
        async_ = self._read(AsyncMCPHandler, uri, async_seen, extra)
        self.assertIn("result", sync, sync)
        self.assertEqual(sync["result"], async_["result"])
        return sync["result"]["contents"][0], sync_seen, async_seen

    def test_a_dict_with_a_declared_mime_type(self) -> None:
        content, sync_seen, async_seen = self._both("typed://7")
        self.assertEqual(content["mimeType"], "application/x-test")
        self.assertEqual(content["text"], '{\n  "id": "7",\n  "n": 1\n}')
        # The hook sees the request params and the template's variables.
        self.assertEqual(sync_seen, [{"uri": "typed://7", "id": "7"}])
        self.assertEqual(async_seen, sync_seen)

    def test_a_dict_without_a_mime_type_is_json(self) -> None:
        content, _, _ = self._both("plain://1")
        self.assertEqual(content["mimeType"], "application/json")
        self.assertIn('"content": "ignored key"', content["text"])

    def test_a_str_is_sent_as_it_is(self) -> None:
        content, _, _ = self._both("text://doc")
        self.assertEqual(content["text"], "# heading")
        self.assertEqual(content["mimeType"], "text/markdown")

    def test_a_contents_result_passes_through(self) -> None:
        content, _, _ = self._both("raw://doc")
        self.assertEqual(content, {"uri": "raw://doc", "text": "as is"})

    def test_uri_is_reserved_and_variables_win_over_params(self) -> None:
        """A template variable named ``uri`` cannot hide the requested URI,
        and a client param cannot replace a variable the permission check
        judged (verification 2026-11-04, Issue 3)."""
        _, sync_seen, async_seen = self._both("shadow://a/7", {"id": "999"})
        self.assertEqual(sync_seen, [{"uri": "shadow://a/7", "id": "7"}])
        self.assertEqual(async_seen, sync_seen)

    def test_a_resource_declared_only_by_pattern(self) -> None:
        content, _, _ = self._both("legacy://v2")
        self.assertEqual(content["text"], "legacy body")


if __name__ == "__main__":
    unittest.main()
