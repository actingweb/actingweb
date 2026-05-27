"""Tests for the shared tools/call result formatter (Phase 2).

Covers:
- structuredContent promotion of extra top-level keys (>= 2025-06-18).
- structuredContent omitted for older negotiated versions.
- explicit structuredContent pass-through and _meta preservation.
- legacy text wrapping for non-content results.
- sync (MCPHandler) / async (AsyncMCPHandler) parity.
"""

import pytest

from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.handlers.mcp import MCPHandler, format_call_tool_result
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.mcp import mcp_tool
from tests.mcp_helpers import make_mcp_config, make_mcp_webobj


class TestFormatCallToolResult:
    """Unit tests on the pure formatter."""

    def test_content_with_extras_promotes_structured_content(self) -> None:
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "success": True,
            "memory_type": "note",
        }
        out = format_call_tool_result(result, "2025-06-18")
        assert out["content"] == [{"type": "text", "text": "ok"}]
        assert out["isError"] is False
        assert out["structuredContent"] == {"success": True, "memory_type": "note"}

    def test_latest_version_promotes_structured_content(self) -> None:
        result = {"content": [{"type": "text", "text": "ok"}], "count": 3}
        out = format_call_tool_result(result, "2025-11-25")
        assert out["structuredContent"] == {"count": 3}

    def test_old_version_omits_structured_content(self) -> None:
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "isError": False,
            "success": True,
        }
        out = format_call_tool_result(result, "2024-11-05")
        assert "structuredContent" not in out
        assert out["content"] == [{"type": "text", "text": "ok"}]
        assert out["isError"] is False

    def test_explicit_structured_content_passthrough(self) -> None:
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": {"explicit": 1},
            "ignored_extra": "x",
        }
        out = format_call_tool_result(result, "2025-06-18")
        # Explicit structuredContent wins; extras are NOT merged in.
        assert out["structuredContent"] == {"explicit": 1}

    def test_meta_is_preserved_not_swept(self) -> None:
        result = {
            "content": [{"type": "text", "text": "ok"}],
            "_meta": {"trace": "abc"},
            "extra": 1,
        }
        out = format_call_tool_result(result, "2025-06-18")
        assert out["_meta"] == {"trace": "abc"}
        # _meta must not appear inside structuredContent.
        assert out["structuredContent"] == {"extra": 1}

    def test_isError_true_preserved(self) -> None:
        result = {"content": [{"type": "text", "text": "boom"}], "isError": True}
        out = format_call_tool_result(result, "2025-06-18")
        assert out["isError"] is True
        assert "structuredContent" not in out  # no extras to promote

    def test_content_only_no_structured_content(self) -> None:
        result = {"content": [{"type": "text", "text": "ok"}]}
        out = format_call_tool_result(result, "2025-11-25")
        assert out["content"] == [{"type": "text", "text": "ok"}]
        assert out["isError"] is False
        assert "structuredContent" not in out
        assert "_meta" not in out

    def test_plain_dict_legacy_text_wrap(self) -> None:
        out = format_call_tool_result({"status": "deleted"}, "2025-11-25")
        assert out["content"][0]["type"] == "text"
        assert "deleted" in out["content"][0]["text"]
        assert "structuredContent" not in out

    def test_bare_value_legacy_text_wrap(self) -> None:
        out = format_call_tool_result("hello", "2025-11-25")
        assert out["content"][0]["type"] == "text"
        assert "hello" in out["content"][0]["text"]


class TestSyncAsyncParity:
    """The sync and async handlers must format identical results identically."""

    @pytest.mark.asyncio
    async def test_sync_async_parity_with_extras(self) -> None:
        app = ActingWebApp(
            aw_type="urn:actingweb:test:mcp_format",
            database="dynamodb",
            fqdn="test.example.com",
        ).with_devtest(enable=True)

        @app.action_hook("store")
        @mcp_tool(description="Store something")
        def store_hook(actor, action_name, data):
            return {
                "content": [{"type": "text", "text": "stored"}],
                "isError": False,
                "success": True,
                "memory_type": "note",
            }

        class MockActorObj:
            id = "actor_parity"
            creator = "test@example.com"
            properties: dict = {}

        mock_actor = ActorInterface(MockActorObj())  # type: ignore[arg-type]

        # Negotiated version that supports structuredContent.
        headers = {"MCP-Protocol-Version": "2025-06-18"}
        request_data = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "store", "arguments": {}},
        }

        sync_handler = MCPHandler(
            make_mcp_webobj(headers), make_mcp_config(), hooks=app.hooks
        )
        sync_handler.authenticate_and_get_actor_cached = lambda: mock_actor
        sync_result = sync_handler.post(request_data)

        async_handler = AsyncMCPHandler(
            make_mcp_webobj(headers), make_mcp_config(), hooks=app.hooks
        )
        async_handler.authenticate_and_get_actor_cached = lambda: mock_actor
        async_result = await async_handler.post_async(request_data)

        assert sync_result == async_result
        assert sync_result["result"]["structuredContent"] == {
            "success": True,
            "memory_type": "note",
        }
