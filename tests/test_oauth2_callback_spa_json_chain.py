"""The callback's SPA JSON return tags the login token pair with one chain.

``spa_mode`` with no ``redirect_url`` in the state answers the callback with
JSON tokens. Its access token and refresh token must share a chain id, so a
logout or revoke with either ends the whole session (3.15.1).
"""

import json
from unittest.mock import MagicMock, patch

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

CALLBACK = "https://test.example.com/oauth/callback"


def _config() -> MagicMock:
    config = MagicMock()
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "google"
    config.force_email_prop_as_creator = False
    config.service_registry = None
    config.ui = True
    config.new_token = MagicMock(return_value="aw-spa-access")
    return config


def _authenticator(actor: MagicMock) -> MagicMock:
    auth = MagicMock()
    auth.is_enabled.return_value = True
    auth.provider.name = "google"
    auth.provider.mobile_deep_link = ""
    auth.exchange_code_for_token.return_value = {
        "access_token": "provider-at",
        "expires_in": 3600,
    }
    auth.provider.extract_user_info_from_token_response.return_value = None
    auth.validate_token_and_get_user_info.return_value = {"sub": "u1"}
    auth.get_email_from_user_info.return_value = "user@example.com"
    auth.lookup_or_create_actor_by_identifier.return_value = actor
    return auth


def test_the_spa_json_return_shares_one_chain_between_the_pair() -> None:
    actor = MagicMock()
    actor.id = "actor-spa-json"
    actor.store = MagicMock()
    state = json.dumps({"provider": "google", "spa_mode": True})
    webobj = AWWebObj(
        url=f"{CALLBACK}?code=c&state=...",
        params={"code": "c", "state": state},
        body="",
        headers={},
        cookies={},
    )
    session_mgr = MagicMock()
    session_mgr.get_session.return_value = None
    session_mgr.new_chain_id.return_value = "login-chain"
    session_mgr.create_refresh_token.return_value = "spa-refresh"

    with (
        patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
            return_value=_authenticator(actor),
        ),
        patch("actingweb.actor.Actor") as actor_cls,
        patch(
            "actingweb.oauth_session.get_oauth2_session_manager",
            return_value=session_mgr,
        ),
    ):
        actor_cls.return_value.get_from_creator.return_value = True
        actor_cls.return_value.id = actor.id
        actor_cls.return_value.store = actor.store
        result = OAuth2CallbackHandler(webobj, _config(), hooks=None).get()

    assert result.get("access_token") == "aw-spa-access"
    assert result.get("refresh_token") == "spa-refresh"
    assert (
        session_mgr.store_access_token.call_args.kwargs["chain_id"]
        == session_mgr.create_refresh_token.call_args.kwargs["chain_id"]
        == "login-chain"
    )
