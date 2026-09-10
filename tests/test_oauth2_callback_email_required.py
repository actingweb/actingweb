"""
Tests for the OAuth2 callback's email-required branches after 3.14.5: a
provider API failure (``get_verified_emails`` returning ``None``) must not be
treated the same as "the provider vouches for nothing" (``[]``) — the former
sent a fully-verified GitHub user to the free-text form on a transient/scope
failure and is now a loud error instead.
"""

import json
from unittest.mock import MagicMock, patch

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

CALLBACK = "https://test.example.com/oauth/callback"
SPA_REDIRECT = "https://test.example.com/spa/callback"  # same FQDN -> safe redirect


def _config(provider: str = "github") -> MagicMock:
    config = MagicMock()
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = provider
    config.force_email_prop_as_creator = True  # require_email mode
    config.service_registry = None
    return config


def _webobj(state: str, code: str = "code-1") -> AWWebObj:
    return AWWebObj(
        url=f"{CALLBACK}?code={code}&state=...",
        params={"code": code, "state": state},
        body="",
        headers={},
        cookies={},
    )


def _mock_authenticator(provider_name: str, verified_emails) -> MagicMock:
    auth = MagicMock()
    auth.is_enabled.return_value = True
    auth.provider.name = provider_name
    auth.provider.mobile_deep_link = ""
    auth.exchange_code_for_token.return_value = {
        "access_token": "provider-at",
        "expires_in": 3600,
    }
    auth.provider.extract_user_info_from_token_response.return_value = None
    auth.validate_token_and_get_user_info.return_value = {"sub": "no-email-user"}
    # No identifier could be extracted (no public/verified email from provider).
    auth.get_email_from_user_info.return_value = None
    auth.provider.get_verified_emails.return_value = verified_emails
    return auth


def _run_web(provider: str, verified_emails) -> tuple[dict, AWWebObj]:
    config = _config(provider)
    state = json.dumps({"provider": provider})
    auth = _mock_authenticator(provider, verified_emails)
    webobj = _webobj(state)

    with patch(
        "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
        return_value=auth,
    ):
        handler = OAuth2CallbackHandler(webobj, config, hooks=None)
        result = handler.get()

    return result, webobj


def _run_spa(provider: str, verified_emails) -> tuple[dict, AWWebObj, MagicMock]:
    config = _config(provider)
    state = json.dumps(
        {"provider": provider, "spa_mode": True, "redirect_url": SPA_REDIRECT}
    )
    auth = _mock_authenticator(provider, verified_emails)
    webobj = _webobj(state)

    session_mgr = MagicMock()
    session_mgr.get_session.return_value = None
    session_mgr.store_session.return_value = "sess-id"

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
        handler = OAuth2CallbackHandler(webobj, config, hooks=None)
        result = handler.get()

    return result, webobj, session_mgr


class TestWebCallbackVerifiedEmailsNone:
    def test_none_verified_emails_is_502_with_template(self):
        result, webobj = _run_web("github", None)
        assert result.get("status_code") == 502
        assert webobj.response.status_code == 502
        assert webobj.response.template_values, "502 must render the error template"
        assert "error" in webobj.response.template_values

    def test_empty_list_redirects_to_email_form(self):
        result, webobj = _run_web("github", [])
        assert result.get("status") == "email_required"
        assert webobj.response.status_code == 302
        assert webobj.response.redirect is not None
        assert webobj.response.redirect.startswith("/oauth/email?session=")

    def test_nonempty_list_is_offered_via_session(self):
        with patch("actingweb.oauth_session.get_oauth2_session_manager") as get_mgr:
            session_mgr = MagicMock()
            session_mgr.store_session.return_value = "sess-id"
            get_mgr.return_value = session_mgr

            result, _webobj = _run_web("github", ["a@example.com", "b@example.com"])

        assert result.get("status") == "email_required"
        _, kwargs = session_mgr.store_session.call_args
        assert kwargs["verified_emails"] == ["a@example.com", "b@example.com"]

    def test_google_no_email_falls_through_to_form_not_502(self):
        """Google's provider has no verified-emails API (base class default
        []), so require_email with no email claim reaches the form, not a
        502 — the None-check must not fire for providers with no such API."""
        result, webobj = _run_web("google", [])
        assert result.get("status") == "email_required"
        assert webobj.response.status_code == 302


class TestSpaCallbackVerifiedEmailsNone:
    def test_none_verified_emails_redirects_with_identifier_failed(self):
        _result, webobj, session_mgr = _run_spa("github", None)
        assert webobj.response.status_code == 302
        assert webobj.response.redirect is not None
        assert "error=identifier_failed" in webobj.response.redirect
        # Must not have stored a session for a failed lookup.
        session_mgr.store_session.assert_not_called()

    def test_empty_list_redirects_with_email_required(self):
        _result, webobj, _session_mgr = _run_spa("github", [])
        assert webobj.response.status_code == 302
        assert webobj.response.redirect is not None
        assert "email_required=true" in webobj.response.redirect
        assert "session=" in webobj.response.redirect
