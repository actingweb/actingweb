"""Regression test: OAuth2CallbackHandler normalizes provider user_info before
firing the oauth_success hook, on BOTH code paths.

``OAuth2CallbackHandler.get`` builds user_info and fires oauth_success in two
places:

- the plain web login path (``get`` itself), and
- the spa_mode browser-redirect path (``_process_spa_oauth_and_create_session``).

GitHub's userinfo carries ``name``, not ``display_name``; without normalization
the hook found no display_name and the GitHub display name was silently dropped.
These tests pin the normalization on both paths so neither can regress.
"""

import json
from unittest.mock import MagicMock, patch

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler

CALLBACK = "https://test.example.com/oauth/callback"
SPA_REDIRECT = "https://test.example.com/spa/callback"  # same FQDN → safe redirect


def _config() -> MagicMock:
    config = MagicMock()
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "github"
    config.force_email_prop_as_creator = False
    config.service_registry = None
    return config


def _webobj(state: str, code: str = "gh-code") -> AWWebObj:
    # No Accept: application/json header → browser-navigation branch.
    return AWWebObj(
        url=f"{CALLBACK}?code={code}&state=...",
        params={"code": code, "state": state},
        body="",
        headers={},
        cookies={},
    )


def _mock_authenticator(raw_user_info: dict) -> MagicMock:
    auth = MagicMock()
    auth.is_enabled.return_value = True
    auth.provider.name = "github"
    auth.provider.mobile_deep_link = ""  # not a -mobile provider
    auth.exchange_code_for_token.return_value = {"access_token": "gh-at", "expires_in": 3600}
    # GitHub fetches userinfo from the endpoint (no id_token in the token response).
    auth.provider.extract_user_info_from_token_response.return_value = None
    auth.validate_token_and_get_user_info.return_value = raw_user_info
    auth.get_email_from_user_info.return_value = "greger@example.com"
    actor = MagicMock()
    actor.id = "actor-gh-1"
    actor.creator = "greger@example.com"
    actor.store = MagicMock()
    auth.lookup_or_create_actor_by_identifier.return_value = actor
    return auth


def _capture_hooks() -> tuple[MagicMock, dict]:
    captured: dict = {}
    hooks = MagicMock()

    def _exec(hook_name, _actor_interface, **kwargs):
        if hook_name == "oauth_success":
            captured["user_info"] = kwargs.get("user_info")
        return True

    hooks.execute_lifecycle_hooks.side_effect = _exec
    return hooks, captured


def _run_spa(raw_user_info: dict) -> dict:
    """Drive the SPA browser-redirect path (_process_spa_oauth_and_create_session)."""
    config = _config()
    state = json.dumps(
        {"provider": "github", "spa_mode": True, "redirect_url": SPA_REDIRECT}
    )
    hooks, captured = _capture_hooks()

    session_mgr = MagicMock()
    session_mgr.get_session.return_value = None
    session_mgr.store_session.return_value = "sess-id"

    auth = _mock_authenticator(raw_user_info)

    with (
        patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
            return_value=auth,
        ),
        patch(
            "actingweb.oauth_session.get_oauth2_session_manager",
            return_value=session_mgr,
        ),
        patch(
            "actingweb.interface.actor_interface.ActorInterface",
            return_value=MagicMock(),
        ),
    ):
        OAuth2CallbackHandler(_webobj(state), config, hooks=hooks).get()

    return captured


def _run_web(raw_user_info: dict) -> dict:
    """Drive the plain web-login path (get() itself, no spa_mode)."""
    config = _config()
    state = json.dumps({"provider": "github"})  # no spa_mode → plain web path
    hooks, captured = _capture_hooks()

    auth = _mock_authenticator(raw_user_info)

    # The plain path does an existence check via actingweb.actor.Actor before
    # lookup/create; return a truthy existing actor so is_new_actor is False.
    existing_actor = MagicMock()
    existing_actor.get_from_creator.return_value = True

    with (
        patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
            return_value=auth,
        ),
        patch("actingweb.actor.Actor", return_value=existing_actor),
        patch(
            "actingweb.interface.actor_interface.ActorInterface",
            return_value=MagicMock(),
        ),
    ):
        OAuth2CallbackHandler(_webobj(state), config, hooks=hooks).get()

    return captured


class TestGithubSpaCallbackNormalization:
    def test_github_name_becomes_display_name_in_hook(self):
        captured = _run_spa(
            {"name": "Greger Wedel", "login": "gregertw", "email": "greger@example.com"}
        )
        assert captured.get("user_info") is not None, "oauth_success was not fired"
        assert captured["user_info"]["display_name"] == "Greger Wedel"

    def test_github_login_used_when_name_missing(self):
        captured = _run_spa(
            {"name": None, "login": "gregertw", "email": "greger@example.com"}
        )
        assert captured["user_info"]["display_name"] == "gregertw"


class TestGithubWebCallbackNormalization:
    def test_github_name_becomes_display_name_in_hook(self):
        captured = _run_web(
            {"name": "Greger Wedel", "login": "gregertw", "email": "greger@example.com"}
        )
        assert captured.get("user_info") is not None, "oauth_success was not fired"
        assert captured["user_info"]["display_name"] == "Greger Wedel"

    def test_github_login_used_when_name_missing(self):
        captured = _run_web(
            {"name": None, "login": "gregertw", "email": "greger@example.com"}
        )
        assert captured["user_info"]["display_name"] == "gregertw"
