"""Regression tests: cancelled-consent (provider ``error=...``) is bounced back
to the SPA callback instead of rendering a backend error page.

When a user cancels OAuth consent the provider redirects back with
``error=access_denied`` and no authorization code. For SPA logins the callback
must 302 the browser back to the app's callback URL with the ``error`` /
``error_description`` query params (so the SPA can show a friendly message),
while non-SPA logins keep returning a 400. These tests pin both the GET callback
(Google/GitHub) and Apple's ``response_mode=form_post`` POST callback.
"""

import json
import time
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlparse

from actingweb.aw_web_request import AWWebObj
from actingweb.handlers.oauth2_callback import (
    OAuth2AppleCallbackHandler,
    OAuth2CallbackHandler,
)
from actingweb.oauth_state_store import StateNonceStore

CALLBACK = "https://test.example.com/oauth/callback"
SPA_REDIRECT = "https://test.example.com/spa/callback"  # same FQDN → safe redirect


def _config() -> MagicMock:
    config = MagicMock()
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "github"
    config.service_registry = None
    config.oauth_providers = {}
    config.spa_redirect_origins = []
    return config


def _webobj(state: str, error: str = "access_denied") -> AWWebObj:
    params = {"error": error, "state": state}
    return AWWebObj(
        url=f"{CALLBACK}?{urlencode(params)}",
        params=params,
        body="",
        headers={},
        cookies={},
    )


def _enabled_authenticator() -> MagicMock:
    auth = MagicMock()
    auth.is_enabled.return_value = True
    return auth


def _redirect(webobj: AWWebObj) -> str:
    return str(webobj.response.redirect or "")


def _run_get(state: str, error: str = "access_denied") -> tuple[dict, AWWebObj]:
    config = _config()
    webobj = _webobj(state, error)
    with patch(
        "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
        return_value=_enabled_authenticator(),
    ):
        result = OAuth2CallbackHandler(webobj, config).get()
    return result, webobj


class TestSpaCallbackErrorRedirect:
    def test_spa_error_redirects_to_callback_with_error_params(self) -> None:
        state = json.dumps(
            {"provider": "github", "spa_mode": True, "redirect_url": SPA_REDIRECT}
        )
        result, webobj = _run_get(state)

        assert result.get("redirect_required") is True
        assert webobj.response.status_code == 302
        parsed = urlparse(_redirect(webobj))
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == SPA_REDIRECT
        q = parse_qs(parsed.query)
        assert q["error"] == ["access_denied"]

    def test_spa_error_includes_error_description(self) -> None:
        state = json.dumps(
            {"provider": "github", "spa_mode": True, "redirect_url": SPA_REDIRECT}
        )
        config = _config()
        params = {
            "error": "access_denied",
            "error_description": "User cancelled",
            "state": state,
        }
        webobj = AWWebObj(
            url=f"{CALLBACK}?{urlencode(params)}",
            params=params,
            body="",
            headers={},
            cookies={},
        )
        with patch(
            "actingweb.handlers.oauth2_callback.create_oauth2_authenticator",
            return_value=_enabled_authenticator(),
        ):
            OAuth2CallbackHandler(webobj, config).get()
        q = parse_qs(urlparse(_redirect(webobj)).query)
        assert q["error_description"] == ["User cancelled"]

    def test_spa_error_preserves_existing_query_params(self) -> None:
        redirect_with_query = f"{SPA_REDIRECT}?tenant=acme&trace=xyz"
        state = json.dumps(
            {
                "provider": "github",
                "spa_mode": True,
                "redirect_url": redirect_with_query,
            }
        )
        _, webobj = _run_get(state)
        q = parse_qs(urlparse(_redirect(webobj)).query)
        assert q["tenant"] == ["acme"]
        assert q["trace"] == ["xyz"]
        assert q["error"] == ["access_denied"]

    def test_spa_error_untrusted_redirect_falls_back_to_root(self) -> None:
        state = json.dumps(
            {
                "provider": "github",
                "spa_mode": True,
                "redirect_url": "https://evil.example.org/steal",
            }
        )
        _, webobj = _run_get(state)
        parsed = urlparse(_redirect(webobj))
        assert parsed.netloc == "test.example.com"
        assert parsed.path == "/"

    def test_spa_error_missing_redirect_falls_back_to_root(self) -> None:
        state = json.dumps({"provider": "github", "spa_mode": True})
        _, webobj = _run_get(state)
        parsed = urlparse(_redirect(webobj))
        assert parsed.netloc == "test.example.com"
        assert parsed.path == "/"

    def test_non_spa_error_returns_400(self) -> None:
        state = json.dumps({"provider": "github"})  # no spa_mode
        result, _ = _run_get(state)
        assert result.get("status_code") == 400
        assert result.get("redirect_required") is not True


def _apple_config() -> MagicMock:
    config = MagicMock()
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "apple"
    config.service_registry = None
    config.oauth_providers = {}
    config.spa_redirect_origins = []

    storage: dict = {}

    class MockDbAttribute:
        def __init__(self):  # type: ignore
            self.storage = storage

        def get_bucket(self, actor_id, bucket):  # type: ignore
            return self.storage.get(f"{actor_id}:{bucket}", {})

        def get_attr(self, actor_id, bucket, name):  # type: ignore
            return self.storage.get(f"{actor_id}:{bucket}", {}).get(name)

        def set_attr(
            self, actor_id, bucket, name, data, timestamp=None, ttl_seconds=None
        ):  # type: ignore
            self.storage.setdefault(f"{actor_id}:{bucket}", {})[name] = {"data": data}
            return True

        def delete_attr(self, actor_id, bucket, name):  # type: ignore
            key = f"{actor_id}:{bucket}"
            if key in self.storage and name in self.storage[key]:
                del self.storage[key][name]
                return True
            return False

        def delete_bucket(self, actor_id, bucket):  # type: ignore
            return self.storage.pop(f"{actor_id}:{bucket}", None) is not None

    db_mod = MagicMock()
    db_mod.DbAttribute = MockDbAttribute
    config.DbAttribute = db_mod
    return config


def _apple_webobj(form: dict) -> AWWebObj:
    return AWWebObj(
        url="https://test.example.com/oauth/callback/apple",
        params={},
        body=urlencode(form),
        headers={},
        cookies={},
    )


class TestAppleSpaCallbackErrorRedirect:
    def test_apple_spa_error_redirects_to_callback(self) -> None:
        config = _apple_config()
        payload = {
            "spa_mode": True,
            "provider": "apple",
            "redirect_url": SPA_REDIRECT,
            "timestamp": int(time.time()),
        }
        nonce = StateNonceStore(config).create(payload)
        webobj = _apple_webobj(
            {"error": "user_cancelled_authorize", "state": nonce}
        )
        result = OAuth2AppleCallbackHandler(webobj, config).post()

        assert result.get("redirect_required") is True
        parsed = urlparse(_redirect(webobj))
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == SPA_REDIRECT
        q = parse_qs(parsed.query)
        assert q["error"] == ["user_cancelled_authorize"]

    def test_apple_non_spa_error_returns_400(self) -> None:
        config = _apple_config()
        payload = {"provider": "apple", "timestamp": int(time.time())}  # no spa_mode
        nonce = StateNonceStore(config).create(payload)
        webobj = _apple_webobj({"error": "user_cancelled_authorize", "state": nonce})
        result = OAuth2AppleCallbackHandler(webobj, config).post()
        assert result.get("status_code") == 400
