"""Tests that actor.store.oauth_provider is written on every sign-in.

Covers both the create path and the existing-actor lookup path of
OAuth2Authenticator.lookup_or_create_actor_by_identifier.
"""

from unittest.mock import MagicMock, patch

from actingweb.config import Config
from actingweb.oauth2 import GoogleOAuth2Provider, OAuth2Authenticator


def _authenticator() -> OAuth2Authenticator:
    config = Config(fqdn="test.example.com", database="dynamodb")
    config.oauth = {"client_id": "cid", "client_secret": "csec"}
    return OAuth2Authenticator(config, GoogleOAuth2Provider(config))


class TestOAuthProviderWrite:
    def test_written_on_existing_actor_lookup(self) -> None:
        auth = _authenticator()
        existing = MagicMock()
        existing.store = MagicMock()
        existing.get_from_creator.return_value = True

        with patch("actingweb.actor.Actor", return_value=existing):
            result = auth.lookup_or_create_actor_by_identifier("user@example.com")

        assert result is existing
        assert existing.store.oauth_provider == "google"

    def test_written_on_new_actor_create(self) -> None:
        auth = _authenticator()
        # Existing lookup returns no actor -> create path.
        existing = MagicMock()
        existing.get_from_creator.return_value = False

        created = MagicMock()
        created_iface = MagicMock()
        created_iface.core_actor = created
        created.store = MagicMock()

        with (
            patch("actingweb.actor.Actor", return_value=existing),
            patch("actingweb.oauth2.ActorInterface.create", return_value=created_iface),
        ):
            result = auth.lookup_or_create_actor_by_identifier(
                "google:sub123", user_info={"email": "user@example.com"}
            )

        assert result is created
        assert created.store.oauth_provider == "google"
