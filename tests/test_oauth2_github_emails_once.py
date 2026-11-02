"""GitHub's ``/user/emails`` is requested once per sign-in (3.16).

The callback's email-required path asked GitHub twice for the same token:
``get_primary_email`` inside ``get_email_from_user_info``, then
``get_verified_emails``, each with its own ``(5, 10)`` timeout. Both now read
one memoised answer on the per-request provider, a failure included.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler
from actingweb.oauth2 import GitHubOAuth2Provider, OAuth2Authenticator

CALLBACK = "https://test.example.com/oauth/callback"
SPA_REDIRECT = "https://test.example.com/spa/callback"


def _config() -> MagicMock:
    config = MagicMock()
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth = {"client_id": "cid", "client_secret": "secret"}
    config.oauth2_provider = "github"
    config.force_email_prop_as_creator = True  # require_email
    config.service_registry = None
    return config


def _response(status: int, body: Any) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    return response


ENTRIES = [
    {"email": "Alt@example.com", "primary": False, "verified": True},
    {"email": "Main@example.com", "primary": True, "verified": True},
]


class TestProviderMemo:
    def _provider(self) -> GitHubOAuth2Provider:
        return GitHubOAuth2Provider(_config())

    def test_primary_then_verified_is_one_request(self) -> None:
        provider = self._provider()
        with patch(
            "actingweb.oauth2.requests.get", return_value=_response(200, ENTRIES)
        ) as get:
            assert provider.get_primary_email("tok") == "Main@example.com"
            assert provider.get_verified_emails("tok") == [
                "alt@example.com",
                "main@example.com",
            ]
        assert get.call_count == 1

    def test_a_failure_is_reused(self) -> None:
        provider = self._provider()
        with patch(
            "actingweb.oauth2.requests.get", side_effect=TimeoutError("slow")
        ) as get:
            assert provider.get_primary_email("tok") is None
            assert provider.get_verified_emails("tok") is None
        assert get.call_count == 1

    def test_another_token_asks_again(self) -> None:
        provider = self._provider()
        with patch(
            "actingweb.oauth2.requests.get", return_value=_response(200, ENTRIES)
        ) as get:
            provider.get_primary_email("tok-1")
            provider.get_primary_email("tok-2")
        assert get.call_count == 2

    def test_an_unverified_primary_is_skipped(self) -> None:
        provider = self._provider()
        entries = [
            {"email": "trap@example.com", "primary": True, "verified": False},
            {"email": "real@example.com", "primary": False, "verified": True},
        ]
        with patch(
            "actingweb.oauth2.requests.get", return_value=_response(200, entries)
        ):
            assert provider.get_primary_email("tok") == "real@example.com"
            assert provider.get_verified_emails("tok") == ["real@example.com"]


def _authenticator() -> OAuth2Authenticator:
    config = _config()
    auth = OAuth2Authenticator(config, GitHubOAuth2Provider(config))
    auth.is_enabled = MagicMock(return_value=True)  # type: ignore[method-assign]
    auth.exchange_code_for_token = MagicMock(  # type: ignore[method-assign]
        return_value={"access_token": "provider-at", "expires_in": 3600}
    )
    return auth


def _run(user_info: dict[str, Any], get: MagicMock, *, spa: bool) -> AWWebObj:
    config = _config()
    state_data: dict[str, Any] = {"provider": "github"}
    if spa:
        state_data.update({"spa_mode": True, "redirect_url": SPA_REDIRECT})
    webobj = AWWebObj(
        url=f"{CALLBACK}?code=c&state=...",
        params={"code": "c", "state": json.dumps(state_data)},
        body="",
        headers={},
        cookies={},
    )
    auth = _authenticator()
    auth.validate_token_and_get_user_info = MagicMock(  # type: ignore[method-assign]
        return_value=user_info
    )
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
        patch("actingweb.oauth2.requests.get", get),
    ):
        OAuth2CallbackHandler(webobj, config, hooks=None).get()
    return webobj


@pytest.mark.parametrize("spa", [False, True])
class TestCallbackRequestsOnce:
    def test_a_failed_fetch_is_one_request_then_the_error(self, spa: bool) -> None:
        get = MagicMock(return_value=_response(404, {"message": "Not Found"}))
        webobj = _run({"id": 42, "login": "someone"}, get, spa=spa)
        assert get.call_count == 1
        if spa:
            assert webobj.response.redirect is not None
            assert "error=identifier_failed" in webobj.response.redirect
        else:
            assert webobj.response.status_code == 502

    def test_a_public_email_asks_github_nothing(self, spa: bool) -> None:
        get = MagicMock(return_value=_response(200, ENTRIES))
        _run({"id": 42, "login": "someone", "email": "pub@example.com"}, get, spa=spa)
        assert get.call_count == 0


class TestMalformedAndEmptyEntries:
    def test_entries_that_are_not_objects_are_a_failure(self) -> None:
        provider = GitHubOAuth2Provider(_config())
        with patch(
            "actingweb.oauth2.requests.get", return_value=_response(200, ["a@x.com"])
        ):
            assert provider.get_verified_emails("tok") is None
            assert provider.get_primary_email("tok") is None

    def test_an_entry_without_an_address_is_skipped(self) -> None:
        provider = GitHubOAuth2Provider(_config())
        entries = [
            {"email": "", "primary": True, "verified": True},
            {"email": "next@example.com", "primary": False, "verified": True},
        ]
        with patch(
            "actingweb.oauth2.requests.get", return_value=_response(200, entries)
        ):
            assert provider.get_primary_email("tok") == "next@example.com"

    def test_the_authenticator_shims_share_one_request(self) -> None:
        config = _config()
        auth = OAuth2Authenticator(config, GitHubOAuth2Provider(config))
        with patch(
            "actingweb.oauth2.requests.get", return_value=_response(200, ENTRIES)
        ) as get:
            assert auth._get_github_primary_email("tok") == "Main@example.com"  # pyright: ignore[reportPrivateUsage]
            assert auth.get_github_verified_emails("tok")
        assert get.call_count == 1


def test_google_asks_no_emails_endpoint() -> None:
    from actingweb.oauth2 import GoogleOAuth2Provider

    provider = GoogleOAuth2Provider(_config())
    with patch("actingweb.oauth2.requests.get") as get:
        assert provider.get_primary_email("tok") is None
        assert provider.get_verified_emails("tok") == []
    get.assert_not_called()
