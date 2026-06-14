"""Tests for JWKSIdTokenValidator (actingweb.oauth2_id_token)."""

import json
import time
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from actingweb import oauth2_jwks
from actingweb.oauth2_id_token import JWKSIdTokenValidator

ISS = "https://appleid.apple.com"
AUD = "com.example.web"
JWKS_URI = "https://appleid.apple.com/auth/keys"
KID = "testkid1"


@pytest.fixture()
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    oauth2_jwks._reset_cache()
    yield
    oauth2_jwks._reset_cache()


def _jwks_for(private_key, kid: str = KID) -> dict:
    pub_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    pub_jwk["kid"] = kid
    pub_jwk["alg"] = "RS256"
    pub_jwk["use"] = "sig"
    return {"keys": [pub_jwk]}


def _sign(private_key, claims: dict, kid: str = KID) -> str:
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def _claims(**overrides) -> dict:
    now = int(time.time())
    base = {
        "iss": ISS,
        "aud": AUD,
        "sub": "001234.abcd",
        "iat": now,
        "exp": now + 600,
    }
    base.update(overrides)
    return base


def _patch_jwks(private_key, kid: str = KID):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _jwks_for(private_key, kid)
    return patch("actingweb.oauth2_jwks.requests.get", return_value=resp)


def _validator(
    audiences: list[str] | None = None,
    expected_iss: str | tuple[str, ...] = ISS,
) -> JWKSIdTokenValidator:
    return JWKSIdTokenValidator(
        jwks_uri=JWKS_URI,
        expected_iss=expected_iss,
        audiences=audiences if audiences is not None else [AUD],
    )


class TestValidate:
    def test_valid_token(self, keypair) -> None:
        token = _sign(keypair, _claims())
        with _patch_jwks(keypair):
            claims = _validator().validate(token)
        assert claims is not None
        assert claims["sub"] == "001234.abcd"

    def test_wrong_iss(self, keypair) -> None:
        token = _sign(keypair, _claims(iss="https://evil.example.com"))
        with _patch_jwks(keypair):
            assert _validator().validate(token) is None

    def test_iss_tuple_accepts_alternate(self, keypair) -> None:
        token = _sign(keypair, _claims(iss="https://account.apple.com"))
        with _patch_jwks(keypair):
            v = _validator(
                expected_iss=("https://appleid.apple.com", "https://account.apple.com")
            )
            assert v.validate(token) is not None

    def test_wrong_aud(self, keypair) -> None:
        token = _sign(keypair, _claims(aud="com.someone.else"))
        with _patch_jwks(keypair):
            assert _validator().validate(token) is None

    def test_aud_list_accepts_any(self, keypair) -> None:
        token = _sign(keypair, _claims(aud=["com.example.ios", AUD]))
        with _patch_jwks(keypair):
            assert _validator().validate(token) is not None

    def test_expired(self, keypair) -> None:
        now = int(time.time())
        token = _sign(keypair, _claims(iat=now - 1200, exp=now - 600))
        with _patch_jwks(keypair):
            assert _validator().validate(token) is None

    def test_nonce_match(self, keypair) -> None:
        token = _sign(keypair, _claims(nonce="abc123"))
        with _patch_jwks(keypair):
            assert _validator().validate(token, nonce="abc123") is not None

    def test_nonce_mismatch(self, keypair) -> None:
        token = _sign(keypair, _claims(nonce="abc123"))
        with _patch_jwks(keypair):
            assert _validator().validate(token, nonce="different") is None

    def test_nonce_required_but_missing(self, keypair) -> None:
        token = _sign(keypair, _claims())  # no nonce claim
        with _patch_jwks(keypair):
            assert _validator().validate(token, nonce="expected") is None

    def test_kid_not_in_jwks(self, keypair) -> None:
        token = _sign(keypair, _claims(), kid="unknownkid")
        with _patch_jwks(keypair, kid=KID):
            assert _validator().validate(token) is None

    def test_bad_signature(self, keypair) -> None:
        # Sign with a *different* key than the JWKS publishes.
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _sign(other, _claims())
        with _patch_jwks(keypair):
            assert _validator().validate(token) is None

    def test_empty_token(self) -> None:
        assert _validator().validate("") is None

    def test_jwks_unavailable_fails_closed(self, keypair) -> None:
        token = _sign(keypair, _claims())
        resp = MagicMock()
        resp.status_code = 500
        resp.json.return_value = None
        with patch("actingweb.oauth2_jwks.requests.get", return_value=resp):
            assert _validator().validate(token) is None
