"""Tests for FanOutManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from actingweb.fanout import (
    CircuitBreaker,
    CircuitState,
    DeliveryResult,
    FanOutManager,
    FanOutResult,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_initial_state_is_closed(self) -> None:
        """Circuit breaker starts in closed state."""
        cb = CircuitBreaker(peer_id="peer1")
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.should_allow_request() is True

    def test_record_success_resets_failures(self) -> None:
        """Recording success resets failure count."""
        cb = CircuitBreaker(peer_id="peer1")
        cb.failure_count = 3
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED
        assert cb.last_success_time > 0

    def test_record_failure_increments_count(self) -> None:
        """Recording failure increments count."""
        cb = CircuitBreaker(peer_id="peer1")
        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.last_failure_time > 0

    def test_circuit_opens_after_threshold(self) -> None:
        """Circuit opens after threshold failures."""
        cb = CircuitBreaker(peer_id="peer1", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.should_allow_request() is False

    def test_circuit_half_opens_after_cooldown(self) -> None:
        """Circuit becomes half-open after cooldown."""
        cb = CircuitBreaker(peer_id="peer1", failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for cooldown
        import time

        time.sleep(0.02)

        assert cb.should_allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_test_request(self) -> None:
        """Half-open state allows test request."""
        cb = CircuitBreaker(peer_id="peer1")
        cb.state = CircuitState.HALF_OPEN
        assert cb.should_allow_request() is True

    def test_success_in_half_open_closes_circuit(self) -> None:
        """Success in half-open state closes circuit."""
        cb = CircuitBreaker(peer_id="peer1")
        cb.state = CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestDeliveryResult:
    """Tests for DeliveryResult dataclass."""

    def test_successful_result(self) -> None:
        """Create successful delivery result."""
        result = DeliveryResult(
            peer_id="peer1",
            subscription_id="sub1",
            success=True,
            status_code=200,
        )
        assert result.success is True
        assert result.error is None

    def test_failed_result(self) -> None:
        """Create failed delivery result."""
        result = DeliveryResult(
            peer_id="peer1",
            subscription_id="sub1",
            success=False,
            status_code=503,
            error="service_unavailable",
        )
        assert result.success is False
        assert result.error == "service_unavailable"

    def test_result_with_retry_after(self) -> None:
        """Create result with retry-after header."""
        result = DeliveryResult(
            peer_id="peer1",
            subscription_id="sub1",
            success=False,
            status_code=429,
            error="rate_limited",
            retry_after=60,
        )
        assert result.retry_after == 60


class TestFanOutManager:
    """Tests for FanOutManager."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_actor = MagicMock()
        self.mock_actor.id = "actor123"
        self.mock_actor.config.proto = "https://"
        self.mock_actor.config.fqdn = "example.com"
        self.mock_actor.trust.get_trust.return_value = {"secret": "test_token"}

        self.manager = FanOutManager(
            actor=self.mock_actor,
            max_concurrent=5,
            circuit_breaker_threshold=3,
            circuit_breaker_cooldown=60.0,
            request_timeout=10.0,
        )

    def test_initialization(self) -> None:
        """Test manager initialization."""
        assert self.manager._max_concurrent == 5
        assert self.manager._cb_threshold == 3
        assert self.manager._cb_cooldown == 60.0

    def test_get_circuit_breaker_creates_new(self) -> None:
        """Get circuit breaker creates one if not exists."""
        cb = self.manager._get_circuit_breaker("peer1")
        assert cb.peer_id == "peer1"
        assert cb.failure_threshold == 3
        assert cb.cooldown_seconds == 60.0

    def test_get_circuit_breaker_reuses_existing(self) -> None:
        """Get circuit breaker reuses existing one."""
        cb1 = self.manager._get_circuit_breaker("peer1")
        cb1.failure_count = 5
        cb2 = self.manager._get_circuit_breaker("peer1")
        assert cb2.failure_count == 5

    def test_get_circuit_breaker_status(self) -> None:
        """Get status of all circuit breakers."""
        cb = self.manager._get_circuit_breaker("peer1")
        cb.record_failure()

        status = self.manager.get_circuit_breaker_status()
        assert "peer1" in status
        assert status["peer1"]["failure_count"] == 1
        assert status["peer1"]["state"] == "closed"

    def test_reset_circuit_breaker(self) -> None:
        """Reset a circuit breaker."""
        cb = self.manager._get_circuit_breaker("peer1")
        cb.failure_count = 10
        cb.state = CircuitState.OPEN

        self.manager.reset_circuit_breaker("peer1")

        cb = self.manager._get_circuit_breaker("peer1")
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_build_resource_url(self) -> None:
        """Build resource URL correctly."""
        url = self.manager._build_resource_url("properties")
        assert url == "https://example.com/actor123/properties"

    @pytest.mark.asyncio
    async def test_deliver_to_empty_subscribers(self) -> None:
        """Deliver to empty subscriber list."""
        result = await self.manager.deliver_to_subscribers([], {}, "target", 1)
        assert result.total == 0
        assert result.successful == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_deliver_success(self) -> None:
        """Successful delivery to subscriber."""
        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]
        payload = {"key": "value"}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await self.manager.deliver_to_subscribers(
                subscriptions, payload, "properties", 1
            )

        assert result.total == 1
        assert result.successful == 1
        assert result.failed == 0
        assert result.results[0].success is True

    @pytest.mark.asyncio
    async def test_deliver_204_success(self) -> None:
        """204 response is also successful."""
        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await self.manager.deliver_to_subscribers(
                subscriptions, {"data": "test"}, "properties", 1
            )

        assert result.successful == 1

    @pytest.mark.asyncio
    async def test_deliver_rate_limited(self) -> None:
        """Handle 429 rate limit response."""
        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "30"}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await self.manager.deliver_to_subscribers(
                subscriptions, {"data": "test"}, "properties", 1
            )

        assert result.failed == 1
        assert result.results[0].error == "rate_limited"
        assert result.results[0].retry_after == 30

    @pytest.mark.asyncio
    async def test_deliver_service_unavailable(self) -> None:
        """Handle 503 service unavailable."""
        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await self.manager.deliver_to_subscribers(
                subscriptions, {"data": "test"}, "properties", 1
            )

        assert result.failed == 1
        assert result.results[0].error == "service_unavailable"

    @pytest.mark.asyncio
    async def test_deliver_timeout(self) -> None:
        """Handle request timeout."""
        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await self.manager.deliver_to_subscribers(
                subscriptions, {"data": "test"}, "properties", 1
            )

        assert result.failed == 1
        assert result.results[0].error == "timeout"

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_request(self) -> None:
        """Circuit breaker blocks requests when open."""
        import time

        # Open the circuit breaker
        cb = self.manager._get_circuit_breaker("peer1")
        cb.state = CircuitState.OPEN
        cb.last_failure_time = time.time()  # Recent failure, within cooldown

        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]

        result = await self.manager.deliver_to_subscribers(
            subscriptions, {"data": "test"}, "properties", 1
        )

        assert result.circuit_open == 1
        assert result.results[0].error == "circuit_open"

    @pytest.mark.asyncio
    async def test_granularity_downgrade(self) -> None:
        """Large payload triggers granularity downgrade."""
        # Create manager with small threshold
        manager = FanOutManager(
            actor=self.mock_actor,
            max_payload_for_high_granularity=10,  # Very small
        )

        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]
        large_payload = {"data": "x" * 100}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await manager.deliver_to_subscribers(
                subscriptions, large_payload, "properties", 1
            )

            # Check that downgrade header was set
            call_args = mock_client.post.call_args
            headers = call_args.kwargs.get("headers", {})
            assert headers.get("X-ActingWeb-Granularity-Downgraded") == "true"

        assert result.results[0].granularity_downgraded is True

    @pytest.mark.asyncio
    async def test_no_downgrade_for_low_granularity(self) -> None:
        """Low granularity subscriptions are not downgraded."""
        manager = FanOutManager(
            actor=self.mock_actor,
            max_payload_for_high_granularity=10,
        )

        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "low",  # Already low
            }
        ]
        large_payload = {"data": "x" * 100}

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await manager.deliver_to_subscribers(
                subscriptions, large_payload, "properties", 1
            )

        assert result.results[0].granularity_downgraded is False

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self) -> None:
        """Deliver to multiple subscribers."""
        subscriptions = [
            {
                "peerid": f"peer{i}",
                "subid": f"sub{i}",
                "callback_url": f"https://peer{i}.example.com/callback",
                "granularity": "high",
            }
            for i in range(3)
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await self.manager.deliver_to_subscribers(
                subscriptions, {"data": "test"}, "properties", 1
            )

        assert result.total == 3
        assert result.successful == 3

    @pytest.mark.asyncio
    async def test_mixed_results(self) -> None:
        """Handle mix of successful and failed deliveries."""
        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            },
            {
                "peerid": "peer2",
                "subid": "sub2",
                "callback_url": "https://peer2.example.com/callback",
                "granularity": "high",
            },
        ]

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200

        mock_response_fail = MagicMock()
        mock_response_fail.status_code = 500

        call_count = 0

        async def mock_post(*_args: object, **_kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response_success
            return mock_response_fail

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await self.manager.deliver_to_subscribers(
                subscriptions, {"data": "test"}, "properties", 1
            )

        assert result.total == 2
        assert result.successful == 1
        assert result.failed == 1

    def test_sync_delivery(self) -> None:
        """Test synchronous delivery wrapper."""
        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            # Use new event loop for sync test
            result = self.manager.deliver_to_subscribers_sync(
                subscriptions, {"data": "test"}, "properties", 1
            )

        assert result.total == 1
        assert result.successful == 1

    @pytest.mark.asyncio
    async def test_authorization_header_added(self) -> None:
        """Authorization header is added when trust exists."""
        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await self.manager.deliver_to_subscribers(
                subscriptions, {"data": "test"}, "properties", 1
            )

            call_args = mock_client.post.call_args
            headers = call_args.kwargs.get("headers", {})
            assert headers.get("Authorization") == "Bearer test_token"

    @pytest.mark.asyncio
    async def test_no_auth_when_no_trust(self) -> None:
        """No authorization when trust doesn't exist."""
        self.mock_actor.trust.get_trust.return_value = None

        subscriptions = [
            {
                "peerid": "peer1",
                "subid": "sub1",
                "callback_url": "https://peer1.example.com/callback",
                "granularity": "high",
            }
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await self.manager.deliver_to_subscribers(
                subscriptions, {"data": "test"}, "properties", 1
            )

            call_args = mock_client.post.call_args
            headers = call_args.kwargs.get("headers", {})
            assert "Authorization" not in headers


class TestFanOutResult:
    """Tests for FanOutResult dataclass."""

    def test_create_result(self) -> None:
        """Create FanOutResult."""
        result = FanOutResult(
            total=10,
            successful=7,
            failed=2,
            circuit_open=1,
        )
        assert result.total == 10
        assert result.successful == 7
        assert result.failed == 2
        assert result.circuit_open == 1

    def test_result_with_details(self) -> None:
        """Create result with delivery details."""
        details = [
            DeliveryResult(
                peer_id="peer1", subscription_id="sub1", success=True, status_code=200
            ),
            DeliveryResult(
                peer_id="peer2",
                subscription_id="sub2",
                success=False,
                error="timeout",
            ),
        ]
        result = FanOutResult(
            total=2,
            successful=1,
            failed=1,
            circuit_open=0,
            results=details,
        )
        assert len(result.results) == 2
