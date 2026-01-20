"""
Fan-out manager for subscription callback delivery.

Provides scalable callback delivery with:
- Parallel HTTP requests with bounded concurrency
- Circuit breaker pattern for failing peers
- Automatic granularity downgrade for large payloads
"""

import asyncio
import gzip
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .interface.actor_interface import ActorInterface
    from .peer_capabilities import PeerCapabilities

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreaker:
    """Circuit breaker for a single peer."""

    peer_id: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0

    # Configuration
    failure_threshold: int = 5
    cooldown_seconds: float = 60.0

    def record_success(self) -> None:
        """Record successful delivery."""
        self.failure_count = 0
        self.last_success_time = time.time()
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record failed delivery."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            logger.warning(
                f"Circuit breaker opened for peer {self.peer_id} "
                f"after {self.failure_count} failures"
            )
            self.state = CircuitState.OPEN

    def should_allow_request(self) -> bool:
        """Check if request should be allowed."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if cooldown has passed
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.cooldown_seconds:
                logger.info(
                    f"Circuit breaker half-open for peer {self.peer_id}, "
                    f"testing recovery"
                )
                self.state = CircuitState.HALF_OPEN
                return True
            return False

        # HALF_OPEN - allow one test request
        return True


@dataclass
class DeliveryResult:
    """Result of delivering to a single subscriber."""

    peer_id: str
    subscription_id: str
    success: bool
    status_code: int | None = None
    error: str | None = None
    retry_after: int | None = None
    granularity_downgraded: bool = False


@dataclass
class FanOutResult:
    """Result of fan-out delivery to all subscribers."""

    total: int
    successful: int
    failed: int
    circuit_open: int
    results: list[DeliveryResult] = field(default_factory=list)


class FanOutManager:
    """
    Manages callback delivery to multiple subscribers at scale.

    Implements protocol v1.4 features:
    - Automatic granularity downgrade when payload > threshold
    - Circuit breaker pattern for handling 429/503 responses
    - Optional compression for large payloads
    """

    def __init__(
        self,
        actor: "ActorInterface",
        max_concurrent: int = 10,
        max_payload_for_high_granularity: int = 65536,  # 64KB
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: float = 60.0,
        request_timeout: float = 30.0,
        enable_compression: bool = True,
    ) -> None:
        """
        Initialize fan-out manager.

        Args:
            actor: The actor sending callbacks
            max_concurrent: Maximum concurrent HTTP requests
            max_payload_for_high_granularity: Payload size limit before downgrade
            circuit_breaker_threshold: Failures before opening circuit
            circuit_breaker_cooldown: Seconds before testing recovery
            request_timeout: HTTP request timeout in seconds
            enable_compression: Whether to use compression when supported
        """
        self._actor = actor
        self._max_concurrent = max_concurrent
        self._max_payload_size = max_payload_for_high_granularity
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown
        self._request_timeout = request_timeout
        self._enable_compression = enable_compression

        # Circuit breakers per peer
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    def _get_circuit_breaker(self, peer_id: str) -> CircuitBreaker:
        """Get or create circuit breaker for peer."""
        if peer_id not in self._circuit_breakers:
            self._circuit_breakers[peer_id] = CircuitBreaker(
                peer_id=peer_id,
                failure_threshold=self._cb_threshold,
                cooldown_seconds=self._cb_cooldown,
            )
        return self._circuit_breakers[peer_id]

    async def deliver_to_subscribers(
        self,
        subscriptions: list[dict[str, Any]],
        payload: dict[str, Any],
        target: str,
        sequence: int,
    ) -> FanOutResult:
        """
        Deliver callbacks to multiple subscribers.

        Args:
            subscriptions: List of subscription dicts with callback URLs
            payload: The callback payload data
            target: Target resource (e.g., "properties")
            sequence: Sequence number for this callback

        Returns:
            FanOutResult with delivery statistics
        """
        if not subscriptions:
            return FanOutResult(total=0, successful=0, failed=0, circuit_open=0)

        # Prepare payload
        payload_json = json.dumps(payload)
        payload_size = len(payload_json.encode("utf-8"))
        needs_downgrade = payload_size > self._max_payload_size

        # Create semaphore for bounded concurrency
        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def deliver_one(sub: dict[str, Any]) -> DeliveryResult:
            peer_id = sub.get("peerid", "")
            sub_id = sub.get("subid", "")
            callback_url = sub.get("callback_url", "")
            granularity = sub.get("granularity", "high")

            # Check circuit breaker
            cb = self._get_circuit_breaker(peer_id)
            if not cb.should_allow_request():
                return DeliveryResult(
                    peer_id=peer_id,
                    subscription_id=sub_id,
                    success=False,
                    error="circuit_open",
                )

            async with semaphore:
                return await self._deliver_single(
                    peer_id=peer_id,
                    subscription_id=sub_id,
                    callback_url=callback_url,
                    payload=payload,
                    payload_size=payload_size,
                    target=target,
                    sequence=sequence,
                    granularity=granularity,
                    needs_downgrade=needs_downgrade,
                )

        # Execute deliveries concurrently
        results = await asyncio.gather(
            *[deliver_one(sub) for sub in subscriptions], return_exceptions=True
        )

        # Process results
        delivery_results: list[DeliveryResult] = []
        successful = 0
        failed = 0
        circuit_open = 0

        for result in results:
            if isinstance(result, BaseException):
                delivery_results.append(
                    DeliveryResult(
                        peer_id="unknown",
                        subscription_id="unknown",
                        success=False,
                        error=str(result),
                    )
                )
                failed += 1
            elif result.success:
                successful += 1
                delivery_results.append(result)
            elif result.error == "circuit_open":
                circuit_open += 1
                delivery_results.append(result)
            else:
                failed += 1
                delivery_results.append(result)

        return FanOutResult(
            total=len(subscriptions),
            successful=successful,
            failed=failed,
            circuit_open=circuit_open,
            results=delivery_results,
        )

    async def _deliver_single(
        self,
        peer_id: str,
        subscription_id: str,
        callback_url: str,
        payload: dict[str, Any],
        payload_size: int,
        target: str,
        sequence: int,
        granularity: str,
        needs_downgrade: bool,
    ) -> DeliveryResult:
        """Deliver callback to a single subscriber."""
        cb = self._get_circuit_breaker(peer_id)

        try:
            # Build callback wrapper per protocol spec
            callback_wrapper: dict[str, Any] = {
                "id": self._actor.id,
                "target": target,
                "sequence": sequence,
                "timestamp": self._get_timestamp(),
                "granularity": granularity,
                "subscriptionid": subscription_id,
            }

            headers: dict[str, str] = {
                "Content-Type": "application/json",
            }

            # Handle granularity downgrade
            granularity_downgraded = False
            if needs_downgrade and granularity == "high":
                # Downgrade to low granularity - send URL instead of data
                callback_wrapper["granularity"] = "low"
                callback_wrapper["url"] = self._build_resource_url(target)
                headers["X-ActingWeb-Granularity-Downgraded"] = "true"
                granularity_downgraded = True
            else:
                callback_wrapper["data"] = payload

            body = json.dumps(callback_wrapper)
            body_bytes = body.encode("utf-8")

            # Compress if enabled and beneficial
            if self._enable_compression and len(body_bytes) > 1024:
                # Check if peer supports compression
                caps = self._get_peer_capabilities(peer_id)
                if caps and caps.supports("compression"):
                    body_bytes = gzip.compress(body_bytes)
                    headers["Content-Encoding"] = "gzip"

            # Add auth token
            trust = self._actor.trust.get_trust(peer_id)
            if trust:
                headers["Authorization"] = f"Bearer {trust.get('secret', '')}"

            # Make HTTP request
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self._request_timeout)
            ) as client:
                response = await client.post(
                    callback_url, content=body_bytes, headers=headers
                )
                status = response.status_code

                if status in (200, 204):
                    cb.record_success()
                    return DeliveryResult(
                        peer_id=peer_id,
                        subscription_id=subscription_id,
                        success=True,
                        status_code=status,
                        granularity_downgraded=granularity_downgraded,
                    )
                elif status == 429:
                    # Rate limited - respect Retry-After
                    retry_after = response.headers.get("Retry-After")
                    cb.record_failure()
                    return DeliveryResult(
                        peer_id=peer_id,
                        subscription_id=subscription_id,
                        success=False,
                        status_code=status,
                        error="rate_limited",
                        retry_after=int(retry_after) if retry_after else None,
                    )
                elif status == 503:
                    cb.record_failure()
                    return DeliveryResult(
                        peer_id=peer_id,
                        subscription_id=subscription_id,
                        success=False,
                        status_code=status,
                        error="service_unavailable",
                    )
                else:
                    cb.record_failure()
                    return DeliveryResult(
                        peer_id=peer_id,
                        subscription_id=subscription_id,
                        success=False,
                        status_code=status,
                        error=f"http_error_{status}",
                    )

        except httpx.TimeoutException:
            cb.record_failure()
            return DeliveryResult(
                peer_id=peer_id,
                subscription_id=subscription_id,
                success=False,
                error="timeout",
            )
        except Exception as e:
            cb.record_failure()
            logger.error(f"Error delivering to {peer_id}: {e}")
            return DeliveryResult(
                peer_id=peer_id,
                subscription_id=subscription_id,
                success=False,
                error=str(e),
            )

    def _get_timestamp(self) -> str:
        """Get ISO timestamp for callback."""
        return datetime.now(UTC).isoformat()

    def _build_resource_url(self, target: str) -> str:
        """Build URL for low granularity callbacks."""
        config = self._actor.config
        return f"{config.proto}{config.fqdn}/{self._actor.id}/{target}"

    def _get_peer_capabilities(self, peer_id: str) -> "PeerCapabilities | None":
        """Get peer capabilities if available."""
        try:
            from .peer_capabilities import PeerCapabilities

            return PeerCapabilities(self._actor, peer_id)
        except Exception:
            return None

    def get_circuit_breaker_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all circuit breakers."""
        return {
            peer_id: {
                "state": cb.state.value,
                "failure_count": cb.failure_count,
                "last_failure_time": cb.last_failure_time,
                "last_success_time": cb.last_success_time,
            }
            for peer_id, cb in self._circuit_breakers.items()
        }

    def reset_circuit_breaker(self, peer_id: str) -> None:
        """Manually reset a circuit breaker."""
        if peer_id in self._circuit_breakers:
            self._circuit_breakers[peer_id] = CircuitBreaker(
                peer_id=peer_id,
                failure_threshold=self._cb_threshold,
                cooldown_seconds=self._cb_cooldown,
            )

    def deliver_to_subscribers_sync(
        self,
        subscriptions: list[dict[str, Any]],
        payload: dict[str, Any],
        target: str,
        sequence: int,
    ) -> FanOutResult:
        """
        Synchronous version of deliver_to_subscribers.

        Runs the async version in an event loop.
        """
        return asyncio.get_event_loop().run_until_complete(
            self.deliver_to_subscribers(subscriptions, payload, target, sequence)
        )
