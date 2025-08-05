"""
OAuth2 authentication module for ActingWeb using oauthlib.

This module provides a comprehensive OAuth2 implementation using the standard oauthlib library,
supporting both Google OAuth2 and generic OAuth2 providers. It consolidates all OAuth2
functionality into a single, maintainable module.
"""

import json
import logging
import time
import secrets
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urlparse
import urlfetch
from oauthlib.oauth2 import WebApplicationClient  # type: ignore[import-untyped]
from oauthlib.common import generate_token  # type: ignore[import-untyped]

from . import actor as actor_module
from . import config as config_class

logger = logging.getLogger(__name__)


class OAuth2Provider:
    """Base OAuth2 provider configuration."""

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.auth_uri = config.get("auth_uri", "")
        self.token_uri = config.get("token_uri", "")
        self.userinfo_uri = config.get("userinfo_uri", "")
        self.scope = config.get("scope", "")
        self.redirect_uri = config.get("redirect_uri", "")

    def is_enabled(self) -> bool:
        """Check if provider is properly configured."""
        return bool(self.client_id and self.client_secret and self.auth_uri and self.token_uri)


class GoogleOAuth2Provider(OAuth2Provider):
    """Google OAuth2 provider with specific configuration."""

    def __init__(self, config: config_class.Config):
        oauth_config = config.oauth or {}
        google_config = {
            "client_id": oauth_config.get("client_id", ""),
            "client_secret": oauth_config.get("client_secret", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "userinfo_uri": "https://www.googleapis.com/oauth2/v2/userinfo",
            "scope": "openid email profile",
            "redirect_uri": f"{config.proto}{config.fqdn}/oauth/callback",
        }
        super().__init__("google", google_config)


class GitHubOAuth2Provider(OAuth2Provider):
    """GitHub OAuth2 provider with specific configuration."""

    def __init__(self, config: config_class.Config):
        oauth_config = config.oauth or {}
        github_config = {
            "client_id": oauth_config.get("client_id", ""),
            "client_secret": oauth_config.get("client_secret", ""),
            "auth_uri": "https://github.com/login/oauth/authorize",
            "token_uri": "https://github.com/login/oauth/access_token",
            "userinfo_uri": "https://api.github.com/user",
            "scope": "user:email",
            "redirect_uri": f"{config.proto}{config.fqdn}/oauth/callback",
        }
        super().__init__("github", github_config)


class OAuth2Authenticator:
    """
    Comprehensive OAuth2 authenticator using oauthlib.

    Handles the complete OAuth2 flow:
    1. Authorization URL generation
    2. Authorization code exchange for tokens
    3. Token validation and refresh
    4. User information retrieval
    5. Actor lookup/creation based on OAuth2 identity
    """

    def __init__(self, config: config_class.Config, provider: Optional[OAuth2Provider] = None):
        self.config = config
        self.provider = provider or GoogleOAuth2Provider(config)
        self.client = WebApplicationClient(self.provider.client_id) if self.provider.is_enabled() else None

        # Session and token management
        self._sessions: Dict[str, Dict[str, Any]] = {}

        if not self.provider.is_enabled():
            logger.debug(
                f"OAuth2 provider '{self.provider.name}' not configured - client_id and client_secret required"
            )

    def is_enabled(self) -> bool:
        """Check if OAuth2 is properly configured."""
        return self.provider.is_enabled()

    def create_authorization_url(self, state: str = "", redirect_after_auth: str = "", email_hint: str = "") -> str:
        """
        Create OAuth2 authorization URL using oauthlib.

        Args:
            state: State parameter to prevent CSRF attacks
            redirect_after_auth: Where to redirect after successful auth
            email_hint: Email to hint which account to use for authentication

        Returns:
            OAuth2 authorization URL
        """
        if not self.is_enabled() or not self.client:
            return ""

        # Generate state if not provided
        if not state:
            state = generate_token()

        # Encode redirect URL and email hint in state if provided
        # IMPORTANT: Don't overwrite encrypted MCP state (which is base64 encoded)
        if (redirect_after_auth or email_hint) and not self._looks_like_encrypted_state(state):
            state_data = {
                "csrf": state, 
                "redirect": redirect_after_auth,
                "expected_email": email_hint,  # Store original email for validation
            }
            state = json.dumps(state_data)

        # Prepare additional parameters for provider-specific features
        extra_params = {
            "access_type": "offline",  # For Google to get refresh token
            "prompt": "consent",  # Force consent to get refresh token
        }

        # Add email hint for Google OAuth2
        if email_hint and self.provider.name == "google":
            extra_params["login_hint"] = email_hint
            logger.info(f"Adding login_hint for Google OAuth2: {email_hint}")

        # Use oauthlib to generate the authorization URL
        authorization_url = self.client.prepare_request_uri(
            self.provider.auth_uri,
            redirect_uri=self.provider.redirect_uri,
            scope=self.provider.scope.split(),
            state=state,
            **extra_params,
        )

        logger.info(f"Created OAuth2 authorization URL with state: {state[:50]}...")
        return str(authorization_url)

    def _looks_like_encrypted_state(self, state: str) -> bool:
        """
        Check if state parameter looks like an encrypted MCP state.
        
        MCP states are base64-encoded encrypted data and won't be valid JSON.
        Standard ActingWeb states are JSON strings.
        
        Args:
            state: State parameter to check
            
        Returns:
            True if this looks like an encrypted MCP state
        """
        if not state:
            return False
            
        # If it starts with '{' it's likely JSON (standard ActingWeb state)
        if state.strip().startswith('{'):
            return False
            
        # If it contains only base64-safe characters and is reasonably long,
        # it's likely an encrypted MCP state
        import re
        if len(state) > 50 and re.match(r'^[A-Za-z0-9+/_=-]+$', state):
            return True
            
        return False

    def exchange_code_for_token(self, code: str, state: str = "") -> Optional[Dict[str, Any]]:
        """
        Exchange authorization code for access token using oauthlib.

        Args:
            code: Authorization code from OAuth2 provider
            state: State parameter from callback

        Returns:
            Token response from OAuth2 provider or None if failed
        """
        if not self.is_enabled() or not self.client or not code:
            return None

        # Prepare token request using oauthlib
        token_request_body = self.client.prepare_request_body(
            code=code,
            redirect_uri=self.provider.redirect_uri,
            client_id=self.provider.client_id,
            client_secret=self.provider.client_secret,
        )

        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}

        # GitHub requires specific Accept header for JSON response
        if self.provider.name == "github":
            headers["Accept"] = "application/json"
            headers["User-Agent"] = "ActingWeb-OAuth2-Client"

        try:
            response = urlfetch.post(url=self.provider.token_uri, data=token_request_body, headers=headers)

            if response.status_code != 200:
                logger.error(f"OAuth2 token exchange failed: {response.status_code} {response.content}")
                return None

            token_data = json.loads(response.content.decode("utf-8"))

            # Parse token response using oauthlib
            self.client.parse_request_body_response(response.content.decode("utf-8"))

            logger.info("Successfully exchanged authorization code for access token")
            return dict(token_data)

        except Exception as e:
            logger.error(f"Exception during token exchange: {e}")
            return None

    def refresh_access_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """
        Refresh access token using oauthlib.

        Args:
            refresh_token: OAuth2 refresh token

        Returns:
            New token response or None if failed
        """
        if not self.is_enabled() or not self.client or not refresh_token:
            return None

        # Prepare refresh request using oauthlib
        refresh_request_body = self.client.prepare_refresh_body(
            refresh_token=refresh_token, client_id=self.provider.client_id, client_secret=self.provider.client_secret
        )

        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}

        # GitHub doesn't typically support refresh tokens
        if self.provider.name == "github":
            logger.warning("GitHub doesn't support refresh tokens - user will need to re-authenticate")
            return None

        try:
            response = urlfetch.post(url=self.provider.token_uri, data=refresh_request_body, headers=headers)

            if response.status_code != 200:
                logger.error(f"OAuth2 token refresh failed: {response.status_code} {response.content}")
                return None

            token_data = json.loads(response.content.decode("utf-8"))

            # Parse token response using oauthlib
            self.client.parse_request_body_response(response.content.decode("utf-8"))

            logger.info("Successfully refreshed access token")
            return dict(token_data)

        except Exception as e:
            logger.error(f"Exception during token refresh: {e}")
            return None

    def validate_token_and_get_user_info(self, access_token: str) -> Optional[Dict[str, Any]]:
        """
        Validate access token and extract user information.

        Args:
            access_token: OAuth2 access token

        Returns:
            User information dict or None if validation failed
        """
        if not access_token or not self.provider.userinfo_uri:
            return None

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

        # GitHub API requires User-Agent header
        if self.provider.name == "github":
            headers["User-Agent"] = "ActingWeb-OAuth2-Client"

        try:
            response = urlfetch.get(url=self.provider.userinfo_uri, headers=headers)

            if response.status_code != 200:
                logger.error(f"OAuth2 userinfo request failed: {response.status_code} {response.content}")
                return None

            userinfo = json.loads(response.content.decode("utf-8"))
            logger.info(f"Successfully validated token and extracted user info")
            return dict(userinfo)

        except Exception as e:
            logger.error(f"Exception during token validation: {e}")
            return None

    def get_email_from_user_info(self, user_info: Dict[str, Any], access_token: Optional[str] = None) -> Optional[str]:
        """Extract email from user info based on provider."""
        if not user_info:
            return None

        # For Google and most providers
        email = user_info.get("email")
        if email:
            return str(email).lower()

        # For GitHub, if email is not public, we may need to make additional API call
        if self.provider.name == "github":
            # Try to get the primary email from GitHub's emails API if we have access token
            if access_token and not email:
                email = self._get_github_primary_email(access_token)
                if email:
                    return email.lower()

            # GitHub might not have email if it's private
            # Use login (username) as fallback identifier
            login = user_info.get("login")
            if login:
                # For GitHub, we'll use login@github.local as the email identifier
                # This ensures each GitHub user gets a unique identifier
                return f"{login}@github.local"

        # Fallback for other providers
        return str(user_info.get("preferred_username", "")).lower()

    def _get_github_primary_email(self, access_token: str) -> Optional[str]:
        """Get primary email from GitHub's emails API."""
        if not access_token:
            return None

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "ActingWeb-OAuth2-Client",
        }

        try:
            response = urlfetch.get(url="https://api.github.com/user/emails", headers=headers)

            if response.status_code != 200:
                logger.warning(f"GitHub emails API request failed: {response.status_code}")
                return None

            emails = json.loads(response.content.decode("utf-8"))

            # Find the primary email
            for email_info in emails:
                if email_info.get("primary", False):
                    email = email_info.get("email")
                    return str(email) if email else None

            # If no primary email found, use the first verified email
            for email_info in emails:
                if email_info.get("verified", False):
                    email = email_info.get("email")
                    return str(email) if email else None

            return None

        except Exception as e:
            logger.warning(f"Failed to get GitHub primary email: {e}")
            return None

    def lookup_or_create_actor_by_email(self, email: str) -> Optional[actor_module.Actor]:
        """
        Look up actor by email or create new one if not found.

        Args:
            email: User email from OAuth2 provider

        Returns:
            Actor instance or None if failed
        """
        if not email:
            return None

        try:
            # Use get_from_creator() method to find existing actor by email
            existing_actor = actor_module.Actor(config=self.config)
            logger.debug(f"Looking up existing actor for email: {email}")
            if existing_actor.get_from_creator(email):
                logger.info(f"Found existing actor {existing_actor.id} for email {email}")
                return existing_actor
            else:
                logger.debug(f"No existing actor found for email {email}, will create new one")

            # Create new actor with email as creator
            new_actor = actor_module.Actor(config=self.config)

            # Create actor URL - let ActingWeb generate the unique ID
            actor_url = f"{self.config.proto}{self.config.fqdn}/oauth-{email}"

            # For OAuth users, we don't need a passphrase - ActingWeb will auto-generate one
            if new_actor.create(url=actor_url, creator=email, passphrase=""):
                # Set up initial properties for OAuth actor
                if new_actor.store:
                    new_actor.store.email = email
                    new_actor.store.auth_method = f"{self.provider.name}_oauth2"
                    new_actor.store.created_at = str(int(time.time()))
                    new_actor.store.oauth_provider = self.provider.name

                logger.info(f"Created new actor {new_actor.id} for {self.provider.name} user {email}")
                return new_actor
            else:
                logger.error(f"Failed to create actor for email {email}")
                return None

        except Exception as e:
            logger.error(f"Exception during actor lookup/creation for {email}: {e}")
            return None

    def validate_email_from_state(self, state: str, authenticated_email: str) -> bool:
        """
        Validate that the authenticated email matches the expected email from OAuth2 state.

        Args:
            state: OAuth2 state parameter containing expected email
            authenticated_email: Email obtained from OAuth2 authentication

        Returns:
            True if emails match or no expected email in state, False otherwise
        """
        if not state or not authenticated_email:
            return False

        try:
            # Try to parse state as JSON
            state_data = json.loads(state)
            expected_email = state_data.get("expected_email")

            if not expected_email:
                # No expected email in state - allow (backward compatibility)
                return True

            # Normalize both emails for comparison (lowercase, strip whitespace)
            expected_email_normalized = expected_email.lower().strip()
            authenticated_email_normalized = authenticated_email.lower().strip()

            if expected_email_normalized == authenticated_email_normalized:
                logger.info(f"Email validation successful: {authenticated_email}")
                return True
            else:
                logger.warning(
                    f"Email mismatch: expected {expected_email_normalized}, got {authenticated_email_normalized}"
                )
                return False

        except (json.JSONDecodeError, TypeError):
            # State is not JSON - treat as simple string (backward compatibility)
            logger.debug("State is not JSON, skipping email validation")
            return True
        except Exception as e:
            logger.error(f"Error validating email from state: {e}")
            return False

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

        # Validate token and get user info
        user_info = self.validate_token_and_get_user_info(bearer_token)
        if not user_info:
            return None, None

        # Extract email from user info
        email = self.get_email_from_user_info(user_info, bearer_token)
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

    def store_session_data(self, session_id: str, data: Dict[str, Any]) -> None:
        """Store session data for OAuth2 flow."""
        self._sessions[session_id] = data

    def get_session_data(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data for OAuth2 flow."""
        return self._sessions.get(session_id)

    def clear_session_data(self, session_id: str) -> None:
        """Clear session data after OAuth2 flow completion."""
        self._sessions.pop(session_id, None)


# Factory functions for backward compatibility and convenience


def create_oauth2_authenticator(config: config_class.Config, provider_name: str = "") -> OAuth2Authenticator:
    """
    Factory function to create OAuth2 authenticator for the configured provider.

    Args:
        config: ActingWeb configuration
        provider_name: Provider name (auto-detected from config if not specified)

    Returns:
        OAuth2Authenticator configured for the specified provider
    """
    # Auto-detect provider from config if not specified
    if not provider_name:
        provider_name = getattr(config, "oauth2_provider", "google")

    # Built-in provider support
    if provider_name == "google":
        return OAuth2Authenticator(config, GoogleOAuth2Provider(config))
    elif provider_name == "github":
        return OAuth2Authenticator(config, GitHubOAuth2Provider(config))
    else:
        # Default to Google if provider not recognized
        return OAuth2Authenticator(config, GoogleOAuth2Provider(config))




def create_google_authenticator(config: config_class.Config) -> OAuth2Authenticator:
    """
    Factory function to create Google OAuth2 authenticator.

    Args:
        config: ActingWeb configuration

    Returns:
        OAuth2Authenticator configured for Google
    """
    return OAuth2Authenticator(config, GoogleOAuth2Provider(config))


def create_github_authenticator(config: config_class.Config) -> OAuth2Authenticator:
    """
    Factory function to create GitHub OAuth2 authenticator.

    Args:
        config: ActingWeb configuration

    Returns:
        OAuth2Authenticator configured for GitHub
    """
    return OAuth2Authenticator(config, GitHubOAuth2Provider(config))


def create_generic_authenticator(config: config_class.Config, provider_config: Dict[str, Any]) -> OAuth2Authenticator:
    """
    Factory function to create generic OAuth2 authenticator.

    Args:
        config: ActingWeb configuration
        provider_config: OAuth2 provider configuration dict

    Returns:
        OAuth2Authenticator configured for generic provider
    """
    provider = OAuth2Provider("generic", provider_config)
    return OAuth2Authenticator(config, provider)


# Utility functions


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


def parse_state_parameter(state: str) -> Tuple[str, str, str]:
    """
    Parse state parameter to extract CSRF token, redirect URL, and actor ID.

    Args:
        state: State parameter from OAuth callback

    Returns:
        Tuple of (csrf_token, redirect_url, actor_id)
    """
    if not state:
        return "", "", ""

    try:
        state_data = json.loads(state)
        return (state_data.get("csrf", ""), state_data.get("redirect", ""), state_data.get("actor_id", ""))
    except (json.JSONDecodeError, TypeError):
        # If not JSON, it might be just an actor ID (for legacy compatibility)
        # Check if it looks like an actor ID (32 hex chars)
        if len(state) == 32 and all(c in "0123456789abcdef" for c in state.lower()):
            return "", "", state
        # Otherwise treat as simple CSRF token
        return state, "", ""


def validate_redirect_url(redirect_url: str, allowed_domains: list[str]) -> bool:
    """
    Validate that redirect URL is safe (same domain or allowed).

    Args:
        redirect_url: URL to validate
        allowed_domains: List of allowed domains

    Returns:
        True if URL is safe to redirect to
    """
    if not redirect_url:
        return False

    try:
        parsed = urlparse(redirect_url)

        # Allow relative URLs (no scheme/netloc)
        if not parsed.scheme and not parsed.netloc:
            return True

        # Allow same domain and allowed domains
        if parsed.netloc in allowed_domains:
            return True

        return False

    except Exception:
        return False
