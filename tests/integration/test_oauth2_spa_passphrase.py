"""
Integration tests for passphrase-to-SPA-token exchange endpoint.

Tests the POST /oauth/spa/token endpoint with grant_type="passphrase",
which exchanges a valid creator passphrase for SPA tokens.
"""

import os
import time
from threading import Thread

import pytest
import requests
import uvicorn


class TestPassphraseExchangeEndpoint:
    """Test the passphrase exchange endpoint in devtest mode."""

    def test_passphrase_exchange_success(self, test_app, actor_factory):
        """
        Test successful passphrase exchange returns valid tokens.

        Steps:
        1. Create an actor with known passphrase
        2. Exchange passphrase for SPA tokens
        3. Verify response contains valid tokens
        """
        # Create actor
        actor = actor_factory.create("passphrase_test@example.com")

        # Exchange passphrase for tokens
        response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": actor["id"],
                "passphrase": actor["passphrase"],
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert data["success"] is True
        assert data["actor_id"] == actor["id"]
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] == 3600
        assert "expires_at" in data
        assert data["refresh_token_expires_in"] == 86400 * 14

    def test_passphrase_exchange_invalid_passphrase(self, test_app, actor_factory):
        """Test that invalid passphrase returns 401."""
        # Create actor
        actor = actor_factory.create("invalid_pass_test@example.com")

        # Try with wrong passphrase
        response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": actor["id"],
                "passphrase": "wrong-passphrase",
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["error"] is True
        assert "passphrase" in data["message"].lower() or "invalid" in data["message"].lower()

    def test_passphrase_exchange_nonexistent_actor(self, test_app):
        """Test that nonexistent actor returns 404."""
        response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": "nonexistent-actor-id",
                "passphrase": "some-passphrase",
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 404
        data = response.json()
        assert data["error"] is True

    def test_passphrase_exchange_missing_actor_id(self, test_app):
        """Test that missing actor_id returns 400."""
        response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "passphrase": "some-passphrase",
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] is True
        assert "actor_id" in data["message"]

    def test_passphrase_exchange_missing_passphrase(self, test_app, actor_factory):
        """Test that missing passphrase returns 400."""
        actor = actor_factory.create("missing_pass_test@example.com")

        response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": actor["id"],
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error"] is True
        assert "passphrase" in data["message"]

    def test_token_can_be_used_to_access_actor(self, test_app, actor_factory):
        """
        Test that the returned access token can be used to access the actor.

        This is the main use case: get a token via passphrase, then use it
        for subsequent API calls.
        """
        # Create actor
        actor = actor_factory.create("token_use_test@example.com")

        # Exchange passphrase for tokens
        token_response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": actor["id"],
                "passphrase": actor["passphrase"],
            },
            headers={"Content-Type": "application/json"},
        )

        assert token_response.status_code == 200
        access_token = token_response.json()["access_token"]

        # Use the token to access the actor's properties
        props_response = requests.get(
            f"{test_app}/{actor['id']}/properties",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        # Should be able to access (may be 200 with empty list or 404 if no properties)
        assert props_response.status_code in [200, 404]

    def test_token_delivery_cookie_mode(self, test_app, actor_factory):
        """Test cookie delivery mode sets cookies properly."""
        actor = actor_factory.create("cookie_mode_test@example.com")

        response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": actor["id"],
                "passphrase": actor["passphrase"],
                "token_delivery": "cookie",
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # In cookie mode, tokens should NOT be in JSON body
        assert "access_token" not in data
        assert "refresh_token" not in data
        assert data["token_delivery"] == "cookie"

        # Cookies should be set
        assert "access_token" in response.cookies or "oauth_token" in response.cookies

    def test_token_delivery_hybrid_mode(self, test_app, actor_factory):
        """Test hybrid delivery mode returns access token in body, refresh in cookie."""
        actor = actor_factory.create("hybrid_mode_test@example.com")

        response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": actor["id"],
                "passphrase": actor["passphrase"],
                "token_delivery": "hybrid",
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 200
        data = response.json()

        # In hybrid mode, access token in body, refresh token NOT in body
        assert "access_token" in data
        assert "refresh_token" not in data
        assert data["token_delivery"] == "hybrid"

    def test_refresh_token_can_be_used_for_refresh(self, test_app, actor_factory):
        """Test that the returned refresh token can be used to get new tokens."""
        # Create actor
        actor = actor_factory.create("refresh_test@example.com")

        # Exchange passphrase for tokens
        token_response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": actor["id"],
                "passphrase": actor["passphrase"],
            },
            headers={"Content-Type": "application/json"},
        )

        assert token_response.status_code == 200
        refresh_token = token_response.json()["refresh_token"]

        # Use refresh token to get new access token
        refresh_response = requests.post(
            f"{test_app}/oauth/spa/token",
            json={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/json"},
        )

        assert refresh_response.status_code == 200
        data = refresh_response.json()
        assert data["success"] is True
        assert "access_token" in data


class TestPassphraseExchangeDevtestDisabled:
    """Test that passphrase exchange is blocked when devtest is disabled."""

    @pytest.fixture(scope="class")
    def no_devtest_app(self, docker_services, setup_database, worker_info):
        """
        Start a test app with devtest disabled.

        Uses a different port than the main test_app to run simultaneously.
        """
        from ..integration.test_harness import create_test_app

        # Use a port that doesn't conflict with other test apps
        no_devtest_port = 5580 + worker_info["port_offset"]
        no_devtest_url = f"http://localhost:{no_devtest_port}"

        # Set environment based on database backend
        os.environ["DATABASE_BACKEND"] = os.environ.get("DATABASE_BACKEND", "dynamodb")

        # Create app with devtest DISABLED
        fastapi_app, _ = create_test_app(
            fqdn=f"localhost:{no_devtest_port}",
            proto="http://",
            enable_oauth=True,
            enable_mcp=False,
            enable_devtest=False,  # Key difference: devtest disabled
        )

        # Run in background thread
        def run_app():
            uvicorn.run(
                fastapi_app,
                host="0.0.0.0",
                port=no_devtest_port,
                log_level="error",
            )

        thread = Thread(target=run_app, daemon=True)
        thread.start()

        # Wait for app to be ready
        max_retries = 30
        for _ in range(max_retries):
            try:
                response = requests.get(f"{no_devtest_url}/", timeout=2)
                if response.status_code in [200, 404]:
                    break
            except requests.exceptions.ConnectionError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError(f"No-devtest app failed to start on port {no_devtest_port}")

        return no_devtest_url

    def test_passphrase_exchange_forbidden_without_devtest(
        self, no_devtest_app, test_app, actor_factory
    ):
        """
        Test that passphrase exchange returns 403 when devtest is disabled.

        Creates an actor using the main test_app (with devtest enabled),
        then tries to exchange passphrase on the no-devtest app.
        """
        # Create actor using main test app (with devtest enabled)
        # Note: Both apps share the same database
        actor = actor_factory.create("devtest_forbidden_test@example.com")

        # Try to exchange passphrase on the no-devtest app
        response = requests.post(
            f"{no_devtest_app}/oauth/spa/token",
            json={
                "grant_type": "passphrase",
                "actor_id": actor["id"],
                "passphrase": actor["passphrase"],
            },
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 403
        data = response.json()
        assert data["error"] is True
        assert "devtest" in data["message"].lower()
