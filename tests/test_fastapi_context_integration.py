"""Integration tests for FastAPI request context management."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from actingweb import request_context
from actingweb.interface import ActingWebApp
from actingweb.interface.integrations.fastapi_integration import (
    FastAPIIntegration,
    RequestContextMiddleware,
)


@pytest.fixture
def fastapi_app() -> FastAPI:
    """Create a FastAPI app for testing."""
    app = FastAPI()
    return app


@pytest.fixture
def aw_app() -> ActingWebApp:
    """Create an ActingWeb app for testing."""
    return ActingWebApp(
        aw_type="urn:actingweb:test",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_devtest(enable=True)


@pytest.fixture
def fastapi_integration(
    aw_app: ActingWebApp, fastapi_app: FastAPI
) -> FastAPIIntegration:
    """Create FastAPI integration with context middleware."""
    integration = FastAPIIntegration(aw_app, fastapi_app)
    return integration


class TestFastAPIContextSetup:
    """Tests for FastAPI context setup in requests."""

    def test_context_set_on_request(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that context is set during request processing."""

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            # Context should be set during request
            req_id = request_context.get_request_id()
            actor_id = request_context.get_actor_id()
            assert req_id is not None
            assert actor_id is None  # No actor_id in this path
            return {"request_id": req_id or ""}

        client = TestClient(fastapi_app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "request_id" in response.json()

    def test_context_cleared_after_request(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that context is cleared after request completes."""

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            return {"status": "OK"}

        # Ensure context is clear before request
        request_context.clear_request_context()

        client = TestClient(fastapi_app)
        client.get("/test")

        # Context should be cleared after request
        assert request_context.get_request_id() is None
        assert request_context.get_actor_id() is None

    def test_request_id_from_header(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that request ID is extracted from X-Request-ID header."""
        test_req_id = "550e8400-e29b-41d4-a716-446655440000"

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            req_id = request_context.get_request_id()
            assert req_id == test_req_id
            return {"status": "OK"}

        client = TestClient(fastapi_app)
        response = client.get("/test", headers={"X-Request-ID": test_req_id})

        assert response.status_code == 200

    def test_request_id_generated_if_not_provided(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that request ID is generated if not in header."""

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            req_id = request_context.get_request_id()
            assert req_id is not None
            assert len(req_id) == 36  # UUID format
            return {"status": "OK"}

        client = TestClient(fastapi_app)
        response = client.get("/test")

        assert response.status_code == 200


class TestFastAPIActorIdExtraction:
    """Tests for actor ID extraction from URL paths."""

    def test_actor_id_extracted_from_path(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that actor_id is extracted from URL path."""

        @fastapi_app.get("/{actor_id}/test")
        async def test_route(actor_id: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            context_actor = request_context.get_actor_id()
            assert context_actor == actor_id
            return {"actor": actor_id}

        client = TestClient(fastapi_app)
        response = client.get("/actor123/test")

        assert response.status_code == 200
        assert response.json()["actor"] == "actor123"

    def test_oauth_path_not_treated_as_actor(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that /oauth/* paths don't set actor_id."""

        @fastapi_app.get("/oauth/callback")
        async def oauth_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            context_actor = request_context.get_actor_id()
            assert context_actor is None  # Should not be set for /oauth/*
            return {"status": "OK"}

        client = TestClient(fastapi_app)
        response = client.get("/oauth/callback")

        assert response.status_code == 200

    def test_docs_path_not_treated_as_actor(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that /docs path doesn't set actor_id."""

        @fastapi_app.get("/docs")
        async def docs_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            context_actor = request_context.get_actor_id()
            assert context_actor is None  # Should not be set for /docs
            return {"status": "OK"}

        client = TestClient(fastapi_app)
        response = client.get("/docs")

        assert response.status_code == 200


class TestFastAPIResponseHeaders:
    """Tests for X-Request-ID in response headers."""

    def test_request_id_added_to_response(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that X-Request-ID is added to response headers."""

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            return {"status": "OK"}

        client = TestClient(fastapi_app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        # Should be a valid UUID
        req_id = response.headers["X-Request-ID"]
        assert len(req_id) == 36

    def test_request_id_echoed_in_response(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that provided request ID is echoed in response."""
        test_req_id = "550e8400-e29b-41d4-a716-446655440000"

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            return {"status": "OK"}

        client = TestClient(fastapi_app)
        response = client.get("/test", headers={"X-Request-ID": test_req_id})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == test_req_id


class TestFastAPIContextIsolation:
    """Tests for context isolation between requests."""

    def test_context_isolated_between_requests(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that context doesn't leak between requests."""
        request_ids = []

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            req_id = request_context.get_request_id()
            request_ids.append(req_id)
            return {"status": "OK"}

        client = TestClient(fastapi_app)

        # Make multiple requests
        for _ in range(3):
            response = client.get("/test")
            assert response.status_code == 200

        # All request IDs should be different
        assert len(set(request_ids)) == 3


class TestFastAPIAsyncContextPropagation:
    """Tests for context propagation through async/await."""

    @pytest.mark.asyncio
    async def test_context_propagates_through_async_calls(
        self, fastapi_app: FastAPI, fastapi_integration: FastAPIIntegration
    ) -> None:
        """Test that context propagates through async function calls."""

        async def inner_function() -> str:
            # Context should be accessible in inner async function
            req_id = request_context.get_request_id()
            assert req_id is not None
            return req_id or ""

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            outer_req_id = request_context.get_request_id()
            inner_req_id = await inner_function()
            # Should be the same request ID
            assert outer_req_id == inner_req_id
            return {"request_id": inner_req_id}

        client = TestClient(fastapi_app)
        response = client.get("/test")

        assert response.status_code == 200


class TestFastAPILoggingIntegration:
    """Tests for context in logging output."""

    def test_context_appears_in_logs(
        self,
        fastapi_app: FastAPI,
        fastapi_integration: FastAPIIntegration,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that request context appears in log output."""
        from actingweb.logging_config import get_context_format

        # Set up logger with context filter
        test_logger = logging.getLogger("test_fastapi_context")
        test_logger.setLevel(logging.INFO)
        test_logger.handlers.clear()

        handler = logging.StreamHandler()
        test_logger.addHandler(handler)

        # Add filter after handler is attached
        from actingweb.log_filter import add_context_filter_to_logger

        add_context_filter_to_logger(test_logger)

        # Update formatter to include context
        formatter = logging.Formatter(get_context_format())
        handler.setFormatter(formatter)

        @fastapi_app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            test_logger.info("Processing request in FastAPI")
            return {"status": "OK"}

        with caplog.at_level(logging.INFO, logger="test_fastapi_context"):
            client = TestClient(fastapi_app)
            response = client.get("/test")

        assert response.status_code == 200
        assert len(caplog.records) > 0
        # Check that context was added to log record
        assert hasattr(caplog.records[0], "context")

        # Clean up
        test_logger.removeHandler(handler)


class TestFastAPIMiddlewareStandalone:
    """Tests for RequestContextMiddleware when used standalone."""

    def test_middleware_can_be_added_manually(self) -> None:
        """Test that middleware can be added to FastAPI app manually."""
        app = FastAPI()
        app.add_middleware(RequestContextMiddleware)

        @app.get("/test")
        async def test_route() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            req_id = request_context.get_request_id()
            assert req_id is not None
            return {"request_id": req_id or ""}

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
