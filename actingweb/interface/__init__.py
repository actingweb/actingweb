"""
Modern developer interface for ActingWeb library.

This module provides a clean, fluent API for building ActingWeb applications
with improved developer experience.
"""

from .actor_interface import ActorInterface
from .app import ActingWebApp
from .hooks import (
    HookRegistry,
    action_hook,
    app_callback_hook,
    callback_hook,
    method_hook,
    property_hook,
    subscription_hook,
)
from .property_store import PropertyStore
from .subscription_manager import SubscriptionManager
from .trust_manager import TrustManager

__all__ = [
    "ActingWebApp",
    "ActorInterface",
    "PropertyStore",
    "TrustManager",
    "SubscriptionManager",
    "HookRegistry",
    "property_hook",
    "callback_hook",
    "app_callback_hook",
    "subscription_hook",
    "method_hook",
    "action_hook",
]
