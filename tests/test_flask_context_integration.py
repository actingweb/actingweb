"""Integration tests for Flask request context management."""

import logging

import pytest
from flask import Flask

from actingweb import request_context
from actingweb.interface import ActingWebApp
from actingweb.interface.integrations.flask_integration import FlaskIntegration


@pytest.fixture
def flask_app() -> Flask:
    """Create a Flask app for testing."""
    app = Flask(__name__)
    app.config["TESTING"] = True
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
def flask_integration(aw_app: ActingWebApp, flask_app: Flask) -> FlaskIntegration:
    """Create Flask integration with context hooks."""
    integration = FlaskIntegration(aw_app, flask_app)
    return integration


class TestFlaskContextSetup:
    """Tests for Flask context setup in requests."""

    def test_context_set_on_request(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that context is set during request processing."""

        @flask_app.route("/test")
        def test_route() -> str:  # pyright: ignore[reportUnusedFunction]
            # Context should be set during request
            req_id = request_context.get_request_id()
            actor_id = request_context.get_actor_id()
            assert req_id is not None
            assert actor_id is None  # No actor_id in this path
            return f"Request ID: {req_id}"

        client = flask_app.test_client()
        response = client.get("/test")

        assert response.status_code == 200
        assert b"Request ID:" in response.data

    def test_context_cleared_after_request(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that context is cleared after request completes."""

        @flask_app.route("/test")
        def test_route() -> str:  # pyright: ignore[reportUnusedFunction]
            return "OK"

        # Ensure context is clear before request
        request_context.clear_request_context()

        client = flask_app.test_client()
        client.get("/test")

        # Context should be cleared after request
        assert request_context.get_request_id() is None
        assert request_context.get_actor_id() is None

    def test_request_id_from_header(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that request ID is extracted from X-Request-ID header."""
        test_req_id = "550e8400-e29b-41d4-a716-446655440000"

        @flask_app.route("/test")
        def test_route() -> str:  # pyright: ignore[reportUnusedFunction]
            req_id = request_context.get_request_id()
            assert req_id == test_req_id
            return "OK"

        client = flask_app.test_client()
        response = client.get("/test", headers={"X-Request-ID": test_req_id})

        assert response.status_code == 200

    def test_request_id_generated_if_not_provided(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that request ID is generated if not in header."""

        @flask_app.route("/test")
        def test_route() -> str:  # pyright: ignore[reportUnusedFunction]
            req_id = request_context.get_request_id()
            assert req_id is not None
            assert len(req_id) == 36  # UUID format
            return "OK"

        client = flask_app.test_client()
        response = client.get("/test")

        assert response.status_code == 200


class TestFlaskActorIdExtraction:
    """Tests for actor ID extraction from URL paths."""

    def test_actor_id_extracted_from_path(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that actor_id is extracted from URL path."""

        @flask_app.route("/<actor_id>/test")
        def test_route(actor_id: str) -> str:  # pyright: ignore[reportUnusedFunction]
            context_actor = request_context.get_actor_id()
            assert context_actor == actor_id
            return f"Actor: {actor_id}"

        client = flask_app.test_client()
        response = client.get("/actor123/test")

        assert response.status_code == 200
        assert b"Actor: actor123" in response.data

    def test_oauth_path_not_treated_as_actor(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that /oauth/* paths don't set actor_id."""

        @flask_app.route("/oauth/callback")
        def oauth_route() -> str:  # pyright: ignore[reportUnusedFunction]
            context_actor = request_context.get_actor_id()
            assert context_actor is None  # Should not be set for /oauth/*
            return "OK"

        client = flask_app.test_client()
        response = client.get("/oauth/callback")

        assert response.status_code == 200

    def test_static_path_not_treated_as_actor(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that /static/* paths don't set actor_id."""

        @flask_app.route("/static/style.css")
        def static_route() -> str:  # pyright: ignore[reportUnusedFunction]
            context_actor = request_context.get_actor_id()
            assert context_actor is None  # Should not be set for /static/*
            return "OK"

        client = flask_app.test_client()
        response = client.get("/static/style.css")

        assert response.status_code == 200


class TestFlaskResponseHeaders:
    """Tests for X-Request-ID in response headers."""

    def test_request_id_added_to_response(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that X-Request-ID is added to response headers."""

        @flask_app.route("/test")
        def test_route() -> str:  # pyright: ignore[reportUnusedFunction]
            return "OK"

        client = flask_app.test_client()
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        # Should be a valid UUID
        req_id = response.headers["X-Request-ID"]
        assert len(req_id) == 36

    def test_request_id_echoed_in_response(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that provided request ID is echoed in response."""
        test_req_id = "550e8400-e29b-41d4-a716-446655440000"

        @flask_app.route("/test")
        def test_route() -> str:  # pyright: ignore[reportUnusedFunction]
            return "OK"

        client = flask_app.test_client()
        response = client.get("/test", headers={"X-Request-ID": test_req_id})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == test_req_id


class TestFlaskContextIsolation:
    """Tests for context isolation between requests."""

    def test_context_isolated_between_requests(
        self, flask_app: Flask, flask_integration: FlaskIntegration
    ) -> None:
        """Test that context doesn't leak between requests."""
        request_ids = []

        @flask_app.route("/test")
        def test_route() -> str:  # pyright: ignore[reportUnusedFunction]
            req_id = request_context.get_request_id()
            request_ids.append(req_id)
            return "OK"

        client = flask_app.test_client()

        # Make multiple requests
        for _ in range(3):
            response = client.get("/test")
            assert response.status_code == 200

        # All request IDs should be different
        assert len(set(request_ids)) == 3


class TestFlaskLoggingIntegration:
    """Tests for context in logging output."""

    def test_context_appears_in_logs(
        self,
        flask_app: Flask,
        flask_integration: FlaskIntegration,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that request context appears in log output."""
        from actingweb.logging_config import get_context_format

        # Set up logger with context filter
        test_logger = logging.getLogger("test_flask_context")
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

        @flask_app.route("/test")
        def test_route() -> str:  # pyright: ignore[reportUnusedFunction]
            test_logger.info("Processing request in Flask")
            return "OK"

        with caplog.at_level(logging.INFO, logger="test_flask_context"):
            client = flask_app.test_client()
            response = client.get("/test")

        assert response.status_code == 200
        assert len(caplog.records) > 0
        # Check that context was added to log record
        assert hasattr(caplog.records[0], "context")

        # Clean up
        test_logger.removeHandler(handler)
