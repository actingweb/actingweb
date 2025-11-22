"""
ActingWeb Third-Party Service Integration Module

Provides a unified, clean interface for integrating with OAuth2-protected third-party services
like Dropbox, Gmail, GitHub, etc. This replaces the legacy OAuth class with a modern,
developer-friendly API built on top of the new OAuth2 system.

Key Features:
- Unified service registration and configuration
- Automatic token management and refresh
- Clean developer interface similar to other ActingWeb functionality
- Built on modern OAuth2 foundation with oauthlib
- Per-actor service authentication with trust relationship storage
"""

from .service_client import ServiceClient
from .service_config import ServiceConfig
from .service_registry import ServiceRegistry

__all__ = ["ServiceRegistry", "ServiceClient", "ServiceConfig"]
