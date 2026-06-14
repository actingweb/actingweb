"""Tests for Apple in the LLM-triggered (MCP) OAuth web flow (Phase 6)."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from actingweb import oauth2_apple
from actingweb.aw_web_request import AWWebObj
from actingweb.config import Config
from actingweb.handlers.oauth2_callback import OAuth2AppleCallbackHandler
from actingweb.oauth2 import create_oauth2_authenticator
from actingweb.oauth_state_store import StateNonceStore

SERVICES_ID = "com.example.web"


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


def _make_config(ec_pem: str) -> Config:
    config = MagicMock(spec=Config)
    config.proto = "https://"
    config.fqdn = "test.example.com"
    config.oauth2_provider = "apple"
    config.oauth_providers = {
        "apple": {
            "client_id": SERVICES_ID,
            "apple_team_id": "TEAM",
            "apple_key_id": "KEY",
            "apple_private_key_pem": ec_pem,
            "audiences": [SERVICES_ID],
            "redirect_uri": "https://test.example.com/oauth/callback/apple",
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


def _apple_post(config, form: dict) -> OAuth2AppleCallbackHandler:
    webobj = AWWebObj(
        url="https://test.example.com/oauth/callback/apple",
        params={},
        body=urlencode(form),
        headers={},
        cookies={},
    )
    return OAuth2AppleCallbackHandler(webobj, config, hooks=None)


class TestAppleAuthorizeUrl:
    def test_authorize_url_has_form_post(self, ec_pem: str) -> None:
        config = _make_config(ec_pem)
        auth = create_oauth2_authenticator(config, "apple")
        url = auth.create_authorization_url(state="some-nonce")
        assert "response_mode=form_post" in url


class TestAppleMcpCallbackDispatch:
    def test_mcp_nonce_dispatches_to_mcp_server(self, ec_pem: str) -> None:
        config = _make_config(ec_pem)
        # MCP-bound nonce carries the encrypted MCP state.
        nonce = StateNonceStore(config).create(
            {"provider": "apple", "mcp_state": "encrypted-mcp-state-xyz"}
        )

        fake_server = MagicMock()
        fake_server.handle_oauth_callback.return_value = {
            "action": "redirect",
            "url": "https://client.example/cb?code=mcp-code&state=orig",
        }

        handler = _apple_post(config, {"state": nonce, "code": "apple-code"})
        with patch(
            "actingweb.oauth2_server.oauth2_server.ActingWebOAuth2Server",
            return_value=fake_server,
        ):
            result = handler.post()

        assert result.get("redirect_required") is True
        assert result["redirect_url"].startswith("https://client.example/cb")
        # The MCP server completed the callback with the unwrapped encrypted state.
        fake_server.handle_oauth_callback.assert_called_once()
        call_args = fake_server.handle_oauth_callback.call_args[0][0]
        assert call_args["state"] == "encrypted-mcp-state-xyz"
        assert call_args["code"] == "apple-code"

    def test_spa_nonce_does_not_dispatch_to_mcp(self, ec_pem: str) -> None:
        config = _make_config(ec_pem)
        # SPA-bound nonce (no mcp_state) must NOT reach the MCP server.
        nonce = StateNonceStore(config).create(
            {
                "provider": "apple",
                "spa_mode": True,
                "redirect_url": "https://test.example.com/spa/cb",
            }
        )

        handler = _apple_post(config, {"state": nonce, "code": "apple-code"})
        sentinel = {"sentinel": "spa-path"}
        with (
            patch(
                "actingweb.oauth2_server.oauth2_server.ActingWebOAuth2Server"
            ) as server_cls,
            patch.object(OAuth2AppleCallbackHandler, "get", return_value=sentinel),
        ):
            result = handler.post()

        assert result == sentinel
        server_cls.assert_not_called()
