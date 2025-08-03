"""
OAuth2 callback handler for ActingWeb.

This handler processes OAuth2 callbacks from various providers after user authentication,
exchanges the authorization code for an access token, and sets up the user session.
Uses the consolidated oauth2 module for provider-agnostic OAuth2 handling.
"""

import logging
import time
from typing import Dict, Any, Optional, TYPE_CHECKING
from urllib.parse import urlparse

from .base_handler import BaseHandler

if TYPE_CHECKING:
    from ..interface.hooks import HookRegistry
    from .. import aw_web_request
from ..oauth2 import create_oauth2_authenticator, parse_state_parameter
from .. import config as config_class

logger = logging.getLogger(__name__)


class OAuth2CallbackHandler(BaseHandler):
    """
    Handles OAuth2 callbacks at /oauth/callback.
    
    This endpoint is called by OAuth2 providers after user authentication with:
    - code: Authorization code to exchange for access token
    - state: CSRF protection and optional redirect URL
    - error: Error code if authentication failed
    """
    
    def __init__(self, webobj: Optional['aw_web_request.AWWebObj'] = None, config: Optional[config_class.Config] = None, hooks: Optional['HookRegistry'] = None) -> None:
        if config is None:
            raise RuntimeError("Config is required for OAuth2CallbackHandler")
        if webobj is None:
            from .. import aw_web_request
            webobj = aw_web_request.AWWebObj()
        super().__init__(webobj, config, hooks)
        # Use generic OAuth2 authenticator (configurable provider)
        self.authenticator = create_oauth2_authenticator(config) if config else None
        
    def get(self) -> Dict[str, Any]:
        """
        Handle GET request to /oauth/callback from OAuth2 provider.
        
        Expected parameters:
        - code: Authorization code from OAuth2 provider
        - state: State parameter for CSRF protection
        - error: Error code if authentication failed
        
        Returns:
            Response dict with success/error status
        """
        if not self.authenticator or not self.authenticator.is_enabled():
            logger.error("OAuth2 not configured")
            return self.error_response(500, "OAuth2 not configured")
        
        # Check for error parameter
        error = self.request.get("error")
        if error:
            error_description = self.request.get("error_description")
            if not error_description:
                error_description = ""
            logger.warning(f"OAuth2 error: {error} - {error_description}")
            return self.error_response(400, f"Authentication failed: {error}")
        
        # Get authorization code
        code = self.request.get("code")
        if not code:
            logger.error("No authorization code in OAuth2 callback")
            return self.error_response(400, "Missing authorization code")
        
        # Get and parse state parameter
        state = self.request.get("state")
        if not state:
            state = ""
        _, redirect_url, actor_id = parse_state_parameter(state)
        logger.debug(f"Parsed state - redirect_url: '{redirect_url}', actor_id: '{actor_id}'")
        
        # Exchange code for access token
        token_data = self.authenticator.exchange_code_for_token(code, state)
        if not token_data or "access_token" not in token_data:
            logger.error("Failed to exchange authorization code for access token")
            return self.error_response(502, "Token exchange failed")
        
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        
        # Validate token and get user info
        user_info = self.authenticator.validate_token_and_get_user_info(access_token)
        if not user_info:
            logger.error("Failed to validate token or extract user info")
            return self.error_response(502, "Token validation failed")
        
        # Extract email from user info
        email = self.authenticator.get_email_from_user_info(user_info, access_token)
        if not email:
            logger.error("Failed to extract email from user info")
            return self.error_response(502, "Email extraction failed")
        
        # Validate that the authenticated email matches the expected email from the form
        if not self.authenticator.validate_email_from_state(state, email):
            logger.error(f"Email validation failed - authenticated as {email} but expected different email from form")
            return self.error_response(403, "Authentication email does not match the email provided in the form")
        
        # Use existing actor from state if provided, otherwise lookup/create by email
        actor_instance = None
        if actor_id:
            # Try to use the existing actor from the state parameter
            from .. import actor as actor_module
            try:
                actor_instance = actor_module.Actor(config=self.config)
                if not actor_instance.get(actor_id):
                    logger.warning(f"Actor {actor_id} from state not found, will lookup/create by email")
                    actor_instance = None
                else:
                    logger.info(f"Using existing actor {actor_id} from state parameter")
            except Exception as e:
                logger.warning(f"Failed to load actor {actor_id} from state: {e}, will lookup/create by email")
                actor_instance = None
        
        # If no actor from state or loading failed, lookup/create by email
        if not actor_instance:
            actor_instance = self.authenticator.lookup_or_create_actor_by_email(email)
            if not actor_instance:
                logger.error(f"Failed to lookup or create actor for email {email}")
                return self.error_response(502, "Actor creation failed")
        
        # Store OAuth tokens in actor properties
        # The auth system expects oauth_token (not oauth_access_token)
        if actor_instance.store:
            actor_instance.store.oauth_token = access_token  # This is what auth.py looks for
            actor_instance.store.oauth_token_expiry = str(int(time.time()) + expires_in) if expires_in else None
            if refresh_token:
                actor_instance.store.oauth_refresh_token = refresh_token
            actor_instance.store.oauth_token_timestamp = str(int(time.time()))
        
        # Execute OAuth success lifecycle hook
        oauth_valid = True
        if self.hooks:
            try:
                result = self.hooks.execute_lifecycle_hooks(
                    "oauth_success", 
                    actor_instance, 
                    email=email,
                    access_token=access_token,
                    token_data=token_data
                )
                oauth_valid = bool(result) if result is not None else True
            except Exception as e:
                logger.error(f"Error executing oauth_success hook: {e}")
                oauth_valid = False
        
        if not oauth_valid:
            logger.warning(f"OAuth success hook rejected authentication for {email}")
            return self.error_response(403, "Authentication rejected")
        
        # Set up successful response
        response_data = {
            "status": "success",
            "message": "Authentication successful",
            "actor_id": actor_instance.id,
            "email": email,
            "access_token": access_token,
            "expires_in": expires_in
        }
        
        # For interactive web authentication, redirect to the actor's www page
        # For API clients, they would use the Bearer token directly
        
        # For interactive authentication, always redirect to actor's www page
        # This avoids authentication loops with the original URL
        final_redirect = f"/{actor_instance.id}/www"
        logger.info(f"Redirecting to actor www page: {final_redirect}")
        
        # Log the original URL for reference but don't use it
        if redirect_url:
            logger.info(f"Original URL was: {redirect_url} (redirecting to www page instead)")
        
        # Set session cookie so user stays authenticated after redirect
        # The cookie should match the token stored in the actor (oauth_token)
        stored_token = actor_instance.store.oauth_token if actor_instance.store else access_token
        # Set a longer cookie expiry (2 weeks like ActingWeb default) since OAuth tokens are usually valid for 1 hour
        # but we want the session to persist longer than that
        cookie_max_age = 1209600  # 2 weeks, matching ActingWeb's default
        
        self.response.set_cookie(
            "oauth_token", 
            str(stored_token), 
            max_age=cookie_max_age,
            path="/", 
            secure=True
        )
        
        logger.info(f"Set oauth_token cookie with token length {len(str(stored_token))} and max_age {cookie_max_age}")
        
        # Perform the redirect for interactive authentication
        self.response.set_status(302, "Found")
        self.response.set_redirect(final_redirect)
        
        # Also include the information in the response data for completeness
        response_data["redirect_url"] = final_redirect
        response_data["redirect_performed"] = True
        
        # Execute OAuth completed lifecycle hook
        if self.hooks:
            try:
                self.hooks.execute_lifecycle_hooks(
                    "oauth_completed",
                    actor_instance,
                    email=email,
                    access_token=access_token,
                    redirect_url=response_data["redirect_url"]
                )
            except Exception as e:
                logger.error(f"Error executing oauth_completed hook: {e}")
        
        logger.info(f"OAuth2 authentication completed successfully for {email} -> {actor_instance.id}")
        return response_data
    
    
    def _is_safe_redirect(self, url: str) -> bool:
        """
        Check if redirect URL is safe (same domain).
        
        Args:
            url: URL to validate
            
        Returns:
            True if URL is safe to redirect to
        """
        if not url:
            return False
        
        try:
            # Parse the URL
            parsed = urlparse(url)
            
            # Allow relative URLs (no scheme/netloc)
            if not parsed.scheme and not parsed.netloc:
                return True
            
            # Allow same domain redirects
            if parsed.netloc == self.config.fqdn:
                return True
            
            # Reject external redirects
            return False
            
        except Exception:
            return False
    
    def error_response(self, status_code: int, message: str) -> Dict[str, Any]:
        """Create error response with template rendering for user-friendly errors."""
        self.response.set_status(status_code)
        
        # For user-facing errors, try to render template
        if status_code in [403, 400] and hasattr(self.response, 'template_values'):
            self.response.template_values = {
                "error": message,
                "status_code": status_code
            }
        
        return {
            "error": True,
            "status_code": status_code,
            "message": message
        }