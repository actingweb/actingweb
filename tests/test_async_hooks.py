"""Tests for async/await hook support."""

import asyncio

import pytest

from actingweb.interface.hooks import HookRegistry


class TestAsyncHookExecution:
    """Test async hook execution."""

    @pytest.fixture
    def registry(self):
        return HookRegistry()

    @pytest.fixture
    def mock_actor(self):
        class MockActor:
            def __init__(self):
                self.id = "test-actor"

        return MockActor()

    @pytest.mark.asyncio
    async def test_async_method_hook_execution(self, registry, mock_actor):
        """Test that async method hooks are properly awaited."""
        call_order = []

        async def async_hook(_actor, _method_name, data):
            call_order.append("async_start")
            await asyncio.sleep(0.01)  # Simulate async I/O
            call_order.append("async_end")
            return {"result": "async", "data": data}

        registry.register_method_hook("test_method", async_hook)

        result = await registry.execute_method_hooks_async(
            "test_method", mock_actor, {"input": "test"}
        )

        assert result == {"result": "async", "data": {"input": "test"}}
        assert call_order == ["async_start", "async_end"]

    @pytest.mark.asyncio
    async def test_sync_hook_in_async_context(self, registry, mock_actor):
        """Test that sync hooks work correctly in async context."""

        def sync_hook(actor, method_name, data):
            return {"result": "sync"}

        registry.register_method_hook("test_method", sync_hook)

        result = await registry.execute_method_hooks_async("test_method", mock_actor, {})

        assert result == {"result": "sync"}

    @pytest.mark.asyncio
    async def test_mixed_sync_async_hooks(self, registry, mock_actor):
        """Test mix of sync and async hooks in same registry."""

        def sync_hook(_actor, _method_name, _data):
            return {"type": "sync"}

        async def async_hook(_actor, _method_name, _data):
            await asyncio.sleep(0.01)
            return {"type": "async"}

        registry.register_method_hook("method1", sync_hook)
        registry.register_method_hook("method2", async_hook)

        result1 = await registry.execute_method_hooks_async("method1", mock_actor, {})
        result2 = await registry.execute_method_hooks_async("method2", mock_actor, {})

        assert result1["type"] == "sync"
        assert result2["type"] == "async"

    @pytest.mark.asyncio
    async def test_async_hook_exception_handling(self, registry, mock_actor):
        """Test that async hook exceptions are caught and logged."""

        async def failing_hook(_actor, _method_name, _data):
            await asyncio.sleep(0.01)
            raise ValueError("Test error")

        registry.register_method_hook("test_method", failing_hook)

        # Should return None and log error, not propagate exception
        result = await registry.execute_method_hooks_async("test_method", mock_actor, {})
        assert result is None

    @pytest.mark.asyncio
    async def test_async_action_hooks(self, registry, mock_actor):
        """Test async action hook execution."""

        async def async_action(_actor, action_name, _data):
            await asyncio.sleep(0.01)
            return {"executed": True, "action": action_name}

        registry.register_action_hook("test_action", async_action)

        result = await registry.execute_action_hooks_async(
            "test_action", mock_actor, {"param": "value"}
        )

        assert result == {"executed": True, "action": "test_action"}

    def test_async_hook_in_sync_context(self, registry, mock_actor):
        """Test that async hooks can be called from sync context."""

        async def async_hook(_actor, _method_name, _data):
            await asyncio.sleep(0.01)
            return {"result": "async_from_sync"}

        registry.register_method_hook("test_method", async_hook)

        # Sync execution should still work (via asyncio.run())
        result = registry.execute_method_hooks("test_method", mock_actor, {})

        assert result == {"result": "async_from_sync"}

    @pytest.mark.asyncio
    async def test_wildcard_async_hooks(self, registry, mock_actor):
        """Test wildcard hooks with async execution."""

        async def wildcard_hook(_actor, method_name, _data):
            await asyncio.sleep(0.01)
            return {"caught_by": "wildcard", "method": method_name}

        registry.register_method_hook("*", wildcard_hook)

        result = await registry.execute_method_hooks_async("any_method", mock_actor, {})

        assert result["caught_by"] == "wildcard"
        assert result["method"] == "any_method"

    @pytest.mark.asyncio
    async def test_async_property_hooks(self, registry, mock_actor):
        """Test async property hook execution."""

        async def async_property_hook(_actor, operation, value, _path):
            await asyncio.sleep(0.01)
            if operation == "get":
                return f"async:{value}"
            return value

        registry.register_property_hook("test_property", async_property_hook)

        result = await registry.execute_property_hooks_async(
            "test_property", "get", mock_actor, "original_value"
        )

        assert result == "async:original_value"

    @pytest.mark.asyncio
    async def test_async_callback_hooks(self, registry, mock_actor):
        """Test async callback hook execution."""

        async def async_callback(_actor, _callback_name, data):
            await asyncio.sleep(0.01)
            return {"processed": True, "data": data}

        registry.register_callback_hook("test_callback", async_callback)

        result = await registry.execute_callback_hooks_async(
            "test_callback", mock_actor, {"input": "test"}
        )

        assert result == {"processed": True, "data": {"input": "test"}}

    @pytest.mark.asyncio
    async def test_async_lifecycle_hooks(self, registry, mock_actor):
        """Test async lifecycle hook execution."""

        async def async_lifecycle(actor, **_kwargs):
            await asyncio.sleep(0.01)
            return {"lifecycle": "actor_created", "actor_id": actor.id}

        registry.register_lifecycle_hook("actor_created", async_lifecycle)

        result = await registry.execute_lifecycle_hooks_async(
            "actor_created", mock_actor
        )

        assert result == {"lifecycle": "actor_created", "actor_id": "test-actor"}

    @pytest.mark.asyncio
    async def test_async_subscription_hooks(self, registry, mock_actor):
        """Test async subscription hook execution."""

        async def async_subscription(_actor, _subscription, _peer_id, _data):
            await asyncio.sleep(0.01)
            return True

        registry.register_subscription_hook(async_subscription)

        result = await registry.execute_subscription_hooks_async(
            mock_actor, {"sub_id": "123"}, "peer123", {"event": "test"}
        )

        assert result is True


class TestAsyncHookPerformance:
    """Performance tests for async vs sync hooks."""

    @pytest.fixture
    def registry(self):
        return HookRegistry()

    @pytest.fixture
    def mock_actor(self):
        class MockActor:
            def __init__(self):
                self.id = "test-actor"

        return MockActor()

    @pytest.mark.asyncio
    async def test_concurrent_async_hooks(self, registry, mock_actor):
        """Test that multiple async calls can run concurrently."""
        import time

        async def slow_async_hook(_actor, _method_name, data):
            await asyncio.sleep(0.1)  # Simulated I/O
            return {"done": True, "id": data.get("id")}

        registry.register_method_hook("slow_method", slow_async_hook)

        # Run 5 calls concurrently
        start = time.time()
        tasks = [
            registry.execute_method_hooks_async("slow_method", mock_actor, {"id": i})
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start

        # Should complete in ~0.1s (concurrent), not ~0.5s (sequential)
        assert elapsed < 0.3  # Allow some overhead
        assert all(r["done"] for r in results)
        assert {r["id"] for r in results} == {0, 1, 2, 3, 4}

    @pytest.mark.asyncio
    async def test_async_hook_no_blocking(self, registry, mock_actor):
        """Test that async hooks don't block the event loop."""

        async def async_hook(_actor, _method_name, _data):
            await asyncio.sleep(0.05)
            return {"async": True}

        def sync_hook(_actor, _method_name, _data):
            return {"sync": True}

        registry.register_method_hook("async_method", async_hook)
        registry.register_method_hook("quick_method", sync_hook)

        # Start slow async operation
        slow_task = asyncio.create_task(
            registry.execute_method_hooks_async("async_method", mock_actor, {})
        )

        # Quick sync operation should complete while async is running
        quick_result = await registry.execute_method_hooks_async(
            "quick_method", mock_actor, {}
        )

        # Wait for slow task
        slow_result = await slow_task

        assert quick_result == {"sync": True}
        assert slow_result == {"async": True}


class TestAsyncHookContextDetection:
    """Test automatic sync/async context detection."""

    @pytest.fixture
    def registry(self):
        return HookRegistry()

    @pytest.fixture
    def mock_actor(self):
        class MockActor:
            def __init__(self):
                self.id = "test-actor"

        return MockActor()

    def test_sync_hook_in_sync_context(self, registry, mock_actor):
        """Test sync hook called from sync context."""

        def sync_hook(_actor, _method_name, _data):
            return {"context": "sync"}

        registry.register_method_hook("test", sync_hook)

        result = registry.execute_method_hooks("test", mock_actor, {})
        assert result == {"context": "sync"}

    @pytest.mark.asyncio
    async def test_async_hook_in_async_context(self, registry, mock_actor):
        """Test async hook called from async context."""

        async def async_hook(_actor, _method_name, _data):
            return {"context": "async"}

        registry.register_method_hook("test", async_hook)

        result = await registry.execute_method_hooks_async("test", mock_actor, {})
        assert result == {"context": "async"}

    def test_async_hook_from_sync_context_via_asyncio_run(self, registry, mock_actor):
        """Test that async hook can be called from sync context via asyncio.run()."""

        async def async_hook(actor, method_name, data):
            await asyncio.sleep(0.01)
            return {"ran": "via_asyncio_run"}

        registry.register_method_hook("test", async_hook)

        # This should use asyncio.run() internally
        result = registry.execute_method_hooks("test", mock_actor, {})
        assert result == {"ran": "via_asyncio_run"}
