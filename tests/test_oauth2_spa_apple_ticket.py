"""Tests for the apple_mobile_ticket grant on /oauth/spa/token."""

import json
import time
from collections.abc import Iterator
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
from actingweb.oauth_state_store import AppleTicketStore

SERVICES_ID = "com.example.web"
BUNDLE_ID = "com.example.app"
APPLE_KID = "applekid"


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
    config.oauth2_provider = "apple-mobile"
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
            "apple_mobile_deep_link": "io.example.app://callback",
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


def _apple_id_token(rsa_key, sub="apple-sub") -> str:
    now = int(time.time())
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": SERVICES_ID,
        "sub": sub,
        "iat": now,
        "exp": now + 600,
        "email": "apple-user@privaterelay.appleid.com",
    }
    return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": APPLE_KID})


def _handler(config, body: dict) -> OAuth2SPAHandler:
    webobj = AWWebObj(
        url="https://test.example.com/oauth/spa/token",
        params={},
        body=json.dumps(body),
        headers={"Accept": "application/json"},
        cookies={},
    )
    return OAuth2SPAHandler(webobj, config, hooks=None)


def _run(config, body, rsa_key):
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
    mock_actor.id = "actor-1"
    mock_actor.store = MagicMock()
    mock_actor.get_from_creator.return_value = True

    session_mgr = MagicMock()
    session_mgr.create_refresh_token.return_value = "aw-refresh"

    with (
        patch("actingweb.oauth2.requests.post", return_value=token_resp),
        patch("actingweb.oauth2_jwks.requests.get", return_value=jwks_resp),
        patch("actingweb.actor.Actor", return_value=mock_actor),
        patch(
            "actingweb.oauth_session.get_oauth2_session_manager",
            return_value=session_mgr,
        ),
    ):
        return _handler(config, body)._handle_token()


def _body(ticket: str) -> dict:
    return {"grant_type": "apple_mobile_ticket", "ticket": ticket}


class TestAppleTicketGrant:
    def test_valid_ticket_creates_session(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        ticket = AppleTicketStore(config).create(
            code="apple-code",
            redirect_uri="https://test.example.com/oauth/callback/apple",
            provider="apple-mobile",
        )
        result = _run(config, _body(ticket), rsa_key)
        assert result.get("success") is True
        assert result.get("access_token") == "aw-access-token"
        assert result.get("email") == "apple-user@privaterelay.appleid.com"

    def test_replayed_ticket_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        ticket = AppleTicketStore(config).create(
            code="apple-code",
            redirect_uri="https://test.example.com/oauth/callback/apple",
            provider="apple-mobile",
        )
        first = _run(config, _body(ticket), rsa_key)
        second = _run(config, _body(ticket), rsa_key)
        assert first.get("success") is True
        assert second.get("status_code") == 400

    def test_unknown_ticket_rejected(self, ec_pem, rsa_key) -> None:
        config = _make_config(ec_pem)
        result = _run(config, _body("bogus-ticket"), rsa_key)
        assert result.get("status_code") == 400

    def test_missing_ticket_rejected(self, ec_pem) -> None:
        config = _make_config(ec_pem)
        result = _handler(config, _body(""))._handle_token()
        assert result.get("status_code") == 400
