"""
Service client for making authenticated API calls to third-party OAuth2 services.

This provides a clean, modern replacement for the legacy OAuth class functionality,
built on top of the new OAuth2 system with proper token management.
"""

import json
import logging
from typing import Any
from urllib.parse import urljoin

import requests

from ...oauth2 import OAuth2Authenticator, OAuth2Provider
from .service_config import ServiceConfig

logger = logging.getLogger(__name__)


class ServiceOAuth2Provider(OAuth2Provider):
    """OAuth2 provider adapter for third-party services."""

    def __init__(self, service_config: ServiceConfig):
        # Convert ServiceConfig to OAuth2Provider format
        config_dict = service_config.to_oauth2_config()
        super().__init__(service_config.name, config_dict)
        self.service_config = service_config


class ServiceClient:
    """
    Clean, modern client for third-party OAuth2 service integration.

    This replaces the legacy OAuth class with a developer-friendly interface
    that automatically handles token management, refresh, and API calls.

    Example usage:
        # Get authenticated client
        dropbox = actor.services.get("dropbox")

        # Check authentication status
        if not dropbox.is_authenticated():
            return {"auth_url": dropbox.get_authorization_url()}

        # Make API calls
        files = dropbox.get("/2/files/list_folder", {"path": "/Documents"})
        response = dropbox.post("/2/files/upload", data=file_content)
    """

    def __init__(self, service_config: ServiceConfig, actor_interface, aw_config):
        """Initialize service client for a specific actor."""
        self.service_config = service_config
        self.actor = actor_interface
        self.aw_config = aw_config

        # Create OAuth2 authenticator for this service
        self.provider = ServiceOAuth2Provider(service_config)
        self.authenticator = OAuth2Authenticator(aw_config, self.provider)

        # Current access token
        self._access_token: str | None = None
        self._refresh_token: str | None = None

        # Load tokens from actor properties if available
        self._load_tokens()

    def _load_tokens(self) -> None:
        """Load OAuth tokens from actor storage."""
        if not self.actor.property:
            return

        # Load tokens stored for this service
        access_token_key = f"service_{self.service_config.name}_access_token"
        refresh_token_key = f"service_{self.service_config.name}_refresh_token"

        self._access_token = self.actor.property.get(access_token_key)
        self._refresh_token = self.actor.property.get(refresh_token_key)

    def _save_tokens(self, access_token: str, refresh_token: str | None = None) -> None:
        """Save OAuth tokens to actor storage."""
        if not self.actor.property:
            logger.warning(
                f"Cannot save tokens for service {self.service_config.name} - no property store"
            )
            return

        access_token_key = f"service_{self.service_config.name}_access_token"
        refresh_token_key = f"service_{self.service_config.name}_refresh_token"

        self.actor.property[access_token_key] = access_token
        self._access_token = access_token

        if refresh_token:
            self.actor.property[refresh_token_key] = refresh_token
            self._refresh_token = refresh_token

    def is_authenticated(self) -> bool:
        """Check if the service is authenticated for this actor."""
        return bool(self._access_token)

    def get_authorization_url(self, state: str = "", redirect_uri: str = "") -> str:
        """
        Get OAuth2 authorization URL for this service.

        Args:
            state: Optional state parameter for OAuth flow
            redirect_uri: Optional redirect URI override

        Returns:
            Authorization URL where user should be redirected
        """
        # Use service-specific redirect URI if not provided
        if not redirect_uri:
            redirect_uri = f"{self.aw_config.proto}{self.aw_config.fqdn}/services/{self.service_config.name}/callback"

        # Create authorization URL using OAuth2 authenticator
        return self.authenticator.create_authorization_url(
            state=state, redirect_after_auth=redirect_uri
        )

    def handle_callback(self, authorization_code: str, state: str = "") -> bool:
        """
        Handle OAuth2 callback and exchange code for tokens.

        Args:
            authorization_code: Authorization code from OAuth callback
            state: State parameter from OAuth callback

        Returns:
            True if token exchange was successful
        """
        try:
            # Exchange code for tokens
            token_response = self.authenticator.exchange_code_for_token(
                authorization_code, state
            )

            if not token_response or "access_token" not in token_response:
                logger.error(
                    f"Failed to exchange authorization code for {self.service_config.name}"
                )
                return False

            # Save tokens
            access_token = token_response["access_token"]
            refresh_token = token_response.get("refresh_token")

            self._save_tokens(access_token, refresh_token)

            logger.info(
                f"Successfully authenticated {self.service_config.name} for actor {self.actor.id}"
            )
            return True

        except Exception as e:
            logger.error(f"Error handling {self.service_config.name} callback: {e}")
            return False

    def _refresh_token_if_needed(self) -> bool:
        """Refresh access token if needed and possible."""
        if not self._refresh_token:
            return False

        try:
            token_response = self.authenticator.refresh_access_token(
                self._refresh_token
            )

            if token_response and "access_token" in token_response:
                new_access_token = token_response["access_token"]
                new_refresh_token = token_response.get(
                    "refresh_token", self._refresh_token
                )

                self._save_tokens(new_access_token, new_refresh_token)
                logger.info(f"Refreshed access token for {self.service_config.name}")
                return True

        except Exception as e:
            logger.error(f"Error refreshing token for {self.service_config.name}: {e}")

        return False

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | str | bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """
        Make authenticated API request to the service.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint (relative to base_api_url or absolute URL)
            params: URL parameters
            data: Request body data
            headers: Additional headers

        Returns:
            JSON response or None if request failed
        """
        if not self._access_token:
            logger.error(f"No access token available for {self.service_config.name}")
            return None

        # Build full URL
        if endpoint.startswith(("http://", "https://")):
            url = endpoint
        elif self.service_config.base_api_url:
            url = urljoin(self.service_config.base_api_url, endpoint)
        else:
            raise ValueError(
                f"No base_api_url configured for {self.service_config.name} and endpoint is not absolute"
            )

        # Prepare headers
        request_headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)

        # Prepare data
        if isinstance(data, dict):
            data = json.dumps(data)

        try:
            # Make request
            response = requests.request(
                method=method.upper(),
                url=url,
                params=params,
                data=data,
                headers=request_headers,
                timeout=(5, 30),  # 5s connect, 30s read timeout
            )

            # Handle authentication errors
            if response.status_code == 401:
                logger.info(
                    f"Access token expired for {self.service_config.name}, attempting refresh"
                )
                if self._refresh_token_if_needed():
                    # Retry with new token
                    request_headers["Authorization"] = f"Bearer {self._access_token}"
                    response = requests.request(
                        method=method.upper(),
                        url=url,
                        params=params,
                        data=data,
                        headers=request_headers,
                        timeout=(5, 30),
                    )
                else:
                    logger.error(
                        f"Unable to refresh token for {self.service_config.name}"
                    )
                    return None

            # Handle other error status codes
            if response.status_code >= 400:
                logger.error(
                    f"API request failed for {self.service_config.name}: {response.status_code} {response.text}"
                )
                return None

            # Return JSON response or empty dict for 204 No Content
            if response.status_code == 204:
                return {}

            return response.json() if response.content else {}

        except Exception as e:
            logger.error(f"Error making request to {self.service_config.name}: {e}")
            return None

    def get(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Make GET request to the service API."""
        return self._make_request("GET", endpoint, params=params)

    def post(
        self,
        endpoint: str,
        data: dict[str, Any] | str | bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Make POST request to the service API."""
        return self._make_request("POST", endpoint, params=params, data=data)

    def put(
        self,
        endpoint: str,
        data: dict[str, Any] | str | bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Make PUT request to the service API."""
        return self._make_request("PUT", endpoint, params=params, data=data)

    def delete(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Make DELETE request to the service API."""
        return self._make_request("DELETE", endpoint, params=params)

    def revoke_tokens(self) -> bool:
        """Revoke tokens and clear authentication for this service."""
        success = True

        # Revoke tokens with service if revocation endpoint is available
        if self.service_config.revocation_uri and self._access_token:
            try:
                response = requests.post(
                    self.service_config.revocation_uri,
                    data={"token": self._access_token},
                    timeout=(5, 10),
                )
                if response.status_code >= 400:
                    logger.warning(
                        f"Failed to revoke token with {self.service_config.name}: {response.status_code}"
                    )
                    success = False
            except Exception as e:
                logger.error(
                    f"Error revoking token with {self.service_config.name}: {e}"
                )
                success = False

        # Clear stored tokens
        if self.actor.property:
            access_token_key = f"service_{self.service_config.name}_access_token"
            refresh_token_key = f"service_{self.service_config.name}_refresh_token"

            self.actor.property[access_token_key] = None
            self.actor.property[refresh_token_key] = None

        self._access_token = None
        self._refresh_token = None

        logger.info(f"Cleared authentication for {self.service_config.name}")
        return success
