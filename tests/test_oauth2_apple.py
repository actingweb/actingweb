"""Tests for Apple client_secret JWT generation and key loading."""

import time
from collections.abc import Iterator

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from actingweb import oauth2_apple

TEAM_ID = "TEAMID1234"
KEY_ID = "KEYID56789"
CLIENT_ID = "com.example.web"


@pytest.fixture()
def ec_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    oauth2_apple._reset_credentials()
    yield
    oauth2_apple._reset_credentials()


class TestMakeAppleClientSecret:
    def test_signs_valid_es256(self, ec_pem: str) -> None:
        now = int(time.time())
        token = oauth2_apple.make_apple_client_secret(
            TEAM_ID, KEY_ID, CLIENT_ID, ec_pem, now=now
        )
        # Decode + verify against the public key.
        priv = serialization.load_pem_private_key(ec_pem.encode(), password=None)
        pub = priv.public_key()
        claims = jwt.decode(
            token,
            pub,  # type: ignore[arg-type]
            algorithms=["ES256"],
            audience=oauth2_apple.APPLE_AUDIENCE,
        )
        assert claims["iss"] == TEAM_ID
        assert claims["sub"] == CLIENT_ID
        assert claims["aud"] == oauth2_apple.APPLE_AUDIENCE
        assert claims["exp"] > claims["iat"]

    def test_header_has_kid(self, ec_pem: str) -> None:
        token = oauth2_apple.make_apple_client_secret(
            TEAM_ID, KEY_ID, CLIENT_ID, ec_pem, now=int(time.time())
        )
        header = jwt.get_unverified_header(token)
        assert header["kid"] == KEY_ID
        assert header["alg"] == "ES256"


class TestCachedClientSecret:
    def test_same_value_within_bucket(self, ec_pem: str) -> None:
        oauth2_apple.register_apple_credentials(
            "apple",
            team_id=TEAM_ID,
            key_id=KEY_ID,
            client_id=CLIENT_ID,
            private_key_pem=ec_pem,
        )
        a = oauth2_apple.get_client_secret("apple")
        b = oauth2_apple.get_client_secret("apple")
        assert a == b

    def test_new_value_after_bucket_roll(self, ec_pem: str) -> None:
        oauth2_apple.register_apple_credentials(
            "apple",
            team_id=TEAM_ID,
            key_id=KEY_ID,
            client_id=CLIENT_ID,
            private_key_pem=ec_pem,
        )
        bucket = int(time.time() // 300)
        v1 = oauth2_apple._cached_client_secret(bucket, "apple")
        v2 = oauth2_apple._cached_client_secret(bucket + 1, "apple")
        # Different buckets -> independently signed (iat differs) -> distinct.
        assert v1 != v2

    def test_unregistered_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="No Apple credentials"):
            oauth2_apple._cached_client_secret(int(time.time() // 300), "apple-mobile")


class TestLoadPrivateKeyPem:
    def test_accepts_pem_string(self, ec_pem: str) -> None:
        result = oauth2_apple.load_private_key_pem({"apple_private_key_pem": ec_pem})
        assert "PRIVATE KEY" in result

    def test_accepts_file_path(self, ec_pem: str, tmp_path) -> None:
        p = tmp_path / "AuthKey.p8"
        p.write_text(ec_pem)
        result = oauth2_apple.load_private_key_pem({"apple_private_key_path": str(p)})
        assert "PRIVATE KEY" in result

    def test_file_precedence_over_pem(self, ec_pem: str, tmp_path) -> None:
        # Build a second, distinct key to write to file.
        file_key = ec.generate_private_key(ec.SECP256R1())
        file_pem = file_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("utf-8")
        p = tmp_path / "AuthKey.p8"
        p.write_text(file_pem)
        result = oauth2_apple.load_private_key_pem(
            {"apple_private_key_path": str(p), "apple_private_key_pem": ec_pem}
        )
        assert result.strip() == file_pem.strip()

    def test_missing_file_raises_with_path(self) -> None:
        with pytest.raises(ValueError, match="/nonexistent/AuthKey.p8"):
            oauth2_apple.load_private_key_pem(
                {"apple_private_key_path": "/nonexistent/AuthKey.p8"}
            )

    def test_invalid_pem_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid PEM key"):
            oauth2_apple.load_private_key_pem(
                {
                    "apple_private_key_pem": "-----BEGIN PRIVATE KEY-----\ngarbage\n-----END PRIVATE KEY-----"
                }
            )

    def test_no_key_provided_raises(self) -> None:
        with pytest.raises(ValueError, match="Apple private key not provided"):
            oauth2_apple.load_private_key_pem({})

    def test_rejects_rsa_key(self) -> None:
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("utf-8")
        with pytest.raises(ValueError, match="not an EC"):
            oauth2_apple.load_private_key_pem({"apple_private_key_pem": rsa_pem})

    def test_literal_newline_conversion(self, ec_pem: str) -> None:
        escaped = ec_pem.replace("\n", "\\n")
        result = oauth2_apple.load_private_key_pem({"apple_private_key_pem": escaped})
        assert "PRIVATE KEY" in result
