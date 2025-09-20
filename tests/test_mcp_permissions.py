import unittest
from unittest.mock import patch, Mock

from actingweb.interface.hooks import HookRegistry
from actingweb.handlers.mcp import MCPHandler
from actingweb.mcp.decorators import mcp_tool, mcp_prompt


def make_hooks():
    hooks = HookRegistry()

    @mcp_tool(description="Search content")
    def search_tool(actor, action_name, data):
        return {"result": f"searched:{data.get('q', '')}"}

    @mcp_tool(description="Create a note")
    def create_note_tool(actor, action_name, data):
        return {"result": f"created:{data.get('title', '')}"}

    hooks.register_action_hook("search", search_tool)
    hooks.register_action_hook("create_note", create_note_tool)
    
    @mcp_prompt(description="Summarize content")
    def summarize_prompt(actor, method_name, data):
        return {"prompt": f"Summarize: {data.get('text', '')}"}

    @mcp_prompt(description="Admin only")
    def admin_prompt(actor, method_name, data):
        return {"prompt": "admin"}

    hooks.register_method_hook("summarize", summarize_prompt)
    hooks.register_method_hook("admin_action", admin_prompt)
    return hooks


class FakeActor:
    def __init__(self, actor_id: str, peer_id: str):
        self.id = actor_id
        # Trust context is set by authentication; simulate here
        self._mcp_trust_context = {"peer_id": peer_id}


class TestMcpPermissions(unittest.TestCase):
    def setUp(self) -> None:
        self.actor_id = "actor123"
        self.peer_id = "oauth2:test_peer"
        self.fake_actor = FakeActor(self.actor_id, self.peer_id)
        self.hooks = make_hooks()
        self.handler = MCPHandler()
        # Inject hooks
        self.handler.hooks = self.hooks

    @patch("actingweb.handlers.mcp.RuntimeContext")
    @patch("actingweb.permission_evaluator.get_permission_evaluator")
    @patch.object(MCPHandler, "authenticate_and_get_actor_cached")
    def test_tools_list_filters_by_permission(self, mock_auth, mock_get_eval, mock_runtime_context):
        # Auth returns our fake actor
        mock_auth.return_value = self.fake_actor

        # Mock runtime context to return MCP context with peer_id
        mock_mcp_context = Mock()
        mock_mcp_context.peer_id = self.peer_id
        mock_runtime_instance = Mock()
        mock_runtime_instance.get_mcp_context.return_value = mock_mcp_context
        mock_runtime_context.return_value = mock_runtime_instance

        # Mock evaluator to allow 'search' and deny 'create_note'
        from actingweb.permission_evaluator import PermissionResult, PermissionType

        def eval_perm(actor_id, peer_id, perm_type, target, operation="access"):
            if perm_type == PermissionType.TOOLS and target == "search":
                return PermissionResult.ALLOWED
            return PermissionResult.DENIED

        mock_eval = Mock()
        mock_eval.evaluate_permission = Mock(side_effect=eval_perm)
        mock_get_eval.return_value = mock_eval

        # Call tools/list
        resp = self.handler.post({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/list",
            "params": {}
        })

        self.assertEqual(resp.get("id"), "1")
        tools = resp.get("result", {}).get("tools", [])
        names = {t.get("name") for t in tools}
        self.assertIn("search", names)
        self.assertNotIn("create_note", names)

    @patch("actingweb.handlers.mcp.RuntimeContext")
    @patch("actingweb.permission_evaluator.get_permission_evaluator")
    @patch.object(MCPHandler, "authenticate_and_get_actor_cached")
    def test_tools_call_respects_permission(self, mock_auth, mock_get_eval, mock_runtime_context):
        mock_auth.return_value = self.fake_actor

        # Mock runtime context to return MCP context with peer_id
        mock_mcp_context = Mock()
        mock_mcp_context.peer_id = self.peer_id
        mock_runtime_instance = Mock()
        mock_runtime_instance.get_mcp_context.return_value = mock_mcp_context
        mock_runtime_context.return_value = mock_runtime_instance

        from actingweb.permission_evaluator import PermissionResult, PermissionType

        def eval_perm(actor_id, peer_id, perm_type, target, operation="access"):
            if perm_type == PermissionType.TOOLS and target == "search":
                return PermissionResult.ALLOWED
            return PermissionResult.DENIED

        mock_eval = Mock()
        mock_eval.evaluate_permission = Mock(side_effect=eval_perm)
        mock_get_eval.return_value = mock_eval

        # Allowed tool
        ok = self.handler.post({
            "jsonrpc": "2.0",
            "id": "2",
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"q": "hello"}}
        })
        self.assertEqual(ok.get("id"), "2")
        self.assertIn("result", ok)

        # Denied tool
        denied = self.handler.post({
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {"name": "create_note", "arguments": {"title": "t"}}
        })
        self.assertEqual(denied.get("id"), "3")
        self.assertIn("error", denied)
        self.assertEqual(denied["error"].get("code"), -32003)

    @patch("actingweb.handlers.mcp.RuntimeContext")
    @patch("actingweb.permission_evaluator.get_permission_evaluator")
    @patch.object(MCPHandler, "authenticate_and_get_actor_cached")
    def test_prompts_list_and_get_respect_permission(self, mock_auth, mock_get_eval, mock_runtime_context):
        mock_auth.return_value = self.fake_actor

        # Mock runtime context to return MCP context with peer_id
        mock_mcp_context = Mock()
        mock_mcp_context.peer_id = self.peer_id
        mock_runtime_instance = Mock()
        mock_runtime_instance.get_mcp_context.return_value = mock_mcp_context
        mock_runtime_context.return_value = mock_runtime_instance

        from actingweb.permission_evaluator import PermissionResult, PermissionType

        def eval_perm(actor_id, peer_id, perm_type, target, operation="access"):
            if perm_type == PermissionType.PROMPTS and target == "summarize":
                return PermissionResult.ALLOWED
            return PermissionResult.DENIED

        mock_eval = Mock()
        mock_eval.evaluate_permission = Mock(side_effect=eval_perm)
        mock_get_eval.return_value = mock_eval

        # List prompts should include only summarize
        resp = self.handler.post({
            "jsonrpc": "2.0",
            "id": "10",
            "method": "prompts/list",
            "params": {}
        })
        prompts = resp.get("result", {}).get("prompts", [])
        names = {p.get("name") for p in prompts}
        self.assertIn("summarize", names)
        self.assertNotIn("admin_action", names)

        # Get allowed prompt
        ok = self.handler.post({
            "jsonrpc": "2.0",
            "id": "11",
            "method": "prompts/get",
            "params": {"name": "summarize", "arguments": {"text": "abc"}}
        })
        self.assertEqual(ok.get("id"), "11")
        self.assertIn("result", ok)

        # Get denied prompt
        denied = self.handler.post({
            "jsonrpc": "2.0",
            "id": "12",
            "method": "prompts/get",
            "params": {"name": "admin_action"}
        })
        self.assertIn("error", denied)
        self.assertEqual(denied["error"].get("code"), -32003)


if __name__ == "__main__":
    unittest.main()
