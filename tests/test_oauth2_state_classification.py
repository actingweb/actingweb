"""``_looks_like_encrypted_state`` requires the whole state to be base64-safe."""

from actingweb.config import Config
from actingweb.oauth2 import GoogleOAuth2Provider, OAuth2Authenticator


def _authenticator() -> OAuth2Authenticator:
    config = Config(fqdn="test.example.com", database="dynamodb")
    config.oauth = {"client_id": "cid", "client_secret": "csec"}
    return OAuth2Authenticator(config, GoogleOAuth2Provider(config))


def test_long_base64_state_is_encrypted_shape() -> None:
    assert _authenticator()._looks_like_encrypted_state("A" * 60) is True


def test_trailing_newline_is_not_encrypted_shape() -> None:
    assert _authenticator()._looks_like_encrypted_state("A" * 60 + "\n") is False
