"""
Application-specific hooks for ActingWeb demo.

These hooks implement your application's business logic:
- Methods: RPC-style read-only operations (calculate, search, etc.)
- Actions: Operations with external effects (notifications, logging)
- Callbacks: Webhooks for external services (email, SMS, payments)
- Properties: Property access control and validation
- UI: Custom pages under /www endpoint

Customize these hooks to build your application's functionality.
"""

from .action_hooks import register_action_hooks
from .callback_hooks import register_callback_hooks
from .method_hooks import register_method_hooks
from .property_hooks import register_property_hooks
from .ui_hooks import register_ui_hooks

__all__ = [
    "register_method_hooks",
    "register_action_hooks",
    "register_callback_hooks",
    "register_property_hooks",
    "register_ui_hooks",
    "register_all_app_hooks",
]


def register_all_app_hooks(app):
    """Register all application-specific hooks with an ActingWeb application."""
    register_property_hooks(app)
    register_method_hooks(app)
    register_action_hooks(app)
    register_callback_hooks(app)
    register_ui_hooks(app)
