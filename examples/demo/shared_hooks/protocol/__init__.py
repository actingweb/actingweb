"""
Protocol-level hooks for ActingWeb.

These hooks handle core ActingWeb protocol functionality:
- Subscriptions: Data exchange between trusted actors
- Trust: Trust relationship lifecycle events
- Lifecycle: Actor creation, deletion, OAuth events

These are framework-level hooks that implement the ActingWeb protocol,
not application-specific business logic.
"""

from .lifecycle_hooks import register_lifecycle_hooks
from .subscription_hooks import register_subscription_hooks
from .trust_hooks import register_trust_hooks

__all__ = [
    "register_subscription_hooks",
    "register_trust_hooks",
    "register_lifecycle_hooks",
    "register_all_protocol_hooks",
]


def register_all_protocol_hooks(app):
    """Register all protocol-level hooks with an ActingWeb application."""
    register_subscription_hooks(app)
    register_trust_hooks(app)
    register_lifecycle_hooks(app)
