"""
OAuth2 email input handler for ActingWeb.

This handler manages the email input form when OAuth2 providers cannot provide
an email address. It allows users to manually enter their email to complete
actor creation.
"""

import logging
import json
from typing import Dict, Any, Optional, TYPE_CHECKING

from .base_handler import BaseHandler

if TYPE_CHECKING:
    from ..interface.hooks import HookRegistry
    from .. import aw_web_request
    from .. import config as config_class

logger = logging.getLogger(__name__)


class OAuth2EmailHandler(BaseHandler):
    """
    Handler for /oauth/email endpoint.

    This endpoint is reached when OAuth2 callback cannot extract email from
    the provider (e.g., GitHub with private email). It:
    1. GET: Shows email input form (via template_values for app to render)
    2. POST: Processes email input and completes actor creation
    """

    def __init__(
        self,
        webobj: Optional['aw_web_request.AWWebObj'] = None,
        config: Optional['config_class.Config'] = None,
        hooks: Optional['HookRegistry'] = None
    ) -> None:
        if config is None:
            raise RuntimeError("Config is required for OAuth2EmailHandler")
        if webobj is None:
            from .. import aw_web_request
            webobj = aw_web_request.AWWebObj()
        super().__init__(webobj, config, hooks)

    def get(self) -> Dict[str, Any]:
        """
        Handle GET request to /oauth/email - show email input form.

        Expected parameters:
        - session: Session ID from OAuth2 callback

        Sets template_values for app to render email input form.
        """
        session_id = self.request.get("session") or ""

        if not session_id:
            logger.error("No session ID provided to email form")
            return self.error_response(400, "Missing session parameter")

        # Validate session exists and is not expired
        from ..oauth_session import get_oauth2_session_manager

        session_manager = get_oauth2_session_manager(self.config)
        session = session_manager.get_session(session_id)

        if not session:
            logger.error(f"Invalid or expired session: {session_id[:8]}...")
            return self.error_response(400, "Invalid or expired session")

        # Extract provider info for display
        provider = session.get("provider", "OAuth provider")
        provider_display = provider.title()

        # Set template values for app to render email form
        self.response.template_values = {
            "session_id": session_id,
            "action": "/oauth/email",
            "method": "POST",
            "provider": provider,
            "provider_display": provider_display,
            "message": f"Your {provider_display} account does not have a public email. Please enter your email address to continue.",
            "error": None
        }

        return {}  # Template will be rendered by app

    def post(self) -> Dict[str, Any]:
        """
        Handle POST request to /oauth/email - process email input.

        Expected parameters:
        - session: Session ID from OAuth2 callback
        - email: User's email address

        Completes actor creation and redirects to actor's www page.
        """
        # Parse request data
        try:
            body = self.request.body
            if isinstance(body, bytes):
                body_str = body.decode("utf-8", "ignore")
            elif body is None:
                body_str = ""
            else:
                body_str = body

            # Try JSON first
            try:
                params = json.loads(body_str) if body_str else {}
                session_id = params.get("session", "")
                email = params.get("email", "")
            except (json.JSONDecodeError, ValueError):
                # Fall back to form parameters
                session_id = self.request.get("session") or ""
                email = self.request.get("email") or ""

        except Exception as e:
            logger.error(f"Failed to parse email form data: {e}")
            return self.error_response(400, "Invalid form data")

        # Validate inputs
        if not session_id:
            logger.error("No session ID in POST")
            return self.error_response(400, "Missing session parameter")

        if not email or "@" not in email:
            logger.error(f"Invalid email format: {email}")
            # For web forms, set template values with error
            if self.config.ui:
                self.response.set_status(400)
                self.response.template_values = {
                    "session_id": session_id,
                    "action": "/oauth/email",
                    "method": "POST",
                    "provider": "OAuth provider",
                    "error": "Please enter a valid email address"
                }
                return {}
            return self.error_response(400, "Invalid email address")

        # Complete OAuth session with provided email
        from ..oauth_session import get_oauth2_session_manager

        session_manager = get_oauth2_session_manager(self.config)
        actor_instance = session_manager.complete_session(session_id, email)

        if not actor_instance:
            logger.error(f"Failed to complete OAuth session for email {email}")
            # For web forms, set template values with error
            if self.config.ui:
                self.response.set_status(500)
                self.response.template_values = {
                    "session_id": session_id,
                    "action": "/oauth/email",
                    "method": "POST",
                    "provider": "OAuth provider",
                    "error": "Failed to create actor. Session may have expired."
                }
                return {}
            return self.error_response(500, "Failed to create actor")

        # Execute actor_created lifecycle hook if this is a new actor
        if self.hooks:
            try:
                from ..interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(core_actor=actor_instance, service_registry=registry)
                self.hooks.execute_lifecycle_hooks("actor_created", actor_interface)
            except Exception as e:
                logger.error(f"Error in lifecycle hook for actor_created: {e}")

        # Set up session cookie with OAuth token
        if actor_instance.store and actor_instance.store.oauth_token:
            oauth_token = actor_instance.store.oauth_token
            cookie_max_age = 1209600  # 2 weeks

            self.response.set_cookie(
                "oauth_token",
                str(oauth_token),
                max_age=cookie_max_age,
                path="/",
                secure=True
            )

            logger.debug(f"Set oauth_token cookie for actor {actor_instance.id}")

        # Redirect to actor's www page
        redirect_url = f"/{actor_instance.id}/www"
        self.response.set_status(302, "Found")
        self.response.set_redirect(redirect_url)

        logger.info(f"Completed OAuth email flow for {email} -> actor {actor_instance.id}")

        return {
            "status": "success",
            "message": "Actor created successfully",
            "actor_id": actor_instance.id,
            "email": email,
            "redirect_url": redirect_url,
            "redirect_performed": True
        }

    def error_response(self, status_code: int, message: str) -> Dict[str, Any]:
        """Create error response with template rendering for user-friendly errors."""
        self.response.set_status(status_code)

        # For user-facing errors, try to render template
        if status_code in [400, 500] and hasattr(self.response, 'template_values'):
            session_id = self.request.get("session") or ""
            self.response.template_values = {
                "session_id": session_id,
                "action": "/oauth/email",
                "method": "POST",
                "provider": "OAuth provider",
                "error": message,
                "status_code": status_code
            }

        return {
            "error": True,
            "status_code": status_code,
            "message": message
        }
