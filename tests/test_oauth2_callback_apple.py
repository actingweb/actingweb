"""Tests for OAuth2AppleCallbackHandler (POST /oauth/callback/apple)."""

import json
import time
from collections.abc import Iterator
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import RSAAlgorithm

from actingweb import oauth2_apple, oauth2_jwks
from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.handlers.oauth2_callback import OAuth2AppleCallbackHandler
from actingweb.oauth_state_store import AppleTicketStore, StateNonceStore

SERVICES_ID = "com.example.web"
BUNDLE_ID = "com.example.app"
TEAM_ID = "TEAMID1234"
KEY_ID = "KEYID56789"
APPLE_KID = "applekid"
DEEP_LINK = "io.example.app://callback"


@pytest.fixture()
def ec_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


@pytest.fixture()
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    oauth2_apple._reset_credentials()
    oauth2_jwks._reset_cache()
    yield
    oauth2_apple._reset_credentials()
    oauth2_jwks._reset_cache()


def _make_config(ec_pem: str, *, include_mobile: bool = False) -> Config:
    config = MagicMock(spec=Config)
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "apple"
    config.force_email_prop_as_creator = False
    config.service_registry = None
    config.devtest = False
    config.new_token = MagicMock(return_value="spa-access-token-xyz")

    apple_cfg = {
        "client_id": SERVICES_ID,
        "apple_team_id": TEAM_ID,
        "apple_key_id": KEY_ID,
        "apple_private_key_pem": ec_pem,
        "audiences": [SERVICES_ID, BUNDLE_ID],
        "redirect_uri": "https://test.example.com/oauth/callback/apple",
    }
    providers = {"apple": dict(apple_cfg)}
    if include_mobile:
        mobile = dict(apple_cfg)
        mobile["apple_mobile_deep_link"] = DEEP_LINK
        providers["apple-mobile"] = mobile
    config.oauth_providers = providers
    config.oauth = dict(apple_cfg)

    # In-memory attribute backend (mirrors test_oauth_session pattern).
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
            key = f"{actor_id}:{bucket}"
            self.storage.setdefault(key, {})[name] = {"data": data}
            return True

        def delete_attr(self, actor_id, bucket, name):  # type: ignore
            key = f"{actor_id}:{bucket}"
            if key in self.storage and name in self.storage[key]:
                del self.storage[key][name]
                return True
            return False

        def delete_attr_conditional(self, actor_id, bucket, name):  # type: ignore
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


def _apple_jwks(rsa_key) -> dict:
    pub = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    pub["kid"] = APPLE_KID
    pub["alg"] = "RS256"
    pub["use"] = "sig"
    return {"keys": [pub]}


def _apple_id_token(rsa_key, *, aud=SERVICES_ID, sub="000777.apple") -> str:
    now = int(time.time())
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": aud,
        "sub": sub,
        "iat": now,
        "exp": now + 600,
        "email": "abc@privaterelay.appleid.com",
        "email_verified": "true",
    }
    return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": APPLE_KID})


def _webobj(form: dict) -> AWWebObj:
    return AWWebObj(
        url="https://test.example.com/oauth/callback/apple",
        params={},
        body=urlencode(form),
        headers={},
        cookies={},
    )


def _spa_payload() -> dict:
    return {
        "spa_mode": True,
        "provider": "apple",
        "redirect_url": "https://test.example.com/spa/callback",
        "return_path": "/app",
        "token_delivery": "json",
        "timestamp": int(time.time()),
    }


class TestAppleCallbackErrors:
    def test_missing_state_returns_400(self, ec_pem: str) -> None:
        config = _make_config(ec_pem)
        handler = OAuth2AppleCallbackHandler(_webobj({"code": "x"}), config)
        result = handler.post()
        assert result.get("status_code") == 400

    def test_invalid_state_nonce_returns_400(self, ec_pem: str) -> None:
        config = _make_config(ec_pem)
        handler = OAuth2AppleCallbackHandler(
            _webobj({"state": "bogus-nonce", "code": "x"}), config
        )
        result = handler.post()
        assert result.get("status_code") == 400
        assert "nonce" in result.get("message", "").lower()

    def test_replayed_state_nonce_returns_400(self, ec_pem: str) -> None:
        config = _make_config(ec_pem)
        nonce = StateNonceStore(config).create(_spa_payload())
        # First consume (directly) to simulate prior use.
        StateNonceStore(config).consume(nonce)
        handler = OAuth2AppleCallbackHandler(
            _webobj({"state": nonce, "code": "x"}), config
        )
        result = handler.post()
        assert result.get("status_code") == 400

    def test_error_param_returns_400(self, ec_pem: str) -> None:
        config = _make_config(ec_pem)
        handler = OAuth2AppleCallbackHandler(
            _webobj({"error": "user_cancelled_authorize"}), config
        )
        result = handler.post()
        assert result.get("status_code") == 400

    def test_apple_missing_code_returns_400(self, ec_pem: str) -> None:
        config = _make_config(ec_pem)
        nonce = StateNonceStore(config).create(_spa_payload())
        handler = OAuth2AppleCallbackHandler(_webobj({"state": nonce}), config)
        result = handler.post()
        assert result.get("status_code") == 400


class TestAppleMobileTicket:
    def test_mobile_callback_redirects_with_ticket_no_token(self, ec_pem: str) -> None:
        config = _make_config(ec_pem, include_mobile=True)
        payload = {"provider": "apple-mobile", "spa_mode": True}
        nonce = StateNonceStore(config).create(payload)

        webobj = _webobj({"state": nonce, "code": "apple-auth-code"})
        handler = OAuth2AppleCallbackHandler(webobj, config)
        result = handler.post()

        assert result.get("redirect_required") is True
        redirect = result["redirect_url"]
        assert redirect.startswith("io.example.app://callback")
        q = parse_qs(urlparse(redirect).query)
        assert "ticket" in q
        # No ActingWeb token of any kind in the deep link.
        assert "access_token" not in redirect
        assert "session" not in redirect
        assert "refresh_token" not in redirect

        # The ticket resolves to the stored IdP code + Apple redirect_uri.
        ticket = q["ticket"][0]
        stored = AppleTicketStore(config).consume(ticket)
        assert stored is not None
        assert stored["code"] == "apple-auth-code"
        assert stored["redirect_uri"].endswith("/oauth/callback/apple")
        assert stored["provider"] == "apple-mobile"


class TestAppleWebFlow:
    def _run(self, config, rsa_key, form, hooks=None):
        webobj = _webobj(form)
        handler = OAuth2AppleCallbackHandler(webobj, config, hooks=hooks)

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_body = {
            "access_token": "apple-access",
            "refresh_token": "apple-refresh",
            "id_token": _apple_id_token(rsa_key),
            "expires_in": 3600,
        }
        token_resp.json.return_value = token_body
        token_resp.text = json.dumps(token_body)

        jwks_resp = MagicMock()
        jwks_resp.status_code = 200
        jwks_resp.json.return_value = _apple_jwks(rsa_key)

        mock_actor = MagicMock()
        mock_actor.id = "actor-apple-1"
        mock_actor.store = MagicMock()
        mock_actor.get_from_creator.return_value = True

        session_mgr = MagicMock()
        session_mgr.get_session.return_value = None
        session_mgr.create_refresh_token.return_value = "spa-refresh"
        session_mgr.store_session.return_value = "pending-session-id"

        with (
            patch("actingweb.oauth2.requests.post", return_value=token_resp),
            patch("actingweb.oauth2_jwks.requests.get", return_value=jwks_resp),
            patch("actingweb.actor.Actor", return_value=mock_actor),
            patch(
                "actingweb.oauth_session.get_oauth2_session_manager",
                return_value=session_mgr,
            ),
        ):
            result = handler.post()
        return result, webobj, mock_actor

    def test_web_spa_flow_creates_session_and_redirects(
        self, ec_pem: str, rsa_key
    ) -> None:
        config = _make_config(ec_pem)
        nonce = StateNonceStore(config).create(_spa_payload())
        result, webobj, _ = self._run(
            config, rsa_key, {"state": nonce, "code": "apple-code"}
        )
        assert result.get("redirect_required") is True
        assert webobj.response.redirect is not None
        assert "test.example.com/spa/callback" in webobj.response.redirect
        assert "session=" in webobj.response.redirect

    def test_first_sign_in_user_payload_normalized_in_hook(
        self, ec_pem: str, rsa_key
    ) -> None:
        config = _make_config(ec_pem)
        nonce = StateNonceStore(config).create(_spa_payload())
        captured = {}

        hooks = MagicMock()

        def _exec(hook_name, actor_interface, **kwargs):
            captured["hook"] = hook_name
            captured["user_info"] = kwargs.get("user_info")
            return True

        hooks.execute_lifecycle_hooks.side_effect = _exec

        user_json = json.dumps(
            {"name": {"firstName": "Jane", "lastName": "Doe"}, "email": "jane@x.com"}
        )
        result, _, _ = self._run(
            config,
            rsa_key,
            {"state": nonce, "code": "apple-code", "user": user_json},
            hooks=hooks,
        )
        assert result.get("redirect_required") is True
        assert captured["hook"] == "oauth_success"
        info = captured["user_info"]
        assert info["given_name"] == "Jane"
        assert info["family_name"] == "Doe"
        assert info["display_name"] == "Jane Doe"
