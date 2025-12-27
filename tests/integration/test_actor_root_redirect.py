"""
Test actor root endpoint content negotiation.

Tests the /<actor_id> endpoint behavior:
- API clients (Accept: application/json or default) get JSON response
- Browsers (Accept: text/html) get redirected based on config.ui setting
"""

import requests


class TestActorRootContentNegotiation:
    """
    Test content negotiation for actor root endpoint.

    These tests verify that:
    - API clients receive JSON responses
    - Browser requests are redirected appropriately
    """

    # Shared state
    actor_url: str | None = None
    actor_id: str | None = None
    passphrase: str | None = None
    creator: str = "roottest@actingweb.net"

    def test_001_create_actor(self, http_client):
        """Create actor for testing."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        TestActorRootContentNegotiation.actor_url = response.headers.get("Location")
        TestActorRootContentNegotiation.actor_id = response.json()["id"]
        TestActorRootContentNegotiation.passphrase = response.json()["passphrase"]

    def test_002_api_client_gets_json_default(self, http_client):
        """
        API client with default Accept header gets JSON response.

        requests library sends Accept: */* by default.
        """
        response = requests.get(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
            allow_redirects=False,
        )
        assert response.status_code == 200
        assert "application/json" in response.headers.get("Content-Type", "")
        data = response.json()
        assert data["id"] == self.actor_id
        assert data["creator"] == self.creator

    def test_003_api_client_gets_json_explicit(self, http_client):
        """
        API client with explicit Accept: application/json gets JSON response.
        """
        response = requests.get(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
            headers={"Accept": "application/json"},
            allow_redirects=False,
        )
        assert response.status_code == 200
        assert "application/json" in response.headers.get("Content-Type", "")
        data = response.json()
        assert data["id"] == self.actor_id

    def test_004_browser_gets_redirect(self, http_client):
        """
        Browser (Accept: text/html) gets redirected.

        When config.ui is True, redirects to /<actor_id>/www
        When config.ui is False, redirects to /<actor_id>/app
        """
        response = requests.get(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
            headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            allow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        # Should redirect to either /www or /app depending on config
        assert "/www" in location or "/app" in location

    def test_005_browser_redirect_includes_actor_id(self, http_client):
        """
        Browser redirect Location header includes correct actor ID.
        """
        response = requests.get(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
            headers={"Accept": "text/html"},
            allow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert self.actor_id in location  # type: ignore[operator]

    def test_006_unauthenticated_browser_redirects_to_login(self, http_client):
        """
        Unauthenticated browser gets redirected to /login.

        This provides a consistent login experience instead of going
        directly to OAuth provider.
        """
        response = requests.get(
            self.actor_url,  # type: ignore[arg-type]
            # No auth credentials
            headers={"Accept": "text/html"},
            allow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "/login" in location

    def test_007_cleanup_actor(self, http_client):
        """Clean up test actor."""
        if self.actor_url:
            response = requests.delete(
                self.actor_url,
                auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
            )
            assert response.status_code == 204
