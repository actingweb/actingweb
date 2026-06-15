"""Tests for AppleOAuth2Provider integration in actingweb.oauth2."""

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
from actingweb.config import Config
from actingweb.oauth2 import AppleOAuth2Provider, create_apple_authenticator

TEAM_ID = "TEAMID1234"
KEY_ID = "KEYID56789"
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


def _config() -> Config:
    return Config(fqdn="test.example.com", database="dynamodb")


def _prov_cfg(ec_pem: str, name: str = "apple") -> dict:
    return {
        "client_id": SERVICES_ID,
        "apple_team_id": TEAM_ID,
        "apple_key_id": KEY_ID,
        "apple_private_key_pem": ec_pem,
        "audiences": [SERVICES_ID, BUNDLE_ID],
        "_provider_name": name,
    }


def _apple_jwks(rsa_key, kid: str = APPLE_KID) -> dict:
    pub = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    pub["kid"] = kid
    pub["alg"] = "RS256"
    pub["use"] = "sig"
    return {"keys": [pub]}


def _apple_id_token(rsa_key, *, aud=SERVICES_ID, sub="000123.abc") -> str:
    now = int(time.time())
    claims = {
        "iss": "https://appleid.apple.com",
        "aud": aud,
        "sub": sub,
        "iat": now,
        "exp": now + 600,
        "email": "user@privaterelay.appleid.com",
        "email_verified": "true",
    }
    return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": APPLE_KID})


class TestAppleProviderBasics:
    def test_endpoints(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        assert p.auth_uri == AppleOAuth2Provider.AUTH_URI
        assert p.token_uri == AppleOAuth2Provider.TOKEN_URI
        assert p.revocation_uri == AppleOAuth2Provider.REVOCATION_URI
        assert p.userinfo_uri == ""

    def test_default_redirect_uri(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        assert p.redirect_uri.endswith("/oauth/callback/apple")

    def test_is_enabled(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        assert p.is_enabled() is True

    def test_not_enabled_without_key(self) -> None:
        cfg = {
            "client_id": SERVICES_ID,
            "apple_team_id": TEAM_ID,
            "apple_key_id": KEY_ID,
        }
        p = AppleOAuth2Provider(_config(), provider_config=cfg)
        assert p.is_enabled() is False

    def test_supports_refresh_and_revoke(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        assert p.supports_refresh_tokens() is True
        assert p.supports_revoke() is True

    def test_form_post_param(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        assert p.authorize_extra_params() == {"response_mode": "form_post"}

    def test_discovery_extras(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        extras = p.discovery_extras()
        assert extras["jwks_uri"] == AppleOAuth2Provider.JWKS_URI
        assert extras["id_token_signing_alg_values_supported"] == ["RS256"]


class TestAppleClientSecret:
    def test_make_client_secret_uses_cache(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        a = p.make_client_secret()
        b = p.make_client_secret()
        assert a == b
        header = jwt.get_unverified_header(a)
        assert header["alg"] == "ES256"
        assert header["kid"] == KEY_ID

    def test_distinct_creds_per_variant(self, ec_pem: str) -> None:
        AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem, "apple"))
        AppleOAuth2Provider(
            _config(), provider_config=_prov_cfg(ec_pem, "apple-mobile")
        )
        assert "apple" in oauth2_apple._APPLE_CREDS
        assert "apple-mobile" in oauth2_apple._APPLE_CREDS


class TestAppleIdTokenExtraction:
    def test_extract_user_info_validates_id_token(self, ec_pem: str, rsa_key) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        id_token = _apple_id_token(rsa_key)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _apple_jwks(rsa_key)
        with patch("actingweb.oauth2_jwks.requests.get", return_value=resp):
            claims = p.extract_user_info_from_token_response({"id_token": id_token})
        assert claims is not None
        assert claims["sub"] == "000123.abc"

    def test_extract_accepts_bundle_id_aud(self, ec_pem: str, rsa_key) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        id_token = _apple_id_token(rsa_key, aud=BUNDLE_ID)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _apple_jwks(rsa_key)
        with patch("actingweb.oauth2_jwks.requests.get", return_value=resp):
            claims = p.extract_user_info_from_token_response({"id_token": id_token})
        assert claims is not None

    def test_extract_rejects_unknown_aud(self, ec_pem: str, rsa_key) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        id_token = _apple_id_token(rsa_key, aud="com.attacker.app")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = _apple_jwks(rsa_key)
        with patch("actingweb.oauth2_jwks.requests.get", return_value=resp):
            claims = p.extract_user_info_from_token_response({"id_token": id_token})
        assert claims is None

    def test_no_id_token_returns_none(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        assert p.extract_user_info_from_token_response({}) is None


class TestAppleIdentifier:
    def test_apple_sub_identifier(self, ec_pem: str) -> None:
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        assert p.extract_identifier_from_user_info({"sub": "xyz"}) == "apple:xyz"

    def test_store_provider_identity(self, ec_pem: str) -> None:
        class _Store:
            pass

        store = _Store()
        p = AppleOAuth2Provider(_config(), provider_config=_prov_cfg(ec_pem))
        p.store_provider_identity(store, "apple:xyz")
        assert store.oauth_sub == "xyz"  # type: ignore[attr-defined]


class TestAppleFactoryAndRevoke:
    def test_factory_creates_apple(self, ec_pem: str) -> None:
        config = _config()
        config.oauth_providers = {"apple": _prov_cfg(ec_pem)}
        auth = create_apple_authenticator(config)
        assert isinstance(auth.provider, AppleOAuth2Provider)

    def test_revoke_uses_es256_client_secret(self, ec_pem: str) -> None:
        config = _config()
        config.oauth_providers = {"apple": _prov_cfg(ec_pem)}
        auth = create_apple_authenticator(config)
        captured = {}

        def _fake_post(url, data=None, headers=None, timeout=None):
            captured["data"] = data
            r = MagicMock()
            r.status_code = 200
            r.text = "{}"
            return r

        with patch("actingweb.oauth2.requests.post", side_effect=_fake_post):
            ok = auth.revoke_token("some-refresh-token")
        assert ok is True
        cs = captured["data"]["client_secret"]
        header = jwt.get_unverified_header(cs)
        assert header["alg"] == "ES256"
