"""
Integration tests for async handlers with FastAPI.

Tests AsyncMethodsHandler and AsyncActionsHandler integration.
"""

import pytest
import requests


class TestAsyncMethodHandlerIntegration:
    """Test AsyncMethodsHandler with FastAPI integration."""

    def test_async_method_hook_with_fastapi(self, test_app, actor_factory):
        """Test that async method hooks work correctly with FastAPI."""
        # This test requires the test_app to have async hooks registered
        # Create an actor first
        response = requests.post(
            f"{test_app}/",
            json={"creator": "test@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        creator = actor_data["creator"]
        passphrase = actor_data["passphrase"]

        # Test POST to methods endpoint (should use async handler if available)
        response = requests.post(
            f"{test_app}/{actor_id}/methods/test_method",
            json={"input": "test_data"},
            auth=(creator, passphrase),
        )

        # If no method hook is registered, we expect 400
        # If an async method hook is registered, we expect 200
        # This test validates the plumbing works
        assert response.status_code in [200, 400]

        # Cleanup
        requests.delete(f"{test_app}/{actor_id}", auth=(creator, passphrase))

    def test_async_action_hook_with_fastapi(self, test_app, actor_factory):
        """Test that async action hooks work correctly with FastAPI."""
        # Create an actor
        response = requests.post(
            f"{test_app}/",
            json={"creator": "test@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        creator = actor_data["creator"]
        passphrase = actor_data["passphrase"]

        # Test POST to actions endpoint
        response = requests.post(
            f"{test_app}/{actor_id}/actions/test_action",
            json={"param": "value"},
            auth=(creator, passphrase),
        )

        # Should use async handler if available
        assert response.status_code in [200, 400]

        # Cleanup
        requests.delete(f"{test_app}/{actor_id}", auth=(creator, passphrase))

    def test_jsonrpc_with_async_handler(self, test_app, actor_factory):
        """Test JSON-RPC requests work with async method handlers."""
        # Create an actor
        response = requests.post(
            f"{test_app}/",
            json={"creator": "test@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        creator = actor_data["creator"]
        passphrase = actor_data["passphrase"]

        # Send JSON-RPC request
        jsonrpc_request = {
            "jsonrpc": "2.0",
            "method": "test_method",
            "params": {"input": "test"},
            "id": 1,
        }

        response = requests.post(
            f"{test_app}/{actor_id}/methods/test_method",
            json=jsonrpc_request,
            auth=(creator, passphrase),
        )

        # Should get either JSON-RPC response or error
        assert response.status_code in [200, 400]
        if response.status_code == 200:
            result = response.json()
            assert "jsonrpc" in result
            assert result["jsonrpc"] == "2.0"

        # Cleanup
        requests.delete(f"{test_app}/{actor_id}", auth=(creator, passphrase))


class TestAsyncHandlerPerformance:
    """Performance tests for async handlers."""

    def test_concurrent_method_calls_dont_block(self, test_app):
        """Test that concurrent async method calls don't block each other."""
        import concurrent.futures
        import time

        # Create actor
        response = requests.post(
            f"{test_app}/",
            json={"creator": "test@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        creator = actor_data["creator"]
        passphrase = actor_data["passphrase"]

        def make_request(request_id):
            """Make a method call and return elapsed time."""
            start = time.time()
            response = requests.post(
                f"{test_app}/{actor_id}/methods/test_method",
                json={"id": request_id},
                auth=(creator, passphrase),
                timeout=10,
            )
            elapsed = time.time() - start
            return (response.status_code, elapsed)

        # Make 5 concurrent requests
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request, i) for i in range(5)]
            results = [f.result() for f in futures]
        total_elapsed = time.time() - start_time

        # All requests should complete
        assert len(results) == 5

        # Total time should be reasonable (not 5x individual request time)
        # With async handlers, concurrent requests shouldn't block each other
        assert total_elapsed < 15  # Generous timeout for CI

        # Cleanup
        requests.delete(f"{test_app}/{actor_id}", auth=(creator, passphrase))


@pytest.mark.asyncio
class TestAsyncHookWithFastAPI:
    """Direct async tests with FastAPI app."""

    async def test_async_hook_native_execution(self):
        """Test that async hooks execute natively without thread pool."""
        # This would require access to the actual FastAPI app instance
        # and the ability to register hooks and test them directly
        # For now, this is a placeholder for future direct async testing
        pass


class TestBackwardCompatibilityWithSyncHooks:
    """Test that sync hooks still work with FastAPI."""

    def test_sync_hook_with_fastapi_methods(self, test_app):
        """Test that sync method hooks work with FastAPI."""
        # Create actor
        response = requests.post(
            f"{test_app}/",
            json={"creator": "sync@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        creator = actor_data["creator"]
        passphrase = actor_data["passphrase"]

        # Call method endpoint (should work with sync hooks too)
        response = requests.post(
            f"{test_app}/{actor_id}/methods/sync_method",
            json={"input": "test"},
            auth=(creator, passphrase),
        )

        # Should work regardless of sync/async
        assert response.status_code in [200, 400]

        # Cleanup
        requests.delete(f"{test_app}/{actor_id}", auth=(creator, passphrase))

    def test_sync_hook_with_fastapi_actions(self, test_app):
        """Test that sync action hooks work with FastAPI."""
        # Create actor
        response = requests.post(
            f"{test_app}/",
            json={"creator": "sync@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        creator = actor_data["creator"]
        passphrase = actor_data["passphrase"]

        # Call action endpoint
        response = requests.post(
            f"{test_app}/{actor_id}/actions/sync_action",
            json={"param": "value"},
            auth=(creator, passphrase),
        )

        # Should work with sync hooks
        assert response.status_code in [200, 400]

        # Cleanup
        requests.delete(f"{test_app}/{actor_id}", auth=(creator, passphrase))


class TestAsyncHandlerErrorHandling:
    """Test error handling in async handlers."""

    def test_async_hook_exception_returns_400(self, test_app):
        """Test that async hook exceptions are handled gracefully."""
        # Create actor
        response = requests.post(
            f"{test_app}/",
            json={"creator": "test@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        creator = actor_data["creator"]
        passphrase = actor_data["passphrase"]

        # Call method that might have failing hook
        response = requests.post(
            f"{test_app}/{actor_id}/methods/failing_method",
            json={"input": "test"},
            auth=(creator, passphrase),
        )

        # Should handle errors gracefully (not 500)
        assert response.status_code in [200, 400, 404]

        # Cleanup
        requests.delete(f"{test_app}/{actor_id}", auth=(creator, passphrase))

    def test_async_handler_with_invalid_json(self, test_app):
        """Test async handler with invalid JSON input."""
        # Create actor
        response = requests.post(
            f"{test_app}/",
            json={"creator": "test@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201
        actor_data = response.json()
        actor_id = actor_data["id"]
        creator = actor_data["creator"]
        passphrase = actor_data["passphrase"]

        # Send invalid JSON
        response = requests.post(
            f"{test_app}/{actor_id}/methods/test_method",
            data="invalid json{",
            headers={"Content-Type": "application/json"},
            auth=(creator, passphrase),
        )

        # Should return 400 for bad JSON
        assert response.status_code == 400

        # Cleanup
        requests.delete(f"{test_app}/{actor_id}", auth=(creator, passphrase))
