"""
Tests for ``clear_pending_email_verification`` (3.14.5): a provider-verified
login of an actor that was form-created and left pending
(``email_verified == "false"``, a live verification token and index row)
clears the squatted state instead of leaving an abandoned link able to
"verify" an actor its real owner has already authenticated into.
"""

from unittest.mock import MagicMock, patch

from actingweb.config import Config
from actingweb.oauth2 import clear_pending_email_verification


def _actor(email_verified: str | None = "false", token: str | None = "tok-abc"):
    actor = MagicMock()
    actor.store = MagicMock()
    actor.store.email_verified = email_verified
    actor.store.email_verification_token = token
    actor.store.email_verification_created_at = "1234"
    return actor


class TestClearPendingEmailVerification:
    def test_clears_pending_state_and_index_row(self):
        actor = _actor()
        config = MagicMock(spec=Config)

        with patch("actingweb.attribute.Attributes") as mock_attrs_cls:
            mock_index = MagicMock()
            mock_attrs_cls.return_value = mock_index

            clear_pending_email_verification(actor, config)

        mock_index.delete_attr.assert_called_once_with("tok-abc")
        assert actor.store.email_verified is None
        assert actor.store.email_verification_token is None
        assert actor.store.email_verification_created_at is None

    def test_noop_when_not_pending(self):
        """An actor whose email is provider-verified (absent) or link-verified
        ('true') has nothing to clear — no index lookup should happen."""
        for state in (None, "true"):
            actor = _actor(email_verified=state, token=None)
            config = MagicMock(spec=Config)

            with patch("actingweb.attribute.Attributes") as mock_attrs_cls:
                clear_pending_email_verification(actor, config)
                mock_attrs_cls.assert_not_called()

    def test_noop_when_no_store(self):
        actor = MagicMock()
        actor.store = None
        config = MagicMock(spec=Config)

        with patch("actingweb.attribute.Attributes") as mock_attrs_cls:
            clear_pending_email_verification(actor, config)
            mock_attrs_cls.assert_not_called()

    def test_pending_with_no_token_still_clears_flags_without_index_lookup(self):
        actor = _actor(email_verified="false", token=None)
        config = MagicMock(spec=Config)

        with patch("actingweb.attribute.Attributes") as mock_attrs_cls:
            clear_pending_email_verification(actor, config)
            mock_attrs_cls.assert_not_called()

        assert actor.store.email_verified is None


class TestClearPendingWiredIntoLookupOrCreate:
    def test_existing_actor_branch_calls_clear_pending(self):
        """lookup_or_create_actor_by_identifier's existing-actor branch (hit
        by a provider-verified web/dropdown login) clears squatted state."""
        from actingweb.oauth2 import GoogleOAuth2Provider, OAuth2Authenticator

        config = MagicMock(spec=Config)
        config.oauth = {}
        config.proto = "https://"
        config.fqdn = "test.example.com"
        provider = GoogleOAuth2Provider(config)
        authenticator = OAuth2Authenticator(config, provider)

        existing_actor = _actor()

        with (
            patch("actingweb.actor.Actor", return_value=existing_actor),
            patch("actingweb.oauth2.clear_pending_email_verification") as mock_clear,
        ):
            result = authenticator.lookup_or_create_actor_by_identifier(
                "user@example.com"
            )

        assert result is existing_actor
        mock_clear.assert_called_once_with(existing_actor, config)


class TestClearPendingOnStateSelectedActor:
    """An actor named by ``actor_id`` in the OAuth state is loaded directly
    and never reaches ``lookup_or_create_actor_by_identifier``, so the
    cleanup has to be wired at that branch too. The creator check just above
    it has already established that the provider vouched for this actor's
    owner."""

    def test_state_selected_actor_gets_pending_state_cleared(self):
        import json

        from actingweb.aw_web_request import AWWebObj
        from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

        config = MagicMock()
        config.proto = "https://"
        config.fqdn = "test.example.com"
        config.oauth2_provider = "google"
        config.force_email_prop_as_creator = False
        config.service_registry = None
        config.ui = False

        state_actor = _actor()
        state_actor.id = "actor-from-state"
        state_actor.creator = "user@example.com"
        state_actor.get.return_value = True

        auth = MagicMock()
        auth.is_enabled.return_value = True
        auth.provider.name = "google"
        auth.provider.mobile_deep_link = ""
        auth.exchange_code_for_token.return_value = {
            "access_token": "at",
            "expires_in": 3600,
        }
        auth.provider.extract_user_info_from_token_response.return_value = None
        auth.validate_token_and_get_user_info.return_value = {
            "email": "user@example.com"
        }
        auth.get_email_from_user_info.return_value = "user@example.com"

        state = json.dumps({"provider": "google", "actor_id": "actor-from-state"})
        webobj = AWWebObj(
            url="https://test.example.com/oauth/callback",
            params={"code": "c", "state": state},
            body="",
            headers={},
            cookies={},
        )

        hooks = MagicMock()
        hooks.execute_lifecycle_hooks.return_value = True

        with (
            patch(
                "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
                return_value=auth,
            ),
            patch("actingweb.actor.Actor", return_value=state_actor),
            patch("actingweb.oauth2.clear_pending_email_verification") as mock_clear,
        ):
            OAuth2CallbackHandler(webobj, config, hooks=hooks).get()

        # The state branch was taken (no lookup/create) and the cleanup ran.
        auth.lookup_or_create_actor_by_identifier.assert_not_called()
        mock_clear.assert_called_once_with(state_actor, config)
