"""Tests for the MCP OAuth2 server's on-demand authenticator (Phase 6)."""

from collections.abc import Iterator

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from actingweb import oauth2_apple
from actingweb.config import Config
from actingweb.oauth2 import AppleOAuth2Provider, GoogleOAuth2Provider
from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    oauth2_apple._reset_credentials()
    yield
    oauth2_apple._reset_credentials()


def _ec_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")


def _config() -> Config:
    config = Config(fqdn="test.example.com", database="dynamodb")
    providers: dict = {
        "google": {"client_id": "gid", "client_secret": "gsec"},
        "apple": {
            "client_id": "com.example.web",
            "apple_team_id": "TEAM",
            "apple_key_id": "KEY",
            "apple_private_key_pem": _ec_pem(),
            "audiences": ["com.example.web"],
        },
    }
    config.oauth_providers = providers
    return config


class TestLazyAuthenticator:
    def test_caches_per_provider(self) -> None:
        server = ActingWebOAuth2Server(_config())
        a1 = server._get_authenticator("google")
        a2 = server._get_authenticator("google")
        assert a1 is a2

    def test_distinct_per_provider(self) -> None:
        server = ActingWebOAuth2Server(_config())
        g = server._get_authenticator("google")
        a = server._get_authenticator("apple")
        assert g is not a
        assert isinstance(g.provider, GoogleOAuth2Provider)
        assert isinstance(a.provider, AppleOAuth2Provider)

    def test_apple_is_reachable(self) -> None:
        server = ActingWebOAuth2Server(_config())
        apple = server._get_authenticator("apple")
        assert isinstance(apple.provider, AppleOAuth2Provider)
        assert apple.is_enabled() is True

    def test_backward_compat_properties(self) -> None:
        server = ActingWebOAuth2Server(_config())
        assert isinstance(server.google_authenticator.provider, GoogleOAuth2Provider)
        # property returns the cached instance
        assert server.google_authenticator is server._get_authenticator("google")
