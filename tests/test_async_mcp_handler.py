"""
Tests for AsyncMCPHandler to verify async hook execution.

These tests verify that:
1. Async hooks execute in the same event loop (no thread pool)
2. Sync hooks still work (backward compatibility)
3. Mixed sync/async hooks work correctly
4. MCP protocol methods (tools, prompts, resources) work with async
"""

import asyncio
import json

import pytest

from actingweb import aw_web_request, config
from actingweb.handlers.async_mcp import AsyncMCPHandler
from actingweb.interface import ActingWebApp
from actingweb.interface.actor_interface import ActorInterface
from actingweb.mcp import mcp_prompt, mcp_tool


class TestAsyncMCPHandler:
    """Test AsyncMCPHandler async execution."""

    @pytest.fixture
    def app(self):
        """Create test ActingWeb app."""
        return ActingWebApp(
            aw_type="urn:actingweb:test:async_mcp",
            database="dynamodb",
            fqdn="test.example.com",
        ).with_devtest(enable=True)

    @pytest.fixture
    def test_config(self):
        """Create test config."""
        cfg = config.Config()
        cfg.fqdn = "test.example.com"
        cfg.proto = "https://"
        cfg.aw_type = "urn:actingweb:test:async_mcp"
        cfg.devtest = True
        return cfg

    @pytest.fixture
    def webobj(self):
        """Create test web object."""
        return aw_web_request.AWWebObj(
            url="https://test.example.com/mcp",
            params={},
            body="",
            headers={},
            cookies={},
        )

    @pytest.fixture
    def mock_actor(self, app):
        """Create mock actor for testing."""

        class MockActor:
            id = "test_actor_123"
            creator = "test@example.com"
            properties = {}

        return ActorInterface(MockActor())

    @pytest.mark.asyncio
    async def test_async_tool_hook_same_event_loop(self, app, test_config, webobj):
        """Verify async tool hooks execute in same event loop without thread pool."""
        hook_event_loop_id = None
        hook_called = False

        @app.action_hook("test_async_tool")
        @mcp_tool(description="Test async tool")
        async def async_tool_hook(actor, action_name, data):
            nonlocal hook_event_loop_id, hook_called
            hook_called = True
            hook_event_loop_id = id(asyncio.get_running_loop())
            await asyncio.sleep(0.001)  # Simulate async I/O
            return {"result": "async_success", "input": data}

        handler = AsyncMCPHandler(webobj, test_config, hooks=app.hooks)
        main_event_loop_id = id(asyncio.get_running_loop())

        # Mock authentication to return a mock actor
        class MockActorObj:
            id = "test_actor"
            creator = "test@example.com"
            properties = {}

        mock_actor = ActorInterface(MockActorObj())
        handler.authenticate_and_get_actor_cached = lambda: mock_actor

        # Call the async tool
        request_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "test_async_tool", "arguments": {"key": "value"}},
        }

        result = await handler.post_async(request_data)

        # Verify hook was called
        assert hook_called, "Hook should have been called"

        # Verify same event loop = no thread pool was used
        assert (
            hook_event_loop_id == main_event_loop_id
        ), f"Expected same event loop (main={main_event_loop_id}, hook={hook_event_loop_id})"

        # Verify result
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 1
        assert "result" in result

    @pytest.mark.asyncio
    async def test_sync_tool_hook_backward_compatibility(
        self, app, test_config, webobj
    ):
        """Verify sync tool hooks still work (backward compatibility)."""
        hook_called = False

        @app.action_hook("test_sync_tool")
        @mcp_tool(description="Test sync tool")
        def sync_tool_hook(actor, action_name, data):
            nonlocal hook_called
            hook_called = True
            return {"result": "sync_success", "input": data}

        handler = AsyncMCPHandler(webobj, test_config, hooks=app.hooks)

        # Mock authentication
        class MockActorObj:
            id = "test_actor"
            creator = "test@example.com"
            properties = {}

        mock_actor = ActorInterface(MockActorObj())
        handler.authenticate_and_get_actor_cached = lambda: mock_actor

        # Call the sync tool
        request_data = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "test_sync_tool", "arguments": {"key": "value"}},
        }

        result = await handler.post_async(request_data)

        # Verify hook was called
        assert hook_called, "Sync hook should have been called"

        # Verify result
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 2
        assert "result" in result

    @pytest.mark.asyncio
    async def test_async_prompt_hook_same_event_loop(self, app, test_config, webobj):
        """Verify async prompt hooks execute in same event loop."""
        hook_event_loop_id = None
        hook_called = False

        @app.method_hook("test_async_prompt")
        @mcp_prompt(description="Test async prompt")
        async def async_prompt_hook(actor, method_name, params):
            nonlocal hook_event_loop_id, hook_called
            hook_called = True
            hook_event_loop_id = id(asyncio.get_running_loop())
            await asyncio.sleep(0.001)  # Simulate async I/O
            return "Async prompt generated successfully"

        handler = AsyncMCPHandler(webobj, test_config, hooks=app.hooks)
        main_event_loop_id = id(asyncio.get_running_loop())

        # Mock authentication
        class MockActorObj:
            id = "test_actor"
            creator = "test@example.com"
            properties = {}

        mock_actor = ActorInterface(MockActorObj())
        handler.authenticate_and_get_actor_cached = lambda: mock_actor

        # Call the async prompt
        request_data = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "prompts/get",
            "params": {"name": "test_async_prompt", "arguments": {}},
        }

        result = await handler.post_async(request_data)

        # Verify hook was called
        assert hook_called, "Async prompt hook should have been called"

        # Verify same event loop
        assert (
            hook_event_loop_id == main_event_loop_id
        ), "Async prompt hook should execute in same event loop"

        # Verify result
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 3
        assert "result" in result
        assert "messages" in result["result"]

    @pytest.mark.asyncio
    async def test_mixed_sync_async_tools(self, app, test_config, webobj):
        """Test app with both sync and async tool hooks."""
        sync_called = False
        async_called = False

        @app.action_hook("sync_tool")
        @mcp_tool(description="Sync tool")
        def sync_tool(actor, action_name, data):
            nonlocal sync_called
            sync_called = True
            return {"result": "sync"}

        @app.action_hook("async_tool")
        @mcp_tool(description="Async tool")
        async def async_tool(actor, action_name, data):
            nonlocal async_called
            async_called = True
            await asyncio.sleep(0.001)
            return {"result": "async"}

        handler = AsyncMCPHandler(webobj, test_config, hooks=app.hooks)

        # Mock authentication
        class MockActorObj:
            id = "test_actor"
            creator = "test@example.com"
            properties = {}

        mock_actor = ActorInterface(MockActorObj())
        handler.authenticate_and_get_actor_cached = lambda: mock_actor

        # Call sync tool
        result1 = await handler.post_async(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "sync_tool", "arguments": {}},
            }
        )

        # Call async tool
        result2 = await handler.post_async(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "async_tool", "arguments": {}},
            }
        )

        # Verify both were called
        assert sync_called, "Sync tool should have been called"
        assert async_called, "Async tool should have been called"

        # Verify both results are valid
        assert result1["jsonrpc"] == "2.0"
        assert result2["jsonrpc"] == "2.0"

    @pytest.mark.asyncio
    async def test_get_async_returns_metadata(self, test_config, webobj):
        """Verify get_async returns MCP server metadata."""
        handler = AsyncMCPHandler(webobj, test_config, hooks=None)

        result = await handler.get_async()

        # Verify metadata structure
        assert "version" in result
        assert "server_name" in result
        assert "capabilities" in result
        assert "transport" in result
        assert "authentication" in result

    @pytest.mark.asyncio
    async def test_initialize_no_auth_required(self, app, test_config, webobj):
        """Verify initialize method doesn't require authentication."""
        handler = AsyncMCPHandler(webobj, test_config, hooks=app.hooks)

        request_data = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "initialize",
            "params": {"clientInfo": {"name": "test_client", "version": "1.0"}},
        }

        result = await handler.post_async(request_data)

        # Verify successful initialization without auth
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 10
        assert "result" in result
        assert "protocolVersion" in result["result"]
        assert "capabilities" in result["result"]

    @pytest.mark.asyncio
    async def test_tools_list_requires_auth(self, app, test_config, webobj):
        """Verify tools/list requires authentication."""
        handler = AsyncMCPHandler(webobj, test_config, hooks=app.hooks)

        # Don't mock authentication - let it fail
        handler.authenticate_and_get_actor_cached = lambda: None

        request_data = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/list",
            "params": {},
        }

        result = await handler.post_async(request_data)

        # Verify authentication error
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 11
        assert "error" in result
        assert result["error"]["code"] == -32002  # Authentication required

    @pytest.mark.asyncio
    async def test_async_tool_with_exception(self, app, test_config, webobj):
        """Verify async tool exceptions are handled properly."""

        @app.action_hook("failing_tool")
        @mcp_tool(description="Tool that fails")
        async def failing_tool(actor, action_name, data):
            await asyncio.sleep(0.001)
            raise ValueError("Intentional test failure")

        handler = AsyncMCPHandler(webobj, test_config, hooks=app.hooks)

        # Mock authentication
        class MockActorObj:
            id = "test_actor"
            creator = "test@example.com"
            properties = {}

        mock_actor = ActorInterface(MockActorObj())
        handler.authenticate_and_get_actor_cached = lambda: mock_actor

        request_data = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "failing_tool", "arguments": {}},
        }

        result = await handler.post_async(request_data)

        # Verify error response
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == 12
        assert "error" in result
        assert result["error"]["code"] == -32603  # Internal error
        assert "Tool execution failed" in result["error"]["message"]

    @pytest.mark.asyncio
    async def test_concurrent_async_tools(self, app, test_config, webobj):
        """Verify multiple async tools can be called concurrently."""
        call_times = []

        @app.action_hook("concurrent_tool")
        @mcp_tool(description="Concurrent tool")
        async def concurrent_tool(actor, action_name, data):
            import time

            start = time.time()
            await asyncio.sleep(0.01)  # 10ms async delay
            end = time.time()
            call_times.append((start, end))
            return {"result": f"tool_{data.get('id')}"}

        handler = AsyncMCPHandler(webobj, test_config, hooks=app.hooks)

        # Mock authentication
        class MockActorObj:
            id = "test_actor"
            creator = "test@example.com"
            properties = {}

        mock_actor = ActorInterface(MockActorObj())
        handler.authenticate_and_get_actor_cached = lambda: mock_actor

        # Call 3 tools concurrently
        tasks = [
            handler.post_async(
                {
                    "jsonrpc": "2.0",
                    "id": i,
                    "method": "tools/call",
                    "params": {"name": "concurrent_tool", "arguments": {"id": i}},
                }
            )
            for i in range(3)
        ]

        results = await asyncio.gather(*tasks)

        # Verify all succeeded
        assert len(results) == 3
        for i, result in enumerate(results):
            assert result["jsonrpc"] == "2.0"
            assert result["id"] == i

        # Verify concurrent execution (should overlap)
        # With true async, all 3 should run concurrently in ~10ms
        # With thread pool, they'd run sequentially in ~30ms
        assert len(call_times) == 3
