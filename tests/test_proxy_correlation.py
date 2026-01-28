"""Integration tests for request correlation in peer-to-peer communication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from actingweb import request_context
from actingweb.aw_proxy import AwProxy
from actingweb.config import Config


@pytest.fixture
def config() -> Config:
    """Create test config."""
    return Config()


@pytest.fixture
def mock_trust() -> dict[str, str]:
    """Create a mock trust relationship."""
    return {
        "baseuri": "https://peer.example.com/actor123",
        "secret": "test-secret-token-123",
        "peerid": "peer123",
        "relationship": "friend",
    }


class TestProxyCorrelationHeaders:
    """Tests for correlation headers in peer requests."""

    def teardown_method(self) -> None:
        """Clean up after each test."""
        request_context.clear_request_context()

    def test_bearer_headers_include_correlation(
        self, config: Config, mock_trust: dict[str, str]
    ) -> None:
        """Test that bearer headers include correlation headers."""
        # Set up request context
        request_context.set_request_context(
            request_id="parent-request-id-12345", actor_id="actor1"
        )

        # Create proxy
        proxy = AwProxy(peer_target={"id": "actor1", "peerid": "peer123"}, config=config)
        proxy.trust = mock_trust

        # Get headers
        headers = proxy._bearer_headers()

        # Verify authorization header
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-secret-token-123"

        # Verify correlation headers
        assert "X-Request-ID" in headers
        assert "X-Parent-Request-ID" in headers
        assert headers["X-Parent-Request-ID"] == "parent-request-id-12345"
        # New request ID should be generated
        assert headers["X-Request-ID"] != "parent-request-id-12345"
        assert len(headers["X-Request-ID"]) == 36  # UUID format

    def test_basic_headers_include_correlation(self, config: Config) -> None:
        """Test that basic auth headers include correlation headers."""
        request_context.set_request_context(
            request_id="parent-request-id-67890", actor_id="actor2"
        )

        # Create proxy with peer passphrase
        proxy = AwProxy(
            peer_target={"id": "actor2", "peerid": "peer456", "passphrase": "testpass"},
            config=config,
        )

        # Get headers
        headers = proxy._basic_headers()

        # Verify authorization header
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")

        # Verify correlation headers
        assert "X-Request-ID" in headers
        assert "X-Parent-Request-ID" in headers
        assert headers["X-Parent-Request-ID"] == "parent-request-id-67890"

    def test_correlation_without_parent_context(
        self, config: Config, mock_trust: dict[str, str]
    ) -> None:
        """Test correlation headers when no parent context exists."""
        # Clear any existing context
        request_context.clear_request_context()

        # Create proxy
        proxy = AwProxy(peer_target={"id": "actor1", "peerid": "peer123"}, config=config)
        proxy.trust = mock_trust

        # Get headers
        headers = proxy._bearer_headers()

        # Should have new request ID but no parent
        assert "X-Request-ID" in headers
        assert "X-Parent-Request-ID" not in headers

    @patch("actingweb.aw_proxy.requests.get")
    def test_get_resource_sends_correlation_headers(
        self,
        mock_get: MagicMock,
        config: Config,
        mock_trust: dict[str, str],
    ) -> None:
        """Test that GET requests send correlation headers."""
        request_context.set_request_context(
            request_id="test-parent-id", actor_id="actor1"
        )

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_get.return_value = mock_response

        # Create proxy and make request
        proxy = AwProxy(peer_target={"id": "actor1", "peerid": "peer123"}, config=config)
        proxy.trust = mock_trust
        _ = proxy.get_resource(path="test/resource")

        # Verify request was made with correlation headers
        assert mock_get.called
        call_args = mock_get.call_args
        headers = call_args.kwargs["headers"]

        assert "X-Request-ID" in headers
        assert "X-Parent-Request-ID" in headers
        assert headers["X-Parent-Request-ID"] == "test-parent-id"

    @patch("actingweb.aw_proxy.requests.post")
    def test_create_resource_sends_correlation_headers(
        self,
        mock_post: MagicMock,
        config: Config,
        mock_trust: dict[str, str],
    ) -> None:
        """Test that POST requests send correlation headers."""
        request_context.set_request_context(
            request_id="test-create-parent", actor_id="actor1"
        )

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "new123"}
        mock_post.return_value = mock_response

        # Create proxy and make request
        proxy = AwProxy(peer_target={"id": "actor1", "peerid": "peer123"}, config=config)
        proxy.trust = mock_trust
        _ = proxy.create_resource(path="test/resource", params={"name": "test"})

        # Verify request was made with correlation headers
        assert mock_post.called
        call_args = mock_post.call_args
        headers = call_args.kwargs["headers"]

        assert "X-Request-ID" in headers
        assert "X-Parent-Request-ID" in headers
        assert headers["X-Parent-Request-ID"] == "test-create-parent"

    @patch("actingweb.aw_proxy.requests.get")
    def test_retry_preserves_correlation_headers(
        self,
        mock_get: MagicMock,
        config: Config,
        mock_trust: dict[str, str],
    ) -> None:
        """Test that retry with basic auth preserves correlation headers."""
        request_context.set_request_context(
            request_id="test-retry-parent", actor_id="actor1"
        )

        # Mock initial 401 response, then successful retry
        mock_unauthorized = MagicMock()
        mock_unauthorized.status_code = 401

        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {"result": "success"}

        mock_get.side_effect = [mock_unauthorized, mock_success]

        # Create proxy with passphrase for retry
        proxy = AwProxy(
            peer_target={"id": "actor1", "peerid": "peer123", "passphrase": "testpass"},
            config=config,
        )
        proxy.trust = mock_trust

        _ = proxy.get_resource(path="test/resource")

        # Verify both requests were made
        assert mock_get.call_count == 2

        # Check first request (bearer auth) had correlation headers
        first_call = mock_get.call_args_list[0]
        first_headers = first_call.kwargs["headers"]
        assert "X-Request-ID" in first_headers
        assert "X-Parent-Request-ID" in first_headers
        original_request_id = first_headers["X-Request-ID"]

        # Check retry request (basic auth) preserved same correlation headers
        second_call = mock_get.call_args_list[1]
        second_headers = second_call.kwargs["headers"]
        assert "X-Request-ID" in second_headers
        assert "X-Parent-Request-ID" in second_headers
        # Should preserve the same request ID from original attempt
        assert second_headers["X-Request-ID"] == original_request_id
        assert second_headers["X-Parent-Request-ID"] == "test-retry-parent"


class TestProxyCorrelationAsync:
    """Tests for correlation headers in async peer requests."""

    def teardown_method(self) -> None:
        """Clean up after each test."""
        request_context.clear_request_context()

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_get_resource_async_sends_correlation_headers(
        self, mock_client_class: MagicMock, config: Config
    ) -> None:
        """Test that async GET requests send correlation headers."""
        request_context.set_request_context(
            request_id="test-async-parent", actor_id="actor1"
        )

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}

        # Mock async client - use AsyncMock for async methods
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client

        # Create proxy and make async request
        mock_trust = {
            "baseuri": "https://peer.example.com/actor123",
            "secret": "test-secret-token-123",
        }
        proxy = AwProxy(peer_target={"id": "actor1", "peerid": "peer123"}, config=config)
        proxy.trust = mock_trust

        _ = await proxy.get_resource_async(path="test/resource")

        # Verify request was made with correlation headers
        assert mock_client.get.called
        call_args = mock_client.get.call_args
        headers = call_args.kwargs["headers"]

        assert "X-Request-ID" in headers
        assert "X-Parent-Request-ID" in headers
        assert headers["X-Parent-Request-ID"] == "test-async-parent"

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient")
    async def test_async_retry_preserves_correlation_headers(
        self, mock_client_class: MagicMock, config: Config
    ) -> None:
        """Test that async retry preserves correlation headers."""
        request_context.set_request_context(
            request_id="test-async-retry-parent", actor_id="actor1"
        )

        # Mock initial 401 response
        mock_unauthorized = MagicMock()
        mock_unauthorized.status_code = 401

        # Mock successful retry
        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {"result": "success"}

        # Mock first client (bearer auth) - use AsyncMock for async methods
        mock_client1 = AsyncMock()
        mock_client1.__aenter__.return_value = mock_client1
        mock_client1.__aexit__.return_value = None
        mock_client1.get.return_value = mock_unauthorized

        # Mock second client (basic auth retry) - use AsyncMock for async methods
        mock_client2 = AsyncMock()
        mock_client2.__aenter__.return_value = mock_client2
        mock_client2.__aexit__.return_value = None
        mock_client2.get.return_value = mock_success

        mock_client_class.side_effect = [mock_client1, mock_client2]

        # Create proxy with passphrase for retry
        mock_trust = {
            "baseuri": "https://peer.example.com/actor123",
            "secret": "test-secret-token-123",
        }
        proxy = AwProxy(
            peer_target={"id": "actor1", "peerid": "peer123", "passphrase": "testpass"},
            config=config,
        )
        proxy.trust = mock_trust

        _ = await proxy.get_resource_async(path="test/resource")

        # Verify both requests were made
        assert mock_client1.get.called
        assert mock_client2.get.called

        # Check first request had correlation headers
        first_headers = mock_client1.get.call_args.kwargs["headers"]
        assert "X-Request-ID" in first_headers
        assert "X-Parent-Request-ID" in first_headers
        original_request_id = first_headers["X-Request-ID"]

        # Check retry preserved correlation headers
        second_headers = mock_client2.get.call_args.kwargs["headers"]
        assert "X-Request-ID" in second_headers
        assert "X-Parent-Request-ID" in second_headers
        # Should preserve the same request ID
        assert second_headers["X-Request-ID"] == original_request_id
        assert second_headers["X-Parent-Request-ID"] == "test-async-retry-parent"


class TestCorrelationLogging:
    """Tests for correlation logging."""

    def teardown_method(self) -> None:
        """Clean up after each test."""
        request_context.clear_request_context()

    def test_correlation_logged_with_parent(
        self, config: Config, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that correlation is logged when parent context exists."""
        import logging

        request_context.set_request_context(
            request_id="logged-parent-id-12345", actor_id="actor1"
        )

        # Create proxy
        mock_trust = {
            "baseuri": "https://peer.example.com/actor123",
            "secret": "test-secret",
        }
        proxy = AwProxy(peer_target={"id": "actor1", "peerid": "peer123"}, config=config)
        proxy.trust = mock_trust

        with caplog.at_level(logging.DEBUG, logger="actingweb.aw_proxy"):
            _ = proxy._bearer_headers()

        # Check logs contain correlation info
        assert any("Peer request correlation:" in record.message for record in caplog.records)
        # parent_id is truncated to first 8 chars
        assert any("parent_id=logged-p..." in record.message for record in caplog.records)

    def test_correlation_logged_without_parent(
        self, config: Config, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that correlation is logged when no parent context exists."""
        import logging

        request_context.clear_request_context()

        # Create proxy
        mock_trust = {
            "baseuri": "https://peer.example.com/actor123",
            "secret": "test-secret",
        }
        proxy = AwProxy(peer_target={"id": "actor1", "peerid": "peer123"}, config=config)
        proxy.trust = mock_trust

        with caplog.at_level(logging.DEBUG, logger="actingweb.aw_proxy"):
            _ = proxy._bearer_headers()

        # Check logs indicate no parent
        assert any("(no parent)" in record.message for record in caplog.records)
