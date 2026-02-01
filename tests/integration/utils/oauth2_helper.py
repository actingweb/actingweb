"""
OAuth2 Test Helper.

Provides utilities for testing OAuth2-protected endpoints like /www and /mcp.

This helper handles the complete OAuth2 flow:
1. Register an MCP client
2. Exchange credentials for access token
3. Make authenticated requests with Bearer token
"""

from typing import Any

import requests


class OAuth2TestHelper:
    """
    Helper class for OAuth2-protected endpoint testing.

    This class manages the OAuth2 client lifecycle and provides
    authenticated HTTP methods for testing.
    """

    def __init__(self, base_url: str, worker_id: str = "master"):
        """
        Initialize OAuth2 test helper.

        Args:
            base_url: Base URL of the ActingWeb application (e.g., "http://localhost:5555")
            worker_id: Worker ID for parallel test isolation (e.g., "gw0", "master")
        """
        self.base_url = base_url
        self.worker_id = worker_id
        self.client_id: str | None = None
        self.client_secret: str | None = None
        self.access_token: str | None = None
        self.actor_id: str | None = None

    def register_client(
        self, client_name: str = "Test OAuth2 Client", trust_type: str = "mcp_client"
    ) -> dict[str, Any]:
        """
        Register an OAuth2 client for testing.

        Args:
            client_name: Human-readable name for the client
            trust_type: Trust type for the client (default: mcp_client)

        Returns:
            Client registration response

        Raises:
            AssertionError: If registration fails
        """
        # Add worker ID to ensure unique client_name across workers
        unique_client_name = f"{client_name} [w{self.worker_id}]"

        response = requests.post(
            f"{self.base_url}/oauth/register",
            json={
                "client_name": unique_client_name,
                "redirect_uris": ["http://localhost:3000/callback"],
                "grant_types": ["client_credentials"],
                "trust_type": trust_type,
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201, (
            f"Client registration failed: {response.text}"
        )

        client_data = response.json()
        self.client_id = client_data["client_id"]
        self.client_secret = client_data["client_secret"]
        self.actor_id = client_data.get("actor_id", "_actingweb_oauth2")

        return client_data

    def get_access_token(self, scope: str = "mcp") -> str:
        """
        Get an access token using client credentials flow.

        Args:
            scope: OAuth2 scope to request (default: mcp)

        Returns:
            Access token string

        Raises:
            AssertionError: If token exchange fails
        """
        assert self.client_id is not None, "Client must be registered first"
        assert self.client_secret is not None, "Client must be registered first"

        form_data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": scope,
        }

        response = requests.post(
            f"{self.base_url}/oauth/token",
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data["access_token"]
            return self.access_token  # type: ignore[arg-type,union-attr,attr-defined,return-value]
        else:
            # Token endpoint returned error - this means grant_type parsing failed
            # or client credentials were invalid
            try:
                error_data = response.json()
                error_msg = (
                    f"Token exchange failed: {error_data.get('error', response.text)}"
                )
            except Exception:
                error_msg = f"Token exchange failed with status {response.status_code}: {response.text}"
            raise AssertionError(error_msg)

    def get(self, path: str, **kwargs) -> requests.Response:
        """
        Make an authenticated GET request.

        Args:
            path: URL path (without base URL)
            **kwargs: Additional arguments for requests.get()

        Returns:
            Response object
        """
        assert self.access_token is not None, "Must get access token first"

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"

        return requests.get(f"{self.base_url}{path}", headers=headers, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        """
        Make an authenticated POST request.

        Args:
            path: URL path (without base URL)
            **kwargs: Additional arguments for requests.post()

        Returns:
            Response object
        """
        assert self.access_token is not None, "Must get access token first"

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"

        return requests.post(f"{self.base_url}{path}", headers=headers, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        """
        Make an authenticated DELETE request.

        Args:
            path: URL path (without base URL)
            **kwargs: Additional arguments for requests.delete()

        Returns:
            Response object
        """
        assert self.access_token is not None, "Must get access token first"

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"

        return requests.delete(f"{self.base_url}{path}", headers=headers, **kwargs)


def create_authenticated_client(
    base_url: str,
    worker_id: str = "master",
    client_name: str = "Test Client",
    scope: str = "mcp",
) -> OAuth2TestHelper:
    """
    Convenience function to create a fully authenticated OAuth2 client.

    This performs all necessary setup:
    1. Registers the client
    2. Exchanges credentials for access token
    3. Returns helper ready for making authenticated requests

    Args:
        base_url: Base URL of the ActingWeb application
        worker_id: Worker ID for parallel test isolation (e.g., "gw0", "master")
        client_name: Human-readable name for the client
        scope: OAuth2 scope to request (default: mcp)

    Returns:
        Configured OAuth2TestHelper instance

    Example:
        >>> client = create_authenticated_client("http://localhost:5555")
        >>> response = client.get("/mcp")
        >>> assert response.status_code == 200
    """
    helper = OAuth2TestHelper(base_url, worker_id=worker_id)
    helper.register_client(client_name)
    helper.get_access_token(scope=scope)
    return helper
