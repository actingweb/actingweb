"""
Fan-out manager for subscription callback delivery.

Provides scalable callback delivery with:
- Parallel HTTP requests with bounded concurrency
- Circuit breaker pattern for failing peers (with persistence for Kubernetes)
- Automatic granularity downgrade for large payloads
- Connection pooling via shared HTTP client
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

# Shared HTTP client for connection pooling (module-level singleton)
_shared_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def get_shared_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Get or create shared HTTP client for connection pooling.

    Using a shared client provides:
    - Connection pooling and reuse
    - Reduced TIME_WAIT socket accumulation
    - Better performance with many subscribers
    """
    global _shared_client
    async with _client_lock:
        if _shared_client is None or _shared_client.is_closed:
            _shared_client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0,
                ),
            )
    return _shared_client


async def close_shared_client() -> None:
    """Close the shared HTTP client. Call during application shutdown."""
    global _shared_client
    async with _client_lock:
        if _shared_client is not None and not _shared_client.is_closed:
            await _shared_client.aclose()
            _shared_client = None


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreaker:
    """Circuit breaker for a single peer.

    State can be persisted to survive pod restarts in Kubernetes deployments.
    """

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

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for persistence."""
        return {
            "peer_id": self.peer_id,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CircuitBreaker":
        """Deserialize from dict."""
        return cls(
            peer_id=data.get("peer_id", ""),
            state=CircuitState(data.get("state", "closed")),
            failure_count=data.get("failure_count", 0),
            last_failure_time=data.get("last_failure_time", 0.0),
            last_success_time=data.get("last_success_time", 0.0),
            failure_threshold=data.get("failure_threshold", 5),
            cooldown_seconds=data.get("cooldown_seconds", 60.0),
        )


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
    - Circuit breaker pattern for handling 429/503 responses (persisted for K8s)
    - Optional compression for large payloads
    - Connection pooling via shared HTTP client
    """

    # Storage bucket for circuit breaker state persistence
    _CB_STATE_BUCKET = "_circuit_breaker_state"

    def __init__(
        self,
        actor: "ActorInterface",
        max_concurrent: int = 10,
        max_payload_for_high_granularity: int = 65536,  # 64KB
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: float = 60.0,
        request_timeout: float = 30.0,
        enable_compression: bool = True,
        persist_circuit_breakers: bool = True,
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
            persist_circuit_breakers: Persist circuit breaker state (for Kubernetes)
        """
        self._actor = actor
        self._max_concurrent = max_concurrent
        self._max_payload_size = max_payload_for_high_granularity
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown
        self._request_timeout = request_timeout
        self._enable_compression = enable_compression
        self._persist_cb = persist_circuit_breakers

        # Circuit breakers per peer (in-memory cache)
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

        # Load persisted circuit breaker state
        if self._persist_cb:
            self._load_circuit_breaker_state()

    def _get_circuit_breaker(self, peer_id: str) -> CircuitBreaker:
        """Get or create circuit breaker for peer."""
        if peer_id not in self._circuit_breakers:
            # Try to load from persistence first
            cb = self._load_single_circuit_breaker(peer_id)
            if cb is None:
                cb = CircuitBreaker(
                    peer_id=peer_id,
                    failure_threshold=self._cb_threshold,
                    cooldown_seconds=self._cb_cooldown,
                )
            self._circuit_breakers[peer_id] = cb
        return self._circuit_breakers[peer_id]

    def _load_circuit_breaker_state(self) -> None:
        """Load all circuit breaker state from persistent storage."""
        try:
            from .attribute import Attributes

            db = Attributes(
                actor_id=self._actor.id,
                bucket=self._CB_STATE_BUCKET,
                config=self._actor.config,
            )
            all_attrs = db.get_bucket() or {}
            for attr_name, attr_data in all_attrs.items():
                if attr_name.startswith("cb:"):
                    data = attr_data.get("data") if attr_data else None
                    if data:
                        cb = CircuitBreaker.from_dict(data)
                        # Apply current config
                        cb.failure_threshold = self._cb_threshold
                        cb.cooldown_seconds = self._cb_cooldown
                        self._circuit_breakers[cb.peer_id] = cb
            if self._circuit_breakers:
                logger.debug(
                    f"Loaded {len(self._circuit_breakers)} circuit breaker states"
                )
        except Exception as e:
            logger.warning(f"Failed to load circuit breaker state: {e}")

    def _load_single_circuit_breaker(self, peer_id: str) -> CircuitBreaker | None:
        """Load a single circuit breaker from persistence."""
        if not self._persist_cb:
            return None
        try:
            from .attribute import Attributes

            db = Attributes(
                actor_id=self._actor.id,
                bucket=self._CB_STATE_BUCKET,
                config=self._actor.config,
            )
            attr = db.get_attr(name=f"cb:{peer_id}")
            data = attr.get("data") if attr else None
            if data:
                cb = CircuitBreaker.from_dict(data)
                cb.failure_threshold = self._cb_threshold
                cb.cooldown_seconds = self._cb_cooldown
                return cb
        except Exception as e:
            logger.debug(f"Failed to load circuit breaker for {peer_id}: {e}")
        return None

    def _persist_circuit_breaker(self, cb: CircuitBreaker) -> None:
        """Persist circuit breaker state."""
        if not self._persist_cb:
            return
        try:
            from .attribute import Attributes

            db = Attributes(
                actor_id=self._actor.id,
                bucket=self._CB_STATE_BUCKET,
                config=self._actor.config,
            )
            db.set_attr(name=f"cb:{cb.peer_id}", data=cb.to_dict())
        except Exception as e:
            logger.warning(f"Failed to persist circuit breaker for {cb.peer_id}: {e}")

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

            # Make HTTP request using shared client for connection pooling
            client = await get_shared_client(self._request_timeout)
            response = await client.post(
                callback_url, content=body_bytes, headers=headers
            )
            status = response.status_code

            if status in (200, 204):
                cb.record_success()
                self._persist_circuit_breaker(cb)
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
                self._persist_circuit_breaker(cb)
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
                self._persist_circuit_breaker(cb)
                return DeliveryResult(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    success=False,
                    status_code=status,
                    error="service_unavailable",
                )
            else:
                cb.record_failure()
                self._persist_circuit_breaker(cb)
                return DeliveryResult(
                    peer_id=peer_id,
                    subscription_id=subscription_id,
                    success=False,
                    status_code=status,
                    error=f"http_error_{status}",
                )

        except httpx.TimeoutException:
            cb.record_failure()
            self._persist_circuit_breaker(cb)
            return DeliveryResult(
                peer_id=peer_id,
                subscription_id=subscription_id,
                success=False,
                error="timeout",
            )
        except httpx.RequestError as e:
            cb.record_failure()
            self._persist_circuit_breaker(cb)
            logger.error(f"Request error delivering to {peer_id}: {e}")
            return DeliveryResult(
                peer_id=peer_id,
                subscription_id=subscription_id,
                success=False,
                error=f"request_error: {e}",
            )
        except Exception as e:
            cb.record_failure()
            self._persist_circuit_breaker(cb)
            logger.error(f"Unexpected error delivering to {peer_id}: {e}", exc_info=True)
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
        cb = CircuitBreaker(
            peer_id=peer_id,
            failure_threshold=self._cb_threshold,
            cooldown_seconds=self._cb_cooldown,
        )
        self._circuit_breakers[peer_id] = cb
        self._persist_circuit_breaker(cb)

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
        return asyncio.run(
            self.deliver_to_subscribers(subscriptions, payload, target, sequence)
        )
