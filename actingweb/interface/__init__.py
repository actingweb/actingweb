"""
Modern developer interface for ActingWeb library.

This module provides a clean, fluent API for building ActingWeb applications
with improved developer experience.
"""

from .app import ActingWebApp
from .actor_interface import ActorInterface
from .property_store import PropertyStore
from .trust_manager import TrustManager
from .subscription_manager import SubscriptionManager
from .hooks import HookRegistry, property_hook, callback_hook, app_callback_hook, subscription_hook, method_hook, action_hook

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