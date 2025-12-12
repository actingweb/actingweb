"""
OAuth2 authentication module for ActingWeb using oauthlib.

This module provides a comprehensive OAuth2 implementation using the standard oauthlib library,
supporting both Google OAuth2 and generic OAuth2 providers. It consolidates all OAuth2
functionality into a single, maintainable module.
"""

import hashlib
import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests  # type: ignore[import-untyped]
from oauthlib.common import generate_token  # type: ignore[import-untyped]
from oauthlib.oauth2 import WebApplicationClient  # type: ignore[import-untyped]

from . import actor as actor_module
from . import config as config_class
from .constants import ESTABLISHED_VIA_OAUTH2_INTERACTIVE
from .interface.actor_interface import ActorInterface

logger = logging.getLogger(__name__)

# Simple cache for invalid tokens to avoid repeat network requests
_invalid_token_cache: dict[str, float] = {}
_INVALID_TOKEN_CACHE_TTL = 300  # 5 minutes


class OAuth2Provider:
    """Base OAuth2 provider configuration."""

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.auth_uri = config.get("auth_uri", "")
        self.token_uri = config.get("token_uri", "")
        self.userinfo_uri = config.get("userinfo_uri", "")
        self.revocation_uri = config.get("revocation_uri", "")
        self.scope = config.get("scope", "")
        self.redirect_uri = config.get("redirect_uri", "")

    def is_enabled(self) -> bool:
        """Check if provider is properly configured."""
        return bool(
            self.client_id and self.client_secret and self.auth_uri and self.token_uri
        )


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
            "revocation_uri": "https://oauth2.googleapis.com/revoke",
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

    def __init__(
        self, config: config_class.Config, provider: OAuth2Provider | None = None
    ):
        self.config = config
        self.provider = provider or GoogleOAuth2Provider(config)
        self.client = (
            WebApplicationClient(self.provider.client_id)
            if self.provider.is_enabled()
            else None
        )

        # Session and token management
        self._sessions: dict[str, dict[str, Any]] = {}

        if not self.provider.is_enabled():
            logger.warning(
                f"OAuth2 provider '{self.provider.name}' not configured - client_id and client_secret required"
            )

    def is_enabled(self) -> bool:
        """Check if OAuth2 is properly configured."""
        return self.provider.is_enabled()

    def create_authorization_url(
        self,
        state: str = "",
        redirect_after_auth: str = "",
        email_hint: str = "",
        trust_type: str = "",
        user_agent: str = "",
        code_challenge: str = "",
        code_challenge_method: str = "",
    ) -> str:
        """
        Create OAuth2 authorization URL using oauthlib with trust type selection.

        Args:
            state: State parameter to prevent CSRF attacks
            redirect_after_auth: Where to redirect after successful auth
            email_hint: Email to hint which account to use for authentication
            trust_type: Trust relationship type to establish (e.g., 'mcp_client', 'web_user')
            user_agent: User-Agent header for client identification and MCP coordination
            code_challenge: PKCE code challenge for SPA OAuth flows
            code_challenge_method: PKCE challenge method (typically "S256")

        Returns:
            OAuth2 authorization URL
        """
        if not self.is_enabled() or not self.client:
            return ""

        # Generate state if not provided
        if not state:
            state = generate_token()

        # Encode redirect URL, email hint, trust type, and user agent in state if provided
        # IMPORTANT: Don't overwrite encrypted MCP state (which is base64 encoded)
        if (
            redirect_after_auth or email_hint or trust_type or user_agent
        ) and not self._looks_like_encrypted_state(state):
            state_data = {
                "csrf": state,
                "redirect": redirect_after_auth,
                "expected_email": email_hint,  # Store original email for validation
                "trust_type": trust_type,  # Store trust type for automatic relationship creation
                "user_agent": user_agent[:100]
                if user_agent
                else "",  # Truncate user agent to prevent large state
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

        # Add PKCE parameters if provided (for SPA OAuth flows)
        if code_challenge and code_challenge_method:
            extra_params["code_challenge"] = code_challenge
            extra_params["code_challenge_method"] = code_challenge_method

        # Use oauthlib to generate the authorization URL
        authorization_url = self.client.prepare_request_uri(
            self.provider.auth_uri,
            redirect_uri=self.provider.redirect_uri,
            scope=self.provider.scope.split(),
            state=state,
            **extra_params,
        )

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
        if state.strip().startswith("{"):
            return False

        # If it contains only base64-safe characters and is reasonably long,
        # it's likely an encrypted MCP state

        if len(state) > 50 and re.match(r"^[A-Za-z0-9+/_=-]+$", state):
            return True

        return False

    def exchange_code_for_token(
        self, code: str, state: str = "", code_verifier: str | None = None
    ) -> dict[str, Any] | None:  # pylint: disable=unused-argument
        """
        Exchange authorization code for access token using oauthlib.

        Args:
            code: Authorization code from OAuth2 provider
            state: State parameter from callback
            code_verifier: PKCE code verifier (required if PKCE was used in authorization)

        Returns:
            Token response from OAuth2 provider or None if failed
        """
        if not self.is_enabled() or not self.client or not code:
            return None

        # Prepare token request using oauthlib
        # Include code_verifier if PKCE was used
        prepare_kwargs: dict[str, Any] = {
            "code": code,
            "redirect_uri": self.provider.redirect_uri,
            "client_id": self.provider.client_id,
            "client_secret": self.provider.client_secret,
        }
        if code_verifier:
            prepare_kwargs["code_verifier"] = code_verifier

        token_request_body = self.client.prepare_request_body(**prepare_kwargs)

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        # GitHub requires specific Accept header for JSON response
        if self.provider.name == "github":
            headers["Accept"] = "application/json"
            headers["User-Agent"] = "ActingWeb-OAuth2-Client"

        try:
            # Use requests library with better timeout and connection handling
            response = requests.post(
                url=self.provider.token_uri,
                data=token_request_body,
                headers=headers,
                timeout=(5, 15),  # (connect timeout, read timeout)
            )

            if response.status_code != 200:
                logger.error(
                    f"OAuth2 token exchange failed: {response.status_code} {response.text}"
                )
                return None

            token_data = response.json()

            # Parse token response using oauthlib
            self.client.parse_request_body_response(response.text)

            return dict(token_data)

        except Exception as e:
            logger.error(f"Exception during token exchange: {e}")
            return None

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any] | None:
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
            refresh_token=refresh_token,
            client_id=self.provider.client_id,
            client_secret=self.provider.client_secret,
        )

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        # GitHub doesn't typically support refresh tokens
        if self.provider.name == "github":
            logger.warning(
                "GitHub doesn't support refresh tokens - user will need to re-authenticate"
            )
            return None

        try:
            # Use requests library with better timeout and connection handling
            response = requests.post(
                url=self.provider.token_uri,
                data=refresh_request_body,
                headers=headers,
                timeout=(5, 15),  # (connect timeout, read timeout)
            )

            if response.status_code != 200:
                logger.error(
                    f"OAuth2 token refresh failed: {response.status_code} {response.text}"
                )
                return None

            token_data = response.json()

            # Parse token response using oauthlib
            self.client.parse_request_body_response(response.text)

            return dict(token_data)

        except Exception as e:
            logger.error(f"Exception during token refresh: {e}")
            return None

    def validate_token_and_get_user_info(
        self, access_token: str
    ) -> dict[str, Any] | None:
        """
        Validate access token and extract user information.

        Args:
            access_token: OAuth2 access token

        Returns:
            User information dict or None if validation failed
        """
        if not access_token or not self.provider.userinfo_uri:
            return None

        # Check cache for previously validated invalid tokens
        current_time = time.time()
        token_hash = hashlib.sha256(access_token.encode()).hexdigest()[:16]
        if token_hash in _invalid_token_cache:
            cache_time = _invalid_token_cache[token_hash]
            if current_time - cache_time < _INVALID_TOKEN_CACHE_TTL:
                logger.debug(
                    "Token found in invalid token cache - skipping network request"
                )
                return None

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        # GitHub API requires User-Agent header
        if self.provider.name == "github":
            headers["User-Agent"] = "ActingWeb-OAuth2-Client"

        try:
            # Use requests library with better timeout handling
            response = requests.get(
                url=self.provider.userinfo_uri,
                headers=headers,
                timeout=(5, 10),  # (connect timeout, read timeout)
            )

            if response.status_code != 200:
                logger.debug(
                    f"OAuth2 userinfo request failed: {response.status_code} {response.text}"
                )
                # Cache this invalid token to avoid future network requests
                _invalid_token_cache[token_hash] = current_time
                return None

            userinfo = response.json()
            return dict(userinfo)

        except Exception as e:
            logger.error(f"Exception during token validation: {e}")
            # Cache this invalid token to avoid future network requests
            _invalid_token_cache[token_hash] = current_time
            return None

    async def validate_token_and_get_user_info_async(
        self, access_token: str
    ) -> dict[str, Any] | None:
        """
        Async version: Validate access token and extract user information.

        Uses httpx for non-blocking HTTP requests, suitable for use within
        async handlers where blocking the event loop would cause issues.

        Args:
            access_token: OAuth2 access token

        Returns:
            User information dict or None if validation failed
        """
        if not access_token or not self.provider.userinfo_uri:
            return None

        # Check cache for previously validated invalid tokens
        current_time = time.time()
        token_hash = hashlib.sha256(access_token.encode()).hexdigest()[:16]
        if token_hash in _invalid_token_cache:
            cache_time = _invalid_token_cache[token_hash]
            if current_time - cache_time < _INVALID_TOKEN_CACHE_TTL:
                logger.debug(
                    "Token found in invalid token cache - skipping network request"
                )
                return None

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        # GitHub API requires User-Agent header
        if self.provider.name == "github":
            headers["User-Agent"] = "ActingWeb-OAuth2-Client"

        try:
            import httpx

            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                response = await client.get(
                    url=self.provider.userinfo_uri,
                    headers=headers,
                )

            if response.status_code != 200:
                logger.debug(
                    f"OAuth2 userinfo request failed (async): {response.status_code} {response.text}"
                )
                # Cache this invalid token to avoid future network requests
                _invalid_token_cache[token_hash] = current_time
                return None

            userinfo = response.json()
            return dict(userinfo)

        except ImportError:
            logger.warning("httpx not available, falling back to sync validation")
            return self.validate_token_and_get_user_info(access_token)
        except Exception as e:
            logger.error(f"Exception during async token validation: {e}")
            # Cache this invalid token to avoid future network requests
            _invalid_token_cache[token_hash] = current_time
            return None

    def get_email_from_user_info(
        self,
        user_info: dict[str, Any],
        access_token: str | None = None,
        require_email: bool = False,
    ) -> str | None:
        """
        Extract email or unique provider identifier from user info.

        Behavior depends on require_email flag:
        - If True: Only return valid email addresses (respects force_email_prop_as_creator)
        - If False: Return provider-specific unique identifier if email unavailable

        Args:
            user_info: User information from OAuth2 provider
            access_token: OAuth2 access token (for additional API calls)
            require_email: If True, only return valid emails (not provider IDs)

        Returns:
            Email address or provider-specific identifier, or None if unavailable
        """
        if not user_info:
            return None

        # Always try to get email first (preferred for both modes)
        email = user_info.get("email")
        if email:
            return str(email).lower()

        # If email is required (force_email_prop_as_creator=True), try harder
        if require_email:
            if self.provider.name == "github" and access_token:
                # Try to fetch verified emails from GitHub API
                email = self._get_github_primary_email(access_token)
                if email:
                    return email.lower()

            # If still no email and email is required, return None
            # This will trigger email input form
            return None

        # Email not required - use provider-specific unique identifier
        logger.info(
            f"Email not available, using provider-specific identifier for {self.provider.name}"
        )

        if self.provider.name == "google":
            # Google 'sub' claim is stable unique identifier (never changes)
            sub = user_info.get("sub")
            if sub:
                return f"google:{sub}"

        if self.provider.name == "github":
            # GitHub user ID is most stable (doesn't change even if username changes)
            user_id = user_info.get("id")
            if user_id:
                return f"github:{user_id}"

            # Fallback to username (can change but better than nothing)
            login = user_info.get("login")
            if login:
                logger.warning(
                    f"Using GitHub username '{login}' as identifier - this may change"
                )
                return f"github:{login}".lower()

        # Fallback for other providers
        username = user_info.get("preferred_username", "")
        if username:
            return f"{self.provider.name}:{username}".lower()

        # No identifier available
        logger.error(
            f"Failed to extract any identifier from {self.provider.name} user info"
        )
        return None

    def _get_github_primary_email(self, access_token: str) -> str | None:
        """Get primary email from GitHub's emails API."""
        if not access_token:
            return None

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "ActingWeb-OAuth2-Client",
        }

        try:
            # Use requests library with better timeout handling
            response = requests.get(
                url="https://api.github.com/user/emails",
                headers=headers,
                timeout=(5, 10),  # (connect timeout, read timeout)
            )

            if response.status_code != 200:
                logger.warning(
                    f"GitHub emails API request failed: {response.status_code}"
                )
                return None

            emails = response.json()

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

    def _get_github_verified_emails(self, access_token: str) -> list[str] | None:
        """
        Fetch ALL verified emails from GitHub's emails API.

        Args:
            access_token: GitHub OAuth access token

        Returns:
            List of verified email addresses, or None if API call fails
        """
        if not access_token:
            return None

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "ActingWeb-OAuth2-Client",
        }

        try:
            response = requests.get(
                url="https://api.github.com/user/emails",
                headers=headers,
                timeout=(5, 10),
            )

            if response.status_code != 200:
                logger.warning(
                    f"GitHub emails API request failed: {response.status_code}"
                )
                return None

            emails = response.json()

            # Extract all verified emails
            verified = []
            for email_info in emails:
                if email_info.get("verified", False):
                    email = email_info.get("email")
                    if email:
                        verified.append(str(email).lower())

            if verified:
                logger.debug(f"Found {len(verified)} verified emails from GitHub")
                return verified

            return None

        except Exception as e:
            logger.warning(f"Failed to get GitHub verified emails: {e}")
            return None

    def lookup_or_create_actor_by_email(self, email: str) -> actor_module.Actor | None:
        """
        Look up actor by email or create new one if not found.

        DEPRECATED: Use lookup_or_create_actor_by_identifier() instead.

        Args:
            email: User email from OAuth2 provider

        Returns:
            Actor instance or None if failed
        """
        return self.lookup_or_create_actor_by_identifier(email, user_info=None)

    def lookup_or_create_actor_by_identifier(
        self, identifier: str, user_info: dict[str, Any] | None = None
    ) -> actor_module.Actor | None:
        """
        Look up actor by identifier (email or provider ID) or create new one if not found.

        Args:
            identifier: User identifier - can be email or provider-specific ID
            user_info: Optional user info for additional metadata storage

        Returns:
            Actor instance or None if failed
        """
        if not identifier:
            return None

        try:
            # Use get_from_creator() method to find existing actor by identifier
            existing_actor = actor_module.Actor(config=self.config)
            if existing_actor.get_from_creator(identifier):
                logger.info(f"Found existing actor for identifier: {identifier}")
                return existing_actor

            # Create new actor with identifier as creator
            logger.info(f"Creating new actor for identifier: {identifier}")

            try:
                actor_interface = ActorInterface.create(
                    creator=identifier,
                    config=self.config,
                    passphrase="",  # ActingWeb will auto-generate
                    hooks=getattr(self.config, "_hooks", None),
                )

                # Set up initial properties for OAuth actor
                if actor_interface.core_actor.store:
                    # Store OAuth provider info
                    actor_interface.core_actor.store.auth_method = (
                        f"{self.provider.name}_oauth2"
                    )
                    actor_interface.core_actor.store.created_at = str(int(time.time()))
                    actor_interface.core_actor.store.oauth_provider = self.provider.name

                    # If identifier is provider-specific ID, store actual email separately
                    if ":" in identifier and user_info:
                        email = user_info.get("email")
                        if email:
                            actor_interface.core_actor.store.email = email.lower()
                            logger.debug(
                                f"Stored display email for provider ID actor: {email}"
                            )

                        # Store provider-specific ID for reference
                        if identifier.startswith("google:"):
                            actor_interface.core_actor.store.oauth_sub = (
                                identifier.split(":", 1)[1]
                            )
                        elif identifier.startswith("github:"):
                            actor_interface.core_actor.store.oauth_github_id = (
                                identifier.split(":", 1)[1]
                            )
                    elif "@" in identifier:
                        # Identifier is an email - store it in email property too
                        actor_interface.core_actor.store.email = identifier

                return actor_interface.core_actor

            except Exception as create_error:
                logger.error(
                    f"Failed to create actor for identifier {identifier}: {create_error}"
                )
                return None

        except Exception as e:
            logger.error(
                f"Exception during actor lookup/creation for {identifier}: {e}"
            )
            return None

    def validate_email_from_state(self, state: str, authenticated_email: str) -> bool:
        from .oauth_state import validate_expected_email

        return validate_expected_email(state, authenticated_email)

    def authenticate_bearer_token(
        self, bearer_token: str
    ) -> tuple[actor_module.Actor | None, str | None]:
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

    def store_session_data(self, session_id: str, data: dict[str, Any]) -> None:
        """Store session data for OAuth2 flow."""
        self._sessions[session_id] = data

    def get_session_data(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data for OAuth2 flow."""
        return self._sessions.get(session_id)

    def clear_session_data(self, session_id: str) -> None:
        """Clear session data after OAuth2 flow completion."""
        self._sessions.pop(session_id, None)

    def revoke_token(self, token: str) -> bool:
        """
        Revoke an OAuth2 access or refresh token.

        This method calls the provider's revocation endpoint to invalidate
        the token, ensuring it cannot be used for further authentication.

        Args:
            token: OAuth2 access token or refresh token to revoke

        Returns:
            True if revocation was successful, False otherwise
        """
        try:
            if not self.is_enabled():
                logger.warning("OAuth2 provider not enabled, cannot revoke token")
                return False

            if not token:
                logger.warning("No token provided for revocation")
                return False

            # Get the revocation endpoint from the provider
            revocation_url = self.provider.revocation_uri
            if not revocation_url:
                logger.warning(
                    f"Provider {self.provider.__class__.__name__} does not support token revocation"
                )
                return False

            # Prepare revocation request
            import requests

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "ActingWeb/1.0",
            }

            data = {"token": token, "client_id": self.provider.client_id}

            # Add client secret if available (for confidential clients)
            if hasattr(self.provider, "client_secret") and self.provider.client_secret:
                data["client_secret"] = self.provider.client_secret

            # Make revocation request
            response = requests.post(
                revocation_url, data=data, headers=headers, timeout=10
            )

            # Google returns 200 for both successful revocations and already-invalid tokens
            # This is per RFC 7009 - revocation should be idempotent
            if response.status_code == 200:
                return True
            else:
                logger.warning(
                    f"Token revocation failed with status {response.status_code}: {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error during token revocation: {e}")
            return False


# Factory functions for backward compatibility and convenience


def create_oauth2_authenticator(
    config: config_class.Config, provider_name: str = ""
) -> OAuth2Authenticator:
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


def create_generic_authenticator(
    config: config_class.Config, provider_config: dict[str, Any]
) -> OAuth2Authenticator:
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


def extract_bearer_token(auth_header: str) -> str | None:
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


"""Legacy helpers removed: use actingweb.oauth_state.decode_state and validate_expected_email"""


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


def create_oauth2_trust_relationship(
    actor: ActorInterface,
    email: str,
    trust_type: str,
    oauth_tokens: dict[str, Any],
    established_via: str | None = None,
    client_id: str | None = None,
    client_name: str | None = None,
    client_version: str | None = None,
    client_platform: str | None = None,
) -> bool:
    """
    Create trust relationship after successful OAuth2 authentication.

    Args:
        actor: ActorInterface for the user's actor
        email: Authenticated user's email
        trust_type: Type of trust relationship to create
        oauth_tokens: OAuth2 tokens from authentication
        established_via: Optional override for how relationship was established
        client_id: Optional MCP client ID for unique identification per client
        client_name: Optional client application name
        client_version: Optional client application version
        client_platform: Optional client platform/user-agent info

    Returns:
        True if trust relationship was created successfully
    """
    try:
        # All OAuth2 trust relationships are established via OAuth2, regardless of trust type
        if established_via is None:
            established_via = ESTABLISHED_VIA_OAUTH2_INTERACTIVE

        # Delegate to TrustManager for unified behavior
        from .interface.trust_manager import TrustManager

        tm = TrustManager(actor.core_actor)
        return tm.create_or_update_oauth_trust(
            email=email,
            trust_type=trust_type,
            oauth_tokens=oauth_tokens,
            established_via=established_via,
            client_id=client_id,
            client_name=client_name,
            client_version=client_version,
            client_platform=client_platform,
        )
    except Exception as e:
        logger.error(f"Error creating OAuth2 trust relationship: {e}")
        return False
