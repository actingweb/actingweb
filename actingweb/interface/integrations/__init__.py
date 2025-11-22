"""
Web framework integrations for ActingWeb.

Provides seamless integration with popular Python web frameworks.
"""

try:
    from .flask_integration import FlaskIntegration

    _flask_available = True
except ImportError:
    _flask_available = False

try:
    from .fastapi_integration import FastAPIIntegration

    _fastapi_available = True
except ImportError:
    _fastapi_available = False

__all__ = []
if _flask_available:
    __all__.append("FlaskIntegration")
if _fastapi_available:
    __all__.append("FastAPIIntegration")
