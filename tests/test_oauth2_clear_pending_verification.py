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
