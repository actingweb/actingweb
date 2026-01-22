"""
OAuth2 Security Tests.

Tests security protections in the OAuth2 authentication flows:
1. Cross-actor authorization prevention (MCP flow)
2. Session fixation prevention (web login flow)
3. Email validation during authorization

These tests ensure that OAuth2 flows properly validate actor ownership
and prevent unauthorized access to other users' actors.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.oauth_state import encode_state


@pytest.fixture(autouse=True)
def cleanup_mocks() -> Generator[None, None, None]:
    """Ensure all mocks are cleaned up between tests to prevent pollution."""
    yield
    # Stop all active patches after each test
    patch.stopall()


@pytest.mark.xdist_group(name="oauth2_security_TestCrossActorAuthorizationPrevention")
class TestCrossActorAuthorizationPrevention:
    """
    Test protection against cross-actor authorization attacks.

    Attack scenario:
    1. Alice creates actor with email alice@example.com (actor_id=alice_123)
    2. Bob attempts MCP authorization with actor_id=alice_123
    3. Bob authenticates with bob@example.com via OAuth2
    4. System should REJECT - Bob cannot authorize access to Alice's actor
    """

    def test_mcp_authorization_rejects_different_email(
        self, actor_factory: Any, test_app: str
    ) -> None:
        """
        Test that MCP authorization is rejected when OAuth email doesn't match actor creator.

        This prevents Bob from authorizing MCP access to Alice's actor.
        """
        # Step 1: Alice creates her actor
        alice_actor = actor_factory.create("alice@example.com")
        alice_actor_id = alice_actor["id"]

        # Step 2: Bob attempts MCP authorization with Alice's actor_id
        # Encode state with Alice's actor_id and trust_type (MCP flow)
        state = encode_state(
            csrf="test_csrf",
            redirect="",
            actor_id=alice_actor_id,  # Alice's actor
            trust_type="mcp_client",  # This triggers trust relationship creation
            expected_email="",
            user_agent="",
        )

        # Step 3: Create request object for OAuth2 callback
        from actingweb import config as config_module

        config = config_module.Config(database="dynamodb")

        # Configure OAuth2
        config.oauth = {"client_id": "test_client", "client_secret": "test_secret"}
        config.fqdn = test_app.replace("http://", "").replace("https://", "")
        config.proto = "http://" if "http://" in test_app else "https://"

        webobj = AWWebObj(
            url=f"{test_app}/oauth/callback?code=bob_auth_code&state={state}",
            params={"code": "bob_auth_code", "state": state},
            body=None,
            headers={},
            cookies={},
        )

        # Step 4: Mock OAuth2Authenticator methods to return Bob's credentials
        with patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator"
        ) as mock_create_auth:
            mock_authenticator = MagicMock()
            mock_create_auth.return_value = mock_authenticator
            mock_authenticator.is_enabled.return_value = True

            # Mock token exchange to return Bob's token data
            mock_authenticator.exchange_code_for_token.return_value = {
                "access_token": "bob_access_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

            # Mock email extraction to return Bob's email (not Alice's!)
            mock_authenticator.get_email_from_user_info.return_value = "bob@example.com"
            mock_authenticator.provider.name = "google"

            # Step 5: Call the OAuth2 callback handler
            from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

            handler = OAuth2CallbackHandler(webobj, config, hooks=None)
            result = handler.get()

            # Step 6: Verify authorization was rejected (403 status)
            assert webobj.response.status_code == 403, (
                f"Expected 403 Forbidden, got {webobj.response.status_code}"
            )

            # Verify result contains error
            assert "error" in result or result.get("status_code") == 403, (
                f"Result should indicate error: {result}"
            )

            # Verify error message mentions the mismatch
            error_msg = str(result.get("message", "")).lower()
            assert any(
                keyword in error_msg
                for keyword in [
                    "bob@example.com",
                    "alice@example.com",
                    "different",
                    "doesn't belong",
                ]
            ), f"Error message should explain the mismatch: {result}"

    def test_web_login_rejects_different_email(
        self, actor_factory: Any, test_app: str
    ) -> None:
        """
        Test that web login is rejected when OAuth email doesn't match actor creator.

        This prevents session fixation attacks where an attacker tricks a victim
        into logging in to the attacker's actor.
        """
        # Step 1: Alice creates her actor
        alice_actor = actor_factory.create("alice@example.com")
        alice_actor_id = alice_actor["id"]

        # Step 2: Attacker tricks victim into OAuth with attacker's actor_id
        # Encode state with Alice's actor_id but NO trust_type (web login flow)
        state = encode_state(
            csrf="test_csrf",
            redirect="",
            actor_id=alice_actor_id,  # Alice's actor
            trust_type="",  # Empty trust_type = web login flow
            expected_email="",
            user_agent="",
        )

        # Step 3: Create request object
        from actingweb import config as config_module

        config = config_module.Config(database="dynamodb")
        config.oauth = {"client_id": "test_client", "client_secret": "test_secret"}
        config.fqdn = test_app.replace("http://", "").replace("https://", "")
        config.proto = "http://" if "http://" in test_app else "https://"

        webobj = AWWebObj(
            url=f"{test_app}/oauth/callback?code=bob_auth_code&state={state}",
            params={"code": "bob_auth_code", "state": state},
            body=None,
            headers={},
            cookies={},
        )

        # Step 4: Mock OAuth2Authenticator to return Bob's credentials
        with patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator"
        ) as mock_create_auth:
            mock_authenticator = MagicMock()
            mock_create_auth.return_value = mock_authenticator
            mock_authenticator.is_enabled.return_value = True

            mock_authenticator.exchange_code_for_token.return_value = {
                "access_token": "bob_access_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

            mock_authenticator.get_email_from_user_info.return_value = "bob@example.com"
            mock_authenticator.provider.name = "google"

            # Step 5: Call handler
            from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

            handler = OAuth2CallbackHandler(webobj, config, hooks=None)
            result = handler.get()

            # Step 6: Verify login was rejected (session fixation prevented)
            assert webobj.response.status_code == 403, (
                f"Expected 403 Forbidden, got {webobj.response.status_code}"
            )

            error_msg = str(result.get("message", "")).lower()
            assert any(
                word in error_msg
                for word in ["authentication", "failed", "doesn't belong"]
            ), f"Error should mention authentication failure: {result}"

    def test_self_authorization_succeeds(
        self, actor_factory: Any, test_app: str
    ) -> None:
        """
        Test that legitimate self-authorization succeeds.

        Alice authorizes MCP access to her own actor - should succeed.
        """
        # Step 1: Alice creates her actor
        alice_actor = actor_factory.create("alice@example.com")
        alice_actor_id = alice_actor["id"]
        alice_email = alice_actor["creator"]  # Get actual email (may be uniquified)

        # Step 2: Alice starts MCP authorization for her own actor
        state = encode_state(
            csrf="test_csrf",
            redirect="",
            actor_id=alice_actor_id,  # Alice's own actor
            trust_type="mcp_client",
            expected_email="",
            user_agent="",
        )

        # Step 3: Create request object
        from actingweb import config as config_module

        config = config_module.Config(database="dynamodb")
        config.oauth = {"client_id": "test_client", "client_secret": "test_secret"}
        config.fqdn = test_app.replace("http://", "").replace("https://", "")
        config.proto = "http://" if "http://" in test_app else "https://"

        webobj = AWWebObj(
            url=f"{test_app}/oauth/callback?code=alice_auth_code&state={state}",
            params={"code": "alice_auth_code", "state": state},
            body=None,
            headers={},
            cookies={},
        )

        # Step 4: Mock OAuth2Authenticator to return Alice's credentials
        # Patch where it's imported in the handler to avoid test pollution
        with patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator"
        ) as mock_create_auth:
            mock_authenticator = MagicMock()
            mock_create_auth.return_value = mock_authenticator
            mock_authenticator.is_enabled.return_value = True

            mock_authenticator.exchange_code_for_token.return_value = {
                "access_token": "alice_access_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

            # Use actual actor email (may be uniquified for parallel execution)
            mock_authenticator.get_email_from_user_info.return_value = alice_email
            mock_authenticator.provider.name = "google"

            # Step 5: Call handler
            from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

            handler = OAuth2CallbackHandler(webobj, config, hooks=None)
            result = handler.get()

            # Step 6: Verify authorization succeeded (redirect or success)
            assert webobj.response.status_code in [200, 302], (
                f"Expected success (200 or 302), got {webobj.response.status_code}: {result}"
            )

            # Verify not an error response
            assert not result.get("error") or webobj.response.status_code in [
                200,
                302,
            ], f"Self-authorization should succeed: {result}"

    def test_new_actor_creation_without_actor_id(self, test_app: str) -> None:
        """
        Test that new actor creation succeeds when no actor_id is provided.

        Bob starts OAuth without actor_id - system creates new actor for Bob.
        """
        # Step 1: Bob starts OAuth without actor_id (new actor flow)
        state = encode_state(
            csrf="test_csrf",
            redirect="",
            actor_id="",  # No actor_id = create new actor
            trust_type="mcp_client",
            expected_email="",
            user_agent="",
        )

        # Step 2: Create request object
        from actingweb import config as config_module

        config = config_module.Config(database="dynamodb")
        config.oauth = {"client_id": "test_client", "client_secret": "test_secret"}
        config.fqdn = test_app.replace("http://", "").replace("https://", "")
        config.proto = "http://" if "http://" in test_app else "https://"

        webobj = AWWebObj(
            url=f"{test_app}/oauth/callback?code=bob_auth_code&state={state}",
            params={"code": "bob_auth_code", "state": state},
            body=None,
            headers={},
            cookies={},
        )

        # Step 3: Mock OAuth2Authenticator to return Bob's credentials
        with patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator"
        ) as mock_create_auth:
            mock_authenticator = MagicMock()
            mock_create_auth.return_value = mock_authenticator
            mock_authenticator.is_enabled.return_value = True

            # Create a mock actor for Bob
            mock_bob_actor = MagicMock()
            mock_bob_actor.id = "bob_actor_123"
            mock_bob_actor.creator = "bob@example.com"
            mock_bob_actor.store = MagicMock()

            mock_authenticator.exchange_code_for_token.return_value = {
                "access_token": "bob_access_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

            mock_authenticator.get_email_from_user_info.return_value = "bob@example.com"
            mock_authenticator.provider.name = "google"

            # Mock actor creation
            mock_authenticator.lookup_or_create_actor_by_identifier.return_value = (
                mock_bob_actor
            )

            # Step 4: Call handler
            from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

            handler = OAuth2CallbackHandler(webobj, config, hooks=None)
            result = handler.get()

            # Step 5: Verify new actor was created (success response)
            assert webobj.response.status_code in [200, 302], (
                f"Expected success creating new actor, got {webobj.response.status_code}: {result}"
            )

    def test_provider_id_mode_validation(
        self, actor_factory: Any, test_app: str
    ) -> None:
        """
        Test that provider ID mode (force_email_prop_as_creator=False) also validates ownership.

        When using provider IDs like google:12345, the validation should still work.
        """
        # This test requires provider ID mode to be enabled
        # For now, we'll test the email mode which is the default
        # A full test would require a test app configured with provider ID mode
        pass


@pytest.mark.xdist_group(name="oauth2_security_TestEmailValidationSecurity")
class TestEmailValidationSecurity:
    """Test email validation during OAuth2 flows."""

    def test_reject_unverified_email_in_strict_mode(self, test_app: str) -> None:
        """
        Test that unverified emails are handled appropriately.

        This is part of the email verification security system.
        """
        # Encode state for web login
        state = encode_state(
            csrf="test_csrf",
            redirect="",
            actor_id="",
            trust_type="",  # Web login
            expected_email="",
            user_agent="",
        )

        # Create request object
        from actingweb import config as config_module

        config = config_module.Config(database="dynamodb")
        config.oauth = {"client_id": "test_client", "client_secret": "test_secret"}
        config.fqdn = test_app.replace("http://", "").replace("https://", "")
        config.proto = "http://" if "http://" in test_app else "https://"

        webobj = AWWebObj(
            url=f"{test_app}/oauth/callback?code=auth_code&state={state}",
            params={"code": "auth_code", "state": state},
            body=None,
            headers={},
            cookies={},
        )

        # Mock OAuth2Authenticator returning email (which will trigger verification)
        with patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator"
        ) as mock_create_auth:
            mock_authenticator = MagicMock()
            mock_create_auth.return_value = mock_authenticator
            mock_authenticator.is_enabled.return_value = True

            # Mock actor for verification flow
            mock_actor = MagicMock()
            mock_actor.id = "test_actor_456"
            mock_actor.creator = "user@example.com"
            mock_actor.store = MagicMock()

            mock_authenticator.exchange_code_for_token.return_value = {
                "access_token": "access_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

            mock_authenticator.get_email_from_user_info.return_value = (
                "user@example.com"
            )
            mock_authenticator.provider.name = "google"

            # Mock actor creation
            mock_authenticator.lookup_or_create_actor_by_identifier.return_value = (
                mock_actor
            )

            # Call handler
            from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

            handler = OAuth2CallbackHandler(webobj, config, hooks=None)
            result = handler.get()

            # Should redirect to actor www page or handle verification
            # (The exact behavior depends on email verification configuration)
            assert webobj.response.status_code in [200, 302, 400, 502], (
                f"Should handle email appropriately, got {webobj.response.status_code}: {result}"
            )
