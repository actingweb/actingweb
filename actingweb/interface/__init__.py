"""
Modern developer interface for ActingWeb library.

This module provides a clean, fluent API for building ActingWeb applications
with improved developer experience.
"""

from ..callback_processor import CallbackProcessor, CallbackType, ProcessResult
from ..fanout import FanOutManager, FanOutResult
from ..peer_capabilities import PeerCapabilities
from ..remote_storage import RemotePeerStore, get_remote_bucket
from ..subscription_config import SubscriptionProcessingConfig
from .actor_interface import ActorInterface
from .app import ActingWebApp
from .authenticated_views import (
    AuthContext,
    AuthenticatedActorView,
    AuthenticatedPropertyListStore,
    AuthenticatedPropertyStore,
    AuthenticatedSubscriptionManager,
    PermissionError,
)
from .hooks import (
    HookMetadata,
    HookRegistry,
    action_hook,
    app_callback_hook,
    callback_hook,
    get_hook_metadata,
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
    "HookMetadata",
    "get_hook_metadata",
    "property_hook",
    "callback_hook",
    "app_callback_hook",
    "subscription_hook",
    "method_hook",
    "action_hook",
    # Authenticated views
    "AuthContext",
    "AuthenticatedActorView",
    "AuthenticatedPropertyStore",
    "AuthenticatedPropertyListStore",
    "AuthenticatedSubscriptionManager",
    "PermissionError",
    # Subscription processing
    "CallbackProcessor",
    "ProcessResult",
    "CallbackType",
    "RemotePeerStore",
    "get_remote_bucket",
    "PeerCapabilities",
    "FanOutManager",
    "FanOutResult",
    "SubscriptionProcessingConfig",
]
