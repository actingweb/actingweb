"""Tests for the JWT-bearer grant on /oauth/spa/token (native OIDC sign-in)."""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import RSAAlgorithm

from actingweb import oauth2_apple, oauth2_jwks
from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.handlers.oauth2_spa import OAuth2SPAHandler

SERVICES_ID = "com.example.web"
BUNDLE_ID = "com.example.app"
GOOGLE_IOS = "111-ios.apps.googleusercontent.com"
APPLE_KID = "applekid"
GOOGLE_KID = "googlekid"


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


def _make_config(ec_pem: str) -> Config:
    config = MagicMock(spec=Config)
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "apple"
    config.force_email_prop_as_creator = False
    config.service_registry = None
    config.devtest = False
    config.new_token = MagicMock(return_value="aw-access-token")
    config.oauth_providers = {
        "apple-mobile": {
            "client_id": SERVICES_ID,
            "apple_team_id": "TEAM",
            "apple_key_id": "KEY",
            "apple_private_key_pem": ec_pem,
            "audiences": [SERVICES_ID, BUNDLE_ID],
            "redirect_uri": "https://test.example.com/oauth/callback/apple",
        },
        "google-native": {
            "client_id": GOOGLE_IOS,
            "client_secret": "",
            "audiences": [GOOGLE_IOS],
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


def _jwks(rsa_key, kid: str) -> dict:
    pub = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    pub["kid"] = kid
    pub["alg"] = "RS256"
    pub["use"] = "sig"
    return {"keys": [pub]}


def _apple_token(
    rsa_key, *, aud=SERVICES_ID, sub="apple-sub-1", nonce="n", **over
) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": aud,
        "sub": sub,
        "iat": now,
        "exp": now + 600,
        "email": "apple-user@privaterelay.appleid.com",
        "nonce": nonce,
    }
    claims.update(over)
    return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": APPLE_KID})


def _google_token(
    rsa_key, *, aud=GOOGLE_IOS, sub="google-sub-1", nonce="n", **over
) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": aud,
        "sub": sub,
        "iat": now,
        "exp": now + 600,
        "email": "google-user@gmail.com",
        "nonce": nonce,
    }
    claims.update(over)
    return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": GOOGLE_KID})


def _handler(config, body: dict, hooks=None) -> OAuth2SPAHandler:
    webobj = AWWebObj(
        url="https://test.example.com/oauth/spa/token",
        params={},
        body=json.dumps(body),
        headers={"Accept": "application/json"},
        cookies={},
    )
    return OAuth2SPAHandler(webobj, config, hooks=hooks)


@contextmanager
def _mocked_backend(jwks: dict, captured: dict | None = None):
    jwks_resp = MagicMock()
    jwks_resp.status_code = 200
    jwks_resp.json.return_value = jwks

    mock_actor = MagicMock()
    mock_actor.id = "actor-1"
    mock_actor.store = MagicMock()
    mock_actor.get_from_creator.return_value = True

    session_mgr = MagicMock()
    session_mgr.create_refresh_token.return_value = "aw-refresh"

    with (
        patch("actingweb.oauth2_jwks.requests.get", return_value=jwks_resp),
        patch("actingweb.actor.Actor", return_value=mock_actor),
        patch(
            "actingweb.oauth_session.get_oauth2_session_manager",
            return_value=session_mgr,
        ),
    ):
        if captured is not None:
            captured["actor"] = mock_actor
        yield


def _jwt_bearer_body(provider: str, assertion: str, nonce: str = "n") -> dict:
    return {
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "provider": provider,
        "assertion": assertion,
        "nonce": nonce,
    }


class TestJwtBearerSuccess:
    def test_apple_id_token_creates_session(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        token = _apple_token(rsa_key, nonce="nonce-a")
        handler = _handler(config, _jwt_bearer_body("apple-mobile", token, "nonce-a"))
        with _mocked_backend(_jwks(rsa_key, APPLE_KID)):
            result = handler._handle_token()
        assert result.get("success") is True
        assert result.get("access_token") == "aw-access-token"
        assert result.get("email") == "apple-user@privaterelay.appleid.com"

    def test_google_id_token_creates_session(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        token = _google_token(rsa_key, nonce="nonce-g")
        handler = _handler(config, _jwt_bearer_body("google-native", token, "nonce-g"))
        with _mocked_backend(_jwks(rsa_key, GOOGLE_KID)):
            result = handler._handle_token()
        assert result.get("success") is True
        assert result.get("email") == "google-user@gmail.com"

    def test_apple_identifier_uses_sub_when_no_email(self, ec_pem) -> None:
        # When the id_token carries no email, the actor identifier is apple:{sub}.
        from actingweb.oauth2 import create_oauth2_authenticator

        config = _make_config(ec_pem)
        auth = create_oauth2_authenticator(config, "apple-mobile")
        assert auth.get_email_from_user_info({"sub": "sub-xyz"}) == "apple:sub-xyz"

    def test_google_identifier_uses_sub_when_no_email(self, ec_pem) -> None:
        from actingweb.oauth2 import create_oauth2_authenticator

        config = _make_config(ec_pem)
        auth = create_oauth2_authenticator(config, "google-native")
        assert auth.get_email_from_user_info({"sub": "g-123"}) == "google:g-123"


class TestJwtBearerRejections:
    def test_provider_iss_mismatch_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        # A Google id_token submitted as apple-mobile must be rejected.
        google = _google_token(rsa_key, nonce="n")
        handler = _handler(config, _jwt_bearer_body("apple-mobile", google))
        with _mocked_backend(_jwks(rsa_key, APPLE_KID)):
            result = handler._handle_token()
        assert result.get("status_code") == 400
        assert "issuer" in result.get("message", "").lower()

    def test_replay_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        token = _apple_token(rsa_key, nonce="n", sub="replay-sub")
        with _mocked_backend(_jwks(rsa_key, APPLE_KID)):
            first = _handler(
                config, _jwt_bearer_body("apple-mobile", token)
            )._handle_token()
            second = _handler(
                config, _jwt_bearer_body("apple-mobile", token)
            )._handle_token()
        assert first.get("success") is True
        assert second.get("status_code") == 400
        assert "replay" in second.get("message", "").lower()

    def test_missing_nonce_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        token = _apple_token(rsa_key)
        body = _jwt_bearer_body("apple-mobile", token)
        del body["nonce"]
        handler = _handler(config, body)
        with _mocked_backend(_jwks(rsa_key, APPLE_KID)):
            result = handler._handle_token()
        assert result.get("status_code") == 400
        assert "nonce" in result.get("message", "").lower()

    def test_nonce_mismatch_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        token = _apple_token(rsa_key, nonce="expected")
        handler = _handler(config, _jwt_bearer_body("apple-mobile", token, "different"))
        with _mocked_backend(_jwks(rsa_key, APPLE_KID)):
            result = handler._handle_token()
        assert result.get("status_code") == 400

    def test_expired_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        now = int(time.time())
        token = _apple_token(rsa_key, iat=now - 1200, exp=now - 600)
        handler = _handler(config, _jwt_bearer_body("apple-mobile", token))
        with _mocked_backend(_jwks(rsa_key, APPLE_KID)):
            result = handler._handle_token()
        assert result.get("status_code") == 400

    def test_wrong_aud_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        token = _apple_token(rsa_key, aud="com.attacker.app")
        handler = _handler(config, _jwt_bearer_body("apple-mobile", token))
        with _mocked_backend(_jwks(rsa_key, APPLE_KID)):
            result = handler._handle_token()
        assert result.get("status_code") == 400

    def test_missing_assertion_rejected(self, ec_pem) -> None:
        config = _make_config(ec_pem)
        handler = _handler(config, _jwt_bearer_body("apple-mobile", ""))
        result = handler._handle_token()
        assert result.get("status_code") == 400

    def test_unknown_provider_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        token = _apple_token(rsa_key)
        handler = _handler(config, _jwt_bearer_body("facebook", token))
        result = handler._handle_token()
        assert result.get("status_code") == 400
