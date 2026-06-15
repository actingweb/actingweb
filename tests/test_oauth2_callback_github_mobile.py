"""Tests for the github-mobile ticket flow on GET /oauth/callback.

GitHub mobile routes its OAuth redirect through the HTTPS ``/oauth/callback`` so
the authorization code is exchanged server-side and the Capacitor app receives
only an opaque single-use ticket on its custom-scheme deep link. This verifies
the query-mode callback hands off a ticket (and nothing exploitable) rather than
completing a web session.
"""

import json
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.handlers.oauth2_callback import OAuth2CallbackHandler
from actingweb.oauth_state_store import MobileTicketStore

CLIENT_ID = "github-client-id"
DEEP_LINK = "io.example.app://callback"
CALLBACK = "https://test.example.com/oauth/callback"


def _make_config() -> Config:
    config = MagicMock(spec=Config)
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "github-mobile"
    config.force_email_prop_as_creator = False
    config.service_registry = None
    config.devtest = False
    config.ui = False
    config.oauth_providers = {
        "github-mobile": {
            "client_id": CLIENT_ID,
            "client_secret": "github-secret",
            "redirect_uri": CALLBACK,
            "mobile_deep_link": DEEP_LINK,
        },
    }
    config.oauth = {}

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


def _state(provider: str) -> str:
    # The query-mode callback decodes JSON state; provider drives the branch.
    return json.dumps({"provider": provider, "spa_mode": True})


def _webobj(provider: str, code: str = "github-auth-code") -> AWWebObj:
    return AWWebObj(
        url=f"{CALLBACK}?code={code}&state=...",
        params={"code": code, "state": _state(provider)},
        body="",
        headers={},
        cookies={},
    )


class TestGithubMobileCallback:
    def test_redirects_with_ticket_no_code_or_token(self) -> None:
        config = _make_config()
        handler = OAuth2CallbackHandler(_webobj("github-mobile"), config)
        result = handler.get()

        assert result.get("redirect_required") is True
        redirect = result["redirect_url"]
        assert redirect.startswith("io.example.app://callback")

        q = parse_qs(urlparse(redirect).query)
        assert "ticket" in q
        # Neither the IdP code nor any ActingWeb token may appear in the deep link.
        assert "code" not in q
        assert "access_token" not in redirect
        assert "session" not in redirect
        assert "refresh_token" not in redirect

    def test_ticket_redeemable_and_carries_code(self) -> None:
        config = _make_config()
        handler = OAuth2CallbackHandler(_webobj("github-mobile"), config)
        result = handler.get()
        ticket = parse_qs(urlparse(result["redirect_url"]).query)["ticket"][0]

        stored = MobileTicketStore(config).consume(ticket)
        assert stored is not None
        assert stored["code"] == "github-auth-code"
        assert stored["provider"] == "github-mobile"
        assert stored["redirect_uri"] == CALLBACK

    def test_ticket_carries_pkce_session_id(self) -> None:
        # Server-managed PKCE: the verifier session id must ride the ticket so the
        # deferred server-side code exchange can supply the code_verifier.
        config = _make_config()
        state = json.dumps(
            {
                "provider": "github-mobile",
                "spa_mode": True,
                "pkce_session_id": "pkce-sess-123",
            }
        )
        webobj = AWWebObj(
            url=f"{CALLBACK}?code=c&state=...",
            params={"code": "github-auth-code", "state": state},
            body="",
            headers={},
            cookies={},
        )
        result = OAuth2CallbackHandler(webobj, config).get()
        ticket = parse_qs(urlparse(result["redirect_url"]).query)["ticket"][0]

        stored = MobileTicketStore(config).consume(ticket)
        assert stored is not None
        assert stored.get("extra", {}).get("pkce_session_id") == "pkce-sess-123"
