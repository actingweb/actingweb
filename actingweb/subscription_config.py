"""
Configuration for automatic subscription processing.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


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
        max_pending: Maximum pending callbacks; a callback beyond it is refused with 400
        storage_prefix: Bucket prefix for RemotePeerStore
        max_concurrent_callbacks: Callbacks of one write sent at once to
            subscribers on other hosts (3.16: read by the sender; default 4)
        callback_delivery_budget_seconds: Total time one request may spend
            delivering its callbacks; None (the default) for no budget
        serialize_own_host_callbacks: Send subscribers on the publisher's own
            host one at a time (default True; turn off for a deployment that
            serves one request per function instance)
        subscription_data_hooks: Dict mapping target names to list of hook callables
    """

    enabled: bool = False
    auto_sequence: bool = True
    auto_storage: bool = True
    auto_cleanup: bool = True
    gap_timeout_seconds: float = 5.0
    max_pending: int = 100
    storage_prefix: str = "remote:"

    # Outbound delivery (3.16, actingweb.callback_sender)
    max_concurrent_callbacks: int = 4
    callback_delivery_budget_seconds: float | None = None
    serialize_own_host_callbacks: bool = True

    # Hooks for subscription data processing
    subscription_data_hooks: dict[str, list[Callable[..., Any]]] = field(
        default_factory=dict
    )
