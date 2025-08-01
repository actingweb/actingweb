"""
Google OAuth2 callback handler for ActingWeb.

This handler processes the OAuth2 callback from Google after user authentication,
exchanges the authorization code for an access token, and sets up the user session.
"""

import logging
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from .base_handler import BaseHandler
from ..google_oauth import GoogleOAuthAuthenticator, parse_state_parameter
from .. import config as config_class


logger = logging.getLogger(__name__)


class GoogleOAuthCallbackHandler(BaseHandler):
    """
    Handles Google OAuth2 callbacks at /oauth/callback.
    
    This endpoint is called by Google after user authentication with:
    - code: Authorization code to exchange for access token
    - state: CSRF protection and optional redirect URL
    - error: Error code if authentication failed
    """
    
    def __init__(self, webobj=None, config: Optional[config_class.Config] = None, hooks=None):
        super().__init__(webobj, config, hooks)
        self.authenticator = GoogleOAuthAuthenticator(config) if config else None
        
    def get(self) -> Dict[str, Any]:
        """
        Handle GET request to /oauth/callback from Google.
        
        Expected parameters:
        - code: Authorization code from Google
        - state: State parameter for CSRF protection
        - error: Error code if authentication failed
        
        Returns:
            Response dict with success/error status
        """
        if not self.authenticator or not self.authenticator.is_enabled():
            logger.error("Google OAuth2 not configured")
            return self.error_response(500, "OAuth2 not configured")
        
        # Check for error parameter
        error = self.request.get("error")
        if error:
            error_description = self.request.get("error_description")
            if not error_description:
                error_description = ""
            logger.warning(f"Google OAuth2 error: {error} - {error_description}")
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
        csrf_token, redirect_url = parse_state_parameter(state)
        
        # Exchange code for access token
        token_data = self.authenticator.exchange_code_for_token(code)
        if not token_data or "access_token" not in token_data:
            logger.error("Failed to exchange authorization code for access token")
            return self.error_response(502, "Token exchange failed")
        
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        
        # Validate token and get user email
        email = self.authenticator.validate_token_and_get_email(access_token)
        if not email:
            logger.error("Failed to validate token or extract email")
            return self.error_response(502, "Token validation failed")
        
        # Look up or create actor by email
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
        # Set a longer cookie expiry (2 weeks like ActingWeb default) since Google tokens are usually valid for 1 hour
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
        """Create error response."""
        self.response.set_status(status_code)
        return {
            "error": True,
            "status_code": status_code,
            "message": message
        }


import time  # Import moved here to avoid circular imports