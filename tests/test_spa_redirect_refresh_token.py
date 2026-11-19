"""A redirect sign-in mints a refresh token only where it hands one out.

The browser redirect of an SPA sign-in keeps its result as a pending
session, and fetching that session never returns a refresh token. With
``json`` or ``cookie`` delivery the callback still minted one and kept it
in the session: a live token nobody holds (release validation 2026-11-18,
owner: mint only for ``hybrid``, whose cookie carries it).
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

CALLBACK = "https://test.example.com/oauth/callback"
SPA_REDIRECT = "https://test.example.com/spa/callback"


def _sign_in(token_delivery: str) -> tuple[AWWebObj, MagicMock]:
    config = MagicMock()
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "google"
    config.force_email_prop_as_creator = False
    config.service_registry = None
    config._hooks = None
    auth = MagicMock()
    auth.is_enabled.return_value = True
    auth.provider.name = "google"
    auth.provider.mobile_deep_link = ""
    auth.exchange_code_for_token.return_value = {
        "access_token": "provider-at",
        "expires_in": 3600,
    }
    auth.provider.extract_user_info_from_token_response.return_value = None
    auth.validate_token_and_get_user_info.return_value = {
        "sub": "u1",
        "email": "u@example.test",
        "email_verified": True,
    }
    auth.get_email_from_user_info.return_value = "u@example.test"
    actor = MagicMock()
    actor.id = "actor-1"
    auth.lookup_or_create_actor_by_identifier.return_value = actor
    state = json.dumps(
        {
            "provider": "google",
            "spa_mode": True,
            "redirect_url": SPA_REDIRECT,
            "token_delivery": token_delivery,
        }
    )
    webobj = AWWebObj(
        url=f"{CALLBACK}?code=c&state=...",
        params={"code": "c", "state": state},
        body="",
        headers={},
        cookies={},
    )
    session_mgr = MagicMock()
    session_mgr.get_session.return_value = None
    session_mgr.store_session.return_value = "sess-id"
    session_mgr.create_refresh_token.return_value = "spa-refresh"
    with (
        patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
            return_value=auth,
        ),
        patch(
            "actingweb.oauth_session.get_oauth2_session_manager",
            return_value=session_mgr,
        ),
    ):
        OAuth2CallbackHandler(webobj, config, hooks=None).get()
    return webobj, session_mgr


def _stored_token_data(session_mgr: MagicMock) -> dict[str, Any]:
    assert session_mgr.store_session.called, "the sign-in did not complete"
    return session_mgr.store_session.call_args.kwargs["token_data"]


@pytest.mark.parametrize("delivery", ["json", "cookie"])
def test_no_refresh_token_is_minted_where_none_is_handed_out(delivery: str) -> None:
    webobj, session_mgr = _sign_in(delivery)
    session_mgr.create_refresh_token.assert_not_called()
    assert "refresh_token" not in _stored_token_data(session_mgr)
    assert webobj.response.redirect and "sess-id" in webobj.response.redirect


def test_hybrid_mints_one_and_sets_it_as_the_cookie() -> None:
    webobj, session_mgr = _sign_in("hybrid")
    session_mgr.create_refresh_token.assert_called_once()
    assert "refresh_token" not in _stored_token_data(session_mgr)
    assert "spa-refresh" in json.dumps(webobj.response.cookies, default=str)
