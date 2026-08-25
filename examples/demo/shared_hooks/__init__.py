"""
Shared hooks for ActingWeb demo applications.

This module provides common hook implementations organized by purpose:

Protocol-Level Hooks (shared_hooks/protocol/):
    ActingWeb core protocol functionality
    - subscription_hooks: Handle data from actor-to-actor subscriptions
    - trust_hooks: Handle trust relationship lifecycle events
    - lifecycle_hooks: Handle actor creation, deletion, OAuth events

App-Specific Hooks (shared_hooks/app/):
    Your application's business logic
    - method_hooks: RPC-style read-only operations (calculate, search, etc.)
    - action_hooks: Operations with external effects (notifications, logging)
    - callback_hooks: Webhooks for external services (email, SMS, payments)
    - property_hooks: Property access control and validation

Usage:
    from shared_hooks import register_all_shared_hooks

    app = ActingWebApp(...)
    register_all_shared_hooks(app)
"""

from .app import (
    register_action_hooks,
    register_all_app_hooks,
    register_callback_hooks,
    register_method_hooks,
    register_property_hooks,
    register_ui_hooks,
)
from .protocol import (
    register_all_protocol_hooks,
    register_lifecycle_hooks,
    register_subscription_hooks,
    register_trust_hooks,
)

__all__ = [
    # Protocol-level hooks
    "register_subscription_hooks",
    "register_trust_hooks",
    "register_lifecycle_hooks",
    "register_all_protocol_hooks",
    # App-specific hooks
    "register_method_hooks",
    "register_action_hooks",
    "register_callback_hooks",
    "register_property_hooks",
    "register_ui_hooks",
    "register_all_app_hooks",
    # Convenience function
    "register_all_shared_hooks",
]


def register_all_shared_hooks(app):
    """
    Register all shared hooks with an ActingWeb application.

    This registers both protocol-level and app-specific hooks.

    Args:
        app: ActingWebApp instance to register hooks with
    """
    # Protocol-level hooks (ActingWeb core)
    register_all_protocol_hooks(app)

    # App-specific hooks (your application)
    register_all_app_hooks(app)
