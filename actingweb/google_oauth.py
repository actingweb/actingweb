"""
Google OAuth2 authentication for ActingWeb.

This module provides Google OAuth2 authentication support for ActingWeb applications,
enabling Bearer token authentication and automatic actor creation based on Google email.
"""

import json
import logging
import time
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlencode, urlparse, parse_qs
import urlfetch

from . import actor as actor_module
from . import config as config_class


logger = logging.getLogger(__name__)


class GoogleOAuthAuthenticator:
    """
    Google OAuth2 authenticator for ActingWeb.
    
    Handles the complete OAuth2 flow:
    1. Redirect to Google for authorization
    2. Handle callback with authorization code
    3. Exchange code for access token
    4. Validate token and extract user email
    5. Look up or create ActingWeb actor by email
    """
    
    def __init__(self, config: config_class.Config):
        self.config = config
        self.google_oauth_config = {
            "client_id": config.oauth.get("client_id", ""),
            "client_secret": config.oauth.get("client_secret", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "userinfo_uri": "https://www.googleapis.com/oauth2/v2/userinfo",
            "scope": "openid email profile",
            "redirect_uri": f"{config.proto}{config.fqdn}/oauth/callback"
        }
        
        # Validate configuration
        if not self.google_oauth_config["client_id"] or not self.google_oauth_config["client_secret"]:
            logger.warning("Google OAuth2 not configured - client_id and client_secret required")
            
    def is_enabled(self) -> bool:
        """Check if Google OAuth2 is properly configured."""
        return bool(self.google_oauth_config["client_id"] and self.google_oauth_config["client_secret"])
    
    def create_authorization_url(self, state: str = "", redirect_after_auth: str = "") -> str:
        """
        Create Google OAuth2 authorization URL.
        
        Args:
            state: State parameter to prevent CSRF attacks
            redirect_after_auth: Where to redirect after successful auth
            
        Returns:
            Google authorization URL
        """
        if not self.is_enabled():
            return ""
            
        # Encode redirect URL in state if provided
        if redirect_after_auth:
            state_data = {
                "csrf": state,
                "redirect": redirect_after_auth
            }
            state = json.dumps(state_data)
            
        params = {
            "client_id": self.google_oauth_config["client_id"],
            "redirect_uri": self.google_oauth_config["redirect_uri"],
            "scope": self.google_oauth_config["scope"],
            "response_type": "code",
            "access_type": "offline",
            "state": state,
            "prompt": "consent"  # Force consent to get refresh token
        }
        
        url = f"{self.google_oauth_config['auth_uri']}?{urlencode(params)}"
        logger.info(f"Created Google OAuth2 authorization URL with state: {state[:50]}...")
        return url
    
    def exchange_code_for_token(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Exchange authorization code for access token.
        
        Args:
            code: Authorization code from Google
            
        Returns:
            Token response from Google or None if failed
        """
        if not self.is_enabled() or not code:
            return None
            
        params = {
            "client_id": self.google_oauth_config["client_id"],
            "client_secret": self.google_oauth_config["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.google_oauth_config["redirect_uri"]
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        
        try:
            response = urlfetch.post(
                url=self.google_oauth_config["token_uri"],
                data=urlencode(params),
                headers=headers
            )
            
            if response.status_code != 200:
                logger.error(f"Google token exchange failed: {response.status_code} {response.content}")
                return None
                
            token_data = json.loads(response.content.decode("utf-8"))
            logger.info("Successfully exchanged authorization code for access token")
            return token_data
            
        except Exception as e:
            logger.error(f"Exception during token exchange: {e}")
            return None
    
    def validate_token_and_get_email(self, access_token: str) -> Optional[str]:
        """
        Validate access token with Google and extract user email.
        
        Args:
            access_token: Google access token
            
        Returns:
            User email or None if validation failed
        """
        if not access_token:
            return None
            
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        
        try:
            response = urlfetch.get(
                url=self.google_oauth_config["userinfo_uri"],
                headers=headers
            )
            
            if response.status_code != 200:
                logger.error(f"Google userinfo request failed: {response.status_code} {response.content}")
                return None
                
            userinfo = json.loads(response.content.decode("utf-8"))
            email = userinfo.get("email")
            
            if not email:
                logger.error("No email found in Google userinfo response")
                return None
                
            logger.info(f"Successfully validated token and extracted email: {email}")
            return email.lower()
            
        except Exception as e:
            logger.error(f"Exception during token validation: {e}")
            return None
    
    def lookup_or_create_actor_by_email(self, email: str) -> Optional[actor_module.Actor]:
        """
        Look up actor by email or create new one if not found.
        
        Args:
            email: User email from Google
            
        Returns:
            ActorInterface instance or None if failed
        """
        if not email:
            return None
            
        try:
            # Use get_from_creator() method to find existing actor by email
            # The email is stored as the creator field when Google OAuth is used
            existing_actor = actor_module.Actor(config=self.config)
            if existing_actor.get_from_creator(email):
                # Actor found and loaded
                logger.info(f"Found existing actor {existing_actor.id} for email {email}")
                return existing_actor
            
            # Create new actor with email as creator
            new_actor = actor_module.Actor(config=self.config)
            
            # Create actor URL - we'll let ActingWeb generate the unique ID
            # The URL is used as a seed for ID generation, so we use a placeholder
            actor_url = f"{self.config.proto}{self.config.fqdn}/oauth-{email}"
            
            # For OAuth users, we don't need a passphrase - ActingWeb will auto-generate one
            if new_actor.create(url=actor_url, creator=email, passphrase=""):
                # Set up initial properties for Google OAuth actor
                if new_actor.store:
                    new_actor.store.email = email
                    new_actor.store.auth_method = "google_oauth2"
                    new_actor.store.created_at = str(int(time.time()))
                    new_actor.store.oauth_provider = "google"
                
                logger.info(f"Created new actor {new_actor.id} for Google user {email}")
                return new_actor
            else:
                logger.error(f"Failed to create actor for email {email}")
                return None
                
        except Exception as e:
            logger.error(f"Exception during actor lookup/creation for {email}: {e}")
            return None
    
    def authenticate_bearer_token(self, bearer_token: str) -> Tuple[Optional[actor_module.Actor], Optional[str]]:
        """
        Authenticate Bearer token and return associated actor.
        
        Args:
            bearer_token: Bearer token from Authorization header
            
        Returns:
            Tuple of (Actor, email) or (None, None) if authentication failed
        """
        if not bearer_token:
            return None, None
            
        # Validate token with Google and get email
        email = self.validate_token_and_get_email(bearer_token)
        if not email:
            return None, None
            
        # Look up or create actor by email
        actor_instance = self.lookup_or_create_actor_by_email(email)
        if not actor_instance:
            return None, None
            
        return actor_instance, email
    
    def create_www_authenticate_header(self) -> str:
        """
        Create WWW-Authenticate header for OAuth2.
        
        Returns:
            WWW-Authenticate header value
        """
        if not self.is_enabled():
            return 'Bearer realm="ActingWeb"'
            
        # Include authorization URL in the header for client convenience
        auth_url = self.create_authorization_url()
        return f'Bearer realm="ActingWeb", authorization_uri="{auth_url}"'


def create_google_authenticator(config: config_class.Config) -> GoogleOAuthAuthenticator:
    """
    Factory function to create Google OAuth2 authenticator.
    
    Args:
        config: ActingWeb configuration
        
    Returns:
        GoogleOAuthAuthenticator instance
    """
    return GoogleOAuthAuthenticator(config)


def extract_bearer_token(auth_header: str) -> Optional[str]:
    """
    Extract Bearer token from Authorization header.
    
    Args:
        auth_header: Authorization header value
        
    Returns:
        Bearer token or None if not found
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:].strip()


def parse_state_parameter(state: str) -> Tuple[str, str]:
    """
    Parse state parameter to extract CSRF token and redirect URL.
    
    Args:
        state: State parameter from OAuth callback
        
    Returns:
        Tuple of (csrf_token, redirect_url)
    """
    if not state:
        return "", ""
        
    try:
        state_data = json.loads(state)
        return state_data.get("csrf", ""), state_data.get("redirect", "")
    except (json.JSONDecodeError, TypeError):
        # Treat as simple CSRF token if not JSON
        return state, ""