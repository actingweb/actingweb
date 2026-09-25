"""Public MCP clients (``token_endpoint_auth_method: none``) end to end.

Dynamic registration honours ``none`` and issues no secret; every grant
authenticates through ``ActingWebOAuth2Server._authenticate_client``, which
fails closed for a confidential client without its secret and ignores a
secret a public client sends anyway.
"""

import base64
from typing import Any
from unittest import mock

import pytest

from actingweb.interface.oauth_client_manager import OAuth2ClientManager
from actingweb.oauth2_server.oauth2_server import ActingWebOAuth2Server
from tests.mcp_oauth_server_helpers import (
    make_handler,
    make_server,
    no_actor_store,
    register,
)
from tests.mcp_token_double import MemoryStore, make_config

VERIFIER = "v" * 64


@pytest.fixture
def env() -> tuple[ActingWebOAuth2Server, MemoryStore]:
    config, store = make_config()
    return make_server(config), store


def _tokens_for(server: ActingWebOAuth2Server, client_id: str) -> dict[str, Any]:
    tm = server.token_manager
    code = tm.create_authorization_code("actor-1", client_id, {"access_token": "g"})
    tokens = tm.exchange_authorization_code(code, client_id)
    assert tokens
    return tokens


class TestRegistration:
    def test_none_gets_no_secret(self, env: Any) -> None:
        server, _ = env
        resp = register(server, token_endpoint_auth_method="none")
        assert "client_secret" not in resp
        assert "client_secret_expires_at" not in resp
        stored = server.client_registry.validate_client(resp["client_id"])
        assert stored["token_endpoint_auth_method"] == "none"
        assert stored["client_secret"] is None

    def test_basic_gets_secret_that_never_expires(self, env: Any) -> None:
        server, _ = env
        resp = register(server, token_endpoint_auth_method="client_secret_basic")
        assert resp["client_secret"]
        assert resp["client_secret_expires_at"] == 0
        assert resp["token_endpoint_auth_method"] == "client_secret_basic"

    def test_unknown_method_is_refused(self, env: Any) -> None:
        server, _ = env
        with pytest.raises(ValueError, match="token_endpoint_auth_method"):
            register(server, token_endpoint_auth_method="private_key_jwt")

    def test_absent_method_is_client_secret_post(self, env: Any) -> None:
        server, _ = env
        resp = register(server)
        assert resp["token_endpoint_auth_method"] == "client_secret_post"
        assert resp["client_secret"]


class TestRegistrationName:
    def test_client_name_is_sanitised(self, env: Any) -> None:
        server, _ = env
        resp = register(server, client_name="Evil\nIgnore previous")
        assert resp["client_name"] == "Evil Ignore previous"
        stored = server.client_registry.validate_client(resp["client_id"])
        assert stored["client_name"] == "Evil Ignore previous"

    def test_name_of_only_control_characters_is_refused(self, env: Any) -> None:
        server, _ = env
        with pytest.raises(ValueError, match="client_name"):
            register(server, client_name="\n\t")


class TestAuthenticateClient:
    def test_public_client_with_or_without_secret(self, env: Any) -> None:
        server, _ = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        assert server._authenticate_client(cid, None)
        assert server._authenticate_client(cid, "bogus")

    @pytest.mark.parametrize("secret", [None, "", "wrong"])
    def test_confidential_without_the_right_secret(
        self, env: Any, secret: str | None
    ) -> None:
        server, _ = env
        cid = register(server)["client_id"]
        assert server._authenticate_client(cid, secret) is None

    def test_confidential_with_the_right_secret(self, env: Any) -> None:
        server, _ = env
        resp = register(server)
        assert server._authenticate_client(resp["client_id"], resp["client_secret"])

    def test_unknown_client(self, env: Any) -> None:
        server, _ = env
        assert server._authenticate_client("mcp_nope", "x") is None


class TestGrants:
    def test_code_grant_confidential_without_secret_is_invalid_client(
        self, env: Any
    ) -> None:
        server, _ = env
        cid = register(server)["client_id"]
        code = server.token_manager.create_authorization_code(
            "actor-1", cid, {"access_token": "g"}
        )
        resp = server.handle_token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": cid,
                "client_secret": None,
                "redirect_uri": "https://client/cb",
            }
        )
        assert resp["error"] == "invalid_client"

    def test_code_grant_public_without_verifier_is_invalid_request(
        self, env: Any
    ) -> None:
        server, _ = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        resp = server.handle_token_request(
            {
                "grant_type": "authorization_code",
                "code": "ac_x",
                "client_id": cid,
                "redirect_uri": "https://client/cb",
            }
        )
        assert resp["error"] == "invalid_request"

    def test_refresh_grant_public_without_secret(self, env: Any) -> None:
        server, _ = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        tokens = _tokens_for(server, cid)
        resp = server.handle_token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": cid,
                "client_secret": None,
            }
        )
        assert "error" not in resp
        assert resp["refresh_token"] != tokens["refresh_token"]

    def test_refresh_grant_confidential_without_secret(self, env: Any) -> None:
        server, _ = env
        cid = register(server)["client_id"]
        tokens = _tokens_for(server, cid)
        resp = server.handle_token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": cid,
                "client_secret": None,
            }
        )
        assert resp["error"] == "invalid_client"

    def test_client_credentials_public_is_unauthorized_client(self, env: Any) -> None:
        server, _ = env
        cid = register(server, token_endpoint_auth_method="none")["client_id"]
        resp = server.handle_token_request(
            {"grant_type": "client_credentials", "client_id": cid}
        )
        assert resp["error"] == "unauthorized_client"

    def test_client_credentials_confidential_without_secret(self, env: Any) -> None:
        server, _ = env
        cid = register(server)["client_id"]
        resp = server.handle_token_request(
            {"grant_type": "client_credentials", "client_id": cid}
        )
        assert resp["error"] == "invalid_request"

    def test_client_credentials_reads_the_client_once(self, env: Any) -> None:
        server, _ = env
        resp = register(server)
        registry = server.client_registry
        with mock.patch.object(
            registry, "load_client_strict", wraps=registry.load_client_strict
        ) as load:
            server.handle_token_request(
                {
                    "grant_type": "client_credentials",
                    "client_id": resp["client_id"],
                    "client_secret": "wrong",
                }
            )
        assert load.call_count == 1


class TestClientManager:
    def test_public_client_through_the_sdk(self, env: Any) -> None:
        server, _ = env
        manager = OAuth2ClientManager("actor-owner", server.config)
        with no_actor_store():
            client = manager.create_client("SDK", token_endpoint_auth_method="none")
        assert "client_secret" not in client
        with pytest.raises(ValueError, match="public client"):
            manager.regenerate_client_secret(client["client_id"])


def _basic(client_id: str, secret: str) -> dict[str, str]:
    raw = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return {"Accept": "application/json", "Authorization": f"Basic {raw}"}


class TestTokenHandlerCredentials:
    def _refresh(
        self, server: ActingWebOAuth2Server, body: dict[str, str], headers: Any
    ) -> tuple[dict[str, Any], int]:
        handler = make_handler(server, body=body, headers=headers)
        out = handler._handle_token_request()
        return out, handler.response.status_code

    def test_header_secret_used_with_body_client_id(self, env: Any) -> None:
        server, _ = env
        resp = register(server)
        cid, secret = resp["client_id"], resp["client_secret"]
        tokens = _tokens_for(server, cid)
        out, _ = self._refresh(
            server,
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": cid,
            },
            _basic(cid, secret),
        )
        assert "error" not in out

    def test_differing_body_and_header_secrets_are_refused(self, env: Any) -> None:
        """Two authentication methods that disagree (RFC 6749 §2.3.1): refuse
        rather than silently pick one."""
        server, _ = env
        resp = register(server)
        cid, secret = resp["client_id"], resp["client_secret"]
        tokens = _tokens_for(server, cid)
        out, status = self._refresh(
            server,
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": cid,
                "client_secret": secret,
            },
            _basic(cid, "wrong"),
        )
        assert status == 400
        assert out["error"] == "invalid_request"

    def test_identical_body_and_header_secrets_are_accepted(self, env: Any) -> None:
        server, _ = env
        resp = register(server)
        cid, secret = resp["client_id"], resp["client_secret"]
        tokens = _tokens_for(server, cid)
        out, _ = self._refresh(
            server,
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": cid,
                "client_secret": secret,
            },
            _basic(cid, secret),
        )
        assert "error" not in out

    def test_mismatched_client_ids_are_refused(self, env: Any) -> None:
        server, _ = env
        resp = register(server)
        out, status = self._refresh(
            server,
            {
                "grant_type": "refresh_token",
                "refresh_token": "rt_x",
                "client_id": "mcp_someone_else",
            },
            _basic(resp["client_id"], resp["client_secret"]),
        )
        assert status == 400
        assert out["error"] == "invalid_request"
