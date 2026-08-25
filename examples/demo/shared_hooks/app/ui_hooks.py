"""
UI hooks for ActingWeb demo applications.

UI hooks extend the built-in /www endpoint with custom pages.
The ActingWeb framework provides default pages for actor management,
and these hooks let you add application-specific pages.

Custom pages are served at: GET /{actor_id}/www/{path}
"""

import logging
from typing import Any

from actingweb.interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)


def register_ui_hooks(app):
    """Register UI hooks with the ActingWeb application."""

    @app.callback_hook("www")
    def handle_www_paths(
        actor: ActorInterface, name: str, data: dict[str, Any]
    ) -> dict[str, Any] | bool:
        """
        Handle custom www paths for web UI extensions.

        Endpoint: GET /{actor_id}/www/{path}

        Parameters:
            path: The sub-path being requested (e.g., "demo")

        Returns:
            For template rendering: {"template": "template-name.html", "data": {...}}
            False to fall through to default handling

        Template Rendering:
            When returning {"template": "...", "data": {...}}, ActingWeb renders
            that template with the provided data merged with standard template
            variables (id, url, actor_root, actor_www).

        Available Custom Paths:
            - demo: API Explorer page for testing hooks interactively
        """
        path = data.get("path", "")

        if path == "demo":
            return {
                "template": "aw-actor-www-demo.html",
                "data": {},
            }

        # Fall through to default handling for unknown paths
        return False
