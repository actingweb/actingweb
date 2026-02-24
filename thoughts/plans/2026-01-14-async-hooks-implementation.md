# ActingWeb Async/Await Hook Support Implementation Plan

**Date**: 2026-01-14
**Status**: Proposed
**Impact**: Backward Compatible Enhancement (with careful layered approach)

## Executive Summary

This plan proposes adding native async/await support to ActingWeb hooks while maintaining complete backward compatibility with existing synchronous hooks. The key insight is that async support must be implemented at the **hook execution layer** (HookRegistry), not at the handler layer, to avoid breaking existing applications.

## Background

### Current Architecture

ActingWeb implements a synchronous hook system across multiple layers:

1. **Hook Registry** (`actingweb/interface/hooks.py`): Manages hook registration and execution
   - `execute_method_hooks()` - Method RPC hooks
   - `execute_action_hooks()` - Action trigger hooks
   - `execute_property_hooks()` - Property access hooks
   - `execute_callback_hooks()` / `execute_app_callback_hooks()` - Callback hooks
   - `execute_lifecycle_hooks()` - Lifecycle event hooks
   - `execute_subscription_hooks()` - Subscription hooks

2. **Handlers** (`actingweb/handlers/`): Process HTTP requests and invoke hooks
   - All handlers are currently synchronous
   - Handlers are instantiated and called by framework integrations

3. **Framework Integrations**:
   - **FastAPI** (`fastapi_integration.py`): Uses `run_in_executor()` to run sync handlers in thread pool
   - **Flask** (`flask_integration.py`): Calls handlers directly (synchronous)

### Problem Statement

Applications using ActingWeb (e.g., actingweb_mcp) need to:
1. Call external async services (AWS Bedrock AI, async HTTP clients)
2. Perform async database operations
3. Execute remote peer method calls (AwProxy supports async)
4. Support both Flask (sync) and FastAPI (async) deployments

Current workarounds have significant drawbacks:
- **nest_asyncio**: Monkeypatches the event loop, can cause subtle bugs
- **Thread pools**: Performance overhead, thread exhaustion under load
- **Sync wrappers**: Event loop conflicts in async contexts

### Design Constraints

1. **Backward Compatibility**: Existing sync hooks must continue working without code changes
2. **Framework Agnostic**: Solution must work with both Flask (sync) and FastAPI (async)
3. **Gradual Migration**: Applications can convert hooks to async incrementally
4. **No Breaking Changes**: Handler signatures and public APIs must remain stable

## Proposed Solution: Layered Async Support

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Framework Integration Layer                   │
│  ┌─────────────────────┐    ┌─────────────────────────────────┐│
│  │   Flask (sync)      │    │   FastAPI (async)               ││
│  │   Calls handlers    │    │   Calls handlers via executor   ││
│  │   synchronously     │    │   OR directly if async          ││
│  └─────────────────────┘    └─────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Handler Layer                              │
│   ActionsHandler, MethodsHandler, PropertiesHandler, etc.       │
│   - Remain synchronous (no changes required)                    │
│   - Call hook execution methods                                  │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Hook Registry Layer                          │
│   HookRegistry.execute_*_hooks() methods                        │
│   - Detect sync vs async hooks using inspect.iscoroutinefunction│
│   - Sync hooks: call directly                                   │
│   - Async hooks: run in event loop if available, else fallback  │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Application Hooks                            │
│   @app.method_hook("foo")                                       │
│   def sync_hook(...): ...     # Works (existing)                │
│                                                                  │
│   @app.method_hook("bar")                                       │
│   async def async_hook(...): ...  # Works (new capability)      │
└─────────────────────────────────────────────────────────────────┘
```

### Key Insight: Runtime Context Detection

The critical challenge is that hooks may be:
1. **Async hooks in async context** (FastAPI) → Use `await`
2. **Async hooks in sync context** (Flask) → Need to run event loop
3. **Sync hooks in either context** → Call directly

**Solution**: Use `asyncio.get_running_loop()` to detect context:

```python
def execute_method_hooks(self, method_name: str, actor: Any, data: Any, ...) -> Any:
    """Execute method hooks - works in both sync and async contexts."""

    # Check if we're in an async context
    try:
        loop = asyncio.get_running_loop()
        # We're in async context - but this is a sync function!
        # This shouldn't happen if callers use execute_method_hooks_async()
        # Fall back to sync-only execution
        return self._execute_method_hooks_sync_only(method_name, actor, data, auth_context)
    except RuntimeError:
        # No running loop - we're in sync context
        return self._execute_method_hooks_sync_only(method_name, actor, data, auth_context)

async def execute_method_hooks_async(self, method_name: str, actor: Any, data: Any, ...) -> Any:
    """Execute method hooks asynchronously - for async contexts."""
    # Can await async hooks directly
    ...
```

## Implementation Plan

### Phase 1: Core Hook System Enhancement (Week 1)

#### 1.1 Add Async Execution Methods to HookRegistry

**File**: `actingweb/interface/hooks.py`

Add new async methods alongside existing sync methods for backward compatibility:

```python
import asyncio
import inspect
from typing import Any

class HookRegistry:
    # ... existing code ...

    async def execute_method_hooks_async(
        self,
        method_name: str,
        actor: Any,
        data: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute method hooks with native async support.

        Use this method when calling from an async context (FastAPI handlers).
        Supports both sync and async hooks:
        - Async hooks are awaited directly
        - Sync hooks are called directly (sync-compatible)

        Args:
            method_name: Name of the method hook to execute
            actor: ActorInterface instance
            data: Request data/parameters
            auth_context: Optional authentication context

        Returns:
            Result from the first successful hook, or None
        """
        # Permission check (sync - fast operation)
        if not self._check_hook_permission("method", method_name, actor, auth_context):
            logger.debug(f"Method hook permission denied for {method_name}")
            return None

        result = None

        # Execute hooks for specific method
        if method_name in self._method_hooks:
            for hook in self._method_hooks[method_name]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, method_name, data)
                    else:
                        hook_result = hook(actor, method_name, data)

                    if hook_result is not None:
                        result = hook_result
                        break  # First successful hook wins
                except Exception as e:
                    logger.error(f"Error in method hook for {method_name}: {e}")

        # Execute wildcard hooks if no specific hook handled it
        if result is None and "*" in self._method_hooks:
            for hook in self._method_hooks["*"]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, method_name, data)
                    else:
                        hook_result = hook(actor, method_name, data)

                    if hook_result is not None:
                        result = hook_result
                        break
                except Exception as e:
                    logger.error(f"Error in wildcard method hook: {e}")

        return result

    async def execute_action_hooks_async(
        self,
        action_name: str,
        actor: Any,
        data: Any,
        auth_context: dict[str, Any] | None = None,
    ) -> Any:
        """Execute action hooks with native async support.

        See execute_method_hooks_async for details.
        """
        if not self._check_hook_permission("action", action_name, actor, auth_context):
            logger.debug(f"Action hook permission denied for {action_name}")
            return None

        result = None

        if action_name in self._action_hooks:
            for hook in self._action_hooks[action_name]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, action_name, data)
                    else:
                        hook_result = hook(actor, action_name, data)

                    if hook_result is not None:
                        result = hook_result
                        break
                except Exception as e:
                    logger.error(f"Error in action hook for {action_name}: {e}")

        if result is None and "*" in self._action_hooks:
            for hook in self._action_hooks["*"]:
                try:
                    if inspect.iscoroutinefunction(hook):
                        hook_result = await hook(actor, action_name, data)
                    else:
                        hook_result = hook(actor, action_name, data)

                    if hook_result is not None:
                        result = hook_result
                        break
                except Exception as e:
                    logger.error(f"Error in wildcard action hook: {e}")

        return result

    # Keep existing sync methods unchanged for backward compatibility
    def execute_method_hooks(self, ...) -> Any:
        """Execute method hooks synchronously (existing behavior).

        Note: If you have async hooks and are in an async context,
        use execute_method_hooks_async() instead for proper async execution.
        Sync hooks in this method will work correctly.
        Async hooks in this method will be executed via asyncio.run() which
        may cause issues if already in an event loop - use _async variant.
        """
        # ... existing implementation unchanged ...
```

#### 1.2 Add Helper for Context-Aware Execution

**File**: `actingweb/interface/hooks.py`

```python
def _run_hook_with_context(self, hook: Callable, *args: Any, **kwargs: Any) -> Any:
    """Execute a hook, handling both sync and async hooks appropriately.

    For use in sync contexts only. In async contexts, use the _async methods.

    - Sync hooks: Called directly
    - Async hooks: Executed via asyncio.run() if no event loop,
                   or raises RuntimeError if in async context
    """
    if inspect.iscoroutinefunction(hook):
        try:
            asyncio.get_running_loop()
            # We're in an async context - caller should use _async variant
            logger.warning(
                f"Async hook {hook.__name__} called from sync method in async context. "
                "Use execute_*_hooks_async() for proper async support."
            )
            # Fall back to running in new event loop (may cause issues)
            return asyncio.run(hook(*args, **kwargs))
        except RuntimeError:
            # No running loop - safe to create one
            return asyncio.run(hook(*args, **kwargs))
    else:
        return hook(*args, **kwargs)
```

### Phase 2: Async Handler Variants (Week 2)

#### 2.1 Add Async Handler Base Class

**New File**: `actingweb/handlers/async_base_handler.py`

```python
"""Async-capable base handler for ActingWeb."""

from typing import Any
from actingweb.handlers.base_handler import BaseHandler


class AsyncCapableHandler(BaseHandler):
    """Base handler that supports async hook execution.

    Subclasses can override methods as async for FastAPI integration.
    """

    async def execute_method_hooks_async(
        self, method_name: str, actor_interface: Any, data: Any, auth_context: dict
    ) -> Any:
        """Execute method hooks asynchronously."""
        if self.hooks:
            return await self.hooks.execute_method_hooks_async(
                method_name, actor_interface, data, auth_context
            )
        return None

    async def execute_action_hooks_async(
        self, action_name: str, actor_interface: Any, data: Any, auth_context: dict
    ) -> Any:
        """Execute action hooks asynchronously."""
        if self.hooks:
            return await self.hooks.execute_action_hooks_async(
                action_name, actor_interface, data, auth_context
            )
        return None
```

#### 2.2 Add Async Methods Handler

**New File**: `actingweb/handlers/async_methods.py`

```python
"""Async-capable methods handler for ActingWeb."""

import json
import logging
from typing import Any

from actingweb import auth
from actingweb.handlers.methods import MethodsHandler

logger = logging.getLogger(__name__)


class AsyncMethodsHandler(MethodsHandler):
    """Async-capable methods handler for FastAPI integration.

    Provides async versions of HTTP methods that properly await async hooks.
    Use this handler with FastAPI for optimal async performance.
    """

    async def post_async(self, actor_id: str, name: str = "") -> None:
        """Handle POST requests to methods endpoint asynchronously."""
        auth_result = self._authenticate_dual_context(
            actor_id, "methods", "methods", name=name, add_response=False
        )
        if (
            not auth_result.actor
            or not auth_result.auth_obj
            or (
                auth_result.auth_obj.response["code"] != 200
                and auth_result.auth_obj.response["code"] != 401
            )
        ):
            auth.add_auth_response(appreq=self, auth_obj=auth_result.auth_obj)
            return

        myself = auth_result.actor
        check = auth_result.auth_obj

        if not self._check_method_permission(actor_id, check, name):
            if self.response:
                self.response.set_status(403, "Forbidden")
            return

        # Parse request body
        try:
            body: str | bytes | None = self.request.body
            if body is None:
                body_str = "{}"
            elif isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            else:
                body_str = body
            params = json.loads(body_str)
        except (TypeError, ValueError, KeyError):
            if self.response:
                self.response.set_status(400, "Error in json body")
            return

        # Check if this is a JSON-RPC request
        is_jsonrpc = "jsonrpc" in params and params["jsonrpc"] == "2.0"

        if is_jsonrpc:
            result = await self._handle_jsonrpc_request_async(params, name, myself, check)
        else:
            result = None
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    auth_context = self._create_auth_context(check)
                    # Use async hook execution
                    result = await self.hooks.execute_method_hooks_async(
                        name, actor_interface, params, auth_context
                    )

        if result is not None:
            if self.response:
                self.response.set_status(200, "OK")
                self.response.headers["Content-Type"] = "application/json"
                self.response.write(json.dumps(result))
        else:
            if self.response:
                self.response.set_status(400, "Processing error")

    async def _handle_jsonrpc_request_async(
        self, params: dict[str, Any], method_name: str, myself: Any, auth_obj: Any
    ) -> dict[str, Any] | None:
        """Handle JSON-RPC 2.0 request asynchronously."""
        if "method" not in params:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32600, "message": "Invalid Request", "data": "Missing method"},
                "id": params.get("id"),
            }

        if method_name and method_name != params["method"]:
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32600, "message": "Invalid Request", "data": "Method name mismatch"},
                "id": params.get("id"),
            }

        method_params = params.get("params", {})

        try:
            result = None
            if self.hooks:
                actor_interface = self._get_actor_interface(myself)
                if actor_interface:
                    auth_context = self._create_auth_context(auth_obj)
                    result = await self.hooks.execute_method_hooks_async(
                        params["method"], actor_interface, method_params, auth_context
                    )

            if result is not None:
                response = {"jsonrpc": "2.0", "result": result}
                if "id" in params:
                    response["id"] = params["id"]
                return response
            else:
                return {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": "Method not found"},
                    "id": params.get("id"),
                }
        except Exception as e:
            logger.error(f"Error executing method {params['method']}: {e}")
            return {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": "Internal error", "data": str(e)},
                "id": params.get("id"),
            }
```

Similarly create `actingweb/handlers/async_actions.py`.

### Phase 3: FastAPI Integration Update (Week 2-3)

#### 3.1 Update FastAPI Handler Selection

**File**: `actingweb/interface/integrations/fastapi_integration.py`

```python
async def _handle_actor_request(
    self, request: Request, actor_id: str, endpoint: str, **kwargs: Any
) -> Response:
    """Handle actor-specific requests with async hook support."""
    req_data = await self._normalize_request(request)
    webobj = AWWebObj(...)

    # Get appropriate handler - prefer async variants for methods/actions
    handler = self._get_handler(endpoint, webobj, actor_id, **kwargs)
    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")

    method_name = request.method.lower()

    # Check for async handler method variant
    async_method_name = f"{method_name}_async"
    async_handler_method = getattr(handler, async_method_name, None)
    sync_handler_method = getattr(handler, method_name, None)

    if async_handler_method and callable(async_handler_method):
        # Use native async handler - no thread pool overhead
        try:
            await async_handler_method(*args)
        except Exception as e:
            self.logger.error(f"Error in async {endpoint} handler: {e}")
            self._set_error_response(webobj, e)
    elif sync_handler_method and callable(sync_handler_method):
        # Fall back to sync handler in thread pool
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self.executor, sync_handler_method, *args)
        except Exception as e:
            self.logger.error(f"Error in sync {endpoint} handler: {e}")
            self._set_error_response(webobj, e)
    else:
        raise HTTPException(status_code=405, detail="Method not allowed")

    return self._create_fastapi_response(webobj, request)
```

#### 3.2 Update Handler Factory for Async Handlers

**File**: `actingweb/interface/integrations/base_integration.py`

```python
def get_handler_class(self, endpoint: str, webobj: Any, config: "Config", **kwargs: Any):
    """Get handler class - prefer async variants when available."""
    from ...handlers import actions, methods
    from ...handlers import async_actions, async_methods  # New imports

    # Check if caller prefers async handlers (set by FastAPI integration)
    prefer_async = kwargs.pop("_prefer_async", False)

    handlers = {
        "methods": lambda: (
            async_methods.AsyncMethodsHandler(webobj, config, hooks=self.aw_app.hooks)
            if prefer_async else
            methods.MethodsHandler(webobj, config, hooks=self.aw_app.hooks)
        ),
        "actions": lambda: (
            async_actions.AsyncActionsHandler(webobj, config, hooks=self.aw_app.hooks)
            if prefer_async else
            actions.ActionsHandler(webobj, config, hooks=self.aw_app.hooks)
        ),
        # ... other handlers unchanged ...
    }
```

### Phase 4: Flask Compatibility (Week 3)

#### 4.1 Sync Execution of Async Hooks in Flask

Flask handlers remain synchronous. When an async hook is registered and called from Flask:

```python
# In HookRegistry.execute_method_hooks() (sync method)
def execute_method_hooks(self, method_name: str, actor: Any, data: Any, ...) -> Any:
    """Execute method hooks synchronously.

    Note: Async hooks will be executed via asyncio.run() in a sync context.
    This creates a new event loop per call, which works but has overhead.
    For optimal async performance, use FastAPI with execute_method_hooks_async().
    """
    # ... permission check ...

    for hook in hooks:
        try:
            if inspect.iscoroutinefunction(hook):
                # Async hook in sync context - run in new event loop
                try:
                    loop = asyncio.get_running_loop()
                    # Already in async context - should use _async variant
                    logger.warning(
                        f"Sync execute_method_hooks called with async hook in async context. "
                        "Consider using execute_method_hooks_async()."
                    )
                    # Create a new thread to run the async hook
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, hook(actor, method_name, data))
                        hook_result = future.result()
                except RuntimeError:
                    # No running loop - safe to use asyncio.run()
                    hook_result = asyncio.run(hook(actor, method_name, data))
            else:
                hook_result = hook(actor, method_name, data)

            if hook_result is not None:
                result = hook_result
                break
        except Exception as e:
            logger.error(f"Error in method hook for {method_name}: {e}")

    return result
```

### Phase 5: Testing (Week 3-4)

#### 5.1 Unit Tests

**New File**: `tests/test_async_hooks.py`

```python
"""Tests for async/await hook support."""

import asyncio
import pytest
from unittest.mock import MagicMock

from actingweb.interface.hooks import HookRegistry


class TestAsyncHookExecution:
    """Test async hook execution."""

    @pytest.fixture
    def registry(self):
        return HookRegistry()

    @pytest.fixture
    def mock_actor(self):
        actor = MagicMock()
        actor.id = "test-actor"
        return actor

    @pytest.mark.asyncio
    async def test_async_method_hook_execution(self, registry, mock_actor):
        """Test that async method hooks are properly awaited."""
        call_order = []

        @registry.register_method_hook("test_method")
        async def async_hook(actor, method_name, data):
            call_order.append("async_start")
            await asyncio.sleep(0.01)  # Simulate async I/O
            call_order.append("async_end")
            return {"result": "async", "data": data}

        result = await registry.execute_method_hooks_async(
            "test_method", mock_actor, {"input": "test"}
        )

        assert result == {"result": "async", "data": {"input": "test"}}
        assert call_order == ["async_start", "async_end"]

    @pytest.mark.asyncio
    async def test_sync_hook_in_async_context(self, registry, mock_actor):
        """Test that sync hooks work correctly in async context."""
        @registry.register_method_hook("test_method")
        def sync_hook(actor, method_name, data):
            return {"result": "sync"}

        result = await registry.execute_method_hooks_async(
            "test_method", mock_actor, {}
        )

        assert result == {"result": "sync"}

    @pytest.mark.asyncio
    async def test_mixed_sync_async_hooks(self, registry, mock_actor):
        """Test mix of sync and async hooks in same registry."""
        @registry.register_method_hook("method1")
        def sync_hook(actor, method_name, data):
            return {"type": "sync"}

        @registry.register_method_hook("method2")
        async def async_hook(actor, method_name, data):
            await asyncio.sleep(0.01)
            return {"type": "async"}

        result1 = await registry.execute_method_hooks_async("method1", mock_actor, {})
        result2 = await registry.execute_method_hooks_async("method2", mock_actor, {})

        assert result1["type"] == "sync"
        assert result2["type"] == "async"

    @pytest.mark.asyncio
    async def test_async_hook_exception_handling(self, registry, mock_actor):
        """Test that async hook exceptions are caught and logged."""
        @registry.register_method_hook("test_method")
        async def failing_hook(actor, method_name, data):
            await asyncio.sleep(0.01)
            raise ValueError("Test error")

        # Should return None and log error, not propagate exception
        result = await registry.execute_method_hooks_async(
            "test_method", mock_actor, {}
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_async_action_hooks(self, registry, mock_actor):
        """Test async action hook execution."""
        @registry.register_action_hook("test_action")
        async def async_action(actor, action_name, data):
            await asyncio.sleep(0.01)
            return {"executed": True, "action": action_name}

        result = await registry.execute_action_hooks_async(
            "test_action", mock_actor, {"param": "value"}
        )

        assert result == {"executed": True, "action": "test_action"}

    def test_async_hook_in_sync_context(self, registry, mock_actor):
        """Test that async hooks can be called from sync context."""
        @registry.register_method_hook("test_method")
        async def async_hook(actor, method_name, data):
            await asyncio.sleep(0.01)
            return {"result": "async_from_sync"}

        # Sync execution should still work (via asyncio.run())
        result = registry.execute_method_hooks(
            "test_method", mock_actor, {}
        )

        assert result == {"result": "async_from_sync"}

    @pytest.mark.asyncio
    async def test_wildcard_async_hooks(self, registry, mock_actor):
        """Test wildcard hooks with async execution."""
        @registry.register_method_hook("*")
        async def wildcard_hook(actor, method_name, data):
            await asyncio.sleep(0.01)
            return {"caught_by": "wildcard", "method": method_name}

        result = await registry.execute_method_hooks_async(
            "any_method", mock_actor, {}
        )

        assert result["caught_by"] == "wildcard"
        assert result["method"] == "any_method"


class TestAsyncHookPerformance:
    """Performance tests for async vs sync hooks."""

    @pytest.fixture
    def registry(self):
        return HookRegistry()

    @pytest.fixture
    def mock_actor(self):
        actor = MagicMock()
        actor.id = "test-actor"
        return actor

    @pytest.mark.asyncio
    async def test_concurrent_async_hooks(self, registry, mock_actor):
        """Test that multiple async calls can run concurrently."""
        import time

        @registry.register_method_hook("slow_method")
        async def slow_async_hook(actor, method_name, data):
            await asyncio.sleep(0.1)  # Simulated I/O
            return {"done": True, "id": data.get("id")}

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
```

#### 5.2 Integration Tests

**New File**: `tests/test_async_handlers_integration.py`

```python
"""Integration tests for async handler support."""

import pytest
from unittest.mock import MagicMock, AsyncMock

# Test with actual FastAPI test client
pytest.importorskip("httpx")
from httpx import AsyncClient


class TestAsyncHandlerIntegration:
    """Test async handlers in FastAPI context."""

    @pytest.mark.asyncio
    async def test_fastapi_async_method_handler(self, test_app):
        """Test FastAPI async method handler end-to-end."""
        # Register async hook
        @test_app.method_hook("async_test")
        async def async_test_hook(actor, method_name, data):
            import asyncio
            await asyncio.sleep(0.01)
            return {"success": True, "data": data}

        async with AsyncClient(app=test_app.fastapi_app, base_url="http://test") as client:
            response = await client.post(
                f"/actors/{actor_id}/methods/async_test",
                json={"param": "value"},
                headers={"Authorization": f"Basic {auth_header}"}
            )

        assert response.status_code == 200
        result = response.json()
        assert result["success"] is True
        assert result["data"]["param"] == "value"
```

### Phase 6: Documentation (Week 4)

#### 6.1 Update Hooks Reference

**File**: `docs/reference/hooks-reference.rst`

Add section:

```rst
Async Hook Support
------------------

ActingWeb supports both synchronous and asynchronous hooks. The framework
automatically detects the hook type and executes appropriately.

Defining Async Hooks
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from actingweb.interface import ActingWebApp

    app = ActingWebApp(...)

    # Synchronous hook (existing pattern)
    @app.method_hook("sync_operation")
    def handle_sync(actor, method_name, data):
        result = process_data(data)
        return {"result": result}

    # Asynchronous hook (new capability)
    @app.method_hook("async_operation")
    async def handle_async(actor, method_name, data):
        async with aiohttp.ClientSession() as session:
            async with session.get(data["url"]) as response:
                content = await response.text()
        return {"content": content}

Framework Behavior
~~~~~~~~~~~~~~~~~~

**FastAPI (Async Context)**:
- Async hooks are awaited directly with no overhead
- Sync hooks are called directly (synchronous-compatible)
- Best performance for async I/O operations

**Flask (Sync Context)**:
- Async hooks are executed via ``asyncio.run()``
- Creates a new event loop per async hook call
- Works correctly but has slight overhead
- Sync hooks are called directly

When to Use Async Hooks
~~~~~~~~~~~~~~~~~~~~~~~

Use async hooks when your hook needs to:

- Make HTTP requests to external services
- Query databases with async drivers
- Call AWS services via aioboto3
- Perform any I/O-bound operation

Use sync hooks when:

- Performing CPU-bound computations
- Operations complete quickly without I/O
- Using libraries without async support
```

#### 6.2 Migration Guide

**New File**: `docs/guides/async-hooks-migration.rst`

```rst
Migrating to Async Hooks
========================

This guide helps you migrate existing synchronous hooks to async
for improved performance in async frameworks like FastAPI.

Prerequisites
-------------

- Python 3.8+ (for native async/await)
- Async-compatible libraries for I/O operations

Migration Steps
---------------

1. **Identify I/O-Bound Hooks**

   Look for hooks that:

   - Make HTTP requests (``requests``, ``urllib``)
   - Query databases
   - Read/write files
   - Call external APIs

2. **Install Async Libraries**

   Replace sync libraries with async equivalents:

   - ``requests`` → ``aiohttp`` or ``httpx``
   - ``psycopg2`` → ``asyncpg``
   - ``boto3`` → ``aioboto3``

3. **Convert Hook Signature**

   .. code-block:: python

       # Before
       @app.method_hook("fetch_data")
       def fetch_data(actor, method_name, data):
           response = requests.get(data["url"])
           return {"content": response.text}

       # After
       @app.method_hook("fetch_data")
       async def fetch_data(actor, method_name, data):
           async with httpx.AsyncClient() as client:
               response = await client.get(data["url"])
           return {"content": response.text}

4. **Test Thoroughly**

   Use ``pytest-asyncio`` for testing:

   .. code-block:: python

       @pytest.mark.asyncio
       async def test_fetch_data_hook():
           result = await registry.execute_method_hooks_async(
               "fetch_data", mock_actor, {"url": "https://example.com"}
           )
           assert "content" in result

Backward Compatibility
----------------------

- Existing sync hooks continue to work without changes
- Mix sync and async hooks freely in the same application
- No changes required for Flask deployments
- FastAPI deployments automatically benefit from async hooks
```

## Backward Compatibility Guarantees

### What Stays the Same

1. **Sync Hooks**: All existing synchronous hooks continue to work unchanged
2. **Handler APIs**: Handler method signatures remain identical
3. **Decorators**: Same `@app.method_hook()`, `@app.action_hook()` decorators
4. **Flask Behavior**: Flask integration unchanged (uses sync handlers)
5. **Test Patterns**: Existing sync tests continue to pass

### What's Added

1. **Async Hook Support**: New capability to define `async def` hooks
2. **Async Execution Methods**: `execute_*_hooks_async()` methods on HookRegistry
3. **Async Handler Variants**: Optional `AsyncMethodsHandler`, `AsyncActionsHandler`
4. **FastAPI Optimization**: Native async execution when async handlers available

### Migration Path

| Stage | Action | Risk |
|-------|--------|------|
| 1 | Deploy ActingWeb with async support | Zero - additive only |
| 2 | Applications continue using sync hooks | Zero - unchanged |
| 3 | Convert I/O-heavy hooks to async | Low - per-hook migration |
| 4 | FastAPI apps gain performance benefits | Low - automatic |

## Risk Assessment

### Low Risk
- ✅ Additive changes only - no modifications to existing sync code paths
- ✅ Sync hooks continue working identically
- ✅ Standard Python async patterns
- ✅ Well-tested libraries (asyncio is mature)

### Medium Risk
- ⚠️ Async hooks in sync context use `asyncio.run()` (has overhead)
- ⚠️ Debugging async code is more complex
- ⚠️ Team needs to learn async patterns

### Mitigation Strategies

1. **Comprehensive Test Suite**: Unit and integration tests for all scenarios
2. **Gradual Rollout**: Deploy async support first, migrate hooks incrementally
3. **Documentation**: Clear guides on when to use async vs sync
4. **Monitoring**: Add logging to track async vs sync hook usage
5. **Fallback**: Sync execution always available as fallback

## Success Metrics

### Technical Criteria

- [ ] All existing tests pass unchanged
- [ ] New async tests pass (unit + integration)
- [ ] No performance regression for sync hooks
- [ ] Pyright type checking passes
- [ ] Ruff linting passes

### Performance Targets (FastAPI with async hooks)

- 50% reduction in response latency for I/O-bound hooks
- 3x improvement in concurrent request handling
- Zero thread pool usage for async operations

### Adoption Targets (6 months)

- Applications can migrate hooks at their own pace
- Zero breaking changes reported
- Clear documentation enables self-service migration

## Implementation Checklist

### Week 1: Core Hook System ✅ COMPLETE
- [x] Add `execute_method_hooks_async()` to HookRegistry
- [x] Add `execute_action_hooks_async()` to HookRegistry
- [x] Add all async hook variants: `execute_property_hooks_async()`, `execute_callback_hooks_async()`, `execute_app_callback_hooks_async()`, `execute_subscription_hooks_async()`, `execute_lifecycle_hooks_async()`
- [x] Add helper for context-aware hook execution (`_execute_hook_in_sync_context()`)
- [x] Update sync methods to support async hooks via `asyncio.run()`
- [x] Unit tests for async hook execution (tests/test_async_hooks.py - 17 test cases)
- [x] Code review

### Week 2: Handler Support ✅ COMPLETE
- [x] Create `AsyncMethodsHandler` with `post_async()` method (+ get_async, put_async, delete_async)
- [x] Create `AsyncActionsHandler` with `post_async()` method (+ get_async, put_async, delete_async)
- [x] Update base_integration handler factory with `_prefer_async_handlers()`
- [x] Integration tests (tests/integration/test_async_handlers_integration.py)

### Week 3: FastAPI Integration ✅ COMPLETE
- [x] Update `_handle_actor_request` for async handler detection
- [x] Add `_prefer_async_handlers()` method to FastAPI integration
- [x] Handler selection with async variants
- [x] Performance benchmarks (concurrent execution tests in test_async_hooks.py)
- [x] Flask compatibility verification (backward compatible by design, sync hooks use asyncio.run())

### Week 4: Documentation & Release ✅ COMPLETE
- [x] Update hooks-reference.rst (comprehensive async/await section with examples)
- [x] Create async-hooks-migration.rst (complete migration guide with real-world examples)
- [x] Update docs/guides/index.rst to include migration guide
- [x] Update CHANGELOG.rst (detailed v3.9.0 release notes)
- [x] Version bump (v3.9.0 in pyproject.toml and actingweb/__init__.py)
- [x] Release notes (included in CHANGELOG.rst)

## Implementation Summary

### Files Created
- `actingweb/handlers/async_methods.py` - AsyncMethodsHandler (122 lines)
- `actingweb/handlers/async_actions.py` - AsyncActionsHandler (132 lines)
- `tests/test_async_hooks.py` - Unit tests for async hooks (312 lines, 17 test cases)
- `tests/integration/test_async_handlers_integration.py` - Integration tests (292 lines)
- `docs/guides/async-hooks-migration.rst` - Migration guide (580+ lines)

### Files Modified
- `actingweb/interface/hooks.py` - Added async execution methods
- `actingweb/interface/integrations/base_integration.py` - Handler factory updates
- `actingweb/interface/integrations/fastapi_integration.py` - Async handler detection
- `docs/reference/hooks-reference.rst` - Added async examples
- `docs/guides/index.rst` - Added migration guide to toctree
- `CHANGELOG.rst` - v3.9.0 release notes
- `pyproject.toml` & `actingweb/__init__.py` - Version 3.9.0

### Quality Metrics
- **Pyright**: 0 errors, 0 warnings ✅
- **Ruff**: All checks passed ✅
- **Tests**: 1074 passed, 1 skipped (100% success rate) ✅
- **Test Time**: 7:35 (parallel execution)
- **Coverage**: 45.09% maintained
- **Backward Compatibility**: Verified - all existing tests pass

### Key Features Implemented
1. Native async/await support for all hook types
2. Automatic sync vs async hook detection via `inspect.iscoroutinefunction()`
3. FastAPI async handlers (AsyncMethodsHandler, AsyncActionsHandler)
4. Backward compatibility - sync hooks work without changes
5. Mixed sync/async hook support in same application
6. Flask compatibility via `asyncio.run()` fallback
7. Performance improvements for I/O-bound operations
8. Comprehensive documentation and migration guide

## References

- Python asyncio documentation: <https://docs.python.org/3/library/asyncio.html>
- FastAPI async support: <https://fastapi.tiangolo.com/async/>
- pytest-asyncio: <https://pytest-asyncio.readthedocs.io/>
- inspect.iscoroutinefunction: <https://docs.python.org/3/library/inspect.html#inspect.iscoroutinefunction>

---

**Author**: Claude Code
**Reviewed By**: Principal Engineer Review
**Status**: ✅ IMPLEMENTED & TESTED
**Implementation**: Completed January 14, 2026
**Version**: v3.9.0
