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

        result = await registry.execute_method_hooks_async(
            "test_method", mock_actor, {}
        )

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
        result = await registry.execute_method_hooks_async(
            "test_method", mock_actor, {}
        )
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

    @pytest.mark.asyncio
    async def test_async_hook_from_sync_method_in_async_context(
        self, registry, mock_actor
    ):
        """Test async hook called from sync method while inside async event loop.

        This tests the ThreadPoolExecutor fallback path in _execute_hook_in_sync_context.
        When sync execution methods are called from an async context (e.g., Flask
        running in async wrapper), async hooks must be executed via thread pool
        to avoid 'asyncio.run() cannot be called from a running event loop' error.
        """
        execution_log = []

        async def async_hook(_actor, _method_name, _data):
            execution_log.append("async_hook_start")
            await asyncio.sleep(0.01)
            execution_log.append("async_hook_end")
            return {"executed_via": "thread_pool"}

        registry.register_method_hook("test_method", async_hook)

        # Call sync method from async context - this triggers ThreadPoolExecutor path
        # The sync method will detect we're in an event loop and use thread pool
        result = registry.execute_method_hooks("test_method", mock_actor, {})

        assert result == {"executed_via": "thread_pool"}
        assert execution_log == ["async_hook_start", "async_hook_end"]

    @pytest.mark.asyncio
    async def test_mixed_hooks_from_sync_method_in_async_context(
        self, registry, mock_actor
    ):
        """Test both sync and async hooks via sync method in async context."""
        execution_log = []

        def sync_hook(_actor, _method_name, _data):
            execution_log.append("sync")
            return None  # Return None to allow next hook to run

        async def async_hook(_actor, _method_name, _data):
            execution_log.append("async")
            await asyncio.sleep(0.01)
            return {"from": "async_hook"}

        # Register both hooks for same method - sync first, async second
        registry.register_method_hook("test", sync_hook)
        registry.register_method_hook("test", async_hook)

        # Call sync method from async context
        result = registry.execute_method_hooks("test", mock_actor, {})

        # Both hooks should execute, async hook result returned (first non-None)
        assert result == {"from": "async_hook"}
        assert "sync" in execution_log
        assert "async" in execution_log


class TestAsyncHookFlaskCompatibility:
    """Test async hooks work correctly in Flask-like sync contexts.

    These tests verify the code path used by Flask handlers when calling
    async hooks via the sync execution methods.
    """

    @pytest.fixture
    def registry(self):
        return HookRegistry()

    @pytest.fixture
    def mock_actor(self):
        class MockActor:
            def __init__(self):
                self.id = "test-actor"

        return MockActor()

    def test_async_method_hook_in_flask_context(self, registry, mock_actor):
        """Test async method hook works when called via sync execution (Flask path)."""

        async def async_method(_actor, _method_name, data):
            await asyncio.sleep(0.01)
            return {"processed": data.get("input", "none")}

        registry.register_method_hook("flask_method", async_method)

        # Simulate Flask handler calling execute_method_hooks (sync)
        result = registry.execute_method_hooks(
            "flask_method", mock_actor, {"input": "test"}
        )

        assert result == {"processed": "test"}

    def test_async_action_hook_in_flask_context(self, registry, mock_actor):
        """Test async action hook works when called via sync execution (Flask path)."""

        async def async_action(_actor, _action_name, data):
            await asyncio.sleep(0.01)
            return {"action_result": data.get("param", "default")}

        registry.register_action_hook("flask_action", async_action)

        # Simulate Flask handler calling execute_action_hooks (sync)
        result = registry.execute_action_hooks(
            "flask_action", mock_actor, {"param": "value"}
        )

        assert result == {"action_result": "value"}

    def test_asyncio_gather_in_flask_context(self, registry, mock_actor):
        """Test that asyncio.gather works inside async hooks called from Flask.

        This is a key use case: developers can write async hooks that make
        multiple concurrent HTTP requests even when running in Flask.
        """
        import time

        async def concurrent_requests(_actor, _method_name, _data):
            # Simulate 3 concurrent HTTP requests
            async def fake_request(url, delay):
                await asyncio.sleep(delay)
                return {"url": url}

            start = time.time()
            results = await asyncio.gather(
                fake_request("api1", 0.05),
                fake_request("api2", 0.05),
                fake_request("api3", 0.05),
            )
            elapsed = time.time() - start

            return {
                "results": results,
                "elapsed": elapsed,
                "concurrent": elapsed < 0.1,  # Should be ~0.05s, not 0.15s
            }

        registry.register_method_hook("concurrent", concurrent_requests)

        # Call from sync context (Flask path)
        result = registry.execute_method_hooks("concurrent", mock_actor, {})

        assert len(result["results"]) == 3
        assert result["concurrent"] is True  # Confirms concurrent execution worked

    def test_exception_in_async_hook_flask_context(self, registry, mock_actor):
        """Test exception handling in async hooks called from Flask context."""

        async def failing_hook(_actor, _method_name, _data):
            await asyncio.sleep(0.01)
            raise ValueError("Simulated failure")

        registry.register_method_hook("failing", failing_hook)

        # Should not raise, should return None
        result = registry.execute_method_hooks("failing", mock_actor, {})

        assert result is None


class TestAsyncHookSyncExecutionFixes:
    """Tests for async hooks executed via sync methods.

    These tests verify that async hooks work correctly when called from
    sync execution methods (execute_*_hooks) for all hook types.

    This addresses the issue where lifecycle, callback, property, and
    subscription hooks did not use _execute_hook_in_sync_context() to
    properly handle async hooks in sync contexts.
    """

    @pytest.fixture
    def registry(self):
        return HookRegistry()

    @pytest.fixture
    def mock_actor(self):
        class MockActor:
            def __init__(self):
                self.id = "test-actor"

        return MockActor()

    def test_async_lifecycle_hook_in_sync_context(self, registry, mock_actor):
        """Test async lifecycle hook works when called via sync execution."""

        async def async_lifecycle(actor, **_kwargs):
            await asyncio.sleep(0.01)
            return {"event": "actor_created", "actor_id": actor.id}

        registry.register_lifecycle_hook("actor_created", async_lifecycle)

        # Call sync method - should work with async hook
        result = registry.execute_lifecycle_hooks("actor_created", mock_actor)

        assert result == {"event": "actor_created", "actor_id": "test-actor"}

    def test_async_callback_hook_in_sync_context(self, registry, mock_actor):
        """Test async callback hook works when called via sync execution."""

        async def async_callback(_actor, _callback_name, data):
            await asyncio.sleep(0.01)
            return {"processed": True, "data": data}

        registry.register_callback_hook("test_callback", async_callback)

        # Call sync method - should work with async hook
        result = registry.execute_callback_hooks(
            "test_callback", mock_actor, {"input": "test"}
        )

        assert result == {"processed": True, "data": {"input": "test"}}

    def test_async_property_hook_in_sync_context(self, registry, mock_actor):
        """Test async property hook works when called via sync execution."""

        async def async_property(_actor, operation, value, _path):
            await asyncio.sleep(0.01)
            if operation == "get":
                return f"async:{value}"
            return value

        registry.register_property_hook("test_prop", async_property)

        # Call sync method - should work with async hook
        result = registry.execute_property_hooks(
            "test_prop", "get", mock_actor, "original_value"
        )

        assert result == "async:original_value"

    def test_async_subscription_hook_in_sync_context(self, registry, mock_actor):
        """Test async subscription hook works when called via sync execution."""

        async def async_subscription(_actor, _subscription, _peer_id, _data):
            await asyncio.sleep(0.01)
            return True

        registry.register_subscription_hook(async_subscription)

        # Call sync method - should work with async hook
        result = registry.execute_subscription_hooks(
            mock_actor, {"sub_id": "123"}, "peer123", {"event": "test"}
        )

        assert result is True

    def test_async_app_callback_hook_in_sync_context(self, registry):
        """Test async app callback hook works when called via sync execution."""

        async def async_app_callback(data):
            await asyncio.sleep(0.01)
            return {"app_callback": True, "data": data}

        registry.register_app_callback_hook("bot", async_app_callback)

        # Call sync method - should work with async hook
        result = registry.execute_app_callback_hooks("bot", {"message": "hello"})

        assert result == {"app_callback": True, "data": {"message": "hello"}}

    def test_async_wildcard_callback_hook_in_sync_context(self, registry, mock_actor):
        """Test async wildcard callback hook works when called via sync execution."""

        async def async_wildcard(_actor, callback_name, data):
            await asyncio.sleep(0.01)
            return {"callback": callback_name, "processed": True}

        registry.register_callback_hook("*", async_wildcard)

        # Call sync method with any callback name
        result = registry.execute_callback_hooks(
            "any_callback", mock_actor, {"test": True}
        )

        assert result == {"callback": "any_callback", "processed": True}

    def test_async_wildcard_property_hook_in_sync_context(self, registry, mock_actor):
        """Test async wildcard property hook works when called via sync execution."""

        async def async_wildcard(_actor, operation, value, _path):
            await asyncio.sleep(0.01)
            return f"transformed:{value}"

        registry.register_property_hook("*", async_wildcard)

        # Call sync method with any property name
        result = registry.execute_property_hooks(
            "any_property", "get", mock_actor, "value"
        )

        assert result == "transformed:value"

    def test_mixed_sync_async_lifecycle_hooks(self, registry, mock_actor):
        """Test mix of sync and async lifecycle hooks via sync execution."""
        execution_log = []

        def sync_lifecycle(actor, **_kwargs):
            execution_log.append("sync")
            return None  # Return None to allow next hook

        async def async_lifecycle(actor, **_kwargs):
            await asyncio.sleep(0.01)
            execution_log.append("async")
            return {"from": "async"}

        registry.register_lifecycle_hook("test_event", sync_lifecycle)
        registry.register_lifecycle_hook("test_event", async_lifecycle)

        result = registry.execute_lifecycle_hooks("test_event", mock_actor)

        assert result == {"from": "async"}
        assert "sync" in execution_log
        assert "async" in execution_log

    def test_async_lifecycle_hook_with_kwargs(self, registry, mock_actor):
        """Test async lifecycle hook receives kwargs correctly."""

        async def async_lifecycle(actor, **kwargs):
            await asyncio.sleep(0.01)
            return {
                "actor_id": actor.id,
                "extra_param": kwargs.get("extra_param"),
                "another_param": kwargs.get("another_param"),
            }

        registry.register_lifecycle_hook("custom_event", async_lifecycle)

        result = registry.execute_lifecycle_hooks(
            "custom_event", mock_actor, extra_param="value1", another_param="value2"
        )

        assert result == {
            "actor_id": "test-actor",
            "extra_param": "value1",
            "another_param": "value2",
        }

    def test_async_callback_hook_exception_handling(self, registry, mock_actor):
        """Test exception handling in async callback hooks via sync execution."""

        async def failing_callback(_actor, _callback_name, _data):
            await asyncio.sleep(0.01)
            raise ValueError("Test error")

        registry.register_callback_hook("failing", failing_callback)

        # Should not raise, should return False (not processed)
        result = registry.execute_callback_hooks("failing", mock_actor, {})

        assert result is False

    def test_async_property_hook_exception_handling(self, registry, mock_actor):
        """Test exception handling in async property hooks via sync execution."""

        async def failing_property(_actor, _operation, _value, _path):
            await asyncio.sleep(0.01)
            raise ValueError("Test error")

        registry.register_property_hook("failing_prop", failing_property)

        # For PUT operation, should return None on error
        result = registry.execute_property_hooks(
            "failing_prop", "put", mock_actor, "value"
        )

        assert result is None

    def test_async_lifecycle_hook_exception_handling(self, registry, mock_actor):
        """Test exception handling in async lifecycle hooks via sync execution."""

        async def failing_lifecycle(_actor, **_kwargs):
            await asyncio.sleep(0.01)
            raise ValueError("Test error")

        registry.register_lifecycle_hook("failing_event", failing_lifecycle)

        # Should not raise, should return None
        result = registry.execute_lifecycle_hooks("failing_event", mock_actor)

        assert result is None

    def test_async_property_hook_with_nested_path(self, registry, mock_actor):
        """Test async property hook correctly receives nested path parameter."""
        received_paths = []

        async def async_property_with_path(_actor, operation, value, path):
            await asyncio.sleep(0.01)
            received_paths.append(path)
            return f"transformed:{value}:path={'/'.join(path)}"

        registry.register_property_hook("settings", async_property_with_path)

        # Test with deeply nested path
        result = registry.execute_property_hooks(
            "settings", "get", mock_actor, "dark", path=["theme", "color", "mode"]
        )

        assert result == "transformed:dark:path=theme/color/mode"
        assert received_paths == [["theme", "color", "mode"]]

    def test_async_subscription_hook_exception_handling(self, registry, mock_actor):
        """Test exception handling in async subscription hooks via sync execution."""

        async def failing_subscription(_actor, _subscription, _peer_id, _data):
            await asyncio.sleep(0.01)
            raise ValueError("Test error")

        registry.register_subscription_hook(failing_subscription)

        # Should not raise, should return False (not processed)
        result = registry.execute_subscription_hooks(
            mock_actor, {"sub_id": "123"}, "peer123", {"event": "test"}
        )

        assert result is False
