"""
Email verification handler for ActingWeb.

Handles email verification for OAuth2 actors where the email address
could not be verified by the OAuth provider.

Supports both HTML template responses and JSON API responses based on
the Accept header (application/json for API clients).
"""

import json
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, Optional

from .base_handler import BaseHandler

if TYPE_CHECKING:
    from .. import aw_web_request
    from .. import config as config_class
    from ..interface.hooks import HookRegistry

logger = logging.getLogger(__name__)


class EmailVerificationHandler(BaseHandler):
    """
    Handler for /<actor_id>/www/verify_email endpoint.

    This endpoint verifies email addresses for actors created via OAuth2
    when the OAuth provider could not verify the email.

    Supports JSON API responses when Accept: application/json header is present.
    """

    def __init__(
        self,
        webobj: Optional["aw_web_request.AWWebObj"] = None,
        config: Optional["config_class.Config"] = None,
        hooks: Optional["HookRegistry"] = None,
    ) -> None:
        if webobj is None:
            raise RuntimeError("WebObj is required for EmailVerificationHandler")
        if config is None:
            raise RuntimeError("Config is required for EmailVerificationHandler")
        super().__init__(webobj, config, hooks)

    def _wants_json(self) -> bool:
        """Check if client prefers JSON response based on Accept header."""
        if self.request.headers is None:
            return False
        accept = self.request.headers.get("Accept", "")
        return "application/json" in accept

    def _json_response(
        self, data: dict[str, Any], status_code: int = 200
    ) -> dict[str, Any]:
        """Return JSON response for API clients."""
        if self.response:
            self.response.write(json.dumps(data))
            self.response.headers["Content-Type"] = "application/json"
            self.response.set_status(status_code)
        return data

    def get(self) -> dict[str, Any]:
        """
        Handle GET request to verify email with token.

        Expected parameters:
        - token: Verification token sent via email

        URL: /<actor_id>/www/verify_email?token=abc123...
        """
        from .. import actor as actor_module

        # Get actor_id from URL path
        # URL format: /<actor_id>/www/verify_email
        actor_id: str | None = None
        if self.request.url:
            parts = self.request.url.split("/")
            if len(parts) >= 2:
                actor_id = parts[1]  # First non-empty part after leading /

        if not actor_id:
            logger.error("No actor_id in verification request")
            return self.error_response(400, "Invalid verification link")

        # Get verification token from query parameters
        token = self.request.get("token") or ""
        if not token:
            logger.error("No verification token provided")
            return self.error_response(400, "Missing verification token")

        # Load actor
        actor = actor_module.Actor(actor_id=actor_id, config=self.config)
        if not actor.id:
            logger.error(f"Actor {actor_id} not found")
            return self.error_response(404, "Actor not found")

        # Check if already verified
        if actor.store and actor.store.email_verified == "true":
            logger.info(f"Email already verified for actor {actor_id}")
            if self._wants_json():
                return self._json_response(
                    {
                        "success": True,
                        "status": "already_verified",
                        "message": "Your email address has already been verified.",
                        "email": actor.store.email or actor.creator,
                    }
                )
            # Show success page anyway
            self.response.template_values = {
                "status": "already_verified",
                "message": "Your email address has already been verified.",
                "actor_id": actor_id,
                "email": actor.store.email or actor.creator,
            }
            return {}

        # Get stored verification token
        if not actor.store:
            logger.error(f"No store available for actor {actor_id}")
            return self.error_response(500, "Internal error")

        stored_token = actor.store.email_verification_token or ""
        token_created_at = actor.store.email_verification_created_at or "0"

        # Validate token
        if not stored_token:
            logger.error(f"No verification token stored for actor {actor_id}")
            return self.error_response(400, "No verification pending")

        if stored_token != token:
            logger.warning(f"Invalid verification token for actor {actor_id}")
            return self.error_response(403, "Invalid verification token")

        # Check token expiry (24 hours)
        from ..constants import EMAIL_VERIFICATION_TOKEN_EXPIRY

        if int(time.time()) - int(token_created_at) > EMAIL_VERIFICATION_TOKEN_EXPIRY:
            logger.warning(f"Verification token expired for actor {actor_id}")
            return self.error_response(410, "Verification link has expired")

        # Mark email as verified
        actor.store.email_verified = "true"
        actor.store.email_verification_token = None  # Clear token
        actor.store.email_verification_created_at = None
        actor.store.email_verified_at = str(int(time.time()))

        logger.info(
            f"Email verified successfully for actor {actor_id}: {actor.creator}"
        )

        # Execute verification success lifecycle hook
        if self.hooks:
            try:
                from ..interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor, service_registry=registry
                )

                self.hooks.execute_lifecycle_hooks(
                    "email_verified", actor_interface, email=actor.creator
                )
            except Exception as e:
                logger.error(f"Error in email_verified lifecycle hook: {e}")

        # Return response
        if self._wants_json():
            return self._json_response(
                {
                    "success": True,
                    "message": "Your email address has been verified successfully!",
                    "email": actor.creator,
                    "redirect_url": f"/{actor_id}/www",
                }
            )

        # Show success page
        self.response.template_values = {
            "status": "success",
            "message": "Your email address has been verified successfully!",
            "actor_id": actor_id,
            "email": actor.creator,
            "redirect_url": f"/{actor_id}/www",
        }

        return {}

    def post(self) -> dict[str, Any]:
        """
        Handle POST request to resend verification email.

        Expected parameters:
        - email: Email address to verify (optional, defaults to actor.creator)

        URL: /<actor_id>/www/verify_email
        """
        from .. import actor as actor_module

        # Get actor_id from URL path
        # URL format: /<actor_id>/www/verify_email
        actor_id: str | None = None
        if self.request.url:
            parts = self.request.url.split("/")
            if len(parts) >= 2:
                actor_id = parts[1]  # First non-empty part after leading /

        if not actor_id:
            return self.error_response(400, "Invalid request")

        # Load actor
        actor = actor_module.Actor(actor_id=actor_id, config=self.config)
        if not actor.id:
            return self.error_response(404, "Actor not found")

        # Check if already verified
        if actor.store and actor.store.email_verified == "true":
            return self.error_response(400, "Email already verified")

        # Generate new verification token
        from ..constants import EMAIL_VERIFICATION_TOKEN_LENGTH

        token = secrets.token_urlsafe(EMAIL_VERIFICATION_TOKEN_LENGTH)

        # Store token
        if actor.store:
            actor.store.email_verification_token = token
            actor.store.email_verification_created_at = str(int(time.time()))

        # Execute hook to send verification email
        if self.hooks:
            try:
                from ..interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(
                    core_actor=actor, service_registry=registry
                )

                verification_url = f"{self.config.proto}{self.config.fqdn}/{actor_id}/www/verify_email?token={token}"

                self.hooks.execute_lifecycle_hooks(
                    "email_verification_required",
                    actor_interface,
                    email=actor.creator,
                    verification_url=verification_url,
                    token=token,
                )
            except Exception as e:
                logger.error(f"Error in email_verification_required hook: {e}")
                return self.error_response(500, "Failed to send verification email")

        logger.info(f"Resent verification email for actor {actor_id}")

        if self._wants_json():
            return self._json_response(
                {
                    "success": True,
                    "message": "Verification email sent. Please check your inbox.",
                }
            )

        return {
            "status": "success",
            "message": "Verification email sent. Please check your inbox.",
        }

    def error_response(self, status_code: int, message: str) -> dict[str, Any]:
        """Create error response with template rendering or JSON."""
        # For JSON clients, return JSON error
        if self._wants_json():
            return self._json_response(
                {
                    "success": False,
                    "error": message.lower().replace(" ", "_"),
                    "message": message,
                },
                status_code,
            )

        self.response.set_status(status_code)

        # For user-facing errors, render template
        if hasattr(self.response, "template_values"):
            self.response.template_values = {
                "status": "error",
                "error": message,
                "status_code": status_code,
            }

        return {"error": True, "status_code": status_code, "message": message}
