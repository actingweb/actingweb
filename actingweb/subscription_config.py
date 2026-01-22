"""
Configuration for automatic subscription processing.
"""

from dataclasses import dataclass


@dataclass
class SubscriptionProcessingConfig:
    """Configuration for automatic subscription processing.

    This dataclass holds configuration for the automatic subscription
    callback processing pipeline.

    Attributes:
        enabled: Whether automatic subscription processing is enabled
        auto_sequence: Enable CallbackProcessor for sequence handling
        auto_storage: Automatically store received data in RemotePeerStore
        auto_cleanup: Register hook to clean up when trust is deleted
        gap_timeout_seconds: Time before triggering resync on sequence gap
        max_pending: Maximum pending callbacks before back-pressure (429)
        storage_prefix: Bucket prefix for RemotePeerStore
        max_concurrent_callbacks: Max concurrent callback deliveries
        max_payload_for_high_granularity: Payload size before granularity downgrade
        circuit_breaker_threshold: Failures before opening circuit
        circuit_breaker_cooldown: Seconds before testing recovery
    """

    enabled: bool = False
    auto_sequence: bool = True
    auto_storage: bool = True
    auto_cleanup: bool = True
    gap_timeout_seconds: float = 5.0
    max_pending: int = 100
    storage_prefix: str = "remote:"

    # Fan-out settings
    max_concurrent_callbacks: int = 10
    max_payload_for_high_granularity: int = 65536
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown: float = 60.0
